# Core Concepts

This page explains the key concepts and architecture behind folio-data-import.

## Architecture Overview

folio-data-import provides three specialized tools for loading data into FOLIO:

1. **MARC Data Import**: Loads bibliographic MARC records via FOLIO's Data Import change-manager APIs
2. **User Import**: Loads user records from JSON Lines files via FOLIO's /users and /service-points-users APIs
3. **Batch Poster**: Posts Inventory records (Instances, Holdings, Items) via batch storage APIs

Each tool is optimized for its specific data type and uses appropriate FOLIO APIs.

## MARC Data Import

### FOLIO Data Import System

The MARC tool uses FOLIO's **Data Import** system via the change-manager APIs. This requires:

- **Job Profiles**: Pre-configured workflows in FOLIO that define how MARC records are processed
- **Match Profiles**: Criteria for identifying existing records to update
- **Action Profiles**: Instructions for creating or updating FOLIO records
- **Mapping Profiles**: Rules for extracting data from MARC fields to FOLIO fields

```{note}
**Job Profiles are configured in FOLIO**, not in this tool. The tool uploads MARC records to FOLIO's Data Import system using a selected Job Profile. All field mapping, matching, and action logic is defined in FOLIO.
```

### Workflow

1. Initialize a job execution via `/change-manager/jobExecutions`
2. Associate the selected Job Profile with the job
3. Upload MARC records in chunks via `/change-manager/jobExecutions/{id}/records`
4. FOLIO processes records asynchronously according to the Job Profile
5. Job status can be monitored in FOLIO's Data Import logs

### MARC Preprocessors

Optional preprocessors modify MARC records **before** upload to FOLIO. Available preprocessors include:

- **clean_999_fields**: Removes 999 fields with first indicator 'f' and second indicator 'f'; moves other 999 fields to 945
- **strip_999_ff_fields**: Removes only 999 fields with indicators 'f', 'f'
- **clean_non_ff_999_fields**: Moves non-ff 999 fields to 945 with indicators '9', '9'
- **prepend_prefix_001**: Adds a custom prefix to the 001 field (requires configuration)
- **prepend_ppn_prefix_001**: Adds "(PPN)" prefix to the 001 field
- **prepend_abes_prefix_001**: Adds "(ABES)" prefix to the 001 field
- **fix_bib_leader**: Corrects invalid MARC leader values
- **clean_empty_fields**: Removes fields with no subfields or empty subfield values
- **sudoc_supercede_prep**: SUDOC-specific processing for superseded records

See the [MARC Preprocessors Guide](marc_preprocessors.md) for detailed documentation.

## User Import

### Input Format

The User tool reads **JSON Lines** files where each line is a complete user object following the mod-user-import schema:

```json
{"username": "jdoe", "externalSystemId": "12345", "patronGroup": "undergraduate", "personal": {"lastName": "Doe", "firstName": "John"}}
{"username": "asmith", "externalSystemId": "12346", "patronGroup": "faculty", "personal": {"lastName": "Smith", "firstName": "Alice"}}
```

This tool is an **alternative** to FOLIO's built-in `/user-import` API, offering additional features and more granular control.

### User Matching

The tool matches incoming users against existing FOLIO users to determine whether to create or update:

- **Default**: Match by `externalSystemId`
- **Alternative**: Match by `username` or `barcode` via `--user-match-key`
- **ID Override**: If the input record contains an `id` field, that UUID is always used for matching (takes precedence over `--user-match-key`)

### Reference Data Resolution

The tool automatically resolves human-readable names to FOLIO UUIDs:

- **Patron group names** → Patron group UUIDs
- **Service point codes** → Service point UUIDs
- **Address type names** → Address type UUIDs

### Service Points

Service point assignments are handled separately from the user record via FOLIO's `/service-points-users` API:

```json
{
  "username": "jdoe",
  "servicePointsUser": {
    "servicePointsIds": ["MAIN-CIRC", "BRANCH-REF"],
    "defaultServicePointId": "MAIN-CIRC"
  }
}
```

The `servicePointsUser` object is extracted from the input and processed separately after the user is created/updated.

### Field Protection

Two mechanisms protect fields from being overwritten during updates:

1. **CLI option**: `--fields-to-protect username,email,barcode`
2. **Per-user setting**: `customFields.protectedFields` in the existing user record (comma-separated string)

Both sources are combined when determining which fields to preserve.

### Workflow

```
JSON Lines File (.jsonl)
    ↓
Parse user objects
    ↓
Resolve reference data (patron groups, address types)
    ↓
Query existing user (by externalSystemId/username/barcode/id)
    ↓
If exists: Update (preserving protected fields)
If new: Create user
    ↓
POST/PUT via /users API
    ↓
Handle servicePointsUser separately via /service-points-users API
```

## Batch Poster

### Inventory Records Only

Batch Poster works with FOLIO Inventory storage records:

- **Instances**: Bibliographic records
- **Holdings**: Holdings records attached to instances
- **Items**: Item records attached to holdings

### Input Format

Input files are **JSON Lines** format with one record per line:

```json
{"id": "uuid-1", "title": "The Great Gatsby", "instanceTypeId": "uuid", "source": "FOLIO"}
{"id": "uuid-2", "title": "1984", "instanceTypeId": "uuid", "source": "FOLIO"}
```

### Batch Storage APIs

The tool uses FOLIO's **batch synchronous storage** endpoints:

- `/item-storage/batch/synchronous`
- `/holdings-storage/batch/synchronous`
- `/instance-storage/batch/synchronous`

These endpoints accept arrays of records and process them synchronously.

### Upsert Mode

When `--upsert` is enabled:

- Records are matched by `id` field
- Existing records are fetched to get their `_version` for optimistic locking
- New records are created; existing records are updated

### Preservation Options (Upsert Only)

When updating existing records, you can preserve specific data:

- `--preserve-statistical-codes`: Keep existing statistical codes (merged with new)
- `--preserve-administrative-notes`: Keep existing administrative notes (merged with new)
- `--preserve-temporary-locations`: Keep existing temporary location (Items only)
- `--preserve-temporary-loan-types`: Keep existing temporary loan type (Items only)
- Item status is **preserved by default**; use `--overwrite-item-status` to change

### Selective Patching

For fine-grained updates, use `--patch-existing-records` with `--patch-paths`:

```bash
--upsert --patch-existing-records --patch-paths "barcode,materialTypeId"
```

This updates only the specified fields while preserving all others from the existing record.

### Workflow

```
JSON Lines File (.jsonl)
    ↓
Parse records
    ↓
Batch records (default: 100 per batch)
    ↓
If upsert: Fetch existing records for _version
    ↓
POST to /{type}-storage/batch/synchronous?upsert=true
    ↓
Track success/failure per batch
```

## Common Patterns

### Batch Processing

All tools process records in batches:

- Configurable batch size
- Efficient API usage
- Progress tracking per batch
- Failed record tracking

### Progress Tracking

Real-time progress bars show:

- Total records to process
- Records completed
- Success/failure counts

Disable for CI/CD environments: `--no-progress`

### Error Handling

**MARC Import**:
- Errors are tracked in FOLIO's Data Import system
- Job IDs are saved locally to `marc_import_job_ids.txt`
- Check job status and errors in FOLIO UI (Data Import logs)

**User Import**:
- Failed user records are written to `failed_user_import_TIMESTAMP.txt`
- File contains only the raw user JSON (errors are logged to console/log file)
- Processing continues after failures

**Batch Poster**:
- Failed batches are written to a specified file (`--failed-records-file`)
- Detailed error messages logged
- Processing continues after batch failures

### Authentication

All tools authenticate via FOLIO's login API:

```bash
--gateway-url https://folio-snapshot-okapi.dev.folio.org \
--tenant-id diku \
--username diku_admin \
--password admin
```

Or via environment variables:

```bash
export FOLIO_GATEWAY_URL="https://folio-snapshot-okapi.dev.folio.org"
export FOLIO_TENANT_ID="diku"
export FOLIO_USERNAME="diku_admin"
export FOLIO_PASSWORD="admin"
```

### Configuration Files

All tools accept JSON configuration files:

```bash
folio-data-import marc config.json
folio-data-import users config.json
folio-data-import batch-poster config.json
```

Configuration files use snake_case keys matching the CLI parameter names.

## See Also

- [MARC Data Import Guide](marc_data_import_guide.md)
- [MARC Preprocessors](marc_preprocessors.md)
- [User Import Guide](user_import_guide.md)
- [Batch Poster Guide](batch_poster_guide.md)
- [Examples](examples.md)
