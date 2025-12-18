# Rollback Guide: Replica to Master with No Data Discrepancy

## Overview

This guide explains how to safely rollback from replica to master using the **reverse replication** approach, ensuring no data discrepancies or duplicates by using the correct LSN (Log Sequence Number).

## Scenario

You want to use the **old instance** (original master) as the new replica, and make the **replica become the new master**. This requires:
1. Creating publication on the **replica** (new master)
2. Creating subscription on the **old master** (new replica)
3. Using the **correct LSN** to prevent duplicates

## Critical Concept: Understanding LSN for Rollback

### Why LSN Matters

The LSN (Log Sequence Number) represents a specific point in the PostgreSQL Write-Ahead Log (WAL). When setting up reverse replication, you need the LSN that represents:
- **The exact point where the replica snapshot was taken**
- This ensures the old master doesn't re-apply changes it already has

### The Problem Without Correct LSN

❌ **Without correct LSN**: Old master will receive duplicate data from changes that already exist
✅ **With correct LSN**: Old master starts replication from the exact point after the snapshot, avoiding duplicates

## Step-by-Step Rollback Process

### Phase 1: Preparation (Before Cutover)

#### 1. Stop All Writes to Current Master

```sql
-- On CURRENT MASTER (old instance)
-- Block all connections except from specific IPs
-- Use security groups or pg_hba.conf
```

#### 2. Wait for Replication to Catch Up

```sql
-- On CURRENT MASTER
-- Check replication lag is 0
SELECT 
    slot_name, 
    confirmed_flush_lsn AS flushed, 
    pg_current_wal_lsn(), 
    (pg_current_wal_lsn() - confirmed_flush_lsn) AS lsn_distance 
FROM pg_catalog.pg_replication_slots 
WHERE slot_type = 'logical';

-- lsn_distance should be 0
```

#### 3. Record the Current LSN on Replica

```sql
-- On REPLICA (will become new master)
-- This is CRITICAL - record this LSN
SELECT pg_current_wal_lsn();
-- Example output: 38E7/403FB58
```

**⚠️ IMPORTANT**: This LSN is what you'll use for the reverse subscription!

### Phase 2: Setup Reverse Replication

#### 4. Create Publication on Replica (New Master)

```sql
-- On REPLICA (new master)
-- Enable logical replication if not already enabled
-- (Should already be enabled from previous setup)

-- Create publication for each database
CREATE PUBLICATION airbyte_pub_reverse FOR ALL TABLES;
CREATE PUBLICATION test_dbmate_pub_reverse FOR ALL TABLES;

-- Verify
SELECT * FROM pg_publication;
```

#### 5. Create Replication Slots on Replica (New Master)

```sql
-- On REPLICA (new master)
SELECT * FROM pg_create_logical_replication_slot('airbyte_slot_reverse', 'pgoutput');
SELECT * FROM pg_create_logical_replication_slot('test_dbmate_slot_reverse', 'pgoutput');

-- Verify
SELECT * FROM pg_replication_slots;
```

#### 6. Get the Correct LSN

**Method 1: From Previous Step (Recommended)**
Use the LSN you recorded in Step 3 when you ran `SELECT pg_current_wal_lsn()` on the replica.

**Method 2: From Replication Slot on Old Master**
```sql
-- On OLD MASTER
-- Get the confirmed_flush_lsn from the existing replication slot
SELECT 
    slot_name,
    confirmed_flush_lsn,
    restart_lsn
FROM pg_replication_slots
WHERE slot_name IN ('airbyte_slot', 'test_dbmate_slot');

-- Use the confirmed_flush_lsn value
```

**Method 3: From Replication Origin Status on Replica**
```sql
-- On REPLICA
-- Check what LSN the replica has processed
SELECT 
    ros.external_id,
    ros.remote_lsn,  -- This is the LSN from master
    ros.local_lsn,   -- This is the LSN on replica
    s.subname
FROM pg_replication_origin_status ros
JOIN pg_replication_origin ro ON ros.local_id = ro.roident
JOIN pg_subscription s ON ro.roname = 'pg_' || s.oid::text;

-- Use the remote_lsn value
```

#### 7. Disable and Drop Old Subscriptions on Replica

```sql
-- On REPLICA (new master)
-- Clean up the old subscription that was receiving from master

ALTER SUBSCRIPTION airbyte_sub DISABLE;
ALTER SUBSCRIPTION airbyte_sub SET (slot_name = NONE);
DROP SUBSCRIPTION airbyte_sub;

ALTER SUBSCRIPTION test_dbmate_sub DISABLE;
ALTER SUBSCRIPTION test_dbmate_sub SET (slot_name = NONE);
DROP SUBSCRIPTION test_dbmate_sub;
```

#### 8. Drop Old Replication Slots on Old Master

```sql
-- On OLD MASTER
-- Clean up the old replication slots

SELECT pg_drop_replication_slot('airbyte_slot');
SELECT pg_drop_replication_slot('test_dbmate_slot');

-- Drop old publications
DROP PUBLICATION airbyte_pub;
DROP PUBLICATION test_dbmate_pub;
```

### Phase 3: Create Reverse Subscription

#### 9. Create Subscription on Old Master (New Replica)

```sql
-- On OLD MASTER (new replica)
-- Create subscription pointing to REPLICA (new master)

CREATE SUBSCRIPTION airbyte_sub_reverse
CONNECTION 'host=<REPLICA_HOST> user=root password=<PASSWORD> dbname=airbyte'
PUBLICATION airbyte_pub_reverse
WITH (
    copy_data = false,        -- CRITICAL: Don't copy data
    create_slot = false,      -- Slot already created
    enabled = false,          -- Start disabled
    synchronous_commit = false,
    connect = true,
    slot_name = 'airbyte_slot_reverse'
);

CREATE SUBSCRIPTION test_dbmate_sub_reverse
CONNECTION 'host=<REPLICA_HOST> user=root password=<PASSWORD> dbname=test-dbmate'
PUBLICATION test_dbmate_pub_reverse
WITH (
    copy_data = false,
    create_slot = false,
    enabled = false,
    synchronous_commit = false,
    connect = true,
    slot_name = 'test_dbmate_slot_reverse'
);
```

#### 10. Advance Replication Origin to Correct LSN

```sql
-- On OLD MASTER (new replica)
-- Get replication origins
SELECT * FROM pg_replication_origin;

-- Find unused origins
SELECT o.roname 
FROM pg_replication_origin o
LEFT JOIN pg_replication_origin_status s ON o.roident = s.local_id
WHERE o.roname LIKE 'pg_%' AND s.local_id IS NULL;

-- Advance to the LSN from Step 6
-- Use the LSN you recorded when replica was in sync
SELECT pg_replication_origin_advance('pg_<OID>', '<LSN_FROM_STEP_6>');
-- Example: SELECT pg_replication_origin_advance('pg_148921862', '38E7/403FB58');
```

**⚠️ CRITICAL**: The LSN must be the one from Step 6 (when replica was fully caught up)

#### 11. Enable Reverse Subscription

```sql
-- On OLD MASTER (new replica)
ALTER SUBSCRIPTION airbyte_sub_reverse ENABLE;
ALTER SUBSCRIPTION test_dbmate_sub_reverse ENABLE;
```

### Phase 4: Verification

#### 12. Verify Replication is Working

```sql
-- On REPLICA (new master)
-- Check replication slot status
SELECT 
    slot_name, 
    confirmed_flush_lsn AS flushed, 
    pg_current_wal_lsn(), 
    (pg_current_wal_lsn() - confirmed_flush_lsn) AS lsn_distance 
FROM pg_catalog.pg_replication_slots 
WHERE slot_type = 'logical';

-- lsn_distance should be 0 or very small
```

```sql
-- On OLD MASTER (new replica)
-- Check subscription status
SELECT 
    ros.external_id,
    ros.remote_lsn,
    ros.local_lsn,
    s.subname AS subscription_name,
    s.subenabled AS enabled
FROM pg_replication_origin_status ros
JOIN pg_replication_origin ro ON ros.local_id = ro.roident
JOIN pg_subscription s ON ro.roname = 'pg_' || s.oid::text
ORDER BY s.subname;
```

#### 13. Test Data Consistency

```sql
-- On both databases, compare row counts
SELECT 
    schemaname,
    tablename,
    n_live_tup as row_count
FROM pg_stat_user_tables
ORDER BY schemaname, tablename;

-- Check specific tables for data integrity
SELECT COUNT(*), MAX(id), MIN(id) FROM your_table;
```

## How to Get the Right LSN: Summary

### Best Practice (Recommended)

1. **Before cutover**: Stop writes to old master
2. **Wait for sync**: Ensure replica is fully caught up (lsn_distance = 0)
3. **Record LSN on replica**: Run `SELECT pg_current_wal_lsn()` on replica
4. **Use this LSN**: When creating reverse subscription on old master

### Alternative Methods

| Method | Command | When to Use |
|--------|---------|-------------|
| **Current WAL LSN on Replica** | `SELECT pg_current_wal_lsn()` on replica | Best - use when replica is fully synced |
| **Confirmed Flush LSN** | `SELECT confirmed_flush_lsn FROM pg_replication_slots` on old master | Good - shows what replica has confirmed |
| **Remote LSN from Origin** | `SELECT remote_lsn FROM pg_replication_origin_status` on replica | Good - shows what replica received from master |
| **From Logs** | Search for "invalid record length" in PostgreSQL logs | Last resort - after snapshot restore |

## Preventing Duplicates: Key Points

### ✅ DO

- **Stop writes** to old master before recording LSN
- **Wait for full sync** (lsn_distance = 0) before recording LSN
- **Record LSN immediately** after confirming sync
- **Use `copy_data = false`** in subscription
- **Advance replication origin** to the recorded LSN before enabling subscription

### ❌ DON'T

- Don't use LSN from before the replica was synced
- Don't enable subscription before advancing replication origin
- Don't use `copy_data = true` (this will duplicate all data)
- Don't guess the LSN value

## Automation Script for Reverse Replication

You can modify your existing scripts for reverse replication:

```bash
# 1. On REPLICA (new master)
# Create publications and slots
python3 manage_publications.py create

# 2. Record LSN on REPLICA
psql -h <REPLICA_HOST> -U root -d airbyte -c "SELECT pg_current_wal_lsn();"

# 3. Update .env with:
# - MASTER_DB_HOST = <REPLICA_HOST> (new master)
# - REPLICATION_DB_HOST = <OLD_MASTER_HOST> (new replica)
# - LSN = <LSN_FROM_STEP_2>

# 4. On OLD MASTER (new replica)
# Create subscriptions
python3 manage_subscriptions.py create
```

## Troubleshooting

### Issue: Duplicate Data

**Cause**: LSN was set too early (before replica caught up)
**Solution**: 
1. Drop subscription
2. Truncate affected tables
3. Restore from backup
4. Use correct LSN (when replica was fully synced)

### Issue: Missing Data

**Cause**: LSN was set too late (after new changes on replica)
**Solution**:
1. Check `pg_replication_slots` for actual LSN
2. Verify no writes happened between LSN recording and subscription creation

### Issue: Subscription Not Advancing

**Cause**: Replication origin not advanced correctly
**Solution**:
```sql
-- Check current origin status
SELECT * FROM pg_replication_origin_status;

-- Re-advance if needed
SELECT pg_replication_origin_advance('pg_<OID>', '<CORRECT_LSN>');
```

## Rollback Checklist

- [ ] Stop all writes to old master
- [ ] Verify replica is fully synced (lsn_distance = 0)
- [ ] Record current LSN on replica: `SELECT pg_current_wal_lsn()`
- [ ] Create publications on replica (new master)
- [ ] Create replication slots on replica (new master)
- [ ] Drop old subscriptions on replica
- [ ] Drop old replication slots on old master
- [ ] Create reverse subscriptions on old master (new replica)
- [ ] Advance replication origin to recorded LSN
- [ ] Enable reverse subscriptions
- [ ] Verify replication is working
- [ ] Test data consistency
- [ ] Update application connection strings to new master

## References

- [AWS Blog: Encrypt RDS PostgreSQL with Minimal Downtime](https://aws.amazon.com/blogs/database/encrypt-amazon-rds-for-postgresql-and-amazon-aurora-postgresql-database-with-minimal-downtime/)
- [PostgreSQL Logical Replication Documentation](https://www.postgresql.org/docs/current/logical-replication.html)
- [pg_replication_origin_advance](https://www.postgresql.org/docs/current/functions-admin.html#FUNCTIONS-REPLICATION)
