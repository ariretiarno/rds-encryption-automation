# LSN (Log Sequence Number) Guide

## What is LSN?

LSN (Log Sequence Number) is a unique identifier for a position in the PostgreSQL Write-Ahead Log (WAL). It's formatted as `0/XXXXXXXX` (e.g., `0/20000110`).

During RDS encryption migration, we need the LSN to tell the target database: "I already have data up to this point, only send me changes after this."

---

## Three Ways to Get LSN

### ✅ Method 1: Auto-fetch from Source Database (RECOMMENDED - Easiest)

**This is now the default and easiest method!**

The script can automatically query the source PostgreSQL database to get the current LSN from the replication slot.

#### How it works:
```sql
-- The script runs this query on the source database:
SELECT confirmed_flush_lsn
FROM pg_replication_slots
WHERE slot_name = 'your_slot_name' AND slot_type = 'logical';
```

#### Usage:

**Option A: During setup-target (Interactive)**
```bash
python rds_encryption_automation.py \
  --config databases.json \
  --action setup-target

# When prompted, just press Enter to auto-fetch LSN from source
```

**Option B: Standalone command**
```bash
# Get LSN only
python rds_encryption_automation.py \
  --config databases.json \
  --action get-lsn

# Output:
# ================================================================================
# Current LSN from source database: 0/20000110
# ================================================================================
```

**Option C: Use the fetched LSN in setup-target**
```bash
# First get the LSN
LSN=$(python rds_encryption_automation.py --config databases.json --action get-lsn | grep "0/" | awk '{print $NF}')

# Then use it
python rds_encryption_automation.py \
  --config databases.json \
  --action setup-target \
  --lsn $LSN
```

#### Advantages:
- ✅ **Easiest** - No manual log searching
- ✅ **Fastest** - Instant result
- ✅ **Most reliable** - Direct from database
- ✅ **No AWS CLI needed** - Works anywhere with database access
- ✅ **Scriptable** - Easy to automate

#### When to use:
- **Always use this method first** - It's the simplest and most reliable
- Perfect for automation and scripting
- Works from any location with database connectivity

---

### Method 2: From CloudWatch Logs (AWS Console)

Get LSN from the PostgreSQL logs in AWS Console.

#### Steps:
1. Go to AWS RDS Console
2. Select your **encrypted** (target) database
3. Click "Logs & events" tab
4. Open the most recent PostgreSQL log file
5. Search for "invalid record length"
6. Look for a line like:
   ```
   2024-10-15 11:30:00 UTC::@:[12345]:LOG: invalid record length at 0/20000110
   ```
7. Copy the LSN: `0/20000110`

#### Advantages:
- ✅ Official AWS method (from AWS blog post)
- ✅ Visual confirmation in console
- ✅ Good for one-time manual migrations

#### Disadvantages:
- ❌ Requires AWS Console access
- ❌ Manual searching through logs
- ❌ Time-consuming for multiple databases
- ❌ Not scriptable

#### When to use:
- When you don't have direct database access
- For verification/double-checking
- When troubleshooting issues

---

### Method 3: From CloudWatch Logs (AWS CLI)

Get LSN using AWS CLI to query CloudWatch logs.

#### Command:
```bash
aws logs filter-log-events \
  --log-group-name /aws/rds/instance/encrypted-db/postgresql \
  --filter-pattern 'invalid record length' \
  --max-items 5 \
  --query 'events[*].message' \
  --output text
```

#### Or use the helper script:
```bash
./aws_helper.sh get-lsn encrypted-db
```

#### Advantages:
- ✅ Scriptable
- ✅ No database connection needed
- ✅ Can be automated

#### Disadvantages:
- ❌ Requires AWS CLI configured
- ❌ Requires CloudWatch Logs access
- ❌ May need to parse output
- ❌ Slower than direct database query

#### When to use:
- When you have AWS CLI but not database access
- For automation when database access is restricted
- When integrating with AWS-based workflows

---

## Comparison Table

| Method | Ease of Use | Speed | Reliability | Scriptable | Requirements |
|--------|-------------|-------|-------------|------------|--------------|
| **Auto-fetch from DB** | ⭐⭐⭐⭐⭐ | ⚡ Instant | ✅ High | ✅ Yes | Database access |
| **AWS Console** | ⭐⭐ | 🐌 Slow | ✅ High | ❌ No | AWS Console access |
| **AWS CLI** | ⭐⭐⭐ | ⚡ Fast | ✅ High | ✅ Yes | AWS CLI configured |

---

## Understanding LSN in Migration Context

### Timeline Visualization

```
Snapshot Created at LSN: 0/20000110
         │
         ▼
    ─────┴─────────────────────────────────────────────────────────────>
    │                                                                  │
    │ Data BEFORE this LSN                                             │
    │ ✅ Already in snapshot                                           │
    │ ✅ Already in target database                                    │
    │                                                                  │
    └──────────────────────────────────────────────────────────────────┘
                                                                       │
                                                                       │
    ┌──────────────────────────────────────────────────────────────────┘
    │
    │ Data AFTER this LSN
    │ ⚠️  Needs to be replicated
    │ ⚠️  Will be streamed via logical replication
    │
    └─────────────────────────────────────────────────────────────────>
```

### Why We Need LSN

**Without advancing to LSN:**
- Target thinks: "I have no data"
- Source tries to send: "Everything from the beginning"
- Result: ❌ Duplicate data, conflicts, errors

**With advancing to snapshot LSN:**
- Target thinks: "I have data up to 0/20000110"
- Source sends: "Only changes after 0/20000110"
- Result: ✅ Clean replication, no duplicates

---

## PostgreSQL Commands for LSN

### Get current WAL LSN:
```sql
SELECT pg_current_wal_lsn();
-- Returns: 0/20000110
```

### Get LSN from replication slot:
```sql
SELECT 
    slot_name,
    confirmed_flush_lsn,
    pg_current_wal_lsn() AS current_lsn,
    (pg_current_wal_lsn() - confirmed_flush_lsn) AS lag_bytes
FROM pg_replication_slots
WHERE slot_type = 'logical';
```

### Check replication lag:
```sql
SELECT 
    slot_name,
    pg_size_pretty(pg_current_wal_lsn() - confirmed_flush_lsn) AS replication_lag
FROM pg_replication_slots
WHERE slot_type = 'logical';
```

---

## Troubleshooting

### Issue: "Could not auto-fetch LSN from source"

**Possible causes:**
1. Replication slot not created yet
2. Connection to source database failed
3. Insufficient permissions

**Solutions:**
```bash
# 1. Verify replication slot exists
psql -h source-db -U postgres -d mydb -c "SELECT * FROM pg_replication_slots;"

# 2. Test connection
psql -h source-db -U postgres -d mydb -c "SELECT version();"

# 3. Check user permissions
psql -h source-db -U postgres -d mydb -c "SELECT current_user, pg_is_in_recovery();"
```

### Issue: "LSN not found in CloudWatch logs"

**Possible causes:**
1. Wrong log group name
2. Logs not yet available
3. Database not fully restored

**Solutions:**
```bash
# 1. List log groups
aws logs describe-log-groups --log-group-name-prefix /aws/rds/instance/

# 2. List log streams
aws logs describe-log-streams \
  --log-group-name /aws/rds/instance/encrypted-db/postgresql \
  --order-by LastEventTime \
  --descending

# 3. Wait a few minutes and try again
```

### Issue: "Invalid LSN format"

**Valid formats:**
- ✅ `0/20000110`
- ✅ `0/1A2B3C4D`
- ❌ `20000110` (missing segment)
- ❌ `0x20000110` (wrong prefix)

---

## Best Practices

### 1. Always Try Auto-fetch First
```bash
# This is the easiest and most reliable
python rds_encryption_automation.py --config databases.json --action setup-target
# Press Enter when prompted to auto-fetch LSN
```

### 2. Verify LSN Before Using
```bash
# Get LSN
python rds_encryption_automation.py --config databases.json --action get-lsn

# Verify it looks correct (format: 0/XXXXXXXX)
# Then use it
```

### 3. Document Your LSN
Keep a record of the LSN used for each migration:
```bash
# Save to file
python rds_encryption_automation.py --config databases.json --action get-lsn | tee migration_lsn.txt
```

### 4. For Multiple Databases
```bash
# Get LSN for each database
for db in db1 db2 db3; do
  echo "=== $db ==="
  python rds_encryption_automation.py \
    --config databases.json \
    --action get-lsn \
    --database $db
done
```

---

## Summary

**Recommended Approach:**

1. **Use auto-fetch from source database** (Method 1)
   - Easiest, fastest, most reliable
   - Just press Enter when prompted

2. **Fallback to AWS CLI** (Method 3)
   - If database access is restricted
   - Use `./aws_helper.sh get-lsn <db-instance>`

3. **Last resort: AWS Console** (Method 2)
   - For manual verification
   - When troubleshooting

**The new auto-fetch feature makes LSN retrieval trivial - no more manual log searching!**

---

## Quick Reference

```bash
# Get LSN (standalone)
python rds_encryption_automation.py --config databases.json --action get-lsn

# Setup target with auto-fetch (press Enter when prompted)
python rds_encryption_automation.py --config databases.json --action setup-target

# Setup target with manual LSN
python rds_encryption_automation.py --config databases.json --action setup-target --lsn 0/20000110

# Get LSN via AWS CLI
./aws_helper.sh get-lsn encrypted-db

# Get LSN via psql
psql -h source-db -U postgres -d mydb -c "SELECT confirmed_flush_lsn FROM pg_replication_slots WHERE slot_name = 'myslot';"
```

---

**Updated**: October 15, 2024  
**Feature**: Auto-fetch LSN from source database (NEW!)
