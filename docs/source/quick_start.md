# Quick Start

Get started with folio-data-import in minutes.

## Installation

### Using uv (Recommended)

```bash
# Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create a virtual environment
uv venv

# Activate the environment
source .venv/bin/activate  # On macOS/Linux
# Or on Windows: .venv\Scripts\activate

# Install folio-data-import
uv pip install folio-data-import
```

### Using pip

```bash
# Create a virtual environment
python -m venv .venv
source .venv/bin/activate

# Install
pip install folio-data-import
```

## First Import

### Import MARC Records

```bash
# Set FOLIO credentials
export FOLIO_GATEWAY_URL="https://folio-snapshot-okapi.dev.folio.org"
export FOLIO_TENANT_ID="diku"
export FOLIO_USERNAME="diku_admin"
export FOLIO_PASSWORD="admin"

# Import MARC records
folio-data-import marc --marc-file-path records.mrc
```

You'll be prompted to select a Data Import Job Profile. The tool will then upload your MARC records to FOLIO.

### Import Users

```bash
# Prepare user data in JSON Lines format (users.jsonl)
# Each line is a JSON object:
# {"username": "jdoe", "externalSystemId": "12345", "active": true, ...}

# Import users
folio-data-import users --user-file-path users.jsonl
```

### Post Inventory Records

```bash
# Prepare inventory data in JSON format
# instances.json, holdings.json, or items.json

# Post instances
folio-data-import batch-poster \
  --object-type Instances \
  --file-path instances.json
```

## Next Steps

### Learn Core Concepts

Understand how each tool works:
- [Core Concepts](concepts.md)

### Explore Detailed Guides

- [MARC Data Import Guide](marc_data_import_guide.md) - Data Import profiles, preprocessors
- [User Import Guide](user_import_guide.md) - mod-user-import format, field protection
- [Batch Poster Guide](batch_poster_guide.md) - Inventory upserts, field preservation

### See Examples

Check out [Examples](examples.md) for common use cases:
- MARC import with preprocessors
- User import with service point codes
- Batch posting with field preservation

## Common Options

All tools support these common options:

```bash
# Connection parameters
--gateway-url https://folio-snapshot-okapi.dev.folio.org
--tenant-id diku
--username diku_admin
--password admin

# Batch processing
--batch-size 10          # Records per batch
--batch-delay 0.5        # Seconds between batches

# Progress tracking
--no-progress            # Disable progress bars (for CI/CD)
```

## Getting Help

### Command Help

```bash
# General help
folio-data-import --help

# Tool-specific help
folio-data-import marc --help
folio-data-import users --help
folio-data-import batch-poster --help
```

### Troubleshooting

See the [Troubleshooting Guide](troubleshooting.md) for common issues and solutions.

## Environment Variables

Set these once to avoid repeating on every command:

```bash
export FOLIO_GATEWAY_URL="https://folio-snapshot-okapi.dev.folio.org"
export FOLIO_TENANT_ID="diku"
export FOLIO_USERNAME="diku_admin"
export FOLIO_PASSWORD="admin"
```

Then run commands without connection parameters:

```bash
folio-data-import marc --marc-file-path records.mrc
folio-data-import users --user-file-path users.jsonl
```
