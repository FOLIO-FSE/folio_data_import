import asyncio
import datetime
import glob
import io
import json
import logging
import math
import os
import sys
import uuid
from contextlib import ExitStack
from datetime import datetime as dt
from functools import cached_property
from pathlib import Path
from time import sleep
from typing import Annotated, BinaryIO, Callable, Dict, Generator, List, cast

import cyclopts
import folioclient
import httpx
import pymarc
import questionary
import tabulate
from humps import decamelize
from pydantic import BaseModel, Field
from rich.logging import RichHandler

from folio_data_import import __version__ as app_version
from folio_data_import import get_folio_connection_parameters
from folio_data_import._progress import (
    NoOpProgressReporter,
    ProgressReporter,
    RichProgressReporter,
)
from folio_data_import.custom_exceptions import (
    FolioDataImportBatchError,
    FolioDataImportJobError,
)
from folio_data_import.marc_preprocessors._preprocessors import MARCPreprocessor

try:
    datetime_utc = datetime.UTC
except AttributeError:
    datetime_utc = datetime.timezone.utc


# The order in which the report summary should be displayed
REPORT_SUMMARY_ORDERING = {"created": 0, "updated": 1, "discarded": 2, "error": 3}

# Set default timeout and backoff values for HTTP requests when retrying job status and final summary checks # noqa: E501
RETRY_TIMEOUT_START = 5
RETRY_TIMEOUT_RETRY_FACTOR = 1.5
RETRY_TIMEOUT_MAX = 25.32

# Custom log level for data issues, set to 26
DATA_ISSUE_LVL_NUM = 26
logging.addLevelName(DATA_ISSUE_LVL_NUM, "DATA_ISSUES")


class MARCImportStats(BaseModel):
    """Statistics for MARC import operations."""

    records_sent: int = 0
    records_processed: int = 0
    created: int = 0
    updated: int = 0
    discarded: int = 0
    error: int = 0


class CustomLogger(logging.Logger):
    """Logger subclass with custom data_issues method."""

    def data_issues(self, msg: str, *args, **kws) -> None:
        """Log data issues at custom level (26)."""
        if self.isEnabledFor(DATA_ISSUE_LVL_NUM):
            self._log(DATA_ISSUE_LVL_NUM, msg, args, **kws)


# Set the custom logger class as the default
logging.setLoggerClass(CustomLogger)

logger: CustomLogger = logging.getLogger(__name__)  # type: ignore[assignment]


class MARCImportJob:
    """
    Class to manage importing MARC data (Bib, Authority) into FOLIO using the Change Manager
    APIs (https://github.com/folio-org/mod-source-record-manager/tree/master?tab=readme-ov-file#data-import-workflow),
    rather than file-based Data Import. When executed in an interactive environment, it can provide progress bars
    for tracking the number of records both uploaded and processed.

    Args:
        folio_client (FolioClient): An instance of the FolioClient class.
        marc_files (list): A list of Path objects representing the MARC files to import.
        import_profile_name (str): The name of the data import job profile to use.
        batch_size (int): The number of source records to include in a record batch (default=10).
        batch_delay (float): The number of seconds to wait between record batches (default=0).
        no_progress (bool): Disable progress bars (eg. for running in a CI environment).
        marc_record_preprocessors (list or str): A list of callables, or a string representing
            a comma-separated list of MARC record preprocessor names to apply to each record before import.
        preprocessor_args (dict): A dictionary of arguments to pass to the MARC record preprocessor(s).
        let_summary_fail (bool): If True, will not retry or fail the import if the final job summary
            cannot be retrieved (default=False).
        split_files (bool): If True, will split each file into smaller jobs of size `split_size`
        split_size (int): The number of records to include in each split file (default=1000).
        split_offset (int): The number of split files to skip before starting processing (default=0).
        job_ids_file_path (str): The path to the file where job IDs will be saved (default="marc_import_job_ids.txt").
        show_file_names_in_data_import_logs (bool): If True, will set the file name for each job in the data import logs.
    """  # noqa: E501

    class Config(BaseModel):
        """Configuration for MARC import operations."""

        marc_files: Annotated[
            List[Path],
            Field(
                title="MARC files",
                description="List of Path objects representing the MARC files to import",
            ),
        ]
        import_profile_name: Annotated[
            str,
            Field(
                title="Import profile name",
                description="The name of the data import job profile to use",
            ),
        ]
        batch_size: Annotated[
            int,
            Field(
                title="Batch size",
                description="Number of source records to include in a record batch",
                ge=1,
                le=1000,
            ),
        ] = 10
        batch_delay: Annotated[
            float,
            Field(
                title="Batch delay",
                description="Number of seconds to wait between record batches",
                ge=0.0,
            ),
        ] = 0.0
        marc_record_preprocessors: Annotated[
            List[Callable] | str | None,
            Field(
                title="MARC record preprocessor",
                description=(
                    "List of callables or string representing preprocessor(s) "
                    "to apply to each record before import"
                ),
            ),
        ] = None
        preprocessors_args: Annotated[
            Dict[str, Dict] | None,
            Field(
                title="Preprocessor arguments",
                description="Dictionary of arguments to pass to the MARC record preprocessor(s)",
            ),
        ] = None
        no_progress: Annotated[
            bool,
            Field(
                title="No progress bars",
                description="Disable progress bars (e.g., for CI environments)",
            ),
        ] = False
        no_summary: Annotated[
            bool,
            Field(
                title="No summary",
                description="Skip the final job summary",
            ),
        ] = False
        let_summary_fail: Annotated[
            bool,
            Field(
                title="Let summary fail",
                description="Do not retry or fail import if final job summary cannot be retrieved",
            ),
        ] = False
        split_files: Annotated[
            bool,
            Field(
                title="Split files",
                description="Split each file into smaller jobs",
            ),
        ] = False
        split_size: Annotated[
            int,
            Field(
                title="Split size",
                description="Number of records to include in each split file",
                ge=1,
            ),
        ] = 1000
        split_offset: Annotated[
            int,
            Field(
                title="Split offset",
                description="Number of split files to skip before starting processing",
                ge=0,
            ),
        ] = 0
        job_ids_file_path: Annotated[
            Path | None,
            Field(
                title="Job IDs file path",
                description="Path to file where job IDs will be saved",
            ),
        ] = None
        show_file_names_in_data_import_logs: Annotated[
            bool,
            Field(
                title="Show file names in DI logs",
                description="Show file names in data import logs",
            ),
        ] = False

    bad_records_file: BinaryIO
    failed_batches_file: BinaryIO
    job_id: str
    reporter: ProgressReporter
    task_sent: str
    task_imported: str
    http_client: httpx.Client
    current_file: List[Path] | List[BinaryIO]
    record_batch: List[bytes]
    last_current: int = 0
    total_records_sent: int = 0
    finished: bool = False
    job_id: str = ""
    job_ids: List[str]
    job_hrid: int = 0
    _max_summary_retries: int = 2
    _max_job_retries: int = 2
    _job_retries: int = 0
    _summary_retries: int = 0

    def __init__(
        self,
        folio_client: folioclient.FolioClient,
        config: "MARCImportJob.Config",
        reporter: ProgressReporter | None = None,
    ) -> None:
        self.folio_client: folioclient.FolioClient = folio_client
        self.config = config
        self.reporter = reporter or NoOpProgressReporter()
        self.current_retry_timeout: float | None = None
        self.marc_record_preprocessor: MARCPreprocessor = MARCPreprocessor(
            config.marc_record_preprocessors or "", **(config.preprocessors_args or {})
        )
        self.job_ids_file_path = config.job_ids_file_path or config.marc_files[0].parent.joinpath(
            "marc_import_job_ids.txt"
        )

    async def do_work(self) -> None:
        """
        Performs the necessary work for data import.

        This method initializes an HTTP client, files to store records that fail to send,
        and calls the appropriate method to import MARC files based on the configuration.

        Returns:
            None
        """
        self.record_batch = []
        self.job_ids = []
        with (
            self.folio_client.get_folio_http_client() as http_client,
            open(
                self.config.marc_files[0].parent.joinpath(
                    f"bad_marc_records_{dt.now(tz=datetime_utc).strftime('%Y%m%d%H%M%S')}.mrc"
                ),
                "wb+",
            ) as bad_marc_file,
            open(
                self.config.marc_files[0].parent.joinpath(
                    f"failed_batches_{dt.now(tz=datetime_utc).strftime('%Y%m%d%H%M%S')}.mrc"
                ),
                "wb+",
            ) as failed_batches,
        ):
            self.bad_records_file = bad_marc_file
            logger.info(f"Writing bad records to {self.bad_records_file.name}")
            self.failed_batches_file = failed_batches
            logger.info(f"Writing failed batches to {self.failed_batches_file.name}")
            self.http_client = http_client
            if self.config.split_files:
                await self.process_split_files()
            else:
                for file in self.config.marc_files:
                    self.current_file = [file]
                    await self.import_marc_file()

    async def process_split_files(self):
        """
        Process the import of files in smaller batches.
        This method is called when `split_files` is set to True.
        It splits each file into smaller chunks and processes them one by one.
        """
        for file in self.config.marc_files:
            with open(file, "rb") as f:
                file_length = await self.read_total_records([f])
            expected_batches = math.ceil(file_length / self.config.split_size)
            logger.info(
                f"{file.name} contains {file_length} records."
                f" Splitting into {expected_batches} {self.config.split_size} record batches."
            )
            zero_pad_parts = len(str(expected_batches)) if expected_batches > 1 else 2
            for idx, batch in enumerate(
                self.split_marc_file(file, self.config.split_size), start=1
            ):
                if idx > self.config.split_offset:
                    batch.name = f"{file.name} (Part {idx:0{zero_pad_parts}})"
                    self.current_file = [batch]
                    await self.import_marc_file()
            self.move_file_to_complete(file)

    @staticmethod
    def _remove_if_empty(file_path: Path | str, message: str | None = None) -> None:
        """
        Remove a file if it's empty.

        Args:
            file_path: Path to the file to check and potentially remove.
            message: Optional custom log message to use when file is removed.
        """
        file_path = Path(file_path) if isinstance(file_path, str) else file_path
        try:
            if file_path.stat().st_size == 0:
                file_path.unlink(missing_ok=True)
                if message:
                    logger.info(message)
                else:
                    logger.info(f"Removed empty file: {file_path.name}")
        except FileNotFoundError:
            # File doesn't exist, nothing to do
            pass

    async def wrap_up(self) -> None:
        """
        Wraps up the data import process.

        This method is called after the import process is complete.
        It checks for empty bad records and error files and removes them.

        Returns:
            None
        """
        # Check and remove empty files if necessary
        self._remove_if_empty(
            self.bad_records_file.name, "No bad records found. Removing bad records file."
        )
        self._remove_if_empty(
            self.failed_batches_file.name, "No failed batches. Removing failed batches file."
        )

        with open(self.job_ids_file_path, "a+") as job_ids_file:
            logger.info(f"Writing job IDs to {self.job_ids_file_path}")
            for job_id in self.job_ids:
                job_ids_file.write(f"{job_id}\n")
        self._remove_if_empty(
            self.job_ids_file_path, "No job IDs to write. Removing job IDs file."
        )
        logger.info("Import complete.")
        logger.info(f"Total records imported: {self.total_records_sent}")

    async def get_job_status(self) -> None:
        """
        Retrieves the status of a job execution.

        Returns:
            None

        Raises:
            IndexError: If the job execution with the specified ID is not found.
        """
        job_status: Dict | None = None
        try:
            self.current_retry_timeout = (
                (self.current_retry_timeout * RETRY_TIMEOUT_RETRY_FACTOR)
                if self.current_retry_timeout
                else RETRY_TIMEOUT_START
            )
            with self.folio_client.get_folio_http_client() as temp_client:
                temp_client.timeout = self.current_retry_timeout
                self.folio_client.httpx_client = temp_client
                job_status = self.folio_client.folio_get(
                    "/metadata-provider/jobExecutions?statusNot=DISCARDED&uiStatusAny"
                    "=PREPARING_FOR_PREVIEW&uiStatusAny=READY_FOR_PREVIEW&uiStatusAny=RUNNING&limit=50"
                )
                self.current_retry_timeout = None
        except (folioclient.FolioConnectionError, folioclient.FolioHTTPError) as e:
            error_text = e.response.text if hasattr(e, "response") else str(e)

            # Raise non-retriable HTTP errors immediately
            if hasattr(e, "response") and e.response.status_code not in [502, 504, 401]:
                raise e

            # For retriable errors or connection errors
            if (
                self.current_retry_timeout is not None
                and self.current_retry_timeout <= RETRY_TIMEOUT_MAX
            ):
                logger.warning(f"SERVER ERROR fetching job status: {error_text}. Retrying.")
                sleep(0.25)
                return await self.get_job_status()
            elif (
                self.current_retry_timeout is not None
                and self.current_retry_timeout > RETRY_TIMEOUT_MAX
            ):
                logger.critical(
                    f"SERVER ERROR fetching job status: {error_text}. Max retries exceeded."
                )
                raise FolioDataImportJobError(self.job_id, error_text, e) from e
            else:
                raise e
        except Exception as e:
            logger.error(f"Error fetching job status. {e}")

        if job_status is None:
            return

        try:
            status = [job for job in job_status["jobExecutions"] if job["id"] == self.job_id][0]
            self.reporter.update_task(
                self.task_imported,
                advance=status["progress"]["current"] - self.last_current,
            )
            self.last_current = status["progress"]["current"]
        except (IndexError, ValueError, KeyError):
            logger.debug(f"No active job found with ID {self.job_id}. Checking for finished job.")
            try:
                job_status = self.folio_client.folio_get(
                    "/metadata-provider/jobExecutions?limit=100&sortBy=completed_date%2Cdesc&statusAny"
                    "=COMMITTED&statusAny=ERROR&statusAny=CANCELLED"
                )
                status = [job for job in job_status["jobExecutions"] if job["id"] == self.job_id][
                    0
                ]
                self.reporter.update_task(
                    self.task_imported,
                    advance=status["progress"]["current"] - self.last_current,
                )
                self.last_current = status["progress"]["current"]
                self.finished = True
            except (folioclient.FolioConnectionError, folioclient.FolioHTTPError) as e:
                # Raise non-retriable HTTP errors immediately
                if hasattr(e, "response") and e.response.status_code not in [502, 504]:
                    raise e

                # Retry retriable errors or connection errors
                error_text = e.response.text if hasattr(e, "response") else str(e)
                logger.warning(f"SERVER ERROR fetching job status: {error_text}. Retrying.")
                sleep(0.25)
                with self.folio_client.get_folio_http_client() as temp_client:
                    temp_client.timeout = self.current_retry_timeout
                    self.folio_client.httpx_client = temp_client
                    return await self.get_job_status()

    async def set_job_file_name(self) -> None:
        """
        Sets the file name for the current job execution.

        Returns:
            None
        """
        try:
            job_object = self.http_client.get(
                "/change-manager/jobExecutions/" + self.job_id,
            )
            job_object.raise_for_status()
            job_object_json = job_object.json()
            job_object_json.update({"fileName": self.current_file[0].name})
            set_file_name = self.http_client.put(
                "/change-manager/jobExecutions/" + self.job_id,
                json=job_object_json,
            )
            set_file_name.raise_for_status()
        except httpx.HTTPError as e:
            logger.error(
                "Error setting job file name: "
                + str(e)
                + "\n"
                + getattr(getattr(e, "response", ""), "text", "")
            )
            raise e

    async def create_folio_import_job(self) -> None:
        """
        Creates a job execution for importing data into FOLIO.

        Returns:
            None

        Raises:
            FolioHTTPError: If there is an error creating the job.
        """
        try:
            job_response = self.folio_client.folio_post(
                "/change-manager/jobExecutions",
                {"sourceType": "ONLINE", "userId": self.folio_client.current_user},
            )
        except (folioclient.FolioConnectionError, folioclient.FolioHTTPError) as e:
            # Raise non-retriable HTTP errors immediately
            if hasattr(e, "response") and e.response.status_code not in [502, 504]:
                raise e

            # Retry retriable errors or connection errors
            error_text = e.response.text if hasattr(e, "response") else str(e)
            logger.warning(f"SERVER ERROR creating job: {error_text}. Retrying.")
            sleep(0.25)
            return await self.create_folio_import_job()

        try:
            self.job_id = job_response["parentJobExecutionId"]
        except (KeyError, TypeError) as e:
            logger.error(
                f"Invalid job response from FOLIO API. Expected 'parentJobExecutionId' key. "
                f"Response: {job_response}"
            )
            raise ValueError(f"FOLIO API returned invalid job response: {job_response}") from e

        if self.config.show_file_names_in_data_import_logs:
            await self.set_job_file_name()
        self.job_ids.append(self.job_id)
        logger.info(f"Created job: {self.job_id}")

    @cached_property
    def import_profile(self) -> dict:
        """
        Returns the import profile for the current job execution.

        Returns:
            dict: The import profile for the current job execution.
        """
        import_profiles = self.folio_client.folio_get(
            "/data-import-profiles/jobProfiles",
            "jobProfiles",
            query_params={"limit": "1000"},
        )
        profile = [
            profile
            for profile in import_profiles
            if profile["name"] == self.config.import_profile_name
        ][0]
        return profile

    async def set_job_profile(self) -> None:
        """
        Sets the job profile for the current job execution.

        Returns:
            The response from the HTTP request to set the job profile.
        """
        logger.info(
            f"Setting job profile: {self.import_profile['name']} ({self.import_profile['id']})"
            f" for job {self.job_id}"
        )
        set_job_profile = self.http_client.put(
            "/change-manager/jobExecutions/" + self.job_id + "/jobProfile",
            json={
                "id": self.import_profile["id"],
                "name": self.import_profile["name"],
                "dataType": "MARC",
            },
        )
        try:
            set_job_profile.raise_for_status()
            self.job_hrid = set_job_profile.json()["hrId"]
            logger.info(f"Job HRID: {self.job_hrid}")
        except httpx.HTTPError as e:
            logger.error(
                "Error creating job: "
                + str(e)
                + "\n"
                + getattr(getattr(e, "response", ""), "text", "")
            )
            raise e

    @staticmethod
    async def _count_records(files: List[BinaryIO]) -> int:
        """
        Internal method to count total number of records from files.

        Args:
            files (list): List of files to read.

        Returns:
            int: The total number of records found in the files.
        """
        total_records = 0
        for import_file in files:
            while True:
                chunk = import_file.read(104857600)
                if not chunk:
                    break
                total_records += chunk.count(b"\x1d")
            import_file.seek(0)
        return total_records

    @staticmethod
    async def read_total_records(files: List[BinaryIO]) -> int:
        """
        Count records from files with per-file logging.

        Args:
            files (list): List of files to read.

        Returns:
            int: The total number of records found in the files.
        """
        total_records = 0
        for import_file in files:
            file_name = os.path.basename(import_file.name)
            logger.info(f"Counting records in {file_name}...")
            file_record_count = await MARCImportJob._count_records([import_file])
            total_records += file_record_count
            logger.info(f"Counted {file_record_count} records in {file_name}")
        return total_records

    async def process_record_batch(self, batch_payload) -> None:
        """
        Processes a record batch.

        Args:
            batch_payload (dict): A records payload containing the current batch of MARC records.
        """
        try:
            post_batch = self.http_client.post(
                "/change-manager/jobExecutions/" + self.job_id + "/records",
                json=batch_payload,
            )
        except (httpx.ConnectTimeout, httpx.ReadTimeout):
            logger.warning(f"CONNECTION ERROR posting batch {batch_payload['id']}. Retrying...")
            sleep(0.25)
            return await self.process_record_batch(batch_payload)
        try:
            post_batch.raise_for_status()
            self.total_records_sent += len(self.record_batch)
            self.record_batch = []
            self.reporter.update_task(self.task_sent, advance=len(batch_payload["initialRecords"]))
        except httpx.HTTPStatusError as e:
            if e.response.status_code in [
                500,
                400,
                422,
            ]:  # TODO: Update once we no longer have to support < Sunflower to just be 400
                self.total_records_sent += len(self.record_batch)
                self.record_batch = []
                self.reporter.update_task(
                    self.task_sent, advance=len(batch_payload["initialRecords"])
                )
            else:
                for record in self.record_batch:
                    self.failed_batches_file.write(record)
                raise FolioDataImportBatchError(
                    batch_payload["id"], f"{e}\n{e.response.text}", e
                ) from e
        await self.get_job_status()
        sleep(self.config.batch_delay)

    async def process_records(self, files, total_records: int) -> None:
        """
        Process records from the given files.

        Args:
            files (list): List of files to process.
            total_records (int): Total number of records to process.
            pbar_sent: Progress bar for tracking the number of records sent.

        Returns:
            None
        """
        counter = 0
        for import_file in files:
            file_path = Path(import_file.name)
            self.reporter.update_task(
                self.task_sent,
                description=f"Sent ({os.path.basename(import_file.name)})",
            )
            reader = pymarc.MARCReader(import_file, hide_utf8_warnings=True)
            for idx, record in enumerate(reader, start=1):
                if len(self.record_batch) == self.config.batch_size:
                    await self.process_record_batch(
                        await self.create_batch_payload(
                            counter,
                            total_records,
                            counter == total_records,
                        ),
                    )
                    sleep(0.25)
                if record:
                    record = self.marc_record_preprocessor.do_work(record)
                    self.record_batch.append(record.as_marc())
                    counter += 1
                else:
                    logger.data_issues(
                        "RECORD FAILED\t%s\t%s\t%s",
                        f"{file_path.name}:{idx}",
                        f"Error reading {idx} record from {file_path}. Skipping."
                        f" Writing current chunk to {self.bad_records_file.name}.",
                        "",
                    )
                    if reader.current_chunk:
                        self.bad_records_file.write(reader.current_chunk)
            if not self.config.split_files:
                # Close this file handle so Windows releases the lock, then move
                import_file.close()
                self.move_file_to_complete(file_path)
        if self.record_batch or not self.finished:
            await self.process_record_batch(
                await self.create_batch_payload(
                    counter,
                    total_records,
                    counter == total_records,
                ),
            )

    def move_file_to_complete(self, file_path: Path) -> None:
        import_complete_path = file_path.parent.joinpath("import_complete")
        if not import_complete_path.exists():
            logger.debug(f"Creating import_complete directory: {import_complete_path.absolute()}")
            import_complete_path.mkdir(exist_ok=True)
        logger.debug(f"Moving {file_path} to {import_complete_path.absolute()}")
        file_path.rename(file_path.parent.joinpath("import_complete", file_path.name))

    async def create_batch_payload(self, counter: int, total_records, is_last: bool) -> dict:
        """
        Create a batch payload for data import.

        Args:
            counter (int): The current counter value.
            total_records (int): The total number of records.
            is_last (bool): Indicates if this is the last batch.

        Returns:
            dict: The batch payload containing the ID, records metadata, and initial records.
        """
        return {
            "id": str(uuid.uuid4()),
            "recordsMetadata": {
                "last": is_last,
                "counter": counter,
                "contentType": "MARC_RAW",
                "total": total_records,
            },
            "initialRecords": [{"record": x.decode()} for x in self.record_batch],
        }

    @staticmethod
    def split_marc_file(file_path: Path, batch_size: int) -> Generator[io.BytesIO, None, None]:
        """Generator to iterate over MARC records in batches, yielding BytesIO objects."""
        with open(file_path, "rb") as f:
            batch = io.BytesIO()
            count = 0

            while True:
                leader = f.read(24)
                if not leader:
                    break  # End of file

                try:
                    record_length = int(leader[:5])  # Extract record length from leader
                except ValueError as ve:
                    raise ValueError("Invalid MARC record length encountered.") from ve

                record_body = f.read(record_length - 24)
                if len(record_body) != record_length - 24:
                    raise ValueError("Unexpected end of file while reading MARC record.")

                # Verify record terminator
                if record_body[-1:] != b"\x1d":
                    raise ValueError(
                        "MARC record does not end with the expected terminator (0x1D)."
                    )

                # Write the full record to the batch buffer
                batch.write(leader + record_body)
                count += 1

                if count >= batch_size:
                    batch.seek(0)
                    yield batch
                    batch = io.BytesIO()  # Reset buffer
                    count = 0

            # Yield any remaining records
            if count > 0:
                batch.seek(0)
                yield batch

    async def import_marc_file(self) -> None:
        """
        Imports MARC file into the system.

        This method performs the following steps:
        1. Creates a FOLIO import job.
        2. Retrieves the import profile.
        3. Sets the job profile.
        4. Opens the MARC file(s) and reads the total number of records.
        5. Displays progress bars for imported and sent records.
        6. Processes the records and updates the progress bars.
        7. Checks the job status periodically until the import is finished.

        Note: This method assumes that the necessary instance attributes are already set.

        Returns:
            None
        """
        await self.create_folio_import_job()
        await self.set_job_profile()
        with ExitStack() as stack:
            files: List[BinaryIO]
            try:
                if isinstance(self.current_file[0], Path):
                    path_list = cast(List[Path], self.current_file)
                    files = [stack.enter_context(open(file, "rb")) for file in path_list]
                elif isinstance(self.current_file[0], io.BytesIO):
                    bytesio_list = cast(List[io.BytesIO], self.current_file)
                    files = [stack.enter_context(file) for file in bytesio_list]
                else:
                    raise ValueError("Invalid file type. Must be Path or BytesIO.")
            except IndexError as e:
                logger.error(f"Error opening file: {e}")
                raise e

            total_records = await self._count_records(files)

            with self.reporter:
                try:
                    self.task_sent = self.reporter.start_task(
                        "sent", total=total_records, description="Sent"
                    )
                    self.task_imported = self.reporter.start_task(
                        f"imported_{self.job_hrid}",
                        total=total_records,
                        description=f"Imported ({self.job_hrid})",
                    )
                    await self.process_records(files, total_records)
                    while not self.finished:
                        await self.get_job_status()
                except FolioDataImportBatchError as e:
                    logger.error(f"Unhandled error posting batch {e.batch_id}: {e.message}")
                    await self.cancel_job()
                    raise e
                except FolioDataImportJobError as e:
                    await self.cancel_job()
                    if self._job_retries < self._max_job_retries:
                        self._job_retries += 1
                        logger.error(
                            f"Unhandled error processing job {e.job_id}: {e.message},"
                            f" cancelling and retrying."
                        )
                        await self.import_marc_file()
                    else:
                        logger.critical(
                            f"Unhandled error processing job {e.job_id}: {e.message},"
                            f" cancelling and exiting (maximum retries reached)."
                        )
                        raise e
            if self.finished and not self.config.no_summary:
                await asyncio.sleep(5)
                await self.log_job_summary()
            elif self.finished:
                logger.info("Skipping final job summary.")
            self.last_current = 0
            self.finished = False

    async def cancel_job(self) -> None:
        """
        Cancels the current job execution.

        This method sends a request to cancel the job execution and logs the result.

        Returns:
            None
        """
        try:
            cancel = self.http_client.delete(
                f"/change-manager/jobExecutions/{self.job_id}/records",
            )
            cancel.raise_for_status()
            self.finished = True
            logger.info(f"Cancelled job: {self.job_id}")
        except (httpx.ConnectTimeout, httpx.ReadTimeout):
            logger.warning(f"CONNECTION ERROR cancelling job {self.job_id}. Retrying...")
            sleep(0.25)
            await self.cancel_job()

    async def log_job_summary(self):
        if job_summary := await self.get_job_summary():
            job_id = job_summary.pop("jobExecutionId", None)
            total_errors = job_summary.pop("totalErrors", 0)
            columns = ["Summary"] + list(job_summary.keys())
            rows = set()
            for key in columns[1:]:
                rows.update(job_summary[key].keys())

            table_data = []
            for row in rows:
                metric_name = decamelize(row).split("_")[1]
                table_row = [metric_name]
                for col in columns[1:]:
                    table_row.append(job_summary[col].get(row, "N/A"))
                table_data.append(table_row)
            table_data.sort(key=lambda x: REPORT_SUMMARY_ORDERING.get(x[0], 99))
            columns = columns[:1] + [" ".join(decamelize(x).split("_")[:-1]) for x in columns[1:]]
            logger.info(
                f"Results for {'file' if len(self.current_file) == 1 else 'files'}: "
                f"{', '.join([os.path.basename(x.name) for x in self.current_file])}"
            )
            logger.info(
                "\n" + tabulate.tabulate(table_data, headers=columns, tablefmt="fancy_grid"),
            )
            if total_errors:
                logger.info(f"Total errors: {total_errors}. Job ID: {job_id}.")
        else:
            logger.error(f"No job summary available for job #{self.job_hrid}({self.job_id}).")

    async def get_job_summary(self) -> dict:
        """
        Retrieves the job summary for the current job execution.

        Returns:
            dict: The job summary for the current job execution.
        """
        try:
            self.current_retry_timeout = (
                (self.current_retry_timeout * RETRY_TIMEOUT_RETRY_FACTOR)
                if self.current_retry_timeout
                else RETRY_TIMEOUT_START
            )
            with self.folio_client.get_folio_http_client() as temp_client:
                temp_client.timeout = self.current_retry_timeout
                self.folio_client.httpx_client = temp_client
                job_summary = self.folio_client.folio_get(
                    f"/metadata-provider/jobSummary/{self.job_id}"
                )
            self.current_retry_timeout = None
        except (folioclient.FolioConnectionError, folioclient.FolioHTTPError) as e:
            error_text = e.response.text if hasattr(e, "response") else str(e)
            if hasattr(e, "response") and e.response.status_code not in [502, 504, 404]:
                raise e

            if (
                self._max_summary_retries > self._summary_retries
            ) and not self.config.let_summary_fail:
                logger.warning(f"SERVER ERROR fetching job summary: {e}. Retrying.")
                sleep(0.25)
                with self.folio_client.get_folio_http_client() as temp_client:
                    temp_client.timeout = self.current_retry_timeout
                    self.folio_client.httpx_client = temp_client
                    self._summary_retries += 1
                    return await self.get_job_summary()
            else:
                logger.warning(
                    f"SERVER ERROR fetching job summary: {error_text}."
                    " Skipping final summary check."
                )
                job_summary = {}

        return job_summary


def set_up_cli_logging() -> None:
    """
    This function sets up logging for the CLI.
    """
    logger.setLevel(logging.INFO)
    logger.propagate = False

    # Set up file and stream handlers
    file_handler = logging.FileHandler(
        "folio_data_import_{}.log".format(dt.now().strftime("%Y%m%d%H%M%S"))
    )
    file_handler.setLevel(logging.INFO)
    file_handler.addFilter(ExcludeLevelFilter(DATA_ISSUE_LVL_NUM))
    # file_handler.addFilter(IncludeLevelFilter(25))
    file_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    if not any(
        isinstance(h, logging.StreamHandler) and h.stream == sys.stderr for h in logger.handlers
    ):
        stream_handler = RichHandler(
            show_level=False,
            show_time=False,
            omit_repeated_times=False,
            show_path=False,
        )
        stream_handler.setLevel(logging.INFO)
        stream_handler.addFilter(ExcludeLevelFilter(DATA_ISSUE_LVL_NUM))
        # stream_handler.addFilter(ExcludeLevelFilter(25))
        stream_formatter = logging.Formatter("%(message)s")
        stream_handler.setFormatter(stream_formatter)
        logger.addHandler(stream_handler)

    # Set up data issues logging
    data_issues_handler = logging.FileHandler(
        "marc_import_data_issues_{}.log".format(dt.now().strftime("%Y%m%d%H%M%S"))
    )
    data_issues_handler.setLevel(26)
    data_issues_handler.addFilter(IncludeLevelFilter(DATA_ISSUE_LVL_NUM))
    data_issues_formatter = logging.Formatter("%(message)s")
    data_issues_handler.setFormatter(data_issues_formatter)
    logger.addHandler(data_issues_handler)

    # Stop httpx from logging info messages to the console
    logging.getLogger("httpx").setLevel(logging.WARNING)


app = cyclopts.App(version=app_version)


@app.default
def main(
    config_file: Annotated[
        Path | None, cyclopts.Parameter(group="Job Configuration Parameters")
    ] = None,
    *,
    gateway_url: Annotated[
        str | None,
        cyclopts.Parameter(
            env_var=["FOLIO_GATEWAY_URL"],
            show_env_var=True,
            group="FOLIO Connection Parameters",
        ),
    ] = None,
    tenant_id: Annotated[
        str | None,
        cyclopts.Parameter(
            env_var=["FOLIO_TENANT_ID"],
            show_env_var=True,
            group="FOLIO Connection Parameters",
        ),
    ] = None,
    username: Annotated[
        str | None,
        cyclopts.Parameter(
            env_var=["FOLIO_USERNAME"],
            show_env_var=True,
            group="FOLIO Connection Parameters",
        ),
    ] = None,
    password: Annotated[
        str | None,
        cyclopts.Parameter(
            env_var=["FOLIO_PASSWORD"],
            show_env_var=True,
            group="FOLIO Connection Parameters",
        ),
    ] = None,
    marc_file_paths: Annotated[
        List[Path] | None,
        cyclopts.Parameter(
            consume_multiple=True,
            name=["--marc-file-paths", "--marc-file-path"],
            help="Path(s) to MARC file(s). Accepts multiple values and glob patterns.",
            group="Job Configuration Parameters",
        ),
    ] = None,
    member_tenant_id: Annotated[
        str | None,
        cyclopts.Parameter(
            env_var="FOLIO_MEMBER_TENANT_ID",
            show_env_var=True,
            group="FOLIO Connection Parameters",
        ),
    ] = None,
    import_profile_name: Annotated[
        str | None, cyclopts.Parameter(group="Job Configuration Parameters")
    ] = None,
    batch_size: Annotated[int, cyclopts.Parameter(group="Job Configuration Parameters")] = 10,
    batch_delay: Annotated[float, cyclopts.Parameter(group="Job Configuration Parameters")] = 0.0,
    preprocessors: Annotated[
        str | None,
        cyclopts.Parameter(
            name=["--preprocessor", "--preprocessors"], group="Job Configuration Parameters"
        ),
    ] = None,
    preprocessors_config: Annotated[
        str | None,
        cyclopts.Parameter(
            name=["--preprocessor-config", "--preprocessors-config"],
            group="Job Configuration Parameters",
        ),
    ] = None,
    file_names_in_di_logs: Annotated[
        bool, cyclopts.Parameter(group="Job Configuration Parameters")
    ] = False,
    split_files: Annotated[bool, cyclopts.Parameter(group="Job Configuration Parameters")] = False,
    split_size: Annotated[int, cyclopts.Parameter(group="Job Configuration Parameters")] = 1000,
    split_offset: Annotated[int, cyclopts.Parameter(group="Job Configuration Parameters")] = 0,
    no_progress: Annotated[bool, cyclopts.Parameter(group="Job Configuration Parameters")] = False,
    no_summary: Annotated[bool, cyclopts.Parameter(group="Job Configuration Parameters")] = False,
    let_summary_fail: Annotated[
        bool, cyclopts.Parameter(group="Job Configuration Parameters")
    ] = False,
    job_ids_file_path: Annotated[
        str | None, cyclopts.Parameter(group="Job Configuration Parameters")
    ] = None,
) -> None:
    """
    Command-line interface to batch import MARC records into FOLIO using FOLIO Data Import

    Parameters:
        config_file (Path | None): Path to JSON config file for the import job, overrides other parameters if provided.
        gateway_url (str): The FOLIO API Gateway URL.
        tenant_id (str): The tenant id.
        username (str): The FOLIO username.
        password (str): The FOLIO password.
        marc_file_paths (List[Path]): The MARC file(s) or glob pattern(s) to import.
        member_tenant_id (str): The FOLIO ECS member tenant id (if applicable).
        import_profile_name (str): The name of the import profile to use.
        batch_size (int): The number of records to send in each batch.
        batch_delay (float): The delay (in seconds) between sending each batch.
        preprocessors (str): Comma-separated list of MARC record preprocessors to use.
        preprocessors_config (str): Path to JSON config file for the preprocessors.
        file_names_in_di_logs (bool): Show file names in data import logs.
        split_files (bool): Split files into smaller batches.
        split_size (int): The number of records per split batch.
        split_offset (int): The number of split batches to skip before starting import.
        no_progress (bool): Disable progress bars.
        no_summary (bool): Skip the final job summary.
        let_summary_fail (bool): Let the final summary check fail without exiting.
        preprocessor_config (str): Path to JSON config file for the preprocessor.
        job_ids_file_path (str): Path to file to write job IDs to.
    """  # noqa: E501
    set_up_cli_logging()
    gateway_url, tenant_id, username, password = get_folio_connection_parameters(
        gateway_url, tenant_id, username, password
    )
    folio_client = folioclient.FolioClient(gateway_url, tenant_id, username, password)

    if member_tenant_id:
        folio_client.tenant_id = member_tenant_id

    # Handle file path expansion
    marc_files = collect_marc_file_paths(marc_file_paths)

    marc_files.sort()

    if len(marc_files) == 0:
        logger.critical(f"No files found matching {marc_file_paths}. Exiting.")
        sys.exit(1)
    else:
        logger.info(marc_files)

    if preprocessors_config:
        with open(preprocessors_config, "r") as f:
            preprocessor_args = json.load(f)
    else:
        preprocessor_args = {}

    if not import_profile_name:
        import_profile_name = select_import_profile(folio_client)

    job = None
    try:
        if config_file:
            with open(config_file, "r") as f:
                config_data = json.load(f)
            config = MARCImportJob.Config(**config_data)
        else:
            config = MARCImportJob.Config(
                marc_files=marc_files,
                import_profile_name=import_profile_name,
                batch_size=batch_size,
                batch_delay=batch_delay,
                marc_record_preprocessors=preprocessors,
                preprocessors_args=preprocessor_args,
                no_progress=no_progress,
                no_summary=no_summary,
                let_summary_fail=let_summary_fail,
                split_files=split_files,
                split_size=split_size,
                split_offset=split_offset,
                job_ids_file_path=Path(job_ids_file_path) if job_ids_file_path else None,
                show_file_names_in_data_import_logs=file_names_in_di_logs,
            )

        # Create progress reporter
        reporter = (
            NoOpProgressReporter()
            if no_progress
            else RichProgressReporter(show_speed=True, show_time=True)
        )

        job = MARCImportJob(folio_client, config, reporter)
        asyncio.run(run_job(job))
    except Exception as e:
        logger.error("Could not initialize MARCImportJob: " + str(e))
        sys.exit(1)


def select_import_profile(folio_client):
    try:
        import_profiles = folio_client.folio_get(
            "/data-import-profiles/jobProfiles",
            "jobProfiles",
            query_params={"limit": "1000"},
        )
        import_profile_names = [
            profile["name"] for profile in import_profiles if "marc" in profile["dataType"].lower()
        ]
        import_profile_name = questionary.select(
            "Select an import profile:",
            choices=import_profile_names,
        ).ask()
    except httpx.HTTPStatusError as e:
        logger.error(
            f"HTTP Error fetching import profiles: {e}"
            f"\n{getattr(getattr(e, 'response', ''), 'text', '')}\nExiting."
        )
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received. Exiting.")
        sys.exit(0)
    return import_profile_name


def collect_marc_file_paths(marc_file_paths):
    marc_files: List[Path] = []
    if marc_file_paths:
        for file_path in marc_file_paths:
            # Check if the path contains glob patterns
            file_path_str = str(file_path)
            if any(char in file_path_str for char in ["*", "?", "["]):
                # It's a glob pattern - expand it
                expanded = glob.glob(file_path_str)
                marc_files.extend([Path(x) for x in expanded])
            else:
                # It's a regular path
                marc_files.append(file_path)
    return marc_files


async def run_job(job: MARCImportJob):
    try:
        await job.do_work()
    except httpx.HTTPStatusError as e:
        logger.error(
            f"HTTP Error importing files: {e}"
            f"\n{getattr(getattr(e, 'response', ''), 'text', '')}\nExiting."
        )
        sys.exit(1)
    except Exception as e:
        logger.error("Error importing files: " + str(e))
        raise
    finally:
        if job:
            await job.wrap_up()


class ExcludeLevelFilter(logging.Filter):
    def __init__(self, level) -> None:
        super().__init__()
        self.level = level

    def filter(self, record):
        return record.levelno != self.level


class IncludeLevelFilter(logging.Filter):
    def __init__(self, level) -> None:
        super().__init__()
        self.level = level

    def filter(self, record):
        return record.levelno == self.level


if __name__ == "__main__":
    app()
