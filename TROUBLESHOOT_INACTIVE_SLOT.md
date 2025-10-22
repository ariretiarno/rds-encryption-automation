# Troubleshooting: Replication Slot Not Active

## Understanding Slot States

A replication slot goes through different states during the migration process:

### Normal Flow

| Step | Slot State | Subscription State | Expected |
|------|------------|-------------------|----------|
| 1. After `setup-source` | **INACTIVE** | Doesn't exist | ✅ Normal |
| 2. After subscription created | **INACTIVE** | **DISABLED** | ✅ Normal |
| 3. After subscription enabled | **ACTIVE** | **ENABLED** | ✅ Normal |
| 4. During replication | **ACTIVE** | **ENABLED** | ✅ Normal |

### When to Worry

❌ **Slot is INACTIVE after `setup-target` completes**
❌ **Slot is INACTIVE but subscription is ENABLED**
❌ **Slot stays INACTIVE for more than 30 seconds after enabling**

## Diagnostic Steps

### Step 1: Check Slot Status (Source Database)

```sql
SELECT 
    slot_name,
    slot_type,
    active,
    active_pid,
    restart_lsn,
    confirmed_flush_lsn
FROM pg_replication_slots 
WHERE slot_name LIKE '%encryption%';
```

**Expected after `setup-target`**:
```
slot_name                    | active | active_pid | restart_lsn
-----------------------------+--------+------------+-------------
myapp_encryption_slot        | t      | 12345      | 0/20000110
```

**If `active = f` (false)**:
- Subscription might not be enabled
- Connection issue from target to source
- Subscription worker crashed

### Step 2: Check Subscription Status (Target Database)

```sql
SELECT 
    subname,
    subenabled,
    subslotname,
    subconninfo
FROM pg_subscription
WHERE subname LIKE '%encryption%';
```

**Expected**:
```
subname                  | subenabled | subslotname
-------------------------+------------+-------------------------
myapp_encryption_pub     | t          | myapp_encryption_slot
```

**If `subenabled = f` (false)**:
- Subscription was not enabled
- `enable_subscription()` failed
- Check logs for errors

### Step 3: Check Subscription Workers (Target Database)

```sql
SELECT 
    pid,
    application_name,
    state,
    backend_type,
    client_addr
FROM pg_stat_activity
WHERE application_name LIKE '%encryption%'
   OR backend_type = 'logical replication worker';
```

**Expected**:
```
pid   | application_name      | state | backend_type
------+-----------------------+-------+---------------------------
12345 | myapp_encryption_pub  | idle  | logical replication worker
```

**If no rows**:
- Subscription worker not running
- Subscription might be disabled
- Worker crashed (check logs)

### Step 4: Check for Errors (Target Database)

```sql
-- Check subscription errors
SELECT * FROM pg_stat_subscription
WHERE subname LIKE '%encryption%';
```

Look for:
- `last_msg_send_time` - Should be recent
- `last_msg_receipt_time` - Should be recent
- Any error messages

## Common Causes & Solutions

### Cause 1: Subscription Not Enabled

**Symptom**: Slot inactive, `subenabled = false`

**Check**:
```sql
-- On target
SELECT subname, subenabled FROM pg_subscription;
```

**Solution**:
```sql
-- On target
ALTER SUBSCRIPTION myapp_encryption_pub ENABLE;
```

Or re-run:
```bash
python rds_encryption_automation.py --config databases.json --action setup-target --yes
```

---

### Cause 2: Connection Issues

**Symptom**: Slot inactive, subscription enabled, no worker process

**Check**:
1. Network connectivity from target to source
2. Security groups / firewall rules
3. Source database credentials in subscription

**Test connection**:
```bash
# From target server
psql -h source-db.rds.amazonaws.com -U postgres -d myapp
```

**Solution**:
- Fix network/security group rules
- Verify credentials
- Check `pg_hba.conf` on source allows replication connections

---

### Cause 3: Subscription Worker Crashed

**Symptom**: Slot inactive, subscription enabled, worker process missing

**Check logs** (Target database):
```bash
# RDS CloudWatch Logs
aws logs tail /aws/rds/instance/target-db/postgresql --follow
```

Look for:
- `logical replication worker`
- `subscription`
- `ERROR` or `FATAL`

**Common errors**:
- Permission denied
- Replication slot not found
- Connection timeout

**Solution**:
- Fix the error shown in logs
- Disable and re-enable subscription:
  ```sql
  ALTER SUBSCRIPTION myapp_encryption_pub DISABLE;
  ALTER SUBSCRIPTION myapp_encryption_pub ENABLE;
  ```

---

### Cause 4: Replication Slot Doesn't Exist

**Symptom**: Subscription enabled but slot not found

**Check** (Source database):
```sql
SELECT slot_name FROM pg_replication_slots 
WHERE slot_name = 'myapp_encryption_slot';
```

**If no rows**:
- Slot was dropped
- Slot name mismatch
- `setup-source` didn't complete

**Solution**:
Re-run `setup-source`:
```bash
python rds_encryption_automation.py --config databases.json --action setup-source
```

---

### Cause 5: Timing Issue (Just Enabled)

**Symptom**: Slot inactive immediately after enabling

**This is normal!** The subscription worker takes a few seconds to:
1. Start up
2. Connect to source
3. Acquire the slot

**Wait 10-30 seconds** and check again:
```sql
SELECT active FROM pg_replication_slots 
WHERE slot_name = 'myapp_encryption_slot';
```

---

### Cause 6: Subscription Created But Not Enabled (Script Issue)

**Symptom**: After running `setup-target --yes`, subscription exists but is disabled

**Check script logs**:
```
INFO - ✓ Created subscription: myapp_encryption_pub (disabled)
INFO - ✓ Advanced replication origin 'pg_31288228' to LSN 0/20000110
INFO - ✓ Enabled subscription: myapp_encryption_pub  ← Should see this!
```

**If you don't see "Enabled subscription"**:
- Script failed before enabling
- Error during origin advancement
- Check full logs for errors

**Solution**:
Manually enable:
```sql
ALTER SUBSCRIPTION myapp_encryption_pub ENABLE;
```

Or re-run:
```bash
python rds_encryption_automation.py --config databases.json --action setup-target --yes
```

## Verification Commands

### Quick Check Script

Run this on **source** database:

```sql
-- Check if slot is active and who's using it
SELECT 
    s.slot_name,
    s.active,
    s.active_pid,
    a.application_name,
    a.client_addr,
    a.state
FROM pg_replication_slots s
LEFT JOIN pg_stat_activity a ON s.active_pid = a.pid
WHERE s.slot_name LIKE '%encryption%';
```

**Healthy output**:
```
slot_name             | active | active_pid | application_name     | state
----------------------+--------+------------+----------------------+-------
myapp_encryption_slot | t      | 12345      | myapp_encryption_pub | idle
```

### Full Diagnostic

```bash
# On source database
psql -h source-db.rds.amazonaws.com -U postgres -d myapp -c "
SELECT 
    slot_name,
    plugin,
    slot_type,
    active,
    active_pid,
    restart_lsn,
    confirmed_flush_lsn,
    pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) AS lag
FROM pg_replication_slots 
WHERE slot_name LIKE '%encryption%';
"

# On target database
psql -h target-db.rds.amazonaws.com -U postgres -d myapp -c "
SELECT 
    s.subname,
    s.subenabled,
    s.subslotname,
    ss.pid,
    ss.relid,
    ss.received_lsn,
    ss.latest_end_lsn
FROM pg_subscription s
LEFT JOIN pg_stat_subscription ss ON s.oid = ss.subid
WHERE s.subname LIKE '%encryption%';
"
```

## Expected Timeline

### With `--yes` Flag

```
Time | Action | Slot State | Subscription State
-----|--------|------------|-------------------
T+0s | setup-target starts | INACTIVE | Doesn't exist
T+2s | Subscription created | INACTIVE | DISABLED
T+5s | Origin advanced | INACTIVE | DISABLED
T+6s | Subscription enabled | INACTIVE | ENABLED (worker starting)
T+8s | Worker connects | ACTIVE | ENABLED
T+10s | Replication running | ACTIVE | ENABLED
```

### Without `--yes` Flag (Interactive)

Same timeline, but with pauses for user input.

## If Slot Stays Inactive

After running `setup-target --yes`, wait 30 seconds, then check:

```sql
-- On source
SELECT active FROM pg_replication_slots WHERE slot_name = 'myapp_encryption_slot';
```

**If still `active = false`**:

1. **Check target subscription**:
   ```sql
   SELECT subenabled FROM pg_subscription WHERE subname = 'myapp_encryption_pub';
   ```

2. **If `subenabled = false`**, manually enable:
   ```sql
   ALTER SUBSCRIPTION myapp_encryption_pub ENABLE;
   ```

3. **If `subenabled = true`**, check for errors:
   ```sql
   SELECT * FROM pg_stat_subscription;
   ```

4. **Check target logs** for worker errors

5. **Test connection** from target to source

## Automated Check Script

Save this as `check_replication_status.sh`:

```bash
#!/bin/bash

echo "=== SOURCE DATABASE (Slot Status) ==="
psql -h $SOURCE_HOST -U postgres -d $DB_NAME -c "
SELECT slot_name, active, active_pid, restart_lsn 
FROM pg_replication_slots 
WHERE slot_name LIKE '%encryption%';
"

echo ""
echo "=== TARGET DATABASE (Subscription Status) ==="
psql -h $TARGET_HOST -U postgres -d $DB_NAME -c "
SELECT subname, subenabled, subslotname 
FROM pg_subscription 
WHERE subname LIKE '%encryption%';
"

echo ""
echo "=== TARGET DATABASE (Worker Processes) ==="
psql -h $TARGET_HOST -U postgres -d $DB_NAME -c "
SELECT pid, application_name, state, backend_type 
FROM pg_stat_activity 
WHERE application_name LIKE '%encryption%' 
   OR backend_type = 'logical replication worker';
"
```

Usage:
```bash
export SOURCE_HOST=source-db.rds.amazonaws.com
export TARGET_HOST=target-db.rds.amazonaws.com
export DB_NAME=myapp
bash check_replication_status.sh
```

## Summary

**Slot is INACTIVE after `setup-source`**: ✅ **Normal** - No subscription yet

**Slot is INACTIVE after subscription created**: ✅ **Normal** - Subscription is disabled

**Slot is INACTIVE immediately after `setup-target`**: ✅ **Normal** - Worker starting (wait 10-30s)

**Slot is INACTIVE 30+ seconds after `setup-target`**: ❌ **Problem** - Check:
1. Is subscription enabled? (`subenabled = true`)
2. Is worker running? (Check `pg_stat_activity`)
3. Any errors in logs?
4. Can target connect to source?

**Most common fix**: Manually enable subscription:
```sql
ALTER SUBSCRIPTION myapp_encryption_pub ENABLE;
```
