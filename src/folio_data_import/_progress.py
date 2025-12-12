"""Progress reporting abstraction for FOLIO data import tasks.

This module provides a UI-agnostic progress reporting system that can be used
across all import tasks (BatchPoster, UserImport, MARCDataImport, etc.) with
support for multiple simultaneous tasks and easy backend swapping.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol
from uuid import uuid4

from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    ProgressColumn,
    SpinnerColumn,
    Task,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.text import Text

logger = logging.getLogger(__name__)

# Optional Redis support
try:
    import redis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    redis = None  # type: ignore[assignment]


# =============================================================================
# Core Abstractions
# =============================================================================


class TaskStatus(Enum):
    """Status of a progress task."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ProgressReporter(Protocol):
    """Protocol defining the interface for progress reporters.

    This protocol allows for easy swapping between different UI implementations
    (CLI, GUI, web) without changing the core business logic.
    """

    def start_task(
        self,
        name: str,
        total: int | None = None,
        description: str | None = None,
    ) -> str:
        """Start a new progress task.

        Args:
            name: Unique identifier for the task
            total: Total number of items to process (None for indeterminate)
            description: Human-readable task description

        Returns:
            Task ID that can be used to update this task
        """
        ...

    def update_task(
        self,
        task_id: str,
        advance: int = 0,
        total: int | None = None,
        description: str | None = None,
        **stats: Any,
    ) -> None:
        """Update an existing task's progress and statistics.

        Args:
            task_id: ID of the task to update
            advance: Number of items to advance by
            total: New total (if changed)
            description: New description (if changed)
            **stats: Additional statistics to track (created, updated, failed, etc.)
        """
        ...

    def finish_task(self, task_id: str, status: TaskStatus = TaskStatus.COMPLETED) -> None:
        """Mark a task as finished.

        Args:
            task_id: ID of the task to finish
            status: Final status of the task
        """
        ...

    def is_active(self) -> bool:
        """Check if progress reporting is active."""
        ...


class BaseProgressReporter(ABC):
    """Abstract base class for progress reporters.

    Provides common functionality and enforces the interface contract.
    """

    def __init__(self, enabled: bool = True) -> None:
        """Initialize the progress reporter.

        Args:
            enabled: Whether progress reporting is enabled
        """
        self._enabled = enabled
        self._tasks: dict[str, dict[str, Any]] = {}
        self._active = False

    @abstractmethod
    def start_task(
        self,
        name: str,
        total: int | None = None,
        description: str | None = None,
    ) -> str:
        """Start a new progress task."""
        pass

    @abstractmethod
    def update_task(
        self,
        task_id: str,
        advance: int = 0,
        total: int | None = None,
        description: str | None = None,
        **stats: Any,
    ) -> None:
        """Update an existing task."""
        pass

    @abstractmethod
    def finish_task(self, task_id: str, status: TaskStatus = TaskStatus.COMPLETED) -> None:
        """Finish a task."""
        pass

    def is_active(self) -> bool:
        """Check if reporter is active."""
        return self._enabled and self._active

    def get_stats(self, task_id: str) -> dict[str, Any] | None:
        """Get statistics for a task."""
        return self._tasks.get(task_id)

    def _update_stat_dict(self, stat_dict: dict[str, Any], stats: dict[str, Any]) -> None:
        """Update a statistics dictionary with new values.

        Args:
            stat_dict: The dictionary to update
            stats: Statistics to add (values are accumulated)
        """
        for key, value in stats.items():
            if key in stat_dict:
                stat_dict[key] += value
            else:
                stat_dict[key] = value

    @abstractmethod
    def __enter__(self) -> BaseProgressReporter:
        """Enter context manager."""
        pass

    @abstractmethod
    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit context manager."""
        pass


# =============================================================================
# Rich CLI Implementation
# =============================================================================


class ItemsPerSecondColumn(ProgressColumn):
    """Renders the speed in items per second."""

    def render(self, task: Task) -> Text:
        if task.speed is None:
            return Text("?", style="progress.data.speed")
        return Text(f"{task.speed:.0f}rec/s", style="progress.data.speed")


class UserStatsColumn(ProgressColumn):
    def render(self, task: Task) -> Text:
        created = task.fields.get("created", 0)
        updated = task.fields.get("updated", 0)
        failed = task.fields.get("failed", 0)
        created_string = f"Created: {created}"
        updated_string = f"Updated: {updated}"
        failed_string = f"Failed: {failed}"
        text = Text("(")
        text.append(created_string, style="green")
        text.append(" | ")
        text.append(updated_string, style="cyan")
        text.append(" | ")
        text.append(failed_string, style="red")
        text.append(")")
        return text


class BatchPosterStatsColumn(ProgressColumn):
    """Renders statistics for batch posting operations."""

    def render(self, task: Task) -> Text:
        posted = task.fields.get("posted", 0)
        created = task.fields.get("created", 0)
        updated = task.fields.get("updated", 0)
        failed = task.fields.get("failed", 0)
        posted_string = f"Posted: {posted}"
        created_string = f"Created: {created}"
        updated_string = f"Updated: {updated}"
        failed_string = f"Failed: {failed}"
        text = Text("(")
        text.append(posted_string, style="bright_green")
        text.append(" | ")
        text.append(created_string, style="green")
        text.append(" | ")
        text.append(updated_string, style="cyan")
        text.append(" | ")
        text.append(failed_string, style="red")
        text.append(")")
        return text


class GenericStatsColumn(ProgressColumn):
    """Renders generic statistics for any task.

    The stat_configs class attribute can be customized by subclassing or
    direct assignment to change which stats are displayed and their styling.

    Example:
        # Customize via subclass
        class CustomStatsColumn(GenericStatsColumn):
            stat_configs = [
                ("imported", "Imported", "bright_blue"),
                ("skipped", "Skipped", "yellow"),
                ("failed", "Failed", "red"),
            ]

        # Or modify directly
        GenericStatsColumn.stat_configs.append(("custom_stat", "Custom", "magenta"))
    """

    stat_configs: list[tuple[str, str, str]] = [
        ("posted", "Posted", "bright_green"),
        ("created", "Created", "green"),
        ("updated", "Updated", "cyan"),
        ("failed", "Failed", "red"),
        ("processed", "Processed", "blue"),
    ]

    def render(self, task: Task) -> Text:
        """Render statistics based on configured stats."""
        stats_parts = []

        for key, label, style in self.stat_configs:
            if key in task.fields and task.fields[key] > 0:
                stats_parts.append((f"{label}: {task.fields[key]}", style))

        if not stats_parts:
            return Text("")

        text = Text("(")
        for i, (stat_text, style) in enumerate(stats_parts):
            if i > 0:
                text.append(" | ")
            text.append(stat_text, style=style)
        text.append(")")
        return text


class RichProgressReporter(BaseProgressReporter):
    """Rich terminal-based progress reporter.

    Provides a beautiful CLI progress display using the Rich library with
    support for multiple simultaneous tasks, live updates, and logging.
    """

    def __init__(
        self,
        enabled: bool = True,
        show_speed: bool = True,
        show_time: bool = True,
    ) -> None:
        """Initialize the Rich progress reporter.

        Args:
            enabled: Whether progress reporting is enabled
            show_speed: Whether to show items/second
            show_time: Whether to show elapsed/remaining time
        """
        super().__init__(enabled)
        self._show_speed = show_speed
        self._show_time = show_time
        self._progress: Progress | None = None
        self._task_map: dict[str, Any] = {}  # Maps task names to Rich TaskIDs

    def _create_progress(self) -> Any:
        """Create a Rich Progress instance with appropriate columns."""
        columns: list[Any] = [SpinnerColumn(), "[progress.description]{task.description}"]

        columns.append(BarColumn())
        columns.append(MofNCompleteColumn())

        if self._show_speed:
            columns.append(ItemsPerSecondColumn())

        if self._show_time:
            columns.append(TimeElapsedColumn())
            columns.append(TimeRemainingColumn())

        columns.append(GenericStatsColumn())

        return Progress(*columns)

    def start_task(
        self,
        name: str,
        total: int | None = None,
        description: str | None = None,
    ) -> str:
        """Start a new progress task."""
        if not self._enabled or self._progress is None:
            return name

        desc = description or name
        task_id = self._progress.add_task(desc, total=total or 100)
        self._task_map[name] = task_id
        self._tasks[name] = {"total": total or 0, "completed": 0}

        return name

    def update_task(
        self,
        task_id: str,
        advance: int = 0,
        total: int | None = None,
        description: str | None = None,
        **stats: Any,
    ) -> None:
        """Update an existing task."""
        if not self._enabled or self._progress is None or task_id not in self._task_map:
            return

        rich_task_id = self._task_map[task_id]

        # Build update kwargs
        update_kwargs = self._build_update_kwargs(advance, total, description, stats)

        if update_kwargs:
            self._progress.update(rich_task_id, **update_kwargs)

        # Update our internal stats
        self._update_internal_stats(task_id, advance, total, stats)

    def _build_update_kwargs(
        self,
        advance: int,
        total: int | None,
        description: str | None,
        stats: dict[str, Any],
    ) -> dict[str, Any]:
        """Build kwargs dict for progress update."""
        update_kwargs: dict[str, Any] = {}

        if advance > 0:
            update_kwargs["advance"] = advance
        if total is not None:
            update_kwargs["total"] = total
        if description is not None:
            update_kwargs["description"] = description

        # Add statistics as fields
        update_kwargs.update(stats)

        return update_kwargs

    def _update_internal_stats(
        self,
        task_id: str,
        advance: int,
        total: int | None,
        stats: dict[str, Any],
    ) -> None:
        """Update internal task statistics."""
        if task_id not in self._tasks:
            return

        if advance > 0:
            self._tasks[task_id]["completed"] += advance
        if total is not None:
            self._tasks[task_id]["total"] = total

        # Update any additional stats
        self._update_stat_dict(self._tasks[task_id], stats)

    def finish_task(self, task_id: str, status: TaskStatus = TaskStatus.COMPLETED) -> None:
        """Finish a task."""
        if not self._enabled or self._progress is None or task_id not in self._task_map:
            return

        rich_task_id = self._task_map[task_id]

        if status == TaskStatus.COMPLETED:
            # Mark as complete
            task = self._progress.tasks[rich_task_id]
            if task.total and task.completed < task.total:
                self._progress.update(rich_task_id, completed=task.total)
        elif status == TaskStatus.FAILED:
            # Could add visual indicator for failed tasks
            self._progress.update(rich_task_id, description=f"[red]✗ {task.description}[/red]")

    def __enter__(self) -> RichProgressReporter:
        """Enter context manager."""
        if not self._enabled:
            self._active = True
            return self

        self._progress = self._create_progress()
        self._progress.start()
        self._active = True

        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit context manager."""
        self._active = False

        if self._progress:
            self._progress.stop()
            self._progress = None

        self._task_map.clear()


class RedisProgressReporter(BaseProgressReporter):
    """Progress reporter that stores state in Redis for distributed access.

    Stores progress updates in Redis that can be accessed by separate processes
    or API endpoints. Requires redis package to be installed.

    Example:
        >>> reporter = RedisProgressReporter(
        ...     redis_url="redis://localhost:6379",
        ...     session_id="import-123"
        ... )
        >>> with reporter:
        ...     task_id = reporter.start_task("users", total=100)
        ...     reporter.update_task(task_id, advance=10, created=5)
    """

    def __init__(
        self,
        enabled: bool = True,
        redis_url: str = "redis://localhost:6379",
        session_id: str | None = None,
        ttl: int = 3600,
    ) -> None:
        """Initialize the Redis progress reporter.

        Args:
            enabled: Whether progress reporting is enabled
            redis_url: Redis connection URL
            session_id: Unique identifier for this progress session
            ttl: Time-to-live for session data in seconds (default: 1 hour)

        Raises:
            ImportError: If redis package is not installed
        """
        super().__init__(enabled)

        if not REDIS_AVAILABLE:
            raise ImportError(
                "Redis support requires the redis package. Install with optional "
                "dependency: folio-data-import[redis]"
            )

        self._session_id = session_id or self._generate_session_id()
        self._ttl = ttl
        self._redis = redis.from_url(redis_url, decode_responses=True)
        self._session_key = f"progress:session:{self._session_id}"

        # Initialize session in Redis
        if self._enabled:
            self._init_session()

    def _generate_session_id(self) -> str:
        """Generate a unique session ID."""
        return str(uuid4())

    def _init_session(self) -> None:
        """Initialize session data in Redis."""
        session_data = {
            "session_id": self._session_id,
            "status": "pending",
            "tasks": {},
            "created_at": self._get_timestamp(),
            "updated_at": self._get_timestamp(),
        }

        self._redis.set(self._session_key, json.dumps(session_data), ex=self._ttl)

    def start_task(
        self,
        name: str,
        total: int | None = None,
        description: str | None = None,
    ) -> str:
        """Start a new progress task."""
        self._tasks[name] = {"total": total or 0, "completed": 0}

        if self._enabled:
            # Get current session
            session_data = json.loads(self._redis.get(self._session_key) or "{}")

            # Add new task
            session_data["tasks"][name] = {
                "name": name,
                "description": description or name,
                "total": total,
                "completed": 0,
                "status": TaskStatus.RUNNING.value,
                "stats": {},
                "started_at": self._get_timestamp(),
            }
            session_data["updated_at"] = self._get_timestamp()
            session_data["status"] = "running"

            # Update Redis
            self._redis.set(self._session_key, json.dumps(session_data), ex=self._ttl)

        return name

    def update_task(
        self,
        task_id: str,
        advance: int = 0,
        total: int | None = None,
        description: str | None = None,
        **stats: Any,
    ) -> None:
        """Update an existing task."""
        if not self._enabled or task_id not in self._tasks:
            return

        # Update internal stats
        if advance > 0:
            self._tasks[task_id]["completed"] += advance
        if total is not None:
            self._tasks[task_id]["total"] = total

        # Update any additional stats
        self._update_stat_dict(self._tasks[task_id], stats)

        # Update Redis
        session_data = json.loads(self._redis.get(self._session_key) or "{}")

        if task_id not in session_data.get("tasks", {}):
            return

        task_data = session_data["tasks"][task_id]
        task_data["completed"] = self._tasks[task_id]["completed"]

        if total is not None:
            task_data["total"] = total
        if description is not None:
            task_data["description"] = description

        # Update statistics
        self._update_stat_dict(task_data["stats"], stats)

        # Calculate progress percentage
        if task_data["total"] and task_data["total"] > 0:
            task_data["progress_percent"] = (task_data["completed"] / task_data["total"]) * 100
        else:
            task_data["progress_percent"] = 0

        session_data["updated_at"] = self._get_timestamp()

        # Update Redis
        self._redis.set(self._session_key, json.dumps(session_data), ex=self._ttl)

    def finish_task(self, task_id: str, status: TaskStatus = TaskStatus.COMPLETED) -> None:
        """Finish a task."""
        if not self._enabled or task_id not in self._tasks:
            return

        session_data = json.loads(self._redis.get(self._session_key) or "{}")

        if task_id not in session_data.get("tasks", {}):
            return

        task_data = session_data["tasks"][task_id]
        task_data["status"] = status.value
        task_data["finished_at"] = self._get_timestamp()

        # Check if all tasks are complete
        all_complete = all(
            t["status"] in [TaskStatus.COMPLETED.value, TaskStatus.FAILED.value]
            for t in session_data["tasks"].values()
        )
        if all_complete:
            session_data["status"] = "completed"

        session_data["updated_at"] = self._get_timestamp()

        # Update Redis
        self._redis.set(self._session_key, json.dumps(session_data), ex=self._ttl)

    def _get_timestamp(self) -> str:
        """Get current timestamp."""
        return datetime.now(timezone.utc).isoformat()

    @classmethod
    def get_session(
        cls,
        session_id: str,
        redis_url: str = "redis://localhost:6379",
    ) -> dict[str, Any] | None:
        """Get the current state of a session from Redis.

        Args:
            session_id: The session ID to retrieve
            redis_url: Redis connection URL

        Returns:
            Session data dictionary or None if not found

        Raises:
            ImportError: If redis package is not installed
        """
        if not REDIS_AVAILABLE:
            raise ImportError(
                "Redis support requires the redis package. Install it with: pip install redis"
            )

        r = redis.from_url(redis_url, decode_responses=True)
        session_key = f"progress:session:{session_id}"
        data = r.get(session_key)

        return json.loads(data) if data else None

    @classmethod
    def delete_session(
        cls,
        session_id: str,
        redis_url: str = "redis://localhost:6379",
    ) -> bool:
        """Delete a session from Redis.

        Args:
            session_id: The session ID to delete
            redis_url: Redis connection URL

        Returns:
            True if deleted, False if not found

        Raises:
            ImportError: If redis package is not installed
        """
        if not REDIS_AVAILABLE:
            raise ImportError(
                "Redis support requires the redis package. Install it with: pip install redis"
            )

        r = redis.from_url(redis_url, decode_responses=True)
        session_key = f"progress:session:{session_id}"
        return bool(r.delete(session_key))

    def __enter__(self) -> RedisProgressReporter:
        """Enter context manager."""
        self._active = True
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit context manager."""
        self._active = False


class NoOpProgressReporter(BaseProgressReporter):
    """No-operation progress reporter for when progress display is disabled."""

    def __init__(self) -> None:
        """Initialize the no-op reporter."""
        super().__init__(enabled=False)

    def start_task(
        self,
        name: str,
        total: int | None = None,
        description: str | None = None,
    ) -> str:
        """Start a task (no-op)."""
        return name

    def update_task(
        self,
        task_id: str,
        advance: int = 0,
        total: int | None = None,
        description: str | None = None,
        **stats: Any,
    ) -> None:
        """Update a task (no-op)."""
        pass

    def finish_task(self, task_id: str, status: TaskStatus = TaskStatus.COMPLETED) -> None:
        """Finish a task (no-op)."""
        pass

    def __enter__(self) -> NoOpProgressReporter:
        """Enter context manager."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit context manager."""
        pass
