# Automatic Replication Origin Selection

## Overview

The script now **automatically selects** the best replication origin to advance, eliminating manual selection in most cases. It intelligently chooses based on subscription status and matching criteria.

## How It Works

### Automatic Selection Strategy

When advancing a replication origin, the script follows this priority order:

```
1. MATCHING ORIGIN    → Origin linked to current subscription name
2. INACTIVE ORIGIN    → Origin with disabled subscription
3. SINGLE ORIGIN      → Only one origin exists (use it)
4. ORPHANED ORIGIN    → Origin with no subscription
5. MANUAL SELECTION   → Multiple active origins (ask user)
```

### Selection Logic

```python
# Query origins with their subscription status
SELECT 
    ro.roident AS origin_id,
    ro.roname AS origin_name,
    s.subname AS subscription_name,
    s.subenabled AS is_enabled,
    CASE 
        WHEN s.subenabled THEN 'ACTIVE'
        WHEN s.subname IS NOT NULL THEN 'INACTIVE'
        ELSE 'ORPHANED'
    END AS status
FROM pg_replication_origin ro
LEFT JOIN pg_subscription s 
    ON ro.roname = 'pg_' || s.oid::text
```

Then automatically select based on status.

## Selection Scenarios

### Scenario 1: Matching Subscription ✅ (Best Case)

**Situation**: Origin exists for your subscription name

**Example**:
```
Origin: pg_31288228
Subscription: myapp_encryption_pub
Status: INACTIVE
```

**Action**: Auto-selects this origin
```
✓ Auto-selected origin matching subscription: pg_31288228 (Status: INACTIVE)
```

**Why**: This is the correct origin for your subscription.

---

### Scenario 2: Inactive Origin ✅

**Situation**: Subscription exists but is disabled

**Example**:
```
Origin: pg_31288228
Subscription: old_subscription
Status: INACTIVE (disabled)
```

**Action**: Auto-selects the inactive origin
```
✓ Auto-selected inactive origin: pg_31288228
```

**Why**: Inactive origins are safe to advance (no active worker).

---

### Scenario 3: Single Origin ✅

**Situation**: Only one origin exists

**Example**:
```
Origin: pg_31288228
Subscription: myapp_encryption_pub
Status: ACTIVE
```

**Action**: Uses the only available origin
```
✓ Using only available origin: pg_31288228 (Status: ACTIVE)
```

**Why**: Session-based approach handles active origins safely.

---

### Scenario 4: Orphaned Origin ✅

**Situation**: Origin exists but no subscription

**Example**:
```
Origin: pg_31288228
Subscription: None
Status: ORPHANED
```

**Action**: Auto-selects the orphaned origin
```
✓ Auto-selected orphaned origin: pg_31288228
```

**Why**: Orphaned origins are safe to use or clean up.

---

### Scenario 5: Multiple Active Origins ⚠️ (Manual)

**Situation**: Multiple origins, all active

**Example**:
```
Origin 1: pg_31288228, Subscription: app1_pub, Status: ACTIVE
Origin 2: pg_31288229, Subscription: app2_pub, Status: ACTIVE
```

**Action**: Prompts for manual selection
```
================================================================================
MULTIPLE ACTIVE REPLICATION ORIGINS FOUND
================================================================================
1. OID: 1, Name: pg_31288228
   Subscription: app1_pub, Status: ACTIVE
2. OID: 2, Name: pg_31288229
   Subscription: app2_pub, Status: ACTIVE
================================================================================
Select origin to advance (1-2):
```

**Why**: Can't automatically determine which one to use.

## Benefits

### ✅ No Manual Selection Needed

**Before**:
```
MULTIPLE REPLICATION ORIGINS FOUND
1. OID: 1, Name: pg_31288228
2. OID: 2, Name: pg_31288229
Select origin to advance (1-2): _
```

**After**:
```
✓ Auto-selected origin matching subscription: pg_31288228 (Status: INACTIVE)
Creating session for origin: pg_31288228
✓ Advanced replication origin 'pg_31288228' to LSN 0/20000110
```

### ✅ Intelligent Selection

- Prefers origins matching your subscription
- Avoids active origins when inactive ones exist
- Handles orphaned origins gracefully

### ✅ Safer Operations

- Won't accidentally advance wrong origin
- Clear logging of selection reasoning
- Falls back to manual selection when uncertain

## Example Outputs

### Example 1: Perfect Match

```bash
python rds_encryption_automation.py --config my-databases.json --action setup-target
```

```
INFO - Found 1 replication origin(s)
INFO - ✓ Auto-selected origin matching subscription: pg_31288228 (Status: INACTIVE)
INFO - Creating session for origin: pg_31288228
INFO - Advancing origin to LSN: 0/20000110
INFO - ✓ Advanced replication origin 'pg_31288228' to LSN 0/20000110
```

### Example 2: Multiple Origins, One Inactive

```
INFO - Found 3 replication origin(s)
INFO - ✓ Auto-selected inactive origin: pg_31288229
INFO - Creating session for origin: pg_31288229
INFO - Advancing origin to LSN: 0/20000110
INFO - ✓ Advanced replication origin 'pg_31288229' to LSN 0/20000110
```

### Example 3: Orphaned Origin

```
INFO - Found 2 replication origin(s)
INFO - ✓ Auto-selected orphaned origin: pg_31288230
INFO - Creating session for origin: pg_31288230
INFO - Advancing origin to LSN: 0/20000110
INFO - ✓ Advanced replication origin 'pg_31288230' to LSN 0/20000110
```

## When Manual Selection Happens

Manual selection only occurs when:

1. **Multiple active origins exist** AND
2. **None match your subscription name** AND
3. **No inactive or orphaned origins available**

This is rare in normal operation.

## Understanding the Status

### ACTIVE
- Subscription is enabled
- Worker process may be running
- Origin is in use
- **Script handles this with session-based approach**

### INACTIVE
- Subscription exists but is disabled
- No worker process
- Origin is free
- **Preferred for advancement**

### ORPHANED
- No subscription associated
- Leftover from previous operations
- Safe to use or clean up
- **Can be used for advancement**

## Troubleshooting

### If Wrong Origin is Selected

The script logs its selection reasoning. Check the logs:

```
INFO - Found 2 replication origin(s)
INFO - ✓ Auto-selected origin matching subscription: pg_31288228 (Status: INACTIVE)
```

If this is wrong, you can:

1. **Check subscription names** in your config
2. **Manually disable** other subscriptions first
3. **Clean up orphaned origins** before running

### If You Want Manual Control

Use the `check-origin-usage` action first to see all origins:

```bash
# Check origins first
python rds_encryption_automation.py --config my-databases.json --action check-origin-usage

# Then run setup-target
# If multiple active origins exist, you'll be prompted
python rds_encryption_automation.py --config my-databases.json --action setup-target
```

### If Selection Fails

```
ERROR - No replication origin found
```

This means no origins exist yet. This is normal if:
- Subscription hasn't been created yet
- You're running `setup-target` for the first time

The subscription creation step will create the origin.

## Technical Details

### Query Used

```sql
SELECT 
    ro.roident AS origin_id,
    ro.roname AS origin_name,
    s.subname AS subscription_name,
    s.subenabled AS is_enabled,
    CASE 
        WHEN s.subenabled THEN 'ACTIVE'
        WHEN s.subname IS NOT NULL THEN 'INACTIVE'
        ELSE 'ORPHANED'
    END AS status
FROM pg_replication_origin ro
LEFT JOIN pg_subscription s 
    ON ro.roname = 'pg_' || s.oid::text
ORDER BY ro.roident
```

### Selection Priority

```python
if matching_origins:
    # 1. Prefer origin matching our subscription
    origin_name = matching_origins[0][1]
elif inactive_origins:
    # 2. Use an inactive origin
    origin_name = inactive_origins[0][1]
elif len(origins) == 1:
    # 3. Only one origin, use it
    origin_name = origins[0][1]
elif orphaned_origins:
    # 4. Use an orphaned origin
    origin_name = orphaned_origins[0][1]
else:
    # 5. Ask user to select
    prompt_user_for_selection()
```

## Comparison: Before vs After

### Before (Manual Selection)

```
INFO - Replication origins: [(1, 'pg_31288228'), (2, 'pg_31288229')]

MULTIPLE REPLICATION ORIGINS FOUND
1. OID: 1, Name: pg_31288228
2. OID: 2, Name: pg_31288229
Select origin to advance (1-2): _  ← User must choose
```

### After (Automatic Selection)

```
INFO - Found 2 replication origin(s)
INFO - ✓ Auto-selected origin matching subscription: pg_31288228 (Status: INACTIVE)
INFO - Creating session for origin: pg_31288228
INFO - ✓ Advanced replication origin 'pg_31288228' to LSN 0/20000110
```

## Summary

The script now:
- ✅ **Automatically detects** origin status (ACTIVE/INACTIVE/ORPHANED)
- ✅ **Intelligently selects** the best origin to advance
- ✅ **Matches** origins to subscription names
- ✅ **Prefers** inactive/orphaned origins over active ones
- ✅ **Falls back** to manual selection only when necessary
- ✅ **Logs** selection reasoning for transparency

**Most operations now require zero manual intervention!** 🎉
