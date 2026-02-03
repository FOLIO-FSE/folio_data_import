from unittest.mock import Mock, patch
from folio_data_import.MARCDataImport import MARCImportJob
from folioclient import FolioClient
import pytest



@pytest.fixture
def folio_client():
    folio_client = Mock(spec=FolioClient)
    return folio_client


@pytest.fixture
def marc_import_job(folio_client):
    marc_import_job = Mock(spec=MARCImportJob)
    return marc_import_job


class TestRemoveIfEmpty:
    """Test suite for the _remove_if_empty static method."""

    def test_remove_empty_file_with_path_object(self, tmp_path):
        """Test that an empty file is removed when passed as Path object."""
        empty_file = tmp_path / "empty.txt"
        empty_file.touch()
        
        with patch('folio_data_import.MARCDataImport.logger') as mock_logger:
            MARCImportJob._remove_if_empty(empty_file)
        
        assert not empty_file.exists()
        mock_logger.info.assert_called_once_with("Removed empty file: empty.txt")

    def test_remove_empty_file_with_string_path(self, tmp_path):
        """Test that an empty file is removed when passed as string path."""
        empty_file = tmp_path / "empty.txt"
        empty_file.touch()
        
        with patch('folio_data_import.MARCDataImport.logger') as mock_logger:
            MARCImportJob._remove_if_empty(str(empty_file))
        
        assert not empty_file.exists()
        mock_logger.info.assert_called_once_with("Removed empty file: empty.txt")

    def test_remove_empty_file_with_custom_message(self, tmp_path):
        """Test that custom log message is used when provided."""
        empty_file = tmp_path / "empty.txt"
        empty_file.touch()
        custom_message = "Custom message: file removed"
        
        with patch('folio_data_import.MARCDataImport.logger') as mock_logger:
            MARCImportJob._remove_if_empty(empty_file, custom_message)
        
        assert not empty_file.exists()
        mock_logger.info.assert_called_once_with(custom_message)

    def test_keep_non_empty_file(self, tmp_path):
        """Test that a non-empty file is not removed."""
        non_empty_file = tmp_path / "non_empty.txt"
        non_empty_file.write_text("content")
        
        with patch('folio_data_import.MARCDataImport.logger') as mock_logger:
            MARCImportJob._remove_if_empty(non_empty_file)
        
        assert non_empty_file.exists()
        mock_logger.info.assert_not_called()

    def test_handle_nonexistent_file(self, tmp_path):
        """Test that FileNotFoundError is handled gracefully."""
        nonexistent_file = tmp_path / "does_not_exist.txt"
        
        with patch('folio_data_import.MARCDataImport.logger') as mock_logger:
            # Should not raise an exception
            MARCImportJob._remove_if_empty(nonexistent_file)
        
        mock_logger.info.assert_not_called()

    def test_zero_byte_file_is_considered_empty(self, tmp_path):
        """Test that a file with 0 bytes is considered empty."""
        zero_byte_file = tmp_path / "zero.txt"
        zero_byte_file.touch()
        assert zero_byte_file.stat().st_size == 0
        
        with patch('folio_data_import.MARCDataImport.logger') as mock_logger:
            MARCImportJob._remove_if_empty(zero_byte_file)
        
        assert not zero_byte_file.exists()
        mock_logger.info.assert_called_once()


class TestWrapUp:
    """Test suite for the wrap_up method."""

    @pytest.mark.asyncio
    async def test_wrap_up_removes_empty_files(self, tmp_path, folio_client):
        """Test that wrap_up removes empty bad_records and failed_batches files."""
        bad_records_file = tmp_path / "bad_records.jsonl"
        bad_records_file.touch()
        failed_batches_file = tmp_path / "failed_batches.jsonl"
        failed_batches_file.touch()
        job_ids_file = tmp_path / "job_ids.txt"
        
        # Create a minimal MARCImportJob instance
        from types import SimpleNamespace
        
        config = SimpleNamespace(
            okapi_url="http://test",
            tenant_id="test",
            username="test",
            password="test",
            data_source_path=str(tmp_path),
            split_size=1000,
            split_offset=0,
            let_summary_fail=False,
            marc_record_preprocessors="",
            preprocessors_args={},
            job_ids_file_path=str(job_ids_file),
            marc_files=[tmp_path / "test.mrc"],
            no_progress=True,
        )
        
        with patch('folio_data_import.MARCDataImport.logger') as mock_logger:
            job = MARCImportJob(folio_client, config)
            job.bad_records_file = SimpleNamespace(name=str(bad_records_file))
            job.failed_batches_file = SimpleNamespace(name=str(failed_batches_file))
            job.job_ids = ["job1", "job2"]
            job.total_records_sent = 100
            
            await job.wrap_up()
        
        # Verify empty files were removed
        assert not bad_records_file.exists()
        assert not failed_batches_file.exists()
        
        # Verify job IDs were written
        assert job_ids_file.exists()
        assert job_ids_file.read_text() == "job1\njob2\n"
        
        # Verify logging
        assert any("No bad records found" in str(call) for call in mock_logger.info.call_args_list)
        assert any("No failed batches" in str(call) for call in mock_logger.info.call_args_list)
        assert any("Writing job IDs to" in str(call) for call in mock_logger.info.call_args_list)
        assert any("Import complete" in str(call) for call in mock_logger.info.call_args_list)

    @pytest.mark.asyncio
    async def test_wrap_up_keeps_non_empty_files(self, tmp_path, folio_client):
        """Test that wrap_up keeps non-empty bad_records and failed_batches files."""
        bad_records_file = tmp_path / "bad_records.jsonl"
        bad_records_file.write_text('{"error": "test"}')
        failed_batches_file = tmp_path / "failed_batches.jsonl"
        failed_batches_file.write_text('{"batch": "failed"}')
        job_ids_file = tmp_path / "job_ids.txt"
        
        from types import SimpleNamespace
        
        config = SimpleNamespace(
            okapi_url="http://test",
            tenant_id="test",
            username="test",
            password="test",
            data_source_path=str(tmp_path),
            split_size=1000,
            split_offset=0,
            let_summary_fail=False,
            marc_record_preprocessors="",
            preprocessors_args={},
            job_ids_file_path=str(job_ids_file),
            marc_files=[tmp_path / "test.mrc"],
            no_progress=True,
        )
        
        with patch('folio_data_import.MARCDataImport.logger'):
            job = MARCImportJob(folio_client, config)
            job.bad_records_file = SimpleNamespace(name=str(bad_records_file))
            job.failed_batches_file = SimpleNamespace(name=str(failed_batches_file))
            job.job_ids = []
            job.total_records_sent = 50
            
            await job.wrap_up()
        
        # Verify non-empty files were kept
        assert bad_records_file.exists()
        assert failed_batches_file.exists()


class TestMoveAfterContext:
    """Tests that files are moved immediately after processing (within context)."""

    @pytest.mark.asyncio
    async def test_process_records_close_before_move(self, tmp_path, folio_client):
        """Test that close() is called before move_file_to_complete()."""
        source_file = tmp_path / "test.mrc"
        source_file.write_bytes(b"dummy content")

        from types import SimpleNamespace
        config = SimpleNamespace(
            import_profile_name="Test Profile",
            batch_size=10,
            batch_delay=0.0,
            marc_record_preprocessors="",
            preprocessors_args={},
            no_progress=True,
            no_summary=True,
            let_summary_fail=False,
            split_files=False,
            split_size=1000,
            split_offset=0,
            job_ids_file_path=None,
            marc_files=[source_file],
        )

        job = MARCImportJob(folio_client, config)
        job.task_sent = "task_sent"
        job.task_imported = "task_imported"
        job.reporter = Mock()
        job.record_batch = []
        job.finished = False

        call_order = []

        # Track when close() and move are called
        def track_close(original_close):
            def wrapper():
                call_order.append("close")
                return original_close()
            return wrapper

        def track_move(original_move):
            def wrapper(file_path):
                call_order.append("move")
                return original_move(file_path)
            return wrapper

        async def mock_process_record_batch(batch_payload):
            pass

        with (
            patch.object(job, "process_record_batch", mock_process_record_batch),
            patch.object(job, "move_file_to_complete", wraps=track_move(job.move_file_to_complete)),
        ):
            with open(source_file, "rb") as f:
                # Mock MARCReader to avoid actual parsing
                with patch("folio_data_import.MARCDataImport.pymarc.MARCReader") as mock_reader:
                    mock_reader.return_value = []  # Empty iterator, no records
                    
                    # Wrap the close method to track calls
                    f.close = track_close(f.close)
                    
                    await job.process_records([f], total_records=0)

        # close should be called before move
        assert "close" in call_order, "File close() was not called"
        assert "move" in call_order, "move_file_to_complete() was not called"
        # Verify order: close happens before move
        if "close" in call_order and "move" in call_order:
            assert call_order.index("close") < call_order.index("move"), "close must be called before move"

    @pytest.mark.asyncio
    async def test_wrap_up_removes_empty_job_ids_file(self, tmp_path, folio_client):
        """Test that wrap_up removes empty job_ids file with custom message."""
        bad_records_file = tmp_path / "bad_records.jsonl"
        bad_records_file.touch()
        failed_batches_file = tmp_path / "failed_batches.jsonl"
        failed_batches_file.touch()
        job_ids_file = tmp_path / "job_ids.txt"
        
        from types import SimpleNamespace
        
        config = SimpleNamespace(
            okapi_url="http://test",
            tenant_id="test",
            username="test",
            password="test",
            data_source_path=str(tmp_path),
            split_size=1000,
            split_offset=0,
            let_summary_fail=False,
            marc_record_preprocessors="",
            preprocessors_args={},
            job_ids_file_path=str(job_ids_file),
            marc_files=[tmp_path / "test.mrc"],
            no_progress=True,
        )
        
        with patch('folio_data_import.MARCDataImport.logger') as mock_logger:
            job = MARCImportJob(folio_client, config)
            job.bad_records_file = SimpleNamespace(name=str(bad_records_file))
            job.failed_batches_file = SimpleNamespace(name=str(failed_batches_file))
            job.job_ids = []
            job.total_records_sent = 0
            
            await job.wrap_up()
        
        # Verify empty job_ids file was removed
        assert not job_ids_file.exists()
        
        # Verify custom log message was used
        assert any("No job IDs to write" in str(call) for call in mock_logger.info.call_args_list)
