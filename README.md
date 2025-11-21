# folio_data_import

## Description

This project is designed to import data into the FOLIO LSP. It provides a simple and efficient way to import data from various sources using FOLIO's REST APIs.

## Features

- Import MARC records using FOLIO's Data Import system
- Import User records using FOLIO's User APIs
- Batch post Instances, Holdings, and Items to FOLIO inventory storage

## Installation

## Installation

Using `pip`
```shell
pip install folio_data_import
```
or `uv pip`
```shell
uv pip install folio_data_import
```

To install the project from the git repo using Poetry, follow these steps:

1. Clone the repository.
2. Navigate to the project directory: `$ cd /path/to/folio_data_import`.
3. [Install `uv`](https://docs.astral.sh/uv/getting-started/installation/) if you haven't already.
4. Install the project and its dependencies: `$ uv sync`.
5. Run the application using Poetry: `$ uv run folio-data-import --help`.

Make sure to activate the virtual environment created by `uv` before running the application.

## Usage

This package provides CLI commands for importing data into FOLIO:

```shell
# Main command with subcommands
folio-data-import <subcommand> [options]

# Or use standalone commands
folio-user-import [options]
folio-marc-import [options]
folio-batch-poster [options]
```

**Tab Completion:** Install shell completions for better CLI experience:
```shell
folio-data-import --install-completion
```

### Environment Variables

All commands support environment variables for FOLIO connection credentials, allowing you to avoid repeating these parameters:

```shell
export FOLIO_GATEWAY_URL="https://folio-snapshot-okapi.dev.folio.org"
export FOLIO_TENANT_ID="diku"
export FOLIO_USERNAME="diku_admin"
export FOLIO_PASSWORD="admin"
```

Once set, you can omit these parameters from your commands:

```shell
# Instead of:
folio-data-import users --gateway-url "..." --tenant-id "..." --username "..." --password "..." --user-file users.jsonl

# You can simply use:
folio-data-import users --user-file users.jsonl
```

This works for all subcommands: `users`, `marc`, and `batch-poster`.

## CLI Commands

### folio-data-import users

**Alias:** `folio-user-import`

Import users to FOLIO with extended functionality beyond `mod-user-import`.

#### Quick Start

```shell
folio-data-import users \
  --gateway-url "https://folio-snapshot-okapi.dev.folio.org" \
  --tenant-id diku \
  --username diku_admin \
  --password admin \
  --user-file users.jsonl
```

#### Features

**Service Point Management:** Specify service points using codes instead of UUIDs:
```
{
    "username": "checkin-all",
    "barcode": "1728439497039848103",
    "active": true,
    "type": "patron",
    "patronGroup": "staff",
    "departments": [],
    "personal": {
        "lastName": "Admin",
        "firstName": "checkin-all",
        "addresses": [
          {
            "countryId": "HU",
            "addressLine1": "Andrássy Street 1.",
            "addressLine2": "",
            "city": "Budapest",
            "region": "Pest",
            "postalCode": "1061",
            "addressTypeId": "Home",
            "primaryAddress": true
          }
        ],
        "preferredContactTypeId": "email"
    },
    "requestPreference": {
        "holdShelf": true,
        "delivery": false,
        "fulfillment": "Hold Shelf"
    }
    "servicePointsUser": {
        "defaultServicePointId": "cd1",
        "servicePointsIds": [
            "cd1",
            "Online",
            "000",
            "cd2"
        ]
    }
}
```

**Flexible Matching:** Match users by `id`, `externalSystemId`, `username`, or `barcode`:
```shell
folio-data-import users --user-file users.jsonl --user-match-key username
```

**Preferred Contact Type:** Accepts FOLIO IDs or human-friendly strings (`mail`, `email`, `text`, `phone`, `mobile`). Set a default for users without a valid value:
```shell
folio-data-import users --user-file users.jsonl --default-preferred-contact-type email
```

**Field Protection:** Protect specific fields from being updated:

- **Job-level protection** (applies to all records):
  ```shell
  folio-data-import users --user-file users.jsonl \
    --fields-to-protect "personal.preferredFirstName,barcode"
  ```

- **Per-record protection** (using custom field `protectedFields`):
  ```json
  {
    "username": "jdoe",
    "customFields": {
      "protectedFields": "barcode,personal.telephone,personal.addresses"
    }
  }
  ```

#### Input Format

JSON Lines format - one user object in the style<sup>*</sup> of [mod-user-import](https://github.com/folio-org/mod-user-import) (with extended support mentioned above) per line

<sup>*</sup>also supports dereferenced (UUIDs instead of reference strings) user objects (eg. directly extracted from `/users`)

### folio-data-import marc

**Alias:** `folio-marc-import`

Import binary MARC21 records via FOLIO's Data Import system using the [change-manager](https://github.com/folio-org/mod-source-record-manager?tab=readme-ov-file#data-import-workflow) APIs.

#### Quick Start

```shell
folio-data-import marc \
  --gateway-url "https://folio-snapshot-okapi.dev.folio.org" \
  --tenant-id diku \
  --username diku_admin \
  --password admin \
  --marc-source-path records.mrc
```

The command will prompt you to select a [Data Import Job Profile](https://docs.folio.org/docs/metadata/additional-topics/jobprofiles/) configured in your FOLIO tenant.

#### Features

- Process single files or entire directories of MARC files
- Interactive job profile selection
- Real-time progress tracking
- Automatic retry on transient errors

**Note:** FOLIO's import logs can be unreliable. If you don't see a job summary when your job completes, check Data Import in FOLIO (Data Import > Actions > View all logs...).

### folio-data-import batch-poster

**Alias:** `folio-batch-poster`

Efficiently batch post Instances, Holdings, and Items to FOLIO's inventory storage endpoints with support for creating new records and updating existing ones.

#### Quick Start

```shell
folio-data-import batch-poster \
  --gateway-url "https://folio-snapshot-okapi.dev.folio.org" \
  --tenant-id diku \
  --username diku_admin \
  --password admin \
  --object-type Items \
  --file-paths items.jsonl \
  --batch-size 100 \
  --upsert
```

#### Key Features

- **Multiple File Support**: Process multiple files with glob patterns
  ```shell
  folio-data-import batch-poster --object-type Items --file-paths "items_*.jsonl"
  ```

- **Upsert Mode**: Create new records or update existing ones
  ```shell
  folio-data-import batch-poster --object-type Items --file-paths items.jsonl --upsert
  ```

- **Field Preservation**: Control which fields are preserved during updates
  ```shell
  folio-data-import batch-poster --object-type Items --file-paths items.jsonl --upsert \
    --preserve-statistical-codes \
    --preserve-administrative-notes \
    --preserve-temporary-locations \
    --overwrite-item-status
  ```

- **Selective Patching**: Update only specific fields
  ```shell
  folio-data-import batch-poster --object-type Items --file-paths items.jsonl --upsert \
    --patch-existing-records \
    --patch-paths "barcode,status,itemLevelCallNumber"
  ```

- **Failed Records**: Automatically save failed records to a file
  ```shell
  folio-data-import batch-poster --object-type Items --file-paths items.jsonl \
    --failed-records-file failed_items.jsonl
  ```

- **Progress Tracking**: Real-time progress bar with statistics
  - Disable with `--no-progress` for CI/CD environments

- **Config File Support**: Use a JSON config file for complex configurations
  ```shell
  folio-data-import batch-poster config.json
  ```
  
  Example `config.json`:
  ```json
  {
    "object_type": "Items",
    "file_paths": ["items1.jsonl", "items2.jsonl"],
    "batch_size": 100,
    "upsert": true,
    "preserve_statistical_codes": true,
    "preserve_item_status": true,
    "failed_records_file": "failed_items.jsonl"
  }
  ```

#### Input Format

Input files should be JSONL (JSON Lines) format - one complete JSON object per line:

```jsonl
{"id": "item-001", "barcode": "12345", "status": {"name": "Available"}}
{"id": "item-002", "barcode": "12346", "status": {"name": "Available"}}
{"id": "item-003", "barcode": "12347", "status": {"name": "Checked out"}}
```

#### Common Use Cases

**Create new items:**
```shell
folio-data-import batch-poster --object-type Items --file-paths new_items.jsonl
```

**Update existing items (by ID):**
```shell
folio-data-import batch-poster --object-type Items --file-paths items.jsonl --upsert
```

**Update only barcodes and call numbers:**
```shell
folio-data-import batch-poster --object-type Items --file-paths items.jsonl --upsert \
  --patch-existing-records \
  --patch-paths "barcode,itemLevelCallNumber"
```

**Process multiple files:**
```shell
folio-data-import batch-poster --object-type Holdings \
  --file-paths holdings_*.jsonl \
  --batch-size 500 \
  --upsert
```

#### Available Options

Run `folio-data-import batch-poster --help` to see all available options:
- `--object-type`: Type of inventory object (Items, Holdings, or Instances) - **Required**
- `--file-paths`: Path(s) to JSONL file(s) - supports glob patterns - **Required**
- `--batch-size`: Number of records per batch (1-1000, default: 100)
- `--upsert`: Enable create-or-update mode
- `--preserve-statistical-codes`: Keep existing statistical codes during updates
- `--preserve-administrative-notes`: Keep existing administrative notes
- `--preserve-temporary-locations`: Keep temporary location (Items only)
- `--preserve-temporary-loan-types`: Keep temporary loan type (Items only)
- `--preserve-item-status`: Keep item status (Items only, default: true)
- `--patch-existing-records`: Enable selective field patching
- `--patch-paths`: Comma-separated list of fields to patch
- `--failed-records-file`: Path to save failed records
- `--no-progress`: Disable progress bar (useful for CI/CD)

## Programmatic Usage

All CLI commands can also be used programmatically in your Python applications.

### BatchPoster

```python
import asyncio
from folioclient import FolioClient
from folio_data_import.BatchPoster import BatchPoster

async def post_items():
    # Create FOLIO client
    folio = FolioClient(
        okapi_url="https://folio-snapshot-okapi.dev.folio.org",
        tenant_id="diku",
        username="diku_admin",
        password="admin"
    )
    
    # Configure batch poster
    config = BatchPoster.Config(
        object_type="Items",
        batch_size=100,
        upsert=True,
        preserve_statistical_codes=True
    )
    
    # Post records
    async with BatchPoster(
        folio, 
        config,
        failed_records_file="failed_items.jsonl"
    ) as poster:
        await poster.post_records("items.jsonl")
        print(f"Posted: {poster.stats.records_posted}, Failed: {poster.stats.records_failed}")

asyncio.run(post_items())
```

### UserImporter

```python
import asyncio
from folioclient import FolioClient
from folio_data_import.UserImport import UserImporter

async def import_users():
    folio = FolioClient(
        okapi_url="https://folio-snapshot-okapi.dev.folio.org",
        tenant_id="diku",
        username="diku_admin",
        password="admin"
    )
    
    config = UserImporter.Config(
        user_file="users.jsonl",
        user_match_key="username",
        default_preferred_contact_type="email"
    )
    
    importer = UserImporter(folio, config)
    result = await importer.do_work()
    print(f"Imported {result.records_created} users")

asyncio.run(import_users())
```

### MARCImportJob

```python
import asyncio
from folioclient import FolioClient
from folio_data_import.MARCDataImport import MARCImportJob

async def import_marc():
    folio = FolioClient(
        okapi_url="https://folio-snapshot-okapi.dev.folio.org",
        tenant_id="diku",
        username="diku_admin",
        password="admin"
    )
    
    config = MARCImportJob.Config(
        marc_source_path="records.mrc",
        job_profile_id="profile-uuid",
        job_profile_name="Bibliographic records"
    )
    
    job = MARCImportJob(folio, config)
    result = await job.start_import()
    print(f"Imported {result.created_records} MARC records")

asyncio.run(import_marc())
```

### Additional Documentation

For complete API documentation and advanced usage:
- [BatchPoster.md](docs/BatchPoster.md) - Comprehensive BatchPoster guide
- [BatchPoster_Quick_Reference.md](docs/BatchPoster_Quick_Reference.md) - Quick reference

## Contributing

Contributions are welcome! If you have any ideas, suggestions, or bug reports, please open an issue or submit a pull request.

## License

This project is licensed under the [MIT License](LICENSE).
