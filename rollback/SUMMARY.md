# Summary: Rollback with No Data Discrepancy

## Your Questions Answered

### 1. How to rollback with no discrepancy data from replica to master?

**Answer:** Use **reverse replication** with the correct LSN.

**Key Steps:**
1. **Stop writes** to old master
2. **Wait for full sync** (replication lag = 0)
3. **Record LSN** from replica: `SELECT pg_current_wal_lsn()`
4. **Create publications** on replica (becomes new master)
5. **Create subscriptions** on old master (becomes new replica) with LSN from step 3
6. **Advance replication origin** to the recorded LSN before enabling subscription

**Automation:**
```bash
python manage_reverse_replication.py verify
python get_lsn.py replica
# Update .env with LSN
python manage_reverse_replication.py setup_new_master
python manage_reverse_replication.py setup_new_replica
```

### 2. How to get right LSN to prevent duplicates?

**Answer:** Get LSN from **replica** when it's **fully synced** with master.

**Best Method:**
```bash
# 1. Verify sync first
python manage_reverse_replication.py verify
# Must show: ✓ ALL DATABASES ARE FULLY SYNCED

# 2. Get LSN from replica
python get_lsn.py replica
# Look for: ✓ RECOMMENDED FOR ROLLBACK: 38E7/403FB58

# 3. Use this LSN in .env
LSN=38E7/403FB58
```

**Why This Works:**
- When replica is synced, it has processed all data up to LSN X
- Old master also has all data up to LSN X
- Starting replication from LSN X means old master only gets NEW changes
- No duplicates because it skips data it already has

**Alternative Methods:**
```sql
-- Method 1: Current WAL LSN on replica (BEST)
SELECT pg_current_wal_lsn();

-- Method 2: Confirmed flush LSN from master's replication slot
SELECT confirmed_flush_lsn 
FROM pg_replication_slots 
WHERE slot_name = 'your_slot';

-- Method 3: Remote LSN from replica's replication origin
SELECT remote_lsn 
FROM pg_replication_origin_status ros
JOIN pg_subscription s ON ...;
```

### 3. Goal: Using old instance, replica creates publication, master creates subscription - how to get the right LSN?

**Answer:** Follow this exact workflow:

```
┌─────────────────────────────────────────────────────────────┐
│ STEP 1: PREPARATION                                         │
├─────────────────────────────────────────────────────────────┤
│ On OLD MASTER:                                              │
│   - Stop all write operations                               │
│   - Block connections (except from replica)                 │
│                                                             │
│ Verify:                                                     │
│   python manage_reverse_replication.py verify               │
│   → Must show lag = 0 for all databases                     │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ STEP 2: GET THE RIGHT LSN                                   │
├─────────────────────────────────────────────────────────────┤
│ On REPLICA (will become new master):                        │
│   python get_lsn.py replica                                 │
│                                                             │
│ Output will show:                                           │
│   1. CURRENT WAL LSN: 38E7/403FB58  ← USE THIS!            │
│   2. Replication slots (shows what master confirmed)        │
│   3. Replication origins (shows what replica received)      │
│   4. Replication lag (must be 0)                            │
│                                                             │
│ Copy the "RECOMMENDED FOR ROLLBACK" LSN value               │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ STEP 3: UPDATE CONFIGURATION                                │
├─────────────────────────────────────────────────────────────┤
│ Edit .env file:                                             │
│   LSN=38E7/403FB58  # From step 2                           │
│                                                             │
│ Note: REPLICATION_DB_HOST should point to old replica       │
│       MASTER_DB_HOST should point to old master             │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ STEP 4: SETUP REPLICA AS NEW MASTER                         │
├─────────────────────────────────────────────────────────────┤
│ python manage_reverse_replication.py setup_new_master       │
│                                                             │
│ This will:                                                  │
│   1. Clean up old subscriptions on replica                  │
│   2. Create publications: {db}_pub_reverse                  │
│   3. Create replication slots: {db}_slot_reverse            │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ STEP 5: SETUP OLD MASTER AS NEW REPLICA                     │
├─────────────────────────────────────────────────────────────┤
│ python manage_reverse_replication.py setup_new_replica      │
│                                                             │
│ This will:                                                  │
│   1. Create subscriptions: {db}_sub_reverse                 │
│   2. Find unused replication origins                        │
│   3. Advance origin to LSN from step 2  ← CRITICAL!         │
│   4. Enable subscriptions                                   │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ STEP 6: VERIFY REVERSE REPLICATION                          │
├─────────────────────────────────────────────────────────────┤
│ Check new master:                                           │
│   python get_lsn.py replica                                 │
│                                                             │
│ Check new replica:                                          │
│   python get_lsn.py master                                  │
│                                                             │
│ Both should show:                                           │
│   ✓ FULLY SYNCED (lag = 0)                                  │
└─────────────────────────────────────────────────────────────┘
```

## Why This Prevents Duplicates

### The Problem Without Correct LSN

```
Old Master has data:  [A, B, C, D, E] at LSN 100
Replica has data:     [A, B, C, D, E] at LSN 100

If you create subscription without LSN or wrong LSN:
Old Master receives:  [A, B, C, D, E] again → DUPLICATES!
Result:              [A, B, C, D, E, A, B, C, D, E] ❌
```

### The Solution With Correct LSN

```
Old Master has data:  [A, B, C, D, E] at LSN 100
Replica has data:     [A, B, C, D, E] at LSN 100

Create subscription with LSN = 100:
Replication origin advanced to LSN 100
Old Master receives:  [F, G, H] (only NEW data after LSN 100)
Result:              [A, B, C, D, E, F, G, H] ✓
```

## Critical Settings for No Duplicates

When creating reverse subscription, these settings are CRITICAL:

```sql
CREATE SUBSCRIPTION {db}_sub_reverse
CONNECTION '...'
PUBLICATION {db}_pub_reverse
WITH (
    copy_data = false,        -- ✓ MUST be false (don't copy existing data)
    create_slot = false,      -- ✓ Slot already created on new master
    enabled = false,          -- ✓ Start disabled
    synchronous_commit = false,
    connect = true,
    slot_name = '{db}_slot_reverse'
);

-- THEN advance replication origin BEFORE enabling
SELECT pg_replication_origin_advance('pg_148921862', '38E7/403FB58');

-- THEN enable
ALTER SUBSCRIPTION {db}_sub_reverse ENABLE;
```

## Files Created for You

### 1. ROLLBACK_GUIDE.md
**Comprehensive 400+ line guide** covering:
- Complete step-by-step rollback process
- Multiple methods to get LSN
- SQL queries for manual verification
- Troubleshooting common issues
- Rollback checklist

### 2. get_lsn.py
**Helper script** to get LSN information:
```bash
python get_lsn.py replica  # Get LSN from replica
python get_lsn.py master   # Get LSN from master
```

Shows:
- Current WAL LSN (recommended for rollback)
- Replication slot LSN
- Replication origin LSN
- Replication lag status

### 3. manage_reverse_replication.py
**Automation script** for rollback:
```bash
python manage_reverse_replication.py verify           # Check sync
python manage_reverse_replication.py setup_new_master # Setup replica as master
python manage_reverse_replication.py setup_new_replica # Setup master as replica
```

### 4. ROLLBACK_QUICK_REFERENCE.md
**Quick reference** with:
- Visual diagrams
- Command cheat sheet
- Common mistakes to avoid
- Troubleshooting guide

### 5. Updated README.md
Added sections for:
- Rollback features
- LSN management
- Quick start guide
- Scripts overview

## Quick Start (TL;DR)

```bash
# 1. Verify sync
python manage_reverse_replication.py verify

# 2. Get LSN
python get_lsn.py replica
# Copy the LSN value shown

# 3. Update .env
# LSN=<value_from_step_2>

# 4. Setup new master (old replica)
python manage_reverse_replication.py setup_new_master

# 5. Setup new replica (old master)
python manage_reverse_replication.py setup_new_replica

# 6. Verify
python get_lsn.py replica
python get_lsn.py master
```

## Key Takeaways

### ✅ DO

1. **Stop writes** to old master before getting LSN
2. **Verify sync** (lag = 0) before recording LSN
3. **Get LSN from replica** when fully synced
4. **Use `copy_data = false`** in subscription
5. **Advance replication origin** to recorded LSN
6. **Enable subscription** only after advancing origin

### ❌ DON'T

1. Don't use LSN from before replica was synced
2. Don't enable subscription before advancing origin
3. Don't use `copy_data = true`
4. Don't guess the LSN value
5. Don't skip verification steps

## References

- **AWS Blog**: [Encrypt RDS PostgreSQL with Minimal Downtime](https://aws.amazon.com/blogs/database/encrypt-amazon-rds-for-postgresql-and-amazon-aurora-postgresql-database-with-minimal-downtime/)
- **PostgreSQL Docs**: [Logical Replication](https://www.postgresql.org/docs/current/logical-replication.html)
- **pg_replication_origin_advance**: [PostgreSQL Admin Functions](https://www.postgresql.org/docs/current/functions-admin.html)

## Support

For detailed instructions, see:
- **ROLLBACK_GUIDE.md** - Complete rollback guide
- **ROLLBACK_QUICK_REFERENCE.md** - Quick reference and cheat sheet
- **README.md** - Main documentation
