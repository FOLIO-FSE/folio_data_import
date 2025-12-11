"""
BatchPoster module for FOLIO inventory batch operations.

This module provides functionality for batch posting of Instances, Holdings, and Items
to FOLIO's inventory storage endpoints with support for upsert operations.
"""

import asyncio
import glob as glob_module
import json
import logging
import sys
from datetime import datetime as dt
from io import TextIOWrapper
from pathlib import Path
from typing import Annotated, Any, Dict, Generator, List, Literal, Union

import cyclopts
import folioclient
from folioclient import FolioClient
import httpx
from pydantic import BaseModel, Field
from rich.logging import RichHandler

from folio_data_import import get_folio_connection_parameters
from folio_data_import._progress import (
    RichProgressReporter,
    ProgressReporter,
    NoOpProgressReporter,
)

logger = logging.getLogger(__name__)


class BatchPosterStats(BaseModel):
    """Statistics for batch posting operations."""

    records_processed: int = 0
    records_posted: int = 0
    records_created: int = 0
    records_updated: int = 0
    records_failed: int = 0
    batches_posted: int = 0
    batches_failed: int = 0


def get_api_info(object_type: str) -> Dict[str, Any]:
    """
    Get API endpoint information for a given object type.

    Args:
        object_type: The type of object (Instances, Holdings, Items)

    Returns:
        Dictionary containing API endpoint information

    Raises:
        ValueError: If object_type is not supported
    """
    api_info = {
        "Items": {
            "object_name": "items",
            "api_endpoint": "/item-storage/batch/synchronous",
            "query_endpoint": "/item-storage/items",
            "is_batch": True,
            "supports_upsert": True,
        },
        "Holdings": {
            "object_name": "holdingsRecords",
            "api_endpoint": "/holdings-storage/batch/synchronous",
            "query_endpoint": "/holdings-storage/holdings",
            "is_batch": True,
            "supports_upsert": True,
        },
        "Instances": {
            "object_name": "instances",
            "api_endpoint": "/instance-storage/batch/synchronous",
            "query_endpoint": "/instance-storage/instances",
            "is_batch": True,
            "supports_upsert": True,
        },
    }

    if object_type not in api_info:
        raise ValueError(
            f"Unsupported object type: {object_type}. "
            f"Supported types: {', '.join(api_info.keys())}"
        )

    return api_info[object_type]


def deep_update(target: dict, source: dict) -> None:
    """
    Recursively update target dictionary with values from source dictionary.

    Args:
        target: The dictionary to update
        source: The dictionary to merge into target
    """
    for key, value in source.items():
        if isinstance(value, dict) and key in target and isinstance(target[key], dict):
            deep_update(target[key], value)
        else:
            target[key] = value


def extract_paths(record: dict, paths: List[str]) -> dict:
    """
    Extract specified paths from a record.

    Args:
        record: The record to extract from
        paths: List of JSON paths to extract (e.g., ['statisticalCodeIds', 'status'])

    Returns:
        Dictionary containing only the specified paths
    """
    result = {}
    for path in paths:
        if path in record:
            result[path] = record[path]
    return result


class BatchPoster:
    """
    Handles batch posting of inventory records to FOLIO.

    This class provides functionality for posting Instances, Holdings, and Items
    to FOLIO's batch inventory endpoints with support for upsert operations.
    """

    class Config(BaseModel):
        """Configuration for BatchPoster operations."""

        object_type: Annotated[
            Literal["Instances", "Holdings", "Items"],
            Field(
                title="Object type",
                description="The type of inventory object to post: Instances, Holdings, or Items",
            ),
        ]
        batch_size: Annotated[
            int,
            Field(
                title="Batch size",
                description="Number of records to include in each batch (1-1000)",
            ),
        ] = 1
        upsert: Annotated[
            bool,
            Field(
                title="Upsert",
                description=(
                    "Enable upsert mode to create new records or update existing ones. "
                    "When enabled, records with matching IDs will be updated instead "
                    "of causing errors."
                ),
            ),
        ] = False
        preserve_statistical_codes: Annotated[
            bool,
            Field(
                title="Preserve statistical codes",
                description=(
                    "Preserve existing statistical codes during upsert. "
                    "When enabled, statistical codes from existing records will be retained "
                    "and merged with new codes."
                ),
            ),
        ] = False
        preserve_administrative_notes: Annotated[
            bool,
            Field(
                title="Preserve administrative notes",
                description=(
                    "Preserve existing administrative notes during upsert. "
                    "When enabled, administrative notes from existing records will be retained "
                    "and merged with new notes."
                ),
            ),
        ] = False
        preserve_temporary_locations: Annotated[
            bool,
            Field(
                title="Preserve temporary locations",
                description=(
                    "Preserve temporary location assignments on items during upsert. "
                    "Only applicable when object_type is 'Items'."
                ),
            ),
        ] = False
        preserve_temporary_loan_types: Annotated[
            bool,
            Field(
                title="Preserve temporary loan types",
                description=(
                    "Preserve temporary loan type assignments on items during upsert. "
                    "Only applicable when object_type is 'Items'."
                ),
            ),
        ] = False
        preserve_item_status: Annotated[
            bool,
            Field(
                title="Preserve item status",
                description=(
                    "Preserve item status during upsert. When enabled, the status "
                    "field from existing records will be retained. Only applicable "
                    "when object_type is 'Items'."
                ),
            ),
        ] = True
        patch_existing_records: Annotated[
            bool,
            Field(
                title="Patch existing records",
                description=(
                    "Enable selective field patching during upsert. When enabled, only fields "
                    "specified in patch_paths will be updated, preserving all other fields."
                ),
            ),
        ] = False
        patch_paths: Annotated[
            List[str] | None,
            Field(
                title="Patch paths",
                description=(
                    "List of field paths to patch during upsert "
                    "(e.g., ['barcode', 'status']). "
                    "If empty and patch_existing_records is True, all fields "
                    "will be patched. Use this to selectively update only "
                    "specific fields while preserving others."
                ),
            ),
        ] = None
        no_progress: Annotated[
            bool,
            Field(
                title="No progress bar",
                description="Disable the progress bar display (e.g., for CI environments)",
            ),
        ] = False

    def __init__(
        self,
        folio_client: FolioClient,
        config: "BatchPoster.Config",
        failed_records_file=None,
        reporter: ProgressReporter | None = None,
    ):
        """
        Initialize BatchPoster.

        Args:
            folio_client: Authenticated FOLIO client
            config: Configuration for batch posting
            failed_records_file: Optional file handle or path for writing failed records.
                Can be an open file handle (managed by caller) or a string/Path
                (will be opened/closed by BatchPoster).
            reporter: Optional progress reporter. If None, uses NoOpProgressReporter.
        """
        self.folio_client = folio_client
        self.config = config
        self.reporter = reporter or NoOpProgressReporter()
        self.api_info = get_api_info(config.object_type)
        self.stats = BatchPosterStats()

        # Handle failed records file
        self._failed_records_file_handle: TextIOWrapper | None = None
        self._failed_records_path: Path | None = None
        self._owns_file_handle = False

        if failed_records_file:
            if hasattr(failed_records_file, "write"):
                # It's a file handle - use it but don't close it
                self._failed_records_file_handle = failed_records_file
                self._owns_file_handle = False
            else:
                # It's a path - we'll open and manage it
                self._failed_records_path = Path(failed_records_file)
                self._owns_file_handle = True

        # Validate upsert configuration
        if config.upsert and not self.api_info["supports_upsert"]:
            raise ValueError(f"Upsert is not supported for {config.object_type}")

    async def __aenter__(self):
        """Async context manager entry."""
        # Open the file if we own it and it's not already open
        if (
            self._owns_file_handle
            and self._failed_records_path
            and not self._failed_records_file_handle
        ):
            self._failed_records_file_handle = open(
                self._failed_records_path, "w", encoding="utf-8"
            )
            logger.info(f"Opened failed records file: {self._failed_records_path}")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        # Only close the file if we opened it
        if self._owns_file_handle and self._failed_records_file_handle:
            self._failed_records_file_handle.close()
            if self._failed_records_path:
                logger.info(
                    f"Wrote {self.stats.records_failed} failed records "
                    f"to {self._failed_records_path}"
                )
            self._failed_records_file_handle = None

    def _write_failed_record(self, record: dict) -> None:
        """
        Write a single failed record to the file immediately.

        Args:
            record: The record that failed to post
        """
        if self._failed_records_file_handle:
            self._failed_records_file_handle.write(json.dumps(record) + "\n")
            self._failed_records_file_handle.flush()  # Ensure it's written immediately

    def _write_failed_batch(self, batch: List[dict]) -> None:
        """
        Write a batch of failed records to the file immediately.

        Args:
            batch: List of records that failed to post
        """
        if self._failed_records_file_handle:
            for record in batch:
                self._failed_records_file_handle.write(json.dumps(record) + "\n")
            self._failed_records_file_handle.flush()  # Ensure they're written immediately

    def handle_upsert_for_statistical_codes(self, updates: dict, keep_existing: dict) -> None:
        """
        Handle statistical codes during upsert based on configuration.

        Args:
            updates: Dictionary being prepared for update
            keep_existing: Dictionary of fields to preserve from existing record
        """
        if not self.config.preserve_statistical_codes:
            updates["statisticalCodeIds"] = []
            keep_existing["statisticalCodeIds"] = []
        else:
            keep_existing["statisticalCodeIds"] = updates.pop("statisticalCodeIds", [])
            updates["statisticalCodeIds"] = []

    def handle_upsert_for_administrative_notes(self, updates: dict, keep_existing: dict) -> None:
        """
        Handle administrative notes during upsert based on configuration.

        Args:
            updates: Dictionary being prepared for update
            keep_existing: Dictionary of fields to preserve from existing record
        """
        if not self.config.preserve_administrative_notes:
            updates["administrativeNotes"] = []
            keep_existing["administrativeNotes"] = []
        else:
            keep_existing["administrativeNotes"] = updates.pop("administrativeNotes", [])
            updates["administrativeNotes"] = []

    def handle_upsert_for_temporary_locations(self, updates: dict, keep_existing: dict) -> None:
        """
        Handle temporary locations during upsert based on configuration.

        Args:
            updates: Dictionary being prepared for update
            keep_existing: Dictionary of fields to preserve from existing record
        """
        if self.config.preserve_temporary_locations:
            keep_existing["temporaryLocationId"] = updates.pop("temporaryLocationId", None)

    def handle_upsert_for_temporary_loan_types(self, updates: dict, keep_existing: dict) -> None:
        """
        Handle temporary loan types during upsert based on configuration.

        Args:
            updates: Dictionary being prepared for update
            keep_existing: Dictionary of fields to preserve from existing record
        """
        if self.config.preserve_temporary_loan_types:
            keep_existing["temporaryLoanTypeId"] = updates.pop("temporaryLoanTypeId", None)

    def keep_existing_fields(self, updates: dict, existing_record: dict) -> None:
        """
        Preserve specific fields from existing record during upsert.

        Args:
            updates: Dictionary being prepared for update
            existing_record: The existing record in FOLIO
        """
        if self.config.preserve_item_status and "status" in existing_record:
            updates["status"] = existing_record["status"]

    def patch_record(
        self, new_record: dict, existing_record: dict, patch_paths: List[str]
    ) -> None:
        """
        Update new_record with values from existing_record according to patch_paths.

        Args:
            new_record: The new record to be updated
            existing_record: The existing record to patch from
            patch_paths: List of fields in JSON Path notation to patch during upsert
        """
        updates = {}
        updates.update(existing_record)
        keep_existing: Dict[str, Any] = {}

        # Handle special field preservation rules
        self.handle_upsert_for_administrative_notes(updates, keep_existing)
        self.handle_upsert_for_statistical_codes(updates, keep_existing)

        if self.config.object_type == "Items":
            self.handle_upsert_for_temporary_locations(updates, keep_existing)
            self.handle_upsert_for_temporary_loan_types(updates, keep_existing)

        # Determine which fields to keep from new record
        if not patch_paths:
            keep_new = new_record
        else:
            keep_new = extract_paths(new_record, patch_paths)

        # Special handling for instance status
        if "instanceStatusId" in new_record:
            updates["instanceStatusId"] = new_record["instanceStatusId"]

        # Merge the updates
        deep_update(updates, keep_new)

        # Merge arrays from keep_existing, avoiding duplicates
        for key, value in keep_existing.items():
            if isinstance(value, list) and key in keep_new:
                # Combine arrays and remove duplicates
                updates[key] = list(dict.fromkeys(updates.get(key, []) + value))
            elif key not in keep_new:
                updates[key] = value

        # Apply item-specific preservation
        if self.config.object_type == "Items":
            self.keep_existing_fields(updates, existing_record)

        # Update the new_record in place
        new_record.clear()
        new_record.update(updates)

    def prepare_record_for_upsert(self, new_record: dict, existing_record: dict) -> None:
        """
        Prepare a record for upsert by adding version and patching fields.

        Args:
            new_record: The new record to prepare
            existing_record: The existing record in FOLIO
        """
        # Set the version for optimistic locking
        new_record["_version"] = existing_record.get("_version", 1)

        # Apply patching if configured
        if self.config.patch_existing_records:
            self.patch_record(new_record, existing_record, self.config.patch_paths or [])

    async def fetch_existing_records(self, record_ids: List[str]) -> Dict[str, dict]:
        """
        Fetch existing records from FOLIO by their IDs.

        Args:
            record_ids: List of record IDs to fetch

        Returns:
            Dictionary mapping record IDs to their full records
        """
        existing_records: Dict[str, dict] = {}
        query_endpoint = self.api_info["query_endpoint"]
        object_name = self.api_info["object_name"]

        # Fetch in batches of 90 (FOLIO CQL limit for OR queries)
        fetch_batch_size = 90

        async def fetch_batch(batch_ids: List[str]) -> dict:
            query = f"id==({' OR '.join(batch_ids)})"
            params = {"query": query, "limit": fetch_batch_size}
            try:
                return await self.folio_client.folio_get_async(
                    query_endpoint, key=object_name, query_params=params
                )
            except folioclient.FolioClientError as e:
                logger.error(f"FOLIO client error fetching existing records: {e}")
                raise
            except folioclient.FolioConnectionError as e:
                logger.error(f"FOLIO connection error fetching existing records: {e}")
                raise
            except Exception as e:
                logger.error(f"Failed to fetch existing records: {e}")
                raise

        # Create tasks for all batches
        tasks = []
        for i in range(0, len(record_ids), fetch_batch_size):
            batch_slice = record_ids[i : i + fetch_batch_size]
            tasks.append(fetch_batch(batch_slice))

        # Fetch all batches concurrently
        results = await asyncio.gather(*tasks)

        # Process results
        for result in results:
            if isinstance(result, list):
                for record in result:
                    existing_records[record["id"]] = record

        return existing_records

    async def set_versions_for_upsert(self, batch: List[dict]) -> None:
        """
        Fetch existing record versions and prepare batch for upsert.

        Only records that already exist in FOLIO will have their _version set
        and be prepared for update. New records will not have _version set.

        Args:
            batch: List of records to prepare for upsert
        """
        # Extract record IDs
        record_ids = [record["id"] for record in batch if "id" in record]

        if not record_ids:
            return

        # Fetch existing records
        existing_records = await self.fetch_existing_records(record_ids)

        # Only prepare records that already exist
        for record in batch:
            if "id" in record and record["id"] in existing_records:
                self.prepare_record_for_upsert(record, existing_records[record["id"]])

    async def post_batch(self, batch: List[dict]) -> tuple[httpx.Response, int, int]:
        """
        Post a batch of records to FOLIO.

        Args:
            batch: List of records to post

        Returns:
            Tuple of (response data dict, number of creates, number of updates)

        Raises:
            folioclient.FolioClientError: If FOLIO API returns an error
            folioclient.FolioConnectionError: If connection to FOLIO fails
        """
        # Track creates vs updates before posting
        num_creates = 0
        num_updates = 0

        # If upsert mode, set versions and track which are updates
        if self.config.upsert:
            await self.set_versions_for_upsert(batch)
            # Count records with _version as updates, others as creates
            for record in batch:
                if "_version" in record:
                    num_updates += 1
                else:
                    num_creates += 1
        else:
            # In create-only mode, all are creates
            num_creates = len(batch)

        # Prepare payload
        object_name = self.api_info["object_name"]
        payload = {object_name: batch}

        # Prepare query parameters
        query_params = {}
        if self.config.upsert:
            query_params["upsert"] = "true"

        # Make the request
        api_endpoint = self.api_info["api_endpoint"]

        response_data = await self.folio_client.async_httpx_client.post(
            api_endpoint, json=payload, params=query_params
        )
        response_data.raise_for_status()
        logger.info(
            (
                "Posting successful! Total rows: %s Total failed: %s "
                "in %ss "
                "Batch Size: %s Request size: %s "
            ),
            self.stats.records_processed,
            self.stats.records_failed,
            response_data.elapsed.total_seconds(),
            len(batch),
            get_req_size(response_data),
        )
        self.stats.records_posted += len(batch)
        self.stats.batches_posted += 1

        return response_data, num_creates, num_updates

    async def post_records(self, records) -> None:
        """
        Post records in batches.

        Failed records will be written to the file handle provided during initialization.

        Args:
            records: Records to post. Can be:
                - List of dict records
                - File-like object containing JSON lines (one record per line)
                - String/Path to a file containing JSON lines
        """
        # Normalize input to an iterator
        if isinstance(records, (str, Path)):
            # It's a file path
            record_iterator = self._read_records_from_path(records)
        elif hasattr(records, "read"):
            # It's a file-like object
            record_iterator = self._read_records_from_file_handle(records)
        elif isinstance(records, list):
            # It's already a list - wrap in a generator
            record_iterator = iter(records)
        else:
            raise TypeError(
                f"records must be a list, file path, or file-like object, got {type(records)}"
            )

        # Process records in batches
        batch = []
        for record in record_iterator:
            batch.append(record)

            # Post when batch is full
            if len(batch) >= self.config.batch_size:
                await self._post_single_batch(batch)
                batch = []

        # Post any remaining records
        if batch:
            await self._post_single_batch(batch)

    def _read_records_from_path(self, file_path: Union[str, Path]) -> Generator[dict, None, None]:
        """
        Generator that yields records from a file path.

        Args:
            file_path: Path to file containing JSON lines

        Yields:
            Parsed record dictionaries
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Input file not found: {file_path}")

        logger.info(f"Reading records from {file_path}")

        with open(file_path, "r", encoding="utf-8") as f:
            yield from self._read_records_from_file_handle(f)

    def _read_records_from_file_handle(self, file_handle) -> Generator[dict, None, None]:
        """
        Generator that yields records from a file handle.

        If a line cannot be parsed as JSON, writes the problematic line and all
        remaining lines to the failed records file (if configured) before raising
        an exception.

        Args:
            file_handle: File-like object containing JSON lines

        Yields:
            Parsed record dictionaries

        Raises:
            ValueError: If a line cannot be parsed as JSON
        """
        for line_number, original_line in enumerate(file_handle, start=1):
            line = original_line.strip()
            if not line:
                continue

            try:
                record = self._parse_json_line(line, line_number)
                yield record
            except ValueError:
                # Write the failed line to failed records file
                if self._failed_records_file_handle:
                    self._failed_records_file_handle.write(original_line)
                    # Write all remaining lines as-is
                    for remaining_line in file_handle:
                        self._failed_records_file_handle.write(remaining_line)

                    self._failed_records_file_handle.flush()

                # Re-raise the exception
                raise

    async def _post_single_batch(self, batch: List[dict]) -> None:
        """
        Post a single batch with error handling.

        Args:
            batch: List of records to post
        """
        self.stats.records_processed += len(batch)

        try:
            _, num_creates, num_updates = await self.post_batch(batch)

            # Success - update stats
            self.stats.records_created += num_creates
            self.stats.records_updated += num_updates
            # Update progress bar if available
            if hasattr(self, "reporter") and hasattr(self, "task_id"):
                self.reporter.update_task(
                    self.task_id,
                    advance=len(batch),
                    posted=self.stats.records_posted,
                    created=self.stats.records_created,
                    updated=self.stats.records_updated,
                    failed=self.stats.records_failed,
                )

        except folioclient.FolioClientError as e:
            logger.error(f"Batch failed: {e} - {e.response.text}")
            self.stats.records_failed += len(batch)
            self._write_failed_batch(batch)

            # Update progress bar if available
            if hasattr(self, "reporter") and hasattr(self, "task_id"):
                self.reporter.update_task(
                    self.task_id,
                    advance=len(batch),
                    posted=self.stats.records_posted,
                    created=self.stats.records_created,
                    updated=self.stats.records_updated,
                    failed=self.stats.records_failed,
                )

        except folioclient.FolioConnectionError as e:
            logger.error(f"Batch failed due to connection error: {e}")
            self.stats.records_failed += len(batch)
            self._write_failed_batch(batch)

            # Update progress bar if available
            if hasattr(self, "reporter") and hasattr(self, "task_id"):
                self.reporter.update_task(
                    self.task_id,
                    advance=len(batch),
                    posted=self.stats.records_posted,
                    created=self.stats.records_created,
                    updated=self.stats.records_updated,
                    failed=self.stats.records_failed,
                )

        except Exception as e:
            logger.error(f"Unexpected error during batch post: {e}")
            if hasattr(e, "request"):
                logger.debug(f"DEBUG: {e.request}, {e.request.content}")
            self.stats.records_failed += len(batch)
            self._write_failed_batch(batch)

            # Update progress bar if available
            if hasattr(self, "reporter") and hasattr(self, "task_id"):
                self.reporter.update_task(
                    self.task_id,
                    advance=len(batch),
                    posted=self.stats.records_posted,
                    created=self.stats.records_created,
                    updated=self.stats.records_updated,
                    failed=self.stats.records_failed,
                )

    def _parse_json_line(self, line: str, line_number: int) -> dict:
        """
        Parse a JSON line, handling both plain and tab-delimited formats.

        Args:
            line: Line to parse
            line_number: Line number for error reporting

        Returns:
            Parsed record dictionary

        Raises:
            ValueError: If the line cannot be parsed as JSON
        """
        try:
            # Handle both plain JSON and tab-delimited format
            # (tab-delimited: last field is the JSON)
            json_str = line.split("\t")[-1] if "\t" in line else line
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Invalid JSON at line {line_number}: {e}. Line content: {line[:100]}"
            ) from e
        except Exception as e:
            raise ValueError(f"Error processing line {line_number}: {e}") from e

    async def do_work(
        self,
        file_paths: Union[str, Path, List[Union[str, Path]]],
    ) -> BatchPosterStats:
        """
        Main orchestration method for processing files.

        This is the primary entry point for batch posting from files. It handles:
        - Single or multiple file processing
        - Progress tracking and logging
        - Failed record collection
        - Statistics reporting

        Mimics the folio_migration_tools BatchPoster.do_work() workflow.

        Note: To write failed records, pass a file handle or path to the
        BatchPoster constructor's `failed_records_file` parameter.

        Args:
            file_paths: Path(s) to JSONL file(s) to process

        Returns:
            Final statistics from the posting operation

        Example:
            ```python
            config = BatchPosterConfig(
                object_type="Items",
                batch_size=100,
                upsert=True
            )

            reporter = RichProgressReporter(enabled=True)

            # With failed records file
            with open("failed_items.jsonl", "w") as failed_file:
                poster = BatchPoster(folio_client, config, failed_records_file=failed_file, reporter=reporter)
                async with poster:
                    stats = await poster.do_work(["items1.jsonl", "items2.jsonl"])

            # Or let BatchPoster manage the file
            poster = BatchPoster(folio_client, config, failed_records_file="failed_items.jsonl", reporter=reporter)
            async with poster:
                stats = await poster.do_work("items.jsonl")

            print(f"Posted: {stats.records_posted}, Failed: {stats.records_failed}")
            ```
        """  # noqa: E501
        # Reset statistics
        self.stats = BatchPosterStats()

        # Normalize file_paths to list
        if isinstance(file_paths, (str, Path)):
            files_to_process = [Path(file_paths)]
        else:
            files_to_process = [Path(p) for p in file_paths]

        # Log start
        logger.info(
            "Starting batch posting of %d file(s) with batch_size=%d",
            len(files_to_process),
            self.config.batch_size,
        )
        logger.info("Object type: %s", self.config.object_type)
        logger.info("Upsert mode: %s", "On" if self.config.upsert else "Off")
        if self.config.upsert:
            logger.info(
                "Preservation settings: statistical_codes=%s, administrative_notes=%s, "
                "temporary_locations=%s, temporary_loan_types=%s",
                self.config.preserve_statistical_codes,
                self.config.preserve_administrative_notes,
                self.config.preserve_temporary_locations,
                self.config.preserve_temporary_loan_types,
            )

        # Count total lines across all files for progress bar
        total_lines = 0
        for file_path in files_to_process:
            with open(file_path, "rb") as f:
                total_lines += sum(
                    buf.count(b"\n") for buf in iter(lambda: f.read(1024 * 1024), b"")
                )

        # Set up progress reporting
        with self.reporter:
            self.task_id = self.reporter.start_task(
                f"posting_{self.config.object_type}",
                total=total_lines,
                description=f"Posting {self.config.object_type}",
            )

            # Process each file
            for idx, file_path in enumerate(files_to_process, start=1):
                logger.info(
                    "Processing file %d of %d: %s",
                    idx,
                    len(files_to_process),
                    file_path.name,
                )

                try:
                    await self.post_records(file_path)
                except Exception as e:
                    logger.error("Error processing file %s: %s", file_path, e, exc_info=True)
                    raise

            return self.stats

    def get_stats(self) -> BatchPosterStats:
        """
        Get current posting statistics.

        Returns:
            Current statistics
        """
        return self.stats


def get_human_readable_size(size: int, precision: int = 2) -> str:
    """
    Convert bytes to human-readable format.

    Args:
        size: Size in bytes
        precision: Number of decimal places

    Returns:
        Human-readable size string
    """
    suffixes = ["B", "KB", "MB", "GB", "TB"]
    suffix_index = 0
    size_float = float(size)

    while size_float >= 1024 and suffix_index < len(suffixes) - 1:
        suffix_index += 1
        size_float = size_float / 1024.0

    return f"{size_float:.{precision}f}{suffixes[suffix_index]}"


def get_req_size(response: httpx.Response):
    size = response.request.method
    size += str(response.request.url)
    size += "\r\n".join(f"{k}{v}" for k, v in response.request.headers.items())
    size += response.request.content.decode("utf-8") or ""
    return get_human_readable_size(len(size.encode("utf-8")))


def set_up_cli_logging() -> None:
    """
    This function sets up logging for the CLI.
    """

    logger.setLevel(logging.INFO)
    logger.propagate = False

    # Set up file and stream handlers
    file_handler = logging.FileHandler(
        "folio_batch_poster_{}.log".format(dt.now().strftime("%Y%m%d%H%M%S"))
    )
    file_handler.setLevel(logging.INFO)
    file_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    if not any(
        isinstance(h, logging.StreamHandler) and h.stream == sys.stderr for h in logger.handlers
    ):
        stream_handler = RichHandler(
            show_level=False,
            show_time=False,
            omit_repeated_times=False,
            show_path=False,
        )
        stream_handler.setLevel(logging.INFO)
        stream_formatter = logging.Formatter("%(message)s")
        stream_handler.setFormatter(stream_formatter)
        logger.addHandler(stream_handler)

    # Stop httpx from logging info messages to the console
    logging.getLogger("httpx").setLevel(logging.WARNING)


app = cyclopts.App(default_parameter=cyclopts.Parameter(negative=()))


@app.default
def main(
    config_file: Annotated[
        Path | None, cyclopts.Parameter(group="Job Configuration Parameters")
    ] = None,
    *,
    gateway_url: Annotated[
        str | None,
        cyclopts.Parameter(
            env_var="FOLIO_GATEWAY_URL",
            show_env_var=True,
            group="FOLIO Connection Parameters",
        ),
    ] = None,
    tenant_id: Annotated[
        str | None,
        cyclopts.Parameter(
            env_var="FOLIO_TENANT_ID", show_env_var=True, group="FOLIO Connection Parameters"
        ),
    ] = None,
    username: Annotated[
        str | None,
        cyclopts.Parameter(
            env_var="FOLIO_USERNAME", show_env_var=True, group="FOLIO Connection Parameters"
        ),
    ] = None,
    password: Annotated[
        str | None,
        cyclopts.Parameter(
            env_var="FOLIO_PASSWORD", show_env_var=True, group="FOLIO Connection Parameters"
        ),
    ] = None,
    member_tenant_id: Annotated[
        str | None,
        cyclopts.Parameter(
            env_var="FOLIO_MEMBER_TENANT_ID",
            show_env_var=True,
            group="FOLIO Connection Parameters",
        ),
    ] = None,
    object_type: Annotated[
        Literal["Instances", "Holdings", "Items"] | None,
        cyclopts.Parameter(group="Job Configuration Parameters"),
    ] = None,
    file_paths: Annotated[
        tuple[Path, ...] | None,
        cyclopts.Parameter(
            name=["--file-paths", "--file-path"],
            help="Path(s) to JSONL file(s). Accepts multiple values and glob patterns.",
            group="Job Configuration Parameters",
        ),
    ] = None,
    batch_size: Annotated[
        int,
        cyclopts.Parameter(group="Job Configuration Parameters"),
    ] = 100,
    upsert: Annotated[
        bool,
        cyclopts.Parameter(group="Job Configuration Parameters"),
    ] = False,
    preserve_statistical_codes: Annotated[
        bool,
        cyclopts.Parameter(group="Job Configuration Parameters: --upsert options"),
    ] = False,
    preserve_administrative_notes: Annotated[
        bool,
        cyclopts.Parameter(group="Job Configuration Parameters: --upsert options"),
    ] = False,
    preserve_temporary_locations: Annotated[
        bool,
        cyclopts.Parameter(group="Job Configuration Parameters: --upsert options"),
    ] = False,
    preserve_temporary_loan_types: Annotated[
        bool,
        cyclopts.Parameter(group="Job Configuration Parameters: --upsert options"),
    ] = False,
    overwrite_item_status: Annotated[
        bool,
        cyclopts.Parameter(group="Job Configuration Parameters: --upsert options"),
    ] = False,
    patch_existing_records: Annotated[
        bool,
        cyclopts.Parameter(group="Job Configuration Parameters: --upsert options"),
    ] = False,
    patch_paths: Annotated[
        str | None,
        cyclopts.Parameter(
            help=(
                "Comma-separated list of field paths to patch during upsert (e.g., barcode,status)"
            ),
            group="Job Configuration Parameters: --upsert options",
        ),
    ] = None,
    failed_records_file: Annotated[
        Path | None,
        cyclopts.Parameter(group="Job Configuration Parameters"),
    ] = None,
    no_progress: Annotated[
        bool,
        cyclopts.Parameter(group="Job Configuration Parameters"),
    ] = False,
) -> None:
    """
    Command-line interface to batch post inventory records to FOLIO

    Parameters:
        config_file: Path to JSON config file (overrides CLI parameters).
        gateway_url: The FOLIO API Gateway URL.
        tenant_id: The tenant id.
        username: The FOLIO username.
        password: The FOLIO password.
        member_tenant_id: The FOLIO ECS member tenant id (if applicable).
        object_type: Type of inventory object (Instances, Holdings, or Items).
        file_paths: Path(s) to JSONL file(s) to post.
        batch_size: Number of records to include in each batch (1-1000).
        upsert: Enable upsert mode to update existing records.
        preserve_statistical_codes: Preserve existing statistical codes during upsert.
        preserve_administrative_notes: Preserve existing administrative notes during upsert.
        preserve_temporary_locations: Preserve temporary location assignments during upsert.
        preserve_temporary_loan_types: Preserve temporary loan type assignments during upsert.
        overwrite_item_status: Overwrite item status during upsert.
        patch_existing_records: Enable selective field patching during upsert.
        patch_paths: Comma-separated list of field paths to patch.
        failed_records_file: Path to file for writing failed records.
        no_progress: Disable progress bar display.
    """
    set_up_cli_logging()

    gateway_url, tenant_id, username, password = get_folio_connection_parameters(
        gateway_url, tenant_id, username, password
    )
    folio_client = folioclient.FolioClient(gateway_url, tenant_id, username, password)

    if member_tenant_id:
        folio_client.tenant_id = member_tenant_id

    # Handle file path expansion
    expanded_file_paths = expand_file_paths(file_paths)

    expanded_file_paths.sort()

    # Parse patch_paths if provided
    patch_paths_list = parse_patch_paths(patch_paths)

    try:
        if config_file:
            config, files_to_process = parse_config_file(config_file)
        else:
            if not object_type:
                logger.critical("--object-type is required when not using a config file")
                sys.exit(1)

            if not expanded_file_paths:
                logger.critical("No files found to process. Exiting.")
                sys.exit(1)

            config = BatchPoster.Config(
                object_type=object_type,
                batch_size=batch_size,
                upsert=upsert,
                preserve_statistical_codes=preserve_statistical_codes,
                preserve_administrative_notes=preserve_administrative_notes,
                preserve_temporary_locations=preserve_temporary_locations,
                preserve_temporary_loan_types=preserve_temporary_loan_types,
                preserve_item_status=not overwrite_item_status,
                patch_existing_records=patch_existing_records,
                patch_paths=patch_paths_list,
                no_progress=no_progress,
            )
            files_to_process = expanded_file_paths

        logger.info(f"Processing {len(files_to_process)} file(s)")
        asyncio.run(run_batch_poster(folio_client, config, files_to_process, failed_records_file))

    except Exception as e:
        logger.critical(f"An error occurred: {e}", exc_info=True)
        sys.exit(1)


def parse_config_file(config_file):
    with open(config_file, "r") as f:
        config_data = json.load(f)
        # Convert file_paths if present in config
    if "file_paths" in config_data:
        config_data["file_paths"] = [Path(p) for p in config_data["file_paths"]]
    config = BatchPoster.Config(**config_data)
    files_to_process = config_data.get("file_paths", [])
    return config, files_to_process


def parse_patch_paths(patch_paths):
    patch_paths_list = None
    if patch_paths:
        patch_paths_list = [p.strip() for p in patch_paths.split(",") if p.strip()]
    return patch_paths_list


def expand_file_paths(file_paths):
    expanded_paths: List[Path] = []
    if file_paths:
        for file_path in file_paths:
            file_path_str = str(file_path)
            if any(char in file_path_str for char in ["*", "?", "["]):
                # It's a glob pattern - expand it
                expanded = glob_module.glob(file_path_str)
                expanded_paths.extend([Path(x) for x in expanded])
            else:
                # It's a regular path
                expanded_paths.append(file_path)
    return expanded_paths


async def run_batch_poster(
    folio_client: FolioClient,
    config: "BatchPoster.Config",
    files_to_process: List[Path],
    failed_records_file: Path | None,
):
    """
    Run the batch poster operation.

    Args:
        folio_client: Authenticated FOLIO client
        config: BatchPoster configuration
        files_to_process: List of file paths to process
        failed_records_file: Optional path for failed records
    """
    async with folio_client:
        try:
            # Create progress reporter
            reporter = (
                NoOpProgressReporter()
                if config.no_progress
                else RichProgressReporter(show_speed=True, show_time=True)
            )

            poster = BatchPoster(
                folio_client, config, failed_records_file=failed_records_file, reporter=reporter
            )
            async with poster:
                await poster.do_work(files_to_process)
                log_final_stats(poster)

        except Exception as e:
            logger.critical(f"Batch posting failed: {e}", exc_info=True)
            raise


def log_final_stats(poster: BatchPoster) -> None:
    """
    Log the final statistics after batch posting.

    Args:
        poster: The BatchPoster instance containing the stats
    """
    # Log final statistics
    logger.info("=" * 60)
    logger.info("Batch posting complete!")
    logger.info("=" * 60)
    total_processed = poster.stats.records_processed
    logger.info("Total records processed: %d", total_processed)
    logger.info("Records posted successfully: %d", poster.stats.records_posted)
    logger.info("Records created: %d", poster.stats.records_created)
    logger.info("Records updated: %d", poster.stats.records_updated)
    logger.info("Records failed: %d", poster.stats.records_failed)
    logger.info("Total batches posted: %d", poster.stats.batches_posted)
    logger.info("Total batches failed: %d", poster.stats.batches_failed)
    if poster._failed_records_path:
        logger.info("Failed records written to: %s", poster._failed_records_path)


if __name__ == "__main__":
    app()
