# User Import Guide

The User Import tool loads user records into FOLIO from JSON Lines files. It provides an alternative to FOLIO's built-in `/user-import` API with additional features for field protection and flexible user matching.

## Overview

User Import:

- Reads individual user objects from JSON Lines files
- Supports user objects compatible with both mod-user-import and mod-users record schemas
- Resolves reference data (patron groups, address types, departments, service points) by name or code
- Handles service point assignments via the `/service-points-users` API
- Creates request preferences and permission user records for new users
- Provides job-level and per-record field protection during updates
- Supports partial updates (only update present fields)
- Offers flexible user matching (username, barcode, externalSystemId) with forced matching on `id`
- Batch processing with real-time progress tracking

## Basic Usage

### Command Line

```bash
folio-data-import users \
  --gateway-url https://folio-snapshot-okapi.dev.folio.org \
  --tenant-id diku \
  --username diku_admin \
  --password admin \
  --library-name "My Library" \
  --user-file-path users.jsonl
```

### Using a Configuration File

```bash
folio-data-import users config.json
```

Example `config.json`:

```json
{
  "library_name": "My Library",
  "user_file_paths": ["users1.jsonl", "users2.jsonl"],
  "batch_size": 250,
  "user_match_key": "externalSystemId",
  "fields_to_protect": ["username", "barcode"],
  "default_preferred_contact_type": "email",
  "only_update_present_fields": false,
  "limit_simultaneous_requests": 10
}
```

## Command-Line Parameters

### Connection Parameters

| Parameter | Environment Variable | Description |
|-----------|---------------------|-------------|
| `--gateway-url` | `FOLIO_GATEWAY_URL` | FOLIO gateway URL (required) |
| `--tenant-id` | `FOLIO_TENANT_ID` | FOLIO tenant identifier (required) |
| `--username` | `FOLIO_USERNAME` | Username for authentication (required) |
| `--password` | `FOLIO_PASSWORD` | User password (required) |
| `--member-tenant-id` | `FOLIO_MEMBER_TENANT_ID` | ECS member tenant ID (for multi-tenant environments) |

### Job Configuration

| Parameter | Environment Variable | Default | Description |
|-----------|---------------------|---------|-------------|
| `--library-name` | `FOLIO_LIBRARY_NAME` | **Required** | Library name for the import job |
| `--user-file-path` / `--user-file-paths` | - | **Required** | Path(s) to JSON Lines file(s). Supports multiple paths and glob patterns. |
| `--batch-size` | `FOLIO_USER_IMPORT_BATCH_SIZE` | 250 | Users per batch (1-1000) |
| `--user-match-key` | - | `externalSystemId` | Match key: `username`, `barcode`, or `externalSystemId` |
| `--default-preferred-contact-type` | - | `email` | Default contact type (see table below) |
| `--fields-to-protect` | `FOLIO_FIELDS_TO_PROTECT` | (none) | Comma-separated list of field paths to protect |
| `--update-only-present-fields` | - | `false` | Only update fields present in input |
| `--limit-async-requests` | `FOLIO_LIMIT_ASYNC_REQUESTS` | 10 | Max concurrent HTTP requests (1-100) |
| `--report-file-base-path` | - | Current directory | Base path for report files |
| `--config-file` | - | (none) | Path to JSON config file (overrides CLI parameters) |
| `--no-progress` | - | `false` | Disable progress display |

### Preferred Contact Types

The `--default-preferred-contact-type` parameter accepts either the ID or name:

| ID | Name |
|----|------|
| `001` | `mail` |
| `002` | `email` |
| `003` | `text` |
| `004` | `phone` |
| `005` | `mobile` |

## User Data Format

### JSON Lines Format

Input must be in **JSON Lines** format (.jsonl) - one user object per line. Each user object should be compatible with FOLIO's mod-users API user record format.

```{note}
This tool does **not** support the full mod-user-import payload format (which wraps users in a `users` array). It reads individual user objects directly, one per line.
```

```{note}
This tool does **not** support creating custom field definitions or department definitions. These must already exist in FOLIO.
```

Example `users.jsonl`:

```json
{"username": "jdoe", "externalSystemId": "12345", "barcode": "1001", "active": true, "patronGroup": "undergraduate", "personal": {"lastName": "Doe", "firstName": "John", "email": "jdoe@example.edu"}}
{"username": "asmith", "externalSystemId": "12346", "barcode": "1002", "active": true, "patronGroup": "faculty", "personal": {"lastName": "Smith", "firstName": "Alice", "email": "asmith@example.edu"}}
```

### User Object Fields

Common fields include:

**Identification:**
- `username`: Unique login identifier
- `externalSystemId`: External system identifier  
- `barcode`: User barcode
- `id`: FOLIO UUID (if present, forces matching on this field)
- `active`: Boolean status

**Personal Information (personal object):**
- `lastName`: Last name (required)
- `firstName`: First name
- `email`: Email address
- `phone`: Phone number
- `preferredContactTypeId`: Preferred contact type (ID or name)
- `addresses`: Array of address objects

**Group and Department:**
- `patronGroup`: Patron group name or UUID (required)
- `departments`: Array of department names or UUIDs

**Service Points:**
- `servicePointsUser`: Service point assignment object (see below)

## Reference Data Resolution

The importer automatically resolves human-friendly names to UUIDs for:

| Field | API Endpoint | Key Field |
|-------|-------------|-----------|
| `patronGroup` | `/groups` | `group` |
| `addresses[].addressTypeId` | `/addresstypes` | `addressType` |
| `departments[]` | `/departments` | `name` |
| Service point codes | `/service-points` | `code` |

You can use either the human-friendly name or the UUID directly:

```text
{"patronGroup": "undergraduate", ...}
{"patronGroup": "54e17c4c-e315-4c99-9bb6-6c2f31e3a9e5", ...}
```

## User Matching

### Match Keys

The importer matches users in FOLIO using the configured match key:

```bash
# Match by externalSystemId (default)
folio-data-import users \
  --library-name "My Library" \
  --user-file-path users.jsonl \
  --user-match-key externalSystemId

# Match by username
folio-data-import users \
  --library-name "My Library" \
  --user-file-path users.jsonl \
  --user-match-key username

# Match by barcode
folio-data-import users \
  --library-name "My Library" \
  --user-file-path users.jsonl \
  --user-match-key barcode
```

### Forced Matching on `id`

If a user record includes an `id` field, the importer **always** matches on `id` regardless of the configured match key. This ensures that records with explicit UUIDs update the correct user:

```json
{"id": "550e8400-e29b-41d4-a716-446655440000", "username": "jdoe", "externalSystemId": "12345", "active": true, "patronGroup": "undergraduate", "personal": {"lastName": "Doe", "firstName": "John"}}
```

## Field Protection

### Job-Level Protection

Protect specific fields from being overwritten during updates:

```bash
folio-data-import users \
  --library-name "My Library" \
  --user-file-path users.jsonl \
  --fields-to-protect username,barcode,personal.email
```

Nested fields use dot notation: `personal.email`, `personal.addresses`

### Per-Record Protection

Individual user records can specify their own protected fields via `customFields.protectedFields` (comma-separated string):

```json
{"username": "jdoe", "externalSystemId": "12345", "active": true, "patronGroup": "undergraduate", "personal": {"lastName": "Doe", "firstName": "John"}, "customFields": {"protectedFields": "barcode,personal.phone"}}
```

Job-level and per-record protections are combined.

## Update Only Present Fields

The `--update-only-present-fields` option enables partial updates where only fields present in the input are modified:

```bash
folio-data-import users \
  --library-name "My Library" \
  --user-file-path users.jsonl \
  --update-only-present-fields
```

When enabled, missing fields in the input are preserved from the existing record rather than being cleared. This is useful for targeted updates.

## Service Point Assignment

Assign service points using codes (resolved automatically) or UUIDs:

```json
{"username": "jdoe", "externalSystemId": "12345", "active": true, "patronGroup": "staff", "personal": {"lastName": "Doe", "firstName": "John"}, "servicePointsUser": {"servicePointsIds": ["MAIN-CIRC", "LAW-LIB"], "defaultServicePointId": "MAIN-CIRC"}}
```

The `servicePointsUser` object:
- `servicePointsIds`: Array of service point codes or UUIDs
- `defaultServicePointId`: Default service point code or UUID

The importer handles service point assignments separately via the `/service-points-users` API.

## Addresses

Include multiple addresses per user:

```json
{"username": "jdoe", "externalSystemId": "12345", "active": true, "patronGroup": "faculty", "personal": {"lastName": "Doe", "firstName": "John", "addresses": [{"countryId": "US", "addressLine1": "123 Main St", "city": "Springfield", "region": "IL", "postalCode": "62701", "addressTypeId": "Home", "primaryAddress": true}, {"addressLine1": "456 Oak Ave", "city": "Springfield", "region": "IL", "postalCode": "62702", "addressTypeId": "Work"}]}}
```

Address type names (like "Home", "Work") are resolved to UUIDs automatically.

## Multiple Input Files

Process multiple files using glob patterns or multiple paths:

```bash
# Multiple explicit paths
folio-data-import users \
  --library-name "My Library" \
  --user-file-path users1.jsonl \
  --user-file-path users2.jsonl

# Glob pattern
folio-data-import users \
  --library-name "My Library" \
  --user-file-path "data/*.jsonl"
```

## Error Handling

### Failed Records

Failed imports are automatically logged to `failed_user_import_TIMESTAMP.txt` in the current directory (or the path specified by `--report-file-base-path`). The file contains the user objects (one per line in JSON Lines format) that failed to import.

Example failed record:

```json
{"username": "jdoe", "externalSystemId": "12345", "barcode": "1001", "active": true, "patronGroup": "undergraduate", "personal": {"lastName": "Doe", "firstName": "John", "email": "jdoe@example.edu"}}
```

Error details are logged to the console/log output, not written to the failed records file.

### Custom Report Path

```bash
folio-data-import users \
  --library-name "My Library" \
  --user-file-path users.jsonl \
  --report-file-base-path /path/to/reports/
```

### Common Validation Errors

- **Missing patron group**: Patron group doesn't exist in FOLIO
- **Duplicate unique field**: Username/barcode/`externalSystemId` already exists
- **Invalid service point code**: Service point code not found
- **Missing required field**: `library-name` or `user-file-path` not provided

## Progress Tracking

Real-time progress bars show:
- Total users processed
- Successful creates/updates
- Failed imports
- Processing speed and time

Disable for automation:

```bash
folio-data-import users \
  --library-name "My Library" \
  --user-file-path users.jsonl \
  --no-progress
```

## Environment Variables

Connection parameters can be set via environment variables:

```bash
export FOLIO_GATEWAY_URL="https://folio-snapshot-okapi.dev.folio.org"
export FOLIO_TENANT_ID="diku"
export FOLIO_USERNAME="diku_admin"
export FOLIO_PASSWORD="admin"
export FOLIO_LIBRARY_NAME="My Library"
export FOLIO_USER_IMPORT_BATCH_SIZE="250"
export FOLIO_FIELDS_TO_PROTECT="username,barcode"
export FOLIO_LIMIT_ASYNC_REQUESTS="10"
```

## Workflow Example

```bash
# 1. Prepare user data in JSON Lines format
# Each line is a complete JSON object

# 2. Set environment variables (optional)
export FOLIO_GATEWAY_URL="https://folio-snapshot-okapi.dev.folio.org"
export FOLIO_TENANT_ID="diku"
export FOLIO_USERNAME="diku_admin"
export FOLIO_PASSWORD="admin"

# 3. Import users with field protection
folio-data-import users \
  --library-name "Main Library" \
  --user-file-path new_students.jsonl \
  --user-match-key externalSystemId \
  --fields-to-protect username,barcode \
  --default-preferred-contact-type email \
  --batch-size 250

# 4. Check results
# - New users are created
# - Existing users updated (protected fields preserved)
# - Errors logged to failed_user_import_TIMESTAMP.txt
```

## Complete Example

Full-featured user import with all options:

```bash
folio-data-import users \
  --gateway-url https://folio-snapshot-okapi.dev.folio.org \
  --tenant-id diku \
  --username diku_admin \
  --password admin \
  --library-name "Main Library" \
  --user-file-path new_faculty.jsonl \
  --user-match-key externalSystemId \
  --fields-to-protect username,barcode,personal.email \
  --default-preferred-contact-type email \
  --update-only-present-fields \
  --batch-size 250 \
  --limit-async-requests 20 \
  --report-file-base-path /var/log/folio/
```

## Comparison with mod-user-import

| Feature | mod-user-import | folio-data-import users |
|---------|-----------------|-------------------------|
| Input format | Wrapped JSON with `users` array | JSON Lines (one user object per line) |
| API approach | Single POST to `/user-import` | Individual POST/PUT to `/users` |
| Service points | N/A | Codes or UUIDs via `/service-points-users` |
| Field protection | `updateOnlyPresentFields` for addresses | Job-level and per-record for any field |
| Contact type | `mail`, `email`, `text`, `phone`, `mobile` | Same values plus IDs (`001`-`005`) |
| Match key | `externalSystemId` only | Configurable with forced matching on `id` |
| Custom fields | Can define and manage via `included` | Values only (definitions must exist in FOLIO) |
| Departments | Can create via `included` | Values only (must already exist in FOLIO) |
| Batch processing | Single request | Configurable batch size (default 250) |
| Progress tracking | None | Real-time progress bars |
| Concurrent requests | N/A | Configurable (default 10, max 100) |

## See Also

- [Quick Start](quick_start.md)
- [Core Concepts](concepts.md)
- [Examples](examples.md)
- [Troubleshooting](troubleshooting.md)
- [mod-user-import Documentation](https://github.com/folio-org/mod-user-import)
