import csv
import json
import logging
import sys
from pathlib import Path
from typing import Annotated, Dict, List, Tuple

import cyclopts
import folioclient
import pymarc

from folio_data_import import (
    __version__ as app_version,
)
from folio_data_import import (
    get_folio_connection_parameters,
    set_up_cli_logging,
)
from folio_data_import._postgres import (
    POSTGRES_AVAILABLE,
    POSTGRES_INSTALL_MESSAGE,
    PostgresConfig,
    RealDictCursor,
    SSHTunnelConfig,
    db_session,
)
from folio_data_import._progress import (
    NoOpProgressReporter,
    ProgressReporter,
    RichProgressReporter,
)

logger = logging.getLogger(__name__)


class DILogRetriever:
    def __init__(
        self,
        folio_client: folioclient.FolioClient,
        db_config: PostgresConfig,
        ssh_tunnel_config: SSHTunnelConfig,
        progress_reporter: ProgressReporter | None = None,
    ):
        self.folio_client = folio_client
        self.db_config = db_config
        self.ssh_tunnel_config = ssh_tunnel_config
        self.progress_reporter = (
            progress_reporter if progress_reporter is not None else NoOpProgressReporter()
        )

    def retrieve_errors_with_marc(self, job_ids: list[str]) -> List[Tuple[str, pymarc.Record]]:
        error_logs = []
        get_di_errors = self.progress_reporter.start_task(
            "get_di_error_logs_with_marc",
            total=len(job_ids),
            description="Retrieving DI error logs with MARC records",
        )
        with (
            db_session(
                db_config=self.db_config, ssh_tunnel_config=self.ssh_tunnel_config
            ) as session,
        ):
            tenant = self.folio_client.tenant_id
            for job_id in job_ids:
                query = f"""
                    SELECT DISTINCT ON (jr.source_id)
                        jr.id,
                        jr.job_execution_id,
                        jr.source_id,
                        jr.error,
                        ir.incoming_record
                    FROM
                        "{tenant}_mod_source_record_manager".journal_records AS jr
                    INNER JOIN
                        "{tenant}_mod_source_record_manager".incoming_records AS ir
                        ON jr.source_id = ir.id
                    WHERE
                        jr.job_execution_id = %s
                        AND jr.error <> '';
                """  # noqa: S608
                cur = session.cursor(cursor_factory=RealDictCursor)
                cur.execute(query, (job_id,))
                result = cur.fetchall()
                for row in result:
                    if row:
                        try:
                            incoming_record = row.get("incoming_record")
                            if not incoming_record or "rawRecordContent" not in incoming_record:
                                logger.warning(
                                    "Skipping record %s: missing rawRecordContent",
                                    row.get("source_id", "unknown"),
                                )
                                continue
                            marc_record = pymarc.record.Record(
                                incoming_record["rawRecordContent"].encode("utf-8"),
                                force_utf8=True,
                            )
                            error_logs.append(
                                (
                                    json.dumps(row.get("error", "")),
                                    marc_record,
                                )
                            )
                        except Exception as e:
                            logger.warning(
                                "Failed to parse MARC record for source_id %s: %s",
                                row.get("source_id", "unknown"),
                                str(e),
                            )
                cur.close()
                self.progress_reporter.update_task(get_di_errors, advance=1)
        self.progress_reporter.finish_task(get_di_errors)
        return error_logs

    def generate_error_report_and_marc_file(
        self,
        error_logs: List[Tuple[Dict, pymarc.record.Record]],
        report_file_path: str,
        marc_file_path: str,
    ):
        with (
            open(report_file_path, "w", encoding="utf-8") as report_file,
            open(marc_file_path, "wb") as marc_file,
        ):
            marc_writer = pymarc.MARCWriter(marc_file)
            csv_writer = csv.writer(
                report_file, delimiter="\t", quotechar="'", quoting=csv.QUOTE_ALL
            )
            csv_writer.writerow(["Error Log", "MARC Record"])
            for error_log, marc_record in error_logs:
                csv_writer.writerow([error_log, marc_record.as_marc().decode("utf-8")])
                marc_writer.write(marc_record)
            marc_writer.close()


app = cyclopts.App(
    version=app_version,
)


@app.default
def main(
    folio_url: Annotated[
        str | None,
        cyclopts.Parameter(env_var="FOLIO_URL", help="FOLIO Gateway URL"),
    ] = None,
    folio_tenant: Annotated[
        str | None,
        cyclopts.Parameter(env_var="FOLIO_TENANT", help="FOLIO Tenant ID"),
    ] = None,
    folio_username: Annotated[
        str | None,
        cyclopts.Parameter(env_var="FOLIO_USERNAME", help="FOLIO Username"),
    ] = None,
    folio_password: Annotated[
        str | None,
        cyclopts.Parameter(env_var="FOLIO_PASSWORD", help="FOLIO Password"),
    ] = None,
    db_config: Annotated[
        Path | None,
        cyclopts.Parameter(help="Path to the database configuration file (JSON format)"),
    ] = None,
    ssh_config: Annotated[
        Path | None,
        cyclopts.Parameter(help="Path to the SSH tunnel configuration file (JSON format)"),
    ] = None,
    job_ids_file: Annotated[
        Path,
        cyclopts.Parameter(
            help="Path to a text file containing Data Import job execution IDs (one per line)"
        ),
    ] = Path("marc_import_job_ids.txt"),
    report_file_path: Annotated[
        Path,
        cyclopts.Parameter(help="Path to save the error report TSV file"),
    ] = Path("di_error_report.tsv"),
    marc_file_path: Annotated[
        Path, cyclopts.Parameter(help="Path to save the MARC records file")
    ] = Path("di_error_records.mrc"),
    no_progress: Annotated[
        bool,
        cyclopts.Parameter(help="Disable progress reporting"),
    ] = False,
    debug: Annotated[
        bool,
        cyclopts.Parameter(help="Enable debug logging"),
    ] = False,
) -> None:
    """Retrieve FOLIO Data Import error logs with MARC records and generate report files.
    Requires PostgreSQL access.

    Args:
        folio_url (str | None): FOLIO Gateway URL.
        folio_tenant (str | None): FOLIO Tenant ID.
        folio_username (str | None): FOLIO Username.
        folio_password (str | None): FOLIO Password.
        db_config (Path | None): Path to the database configuration file (JSON format).
        ssh_config (Path | None): Path to the SSH tunnel configuration file (JSON format).
        job_ids_file (Path): Path to a text file containing Data Import job execution IDs.
        report_file_path (Path): Path to save the error report TSV file.
        marc_file_path (Path): Path to save the MARC records file.
        no_progress (bool): Disable progress reporting if True.
        debug (bool): Enable debug logging if True.
    """
    # Check for required PostgreSQL dependencies
    if not POSTGRES_AVAILABLE:
        print(f"Error: {POSTGRES_INSTALL_MESSAGE}", file=sys.stderr)
        sys.exit(1)

    set_up_cli_logging(logger, log_file_prefix="di_log_retriever", debug=debug)
    folio_url, folio_tenant, folio_username, folio_password = get_folio_connection_parameters(
        folio_url, folio_tenant, folio_username, folio_password
    )
    folio_client = folioclient.FolioClient(
        gateway_url=folio_url,
        tenant_id=folio_tenant,
        username=folio_username,
        password=folio_password,
    )
    job_ids: List[str] = []
    with open(job_ids_file, "r", encoding="utf-8") as f:
        job_ids = [line.strip() for line in f if line.strip()]
    if job_ids:
        if db_config is None:
            print(
                "Error: --db-config is required. Please provide a path to the database "
                "configuration file (JSON format).",
                file=sys.stderr,
            )
            sys.exit(1)
        with open(db_config, "r", encoding="utf-8") as f:
            database_config = PostgresConfig.model_validate_json(f.read())
        if ssh_config:
            with open(ssh_config, "r", encoding="utf-8") as f:
                ssh_tunnel_config = SSHTunnelConfig.model_validate_json(f.read())
        else:
            ssh_tunnel_config = SSHTunnelConfig(ssh_tunnel=False)
        progress_reporter = (
            NoOpProgressReporter() if no_progress else RichProgressReporter(enabled=True)
        )
        with progress_reporter:
            retriever = DILogRetriever(
                folio_client=folio_client,
                db_config=database_config,
                ssh_tunnel_config=ssh_tunnel_config,
                progress_reporter=progress_reporter,
            )
            error_logs = retriever.retrieve_errors_with_marc(job_ids=job_ids)
            retriever.generate_error_report_and_marc_file(
                error_logs=error_logs,
                report_file_path=report_file_path,
                marc_file_path=marc_file_path,
            )
    else:
        print("No job IDs found in the specified file.")


if __name__ == "__main__":
    app()
