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
    return BatchPoster.Config(object_type="Items")


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


class TestRerunFailedRecords:
    """Tests for rerun_failed_records_one_by_one method."""

    @pytest.mark.asyncio
    async def test_rerun_no_failed_records_file(self, config, mock_folio_client):
        """Test rerun with no failed records file configured.
        
        Should log warning and return without error - no assertions needed.
        """
        async with BatchPoster(mock_folio_client, config) as poster:
            await poster.rerun_failed_records_one_by_one()

    @pytest.mark.asyncio
    async def test_rerun_empty_failed_records_file(
        self, config, mock_folio_client, tmp_path
    ):
        """Test rerun with empty failed records file."""
        failed_file = tmp_path / "failed.jsonl"
        failed_file.write_text("")

        async with BatchPoster(mock_folio_client, config) as poster:
            # Manually set the path (don't use failed_records_file param which truncates)
            poster._failed_records_path = failed_file
            poster._owns_file_handle = False
            await poster.rerun_failed_records_one_by_one()
            # Should return early without processing

    @pytest.mark.asyncio
    async def test_rerun_all_succeed(self, config, mock_folio_client, tmp_path):
        """Test rerun where all records succeed on retry."""
        failed_file = tmp_path / "failed.jsonl"
        failed_records = [
            {"id": "fail1", "barcode": "bc1"},
            {"id": "fail2", "barcode": "bc2"},
        ]
        with open(failed_file, "w", encoding="utf-8") as f:
            for record in failed_records:
                f.write(json.dumps(record) + "\n")

        async with BatchPoster(mock_folio_client, config) as poster:
            # Manually set the path (don't use failed_records_file param which truncates)
            poster._failed_records_path = failed_file
            poster._owns_file_handle = False

            await poster.rerun_failed_records_one_by_one()

            # Both records should have been reprocessed
            assert poster.stats.records_posted == 2
            assert poster.stats.records_failed == 0

            # Rerun file should be removed (empty)
            rerun_file = tmp_path / "failed_rerun.jsonl"
            assert not rerun_file.exists()

    @pytest.mark.asyncio
    async def test_rerun_some_still_fail(self, config, mock_folio_client, tmp_path):
        """Test rerun where some records still fail."""
        failed_file = tmp_path / "failed.jsonl"
        failed_records = [
            {"id": "fail1", "barcode": "bc1"},
            {"id": "fail2", "barcode": "bc2"},
            {"id": "fail3", "barcode": "bc3"},
        ]
        with open(failed_file, "w", encoding="utf-8") as f:
            for record in failed_records:
                f.write(json.dumps(record) + "\n")

        # Make second record fail again
        call_count = 0

        async def mock_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise Exception("Still failing")
            mock_response = Mock()
            mock_response.json = Mock(return_value={})
            mock_response.raise_for_status = Mock()
            mock_response.elapsed.total_seconds = Mock(return_value=0.1)
            mock_request = Mock()
            mock_request.method = "POST"
            mock_request.url = "https://test"
            mock_request.headers = {}
            mock_request.content = b"{}"
            mock_response.request = mock_request
            return mock_response

        mock_folio_client.async_httpx_client.post = mock_post

        async with BatchPoster(mock_folio_client, config) as poster:
            # Manually set the path (don't use failed_records_file param which truncates)
            poster._failed_records_path = failed_file
            poster._owns_file_handle = False

            await poster.rerun_failed_records_one_by_one()

            # 2 succeeded, 1 still failed (rerun failures tracked separately, not in stats)
            assert poster.stats.records_posted == 2

            # Rerun file should exist with the still-failing record
            rerun_file = tmp_path / "failed_rerun.jsonl"
            assert rerun_file.exists()
            with open(rerun_file, "r", encoding="utf-8") as f:
                still_failing = [json.loads(line) for line in f if line.strip()]
            assert len(still_failing) == 1
            assert still_failing[0]["id"] == "fail2"

    @pytest.mark.asyncio
    async def test_rerun_preserves_original_file(
        self, config, mock_folio_client, tmp_path
    ):
        """Test that rerun preserves the original failed records file."""
        failed_file = tmp_path / "failed.jsonl"
        failed_records = [{"id": "fail1", "barcode": "bc1"}]
        with open(failed_file, "w", encoding="utf-8") as f:
            for record in failed_records:
                f.write(json.dumps(record) + "\n")

        original_content = failed_file.read_text()

        async with BatchPoster(mock_folio_client, config) as poster:
            # Manually set the path (don't use failed_records_file param which truncates)
            poster._failed_records_path = failed_file
            poster._owns_file_handle = False

            await poster.rerun_failed_records_one_by_one()

            # Original file should still exist and be unchanged
            assert failed_file.exists()
            assert failed_file.read_text() == original_content

    @pytest.mark.asyncio
    async def test_rerun_creates_file_with_rerun_suffix(
        self, config, mock_folio_client, tmp_path
    ):
        """Test that rerun creates new file with _rerun suffix."""
        failed_file = tmp_path / "my_failed_items.jsonl"
        failed_records = [{"id": "fail1", "barcode": "bc1"}]
        with open(failed_file, "w", encoding="utf-8") as f:
            for record in failed_records:
                f.write(json.dumps(record) + "\n")

        # Make the record fail again
        mock_folio_client.async_httpx_client.post = AsyncMock(
            side_effect=Exception("Still failing")
        )

        async with BatchPoster(mock_folio_client, config) as poster:
            # Manually set the path (don't use failed_records_file param which truncates)
            poster._failed_records_path = failed_file
            poster._owns_file_handle = False

            await poster.rerun_failed_records_one_by_one()

            # New file should have _rerun suffix
            rerun_file = tmp_path / "my_failed_items_rerun.jsonl"
            assert rerun_file.exists()

    @pytest.mark.asyncio
    async def test_rerun_handles_invalid_json_lines(
        self, config, mock_folio_client, tmp_path
    ):
        """Test that rerun handles invalid JSON lines gracefully."""
        failed_file = tmp_path / "failed.jsonl"
        with open(failed_file, "w", encoding="utf-8") as f:
            f.write('{"id": "valid1", "barcode": "bc1"}\n')
            f.write("not valid json\n")
            f.write('{"id": "valid2", "barcode": "bc2"}\n')

        async with BatchPoster(mock_folio_client, config) as poster:
            # Manually set the path (don't use failed_records_file param which truncates)
            poster._failed_records_path = failed_file
            poster._owns_file_handle = False

            await poster.rerun_failed_records_one_by_one()

            # Valid records should be posted, invalid should be in rerun file
            # (rerun failures tracked separately, not in stats)
            assert poster.stats.records_posted == 2

            rerun_file = tmp_path / "failed_rerun.jsonl"
            assert rerun_file.exists()
            with open(rerun_file, "r", encoding="utf-8") as f:
                still_failing = [line.strip() for line in f if line.strip()]
            assert len(still_failing) == 1
            assert still_failing[0] == "not valid json"

    @pytest.mark.asyncio
    async def test_rerun_updates_progress_reporter(
        self, config, mock_folio_client, tmp_path
    ):
        """Test that rerun updates the progress reporter."""
        from folio_data_import._progress import NoOpProgressReporter

        failed_file = tmp_path / "failed.jsonl"
        failed_records = [
            {"id": "fail1", "barcode": "bc1"},
            {"id": "fail2", "barcode": "bc2"},
        ]
        with open(failed_file, "w", encoding="utf-8") as f:
            for record in failed_records:
                f.write(json.dumps(record) + "\n")

        # Create a mock reporter to track calls
        mock_reporter = Mock(spec=NoOpProgressReporter)
        mock_reporter.start_task = Mock(return_value="rerun_task_id")
        mock_reporter.update_task = Mock()
        mock_reporter.finish_task = Mock()
        mock_reporter.__enter__ = Mock(return_value=mock_reporter)
        mock_reporter.__exit__ = Mock(return_value=None)

        async with BatchPoster(
            mock_folio_client,
            config,
            reporter=mock_reporter,
        ) as poster:
            # Manually set the path (don't use failed_records_file param which truncates)
            poster._failed_records_path = failed_file
            poster._owns_file_handle = False

            await poster.rerun_failed_records_one_by_one()

            # Progress reporter should have been used
            mock_reporter.start_task.assert_called_once()
            assert mock_reporter.update_task.call_count == 2  # Once per record
            mock_reporter.finish_task.assert_called_once()


class TestShadowInstances:
    """Tests for ShadowInstances object type support."""

    def test_get_api_info_shadow_instances(self):
        """Test that ShadowInstances returns valid API info."""
        info = get_api_info("ShadowInstances")
        assert info["object_name"] == "instances"
        assert info["api_endpoint"] == "/instance-storage/batch/synchronous"
        assert info["supports_upsert"] is True

    def test_shadow_instances_config(self):
        """Test creating config with ShadowInstances object type."""
        config = BatchPoster.Config(object_type="ShadowInstances")
        assert config.object_type == "ShadowInstances"


class TestSetConsortiumSource:
    """Tests for set_consortium_source static method."""

    def test_convert_marc_to_consortium_marc(self):
        """Test MARC source is converted to CONSORTIUM-MARC."""
        record = {"id": "123", "source": "MARC"}
        BatchPoster.set_consortium_source(record)
        assert record["source"] == "CONSORTIUM-MARC"

    def test_convert_folio_to_consortium_folio(self):
        """Test FOLIO source is converted to CONSORTIUM-FOLIO."""
        record = {"id": "123", "source": "FOLIO"}
        BatchPoster.set_consortium_source(record)
        assert record["source"] == "CONSORTIUM-FOLIO"

    def test_no_conversion_for_other_sources(self):
        """Test that other source values are not modified."""
        record = {"id": "123", "source": "LINKED_DATA"}
        BatchPoster.set_consortium_source(record)
        assert record["source"] == "LINKED_DATA"

    def test_no_conversion_when_source_missing(self):
        """Test that records without source field are not modified."""
        record = {"id": "123", "title": "Test"}
        BatchPoster.set_consortium_source(record)
        assert "source" not in record

    def test_no_conversion_for_empty_source(self):
        """Test that empty source is not modified."""
        record = {"id": "123", "source": ""}
        BatchPoster.set_consortium_source(record)
        assert record["source"] == ""


class TestKeepExistingFields:
    """Tests for keep_existing_fields method preserving hrid and lastCheckIn."""

    @pytest.mark.asyncio
    async def test_always_preserves_hrid(self, mock_folio_client):
        """Test that hrid is always preserved from existing record."""
        config = BatchPoster.Config(object_type="Items")
        async with BatchPoster(mock_folio_client, config) as poster:
            updates = {"id": "123", "barcode": "NEW"}
            existing = {"id": "123", "hrid": "it00000001", "barcode": "OLD"}

            poster.keep_existing_fields(updates, existing)

            assert updates["hrid"] == "it00000001"

    @pytest.mark.asyncio
    async def test_always_preserves_last_check_in(self, mock_folio_client):
        """Test that lastCheckIn is always preserved from existing record."""
        config = BatchPoster.Config(object_type="Items")
        async with BatchPoster(mock_folio_client, config) as poster:
            updates = {"id": "123", "barcode": "NEW"}
            existing = {
                "id": "123",
                "lastCheckIn": {"dateTime": "2024-01-15T10:30:00Z"},
                "barcode": "OLD",
            }

            poster.keep_existing_fields(updates, existing)

            assert updates["lastCheckIn"] == {"dateTime": "2024-01-15T10:30:00Z"}

    @pytest.mark.asyncio
    async def test_preserves_status_when_configured(self, mock_folio_client):
        """Test that status is preserved when preserve_item_status is True."""
        config = BatchPoster.Config(object_type="Items", preserve_item_status=True)
        async with BatchPoster(mock_folio_client, config) as poster:
            updates = {"id": "123", "status": {"name": "Available"}}
            existing = {"id": "123", "status": {"name": "Checked out"}}

            poster.keep_existing_fields(updates, existing)

            assert updates["status"] == {"name": "Checked out"}

    @pytest.mark.asyncio
    async def test_does_not_preserve_status_when_not_configured(self, mock_folio_client):
        """Test that status is not preserved when preserve_item_status is False."""
        config = BatchPoster.Config(object_type="Items", preserve_item_status=False)
        async with BatchPoster(mock_folio_client, config) as poster:
            updates = {"id": "123", "status": {"name": "Available"}}
            existing = {"id": "123", "status": {"name": "Checked out"}}

            poster.keep_existing_fields(updates, existing)

            # Status should remain as the new value
            assert updates["status"] == {"name": "Available"}

    @pytest.mark.asyncio
    async def test_handles_missing_fields_gracefully(self, mock_folio_client):
        """Test that missing fields in existing record don't cause errors."""
        config = BatchPoster.Config(object_type="Items")
        async with BatchPoster(mock_folio_client, config) as poster:
            updates = {"id": "123", "barcode": "NEW"}
            existing = {"id": "123", "barcode": "OLD"}  # No hrid or lastCheckIn

            poster.keep_existing_fields(updates, existing)

            # Should not add fields that don't exist
            assert "hrid" not in updates
            assert "lastCheckIn" not in updates


class TestMARCSourceProtection:
    """Tests for MARC source protection in prepare_record_for_upsert."""

    @pytest.mark.asyncio
    async def test_marc_record_restricts_patch_paths(self, mock_folio_client):
        """Test that MARC-sourced records have restricted patch paths."""
        config = BatchPoster.Config(
            object_type="Instances",
            patch_existing_records=True,
            patch_paths=["title", "contributors", "discoverySuppress"],
        )
        async with BatchPoster(mock_folio_client, config) as poster:
            new_record = {
                "id": "123",
                "title": "New Title",
                "contributors": [{"name": "New Author"}],
                "discoverySuppress": True,
            }
            existing_record = {
                "id": "123",
                "source": "MARC",
                "title": "Original Title",
                "contributors": [{"name": "Original Author"}],
                "discoverySuppress": False,
                "_version": 5,
            }

            poster.prepare_record_for_upsert(new_record, existing_record)

            # Version should be set
            assert new_record["_version"] == 5
            # discoverySuppress should be updated (allowed for MARC)
            assert new_record["discoverySuppress"] is True
            # Title should NOT be updated (not allowed for MARC)
            assert new_record["title"] == "Original Title"

    @pytest.mark.asyncio
    async def test_marc_record_allows_statistical_codes(self, mock_folio_client):
        """Test that MARC records allow statisticalCodeIds to be patched."""
        config = BatchPoster.Config(
            object_type="Instances",
            patch_existing_records=True,
            patch_paths=["statisticalCodeIds"],
        )
        async with BatchPoster(mock_folio_client, config) as poster:
            new_record = {
                "id": "123",
                "statisticalCodeIds": ["stat-code-1", "stat-code-2"],
            }
            existing_record = {
                "id": "123",
                "source": "MARC",
                "statisticalCodeIds": [],
                "_version": 3,
            }

            poster.prepare_record_for_upsert(new_record, existing_record)

            # statisticalCodeIds should be patchable
            assert "stat-code-1" in new_record.get("statisticalCodeIds", [])

    @pytest.mark.asyncio
    async def test_consortium_marc_treated_as_marc(self, mock_folio_client):
        """Test that CONSORTIUM-MARC source is also protected."""
        config = BatchPoster.Config(
            object_type="Instances",
            patch_existing_records=True,
            patch_paths=["title"],
        )
        async with BatchPoster(mock_folio_client, config) as poster:
            new_record = {"id": "123", "title": "New Title"}
            existing_record = {
                "id": "123",
                "source": "CONSORTIUM-MARC",
                "title": "Original Title",
                "_version": 2,
            }

            poster.prepare_record_for_upsert(new_record, existing_record)

            # Title should NOT be updated for CONSORTIUM-MARC
            assert new_record["title"] == "Original Title"

    @pytest.mark.asyncio
    async def test_folio_source_allows_all_patches(self, mock_folio_client):
        """Test that FOLIO-sourced records allow all patches."""
        config = BatchPoster.Config(
            object_type="Instances",
            patch_existing_records=True,
            patch_paths=["title", "contributors"],
        )
        async with BatchPoster(mock_folio_client, config) as poster:
            new_record = {
                "id": "123",
                "title": "New Title",
                "contributors": [{"name": "New Author"}],
            }
            existing_record = {
                "id": "123",
                "source": "FOLIO",
                "title": "Original Title",
                "contributors": [{"name": "Original Author"}],
                "_version": 4,
            }

            poster.prepare_record_for_upsert(new_record, existing_record)

            # All fields should be patchable for FOLIO source
            assert new_record["title"] == "New Title"

    @pytest.mark.asyncio
    async def test_non_instance_types_not_affected(self, mock_folio_client):
        """Test that MARC protection only applies to Instances."""
        config = BatchPoster.Config(
            object_type="Items",
            patch_existing_records=True,
            patch_paths=["barcode"],
        )
        async with BatchPoster(mock_folio_client, config) as poster:
            new_record = {"id": "123", "barcode": "NEW-BARCODE"}
            existing_record = {
                "id": "123",
                "barcode": "OLD-BARCODE",
                "_version": 1,
            }

            poster.prepare_record_for_upsert(new_record, existing_record)

            # Items should allow all patches regardless of source
            assert new_record["barcode"] == "NEW-BARCODE"


@pytest.mark.asyncio
class TestShadowInstancesPostBatch:
    """Tests for ShadowInstances source conversion during post_batch."""

    async def test_shadow_instances_converts_source(self, mock_folio_client):
        """Test that ShadowInstances converts MARC to CONSORTIUM-MARC."""
        config = BatchPoster.Config(object_type="ShadowInstances")
        batch = [
            {"id": "1", "title": "Book 1", "source": "MARC"},
            {"id": "2", "title": "Book 2", "source": "FOLIO"},
        ]

        async with BatchPoster(mock_folio_client, config) as poster:
            await poster.post_batch(batch)

            # Verify the records were modified before posting
            assert batch[0]["source"] == "CONSORTIUM-MARC"
            assert batch[1]["source"] == "CONSORTIUM-FOLIO"

    async def test_regular_instances_does_not_convert_source(self, mock_folio_client):
        """Test that regular Instances does not convert source."""
        config = BatchPoster.Config(object_type="Instances")
        batch = [{"id": "1", "title": "Book 1", "source": "MARC"}]

        async with BatchPoster(mock_folio_client, config) as poster:
            await poster.post_batch(batch)

            # Source should remain unchanged for regular Instances
            assert batch[0]["source"] == "MARC"