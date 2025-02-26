import argparse
import asyncio
import datetime
from email import message
import glob
import importlib
import io
import logging
import os
import sys
import uuid
from contextlib import ExitStack
from datetime import datetime as dt
from functools import cached_property
from getpass import getpass
from pathlib import Path
from time import sleep
from typing import List

import folioclient
import httpx
import inquirer
import pymarc
import tabulate
from humps import decamelize
from tqdm import tqdm

try:
    datetime_utc = datetime.UTC
except AttributeError:
    datetime_utc = datetime.timezone.utc


# The order in which the report summary should be displayed
REPORT_SUMMARY_ORDERING = {"created": 0, "updated": 1, "discarded": 2, "error": 3}

# Set default timeout and backoff values for HTTP requests when retrying job status and final summary checks
RETRY_TIMEOUT_START = 1
RETRY_TIMEOUT_RETRY_FACTOR = 2

# Custom log level for data issues, set to 26
DATA_ISSUE_LVL_NUM = 26
logging.addLevelName(DATA_ISSUE_LVL_NUM, "DATA_ISSUES")

def data_issues(self, msg, *args, **kws):
    if self.isEnabledFor(DATA_ISSUE_LVL_NUM):
        self._log(DATA_ISSUE_LVL_NUM, msg, args, **kws)

logging.Logger.data_issues = data_issues

logger = logging.getLogger(__name__)

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
        consolidate (bool): Consolidate files into a single job. Default is one job for each file.
        no_progress (bool): Disable progress bars (eg. for running in a CI environment).
    """

    bad_records_file: io.TextIOWrapper
    failed_batches_file: io.TextIOWrapper
    job_id: str
    pbar_sent: tqdm
    pbar_imported: tqdm
    http_client: httpx.Client
    current_file: List[Path]
    record_batch: List[dict] = []
    error_records: int = 0
    last_current: int = 0
    total_records_sent: int = 0
    finished: bool = False

    def __init__(
        self,
        folio_client: folioclient.FolioClient,
        marc_files: List[Path],
        import_profile_name: str,
        batch_size=10,
        batch_delay=0,
        marc_record_preprocessor=None,
        consolidate=False,
        no_progress=False,
        let_summary_fail=False,
    ) -> None:
        self.consolidate_files = consolidate
        self.no_progress = no_progress
        self.let_summary_fail = let_summary_fail
        self.folio_client: folioclient.FolioClient = folio_client
        self.import_files = marc_files
        self.import_profile_name = import_profile_name
        self.batch_size = batch_size
        self.batch_delay = batch_delay
        self.current_retry_timeout = None
        self.marc_record_preprocessor = marc_record_preprocessor
        self.pbar_sent: tqdm
        self.pbar_imported: tqdm

    async def do_work(self) -> None:
        """
        Performs the necessary work for data import.

        This method initializes an HTTP client, files to store records that fail to send,
        and calls `self.import_marc_records` to import MARC files. If `consolidate_files` is True,
        it imports all the files specified in `import_files` as a single batch. Otherwise,
        it imports each file as a separate import job.

        Returns:
            None
        """
        with (
            httpx.Client() as http_client,
            open(
                self.import_files[0].parent.joinpath(
                    f"bad_marc_records_{dt.now(tz=datetime_utc).strftime('%Y%m%d%H%M%S')}.mrc"
                ),
                "wb+",
            ) as bad_marc_file,
            open(
                self.import_files[0].parent.joinpath(
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
            if self.consolidate_files:
                self.current_file = self.import_files
                await self.import_marc_file()
            else:
                for file in self.import_files:
                    self.current_file = [file]
                    await self.import_marc_file()
            await self.wrap_up()

    async def wrap_up(self) -> None:
        """
        Wraps up the data import process.

        This method is called after the import process is complete.
        It checks for empty bad records and error files and removes them.

        Returns:
            None
        """
        with open(self.bad_records_file.name, "rb") as bad_records:
            if not bad_records.read(1):
                os.remove(bad_records.name)
                logger.info("No bad records found. Removing bad records file.")
        with open(self.failed_batches_file.name, "rb") as failed_batches:
            if not failed_batches.read(1):
                os.remove(failed_batches.name)
                logger.info("No failed batches. Removing failed batches file.")
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
        try:
            self.current_retry_timeout = (
                (self.current_retry_timeout * RETRY_TIMEOUT_RETRY_FACTOR)
                if self.current_retry_timeout
                else RETRY_TIMEOUT_START
            )
            job_status = self.folio_client.folio_get(
                "/metadata-provider/jobExecutions?statusNot=DISCARDED&uiStatusAny"
                "=PREPARING_FOR_PREVIEW&uiStatusAny=READY_FOR_PREVIEW&uiStatusAny=RUNNING&limit=50"
            )
            self.current_retry_timeout = None
        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.HTTPStatusError) as e:
            if not hasattr(e, "response") or e.response.status_code in [502, 504]:
                error_text = e.response.text if hasattr(e, "response") else str(e)
                logger.warning(f"SERVER ERROR fetching job status: {error_text}. Retrying.")
                sleep(0.25)
                with httpx.Client(
                    timeout=self.current_retry_timeout,
                    verify=self.folio_client.ssl_verify,
                ) as temp_client:
                    self.folio_client.httpx_client = temp_client
                    return await self.get_job_status()
            else:
                raise e
        try:
            status = [
                job for job in job_status["jobExecutions"] if job["id"] == self.job_id
            ][0]
            self.pbar_imported.update(status["progress"]["current"] - self.last_current)
            self.last_current = status["progress"]["current"]
        except IndexError:
            try:
                job_status = self.folio_client.folio_get(
                    "/metadata-provider/jobExecutions?limit=100&sortBy=completed_date%2Cdesc&statusAny"
                    "=COMMITTED&statusAny=ERROR&statusAny=CANCELLED"
                )
                status = [
                    job for job in job_status["jobExecutions"] if job["id"] == self.job_id
                ][0]
                self.pbar_imported.update(status["progress"]["current"] - self.last_current)
                self.last_current = status["progress"]["current"]
                self.finished = True
            except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.HTTPStatusError) as e:
                if not hasattr(e, "response") or e.response.status_code in [502, 504]:
                    error_text = e.response.text if hasattr(e, "response") else str(e)
                    logger.warning(
                        f"SERVER ERROR fetching job status: {error_text}. Retrying."
                    )
                    sleep(0.25)
                    with httpx.Client(
                        timeout=self.current_retry_timeout,
                        verify=self.folio_client.ssl_verify,
                    ) as temp_client:
                        self.folio_client.httpx_client = temp_client
                        return await self.get_job_status()
                else:
                    raise e

    async def create_folio_import_job(self) -> None:
        """
        Creates a job execution for importing data into FOLIO.

        Returns:
            None

        Raises:
            HTTPError: If there is an error creating the job.
        """
        create_job = self.http_client.post(
            self.folio_client.okapi_url + "/change-manager/jobExecutions",
            headers=self.folio_client.okapi_headers,
            json={"sourceType": "ONLINE", "userId": self.folio_client.current_user},
        )
        try:
            create_job.raise_for_status()
        except httpx.HTTPError as e:
            logger.error(
                "Error creating job: "
                + str(e)
                + "\n"
                + getattr(getattr(e, "response", ""), "text", "")
            )
            raise e
        self.job_id = create_job.json()["parentJobExecutionId"]
        logger.info("Created job: " + self.job_id)

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
            if profile["name"] == self.import_profile_name
        ][0]
        return profile

    async def set_job_profile(self) -> None:
        """
        Sets the job profile for the current job execution.

        Returns:
            The response from the HTTP request to set the job profile.
        """
        set_job_profile = self.http_client.put(
            self.folio_client.okapi_url
            + "/change-manager/jobExecutions/"
            + self.job_id
            + "/jobProfile",
            headers=self.folio_client.okapi_headers,
            json={
                "id": self.import_profile["id"],
                "name": self.import_profile["name"],
                "dataType": "MARC",
            },
        )
        try:
            set_job_profile.raise_for_status()
        except httpx.HTTPError as e:
            logger.error(
                "Error creating job: "
                + str(e)
                + "\n"
                + getattr(getattr(e, "response", ""), "text", "")
            )
            raise e

    async def read_total_records(self, files) -> int:
        """
        Reads the total number of records from the given files.

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

    async def process_record_batch(self, batch_payload) -> None:
        """
        Processes a record batch.

        Args:
            batch_payload (dict): A records payload containing the current batch of MARC records.
        """
        try:
            post_batch = self.http_client.post(
                self.folio_client.okapi_url
                + f"/change-manager/jobExecutions/{self.job_id}/records",
                headers=self.folio_client.okapi_headers,
                json=batch_payload,
            )
            # if batch_payload["recordsMetadata"]["last"]:
            #     logger.log(
            #         25,
            #         f"Sending last batch of {batch_payload['recordsMetadata']['total']} records.",
            #     )
        except (httpx.ConnectTimeout, httpx.ReadTimeout):
            sleep(0.25)
            return await self.process_record_batch(batch_payload)
        try:
            post_batch.raise_for_status()
            self.total_records_sent += len(self.record_batch)
            self.record_batch = []
            self.pbar_sent.update(len(batch_payload["initialRecords"]))
        except Exception as e:
            if (
                hasattr(e, "response") and e.response.status_code in [500, 422]
            ):  # TODO: #26 Check for specific error code once https://folio-org.atlassian.net/browse/MODSOURMAN-1281 is resolved
                self.total_records_sent += len(self.record_batch)
                self.record_batch = []
                self.pbar_sent.update(len(batch_payload["initialRecords"]))
            else:
                logger.error("Error posting batch: " + str(e))
                for record in self.record_batch:
                    self.failed_batches_file.write(record)
                    self.error_records += len(self.record_batch)
                    self.pbar_sent.total = self.pbar_sent.total - len(self.record_batch)
                self.record_batch = []
        sleep(self.batch_delay)

    async def process_records(self, files, total_records) -> None:
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
            self.pbar_sent.set_description(
                f"Sent ({os.path.basename(import_file.name)}): "
            )
            reader = pymarc.MARCReader(import_file, hide_utf8_warnings=True)
            for idx, record in enumerate(reader, start=1):
                if len(self.record_batch) == self.batch_size:
                    await self.process_record_batch(
                        await self.create_batch_payload(
                            counter,
                            total_records,
                            (counter - self.error_records)
                            == (total_records - self.error_records),
                        ),
                    )
                    await self.get_job_status()
                    sleep(0.25)
                if record:
                    if self.marc_record_preprocessor:
                        record = await self.apply_marc_record_preprocessing(
                            record, self.marc_record_preprocessor
                        )
                    self.record_batch.append(record.as_marc())
                    counter += 1
                else:
                    logger.data_issues(
                        "RECORD FAILED\t%s\t%s\t%s",
                        f"{file_path.name}:{idx}",
                        f"Error reading {idx} record from {file_path}. Skipping. Writing current chunk to {self.bad_records_file.name}.",
                        "",
                    )
                    self.bad_records_file.write(reader.current_chunk)
            if self.record_batch:
                await self.process_record_batch(
                    await self.create_batch_payload(
                        counter,
                        total_records,
                        (counter - self.error_records)
                        == (total_records - self.error_records),
                    ),
                )
            import_complete_path = file_path.parent.joinpath("import_complete")
            if import_complete_path.exists():
                logger.debug(f"Creating import_complete directory: {import_complete_path.absolute()}")
                import_complete_path.mkdir(exist_ok=True)
            logger.debug(f"Moving {file_path} to {import_complete_path.absolute()}")
            file_path.rename(
                file_path.parent.joinpath("import_complete", file_path.name)
            )

    @staticmethod
    async def apply_marc_record_preprocessing(
        record: pymarc.Record, func_or_path
    ) -> pymarc.Record:
        """
        Apply preprocessing to the MARC record before sending it to FOLIO.

        Args:
            record (pymarc.Record): The MARC record to preprocess.
            func_or_path (Union[Callable, str]): The preprocessing function or its import path.

        Returns:
            pymarc.Record: The preprocessed MARC record.
        """
        if isinstance(func_or_path, str):
            try:
                path_parts = func_or_path.rsplit(".")
                module_path, func_name = ".".join(path_parts[:-1]), path_parts[-1]
                module = importlib.import_module(module_path)
                func = getattr(module, func_name)
            except (ImportError, AttributeError) as e:
                logger.error(
                    f"Error importing preprocessing function {func_or_path}: {e}. Skipping preprocessing."
                )
                return record
        elif callable(func_or_path):
            func = func_or_path
        else:
            logger.warning(
                f"Invalid preprocessing function: {func_or_path}. Skipping preprocessing."
            )
            return record

        try:
            return func(record)
        except Exception as e:
            logger.error(
                f"Error applying preprocessing function: {e}. Skipping preprocessing."
            )
            return record

    async def create_batch_payload(self, counter, total_records, is_last) -> dict:
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
                "counter": counter - self.error_records,
                "contentType": "MARC_RAW",
                "total": total_records - self.error_records,
            },
            "initialRecords": [{"record": x.decode()} for x in self.record_batch],
        }

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
            files = [
                stack.enter_context(open(file, "rb")) for file in self.current_file
            ]
            total_records = await self.read_total_records(files)
            with (
                tqdm(
                    desc="Imported: ",
                    total=total_records,
                    position=1,
                    disable=self.no_progress,
                ) as pbar_imported,
                tqdm(
                    desc="Sent: ()",
                    total=total_records,
                    position=0,
                    disable=self.no_progress,
                ) as pbar_sent,
            ):
                self.pbar_sent = pbar_sent
                self.pbar_imported = pbar_imported
                await self.process_records(files, total_records)
                while not self.finished:
                    await self.get_job_status()
                sleep(1)
            if self.finished:
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
                    columns = columns[:1] + [
                        " ".join(decamelize(x).split("_")[:-1]) for x in columns[1:]
                    ]
                    logger.info(
                        f"Results for {'file' if len(self.current_file) == 1 else 'files'}: "
                        f"{', '.join([os.path.basename(x.name) for x in self.current_file])}"
                    )
                    logger.info(
                        "\n"
                        + tabulate.tabulate(
                            table_data, headers=columns, tablefmt="fancy_grid"
                        ),
                    )
                    if total_errors:
                        logger.info(f"Total errors: {total_errors}. Job ID: {job_id}.")
                else:
                    logger.error(f"No job summary available for job {self.job_id}.")
            self.last_current = 0
            self.finished = False

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
            with httpx.Client(
                timeout=self.current_retry_timeout, verify=self.folio_client.ssl_verify
            ) as temp_client:
                self.folio_client.httpx_client = temp_client
                job_summary = self.folio_client.folio_get(
                    f"/metadata-provider/jobSummary/{self.job_id}"
                )
            self.current_retry_timeout = None
        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.HTTPStatusError) as e:
            error_text = e.response.text if hasattr(e, "response") else str(e)
            if not hasattr(e, "response") or (
                e.response.status_code in [502, 504] and not self.let_summary_fail
            ):
                logger.warning(f"SERVER ERROR fetching job summary: {e}. Retrying.")
                sleep(0.25)
                with httpx.Client(
                    timeout=self.current_retry_timeout,
                    verify=self.folio_client.ssl_verify,
                ) as temp_client:
                    self.folio_client.httpx_client = temp_client
                    return await self.get_job_summary()
            elif hasattr(e, "response") and (
                e.response.status_code in [502, 504] and self.let_summary_fail
            ):
                logger.warning(
                    f"SERVER ERROR fetching job summary: {error_text}. Skipping final summary check."
                )
                job_summary = {}
            else:
                raise e
        return job_summary


def set_up_cli_logging():
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
        isinstance(h, logging.StreamHandler) and h.stream == sys.stderr
        for h in logger.handlers
    ):
        stream_handler = logging.StreamHandler(sys.stdout)
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
    data_issues_formatter = logging.Formatter("%(message)s")
    data_issues_handler.setFormatter(data_issues_formatter)
    logger.addHandler(data_issues_handler)

    # Stop httpx from logging info messages to the console
    logging.getLogger("httpx").setLevel(logging.WARNING)


async def main() -> None:
    """
    Main function to run the MARC import job.

    This function parses command line arguments, initializes the FolioClient,
    and runs the MARCImportJob.
    """
    set_up_cli_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument("--gateway_url", type=str, help="The FOLIO API Gateway URL")
    parser.add_argument("--tenant_id", type=str, help="The FOLIO tenant ID")
    parser.add_argument(
        "--member_tenant_id",
        type=str,
        help="The FOLIO ECS member tenant ID (if applicable)",
        default="",
    )
    parser.add_argument("--username", type=str, help="The FOLIO username")
    parser.add_argument("--password", type=str, help="The FOLIO password", default="")
    parser.add_argument(
        "--marc_file_path",
        type=str,
        help="The MARC file (or file glob, using shell globbing syntax) to import",
    )
    parser.add_argument(
        "--import_profile_name",
        type=str,
        help="The name of the data import job profile to use",
        default="",
    )
    parser.add_argument(
        "--batch_size",
        type=int,
        help="The number of source records to include in a record batch sent to FOLIO.",
        default=10,
    )
    parser.add_argument(
        "--batch_delay",
        type=float,
        help="The number of seconds to wait between record batches.",
        default=0.0,
    )
    parser.add_argument(
        "--preprocessor",
        type=str,
        help=(
            "The path to a Python module containing a preprocessing function "
            "to apply to each MARC record before sending to FOLIO."
        ),
        default=None,
    )
    parser.add_argument(
        "--consolidate",
        action="store_true",
        help=(
            "Consolidate records into a single job. "
            "Default is to create a new job for each MARC file."
        ),
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable progress bars (eg. for running in a CI environment)",
    )
    parser.add_argument(
        "--let-summary-fail",
        action="store_true",
        help="Do not retry fetching the final job summary if it fails",
    )
    args = parser.parse_args()
    if not args.password:
        args.password = getpass("Enter FOLIO password: ")
    folio_client = folioclient.FolioClient(
        args.gateway_url, args.tenant_id, args.username, args.password
    )

    # Set the member tenant id if provided to support FOLIO ECS multi-tenant environments
    if args.member_tenant_id:
        folio_client.okapi_headers["x-okapi-tenant"] = args.member_tenant_id

    if os.path.isabs(args.marc_file_path):
        marc_files = [Path(x) for x in glob.glob(args.marc_file_path)]
    else:
        marc_files = list(Path("./").glob(args.marc_file_path))

    marc_files.sort()

    if len(marc_files) == 0:
        logger.critical(f"No files found matching {args.marc_file_path}. Exiting.")
        sys.exit(1)
    else:
        logger.info(marc_files)

    if not args.import_profile_name:
        import_profiles = folio_client.folio_get(
            "/data-import-profiles/jobProfiles",
            "jobProfiles",
            query_params={"limit": "1000"},
        )
        import_profile_names = [
            profile["name"]
            for profile in import_profiles
            if "marc" in profile["dataType"].lower()
        ]
        questions = [
            inquirer.List(
                "import_profile_name",
                message="Select an import profile",
                choices=import_profile_names,
            )
        ]
        answers = inquirer.prompt(questions)
        args.import_profile_name = answers["import_profile_name"]
    try:
        await MARCImportJob(
            folio_client,
            marc_files,
            args.import_profile_name,
            batch_size=args.batch_size,
            batch_delay=args.batch_delay,
            marc_record_preprocessor=args.preprocessor,
            consolidate=bool(args.consolidate),
            no_progress=bool(args.no_progress),
            let_summary_fail=bool(args.let_summary_fail),
        ).do_work()
    except Exception as e:
        logger.error("Error importing files: " + str(e))
        raise


class ExcludeLevelFilter(logging.Filter):
    def __init__(self, level):
        super().__init__()
        self.level = level

    def filter(self, record):
        return record.levelno != self.level


class IncludeLevelFilter(logging.Filter):
    def __init__(self, level):
        super().__init__()
        self.level = level

    def filter(self, record):
        return record.levelno == self.level


def sync_main() -> None:
    """
    Synchronous main function to run the MARC import job.
    """
    asyncio.run(main())


if __name__ == "__main__":
    asyncio.run(main())
