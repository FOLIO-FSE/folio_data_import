# Examples

This page provides complete, working examples for common use cases.

## MARC Data Import

### Basic MARC Import

Import MARC records using an interactive profile selection:

```bash
folio-data-import marc \
  --gateway-url https://folio-snapshot-okapi.dev.folio.org \
  --tenant-id diku \
  --username diku_admin \
  --password admin \
  --marc-file-path catalog_records.mrc
```

### MARC Import with Named Profile

Specify the Data Import Job Profile by name:

```bash
folio-data-import marc \
  --gateway-url https://folio-snapshot-okapi.dev.folio.org \
  --tenant-id diku \
  --username diku_admin \
  --password admin \
  --marc-file-path bibs.mrc \
  --import-profile-name "Default - Create Instance and SRS MARC Bib"
```

### MARC Import with Preprocessors

Use MARC preprocessors to modify records before upload. Create a configuration file for preprocessors that require settings:

**preprocessor_config.json:**
```json
{
  "prepend_prefix_001": {
    "prefix": "LOCAL"
  }
}
```

```bash
folio-data-import marc \
  --gateway-url https://folio-snapshot-okapi.dev.folio.org \
  --tenant-id diku \
  --username diku_admin \
  --password admin \
  --marc-file-path records.mrc \
  --import-profile-name "Default - Create Instance and SRS MARC Bib" \
  --preprocessor "prepend_prefix_001,clean_empty_fields" \
  --preprocessor-config preprocessor_config.json
```

### MARC Import with Multiple Files

Process multiple MARC files in one job:

```bash
folio-data-import marc \
  --gateway-url https://folio-snapshot-okapi.dev.folio.org \
  --tenant-id diku \
  --username diku_admin \
  --password admin \
  --marc-file-path file1.mrc \
  --marc-file-path file2.mrc \
  --marc-file-path file3.mrc \
  --import-profile-name "Default - Create Instance and SRS MARC Bib"
```

### MARC Import Using Glob Pattern

Use wildcards to import multiple files:

```bash
folio-data-import marc \
  --gateway-url https://folio-snapshot-okapi.dev.folio.org \
  --tenant-id diku \
  --username diku_admin \
  --password admin \
  --marc-file-path "exports/*.mrc" \
  --import-profile-name "Default - Create Instance and SRS MARC Bib"
```

### MARC Import with Configuration File

For complex imports, use a JSON configuration file. Note that connection parameters are provided via CLI or environment variables, not in the config file:

**marc_config.json:**
```json
{
  "marc_files": ["catalog1.mrc", "catalog2.mrc"],
  "import_profile_name": "Default - Create Instance and SRS MARC Bib",
  "batch_size": 10,
  "batch_delay": 1.0,
  "marc_record_preprocessors": "prepend_prefix_001,clean_empty_fields",
  "preprocessors_args": {
    "prepend_prefix_001": {
      "prefix": "LOCAL"
    }
  }
}
```

```bash
folio-data-import marc marc_config.json \
  --gateway-url https://folio-snapshot-okapi.dev.folio.org \
  --tenant-id diku \
  --username diku_admin \
  --password admin
```

### Split Large MARC Files

For very large files, split into smaller jobs:

```bash
folio-data-import marc \
  --gateway-url https://folio-snapshot-okapi.dev.folio.org \
  --tenant-id diku \
  --username diku_admin \
  --password admin \
  --marc-file-path huge_file.mrc \
  --import-profile-name "Default - Create Instance and SRS MARC Bib" \
  --split-files \
  --split-size 1000
```

### Resume a Split Import

Skip already-processed splits when resuming:

```bash
folio-data-import marc \
  --gateway-url https://folio-snapshot-okapi.dev.folio.org \
  --tenant-id diku \
  --username diku_admin \
  --password admin \
  --marc-file-path huge_file.mrc \
  --import-profile-name "Default - Create Instance and SRS MARC Bib" \
  --split-files \
  --split-size 1000 \
  --split-offset 5
```

## User Import

### Basic User Import

Import users from JSON Lines file:

```bash
folio-data-import users \
  --gateway-url https://folio-snapshot-okapi.dev.folio.org \
  --tenant-id diku \
  --username diku_admin \
  --password admin \
  --library-name "Main Library" \
  --user-file-path students.jsonl
```

**students.jsonl:**
```json
{"username": "jdoe", "externalSystemId": "12345", "barcode": "1001", "active": true, "patronGroup": "undergraduate", "personal": {"lastName": "Doe", "firstName": "John", "email": "jdoe@example.edu"}}
{"username": "asmith", "externalSystemId": "12346", "barcode": "1002", "active": true, "patronGroup": "undergraduate", "personal": {"lastName": "Smith", "firstName": "Alice", "email": "asmith@example.edu"}}
```

### User Import with Service Points

Assign service points using codes instead of UUIDs. Service points go in the `servicePointsUser` object:

```bash
folio-data-import users \
  --gateway-url https://folio-snapshot-okapi.dev.folio.org \
  --tenant-id diku \
  --username diku_admin \
  --password admin \
  --library-name "Main Library" \
  --user-file-path faculty.jsonl
```

**faculty.jsonl:**
```json
{"username": "prof_jones", "externalSystemId": "FAC-001", "barcode": "2001", "active": true, "patronGroup": "faculty", "personal": {"lastName": "Jones", "firstName": "Emily", "email": "ejones@example.edu"}, "servicePointsUser": {"servicePointsIds": ["MAIN-CIRC", "LAW-LIB"], "defaultServicePointId": "MAIN-CIRC"}}
```

### User Import with Field Protection

Protect specific fields from being overwritten during updates:

```bash
folio-data-import users \
  --gateway-url https://folio-snapshot-okapi.dev.folio.org \
  --tenant-id diku \
  --username diku_admin \
  --password admin \
  --library-name "Main Library" \
  --user-file-path updates.jsonl \
  --fields-to-protect username,personal.email,barcode
```

### User Import with Partial Updates

Only update fields present in the input, preserving all other existing data:

```bash
folio-data-import users \
  --gateway-url https://folio-snapshot-okapi.dev.folio.org \
  --tenant-id diku \
  --username diku_admin \
  --password admin \
  --library-name "Main Library" \
  --user-file-path updates.jsonl \
  --update-only-present-fields
```

### User Import with Custom Matching

Match existing users by username instead of externalSystemId:

```bash
folio-data-import users \
  --gateway-url https://folio-snapshot-okapi.dev.folio.org \
  --tenant-id diku \
  --username diku_admin \
  --password admin \
  --library-name "Main Library" \
  --user-file-path users.jsonl \
  --user-match-key username
```

Options: `externalSystemId` (default), `username`, or `barcode`

### User Import with Configuration File

**users_config.json:**
```json
{
  "library_name": "Main Library",
  "user_file_paths": ["new_students.jsonl", "new_faculty.jsonl"],
  "batch_size": 250,
  "user_match_key": "externalSystemId",
  "fields_to_protect": ["username", "barcode"],
  "default_preferred_contact_type": "email",
  "only_update_present_fields": false,
  "limit_simultaneous_requests": 10
}
```

```bash
folio-data-import users users_config.json \
  --gateway-url https://folio-snapshot-okapi.dev.folio.org \
  --tenant-id diku \
  --username diku_admin \
  --password admin
```

## Batch Poster

The batch-poster command posts Instances, Holdings, or Items to FOLIO's batch inventory endpoints.

### Post Instance Records

Create new instance records:

```bash
folio-data-import batch-poster \
  --gateway-url https://folio-snapshot-okapi.dev.folio.org \
  --tenant-id diku \
  --username diku_admin \
  --password admin \
  --object-type Instances \
  --file-path instances.jsonl
```

**instances.jsonl:**
```json
{"id": "550e8400-e29b-41d4-a716-446655440000", "title": "The Great Gatsby", "instanceTypeId": "6312d172-f0cf-40f6-b27d-9fa8feaf332f", "source": "FOLIO"}
{"id": "660e8400-e29b-41d4-a716-446655440001", "title": "1984", "instanceTypeId": "6312d172-f0cf-40f6-b27d-9fa8feaf332f", "source": "FOLIO"}
```

### Post Holdings Records

Holdings require a `sourceId` field:

```bash
folio-data-import batch-poster \
  --gateway-url https://folio-snapshot-okapi.dev.folio.org \
  --tenant-id diku \
  --username diku_admin \
  --password admin \
  --object-type Holdings \
  --file-path holdings.jsonl
```

**holdings.jsonl:**
```json
{"id": "660e8400-e29b-41d4-a716-446655440001", "instanceId": "550e8400-e29b-41d4-a716-446655440000", "permanentLocationId": "fcd64ce1-6995-48f0-840e-89ffa2288371", "sourceId": "f32d531e-df79-46b3-8932-cdd35f7a2264"}
{"id": "770e8400-e29b-41d4-a716-446655440002", "instanceId": "660e8400-e29b-41d4-a716-446655440001", "permanentLocationId": "fcd64ce1-6995-48f0-840e-89ffa2288371", "sourceId": "f32d531e-df79-46b3-8932-cdd35f7a2264"}
```

### Post Item Records

```bash
folio-data-import batch-poster \
  --gateway-url https://folio-snapshot-okapi.dev.folio.org \
  --tenant-id diku \
  --username diku_admin \
  --password admin \
  --object-type Items \
  --file-path items.jsonl
```

**items.jsonl:**
```json
{"id": "770e8400-e29b-41d4-a716-446655440002", "holdingsRecordId": "660e8400-e29b-41d4-a716-446655440001", "barcode": "36105217708001", "materialTypeId": "1a54b431-2e4f-452d-9cae-9cee66c9a892", "permanentLoanTypeId": "2b94c631-fca9-4892-a730-03ee529ffe27", "status": {"name": "Available"}}
{"id": "880e8400-e29b-41d4-a716-446655440003", "holdingsRecordId": "660e8400-e29b-41d4-a716-446655440001", "barcode": "36105217708002", "materialTypeId": "1a54b431-2e4f-452d-9cae-9cee66c9a892", "permanentLoanTypeId": "2b94c631-fca9-4892-a730-03ee529ffe27", "status": {"name": "Available"}}
```

### Upsert Mode

Enable upsert to update existing records or create new ones. Records are matched by `id`:

```bash
folio-data-import batch-poster \
  --gateway-url https://folio-snapshot-okapi.dev.folio.org \
  --tenant-id diku \
  --username diku_admin \
  --password admin \
  --object-type Instances \
  --file-path instances.jsonl \
  --upsert
```

### Upsert with Preservation Options

When using `--upsert`, you can preserve specific fields from existing records:

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

**Note:** Item status is preserved by default during upsert. Use `--overwrite-item-status` to allow status changes.

### Upsert with Selective Field Patching

Use `--patch-existing-records` with `--patch-paths` to update only specific fields while preserving all others:

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

### Custom Batch Size

Control the number of records per batch (default is 100):

```bash
folio-data-import batch-poster \
  --gateway-url https://folio-snapshot-okapi.dev.folio.org \
  --tenant-id diku \
  --username diku_admin \
  --password admin \
  --object-type Instances \
  --file-path instances.jsonl \
  --batch-size 50
```

### Capture Failed Records

Write failed records to a file for later review:

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

## Using Environment Variables

Set connection parameters once:

```bash
export FOLIO_GATEWAY_URL="https://folio-snapshot-okapi.dev.folio.org"
export FOLIO_TENANT_ID="diku"
export FOLIO_USERNAME="diku_admin"
export FOLIO_PASSWORD="admin"
```

Then simplify all commands:

```bash
# MARC import
folio-data-import marc --marc-file-path records.mrc

# User import
folio-data-import users \
  --library-name "Main Library" \
  --user-file-path users.jsonl

# Batch poster
folio-data-import batch-poster \
  --object-type Instances \
  --file-path instances.jsonl
```

## ECS Multi-Tenant Environments

For FOLIO ECS environments, use `--member-tenant-id` to specify the target member tenant:

```bash
folio-data-import users \
  --gateway-url https://folio-ecs.example.com \
  --tenant-id central \
  --username admin \
  --password secret \
  --member-tenant-id library-a \
  --library-name "Library A" \
  --user-file-path users.jsonl
```

## See Also

- [MARC Data Import Guide](marc_data_import_guide.md)
- [User Import Guide](user_import_guide.md)
- [Batch Poster Guide](batch_poster_guide.md)
- [Troubleshooting](troubleshooting.md)
