"""Tests for progress reporting functionality."""

import json
from unittest.mock import MagicMock, Mock, patch

import pytest

from folio_data_import._progress import (
    REDIS_AVAILABLE,
    BaseProgressReporter,
    GenericStatsColumn,
    ItemsPerSecondColumn,
    NoOpProgressReporter,
    RedisProgressReporter,
    RichProgressReporter,
    TaskStatus,
)


# =============================================================================
# NoOpProgressReporter Tests
# =============================================================================


def test_noop_reporter_initialization():
    """Test NoOpProgressReporter initializes correctly."""
    reporter = NoOpProgressReporter()
    assert not reporter._enabled
    assert not reporter._active


def test_noop_reporter_context_manager():
    """Test NoOpProgressReporter context manager."""
    reporter = NoOpProgressReporter()
    with reporter:
        assert not reporter.is_active()


def test_noop_reporter_start_task():
    """Test NoOpProgressReporter start_task returns name."""
    reporter = NoOpProgressReporter()
    task_id = reporter.start_task("test_task", total=100)
    assert task_id == "test_task"


def test_noop_reporter_update_task():
    """Test NoOpProgressReporter update_task does nothing."""
    reporter = NoOpProgressReporter()
    # Should not raise any exceptions
    reporter.update_task("test_task", advance=10, created=5)


def test_noop_reporter_finish_task():
    """Test NoOpProgressReporter finish_task does nothing."""
    reporter = NoOpProgressReporter()
    # Should not raise any exceptions
    reporter.finish_task("test_task", TaskStatus.COMPLETED)


# =============================================================================
# RichProgressReporter Tests
# =============================================================================


def test_rich_reporter_initialization():
    """Test RichProgressReporter initializes correctly."""
    reporter = RichProgressReporter(enabled=True, show_speed=True, show_time=True)
    assert reporter._enabled
    assert reporter._show_speed
    assert reporter._show_time


def test_rich_reporter_disabled():
    """Test RichProgressReporter when disabled."""
    reporter = RichProgressReporter(enabled=False)
    with reporter:
        # When disabled, _active is True but _enabled is False so is_active() returns False
        assert reporter._active  # Context manager sets this
        assert not reporter._enabled  # But not enabled for display
        task_id = reporter.start_task("test", total=100)
        assert task_id == "test"


def test_rich_reporter_context_manager():
    """Test RichProgressReporter context manager."""
    reporter = RichProgressReporter()
    assert not reporter.is_active()

    with reporter:
        assert reporter.is_active()
        assert reporter._progress is not None

    assert not reporter.is_active()
    assert reporter._progress is None
def test_rich_reporter_start_task():
    """Test RichProgressReporter start_task."""
    reporter = RichProgressReporter()
    with reporter:
        task_id = reporter.start_task("users", total=100, description="Processing Users")
        assert task_id == "users"
        assert "users" in reporter._tasks
        assert reporter._tasks["users"]["total"] == 100


def test_rich_reporter_update_task():
    """Test RichProgressReporter update_task."""
    reporter = RichProgressReporter()
    with reporter:
        task_id = reporter.start_task("users", total=100)
        reporter.update_task(task_id, advance=10, created=5, updated=3, failed=1)
        
        stats = reporter.get_stats(task_id)
        assert stats["completed"] == 10
        assert stats["created"] == 5
        assert stats["updated"] == 3
        assert stats["failed"] == 1


def test_rich_reporter_finish_task():
    """Test RichProgressReporter finish_task."""
    reporter = RichProgressReporter()
    with reporter:
        task_id = reporter.start_task("users", total=10)
        for i in range(10):
            reporter.update_task(task_id, advance=1)
        reporter.finish_task(task_id, TaskStatus.COMPLETED)


def test_rich_reporter_multiple_tasks():
    """Test RichProgressReporter with multiple tasks."""
    reporter = RichProgressReporter()
    with reporter:
        task1 = reporter.start_task("task1", total=50)
        task2 = reporter.start_task("task2", total=100)
        
        reporter.update_task(task1, advance=25)
        reporter.update_task(task2, advance=50)
        
        assert reporter.get_stats(task1)["completed"] == 25
        assert reporter.get_stats(task2)["completed"] == 50


def test_rich_reporter_update_nonexistent_task():
    """Test RichProgressReporter handles nonexistent task gracefully."""
    reporter = RichProgressReporter()
    with reporter:
        # Should not raise an exception
        reporter.update_task("nonexistent", advance=10)


# =============================================================================
# RedisProgressReporter Tests
# =============================================================================


@pytest.mark.skipif(not REDIS_AVAILABLE, reason="Redis not installed")
def test_redis_reporter_initialization():
    """Test RedisProgressReporter initializes correctly."""
    with patch("folio_data_import._progress.redis") as mock_redis:
        mock_client = Mock()
        mock_redis.from_url.return_value = mock_client
        mock_client.set.return_value = True
        
        reporter = RedisProgressReporter(
            redis_url="redis://localhost:6379",
            session_id="test-session",
            ttl=3600
        )
        
        assert reporter._session_id == "test-session"
        assert reporter._ttl == 3600
        mock_redis.from_url.assert_called_once_with(
            "redis://localhost:6379", decode_responses=True
        )


@pytest.mark.skipif(not REDIS_AVAILABLE, reason="Redis not installed")
def test_redis_reporter_generates_session_id():
    """Test RedisProgressReporter generates session ID if not provided."""
    with patch("folio_data_import._progress.redis") as mock_redis:
        mock_client = Mock()
        mock_redis.from_url.return_value = mock_client
        mock_client.set.return_value = True
        
        reporter = RedisProgressReporter()
        
        assert reporter._session_id is not None
        assert len(reporter._session_id) > 0


@pytest.mark.skipif(not REDIS_AVAILABLE, reason="Redis not installed")
def test_redis_reporter_start_task():
    """Test RedisProgressReporter start_task."""
    with patch("folio_data_import._progress.redis") as mock_redis:
        mock_client = Mock()
        mock_redis.from_url.return_value = mock_client
        mock_client.set.return_value = True
        mock_client.get.return_value = json.dumps({
            "session_id": "test-session",
            "status": "pending",
            "tasks": {},
        })
        
        reporter = RedisProgressReporter(session_id="test-session")
        
        with reporter:
            task_id = reporter.start_task("users", total=100, description="Processing Users")
            assert task_id == "users"
            
            # Verify Redis was called to update the session
            calls = [call for call in mock_client.set.call_args_list]
            assert len(calls) >= 2  # Initial session + task start


@pytest.mark.skipif(not REDIS_AVAILABLE, reason="Redis not installed")
def test_redis_reporter_update_task():
    """Test RedisProgressReporter update_task."""
    with patch("folio_data_import._progress.redis") as mock_redis:
        mock_client = Mock()
        mock_redis.from_url.return_value = mock_client
        mock_client.set.return_value = True
        
        # Mock get to return session with task
        session_data = {
            "session_id": "test-session",
            "status": "running",
            "tasks": {
                "users": {
                    "name": "users",
                    "description": "Processing Users",
                    "total": 100,
                    "completed": 0,
                    "status": "running",
                    "stats": {"created": 0, "updated": 0, "failed": 0, "posted": 0},
                }
            },
        }
        mock_client.get.return_value = json.dumps(session_data)
        
        reporter = RedisProgressReporter(session_id="test-session")
        
        with reporter:
            task_id = reporter.start_task("users", total=100)
            reporter.update_task(task_id, advance=10, created=5, updated=3)
            
            stats = reporter.get_stats(task_id)
            assert stats["completed"] == 10
            assert stats["created"] == 5
            assert stats["updated"] == 3


@pytest.mark.skipif(not REDIS_AVAILABLE, reason="Redis not installed")
def test_redis_reporter_finish_task():
    """Test RedisProgressReporter finish_task."""
    with patch("folio_data_import._progress.redis") as mock_redis:
        mock_client = Mock()
        mock_redis.from_url.return_value = mock_client
        mock_client.set.return_value = True
        
        session_data = {
            "session_id": "test-session",
            "status": "running",
            "tasks": {
                "users": {
                    "name": "users",
                    "total": 100,
                    "completed": 100,
                    "status": "running",
                    "stats": {"created": 0, "updated": 0, "failed": 0, "posted": 0},
                }
            },
        }
        mock_client.get.return_value = json.dumps(session_data)
        
        reporter = RedisProgressReporter(session_id="test-session")
        
        with reporter:
            task_id = reporter.start_task("users", total=100)
            reporter.finish_task(task_id, TaskStatus.COMPLETED)


@pytest.mark.skipif(not REDIS_AVAILABLE, reason="Redis not installed")
def test_redis_reporter_get_session():
    """Test RedisProgressReporter.get_session class method."""
    with patch("folio_data_import._progress.redis") as mock_redis:
        mock_client = Mock()
        mock_redis.from_url.return_value = mock_client
        
        session_data = {
            "session_id": "test-session",
            "status": "running",
            "tasks": {},
        }
        mock_client.get.return_value = json.dumps(session_data)
        
        result = RedisProgressReporter.get_session("test-session")
        
        assert result["session_id"] == "test-session"
        assert result["status"] == "running"


@pytest.mark.skipif(not REDIS_AVAILABLE, reason="Redis not installed")
def test_redis_reporter_get_session_not_found():
    """Test RedisProgressReporter.get_session returns None if not found."""
    with patch("folio_data_import._progress.redis") as mock_redis:
        mock_client = Mock()
        mock_redis.from_url.return_value = mock_client
        mock_client.get.return_value = None
        
        result = RedisProgressReporter.get_session("nonexistent")
        
        assert result is None


@pytest.mark.skipif(not REDIS_AVAILABLE, reason="Redis not installed")
def test_redis_reporter_delete_session():
    """Test RedisProgressReporter.delete_session class method."""
    with patch("folio_data_import._progress.redis") as mock_redis:
        mock_client = Mock()
        mock_redis.from_url.return_value = mock_client
        mock_client.delete.return_value = 1
        
        result = RedisProgressReporter.delete_session("test-session")
        
        assert result is True
        mock_client.delete.assert_called_once_with("progress:session:test-session")


@pytest.mark.skipif(REDIS_AVAILABLE, reason="Test requires Redis to be unavailable")
def test_redis_reporter_raises_without_redis():
    """Test RedisProgressReporter raises ImportError when redis not available."""
    with pytest.raises(ImportError) as exc_info:
        RedisProgressReporter()
    
    assert "redis package" in str(exc_info.value).lower()


# =============================================================================
# Custom Column Tests
# =============================================================================


def test_items_per_second_column():
    """Test ItemsPerSecondColumn renders correctly."""
    from rich.progress import Task
    
    column = ItemsPerSecondColumn()
    
    # Mock task with speed
    task = Mock(spec=Task)
    task.speed = 42.7
    result = column.render(task)
    assert "43rec/s" in str(result)  # Rounds to 43
    
    # Mock task without speed
    task.speed = None
    result = column.render(task)
    assert "?" in str(result)


def test_generic_stats_column_with_stats():
    """Test GenericStatsColumn renders with statistics."""
    from rich.progress import Task
    
    column = GenericStatsColumn()
    
    task = Mock(spec=Task)
    task.fields = {
        "posted": 100,
        "created": 50,
        "updated": 30,
        "failed": 5,
    }
    
    result = column.render(task)
    text = str(result)
    assert "Posted: 100" in text
    assert "Created: 50" in text
    assert "Updated: 30" in text
    assert "Failed: 5" in text


def test_generic_stats_column_empty():
    """Test GenericStatsColumn returns empty text when no stats."""
    from rich.progress import Task
    
    column = GenericStatsColumn()
    
    task = Mock(spec=Task)
    task.fields = {}
    
    result = column.render(task)
    assert str(result) == ""


def test_generic_stats_column_zero_values():
    """Test GenericStatsColumn hides zero values."""
    from rich.progress import Task
    
    column = GenericStatsColumn()
    
    task = Mock(spec=Task)
    task.fields = {
        "posted": 0,
        "created": 10,
        "updated": 0,
    }
    
    result = column.render(task)
    text = str(result)
    assert "Created: 10" in text
    assert "Posted:" not in text
    assert "Updated:" not in text


# =============================================================================
# Integration Tests
# =============================================================================


def test_full_workflow_with_rich_reporter():
    """Test complete workflow with RichProgressReporter."""
    reporter = RichProgressReporter()
    
    with reporter:
        # Start multiple tasks
        task1 = reporter.start_task("users", total=100, description="Processing Users")
        task2 = reporter.start_task("items", total=200, description="Processing Items")
        
        # Update tasks - note that 'advance' accumulates but stats replace
        for i in range(10):
            reporter.update_task(task1, advance=10, created=5, updated=3, failed=2)
            reporter.update_task(task2, advance=20, posted=20, created=10, updated=8)
        
        # Finish tasks
        reporter.finish_task(task1, TaskStatus.COMPLETED)
        reporter.finish_task(task2, TaskStatus.COMPLETED)
        
        # Check final stats
        stats1 = reporter.get_stats(task1)
        assert stats1["completed"] == 100  # advance accumulated
        assert stats1["created"] == 50  # stats accumulated (10 iterations * 5)
        assert stats1["updated"] == 30  # stats accumulated (10 iterations * 3)
        
        stats2 = reporter.get_stats(task2)
        assert stats2["completed"] == 200  # advance accumulated  
        assert stats2["posted"] == 200  # stats accumulated (10 iterations * 20)


def test_reporter_protocol_compliance():
    """Test that all reporters implement the protocol correctly."""
    reporters = [
        NoOpProgressReporter(),
        RichProgressReporter(),
    ]
    
    for reporter in reporters:
        # All should have these methods
        assert hasattr(reporter, "start_task")
        assert hasattr(reporter, "update_task")
        assert hasattr(reporter, "finish_task")
        assert hasattr(reporter, "is_active")
        assert hasattr(reporter, "__enter__")
        assert hasattr(reporter, "__exit__")
