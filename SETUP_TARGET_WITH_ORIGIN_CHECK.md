# Setup Target with Integrated Origin Check

## Overview

The `setup-target` action now **automatically includes** a replication origin usage check before advancing the origin. This helps you understand what's happening and confirm before proceeding.

## What Happens During setup-target

### Step-by-Step Flow

1. **Create Subscription** (or skip if exists)
2. **Get LSN** (auto-fetch or manual entry)
3. **🆕 Check Replication Origin Usage** ← NEW!
4. **🆕 Confirm Before Proceeding** ← NEW!
5. **Advance Replication Origin** (session-based)
6. **Enable Subscription**
7. **Verify Replication**

## Example Output

```bash
python rds_encryption_automation.py --config my-databases.json --action setup-target
```

### You'll See:

```
================================================================================
SETTING UP TARGET DATABASE: encrypted-db.xxxxx.rds.amazonaws.com/myapp_production
================================================================================

✓ Created subscription: myapp_prod_encryption_pub (disabled)
✓ Auto-fetched LSN from source: 0/20000110

================================================================================
CHECKING REPLICATION ORIGIN USAGE
================================================================================

================================================================================
REPLICATION ORIGIN USAGE REPORT
================================================================================

1. ALL REPLICATION ORIGINS
--------------------------------------------------------------------------------
  OID: 1, Name: pg_31288228
    Remote LSN: 0/20000110, Local LSN: 0/20000110

2. SUBSCRIPTION WORKERS (These use replication origins)
--------------------------------------------------------------------------------
  Subscription: myapp_prod_encryption_pub [DISABLED]
    Slot: myapp_prod_encryption_slot
    Worker: Not active

3. ORIGIN-TO-SUBSCRIPTION MAPPING
--------------------------------------------------------------------------------
  Origin 1 (pg_31288228)
    → Subscription: myapp_prod_encryption_pub (OID: 31288228)
    → Status: INACTIVE (disabled)

4. ACTIVE REPLICATION-RELATED PROCESSES
--------------------------------------------------------------------------------
No active replication processes found

================================================================================
INTERPRETATION:
================================================================================
• If 'Status' shows 'ACTIVE (enabled)', the origin is in use
• Active subscription workers hold the origin session
• To advance origin, use session-based approach (already in script)
• Or temporarily: ALTER SUBSCRIPTION <name> DISABLE;
================================================================================

================================================================================
⚠️  ABOUT TO ADVANCE REPLICATION ORIGIN
================================================================================
LSN to advance to: 0/20000110
The script will use session-based approach to handle active origins.
================================================================================
Proceed with advancing replication origin? (yes/no): yes

INFO - Creating session for origin: pg_31288228
INFO - Advancing origin to LSN: 0/20000110
INFO - ✓ Advanced replication origin 'pg_31288228' to LSN 0/20000110
INFO - ✓ Enabled subscription: myapp_prod_encryption_pub
INFO - ✓ Target database setup completed successfully
```

## Benefits

### 1. **Visibility**
You can see exactly which origins exist and their status before advancing.

### 2. **Informed Decision**
The report shows:
- Whether the origin is active or inactive
- Which subscription owns it
- If there are any worker processes

### 3. **Safety**
You get a confirmation prompt before advancing, preventing accidental changes.

### 4. **Debugging**
If something goes wrong, you have detailed information about the state.

## Usage Options

### Option 1: Interactive Mode (Default)
```bash
python rds_encryption_automation.py --config my-databases.json --action setup-target
```
- Shows origin usage report
- Prompts for confirmation
- Best for manual operations

### Option 2: Skip Origin Check (Automation)
```bash
python rds_encryption_automation.py --config my-databases.json --action setup-target --skip-origin-check
```
- Skips the origin usage report
- Skips confirmation prompt
- Proceeds directly to advancing
- Best for CI/CD pipelines

### Option 3: With Manual LSN
```bash
python rds_encryption_automation.py --config my-databases.json --action setup-target --lsn 0/20000110
```
- Uses provided LSN
- Still shows origin check (unless --skip-origin-check)

### Option 4: Fully Automated
```bash
python rds_encryption_automation.py --config my-databases.json --action setup-target --lsn 0/20000110 --skip-origin-check
```
- No prompts
- No origin check
- Fully automated
- Best for scripts

## Understanding the Report

### Section 1: All Replication Origins
Lists every origin with its ID and LSN positions.

**What to look for:**
- How many origins exist
- Their current LSN positions

### Section 2: Subscription Workers
Shows subscriptions and their worker processes.

**What to look for:**
- **[ENABLED]** = Worker is active, origin is in use
- **[DISABLED]** = No worker, origin is free
- **Worker PID** = Process ID if active

### Section 3: Origin-to-Subscription Mapping
Maps origins to their subscriptions.

**What to look for:**
- **ACTIVE (enabled)** = Origin is being used ⚠️
- **INACTIVE (disabled)** = Origin is free ✅
- **ORPHANED** = No subscription, can be cleaned up

### Section 4: Active Processes
Lists all replication-related processes.

**What to look for:**
- Logical replication workers
- Their state (idle, active, etc.)
- When they started

## When to Skip the Origin Check

### ✅ Skip When:
- Running in CI/CD pipeline
- Fully automated deployment
- You've already verified the state
- Running multiple databases in batch

### ❌ Don't Skip When:
- First time running the script
- Troubleshooting issues
- Production database migration
- Unsure about current state

## Troubleshooting

### If Origin Shows "ACTIVE (enabled)"
**Don't worry!** The script uses session-based approach to handle this.

Just answer "yes" to proceed. The script will:
1. Create a session for the origin
2. Advance it within that session
3. Reset the session

### If You See Multiple Origins
The script will prompt you to select which one to advance.

Choose the one that matches your subscription (shown in Section 3).

### If You Want to Cancel
Answer "no" to the confirmation prompt.

The script will exit safely without making changes.

## Comparison: Before vs After

### Before (Old Behavior)
```
✓ Created subscription
✓ Got LSN: 0/20000110
ERROR - replication origin with OID 1 is already active for PID 17013
```
❌ No visibility into what's happening

### After (New Behavior)
```
✓ Created subscription
✓ Got LSN: 0/20000110

REPLICATION ORIGIN USAGE REPORT
  Origin 1 (pg_31288228)
    → Subscription: myapp_prod_encryption_pub
    → Status: ACTIVE (enabled)

Proceed with advancing? (yes/no): yes
✓ Advanced replication origin successfully
```
✅ Full visibility and control

## Related Commands

### Before setup-target
```bash
# Check origins first
python rds_encryption_automation.py --config my-databases.json --action list-origins

# Or get detailed usage report
python rds_encryption_automation.py --config my-databases.json --action check-origin-usage
```

### During setup-target
The origin check is now automatic (unless you use `--skip-origin-check`)

### After setup-target
```bash
# Verify replication is working
python rds_encryption_automation.py --config my-databases.json --action verify
```

## Summary

The integrated origin check provides:
- 🔍 **Visibility** - See what's happening
- 🛡️ **Safety** - Confirm before proceeding
- 🐛 **Debugging** - Detailed state information
- ⚡ **Flexibility** - Skip for automation

**Default behavior**: Shows check + requires confirmation
**Automation mode**: Use `--skip-origin-check` flag

This enhancement makes the migration process more transparent and safer, especially for production databases.
