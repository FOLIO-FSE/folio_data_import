# Troubleshooting

Common issues and their solutions when using folio-data-import.

## Authentication Issues

### Error: "Invalid credentials"

**Problem:** Username or password is incorrect.

**Solution:**

Test credentials manually:

```bash
curl -X POST https://folio-snapshot-okapi.dev.folio.org/authn/login \
  -H "Content-Type: application/json" \
  -H "X-Okapi-Tenant: diku" \
  -d '{"username":"diku_admin","password":"admin"}'
```

Verify:
- Username and password are correct
- User has sufficient permissions
- User account is active in FOLIO

### Error: "Invalid tenant ID"

**Problem:** Tenant ID doesn't match FOLIO system.

**Solution:**

Check your tenant ID with your FOLIO administrator. Common patterns:
- `diku` (FOLIO snapshot/demo)
- `fs09000000` (bugfest environments)
- Custom identifier for your institution

### Error: "Connection refused" or timeout

**Problem:** Cannot connect to FOLIO API.

**Solution:**

Test connectivity:

```bash
# Test basic connectivity
curl https://folio-snapshot-okapi.dev.folio.org/_/version

# Check if you need VPN access
# Check if the URL is correct (no trailing slash)
```

Verify:
- FOLIO server is running
- You have network/VPN access if required
- Gateway URL is correct
- Port is accessible (usually 443 for HTTPS)

## MARC Import Issues

### Error: "Not a valid MARC file"

**Problem:** File is not a valid MARC21 binary file.

**Solution:**

Check the file type:

```bash
file your_file.mrc
# Should show: "data" for binary MARC
# If it shows "ASCII text", it might be MARC XML
```

Convert MARC XML to binary if needed:

```bash
yaz-marcdump -i marcxml -o marc input.xml > output.mrc
```

### Error: "Profile not found"

**Problem:** Data Import Job Profile name doesn't exist.

**Solution:**

1. Run without `--import-profile-name` to see available profiles interactively
2. Check exact spelling in **Settings > Data Import > Job Profiles**
3. Profile names are case-sensitive

```bash
# Let the tool show available profiles
folio-data-import marc --marc-file-path records.mrc
```

### Job Summary Not Available

**Problem:** Import completes but summary cannot be retrieved.

**Solution:**

1. Check **Data Import > View all logs** in FOLIO UI
2. Look up your job ID from `marc_import_job_ids.txt` or `folio_data_import_TIMESTAMP.log`
3. Use flags to handle unreliable summaries:

```bash
# Continue without failing on missing summary
folio-data-import marc \
  --marc-file-path records.mrc \
  --let-summary-fail

# Skip summary retrieval entirely
folio-data-import marc \
  --marc-file-path records.mrc \
  --no-summary
```

### Invalid MARC Records

**Problem:** Some records fail to parse.

**Solution:**

Records that fail to parse are written to `bad_marc_records_TIMESTAMP.mrc`. Common issues:

- Incorrect directory entries
- Encoding issues

```bash
# Fix common leader issues
folio-data-import marc \
  --marc-file-path records.mrc \
  --preprocessor "fix_bib_leader,clean_empty_fields"
```

### Batch Timeouts

**Problem:** Batches timeout on slow networks or large records.

**Solution:**

Reduce batch size and add delay:

```bash
folio-data-import marc \
  --marc-file-path records.mrc \
  --batch-size 5 \
  --batch-delay 2.0
```

## User Import Issues

### Error: "library_name is required"

**Problem:** Missing required `--library-name` parameter.

**Solution:**

Always provide `--library-name`:

```bash
folio-data-import users \
  --library-name "Main Library" \
  --user-file-path users.jsonl
```

Or set via environment variable:

```bash
export FOLIO_LIBRARY_NAME="Main Library"
```

### Error: "Patron group not found"

**Problem:** Patron group name in user data doesn't exist in FOLIO.

**Solution:**

1. Check **Settings > Users > Patron Groups** for exact names
2. Use exact case-sensitive names or UUIDs in your data
3. Create missing patron groups before import

### Error: "Service point not found"

**Problem:** Service point code doesn't exist in FOLIO.

**Solution:**

1. Check **Settings > Tenant > Service Points** for codes
2. Use exact codes in `servicePointsUser.servicePointsIds`
3. Service points must exist before import

### Duplicate User Errors

**Problem:** User already exists with same username/barcode/externalSystemId.

**Solution:**

The importer updates existing users when a match is found. Check:

1. Your `--user-match-key` setting matches your data structure
2. If using `id` field, it always takes precedence
3. Review failed records in `failed_user_import_TIMESTAMP.txt`

### Field Protection Not Working

**Problem:** Protected fields are still being updated.

**Solution:**

1. Use dot notation for nested fields: `personal.email` not just `email`
2. Check both CLI `--fields-to-protect` and per-record `customFields.protectedFields`
3. Fields must match exactly (case-sensitive)

```bash
# Correct nested field notation
folio-data-import users \
  --library-name "Main Library" \
  --user-file-path users.jsonl \
  --fields-to-protect "username,barcode,personal.email,personal.phone"
```

## Batch Poster Issues

### Error: "Invalid object type"

**Problem:** Unrecognized `--object-type` value.

**Solution:**

Use one of the supported types (case-sensitive):
- `Instances`
- `Holdings`
- `Items`

```bash
folio-data-import batch-poster \
  --object-type Items \
  --file-path items.jsonl
```

### Error: "Missing required field"

**Problem:** Record missing a required field.

**Solution:**

Required fields vary by object type:

**Instances:**
- `id`, `title`, `instanceTypeId`, `source`

**Holdings:**
- `id`, `instanceId`, `permanentLocationId`, `sourceId`

**Items:**
- `id`, `holdingsRecordId`, `materialTypeId`, `permanentLoanTypeId`, `status`

### Upsert Not Updating Records

**Problem:** Existing records not being updated.

**Solution:**

1. Ensure `--upsert` flag is provided
2. Records are matched by `id` - IDs must match exactly
3. Check that the ID exists in FOLIO

```bash
# Verify record exists
curl -H "X-Okapi-Token: $TOKEN" \
  "https://your-folio.example.com/item-storage/items/YOUR-ITEM-ID"
```

### Item Status Being Overwritten

**Problem:** Item status changes during upsert when you want to preserve it.

**Solution:**

Item status is preserved by default. If status is being overwritten:

1. Check you're not using `--overwrite-item-status`
2. Verify your input data has the correct status

### Preservation Options Not Working

**Problem:** Statistical codes, notes, etc. not being preserved.

**Solution:**

Preservation options only work with `--upsert`:

```bash
folio-data-import batch-poster \
  --object-type Items \
  --file-path items.jsonl \
  --upsert \
  --preserve-statistical-codes \
  --preserve-administrative-notes
```

## File Format Issues

### Error: "Invalid JSON"

**Problem:** JSON Lines file has syntax errors.

**Solution:**

Validate each line is valid JSON:

```bash
# Check for JSON errors
while read line; do echo "$line" | jq . > /dev/null || echo "Invalid: $line"; done < users.jsonl

# Or validate entire file
jq -c '.' users.jsonl > /dev/null
```

### Error: "Unexpected character"

**Problem:** File encoding issues or BOM (byte order mark).

**Solution:**

Remove BOM and ensure UTF-8 encoding:

```bash
# Remove BOM
sed -i '1s/^\xEF\xBB\xBF//' file.jsonl

# Convert encoding
iconv -f ISO-8859-1 -t UTF-8 old.jsonl > new.jsonl
```

### Empty or Missing File

**Problem:** File path not found or file is empty.

**Solution:**

1. Use absolute paths or correct relative paths
2. Verify file exists and has content
3. Check glob patterns expand correctly

```bash
# Test glob pattern
ls exports/*.mrc

# Use quotes around glob patterns
folio-data-import marc --marc-file-path "exports/*.mrc"
```

## Performance Issues

### Slow Imports

**Problem:** Import is running very slowly.

**Solutions:**

1. **Increase batch size** (within API limits):

```bash
# BatchPoster default is 100, can go up to 1000
folio-data-import batch-poster \
  --object-type Instances \
  --file-path instances.jsonl \
  --batch-size 500

# User import default is 250
folio-data-import users \
  --library-name "Main Library" \
  --user-file-path users.jsonl \
  --batch-size 500
```

2. **Increase concurrent requests** (user import):

```bash
folio-data-import users \
  --library-name "Main Library" \
  --user-file-path users.jsonl \
  --limit-async-requests 20
```

3. **Check FOLIO server performance** - slow responses indicate server-side issues


## Debugging

### View Detailed Logs

All commands output logs to the console. For more detail:

```bash
# Disable progress bars to see all log output clearly
folio-data-import marc \
  --marc-file-path records.mrc \
  --no-progress
```

### Check Output Files

Review generated output files:

```bash
# MARC import job IDs
cat marc_import_job_ids.txt

# Failed MARC records
ls bad_marc_records_*.mrc
ls failed_batches_*.mrc

# Failed user imports
cat failed_user_import_*.txt
```

### Test with Small Sample

Test configuration with a small subset first:

```bash
# Extract first 10 records
head -10 large_file.jsonl > sample.jsonl

# Test with sample
folio-data-import batch-poster \
  --object-type Items \
  --file-path sample.jsonl
```

### Validate Data Before Import

Pre-validate your data:

```bash
# Check JSON Lines format
wc -l users.jsonl  # Count records
head -1 users.jsonl | jq .  # View first record structure

# Check for required fields
jq -r 'select(.patronGroup == null) | .username' users.jsonl
```

## Getting Help

If you can't find a solution:

1. Check the full error message and logs
2. Review [Examples](examples.md) for similar workflows
3. Check the specific guide for your import type:
   - [MARC Data Import Guide](marc_data_import_guide.md)
   - [User Import Guide](user_import_guide.md)
   - [Batch Poster Guide](batch_poster_guide.md)

Report issues on [GitHub](https://github.com/FOLIO-FSE/folio_data_import/issues) with:
- Command used (sanitize credentials)
- Full error message
- Sample data (if possible)

## See Also

- [User Import Guide](user_import_guide.md)
- [MARC Data Import Guide](marc_data_import_guide.md)
- [Batch Poster Guide](batch_poster_guide.md)
- [Examples](examples.md)
