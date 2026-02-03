"""Tests for the DILogRetriever module."""

import csv
import json
import pytest
from io import BytesIO, StringIO
from unittest.mock import MagicMock, Mock, patch, mock_open

import pymarc

from folio_data_import.DILogRetriever import DILogRetriever
from folio_data_import._postgres import PostgresConfig, SSHTunnelConfig
from folio_data_import._progress import NoOpProgressReporter


class TestDILogRetriever:
    """Tests for DILogRetriever class."""

    @pytest.fixture
    def mock_folio_client(self):
        """Create a mock FolioClient."""
        client = MagicMock()
        client.tenant_id = "test_tenant"
        return client

    @pytest.fixture
    def db_config(self):
        """Create a test database configuration."""
        return PostgresConfig(
            host="localhost",
            port=5432,
            database="folio",
            user="folio",
            password="test_password",
        )

    @pytest.fixture
    def ssh_tunnel_config(self):
        """Create a test SSH tunnel configuration (disabled)."""
        return SSHTunnelConfig(ssh_tunnel=False)

    @pytest.fixture
    def retriever(self, mock_folio_client, db_config, ssh_tunnel_config):
        """Create a DILogRetriever instance for testing."""
        return DILogRetriever(
            folio_client=mock_folio_client,
            db_config=db_config,
            ssh_tunnel_config=ssh_tunnel_config,
            progress_reporter=NoOpProgressReporter(),
        )

    def test_init_with_defaults(self, mock_folio_client, db_config, ssh_tunnel_config):
        """Test DILogRetriever initialization with default progress reporter."""
        retriever = DILogRetriever(
            folio_client=mock_folio_client,
            db_config=db_config,
            ssh_tunnel_config=ssh_tunnel_config,
        )
        assert retriever.folio_client == mock_folio_client
        assert retriever.db_config == db_config
        assert retriever.ssh_tunnel_config == ssh_tunnel_config
        assert retriever.progress_reporter is not None

    def test_init_with_custom_progress_reporter(
        self, mock_folio_client, db_config, ssh_tunnel_config
    ):
        """Test DILogRetriever initialization with custom progress reporter."""
        progress_reporter = NoOpProgressReporter()
        retriever = DILogRetriever(
            folio_client=mock_folio_client,
            db_config=db_config,
            ssh_tunnel_config=ssh_tunnel_config,
            progress_reporter=progress_reporter,
        )
        assert retriever.progress_reporter == progress_reporter


class TestRetrieveErrorsWithMarc:
    """Tests for retrieve_errors_with_marc method."""

    @pytest.fixture
    def mock_folio_client(self):
        """Create a mock FolioClient."""
        client = MagicMock()
        client.tenant_id = "test_tenant"
        return client

    @pytest.fixture
    def db_config(self):
        """Create a test database configuration."""
        return PostgresConfig(
            host="localhost",
            port=5432,
            database="folio",
            user="folio",
            password="test_password",
        )

    @pytest.fixture
    def ssh_tunnel_config(self):
        """Create a test SSH tunnel configuration (disabled)."""
        return SSHTunnelConfig(ssh_tunnel=False)

    @pytest.fixture
    def retriever(self, mock_folio_client, db_config, ssh_tunnel_config):
        """Create a DILogRetriever instance for testing."""
        return DILogRetriever(
            folio_client=mock_folio_client,
            db_config=db_config,
            ssh_tunnel_config=ssh_tunnel_config,
            progress_reporter=NoOpProgressReporter(),
        )

    @pytest.fixture
    def sample_marc_record(self):
        """Create a sample MARC record for testing."""
        record = pymarc.Record()
        record.add_field(
            pymarc.Field(
                tag="245",
                indicators=["0", "0"],
                subfields=[pymarc.Subfield(code="a", value="Test Title")],
            )
        )
        return record

    @patch("folio_data_import.DILogRetriever.db_session")
    def test_retrieve_errors_with_marc_success(
        self, mock_db_session, retriever, sample_marc_record
    ):
        """Test successful retrieval of error logs with MARC records."""
        # Create mock cursor and session
        mock_cursor = MagicMock()
        mock_session = MagicMock()
        mock_session.cursor.return_value = mock_cursor

        # Create sample row data using dict format (RealDictCursor)
        raw_marc = sample_marc_record.as_marc().decode("utf-8")
        mock_cursor.fetchall.return_value = [
            {
                "id": "record-id-1",
                "job_execution_id": "job-1",
                "source_id": "source-1",
                "error": "Some error message",
                "incoming_record": {"rawRecordContent": raw_marc},
            }
        ]

        mock_db_session.return_value.__enter__ = Mock(return_value=mock_session)
        mock_db_session.return_value.__exit__ = Mock(return_value=False)

        result = retriever.retrieve_errors_with_marc(["job-1"])

        assert len(result) == 1
        error_log, marc_record = result[0]
        assert json.loads(error_log) == "Some error message"
        assert isinstance(marc_record, pymarc.Record)

    @patch("folio_data_import.DILogRetriever.db_session")
    def test_retrieve_errors_with_marc_empty_results(self, mock_db_session, retriever):
        """Test retrieval when no error records are found."""
        mock_cursor = MagicMock()
        mock_session = MagicMock()
        mock_session.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []

        mock_db_session.return_value.__enter__ = Mock(return_value=mock_session)
        mock_db_session.return_value.__exit__ = Mock(return_value=False)

        result = retriever.retrieve_errors_with_marc(["job-1"])

        assert len(result) == 0

    @patch("folio_data_import.DILogRetriever.db_session")
    def test_retrieve_errors_with_marc_missing_raw_content(self, mock_db_session, retriever):
        """Test handling of records with missing rawRecordContent."""
        mock_cursor = MagicMock()
        mock_session = MagicMock()
        mock_session.cursor.return_value = mock_cursor

        # Row with missing rawRecordContent
        mock_cursor.fetchall.return_value = [
            {
                "id": "record-id-1",
                "job_execution_id": "job-1",
                "source_id": "source-1",
                "error": "Some error message",
                "incoming_record": {},  # Missing rawRecordContent
            }
        ]

        mock_db_session.return_value.__enter__ = Mock(return_value=mock_session)
        mock_db_session.return_value.__exit__ = Mock(return_value=False)

        result = retriever.retrieve_errors_with_marc(["job-1"])

        # Should skip the record and return empty list
        assert len(result) == 0

    @patch("folio_data_import.DILogRetriever.db_session")
    def test_retrieve_errors_with_marc_null_incoming_record(self, mock_db_session, retriever):
        """Test handling of records with null incoming_record."""
        mock_cursor = MagicMock()
        mock_session = MagicMock()
        mock_session.cursor.return_value = mock_cursor

        mock_cursor.fetchall.return_value = [
            {
                "id": "record-id-1",
                "job_execution_id": "job-1",
                "source_id": "source-1",
                "error": "Some error message",
                "incoming_record": None,
            }
        ]

        mock_db_session.return_value.__enter__ = Mock(return_value=mock_session)
        mock_db_session.return_value.__exit__ = Mock(return_value=False)

        result = retriever.retrieve_errors_with_marc(["job-1"])

        # Should skip the record and return empty list
        assert len(result) == 0

    @patch("folio_data_import.DILogRetriever.db_session")
    def test_retrieve_errors_with_marc_malformed_marc(self, mock_db_session, retriever):
        """Test handling of malformed MARC data."""
        mock_cursor = MagicMock()
        mock_session = MagicMock()
        mock_session.cursor.return_value = mock_cursor

        mock_cursor.fetchall.return_value = [
            {
                "id": "record-id-1",
                "job_execution_id": "job-1",
                "source_id": "source-1",
                "error": "Some error message",
                "incoming_record": {"rawRecordContent": "not valid marc data"},
            }
        ]

        mock_db_session.return_value.__enter__ = Mock(return_value=mock_session)
        mock_db_session.return_value.__exit__ = Mock(return_value=False)

        # Should not raise, should log warning and skip
        result = retriever.retrieve_errors_with_marc(["job-1"])

        # May or may not parse depending on pymarc's tolerance
        # The important thing is it doesn't raise an exception
        assert isinstance(result, list)

    @patch("folio_data_import.DILogRetriever.db_session")
    def test_retrieve_errors_multiple_jobs(self, mock_db_session, retriever, sample_marc_record):
        """Test retrieval across multiple job IDs."""
        mock_cursor = MagicMock()
        mock_session = MagicMock()
        mock_session.cursor.return_value = mock_cursor

        raw_marc = sample_marc_record.as_marc().decode("utf-8")

        # Return different results for each call
        mock_cursor.fetchall.side_effect = [
            [
                {
                    "id": "record-1",
                    "job_execution_id": "job-1",
                    "source_id": "source-1",
                    "error": "Error 1",
                    "incoming_record": {"rawRecordContent": raw_marc},
                }
            ],
            [
                {
                    "id": "record-2",
                    "job_execution_id": "job-2",
                    "source_id": "source-2",
                    "error": "Error 2",
                    "incoming_record": {"rawRecordContent": raw_marc},
                }
            ],
        ]

        mock_db_session.return_value.__enter__ = Mock(return_value=mock_session)
        mock_db_session.return_value.__exit__ = Mock(return_value=False)

        result = retriever.retrieve_errors_with_marc(["job-1", "job-2"])

        assert len(result) == 2


class TestGenerateErrorReportAndMarcFile:
    """Tests for generate_error_report_and_marc_file method."""

    @pytest.fixture
    def mock_folio_client(self):
        """Create a mock FolioClient."""
        client = MagicMock()
        client.tenant_id = "test_tenant"
        return client

    @pytest.fixture
    def db_config(self):
        """Create a test database configuration."""
        return PostgresConfig(
            host="localhost",
            port=5432,
            database="folio",
            user="folio",
            password="test_password",
        )

    @pytest.fixture
    def ssh_tunnel_config(self):
        """Create a test SSH tunnel configuration (disabled)."""
        return SSHTunnelConfig(ssh_tunnel=False)

    @pytest.fixture
    def retriever(self, mock_folio_client, db_config, ssh_tunnel_config):
        """Create a DILogRetriever instance for testing."""
        return DILogRetriever(
            folio_client=mock_folio_client,
            db_config=db_config,
            ssh_tunnel_config=ssh_tunnel_config,
            progress_reporter=NoOpProgressReporter(),
        )

    @pytest.fixture
    def sample_marc_record(self):
        """Create a sample MARC record for testing."""
        record = pymarc.Record()
        record.add_field(
            pymarc.Field(
                tag="245",
                indicators=["0", "0"],
                subfields=[pymarc.Subfield(code="a", value="Test Title")],
            )
        )
        return record

    def test_generate_error_report_and_marc_file(self, retriever, sample_marc_record, tmp_path):
        """Test generation of error report TSV and MARC file."""
        error_logs = [
            (json.dumps("Error message 1"), sample_marc_record),
            (json.dumps("Error message 2"), sample_marc_record),
        ]

        report_path = tmp_path / "report.tsv"
        marc_path = tmp_path / "records.mrc"

        retriever.generate_error_report_and_marc_file(
            error_logs=error_logs,
            report_file_path=str(report_path),
            marc_file_path=str(marc_path),
        )

        # Verify report file was created
        assert report_path.exists()
        with open(report_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f, delimiter="\t", quotechar="'")
            rows = list(reader)
            assert len(rows) == 3  # Header + 2 data rows
            assert rows[0] == ["Error Log", "MARC Record"]

        # Verify MARC file was created
        assert marc_path.exists()
        with open(marc_path, "rb") as f:
            reader = pymarc.MARCReader(f)
            records = list(reader)
            assert len(records) == 2

    def test_generate_error_report_empty_logs(self, retriever, tmp_path):
        """Test generation with empty error logs."""
        report_path = tmp_path / "report.tsv"
        marc_path = tmp_path / "records.mrc"

        retriever.generate_error_report_and_marc_file(
            error_logs=[],
            report_file_path=str(report_path),
            marc_file_path=str(marc_path),
        )

        # Verify report file was created with only header
        assert report_path.exists()
        with open(report_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f, delimiter="\t", quotechar="'")
            rows = list(reader)
            assert len(rows) == 1  # Only header
            assert rows[0] == ["Error Log", "MARC Record"]


class TestPostgresConfig:
    """Tests for PostgresConfig model."""

    def test_postgres_config_defaults(self):
        """Test PostgresConfig with default values."""
        config = PostgresConfig(
            host="localhost",
            database="folio",
            user="folio",
        )
        assert config.port == 5432
        assert config.password is None

    def test_postgres_config_full(self):
        """Test PostgresConfig with all values."""
        config = PostgresConfig(
            host="db.example.com",
            port=5433,
            database="folio_db",
            user="admin",
            password="secret",
        )
        assert config.host == "db.example.com"
        assert config.port == 5433
        assert config.database == "folio_db"
        assert config.user == "admin"
        assert config.password == "secret"


class TestSSHTunnelConfig:
    """Tests for SSHTunnelConfig model."""

    def test_ssh_tunnel_config_defaults(self):
        """Test SSHTunnelConfig with default values."""
        config = SSHTunnelConfig()
        assert config.ssh_path == "ssh"
        assert config.ssh_tunnel is False
        assert config.use_ssh_config is False
        assert config.ssh_host is None
        assert config.ssh_user is None
        assert config.ssh_private_key_path is None

    def test_ssh_tunnel_config_enabled(self):
        """Test SSHTunnelConfig with tunnel enabled."""
        config = SSHTunnelConfig(
            ssh_tunnel=True,
            ssh_host="bastion.example.com",
            ssh_user="tunnel_user",
            ssh_private_key_path="~/.ssh/id_rsa",
        )
        assert config.ssh_tunnel is True
        assert config.ssh_host == "bastion.example.com"
        assert config.ssh_user == "tunnel_user"
        assert config.ssh_private_key_path == "~/.ssh/id_rsa"
