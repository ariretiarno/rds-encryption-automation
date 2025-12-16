# Sequence Synchronization Guide

## Overview

PostgreSQL logical replication (publication-subscription) **does NOT replicate sequences**. This is a known limitation of logical replication. Only table data (INSERT/UPDATE/DELETE) is replicated, while sequences remain independent on each server.

This guide explains how to handle sequence synchronization using the provided tools.

---

## The Problem

### What Happens with Sequences in Logical Replication

- **✗ Sequences are NOT replicated** - Only table data changes are sent to subscribers
- **✓ Publisher sequences advance** - As data is inserted on publisher, sequences increment normally
- **✗ Subscriber sequences stay at initial value** - They don't receive sequence updates
- **⚠️ Risk**: If subscriber becomes publisher (failover), new inserts may cause primary key conflicts

### Example Scenario

```sql
-- On PUBLISHER
INSERT INTO users (id, name) VALUES (nextval('users_id_seq'), 'Alice');
-- users_id_seq is now at 1

INSERT INTO users (id, name) VALUES (nextval('users_id_seq'), 'Bob');
-- users_id_seq is now at 2

-- On SUBSCRIBER
-- Data is replicated: users table has Alice (id=1) and Bob (id=2)
-- BUT: users_id_seq is still at 1 (initial value)

-- If subscriber becomes publisher and you insert:
INSERT INTO users (id, name) VALUES (nextval('users_id_seq'), 'Charlie');
-- ERROR: duplicate key value violates unique constraint "users_pkey"
-- DETAIL: Key (id)=(1) already exists.
```

---

## Solution: Sequence Sync Scripts

We provide two scripts to handle sequence synchronization:

1. **`sync_sequences.py`** - Synchronize sequence values from master to replica
2. **`monitor_sequences.py`** - Monitor sequence drift between master and replica

---

## Script 1: sync_sequences.py

### Purpose

Synchronizes all sequence values from master (publisher) to replica (subscriber) database.

### Features

- ✅ Syncs all sequences in a database
- ✅ Dry-run mode to preview changes
- ✅ Safety checks (won't overwrite if replica > master without `--force`)
- ✅ Interactive confirmation mode
- ✅ Supports single database or all databases
- ✅ Detailed logging and summary reports

### Installation

The script is already included in your toolkit. Ensure dependencies are installed:

```bash
pip install -r requirements.txt
```

### Usage

#### Basic Usage

```bash
# Sync sequences for a specific database
python3 sync_sequences.py mydb
```

#### Dry Run (Recommended First)

```bash
# Preview what would be synced without making changes
python3 sync_sequences.py mydb --dry-run
```

**Output:**
```
================================================================================
Syncing sequences for database: mydb
[DRY RUN MODE - No changes will be made]
Master: master-host:5432
Replica: replica-host:5432
================================================================================
Connecting to master database...
Connecting to replica database...

Fetching sequences from master...
Found 5 sequences on master

Fetching sequences from replica...
Found 5 sequences on replica

Syncing sequences...
  → Syncing public.users_id_seq: 1 → 1523
  [DRY RUN] Would set "public"."users_id_seq" to 1523 (is_called=True)
  → Syncing public.orders_id_seq: 1 → 847
  [DRY RUN] Would set "public"."orders_id_seq" to 847 (is_called=True)
  ≈ public.products_id_seq already in sync (100)

================================================================================
SYNC SUMMARY
================================================================================
Total sequences on master: 5
Synced: 2
Skipped: 3
Failed: 0

[DRY RUN] No changes were made. Run without --dry-run to apply changes.
```

#### Sync All Databases

```bash
# Sync sequences for all databases in .env DATABASES variable
python3 sync_sequences.py --all
```

#### Force Sync

```bash
# Force sync even if replica value is higher than master
# Use with caution!
python3 sync_sequences.py mydb --force
```

#### Interactive Mode

```bash
# Prompt for confirmation before syncing
python3 sync_sequences.py mydb --execute
```

**Prompt:**
```
You are about to sync sequences for: mydb
This will update sequence values on the replica database.

Are you sure you want to continue? (yes/no): 
```

### Command Reference

| Flag | Description |
|------|-------------|
| `database` | Database name to sync (required unless `--all`) |
| `--all` | Sync all databases from .env |
| `--dry-run` | Preview changes without applying |
| `--force` | Force sync even if replica > master |
| `--execute` | Prompt for confirmation before syncing |

### Examples

```bash
# Example 1: Safe preview
python3 sync_sequences.py everanakintern --dry-run

# Example 2: Sync with confirmation
python3 sync_sequences.py everanakintern --execute

# Example 3: Sync all databases
python3 sync_sequences.py --all

# Example 4: Force sync (use carefully)
python3 sync_sequences.py everanakintern --force
```

---

## Script 2: monitor_sequences.py

### Purpose

Monitors sequence drift between master and replica databases to identify when synchronization is needed.

### Features

- ✅ Shows sequence values on both master and replica
- ✅ Calculates drift (difference) and percentage
- ✅ Color-coded status indicators
- ✅ Tabular output for easy reading
- ✅ Threshold filtering
- ✅ Continuous watch mode
- ✅ Exit codes for automation

### Usage

#### Basic Monitoring

```bash
# Monitor sequences for a specific database
python3 monitor_sequences.py mydb
```

**Output:**
```
================================================================================
Monitoring sequences for database: mydb
Master: master-host:5432
Replica: replica-host:5432
================================================================================
Connecting to master database...
Connecting to replica database...

Fetching sequences from master...
Found 5 sequences on master
Fetching sequences from replica...
Found 5 sequences on replica

Analyzing sequence drift...

+-------------------------+--------------+---------------+-------+---------+-------------+
| Sequence                | Master Value | Replica Value | Drift | Drift % | Status      |
+=========================+==============+===============+=======+=========+=============+
| public.users_id_seq     | 1523         | 1            | 1522  | 99.9%   | ❌ CRITICAL |
| public.orders_id_seq    | 847          | 1            | 846   | 99.9%   | ⚠ WARNING   |
| public.products_id_seq  | 100          | 100          | 0     | 0.0%    | ✓ IN SYNC   |
+-------------------------+--------------+---------------+-------+---------+-------------+

================================================================================
MONITORING SUMMARY
================================================================================
Total sequences: 5
In sync: 1
Out of sync: 4
Critical drift (>1000): 1

⚠ Sequences are out of sync!
Run sync_sequences.py to synchronize:
  python3 sync_sequences.py mydb --dry-run
  python3 sync_sequences.py mydb
```

#### Show All Sequences

```bash
# Show all sequences, including those in sync
python3 monitor_sequences.py mydb --show-all
```

#### Threshold Filtering

```bash
# Only show sequences with drift >= 100
python3 monitor_sequences.py mydb --threshold 100
```

#### Continuous Monitoring

```bash
# Watch mode: refresh every 60 seconds
python3 monitor_sequences.py mydb --watch 60
```

Press `Ctrl+C` to stop monitoring.

#### Monitor All Databases

```bash
# Monitor all databases from .env
python3 monitor_sequences.py --all
```

### Status Indicators

| Icon | Status | Meaning |
|------|--------|---------||
| ✓ IN SYNC | Good | Sequences are identical |
| ⚠ DRIFT | Warning | Small drift detected |
| ⚠ WARNING | Warning | Drift > 100 |
| ❌ CRITICAL | Critical | Drift > 1000 |
| ❌ MISSING | Critical | Sequence exists on master but not replica |
| ⚠ EXTRA | Warning | Sequence exists on replica but not master |

### Exit Codes

Useful for automation and monitoring systems:

| Exit Code | Meaning |
|-----------|---------||
| 0 | All sequences in sync |
| 1 | Warning: Some sequences out of sync |
| 2 | Critical: Severe drift detected |

### Command Reference

| Flag | Description |
|------|-------------|
| `database` | Database name to monitor (required unless `--all`) |
| `--all` | Monitor all databases from .env |
| `--show-all` | Show all sequences, even those in sync |
| `--threshold N` | Only show sequences with drift >= N |
| `--watch N` | Continuous monitoring, refresh every N seconds |

---

## Complete Workflow

### Recommended Sequence Sync Workflow

```bash
# Step 1: Monitor to identify drift
python3 monitor_sequences.py mydb

# Step 2: Preview what would be synced
python3 sync_sequences.py mydb --dry-run

# Step 3: Sync the sequences
python3 sync_sequences.py mydb

# Step 4: Verify synchronization
python3 monitor_sequences.py mydb
```

### Automated Monitoring Script

Create a cron job or scheduled task:

```bash
#!/bin/bash
# check_sequences.sh

# Monitor all databases and exit with appropriate code
python3 monitor_sequences.py --all

EXIT_CODE=$?

if [ $EXIT_CODE -eq 2 ]; then
    echo "CRITICAL: Severe sequence drift detected!"
    # Send alert
elif [ $EXIT_CODE -eq 1 ]; then
    echo "WARNING: Sequences out of sync"
    # Send notification
else
    echo "OK: All sequences in sync"
fi

exit $EXIT_CODE
```

---

## When to Sync Sequences

### Regular Maintenance

Sync sequences periodically to prevent drift:

```bash
# Daily or weekly sync
0 2 * * * cd /path/to/scripts && python3 sync_sequences.py --all
```

### Before Failover

**Critical**: Always sync sequences before promoting replica to master:

```bash
# 1. Stop writes to master
# 2. Wait for replication to catch up
python3 monitor_replication.py

# 3. Sync sequences
python3 sync_sequences.py --all

# 4. Verify sync
python3 monitor_sequences.py --all

# 5. Promote replica to master
```

### After Schema Changes

If you add new tables with sequences:

```bash
# Sync sequences after DDL changes
python3 sync_sequences.py mydb
```

---

## Troubleshooting

### Issue: Replica Value Higher Than Master

**Symptom:**
```
⚠ Skipping public.users_id_seq: replica value (1500) > master value (1000)
  Use --force to override
```

**Cause:** Replica has been written to directly, or sequences were manually adjusted.

**Solution:**
```bash
# Option 1: Investigate why replica is ahead
# Check for direct writes to replica

# Option 2: Force sync if you're sure (use with caution)
python3 sync_sequences.py mydb --force
```

### Issue: Sequence Missing on Replica

**Symptom:**
```
⚠ Sequence public.new_seq exists on master but not on replica - skipping
```

**Cause:** Schema mismatch - sequence exists on master but not replica.

**Solution:**
```bash
# Sync schema first
python3 generate_sync_ddl.py mydb --execute

# Then sync sequences
python3 sync_sequences.py mydb
```

### Issue: Permission Denied

**Symptom:**
```
ERROR: permission denied for sequence users_id_seq
```

**Cause:** Database user doesn't have permission to modify sequences.

**Solution:**
```sql
-- On replica, grant permissions
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO your_user;
```

---

## Best Practices

### 1. Always Use Dry Run First

```bash
# Preview before applying
python3 sync_sequences.py mydb --dry-run
```

### 2. Monitor Regularly

Set up monitoring to catch drift early:

```bash
# Add to cron
*/30 * * * * python3 monitor_sequences.py --all --threshold 1000
```

### 3. Sync Before Failover

Never promote replica without syncing sequences first.

### 4. Document Sequence Usage

Keep track of which tables use sequences for auto-increment IDs.

### 5. Consider UUIDs for New Tables

For new applications, consider using UUIDs instead of sequences:

```sql
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT
);
```

This eliminates sequence sync issues entirely.

---

## Integration with Existing Scripts

### With Replication Recovery

```bash
# After recovering replication, sync sequences
python3 recover_replication.py mydb --force
python3 sync_sequences.py mydb
```

### With Database Comparison

```bash
# Compare schemas, then sync sequences
python3 compare_databases.py mydb
python3 sync_sequences.py mydb
```

### Complete Sync Workflow

```bash
#!/bin/bash
# complete_sync.sh

DB_NAME="$1"

echo "Step 1: Compare databases..."
python3 compare_databases.py $DB_NAME

echo "Step 2: Sync DDL..."
python3 generate_sync_ddl.py $DB_NAME --execute

echo "Step 3: Recover replication..."
python3 recover_replication.py $DB_NAME --force

echo "Step 4: Monitor sequences..."
python3 monitor_sequences.py $DB_NAME

echo "Step 5: Sync sequences..."
python3 sync_sequences.py $DB_NAME --execute

echo "Step 6: Final verification..."
python3 monitor_sequences.py $DB_NAME
python3 monitor_replication.py
```

---

## Technical Details

### How Sequences Are Synced

The script uses PostgreSQL's `setval()` function:

```sql
-- Set sequence to specific value
SELECT setval('schema.sequence_name', 1523, true);

-- Parameters:
-- 1. sequence name
-- 2. value to set
-- 3. is_called: true = next nextval() returns value+increment
--              false = next nextval() returns value
```

### What Gets Synced

- ✅ `last_value` - Current sequence value
- ✅ `is_called` - Whether sequence has been called
- ✗ `start_value` - Not synced (schema-level)
- ✗ `increment_by` - Not synced (schema-level)
- ✗ `max_value` - Not synced (schema-level)
- ✗ `min_value` - Not synced (schema-level)

### Sequences Excluded

System sequences are automatically excluded:
- `pg_catalog.*`
- `information_schema.*`

---

## Summary

### Quick Reference

| Task | Command |
|------|---------||
| Monitor drift | `python3 monitor_sequences.py mydb` |
| Preview sync | `python3 sync_sequences.py mydb --dry-run` |
| Sync sequences | `python3 sync_sequences.py mydb` |
| Sync all databases | `python3 sync_sequences.py --all` |
| Continuous monitoring | `python3 monitor_sequences.py mydb --watch 60` |

### Key Points

- ⚠️ **Sequences are NOT replicated** by PostgreSQL logical replication
- ✅ **Use sync_sequences.py** to synchronize sequence values
- ✅ **Use monitor_sequences.py** to detect drift
- ⚠️ **Always sync before failover** to prevent primary key conflicts
- ✅ **Run dry-run first** to preview changes

### For Your Database (everanakintern)

```bash
# Complete sequence sync workflow
python3 monitor_sequences.py everanakintern
python3 sync_sequences.py everanakintern --dry-run
python3 sync_sequences.py everanakintern
python3 monitor_sequences.py everanakintern
```

---

## Additional Resources

- [PostgreSQL Logical Replication Documentation](https://www.postgresql.org/docs/current/logical-replication.html)
- [PostgreSQL Sequences Documentation](https://www.postgresql.org/docs/current/sql-createsequence.html)
- [AWS RDS Logical Replication](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/CHAP_PostgreSQL.html#PostgreSQL.Concepts.General.FeatureSupport.LogicalReplication)

For issues or questions, refer to the main [README.md](README.md) or check other guides in this directory.
