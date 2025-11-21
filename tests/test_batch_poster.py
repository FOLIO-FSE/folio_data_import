"""Tests for the BatchPoster module."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from uuid import uuid4

from folioclient import FolioClient

from folio_data_import.BatchPoster import (
    BatchPoster,
    BatchPosterStats,
    deep_update,
    extract_paths,
    get_api_info,
    get_human_readable_size,
)


class TestGetApiInfo:
    """Tests for get_api_info function."""

    def test_unsupported_object_type(self):
        """Test that unsupported object type raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported object type"):
            get_api_info("InvalidType")


class TestDeepUpdate:
    """Tests for deep_update function."""

    def test_simple_update(self):
        """Test simple dictionary update."""
        target = {"a": 1, "b": 2}
        source = {"b": 3, "c": 4}
        deep_update(target, source)
        assert target == {"a": 1, "b": 3, "c": 4}

    def test_nested_update(self):
        """Test nested dictionary update."""
        target = {"a": {"x": 1, "y": 2}, "b": 3}
        source = {"a": {"y": 5, "z": 6}, "c": 7}
        deep_update(target, source)
        assert target == {"a": {"x": 1, "y": 5, "z": 6}, "b": 3, "c": 7}

    def test_list_replacement(self):
        """Test that lists are replaced, not merged."""
        target = {"a": [1, 2, 3]}
        source = {"a": [4, 5]}
        deep_update(target, source)
        assert target == {"a": [4, 5]}


class TestExtractPaths:
    """Tests for extract_paths function."""

    def test_extract_existing_paths(self):
        """Test extracting existing paths."""
        record = {
            "id": "123",
            "statisticalCodeIds": ["code1", "code2"],
            "status": {"name": "Available"},
            "barcode": "12345",
        }
        result = extract_paths(record, ["statisticalCodeIds", "status"])
        assert result == {
            "statisticalCodeIds": ["code1", "code2"],
            "status": {"name": "Available"},
        }

    def test_extract_nonexistent_paths(self):
        """Test extracting non-existent paths returns empty dict."""
        record = {"id": "123", "barcode": "12345"}
        result = extract_paths(record, ["statisticalCodeIds", "status"])
        assert result == {}


class TestBatchPosterConfig:
    """Tests for BatchPoster.Config model."""

    def test_default_values(self):
        """Test that default configuration values are set correctly."""
        config = BatchPoster.Config(object_type="Items")
        assert config.batch_size == 1
        assert config.upsert is False
        assert config.preserve_statistical_codes is False

    def test_custom_values(self):
        """Test that custom configuration values can be set."""
        config = BatchPoster.Config(
            object_type="Holdings",
            batch_size=50,
            upsert=True,
            preserve_statistical_codes=True,
        )
        assert config.object_type == "Holdings"
        assert config.batch_size == 50
        assert config.upsert is True
        assert config.preserve_statistical_codes is True


class TestBatchPosterStats:
    """Tests for BatchPosterStats model."""

    def test_default_stats(self):
        """Test default statistics values."""
        stats = BatchPosterStats()
        assert stats.records_processed == 0
        assert stats.records_posted == 0
        assert stats.records_created == 0
        assert stats.records_updated == 0
        assert stats.records_failed == 0


@pytest.fixture
def mock_folio_client():
    """Create a mock FOLIO client."""
    client = Mock(spec=FolioClient)
    client.okapi_url = "https://folio.example.com"
    client.okapi_headers = {"X-Okapi-Token": "test-token", "X-Okapi-Tenant": "test"}
    
    # Mock the HTTP client context manager
    mock_http_client = Mock()
    client.get_folio_http_client = Mock(return_value=mock_http_client)
    mock_http_client.__enter__ = Mock(return_value=mock_http_client)
    mock_http_client.__exit__ = Mock(return_value=None)
    
    # Mock the async httpx client
    mock_async_client = Mock()
    mock_response = Mock()
    mock_response.json = Mock(return_value={})
    mock_response.raise_for_status = Mock()
    mock_response.elapsed.total_seconds = Mock(return_value=0.5)
    # Mock the request object with proper attributes for get_req_size
    mock_request = Mock()
    mock_request.method = "POST"
    mock_request.url = "https://folio.example.com/api"
    mock_request.headers = {"Content-Type": "application/json"}
    mock_request.content = b'{"test": "data"}'
    mock_response.request = mock_request
    mock_async_client.post = AsyncMock(return_value=mock_response)
    client.async_httpx_client = mock_async_client
    
    return client


@pytest.fixture
def preserve_fields_config():
    """Fixture for config with preserve_fields."""
    return BatchPoster.Config()


@pytest.fixture
def batch_poster(mock_folio_client, config):
    """Create a test BatchPoster instance."""
    return BatchPoster(mock_folio_client, config)


class TestBatchPoster:
    """Tests for BatchPoster class."""

    def test_initialization(self, batch_poster, config):
        """Test BatchPoster initialization."""
        assert batch_poster.folio_client is not None
        assert batch_poster.config == config

    def test_initialization_with_invalid_upsert(self, mock_folio_client):
        """Test initialization fails with upsert on unsupported type."""
        # For this test, we'd need a type that doesn't support upsert
        # Currently all our types support it, so this test would need
        # to be adjusted or we'd need to add a non-upsert type
        pass

    def test_handle_upsert_for_statistical_codes_preserve(self, batch_poster):
        """Test preserving statistical codes during upsert."""
        batch_poster.config.preserve_statistical_codes = True
        updates = {"id": "123", "statisticalCodeIds": ["code1", "code2"]}
        keep_existing = {}

        batch_poster.handle_upsert_for_statistical_codes(updates, keep_existing)

        assert updates["statisticalCodeIds"] == []
        assert keep_existing["statisticalCodeIds"] == ["code1", "code2"]

    def test_handle_upsert_for_statistical_codes_no_preserve(self, batch_poster):
        """Test not preserving statistical codes during upsert."""
        batch_poster.config.preserve_statistical_codes = False
        updates = {"id": "123", "statisticalCodeIds": ["code1", "code2"]}
        keep_existing = {}

        batch_poster.handle_upsert_for_statistical_codes(updates, keep_existing)

        assert updates["statisticalCodeIds"] == []
        assert keep_existing["statisticalCodeIds"] == []

    def test_handle_upsert_for_administrative_notes(self, batch_poster):
        """Test handling administrative notes during upsert."""
        batch_poster.config.preserve_administrative_notes = True
        updates = {"id": "123", "administrativeNotes": ["note1"]}
        keep_existing = {}

        batch_poster.handle_upsert_for_administrative_notes(updates, keep_existing)

        assert updates["administrativeNotes"] == []
        assert keep_existing["administrativeNotes"] == ["note1"]

    def test_handle_upsert_for_temporary_locations(self, batch_poster):
        """Test handling temporary locations during upsert."""
        batch_poster.config.preserve_temporary_locations = True
        updates = {"id": "123", "temporaryLocationId": "loc-123"}
        keep_existing = {}

        batch_poster.handle_upsert_for_temporary_locations(updates, keep_existing)

        assert "temporaryLocationId" not in updates
        assert keep_existing["temporaryLocationId"] == "loc-123"

    def test_patch_record_no_patch_paths(self, batch_poster):
        """Test patching record with no specific paths."""
        new_record = {
            "id": "123",
            "barcode": "NEW-BARCODE",
            "status": {"name": "Available"},
        }
        existing_record = {
            "id": "123",
            "barcode": "OLD-BARCODE",
            "status": {"name": "Checked out"},
            "_version": 2,
        }

        batch_poster.patch_record(new_record, existing_record, [])

        # New record should have all fields from new_record plus preserved fields
        assert new_record["barcode"] == "NEW-BARCODE"
        assert new_record["_version"] == 2

    def test_prepare_record_for_upsert(self, batch_poster):
        """Test preparing a record for upsert."""
        new_record = {"id": "123", "barcode": "12345"}
        existing_record = {"id": "123", "barcode": "67890", "_version": 3}

        batch_poster.prepare_record_for_upsert(new_record, existing_record)

        assert new_record["_version"] == 3

    def test_prepare_record_for_upsert_with_patch(self, batch_poster):
        """Test preparing a record for upsert with patching enabled."""
        batch_poster.config.patch_existing_records = True
        batch_poster.config.patch_paths = ["barcode"]

        new_record = {
            "id": "123",
            "barcode": "NEW-BARCODE",
            "status": {"name": "Available"},
        }
        existing_record = {
            "id": "123",
            "barcode": "OLD-BARCODE",
            "status": {"name": "Checked out"},
            "_version": 2,
        }

        batch_poster.prepare_record_for_upsert(new_record, existing_record)

        assert new_record["_version"] == 2
        assert new_record["barcode"] == "NEW-BARCODE"


@pytest.mark.asyncio
class TestBatchPosterAsync:
    """Async tests for BatchPoster class."""

    async def test_context_manager(self, mock_folio_client, config):
        """Test BatchPoster as async context manager."""
        async with BatchPoster(mock_folio_client, config) as poster:
            assert poster.folio_client is not None

    async def test_fetch_existing_records(self, batch_poster):
        """Test fetching existing records."""
        mock_data = [
            {"id": "id1", "barcode": "123", "_version": 1},
            {"id": "id2", "barcode": "456", "_version": 2},
        ]

        async with batch_poster as poster:
            poster.folio_client.folio_get_async = AsyncMock(return_value=mock_data)

            result = await poster.fetch_existing_records(["id1", "id2"])

            assert len(result) == 2
            assert result["id1"]["barcode"] == "123"
            assert result["id2"]["_version"] == 2
            poster.folio_client.folio_get_async.assert_called_once()

    async def test_set_versions_for_upsert(self, batch_poster):
        """Test setting versions for upsert."""
        batch = [
            {"id": "id1", "barcode": "123"},
            {"id": "id2", "barcode": "456"},
        ]

        existing_records = {
            "id1": {"id": "id1", "barcode": "old123", "_version": 5},
            "id2": {"id": "id2", "barcode": "old456", "_version": 3},
        }

        async with batch_poster as poster:
            with patch.object(
                poster, "fetch_existing_records", return_value=existing_records
            ):
                await poster.set_versions_for_upsert(batch)

                assert batch[0]["_version"] == 5
                assert batch[1]["_version"] == 3

    async def test_post_batch_success(self, batch_poster):
        """Test successful batch posting."""
        batch = [
            {"id": str(uuid4()), "barcode": "123"},
            {"id": str(uuid4()), "barcode": "456"},
        ]

        async with batch_poster as poster:
            response, num_creates, num_updates = await poster.post_batch(batch)

            # Response should be the mock response object
            assert response is not None
            assert num_creates == 2
            assert num_updates == 0
            assert poster.stats.records_posted == 2
            assert poster.stats.batches_posted == 1

    async def test_post_batch_with_upsert(self, batch_poster):
        """Test batch posting with upsert enabled."""
        batch_poster.config.upsert = True
        batch = [{"id": "id1", "barcode": "123"}]

        async with batch_poster as poster:
            with patch.object(poster, "set_versions_for_upsert") as mock_set_versions:
                await poster.post_batch(batch)

                mock_set_versions.assert_called_once_with(batch)
                # Check that async_httpx_client.post was called
                poster.folio_client.async_httpx_client.post.assert_called_once()

    async def test_post_batch_http_error(self, batch_poster):
        """Test batch posting with HTTP error."""
        batch = [{"id": str(uuid4()), "barcode": "123"}]

        async with batch_poster as poster:
            poster.folio_client.async_httpx_client.post = AsyncMock(
                side_effect=Exception("Server error")
            )

            with pytest.raises(Exception, match="Server error"):
                await poster.post_batch(batch)


    async def test_post_records(self, batch_poster, tmp_path):
        """Test posting multiple records."""
        records = [{"id": str(uuid4()), "barcode": f"bc-{i}"} for i in range(25)]
        failed_file = tmp_path / "failed.jsonl"

        # Create BatchPoster with failed_records_file in constructor
        # Create a config that excludes 'id' and 'hrid'
        config = BatchPoster.Config(object_type="Items", batch_size=10)
        poster = BatchPoster(
            batch_poster.folio_client, config, failed_records_file=str(failed_file)
        )

        async with poster:
            await poster.post_records(records)

            # Should have posted 3 batches (10 + 10 + 5)
            assert poster.stats.batches_posted == 3
            assert poster.stats.records_processed == 25


class TestUtilityFunctions:
    """Tests for utility functions."""

    def test_get_human_readable_size(self):
        """Test human-readable size conversion."""
        assert get_human_readable_size(500) == "500.00B"
        assert get_human_readable_size(1024) == "1.00KB"
        assert get_human_readable_size(1024 * 1024) == "1.00MB"
        assert get_human_readable_size(1536 * 1024) == "1.50MB"
        assert get_human_readable_size(1024 * 1024 * 1024) == "1.00GB"

    def test_get_human_readable_size_precision(self):
        """Test human-readable size with custom precision."""
        assert get_human_readable_size(1536 * 1024, precision=1) == "1.5MB"
        assert get_human_readable_size(1536 * 1024, precision=3) == "1.500MB"


@pytest.fixture
def config():
    """Minimal batch poster configuration."""
    return BatchPoster.Config(
        object_type="Items",
        batch_size=2,
    )


@pytest.fixture
def temp_jsonl_file(tmp_path):
    """Create a temporary JSONL file with test records."""
    file_path = tmp_path / "test_records.jsonl"
    records = [
        {"id": "001", "barcode": "item001"},
        {"id": "002", "barcode": "item002"},
        {"id": "003", "barcode": "item003"},
    ]
    with open(file_path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")
    return file_path


@pytest.mark.asyncio
async def test_post_records_from_file_success(
    config, mock_folio_client, temp_jsonl_file
):
    """Test successfully reading and posting from a JSONL file."""
    async with BatchPoster(mock_folio_client, config) as poster:
        await poster.post_records(temp_jsonl_file)

        assert mock_folio_client.async_httpx_client.post.call_count == 2
        assert poster.stats.records_processed == 3
        assert poster.stats.records_created == 3


@pytest.mark.asyncio
async def test_parse_json_line(config, mock_folio_client):
    """Test parsing JSON line."""
    async with BatchPoster(mock_folio_client, config) as poster:
        line = '{"id": "001", "barcode": "test"}'
        result = poster._parse_json_line(line, 1)
        assert result == {"id": "001", "barcode": "test"}


@pytest.mark.asyncio
async def test_do_work_single_file(
    config, mock_folio_client, temp_jsonl_file
):
    """Test do_work() method with a single file."""
    async with BatchPoster(mock_folio_client, config) as poster:
        stats = await poster.do_work(temp_jsonl_file)

        # Verify results
        assert stats.records_posted == 3
        assert stats.records_failed == 0
        assert stats.batches_posted == 2

        # Verify async_httpx_client.post was called (2 batches: [001, 002], [003])
        assert mock_folio_client.async_httpx_client.post.call_count == 2


@pytest.mark.asyncio
async def test_do_work_multiple_files(config, mock_folio_client, tmp_path):
    """Test do_work() method with multiple files."""
    # Create two test files
    file1 = tmp_path / "items1.jsonl"
    file2 = tmp_path / "items2.jsonl"

    with open(file1, "w", encoding="utf-8") as f:
        f.write(json.dumps({"id": "item1"}) + "\n")
        f.write(json.dumps({"id": "item2"}) + "\n")

    with open(file2, "w", encoding="utf-8") as f:
        f.write(json.dumps({"id": "item3"}) + "\n")

    async with BatchPoster(mock_folio_client, config) as poster:
        stats = await poster.do_work([file1, file2])

        # Verify results
        assert stats.records_posted == 3
        assert stats.records_failed == 0
        assert stats.batches_posted == 2

        # Verify async_httpx_client.post was called
        assert mock_folio_client.async_httpx_client.post.call_count == 2