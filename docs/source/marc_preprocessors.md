# MARC Preprocessors

MARC preprocessors modify MARC records **before** they are sent to FOLIO's Data Import system. This is useful for cleaning data, fixing structural issues, or adapting records from specific sources.

## Using Preprocessors

### Basic Usage

Specify preprocessors by name (comma-separated):

```bash
folio-data-import marc \
  --marc-file-path records.mrc \
  --preprocessor "strip_999_ff_fields,fix_bib_leader"
```

### With Configuration

Some preprocessors accept configuration parameters. Provide a JSON configuration file using `--preprocessor-config`:

```bash
folio-data-import marc \
  --marc-file-path records.mrc \
  --preprocessor "prepend_prefix_001" \
  --preprocessor-config preprocessor_config.json
```

Example `preprocessor_config.json`:

```json
{
  "prepend_prefix_001": {
    "prefix": "LOCAL"
  }
}
```

### Multiple Preprocessors

Preprocessors are applied in the order specified:

```bash
folio-data-import marc \
  --marc-file-path records.mrc \
  --preprocessor "strip_999_ff_fields,clean_empty_fields,fix_bib_leader"
```

## Available Preprocessors

The following preprocessors are built into folio-data-import:

| Preprocessor | Description | Config Required |
|-------------|-------------|-----------------|
| `strip_999_ff_fields` | Remove 999 fields with ff indicators (FOLIO system fields) | No |
| `clean_999_fields` | Remove 999 ff fields, move other 999 fields to 945 | No |
| `clean_non_ff_999_fields` | Move non-ff 999 fields to 945 with 99 indicators | No |
| `clean_empty_fields` | Remove empty fields and subfields | No |
| `prepend_prefix_001` | Add prefix to 001 control number | Yes (`prefix`) |
| `prepend_ppn_prefix_001` | Add "(PPN)" prefix to 001 | No |
| `prepend_abes_prefix_001` | Add "(ABES)" prefix to 001 | No |
| `fix_bib_leader` | Fix invalid record type and status in leader | No |
| `move_authority_subfield_9_to_0_all_controllable_fields` | Move $9 to $0 in authority-controlled fields | No |
| `sudoc_supercede_prep` | Process ABES SUDOC records for superseding | No |

## Preprocessor Details

### Field Cleanup

#### `strip_999_ff_fields`

Removes all 999 fields with indicators `f` `f` (FOLIO-generated system fields). Use when importing records exported from another FOLIO system.

```bash
--preprocessor "strip_999_ff_fields"
```

#### `clean_999_fields`

First removes 999 fields with ff indicators, then moves any remaining 999 fields to 945 fields (preserving indicators and subfields). Use when importing records that have both FOLIO-generated 999 fields and local 999 fields.

```bash
--preprocessor "clean_999_fields"
```

#### `clean_non_ff_999_fields`

Moves 999 fields with non-ff indicators to 945 fields with `9` `9` indicators. Use when loading migrated MARC records from folio_migration_tools where other 999 fields could cause loading issues.

Data issues are logged at custom level 26 for compatibility with folio_migration_tools reporting.

```bash
--preprocessor "clean_non_ff_999_fields"
```

#### `clean_empty_fields`

Removes empty fields and subfields that can cause data import mapping issues in FOLIO. This preprocessor checks a comprehensive list of mapped fields (010, 020, 035, 040, 050, 082, 1XX, 2XX, 3XX, 4XX, 5XX, 6XX, 7XX, 8XX, 856) and:

- Removes fields with no subfields
- Removes fields where the only subfield is empty (contains only punctuation or whitespace)
- Removes empty subfields when other subfields have values
- Removes fields that have no non-empty subfields after cleaning

All removals are logged at custom level 26 for data issue reporting.

```bash
--preprocessor "clean_empty_fields"
```

### Control Number Processing

#### `prepend_prefix_001`

Prepends a custom prefix to the 001 field (control number). The prefix is wrapped in parentheses.

**Configuration required:**
- `prefix` (string): The prefix to prepend

**Example configuration file:**

```json
{
  "prepend_prefix_001": {
    "prefix": "LOCAL"
  }
}
```

**Result:** `12345` becomes `(LOCAL)12345`

```bash
--preprocessor "prepend_prefix_001" \
--preprocessor-config config.json
```

#### `prepend_ppn_prefix_001`

Prepends "(PPN)" to the 001 field. Useful for ABES SUDOC catalog records.

**Result:** `12345` becomes `(PPN)12345`

```bash
--preprocessor "prepend_ppn_prefix_001"
```

#### `prepend_abes_prefix_001`

Prepends "(ABES)" to the 001 field. Useful for ABES SUDOC catalog records.

**Result:** `12345` becomes `(ABES)12345`

```bash
--preprocessor "prepend_abes_prefix_001"
```

### Leader Fixes

#### `fix_bib_leader`

Fixes invalid bibliographic record leaders by:

1. **Record status (position 5):** If not a valid status (`a`, `c`, `d`, `n`, `p`), sets to `c` (modified record)
2. **Record type (position 6):** If not a valid type (`a`, `c`, `d`, `e`, `f`, `g`, `i`, `j`, `k`, `m`, `o`, `p`, `r`, `t`), sets to `a` (language material)

Invalid values are logged at custom level 26.

```bash
--preprocessor "fix_bib_leader"
```

### Authority Field Processing

#### `move_authority_subfield_9_to_0_all_controllable_fields`

Moves subfield 9 to subfield 0 in authority-controlled fields. This is useful when importing records from the ABES SUDOC catalog where authority links are stored in $9 instead of $0.

**Affected fields:**
- 100, 110, 111, 130 (main entries)
- 600, 610, 611, 630, 650, 651, 655 (subject headings)
- 700, 710, 711, 730 (added entries)
- 800, 810, 811, 830 (series)
- 880 (alternate graphic representation)

Each move is logged at custom level 26.

```bash
--preprocessor "move_authority_subfield_9_to_0_all_controllable_fields"
```

### SUDOC-Specific Processing

#### `sudoc_supercede_prep`

Comprehensive preprocessor for ABES SUDOC catalog records that:

1. Prepends "(ABES)" to the 001 field (calls `prepend_abes_prefix_001`)
2. Copies 035 fields with `$9 = "sudoc"` to 935 fields with indicators `f` `f` and `$a` prefixed with "(ABES)"

Use when importing newly-merged records from the SUDOC catalog to replace existing records in FOLIO.

```bash
--preprocessor "sudoc_supercede_prep"
```

## Common Workflows

### Importing Records from Another FOLIO System

Remove FOLIO-generated fields and clean up empty fields:

```bash
folio-data-import marc \
  --marc-file-path export.mrc \
  --preprocessor "strip_999_ff_fields,clean_empty_fields"
```

### Importing ABES SUDOC Records

Process SUDOC-specific structure and authority links:

```bash
folio-data-import marc \
  --marc-file-path sudoc.mrc \
  --preprocessor "sudoc_supercede_prep,move_authority_subfield_9_to_0_all_controllable_fields"
```

### Importing Records with Mixed 999 Fields

Separate FOLIO system fields from local data:

```bash
folio-data-import marc \
  --marc-file-path records.mrc \
  --preprocessor "clean_999_fields,clean_empty_fields"
```

### Loading folio_migration_tools Records

Clean up 999 fields that could interfere with migration:

```bash
folio-data-import marc \
  --marc-file-path migrated.mrc \
  --preprocessor "clean_non_ff_999_fields"
```

### Adding Local Prefix to Control Numbers

Ensure unique control numbers when importing from vendors:

```bash
folio-data-import marc \
  --marc-file-path vendor_records.mrc \
  --preprocessor "prepend_prefix_001,clean_empty_fields" \
  --preprocessor-config prefix_config.json
```

With `prefix_config.json`:

```json
{
  "prepend_prefix_001": {
    "prefix": "VENDOR"
  }
}
```

### Fixing Invalid Leaders Before Import

Clean up records with invalid leader bytes:

```bash
folio-data-import marc \
  --marc-file-path legacy_records.mrc \
  --preprocessor "fix_bib_leader,clean_empty_fields"
```

## Custom Preprocessors

You can write custom preprocessors as Python functions and reference them by full module path.

### Preprocessor Function Signature

```python
from pymarc.record import Record

def my_custom_preprocessor(record: Record, **kwargs) -> Record:
    """
    Modify the MARC record.
    
    Args:
        record: The MARC record to preprocess
        **kwargs: Optional configuration parameters from config file
        
    Returns:
        The modified MARC record
    """
    # Your preprocessing logic here
    return record
```

### Example: Custom Preprocessor

```python
# mypreprocessors.py
from pymarc.record import Record
import pymarc

def add_local_note(record: Record, note_text: str = "Imported from legacy system", **kwargs) -> Record:
    """Add a 590 local note field."""
    field = pymarc.Field(
        tag="590",
        indicators=[" ", " "],
        subfields=[pymarc.Subfield("a", note_text)]
    )
    record.add_ordered_field(field)
    return record
```

Usage:

```bash
folio-data-import marc \
  --marc-file-path records.mrc \
  --preprocessor "mypreprocessors.add_local_note" \
  --preprocessor-config custom_config.json
```

With `custom_config.json`:

```json
{
  "mypreprocessors.add_local_note": {
    "note_text": "Migrated January 2026"
  }
}
```

## Configuration Format

The `--preprocessor-config` parameter takes a **path to a JSON file** containing configuration for preprocessors.

### Configuration File Structure

```json
{
  "preprocessor_name": {
    "parameter1": "value1",
    "parameter2": "value2"
  },
  "another.preprocessor": {
    "param": "value"
  },
  "default": {
    "param": "applies to all preprocessors"
  }
}
```

### Configuration Key Resolution

Configuration keys can be specified as:

- **Bare function name:** `prepend_prefix_001`
- **Full module path:** `folio_data_import.marc_preprocessors._preprocessors.prepend_prefix_001`
- **Custom module path:** `mypreprocessors.add_local_note`
- **`default`:** Applied to all preprocessors (overridden by specific keys)

Resolution order:
1. `default` configuration (if present)
2. Configuration by function name
3. Configuration by full module path

### Example Configuration File

```json
{
  "default": {
    "log_level": "DEBUG"
  },
  "prepend_prefix_001": {
    "prefix": "LOCAL"
  },
  "mypreprocessors.add_local_note": {
    "note_text": "Imported via folio-data-import"
  }
}
```

## Data Issue Logging

Many preprocessors log data issues at custom level 26 (between WARNING and ERROR). The CLI automatically generates data issues log files from these level 26 messages, compatible with folio_migration_tools data issues reports.

Issues logged include:
- Empty fields and subfields removed
- Invalid leader values fixed
- Authority subfields moved
- 999 fields with non-ff indicators moved

Data issues are written to log files automatically during import - no additional configuration is required.

## See Also

- [MARC Data Import Guide](marc_data_import_guide.md)
- [Examples](examples.md)
- [pymarc Documentation](https://pymarc.readthedocs.io/)
