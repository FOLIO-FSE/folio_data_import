# MARC Data Import Guide

The MARC Data Import tool loads MARC 21 bibliographic and authority records into FOLIO using FOLIO's Data Import system via the change-manager APIs.

## Overview

MARC Data Import:

- Parses binary MARC21 files (.mrc)
- Uses FOLIO's Data Import system (change-manager APIs)
- Requires a Data Import Job Profile configured in FOLIO
- Supports optional MARC record preprocessing before upload
- Provides real-time progress tracking
- Handles large files by splitting into smaller jobs
- Saves job IDs for tracking in FOLIO's Data Import logs

## Basic Usage

### Command Line

```bash
folio-data-import marc \
  --gateway-url https://folio-snapshot-okapi.dev.folio.org \
  --tenant-id diku \
  --username diku_admin \
  --password admin \
  --marc-file-path records.mrc
```

The command will prompt you to select a [Data Import Job Profile](https://docs.folio.org/docs/metadata/additional-topics/jobprofiles/) configured in your FOLIO tenant.

### Using a Configuration File

For complex or repeated MARC import jobs, use a JSON configuration file:

```bash
folio-data-import marc config.json
```

Example `config.json`:

```json
{
  "marc_files": ["records1.mrc", "records2.mrc"],
  "import_profile_name": "Default - Create Instance and SRS MARC Bib",
  "batch_size": 10,
  "batch_delay": 1.0,
  "split_files": false,
  "split_size": 1000,
  "no_progress": false,
  "no_summary": false
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

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--marc-file-path` / `--marc-file-paths` | **Required** | Path(s) to MARC file(s). Accepts multiple values and glob patterns. |
| `--import-profile-name` | (interactive) | Name of the FOLIO Data Import Job Profile. If not provided, prompts interactively. |
| `--batch-size` | 10 | Number of records per batch (1-1000) |
| `--batch-delay` | 0.0 | Seconds to wait between batches |
| `--preprocessor` / `--preprocessors` | (none) | Comma-separated list of preprocessor names |
| `--preprocessor-config` / `--preprocessors-config` | (none) | Path to JSON file with preprocessor configuration |
| `--split-files` | `false` | Split large files into smaller jobs |
| `--split-size` | 1000 | Records per split (when using `--split-files`) |
| `--split-offset` | 0 | Number of splits to skip before starting |
| `--file-names-in-di-logs` | `false` | Show file names in Data Import logs |
| `--job-ids-file-path` | `marc_import_job_ids.txt` | Path to save job IDs |
| `--no-progress` | `false` | Disable progress bars |
| `--no-summary` | `false` | Skip final job summary |
| `--let-summary-fail` | `false` | Don't fail if summary cannot be retrieved |
| `--config-file` | (none) | Path to JSON config file (overrides CLI parameters) |

## Data Import Job Profiles

The tool uses **Data Import Job Profiles** configured in your FOLIO tenant. These profiles define:

- How MARC records are processed
- What FOLIO records are created (Instances, Holdings, Items, etc.)
- Field mapping rules
- Match and update criteria

To view available profiles in FOLIO:
1. Go to **Settings > Data Import > Job Profiles**
2. Note the profile name you want to use

Common profiles:
- **Default - Create Instance and SRS MARC Bib** - Creates bibliographic records
- **Default - Create SRS MARC Authority** - Creates authority records
- **Inventory Single Record - Default Update Instance** - Updates existing instances
- Custom profiles created by your library

### Specifying a Profile

Provide the profile name on the command line:

```bash
folio-data-import marc \
  --marc-file-path records.mrc \
  --import-profile-name "Default - Create Instance and SRS MARC Bib"
```

Or let the tool prompt you interactively (only profiles with MARC dataType are shown):

```bash
folio-data-import marc --marc-file-path records.mrc
# Will display a list of available profiles to choose from
```

## MARC Record Preprocessors

Optional preprocessors can modify MARC records **before** they're sent to FOLIO's Data Import system. This is useful for:

- Cleaning FOLIO-generated fields from records exported from another FOLIO system
- Fixing structural issues in MARC records
- Adapting records from specific sources (e.g., ABES SUDOC)
- Adding prefixes to control numbers

### Available Preprocessors

| Preprocessor | Description |
|-------------|-------------|
| `strip_999_ff_fields` | Remove 999 fields with indicators ff (FOLIO-generated) |
| `clean_999_fields` | Remove 999 ff fields and move other 999 fields to 945 |
| `clean_empty_fields` | Remove fields with no subfields or only empty subfields |
| `fix_bib_leader` | Fix invalid record type and bibliographic level in leader |
| `fix_auth_leader` | Fix invalid record type in authority record leader |
| `set_auth_type_personal` | Set authority type to personal name |
| `set_auth_type_corporate` | Set authority type to corporate name |
| `set_auth_type_meeting` | Set authority type to meeting name |
| `set_auth_type_geographic` | Set authority type to geographic name |
| `prepend_prefix_001` | Add prefix to 001 control number (requires config) |
| `sudoc_supercede_prep` | Process ABES SUDOC records for superseding |

### Basic Preprocessor Usage

Specify preprocessors by name (comma-separated):

```bash
folio-data-import marc \
  --marc-file-path records.mrc \
  --preprocessor "strip_999_ff_fields,fix_bib_leader"
```

### Preprocessor Configuration

Some preprocessors require configuration. Provide a JSON file:

```bash
folio-data-import marc \
  --marc-file-path records.mrc \
  --preprocessor "prepend_prefix_001,clean_empty_fields" \
  --preprocessor-config preprocessor_config.json
```

Example `preprocessor_config.json`:

```json
{
  "prepend_prefix_001": {
    "prefix": "LOCAL-"
  }
}
```

For complete preprocessor documentation, see [MARC Preprocessors Guide](marc_preprocessors.md).

## File Handling

### Multiple Files

Process multiple MARC files:

```bash
folio-data-import marc \
  --marc-file-path file1.mrc \
  --marc-file-path file2.mrc \
  --marc-file-path file3.mrc
```

### Glob Patterns

Use wildcards to process multiple files:

```bash
folio-data-import marc --marc-file-path "marc_exports/*.mrc"
```

Files are sorted before processing.

### Splitting Large Files

For very large files, split into smaller jobs to avoid timeouts:

```bash
folio-data-import marc \
  --marc-file-path large_file.mrc \
  --split-files \
  --split-size 1000
```

Resume a split job from a specific offset:

```bash
folio-data-import marc \
  --marc-file-path large_file.mrc \
  --split-files \
  --split-size 1000 \
  --split-offset 5  # Skip first 5 splits (5000 records)
```

## Output Files

The importer creates several output files in the same directory as the input MARC files:

| File | Description |
|------|-------------|
| `marc_import_job_ids.txt` | Job IDs for tracking in FOLIO (default location) |
| `bad_marc_records_TIMESTAMP.mrc` | Records that failed to parse |
| `failed_batches_TIMESTAMP.mrc` | Records from batches that failed to send |

### Custom Job ID File Location

```bash
folio-data-import marc \
  --marc-file-path records.mrc \
  --job-ids-file-path /path/to/job_ids.txt
```

## Progress and Job Tracking

### Real-Time Progress

Progress bars show:
- Records uploaded (sent to FOLIO)
- Records processed (imported by FOLIO)
- Processing speed and time

Disable for CI/CD environments:

```bash
folio-data-import marc --marc-file-path records.mrc --no-progress
```

### Job IDs

Job IDs are saved to `marc_import_job_ids.txt` (or custom path). Use these to check job status in FOLIO:

1. Go to **Data Import > View all logs**
2. Find your job by ID
3. View detailed import results

### Viewing in Data Import Logs

Enable file names in the Data Import logs:

```bash
folio-data-import marc \
  --marc-file-path records.mrc \
  --file-names-in-di-logs
```

## Workflow Example

```bash
# 1. Set environment variables (optional)
export FOLIO_GATEWAY_URL="https://folio-snapshot-okapi.dev.folio.org"
export FOLIO_TENANT_ID="diku"
export FOLIO_USERNAME="diku_admin"
export FOLIO_PASSWORD="admin"

# 2. Import MARC records with preprocessing
folio-data-import marc \
  --marc-file-path library_bibs.mrc \
  --import-profile-name "Default - Create Instance and SRS MARC Bib" \
  --preprocessor "strip_999_ff_fields,fix_bib_leader" \
  --batch-size 10 \
  --batch-delay 0.5

# 3. Check results
# - View job IDs in marc_import_job_ids.txt
# - Check Data Import logs in FOLIO UI
# - Review bad_marc_records_*.mrc for parsing failures
# - Review failed_batches_*.mrc for upload failures
```

## Complete Example

Full-featured MARC import with all options:

```bash
folio-data-import marc \
  --gateway-url https://folio-snapshot-okapi.dev.folio.org \
  --tenant-id diku \
  --username diku_admin \
  --password admin \
  --marc-file-path "exports/*.mrc" \
  --import-profile-name "Default - Create Instance and SRS MARC Bib" \
  --preprocessor "strip_999_ff_fields,clean_empty_fields,fix_bib_leader" \
  --preprocessor-config preprocessor_config.json \
  --batch-size 10 \
  --batch-delay 0.5 \
  --split-files \
  --split-size 1000 \
  --file-names-in-di-logs \
  --job-ids-file-path /var/log/folio/job_ids.txt
```

## Common Issues

### Job Summary Not Available

FOLIO's import logs can be unreliable. If the job summary fails to load:

1. Check **Data Import > View all logs** in FOLIO
2. Look up your job ID from `marc_import_job_ids.txt`
3. Use `--let-summary-fail` to continue without failing:

```bash
folio-data-import marc \
  --marc-file-path records.mrc \
  --let-summary-fail
```

4. Use `--no-summary` to skip summary retrieval entirely:

```bash
folio-data-import marc \
  --marc-file-path records.mrc \
  --no-summary
```

### Profile Not Found

If the import profile name isn't found:

1. Check exact spelling in **Settings > Data Import > Job Profiles**
2. Run without `--import-profile-name` to see available profiles
3. Profile names are case-sensitive
4. Only profiles with MARC dataType are shown in the interactive list

### Batch Timeouts

For slow networks or large record batches:

```bash
folio-data-import marc \
  --marc-file-path records.mrc \
  --batch-size 5 \
  --batch-delay 2.0
```

### Invalid MARC Records

Records that fail to parse are written to `bad_marc_records_TIMESTAMP.mrc`. Common issues:

- Incorrect directory entries
- Encoding issues
- Truncated records

These records will require external remediation before they can be loaded.

## Environment Variables

All FOLIO connection parameters can be set via environment variables:

```bash
export FOLIO_GATEWAY_URL="https://folio-snapshot-okapi.dev.folio.org"
export FOLIO_TENANT_ID="diku"
export FOLIO_USERNAME="diku_admin"
export FOLIO_PASSWORD="admin"
```

Then run without repeating connection parameters:

```bash
folio-data-import marc --marc-file-path records.mrc
```

## See Also

- [Quick Start](quick_start.md)
- [Core Concepts](concepts.md)
- [MARC Preprocessors](marc_preprocessors.md)
- [DI Log Retriever](di_log_retriever_guide.md) - Retrieve error logs and failed MARC records from Data Import jobs
- [Examples](examples.md)
- [Troubleshooting](troubleshooting.md)
- [FOLIO Data Import Documentation](https://docs.folio.org/docs/metadata/dataimport/)
