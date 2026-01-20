# Batch Poster Guide

Batch Poster is a tool for posting Inventory records (Instances, Holdings, Items) to FOLIO using the batch synchronous storage APIs.

## Overview

Batch Poster:

- Posts records in configurable batches to FOLIO's storage APIs
- Supports upsert operations (create or update)
- Provides field preservation options during updates
- Tracks progress with real-time feedback
- Captures failed records for retry

## Supported Record Types

Batch Poster works exclusively with FOLIO Inventory storage records:

| Object Type | API Endpoint | Description |
|-------------|--------------|-------------|
| `Instances` | `/instance-storage/batch/synchronous` | Bibliographic records |
| `Holdings` | `/holdings-storage/batch/synchronous` | Holdings records |
| `Items` | `/item-storage/batch/synchronous` | Item records |

```{note}
For other data types, use the appropriate tool:
- **Users**: Use the `users` command
- **MARC Records**: Use the `marc` command
```

## Input Format

Input files must be **JSON Lines** format (`.jsonl`) with one record per line:

```json
{"id": "550e8400-e29b-41d4-a716-446655440000", "title": "The Great Gatsby", "instanceTypeId": "6312d172-f0cf-40f6-b27d-9fa8feaf332f", "source": "FOLIO"}
{"id": "660e8400-e29b-41d4-a716-446655440001", "title": "1984", "instanceTypeId": "6312d172-f0cf-40f6-b27d-9fa8feaf332f", "source": "FOLIO"}
```

Each record must include an `id` field (UUID). For holdings records, also include `sourceId`.

## Basic Usage

### Command Line

```bash
folio-data-import batch-poster \
  --gateway-url https://folio-snapshot-okapi.dev.folio.org \
  --tenant-id diku \
  --username diku_admin \
  --password admin \
  --object-type Instances \
  --file-path instances.jsonl
```

### CLI Parameters

#### FOLIO Connection Parameters

| Parameter | Environment Variable | Description |
|-----------|---------------------|-------------|
| `--gateway-url` | `FOLIO_GATEWAY_URL` | FOLIO API gateway URL |
| `--tenant-id` | `FOLIO_TENANT_ID` | FOLIO tenant identifier |
| `--username` | `FOLIO_USERNAME` | Username for authentication |
| `--password` | `FOLIO_PASSWORD` | User password |
| `--member-tenant-id` | `FOLIO_MEMBER_TENANT_ID` | ECS member tenant (if applicable) |

#### Job Configuration Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--object-type` | (required) | Record type: `Instances`, `Holdings`, or `Items` |
| `--file-path` | (required) | Path(s) to JSONL file(s). Accepts multiple values and glob patterns |
| `--batch-size` | 100 | Number of records per batch (1-1000) |
| `--upsert` | false | Enable upsert mode to update existing records |
| `--failed-records-file` | none | Path to file for writing failed records |
| `--no-progress` | false | Disable progress bar display |

#### Upsert Options

These options only apply when `--upsert` is enabled:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--preserve-statistical-codes` | false | Keep existing statistical codes (merged with new) |
| `--preserve-administrative-notes` | false | Keep existing administrative notes (merged with new) |
| `--preserve-temporary-locations` | false | Keep existing temporary location (Items only) |
| `--preserve-temporary-loan-types` | false | Keep existing temporary loan type (Items only) |
| `--overwrite-item-status` | false | Allow item status changes (status preserved by default) |
| `--patch-existing-records` | false | Enable selective field patching |
| `--patch-paths` | none | Comma-separated list of fields to patch |

## Configuration File

For complex configurations, use a JSON configuration file:

```bash
folio-data-import batch-poster config.json \
  --gateway-url https://folio-snapshot-okapi.dev.folio.org \
  --tenant-id diku \
  --username diku_admin \
  --password admin
```

**config.json:**
```json
{
  "object_type": "Items",
  "file_paths": ["items1.jsonl", "items2.jsonl"],
  "batch_size": 100,
  "upsert": true,
  "preserve_statistical_codes": true,
  "preserve_administrative_notes": true,
  "preserve_temporary_locations": true,
  "preserve_temporary_loan_types": true
}
```

Configuration uses snake_case keys. CLI parameters override config file values.

## Upsert Mode

### Basic Upsert

Enable upsert to create new records or update existing ones:

```bash
folio-data-import batch-poster \
  --gateway-url https://folio-snapshot-okapi.dev.folio.org \
  --tenant-id diku \
  --username diku_admin \
  --password admin \
  --object-type Items \
  --file-path items.jsonl \
  --upsert
```

Records are matched by their `id` field. Existing records are fetched to obtain their `_version` for optimistic locking.

### Preservation Options

When updating existing records, you can preserve specific data:

```bash
folio-data-import batch-poster \
  --gateway-url https://folio-snapshot-okapi.dev.folio.org \
  --tenant-id diku \
  --username diku_admin \
  --password admin \
  --object-type Items \
  --file-path items.jsonl \
  --upsert \
  --preserve-statistical-codes \
  --preserve-administrative-notes \
  --preserve-temporary-locations \
  --preserve-temporary-loan-types
```

**How preservation works:**

- **Statistical codes**: Existing codes are merged with new codes (duplicates removed)
- **Administrative notes**: Existing notes are merged with new notes (duplicates removed)
- **Temporary locations**: Existing temporary location is kept (Items only)
- **Temporary loan types**: Existing temporary loan type is kept (Items only)
- **Item status**: Preserved by default; use `--overwrite-item-status` to change

### Selective Field Patching

For fine-grained updates, use `--patch-existing-records` with `--patch-paths`:

```bash
folio-data-import batch-poster \
  --gateway-url https://folio-snapshot-okapi.dev.folio.org \
  --tenant-id diku \
  --username diku_admin \
  --password admin \
  --object-type Items \
  --file-path items.jsonl \
  --upsert \
  --patch-existing-records \
  --patch-paths "barcode,materialTypeId"
```

This updates **only** `barcode` and `materialTypeId` from your input file while preserving all other fields from the existing record.

## Multiple Files

Process multiple files in one run:

```bash
folio-data-import batch-poster \
  --gateway-url https://folio-snapshot-okapi.dev.folio.org \
  --tenant-id diku \
  --username diku_admin \
  --password admin \
  --object-type Instances \
  --file-path file1.jsonl \
  --file-path file2.jsonl \
  --file-path file3.jsonl
```

Or use glob patterns:

```bash
folio-data-import batch-poster \
  --gateway-url https://folio-snapshot-okapi.dev.folio.org \
  --tenant-id diku \
  --username diku_admin \
  --password admin \
  --object-type Instances \
  --file-path "data/*.jsonl"
```

## Error Handling

### Failed Records File

Capture failed records for later review or retry:

```bash
folio-data-import batch-poster \
  --gateway-url https://folio-snapshot-okapi.dev.folio.org \
  --tenant-id diku \
  --username diku_admin \
  --password admin \
  --object-type Items \
  --file-path items.jsonl \
  --failed-records-file failed_items.jsonl
```

Failed records are written in JSON Lines format, allowing you to fix issues and re-run.

### Error Types

Common errors and solutions:

| Error | Cause | Solution |
|-------|-------|----------|
| 422 Unprocessable Entity | Invalid record data | Check required fields, valid UUIDs |
| 409 Conflict | Duplicate record without upsert | Enable `--upsert` or remove duplicates |
| 400 Bad Request | Malformed JSON | Validate JSON Lines format |
| Timeout | Batch too large | Reduce `--batch-size` |

## Progress Tracking

By default, a progress bar shows:

- Total records to process
- Records completed
- Success/failure counts
- Processing rate

Disable for CI/CD or scripting:

```bash
--no-progress
```

## Common Workflows

### Initial Load (No Upsert)

For loading new records into an empty system:

```bash
folio-data-import batch-poster \
  --gateway-url https://folio-snapshot-okapi.dev.folio.org \
  --tenant-id diku \
  --username diku_admin \
  --password admin \
  --object-type Instances \
  --file-path instances.jsonl \
  --batch-size 100
```

### Bulk Update with Preservation

Update existing records while preserving administrative data:

```bash
folio-data-import batch-poster \
  --gateway-url https://folio-snapshot-okapi.dev.folio.org \
  --tenant-id diku \
  --username diku_admin \
  --password admin \
  --object-type Items \
  --file-path items.jsonl \
  --upsert \
  --preserve-statistical-codes \
  --preserve-administrative-notes \
  --failed-records-file failed_items.jsonl
```

### Update Specific Fields Only

Update only barcodes without touching other fields:

```bash
folio-data-import batch-poster \
  --gateway-url https://folio-snapshot-okapi.dev.folio.org \
  --tenant-id diku \
  --username diku_admin \
  --password admin \
  --object-type Items \
  --file-path barcode_updates.jsonl \
  --upsert \
  --patch-existing-records \
  --patch-paths "barcode"
```

## Environment Variables

Set connection parameters as environment variables to simplify commands:

```bash
export FOLIO_GATEWAY_URL="https://folio-snapshot-okapi.dev.folio.org"
export FOLIO_TENANT_ID="diku"
export FOLIO_USERNAME="diku_admin"
export FOLIO_PASSWORD="admin"

# Then run with just job parameters
folio-data-import batch-poster \
  --object-type Instances \
  --file-path instances.jsonl \
  --upsert
```

## See Also

- [Examples](examples.md) - More usage examples
- [Concepts](concepts.md) - Architecture overview
- [Troubleshooting](troubleshooting.md) - Common issues and solutions
