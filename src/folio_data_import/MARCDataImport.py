import argparse
import asyncio
import glob
import io
import os
from typing import List
import uuid
from contextlib import ExitStack
import datetime
from datetime import datetime as dt
from getpass import getpass
from pathlib import Path
from time import sleep

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
    job_import_profile: dict
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
        consolidate=False,
        no_progress=False,
    ) -> None:
        self.consolidate_files = consolidate
        self.no_progress = no_progress
        self.folio_client: folioclient.FolioClient = folio_client
        self.import_files = marc_files
        self.import_profile_name = import_profile_name
        self.batch_size = batch_size
        self.batch_delay = batch_delay

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
        with httpx.Client() as http_client, open(
            self.import_files[0].parent.joinpath(
                f"bad_marc_records_{dt.now(tz=datetime_utc).strftime('%Y%m%d%H%M%S')}.mrc"
            ),
            "wb+",
        ) as bad_marc_file, open(
            self.import_files[0].parent.joinpath(
                f"failed_batches_{dt.now(tz=datetime_utc).strftime('%Y%m%d%H%M%S')}.mrc"
            ),
            "wb+",
        ) as failed_batches:
            self.bad_records_file = bad_marc_file
            print(f"Writing bad records to {self.bad_records_file.name}")
            self.failed_batches_file = failed_batches
            print(f"Writing failed batches to {self.failed_batches_file.name}")
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
        self.bad_records_file.seek(0)
        if not self.bad_records_file.read(1):
            os.remove(self.bad_records_file.name)
            print("No bad records found. Removing bad records file.")
        self.failed_batches_file.seek(0)
        if not self.failed_batches_file.read(1):
            os.remove(self.failed_batches_file.name)
            print("No failed batches. Removing failed batches file.")
        print("Import complete.")
        print(f"Total records imported: {self.total_records_sent}")

    async def get_job_status(self) -> None:
        """
        Retrieves the status of a job execution.

        Returns:
            None

        Raises:
            IndexError: If the job execution with the specified ID is not found.
        """
        job_status = self.folio_client.folio_get(
            "/metadata-provider/jobExecutions?statusNot=DISCARDED&uiStatusAny"
            "=PREPARING_FOR_PREVIEW&uiStatusAny=READY_FOR_PREVIEW&uiStatusAny=RUNNING&limit=50"
        )
        try:
            status = [
                job for job in job_status["jobExecutions"] if job["id"] == self.job_id
            ][0]
            self.pbar_imported.update(status["progress"]["current"] - self.last_current)
            self.last_current = status["progress"]["current"]
        except IndexError:
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
            print(
                "Error creating job: "
                + str(e)
                + "\n"
                + getattr(getattr(e, "response", ""), "text", "")
            )
            raise e
        self.job_id = create_job.json()["parentJobExecutionId"]

    async def get_import_profile(self) -> None:
        """
        Retrieves the import profile with the specified name.
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
        self.job_import_profile = profile

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
                "id": self.job_import_profile["id"],
                "name": self.job_import_profile["name"],
                "dataType": "MARC",
            },
        )
        try:
            set_job_profile.raise_for_status()
        except httpx.HTTPError as e:
            print(
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
                chunk = import_file.read(1024)
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
        post_batch = self.http_client.post(
            self.folio_client.okapi_url
            + f"/change-manager/jobExecutions/{self.job_id}/records",
            headers=self.folio_client.okapi_headers,
            json=batch_payload,
        )
        try:
            post_batch.raise_for_status()
            self.total_records_sent += len(self.record_batch)
            self.record_batch = []
            self.pbar_sent.update(len(batch_payload["initialRecords"]))
        except Exception as e:
            print("Error posting batch: " + str(e))
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
            self.pbar_sent.set_description(
                f"Sent ({os.path.basename(import_file.name)}): "
            )
            reader = pymarc.MARCReader(import_file, hide_utf8_warnings=True)
            for record in reader:
                if len(self.record_batch) == self.batch_size:
                    await self.process_record_batch(
                        await self.create_batch_payload(counter, total_records, False),
                    )
                    await self.get_job_status()
                    sleep(0.25)
                if record:
                    self.record_batch.append(record.as_marc())
                    counter += 1
                else:
                    self.bad_records_file.write(reader.current_chunk)
            if self.record_batch:
                await self.process_record_batch(
                    await self.create_batch_payload(counter, total_records, True),
                )

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
        await self.get_import_profile()
        await self.set_job_profile()
        with ExitStack() as stack:
            files = [
                stack.enter_context(open(file, "rb")) for file in self.current_file
            ]
            total_records = await self.read_total_records(files)
            with tqdm(
                desc="Imported: ",
                total=total_records,
                position=1,
                disable=self.no_progress,
            ) as pbar_imported, tqdm(
                desc="Sent: ()",
                total=total_records,
                position=0,
                disable=self.no_progress,
            ) as pbar_sent:
                self.pbar_sent = pbar_sent
                self.pbar_imported = pbar_imported
                await self.process_records(files, total_records)
                while not self.finished:
                    await self.get_job_status()
                sleep(1)
            if self.finished:
                job_summary = self.folio_client.folio_get(
                    f"/metadata-provider/jobSummary/{self.job_id}"
                )
                job_summary.pop("jobExecutionId")
                job_summary.pop("totalErrors")
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
                print(
                    f"Results for {'file' if len(self.current_file) == 1 else 'files'}: "
                    f"{', '.join([os.path.basename(x.name) for x in self.current_file])}"
                )
                print(
                    tabulate.tabulate(
                        table_data, headers=columns, tablefmt="fancy_grid"
                    ),
                )
            self.last_current = 0
            self.finished = False


async def main() -> None:
    """
    Main function to run the MARC import job.

    This function parses command line arguments, initializes the FolioClient,
    and runs the MARCImportJob.
    """
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
    args = parser.parse_args()
    if not args.password:
        args.password = getpass("Enter FOLIO password: ")
    folio_client = folioclient.FolioClient(
        args.gateway_url, args.tenant_id, args.username, args.password
    )

    # Set the member tenant id if provided to support FOLIO ECS multi-tenant environments
    if args.member_tenant_id:
        folio_client.okapi_headers["x-okapi-tenant"] = args.member_tenant_id

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
    marc_files = [Path(x) for x in glob.glob(args.marc_file_path, root_dir="./")]
    print(marc_files)
    try:
        await MARCImportJob(
            folio_client,
            marc_files,
            args.import_profile_name,
            batch_size=args.batch_size,
            batch_delay=args.batch_delay,
            consolidate=bool(args.consolidate),
            no_progress=bool(args.no_progress),
        ).do_work()
    except Exception as e:
        print("Error importing files: " + str(e))
        raise


def sync_main() -> None:
    """
    Synchronous main function to run the MARC import job.
    """
    asyncio.run(main())


if __name__ == "__main__":
    asyncio.run(main())
