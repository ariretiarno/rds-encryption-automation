# Changelog - October 21, 2025

## Bug Fixes & Enhancements

### ✨ Enhancement: Non-Interactive Mode (--yes Flag)

**Feature**: Added `--yes` / `-y` flag for fully automated, non-interactive execution.

**What It Does**:
- Auto-fetches LSN from source database
- Auto-confirms all prompts
- No manual input required

**Usage**:
```bash
# Fully automated setup
python rds_encryption_automation.py --config databases.json --action setup-target --yes

# Fastest mode (no prompts, no origin check)
python rds_encryption_automation.py --config databases.json --action setup-target --yes --skip-origin-check
```

**Benefits**:
- Perfect for CI/CD pipelines
- Batch processing multiple databases
- Scheduled automation (cron jobs)
- Quick testing without manual inputs

**Example Output**:
```
INFO - Auto-confirm mode: fetching LSN from source database...
INFO - ✓ Auto-fetched LSN from source: 1971/CC017AB8
INFO - ✓ Auto-confirmed: Using LSN 1971/CC017AB8
INFO - ✓ Advanced replication origin 'pg_31288228' to LSN 1971/CC017AB8
```

**Files Changed**:
- `rds_encryption_automation.py` (lines 765-835, 1238-1243, 1298)

---

### ✨ Enhancement: Automatic Replication Origin Selection

**Feature**: Script now automatically selects the best replication origin to advance.

**How It Works**:
Intelligently selects based on priority:
1. Origin matching subscription name
2. Inactive origin (disabled subscription)
3. Single origin (only one exists)
4. Orphaned origin (no subscription)
5. Manual selection (only if multiple active origins)

**Benefits**:
- No manual selection needed in most cases
- Safer operations (won't pick wrong origin)
- Clear logging of selection reasoning
- Falls back to manual only when necessary

**Example**:
```
INFO - ✓ Auto-selected origin matching subscription: pg_31288228 (Status: INACTIVE)
INFO - ✓ Advanced replication origin 'pg_31288228' to LSN 0/20000110
```

**Files Changed**:
- `rds_encryption_automation.py` (lines 493-571)

---

### 🐛 Fixed: Support for Special Characters in Names

**Issue 1**: Database names containing `-` or `.` caused SQL syntax errors:
```
ERROR - Error creating publication: syntax error at or near "-"
LINE 1: CREATE PUBLICATION recon-engine_pub FOR ALL TABLES
```

**Issue 2**: Slot names with special characters caused errors:
```
ERROR - Error creating replication slot: replication slot name "airbyte-new_slot" contains invalid character
```

**Root Cause**: 
- PostgreSQL identifiers can't contain special characters without quoting
- Replication slot names have stricter rules (only lowercase, numbers, underscore)

**Solution**: 
1. Sanitize database names by replacing `-` and `.` with `_`
2. Quote all identifiers in SQL statements
3. **Sanitize slot names** with stricter rules:
   - Convert to lowercase
   - Replace invalid characters with `_`
   - Ensure doesn't start with number
   - Truncate to 63 characters

**Examples**:
- Database: `recon-engine` → Publication: `recon_engine_encryption_pub`
- Slot: `airbyte-new_slot` → `airbyte_new_slot`
- Slot: `MySlot-V2` → `myslot_v2`

**Files Changed**:
- `rds_encryption_automation.py` (lines 46-58, 60-97, and all SQL statements)

---

### 🔧 Fixed: Proper Subscription Drop Procedure

**Issue**: Dropping subscriptions with simple `DROP SUBSCRIPTION` could cause errors and orphaned resources.

**Solution**: Implemented proper 3-step procedure:
1. `ALTER SUBSCRIPTION ... DISABLE` - Stop the worker
2. `ALTER SUBSCRIPTION ... SET (slot_name = NONE)` - Detach slot
3. `DROP SUBSCRIPTION ...` - Remove subscription

**Benefits**:
- Prevents "subscription is being used" errors
- Avoids orphaned replication slots
- Clean resource cleanup
- No stuck worker processes

**Files Changed**: 
- `rds_encryption_automation.py` (lines 297-308, 739-764)

---

### 🐛 Fixed: Column Name Error in pg_replication_origin

**Issue**: Script failed with `column "roremote_lsn" does not exist` error.

**Root Cause**: The `pg_replication_origin` catalog doesn't have LSN columns. Those exist in `pg_replication_origin_status`.

**Solution**: Removed non-existent columns from queries. Origin diagnostics still work perfectly.

**Files Changed**:
- `rds_encryption_automation.py` (lines 786-792, 848-861)
- `check_replication_origin_usage.sql`

---

### 🐛 Fixed: Replication Origin "Already Active" Error

**Issue**: Script failed with error `replication origin with OID 1 is already active for PID 17013` when running `setup-target` action.

**Root Cause**: Used `pg_replication_origin_advance()` which doesn't work when origin is active.

**Solution**: Implemented session-based approach using:
- `pg_replication_origin_session_setup()`
- `pg_replication_origin_xact_setup()`
- `pg_replication_origin_session_reset()`

**Files Changed**: `rds_encryption_automation.py` (lines 443-535)

---

### ✨ Enhancement: Skip Remaining Steps When Subscription Exists

**Issue**: When user chose not to recreate an existing subscription, the script would still attempt to advance LSN and enable subscription, causing potential errors.

**Solution**: Modified subscription creation flow to return status indicators:
- `'created'` - New subscription created, continue with setup
- `'skipped'` - Subscription exists and user chose to skip, exit cleanly
- `'failed'` - Error occurred, stop execution

When subscription is skipped, all subsequent steps (LSN advancement, enabling) are now skipped automatically.

**Files Changed**: 
- `rds_encryption_automation.py` (lines 258-342, 619-645)

---

### 🎯 Feature: Interactive Origin Selection

**Enhancement**: When multiple replication origins exist, the script now:
- Lists all origins with OID and name
- Prompts user to select which one to advance
- Validates user input

This prevents confusion when multiple origins exist from previous runs.

**Files Changed**: `rds_encryption_automation.py` (lines 473-499)

---

### 📋 Feature: New `list-origins` Action

**New Command**:
```bash
python rds_encryption_automation.py --config databases.json --action list-origins
```

**Purpose**: Debug and inspect replication origins on target database.

**Output**:
- OID (Object ID)
- Origin Name
- Remote LSN
- Local LSN

**Files Changed**: 
- `rds_encryption_automation.py` (lines 736-791, 845-846, 869-870, 896)

---

## Usage Examples

### Normal Setup (New Subscription)
```bash
python rds_encryption_automation.py --config my-databases.json --action setup-target
```

### When Subscription Exists
```
⚠️  SUBSCRIPTION 'myapp_prod_encryption_pub' ALREADY EXISTS
Drop and recreate? (yes/no): no
INFO - Skipping subscription creation and all subsequent setup steps
INFO - ✓ Target database setup skipped (subscription already exists)
```

### List Origins Before Setup
```bash
python rds_encryption_automation.py --config my-databases.json --action list-origins
python rds_encryption_automation.py --config my-databases.json --action setup-target
```

---

## Documentation

Created/Updated:
- `REPLICATION_ORIGIN_FIX.md` - Detailed explanation of fixes and usage
- `CHANGELOG_20251021.md` - This file

---

## Testing Recommendations

1. **Test with existing subscription**: Run `setup-target` when subscription already exists, choose "no" to skip
2. **Test with multiple origins**: If you have multiple origins, verify selection prompt works
3. **Test list-origins**: Run `list-origins` action to verify output
4. **Test normal flow**: Run full setup on fresh target database

---

## Backward Compatibility

⚠️ **Breaking Change**: The `create_subscription()` method now returns `str` instead of `bool`.

If you have custom code calling this method directly, update it to handle the new return values:
- `'created'` instead of `True` (success)
- `'failed'` instead of `False` (error)
- `'skipped'` (new value)

The main script and all CLI actions are fully compatible with these changes.
