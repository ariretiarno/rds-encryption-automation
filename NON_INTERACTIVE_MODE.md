# Non-Interactive Mode (--yes Flag)

## Overview

The `--yes` (or `-y`) flag enables **fully automated, non-interactive mode** for the script. All prompts are automatically confirmed, and LSN is auto-fetched from the source database.

## Problem Solved

### Before (Interactive Mode)

Running `setup-target` required multiple manual inputs:

```bash
python rds_encryption_automation.py --config databases.json --action setup-target
```

**Prompts**:
1. Press Enter to auto-fetch from source ← **Manual**
2. Use this LSN (1971/CC017AB8)? (yes/no): ← **Manual**
3. Proceed with advancing replication origin? (yes/no): ← **Manual**

### After (Non-Interactive Mode)

```bash
python rds_encryption_automation.py --config databases.json --action setup-target --yes
```

**No prompts!** Everything is automated:
- ✅ Auto-fetches LSN from source
- ✅ Auto-confirms LSN usage
- ✅ Auto-confirms origin advancement
- ✅ Proceeds without user interaction

## Usage

### Basic Non-Interactive Mode

```bash
python rds_encryption_automation.py \
  --config databases.json \
  --action setup-target \
  --yes
```

**What happens**:
1. Auto-fetches LSN from source database
2. Auto-confirms the fetched LSN
3. Shows origin usage report (unless `--skip-origin-check`)
4. Auto-confirms origin advancement
5. Advances origin and enables subscription

### With LSN Provided

```bash
python rds_encryption_automation.py \
  --config databases.json \
  --action setup-target \
  --lsn 1971/CC017AB8 \
  --yes
```

**What happens**:
1. Uses the provided LSN (no fetch needed)
2. Shows origin usage report
3. Auto-confirms origin advancement
4. Advances origin and enables subscription

### Fully Automated (No Prompts, No Origin Check)

```bash
python rds_encryption_automation.py \
  --config databases.json \
  --action setup-target \
  --yes \
  --skip-origin-check
```

**What happens**:
1. Auto-fetches LSN from source
2. Auto-confirms LSN
3. Skips origin usage check
4. Auto-confirms origin advancement
5. Advances origin and enables subscription

**This is the fastest, fully automated mode!**

## Example Output

### Interactive Mode (Default)

```
Enter LSN manually, or press Enter to auto-fetch from source: 
INFO - Attempting to auto-fetch LSN from source database...
INFO - ✓ Auto-fetched LSN from source: 1971/CC017AB8
Use this LSN (1971/CC017AB8)? (yes/no): yes

================================================================================
CHECKING REPLICATION ORIGIN USAGE
================================================================================
[... origin report ...]

================================================================================
⚠️  ABOUT TO ADVANCE REPLICATION ORIGIN
================================================================================
LSN to advance to: 1971/CC017AB8
The script will use session-based approach to handle active origins.
================================================================================
Proceed with advancing replication origin? (yes/no): yes
```

### Non-Interactive Mode (--yes)

```
INFO - Auto-confirm mode: fetching LSN from source database...
INFO - ✓ Auto-fetched LSN from source: 1971/CC017AB8
INFO - ✓ Auto-confirmed: Using LSN 1971/CC017AB8

================================================================================
CHECKING REPLICATION ORIGIN USAGE
================================================================================
[... origin report ...]

================================================================================
⚠️  ADVANCING REPLICATION ORIGIN (AUTO-CONFIRMED)
================================================================================
INFO - LSN to advance to: 1971/CC017AB8
INFO - Using session-based approach to handle active origins.
================================================================================

INFO - ✓ Advanced replication origin 'pg_31288228' to LSN 1971/CC017AB8
INFO - ✓ Enabled subscription: myapp_encryption_pub
```

## Use Cases

### 1. CI/CD Pipelines

```bash
#!/bin/bash
# Automated migration script for CI/CD

# Setup source
python rds_encryption_automation.py \
  --config databases.json \
  --action setup-source

# Setup target (fully automated)
python rds_encryption_automation.py \
  --config databases.json \
  --action setup-target \
  --yes \
  --skip-origin-check

# Verify
python rds_encryption_automation.py \
  --config databases.json \
  --action verify
```

### 2. Batch Processing Multiple Databases

```bash
# Process all databases in config without manual intervention
python rds_encryption_automation.py \
  --config all-databases.json \
  --action setup-target \
  --yes
```

### 3. Scheduled Automation

```bash
# Cron job or scheduled task
0 2 * * * /path/to/rds_encryption_automation.py \
  --config /path/to/databases.json \
  --action setup-target \
  --yes \
  --skip-origin-check
```

### 4. Quick Testing

```bash
# Quickly test setup without manual inputs
python rds_encryption_automation.py \
  --config test-db.json \
  --action setup-target \
  --yes
```

## Flags Comparison

| Flag | Purpose | Prompts | Origin Check | LSN |
|------|---------|---------|--------------|-----|
| (none) | Interactive | Yes | Yes | Manual or auto-fetch |
| `--yes` | Auto-confirm | No | Yes | Auto-fetch |
| `--skip-origin-check` | Skip origin check | Yes | No | Manual or auto-fetch |
| `--yes --skip-origin-check` | Fully automated | No | No | Auto-fetch |
| `--lsn X --yes` | Auto with LSN | No | Yes | Provided |
| `--lsn X --yes --skip-origin-check` | Fastest | No | No | Provided |

## Behavior Details

### LSN Handling

**Without `--yes`**:
- Prompts for LSN input
- If Enter pressed, auto-fetches from source
- Prompts to confirm auto-fetched LSN

**With `--yes`**:
- Automatically fetches LSN from source
- Automatically confirms the fetched LSN
- No prompts

**With `--yes --lsn X`**:
- Uses provided LSN
- No fetch, no prompts

### Origin Check

**Without `--skip-origin-check`**:
- Shows origin usage report
- Prompts for confirmation (unless `--yes`)

**With `--skip-origin-check`**:
- Skips origin usage report
- Skips confirmation prompt

**With `--yes` (without `--skip-origin-check`)**:
- Shows origin usage report
- Auto-confirms (no prompt)

### Error Handling

If auto-fetch fails in `--yes` mode:

```
ERROR - Could not auto-fetch LSN from source in auto-confirm mode
```

The script will exit. You must either:
1. Fix the source database connection
2. Provide LSN manually with `--lsn`

## Safety Considerations

### ✅ Safe for Automation

The `--yes` flag is safe because:
- LSN is fetched from the actual source database
- Origin advancement uses session-based approach
- All operations are logged
- Errors cause script to exit

### ⚠️ When to Use Caution

Be careful with `--yes` when:
- Running in production for the first time
- Unsure about database state
- Multiple databases in config

**Recommendation**: Test with interactive mode first, then use `--yes` for subsequent runs.

### 🛡️ Best Practices

1. **Test first**: Run without `--yes` to see what will happen
2. **Check logs**: Review log files after automated runs
3. **Monitor**: Watch replication status after automation
4. **Verify**: Always run `--action verify` after setup

## Combining with Other Flags

### Recommended Combinations

**For CI/CD**:
```bash
--yes --skip-origin-check
```

**For Testing**:
```bash
--yes --database test_db
```

**For Production (First Time)**:
```bash
# No --yes, see what happens first
--action setup-target
```

**For Production (Subsequent)**:
```bash
--yes --database prod_db
```

## Short Form

You can use `-y` instead of `--yes`:

```bash
python rds_encryption_automation.py --config databases.json --action setup-target -y
```

## Troubleshooting

### Script Still Prompts

If you still see prompts with `--yes`:

1. **Check you're using the latest version** of the script
2. **Verify the flag** is spelled correctly: `--yes` or `-y`
3. **Check for other prompts** (e.g., subscription recreation)

### Auto-Fetch Fails

```
ERROR - Could not auto-fetch LSN from source in auto-confirm mode
```

**Solutions**:
1. Check source database connectivity
2. Verify source database credentials
3. Ensure replication slot exists on source
4. Provide LSN manually: `--lsn X --yes`

### Want to See Origin Report But Auto-Confirm

Use `--yes` without `--skip-origin-check`:

```bash
python rds_encryption_automation.py \
  --config databases.json \
  --action setup-target \
  --yes
```

This shows the origin report but auto-confirms advancement.

## Summary

The `--yes` flag provides:

- ✅ **Zero manual input** required
- ✅ **Auto-fetches LSN** from source
- ✅ **Auto-confirms** all prompts
- ✅ **Perfect for automation** (CI/CD, cron, scripts)
- ✅ **Safe and logged** operations
- ✅ **Can combine** with other flags

**Your migration can now run completely unattended!** 🎉

## Examples

### Example 1: Single Database, Fully Automated

```bash
python rds_encryption_automation.py \
  --config my-db.json \
  --action setup-target \
  --yes \
  --skip-origin-check
```

**Output**:
```
INFO - Auto-confirm mode: fetching LSN from source database...
INFO - ✓ Auto-fetched LSN from source: 1971/CC017AB8
INFO - ✓ Auto-confirmed: Using LSN 1971/CC017AB8
INFO - Skipping origin usage check (--skip-origin-check flag set)
INFO - ✓ Advanced replication origin 'pg_31288228' to LSN 1971/CC017AB8
INFO - ✓ Enabled subscription: myapp_encryption_pub
INFO - ✓ Target database setup completed successfully
```

### Example 2: Multiple Databases, Auto-Confirm

```bash
python rds_encryption_automation.py \
  --config all-dbs.json \
  --action setup-target \
  --yes
```

Processes all databases without any manual input!

### Example 3: With Provided LSN

```bash
python rds_encryption_automation.py \
  --config my-db.json \
  --action setup-target \
  --lsn 1971/CC017AB8 \
  --yes \
  --skip-origin-check
```

Fastest mode - no fetch, no check, no prompts!
