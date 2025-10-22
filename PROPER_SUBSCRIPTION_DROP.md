# Proper Subscription Drop Procedure

## Overview

When dropping or recreating a PostgreSQL logical replication subscription, it's important to follow the correct sequence to avoid issues with replication slots and connections.

## The Problem with Simple DROP

**Incorrect (Old Way):**
```sql
DROP SUBSCRIPTION subscription_name;
```

This can cause:
- ❌ Errors if subscription is enabled
- ❌ Orphaned replication slots
- ❌ Connection issues to the source database
- ❌ Slot not properly cleaned up on source

## The Correct Procedure

**Correct (New Way):**
```sql
-- Step 1: Disable the subscription
ALTER SUBSCRIPTION subscription_name DISABLE;

-- Step 2: Detach the replication slot
ALTER SUBSCRIPTION subscription_name SET (slot_name = NONE);

-- Step 3: Drop the subscription
DROP SUBSCRIPTION subscription_name;
```

### Why This Order Matters

1. **DISABLE** - Stops the subscription worker process
   - Prevents active connections to source
   - Stops replication activity
   - Releases the replication origin session

2. **SET (slot_name = NONE)** - Detaches the slot from subscription
   - Prevents automatic slot drop on subscription drop
   - Allows manual slot cleanup on source
   - Avoids "slot is active" errors

3. **DROP SUBSCRIPTION** - Removes the subscription
   - Clean removal without side effects
   - No orphaned resources
   - No connection errors

## Implementation in Script

### When Recreating Subscription

The script now uses this sequence when you choose to drop and recreate:

```python
if user_input == 'yes':
    # Step 1: Disable
    logger.info(f"Disabling subscription '{self.publication_name}'...")
    cur.execute(f"ALTER SUBSCRIPTION {self.publication_name} DISABLE")
    
    # Step 2: Detach slot
    logger.info(f"Detaching slot from subscription '{self.publication_name}'...")
    cur.execute(f"ALTER SUBSCRIPTION {self.publication_name} SET (slot_name = NONE)")
    
    # Step 3: Drop
    logger.info(f"Dropping subscription '{self.publication_name}'...")
    cur.execute(f"DROP SUBSCRIPTION {self.publication_name}")
    
    logger.info(f"✓ Dropped existing subscription '{self.publication_name}'")
```

### When Cleaning Up

The `cleanup` action also uses this sequence:

```bash
python rds_encryption_automation.py --config databases.json --action cleanup
```

Output:
```
Disabling subscription 'myapp_prod_encryption_pub'...
Detaching slot from subscription 'myapp_prod_encryption_pub'...
Dropping subscription 'myapp_prod_encryption_pub'...
✓ Dropped subscription: myapp_prod_encryption_pub
```

## Benefits

### ✅ Prevents Errors

**Before:**
```
ERROR:  cannot drop subscription "sub_name" because it is being used by a logical replication worker
```

**After:**
```
✓ Dropped subscription: sub_name
```

### ✅ Clean Slot Management

The replication slot on the source is not automatically dropped, allowing you to:
- Verify the slot state before dropping
- Manually drop the slot when ready
- Avoid race conditions

### ✅ No Orphaned Resources

- No active connections left hanging
- No replication origin sessions stuck
- No worker processes to kill

## Manual Cleanup

If you need to manually clean up a subscription:

```sql
-- On Target Database
ALTER SUBSCRIPTION myapp_prod_encryption_pub DISABLE;
ALTER SUBSCRIPTION myapp_prod_encryption_pub SET (slot_name = NONE);
DROP SUBSCRIPTION myapp_prod_encryption_pub;

-- On Source Database (after dropping subscription)
SELECT pg_drop_replication_slot('myapp_prod_encryption_slot');
```

## Common Scenarios

### Scenario 1: Recreating During Setup

When running `setup-target` and subscription exists:

```
⚠️  SUBSCRIPTION 'myapp_prod_encryption_pub' ALREADY EXISTS
Drop and recreate? (yes/no): yes

INFO - Disabling subscription 'myapp_prod_encryption_pub'...
INFO - Detaching slot from subscription 'myapp_prod_encryption_pub'...
INFO - Dropping subscription 'myapp_prod_encryption_pub'...
INFO - ✓ Dropped existing subscription 'myapp_prod_encryption_pub'
INFO - ✓ Created subscription: myapp_prod_encryption_pub (disabled)
```

### Scenario 2: Full Cleanup After Migration

When running `cleanup` action:

```bash
python rds_encryption_automation.py --config my-databases.json --action cleanup
```

```
================================================================================
CLEANING UP REPLICATION
================================================================================
INFO - Disabling subscription 'myapp_prod_encryption_pub'...
INFO - Detaching slot from subscription 'myapp_prod_encryption_pub'...
INFO - Dropping subscription 'myapp_prod_encryption_pub'...
INFO - ✓ Dropped subscription: myapp_prod_encryption_pub
INFO - ✓ Dropped replication slot: myapp_prod_encryption_slot
INFO - ✓ Dropped publication: myapp_prod_encryption_pub
INFO - ✓ Cleanup completed successfully
```

### Scenario 3: Subscription Already Disabled

If subscription is already disabled, the script handles it gracefully:

```
INFO - Disabling subscription 'myapp_prod_encryption_pub'...
INFO - Detaching slot from subscription 'myapp_prod_encryption_pub'...
INFO - Dropping subscription 'myapp_prod_encryption_pub'...
INFO - ✓ Dropped subscription: myapp_prod_encryption_pub
```

## Troubleshooting

### If Subscription is Stuck

```sql
-- Check subscription state
SELECT subname, subenabled, subslotname 
FROM pg_subscription 
WHERE subname = 'myapp_prod_encryption_pub';

-- If enabled, disable it
ALTER SUBSCRIPTION myapp_prod_encryption_pub DISABLE;

-- Check for active workers
SELECT pid, application_name, state 
FROM pg_stat_activity 
WHERE application_name LIKE '%myapp_prod_encryption_pub%';

-- If workers exist, wait or terminate them
SELECT pg_terminate_backend(pid) 
FROM pg_stat_activity 
WHERE application_name LIKE '%myapp_prod_encryption_pub%';

-- Then proceed with detach and drop
ALTER SUBSCRIPTION myapp_prod_encryption_pub SET (slot_name = NONE);
DROP SUBSCRIPTION myapp_prod_encryption_pub;
```

### If Slot is Orphaned

After dropping subscription, if slot still exists on source:

```sql
-- On source database
SELECT slot_name, active, active_pid 
FROM pg_replication_slots 
WHERE slot_name = 'myapp_prod_encryption_slot';

-- If not active, drop it
SELECT pg_drop_replication_slot('myapp_prod_encryption_slot');
```

## Best Practices

### ✅ Do This

1. Always disable before dropping
2. Always detach slot before dropping
3. Verify slot state on source after dropping
4. Use the script's `cleanup` action for full cleanup

### ❌ Don't Do This

1. Don't use `DROP SUBSCRIPTION ... CASCADE` unless necessary
2. Don't drop subscription while it's enabled
3. Don't forget to clean up the slot on source
4. Don't manually kill worker processes unless necessary

## PostgreSQL Documentation

This procedure follows PostgreSQL best practices:
- [ALTER SUBSCRIPTION](https://www.postgresql.org/docs/current/sql-altersubscription.html)
- [DROP SUBSCRIPTION](https://www.postgresql.org/docs/current/sql-dropsubscription.html)
- [Replication Slot Management](https://www.postgresql.org/docs/current/logicaldecoding-explanation.html)

## Summary

The script now implements the proper 3-step procedure for dropping subscriptions:

1. **DISABLE** - Stop the worker
2. **SET (slot_name = NONE)** - Detach the slot
3. **DROP** - Remove the subscription

This prevents errors, orphaned resources, and connection issues during subscription management.

**All subscription drops are now safe and clean!** ✅
