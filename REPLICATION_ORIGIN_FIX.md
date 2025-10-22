# Replication Origin Error Fix & Subscription Skip Enhancement

## Problems Addressed

### 1. Replication Origin Error

When running the `setup-target` action, you encountered this error:

```
ERROR - Error advancing replication origin: replication origin with OID 1 is already active for PID 17013
```

### 2. Subscription Skip Behavior

When a subscription already exists and you choose "no" to drop and recreate, the script would still continue with LSN advancement and enabling steps, which could cause errors or unexpected behavior.

## Root Cause

The error occurs because the original code used `pg_replication_origin_advance()` function, which tries to advance a replication origin that's already active in another session. This is a common issue when working with PostgreSQL logical replication.

## Solution

The fix implements a **session-based approach** to advance the replication origin:

1. **Setup a session** for the replication origin using `pg_replication_origin_session_setup()`
2. **Advance the origin** within that session using `pg_replication_origin_xact_setup()`
3. **Reset the session** using `pg_replication_origin_session_reset()`

This approach properly handles the replication origin lifecycle and avoids conflicts with active sessions.

## Changes Made

### 1. Fixed `advance_replication_origin()` Method

**Location**: `rds_encryption_automation.py`, lines 443-535

**Key Changes**:
- Uses `pg_replication_origin_session_setup()` to create a session
- Uses `pg_replication_origin_xact_setup()` to advance the origin
- Properly resets the session after completion
- Added error handling to ensure session cleanup even on failure

### 2. Added Interactive Origin Selection

When multiple replication origins exist (which can happen if you've run the script multiple times), the script now:
- Lists all available origins with their OID and name
- Prompts you to select which origin to advance
- Shows the selection in the logs

### 3. Added `list-origins` Action

A new action to help debug replication origin issues:

```bash
python rds_encryption_automation.py --config databases.json --action list-origins
```

This displays:
- OID (Object ID)
- Name
- Remote LSN
- Local LSN

### 4. Fixed Subscription Skip Behavior

**Location**: `rds_encryption_automation.py`, lines 258-342 and 619-645

**Key Changes**:
- Changed `create_subscription()` return type from `bool` to `str` with three possible values:
  - `'created'` - Subscription was successfully created
  - `'skipped'` - Subscription already exists and user chose not to recreate
  - `'failed'` - An error occurred
- Modified `setup_target_database()` to handle the skip case:
  - When subscription is skipped, all subsequent steps (LSN advancement, enabling) are skipped
  - Returns `True` immediately with a clear message
  - Prevents unnecessary operations on existing subscriptions

### 5. Integrated Origin Check in setup-target

**Location**: `rds_encryption_automation.py`, lines 675-696

**Key Changes**:
- `setup-target` now automatically runs `check_origin_usage()` before advancing
- Shows detailed report of origin status and active processes
- Prompts for confirmation before proceeding with advancement
- Can be skipped with `--skip-origin-check` flag for automation
- Provides full visibility into what's happening before making changes

## How to Use

### Option 1: Run the Fixed Script Normally

Just run the `setup-target` action as before:

```bash
python rds_encryption_automation.py --config my-databases.json --action setup-target
```

The script will now:
1. Check if subscription already exists and prompt for action
2. If you choose to skip, all remaining setup steps are skipped
3. If you choose to recreate or subscription doesn't exist:
   - Automatically fetch LSN from source (or prompt for manual entry)
   - **🆕 Show detailed origin usage report**
   - **🆕 Prompt for confirmation before advancing**
   - Show available replication origins if multiple exist
   - Properly advance the selected origin without errors

### Option 2: Skip Origin Check (For Automation)

For CI/CD pipelines or automated scripts:

```bash
python rds_encryption_automation.py --config my-databases.json --action setup-target --skip-origin-check
```

This skips the origin usage report and confirmation prompt.

### Option 3: Debug First with list-origins

If you want to see what replication origins exist before advancing:

```bash
# First, list the origins
python rds_encryption_automation.py --config my-databases.json --action list-origins

# Then run setup-target
python rds_encryption_automation.py --config my-databases.json --action setup-target
```

## Technical Details

### PostgreSQL Functions Used

1. **`pg_replication_origin_session_setup(origin_name)`**
   - Sets up a replication origin session for the current database connection
   - Required before advancing the origin

2. **`pg_replication_origin_xact_setup(lsn, timestamp)`**
   - Advances the replication origin to the specified LSN
   - Must be called within an active origin session

3. **`pg_replication_origin_session_reset()`**
   - Resets/clears the current origin session
   - Important for cleanup

### Why the Old Approach Failed

The old code used:
```sql
SELECT pg_replication_origin_advance('origin_name', 'lsn')
```

This function requires that the origin is **not currently active** in any session. However, when a subscription is created, PostgreSQL automatically creates an active session for that origin, causing the conflict.

### Why the New Approach Works

The new approach:
```sql
SELECT pg_replication_origin_session_setup('origin_name');
SELECT pg_replication_origin_xact_setup('lsn', 'timestamp');
SELECT pg_replication_origin_session_reset();
```

This explicitly manages the session lifecycle, allowing you to advance the origin even when it's associated with an active subscription.

## Verification

### When Creating New Subscription

After running the fixed script, you should see:

```
INFO - Creating session for origin: pg_31288228
INFO - Advancing origin to LSN: 0/XXXXXXXX
INFO - ✓ Advanced replication origin 'pg_31288228' to LSN 0/XXXXXXXX
```

No more "already active" errors!

### When Subscription Already Exists and You Skip

You'll see:

```
⚠️  SUBSCRIPTION 'myapp_prod_encryption_pub' ALREADY EXISTS
Drop and recreate? (yes/no): no
INFO - Skipping subscription creation and all subsequent setup steps
INFO - ✓ Target database setup skipped (subscription already exists)
```

The script will exit cleanly without attempting LSN advancement or enabling.

## Additional Notes

- The timestamp parameter in `pg_replication_origin_xact_setup()` is set to `'1970-01-01'` as it's required by the function but not critical for this use case
- If an error occurs during the advance operation, the script will attempt to reset the session automatically
- Multiple replication origins can exist if you've created and dropped subscriptions multiple times - the script now handles this gracefully

## References

- [PostgreSQL Replication Origin Functions](https://www.postgresql.org/docs/current/replication-origins.html)
- [AWS Blog: Encrypt RDS PostgreSQL with Minimal Downtime](https://aws.amazon.com/blogs/database/encrypt-amazon-rds-for-postgresql-and-amazon-aurora-postgresql-database-with-minimal-downtime/)
