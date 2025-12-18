# Rollback Quick Reference

## Goal: Reverse Replication (Replica → Master)

Using the **old instance** where:
- **Replica creates publication** (becomes new master)
- **Master creates subscription** (becomes new replica)

## Critical: Getting the Right LSN

### ✅ Correct LSN Prevents Duplicates

```
┌─────────────────────────────────────────────────────────────┐
│  BEFORE ROLLBACK: Master → Replica                         │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  MASTER (Old)                    REPLICA (Old)             │
│  ┌──────────┐                    ┌──────────┐             │
│  │  Data    │  ─────────────────> │  Data    │             │
│  │  LSN: X  │   Replication      │  LSN: X  │             │
│  └──────────┘                    └──────────┘             │
│                                                             │
│  Step 1: STOP WRITES to Master                            │
│  Step 2: WAIT for sync (lag = 0)                          │
│  Step 3: RECORD LSN from Replica = X  ← CRITICAL!         │
│                                                             │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  AFTER ROLLBACK: Replica → Master                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  MASTER (New)                    REPLICA (New)             │
│  ┌──────────┐                    ┌──────────┐             │
│  │  Data    │  <───────────────── │  Data    │             │
│  │  LSN: X  │   Reverse Repl     │  LSN: X  │             │
│  └──────────┘   Start from X     └──────────┘             │
│                                                             │
│  Using LSN = X ensures no duplicate data!                  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Step-by-Step Commands

### 1. Verify Sync (CRITICAL)

```bash
# Check if replication is fully synced
python manage_reverse_replication.py verify

# Expected output:
# ✓ ALL DATABASES ARE FULLY SYNCED
```

**⚠️ DO NOT PROCEED** if there's lag!

### 2. Get LSN from Replica

```bash
# Get LSN information from replica
python get_lsn.py replica

# Look for this line:
# ✓ RECOMMENDED FOR ROLLBACK: 38E7/403FB58
```

**Copy this LSN value!**

### 3. Update Configuration

```bash
# Edit .env file
nano .env

# Update this line:
LSN=38E7/403FB58  # Use the LSN from step 2
```

### 4. Setup New Master (Old Replica)

```bash
# Create publications and replication slots on replica
python manage_reverse_replication.py setup_new_master

# This will:
# - Clean up old subscriptions
# - Create reverse publications
# - Create reverse replication slots
```

### 5. Setup New Replica (Old Master)

```bash
# Create subscriptions on old master
python manage_reverse_replication.py setup_new_replica

# This will:
# - Create reverse subscriptions
# - Advance replication origin to LSN from step 2
# - Enable subscriptions
```

### 6. Verify Reverse Replication

```bash
# Check new master (old replica)
python get_lsn.py replica

# Check new replica (old master)
python get_lsn.py master

# Both should show:
# ✓ FULLY SYNCED
```

## LSN Methods Comparison

| Method | Command | When to Use | Reliability |
|--------|---------|-------------|-------------|
| **Current WAL LSN** | `python get_lsn.py replica` | After stopping writes & sync | ⭐⭐⭐⭐⭐ Best |
| **Confirmed Flush LSN** | Check `pg_replication_slots` on master | When replica is synced | ⭐⭐⭐⭐ Good |
| **Remote LSN** | Check `pg_replication_origin_status` on replica | When replica is synced | ⭐⭐⭐⭐ Good |
| **From Logs** | Search "invalid record length" | After snapshot restore | ⭐⭐ Last resort |

## Common Mistakes to Avoid

### ❌ Wrong LSN = Data Problems

| Mistake | Result | Fix |
|---------|--------|-----|
| LSN too early (before sync) | **Duplicate data** | Drop subscription, truncate, use correct LSN |
| LSN too late (after new writes) | **Missing data** | Check actual LSN from slots |
| No LSN advancement | **All data replicated again** | Always advance replication origin |
| `copy_data = true` | **Duplicate all data** | Always use `copy_data = false` |

## SQL Queries for Manual LSN Check

### On Replica (to get LSN for rollback)

```sql
-- Get current LSN (use this!)
SELECT pg_current_wal_lsn();
-- Example: 38E7/403FB58

-- Check what LSN replica received from master
SELECT 
    ros.remote_lsn,
    s.subname
FROM pg_replication_origin_status ros
JOIN pg_replication_origin ro ON ros.local_id = ro.roident
JOIN pg_subscription s ON ro.roname = 'pg_' || s.oid::text;
```

### On Master (to verify sync before rollback)

```sql
-- Check replication lag (should be 0)
SELECT 
    slot_name,
    confirmed_flush_lsn,
    pg_current_wal_lsn(),
    (pg_current_wal_lsn() - confirmed_flush_lsn) AS lag_bytes
FROM pg_replication_slots
WHERE slot_type = 'logical';

-- lag_bytes MUST be 0 before proceeding!
```

## Rollback Checklist

- [ ] **Stop all writes** to old master
- [ ] **Verify sync**: Run `python manage_reverse_replication.py verify`
- [ ] **All slots show lag = 0**
- [ ] **Get LSN**: Run `python get_lsn.py replica`
- [ ] **Record LSN**: Copy the recommended LSN value
- [ ] **Update .env**: Set `LSN=<value_from_above>`
- [ ] **Setup new master**: Run `python manage_reverse_replication.py setup_new_master`
- [ ] **Setup new replica**: Run `python manage_reverse_replication.py setup_new_replica`
- [ ] **Verify**: Check both databases with `get_lsn.py`
- [ ] **Test**: Insert test data on new master, verify on new replica
- [ ] **Update app**: Point application to new master

## Troubleshooting

### Issue: "No unused replication origins found"

**Solution:**
```sql
-- On new replica (old master)
-- Check existing origins
SELECT * FROM pg_replication_origin;

-- If needed, create more origins (PostgreSQL creates them automatically)
-- Or drop old unused origins
SELECT pg_replication_origin_drop('pg_<old_oid>');
```

### Issue: Duplicate data after rollback

**Cause:** Wrong LSN (too early)

**Solution:**
```bash
# 1. Stop reverse replication
python manage_subscriptions.py delete  # On new replica

# 2. Identify duplicate data
# Compare row counts, check for duplicate IDs

# 3. Clean up duplicates (CAREFUL!)
# Truncate affected tables or delete duplicates

# 4. Get correct LSN
python get_lsn.py replica  # When fully synced

# 5. Retry with correct LSN
# Update .env with new LSN
python manage_subscriptions.py create
```

### Issue: Missing data after rollback

**Cause:** LSN too late or writes happened during rollback

**Solution:**
```sql
-- Check what LSN was used
SELECT * FROM pg_replication_origin_status;

-- Compare with actual slot LSN
SELECT confirmed_flush_lsn FROM pg_replication_slots;

-- If LSN mismatch, re-advance
SELECT pg_replication_origin_advance('pg_<oid>', '<correct_lsn>');
```

## Key Concepts

### What is LSN?

**LSN (Log Sequence Number)** is a unique identifier for a position in the PostgreSQL Write-Ahead Log (WAL).

- Format: `38E7/403FB58` (hexadecimal)
- Represents a specific point in time
- Monotonically increasing
- Used to track replication progress

### Why LSN Matters for Rollback

When you reverse replication:

1. **Old master has data up to LSN X**
2. **Replica has same data up to LSN X** (when synced)
3. **New changes on replica start after LSN X**
4. **Old master needs to start replication from LSN X** (not from 0!)

If you start from LSN 0 or wrong LSN:
- Old master will receive data it already has → **Duplicates**
- Or miss data that was created → **Data loss**

### Replication Origin

**Replication origin** tracks the LSN position for each subscription:

```sql
-- Each subscription gets an origin like 'pg_148921862'
-- The origin remembers: "I've processed up to LSN X"
-- Next replication starts from X+1
```

This is why advancing the origin to the correct LSN is critical!

## Quick Reference: Environment Variables

```bash
# For ROLLBACK, these roles are REVERSED:

# REPLICATION_DB_HOST = Old replica (becomes NEW MASTER)
# MASTER_DB_HOST = Old master (becomes NEW REPLICA)

# LSN = Get from replica when fully synced
# Use: python get_lsn.py replica
```

## Example: Complete Rollback

```bash
# Starting state:
# - Master: db-master.amazonaws.com (old, unencrypted)
# - Replica: db-replica.amazonaws.com (new, encrypted)

# Goal: Make replica the new master

# 1. Stop writes to old master
# (Use security groups, pg_hba.conf, or application config)

# 2. Verify sync
python manage_reverse_replication.py verify
# Output: ✓ ALL DATABASES ARE FULLY SYNCED

# 3. Get LSN from replica
python get_lsn.py replica
# Output: ✓ RECOMMENDED FOR ROLLBACK: 38E7/403FB58

# 4. Update .env
# LSN=38E7/403FB58
# REPLICATION_DB_HOST=db-replica.amazonaws.com  # New master
# MASTER_DB_HOST=db-master.amazonaws.com        # New replica

# 5. Setup new master (replica)
python manage_reverse_replication.py setup_new_master
# Output: ✓ NEW MASTER SETUP COMPLETE

# 6. Setup new replica (old master)
python manage_reverse_replication.py setup_new_replica
# Output: ✓ REVERSE REPLICATION SETUP COMPLETE

# 7. Verify
python get_lsn.py replica  # Check new master
python get_lsn.py master   # Check new replica
# Both should show: ✓ FULLY SYNCED

# 8. Update application to point to new master
# Update connection string to db-replica.amazonaws.com

# 9. Test
# Insert data on new master, verify it appears on new replica

# Done! Rollback complete with no data loss or duplicates.
```

## Resources

- **Detailed Guide**: [ROLLBACK_GUIDE.md](ROLLBACK_GUIDE.md)
- **Main README**: [README.md](README.md)
- **AWS Blog**: [Encrypt RDS PostgreSQL with Minimal Downtime](https://aws.amazon.com/blogs/database/encrypt-amazon-rds-for-postgresql-and-amazon-aurora-postgresql-database-with-minimal-downtime/)
- **PostgreSQL Docs**: [Logical Replication](https://www.postgresql.org/docs/current/logical-replication.html)
