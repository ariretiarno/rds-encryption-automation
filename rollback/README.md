# Rollback / Reverse Replication

This folder contains all tools and documentation for performing a **rollback** (reverse replication) where the replica becomes the new master and the old master becomes the new replica.

## 📚 Documentation

### [SUMMARY.md](SUMMARY.md) - Start Here!
Quick answers to your questions:
- How to rollback with no data discrepancy?
- How to get the right LSN to prevent duplicates?
- Complete workflow for reverse replication

### [ROLLBACK_GUIDE.md](ROLLBACK_GUIDE.md) - Comprehensive Guide
Detailed 400+ line guide covering:
- Step-by-step rollback process
- Multiple methods to get LSN
- SQL queries for manual verification
- Troubleshooting common issues
- Complete rollback checklist

### [ROLLBACK_QUICK_REFERENCE.md](ROLLBACK_QUICK_REFERENCE.md) - Cheat Sheet
Quick reference with:
- Visual diagrams
- Command cheat sheet
- Common mistakes to avoid
- Troubleshooting guide

## 🛠️ Scripts

### [get_lsn.py](get_lsn.py) - Get LSN Information
Get the correct LSN for rollback to prevent duplicates.

**Usage:**
```bash
# Get LSN from replica (use this for rollback!)
python rollback/get_lsn.py replica

# Get LSN from master
python rollback/get_lsn.py master
```

**Output:**
- Current WAL LSN (recommended for rollback)
- Replication slot LSN and lag
- Replication origin status
- Sync verification

### [manage_reverse_replication.py](manage_reverse_replication.py) - Automate Rollback
Automate the reverse replication setup.

**Usage:**
```bash
# 1. Verify replication is synced
python rollback/manage_reverse_replication.py verify

# 2. Setup new master (old replica)
python rollback/manage_reverse_replication.py setup_new_master

# 3. Setup new replica (old master)
python rollback/manage_reverse_replication.py setup_new_replica
```

## 🚀 Quick Start

### Complete Rollback Workflow

```bash
# Step 1: Verify replication is fully synced
python rollback/manage_reverse_replication.py verify
# Must show: ✓ ALL DATABASES ARE FULLY SYNCED

# Step 2: Get the correct LSN from replica
python rollback/get_lsn.py replica
# Look for: ✓ RECOMMENDED FOR ROLLBACK: 38E7/403FB58

# Step 3: Update .env with the LSN
# Edit .env and set: LSN=38E7/403FB58

# Step 4: Setup replica as new master
python rollback/manage_reverse_replication.py setup_new_master

# Step 5: Setup old master as new replica
python rollback/manage_reverse_replication.py setup_new_replica

# Step 6: Verify reverse replication is working
python rollback/get_lsn.py replica  # Check new master
python rollback/get_lsn.py master   # Check new replica
```

## ⚠️ Critical Concepts

### Why LSN Matters

The **LSN (Log Sequence Number)** is critical for preventing data duplicates:

```
Without correct LSN:
Old Master: [A, B, C, D, E]
Receives:   [A, B, C, D, E] again → DUPLICATES! ❌

With correct LSN:
Old Master: [A, B, C, D, E] at LSN 100
Receives:   [F, G, H] (only new data after LSN 100) → No duplicates! ✓
```

### Getting the Right LSN

**Best Practice:**
1. Stop all writes to old master
2. Wait for replication to sync (lag = 0)
3. Get LSN from replica: `python rollback/get_lsn.py replica`
4. Use this LSN when creating reverse subscription

## 📋 Prerequisites

Before running rollback scripts:

1. **Environment configured** - `.env` file with database credentials
2. **Replication synced** - All databases must have lag = 0
3. **Writes stopped** - No writes to old master during rollback
4. **LSN recorded** - Get LSN from replica when fully synced

## 🔍 Troubleshooting

### Issue: Duplicate Data After Rollback

**Cause:** Wrong LSN (too early)

**Solution:**
1. Drop reverse subscription
2. Clean up duplicates
3. Get correct LSN when replica is synced
4. Retry with correct LSN

### Issue: Missing Data After Rollback

**Cause:** LSN too late or writes during rollback

**Solution:**
1. Check LSN from replication origin status
2. Compare with actual slot LSN
3. Re-advance replication origin if needed

### Issue: "No unused replication origins found"

**Solution:**
```sql
-- Check existing origins
SELECT * FROM pg_replication_origin;

-- Drop old unused origins if needed
SELECT pg_replication_origin_drop('pg_<old_oid>');
```

## 📖 File Descriptions

| File | Purpose | When to Use |
|------|---------|-------------|
| `SUMMARY.md` | Quick answers and overview | Start here - answers your questions |
| `ROLLBACK_GUIDE.md` | Complete guide | Need detailed step-by-step instructions |
| `ROLLBACK_QUICK_REFERENCE.md` | Cheat sheet | Need quick command reference |
| `get_lsn.py` | Get LSN script | Before and after rollback |
| `manage_reverse_replication.py` | Automation script | Execute the rollback |

## 🎯 Key Takeaways

### ✅ DO
- Stop writes to old master before getting LSN
- Verify sync (lag = 0) before recording LSN
- Get LSN from replica when fully synced
- Use `copy_data = false` in subscription
- Advance replication origin to recorded LSN

### ❌ DON'T
- Don't use LSN from before replica was synced
- Don't enable subscription before advancing origin
- Don't use `copy_data = true`
- Don't guess the LSN value
- Don't skip verification steps

## 🔗 Related Documentation

- **Main README**: [../README.md](../README.md)
- **Forward Replication Flow**: [../FLOW.md](../FLOW.md)
- **AWS Blog**: [Encrypt RDS PostgreSQL with Minimal Downtime](https://aws.amazon.com/blogs/database/encrypt-amazon-rds-for-postgresql-and-amazon-aurora-postgresql-database-with-minimal-downtime/)

## 💡 Support

For questions or issues:
1. Check [SUMMARY.md](SUMMARY.md) for quick answers
2. Review [ROLLBACK_GUIDE.md](ROLLBACK_GUIDE.md) for detailed instructions
3. Use [ROLLBACK_QUICK_REFERENCE.md](ROLLBACK_QUICK_REFERENCE.md) for troubleshooting
