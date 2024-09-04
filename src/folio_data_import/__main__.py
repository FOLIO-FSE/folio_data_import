import argparse
import asyncio
import glob
from getpass import getpass
from pathlib import Path

import folioclient
import inquirer

from folio_data_import.MARCDataImport import MARCImportJob


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--record-type", type=str, help="The record type to import", default="MARC21"
    )
    parser.add_argument("--gateway_url", type=str, help="The FOLIO API Gateway URL")
    parser.add_argument("--tenant_id", type=str, help="The FOLIO tenant ID")
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
    if not args.import_profile_name:
        import_profiles = folio_client.folio_get(
            "/data-import-profiles/jobProfiles",
            "jobProfiles",
            query_params={"limit": "1000"},
        )
        import_profile_names = [
            profile["name"]
            for profile in import_profiles
            if args.record_type.lower() in profile["dataType"].lower()
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

    if args.record_type.lower() == "marc21":
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
    elif args.record_type.lower() == "users":
        print(
            "User import not yet implemented. Run UserImport.py directly "
            "or use folio-user-import CLI."
        )
    else:
        print("Record type not supported. Supported types are: MARC21")


def sync_main():
    asyncio.run(main())


if __name__ == "__main__":
    asyncio.run(main())
