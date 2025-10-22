# How to Check if Replication Origin is Being Used

## Quick Answer

To check if a replication origin is being used by another process, use the new `check-origin-usage` action:

```bash
python rds_encryption_automation.py --config my-databases.json --action check-origin-usage
```

## What This Shows You

The report includes 4 sections:

### 1. All Replication Origins
Lists all origins with their OID, name, and LSN positions.

### 2. Subscription Workers
Shows which subscriptions exist and whether they have active worker processes.
- **ENABLED** subscriptions have active workers that use the origin
- **DISABLED** subscriptions don't have active workers

### 3. Origin-to-Subscription Mapping
Maps each origin to its subscription and shows status:
- **ACTIVE (enabled)** - Origin is currently in use ⚠️
- **INACTIVE (disabled)** - Origin exists but not in use
- **ORPHANED (no subscription)** - Origin has no associated subscription

### 4. Active Replication Processes
Lists all PostgreSQL processes related to replication with their PIDs and states.

## Example Output

```
================================================================================
REPLICATION ORIGIN USAGE REPORT
================================================================================

1. ALL REPLICATION ORIGINS
--------------------------------------------------------------------------------
  OID: 1, Name: pg_31288228
    Remote LSN: 0/20000110, Local LSN: 0/20000110

2. SUBSCRIPTION WORKERS (These use replication origins)
--------------------------------------------------------------------------------
  Subscription: myapp_prod_encryption_pub [ENABLED]
    Slot: myapp_prod_encryption_slot
    Worker PID: 17013, State: idle, Type: logical replication worker

3. ORIGIN-TO-SUBSCRIPTION MAPPING
--------------------------------------------------------------------------------
  Origin 1 (pg_31288228)
    → Subscription: myapp_prod_encryption_pub (OID: 31288228)
    → Status: ACTIVE (enabled)

4. ACTIVE REPLICATION-RELATED PROCESSES
--------------------------------------------------------------------------------
  PID: 17013
    User: postgres, App: myapp_prod_encryption_pub
    Type: logical replication worker, State: idle
    Started: 2025-10-21 11:00:00

================================================================================
INTERPRETATION:
================================================================================
• If 'Status' shows 'ACTIVE (enabled)', the origin is in use
• Active subscription workers hold the origin session
• To advance origin, use session-based approach (already in script)
• Or temporarily: ALTER SUBSCRIPTION <name> DISABLE;
================================================================================
```

## Understanding the Output

### If Origin Shows "ACTIVE (enabled)"
This means:
- The subscription is enabled
- A worker process is running (or will run)
- The origin is being used by that worker
- **This is why you get "already active" error**

### Solution
The script already handles this with the session-based approach. No action needed!

### If Origin Shows "INACTIVE (disabled)"
This means:
- The subscription exists but is disabled
- No worker is using the origin
- You can safely advance the origin

### If Origin Shows "ORPHANED"
This means:
- The origin exists but has no subscription
- This can happen after dropping a subscription
- You can safely clean it up or ignore it

## Manual SQL Queries

If you prefer to run SQL directly, use the queries in:
```
check_replication_origin_usage.sql
```

### Quick Manual Check

Connect to your target database and run:

```sql
-- Check if origin is linked to an enabled subscription
SELECT 
    ro.roident AS origin_id,
    ro.roname AS origin_name,
    s.subname AS subscription_name,
    s.subenabled AS is_enabled,
    CASE 
        WHEN s.subenabled THEN 'ACTIVE (in use)'
        ELSE 'INACTIVE'
    END AS status
FROM pg_replication_origin ro
LEFT JOIN pg_subscription s 
    ON ro.roname = 'pg_' || s.oid::text;
```

### Check Active Workers

```sql
-- See which processes are running replication workers
SELECT 
    pid,
    application_name,
    state,
    backend_type
FROM pg_stat_activity
WHERE backend_type = 'logical replication worker';
```

## Common Scenarios

### Scenario 1: "Already Active" Error
**Symptom**: Error when trying to advance origin

**Check**:
```bash
python rds_encryption_automation.py --config my-databases.json --action check-origin-usage
```

**Look for**: Section 3 showing "ACTIVE (enabled)"

**Solution**: The script's session-based approach handles this automatically. Just run `setup-target` normally.

### Scenario 2: Multiple Origins
**Symptom**: Multiple origins listed, unsure which to use

**Check**:
```bash
python rds_encryption_automation.py --config my-databases.json --action check-origin-usage
```

**Look for**: Section 3 showing which origin maps to your subscription

**Solution**: The script will prompt you to select the correct origin.

### Scenario 3: Orphaned Origins
**Symptom**: Origins exist but no subscriptions

**Check**:
```bash
python rds_encryption_automation.py --config my-databases.json --action check-origin-usage
```

**Look for**: Section 3 showing "ORPHANED (no subscription)"

**Solution**: These are safe to ignore or clean up manually:
```sql
-- Clean up orphaned origin (be careful!)
SELECT pg_replication_origin_drop('pg_31288228');
```

## Troubleshooting Tips

### If Worker Shows "idle in transaction"
This might indicate a stuck transaction. Check:
```sql
SELECT pid, state, query_start, state_change, query
FROM pg_stat_activity
WHERE backend_type = 'logical replication worker';
```

### If You Need to Temporarily Disable
To free up the origin temporarily:
```sql
ALTER SUBSCRIPTION myapp_prod_encryption_pub DISABLE;
-- Do your work
ALTER SUBSCRIPTION myapp_prod_encryption_pub ENABLE;
```

### If You Need to Kill a Worker
**⚠️ Use with caution!**
```sql
-- Find the PID first
SELECT pid FROM pg_stat_activity 
WHERE backend_type = 'logical replication worker';

-- Terminate gracefully
SELECT pg_terminate_backend(17013);

-- Or force kill (last resort)
SELECT pg_cancel_backend(17013);
```

## Summary

**Best Practice**: Always run `check-origin-usage` before troubleshooting replication issues.

```bash
# Diagnostic workflow
python rds_encryption_automation.py --config my-databases.json --action check-origin-usage
python rds_encryption_automation.py --config my-databases.json --action list-origins
python rds_encryption_automation.py --config my-databases.json --action setup-target
```

The script's session-based approach handles most "already active" scenarios automatically, but this diagnostic tool helps you understand what's happening under the hood.
