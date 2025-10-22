# Replication Slot Name Sanitization

## Problem

Replication slot names with special characters caused errors:

```
ERROR - Error creating replication slot: replication slot name "airbyte-new_slot" contains invalid character
```

## Root Cause

PostgreSQL replication slot names have **stricter rules** than regular identifiers:

### Slot Name Rules

✅ **Allowed**:
- Lowercase letters: `a-z`
- Numbers: `0-9`
- Underscore: `_`

❌ **Not Allowed**:
- Uppercase letters: `A-Z`
- Hyphens: `-`
- Dots: `.`
- Any other special characters
- Cannot start with a number
- Maximum 63 characters

### Why Stricter?

Unlike publications/subscriptions (which can be quoted), replication slot names:
- Are used in file system paths
- Cannot be quoted in `pg_create_logical_replication_slot()`
- Must follow strict naming conventions

## Solution

Implemented automatic slot name sanitization with the `_sanitize_slot_name()` method:

```python
@staticmethod
def _sanitize_slot_name(slot_name: str) -> str:
    """
    Sanitize a replication slot name.
    
    Rules:
    - Convert to lowercase
    - Replace invalid characters with underscores
    - Ensure doesn't start with a number
    - Truncate to 63 characters
    """
    import re
    
    # Convert to lowercase
    sanitized = slot_name.lower()
    
    # Replace invalid characters with underscores
    sanitized = re.sub(r'[^a-z0-9_]', '_', sanitized)
    
    # Ensure it doesn't start with a number
    if sanitized and sanitized[0].isdigit():
        sanitized = f"slot_{sanitized}"
    
    # Ensure it's not empty
    if not sanitized:
        sanitized = "replication_slot"
    
    # Truncate to 63 characters
    if len(sanitized) > 63:
        sanitized = sanitized[:63]
    
    return sanitized
```

## Examples

### Example 1: Hyphen in Name

**Input**: `airbyte-new_slot`
**Output**: `airbyte_new_slot`

```
INFO - Sanitized slot name: 'airbyte-new_slot' → 'airbyte_new_slot'
```

### Example 2: Uppercase Letters

**Input**: `MySlot-Production`
**Output**: `myslot_production`

```
INFO - Sanitized slot name: 'MySlot-Production' → 'myslot_production'
```

### Example 3: Multiple Special Characters

**Input**: `app.prod-v2.slot`
**Output**: `app_prod_v2_slot`

```
INFO - Sanitized slot name: 'app.prod-v2.slot' → 'app_prod_v2_slot'
```

### Example 4: Starts with Number

**Input**: `123_slot`
**Output**: `slot_123_slot`

```
INFO - Sanitized slot name: '123_slot' → 'slot_123_slot'
```

### Example 5: Very Long Name

**Input**: `this_is_a_very_long_replication_slot_name_that_exceeds_the_limit_of_63_characters`
**Output**: `this_is_a_very_long_replication_slot_name_that_exceeds_the_l`

```
INFO - Sanitized slot name: 'this_is_a_very_long...' → 'this_is_a_very_long_replication_slot_name_that_exceeds_the_l'
```

## When Sanitization Happens

### Auto-Generated Slot Names

When you don't specify a `slot_name` in config:

```json
{
  "database": "airbyte-new"
}
```

**Generated**: `airbyte_new_encryption_slot` (already sanitized)

### Custom Slot Names

When you provide a custom `slot_name`:

```json
{
  "database": "mydb",
  "slot_name": "airbyte-new_slot"
}
```

**Sanitized**: `airbyte_new_slot`

**Log Output**:
```
INFO - Sanitized slot name: 'airbyte-new_slot' → 'airbyte_new_slot'
```

## Configuration Examples

### Before (Would Fail)

```json
{
  "databases": [
    {
      "database": "airbyte-new",
      "slot_name": "airbyte-new_slot",
      "source": { ... },
      "target": { ... }
    }
  ]
}
```

**Error**:
```
ERROR - Error creating replication slot: replication slot name "airbyte-new_slot" contains invalid character
```

### After (Works)

Same config, but slot name is automatically sanitized:

```json
{
  "databases": [
    {
      "database": "airbyte-new",
      "slot_name": "airbyte-new_slot",
      "source": { ... },
      "target": { ... }
    }
  ]
}
```

**Output**:
```
INFO - Sanitized slot name: 'airbyte-new_slot' → 'airbyte_new_slot'
INFO - ✓ Created replication slot: airbyte_new_slot
```

## Comparison: Publications vs Slots

### Publications/Subscriptions

- Can contain special characters (with quoting)
- Case-sensitive
- Example: `"MyApp-Production_pub"`

### Replication Slots

- **Cannot** contain special characters (even with quoting)
- Must be lowercase
- Example: `myapp_production_slot`

## Best Practices

### ✅ Recommended Slot Names

```json
"slot_name": "myapp_encryption_slot"
"slot_name": "production_slot"
"slot_name": "db_replication_slot"
```

### ⚠️ Names That Need Sanitization

```json
"slot_name": "MyApp-Slot"           → myapp_slot
"slot_name": "app.production"       → app_production
"slot_name": "replication-slot-v2"  → replication_slot_v2
```

### ❌ Avoid These Patterns

```json
"slot_name": "123slot"              → slot_123slot (adds prefix)
"slot_name": ""                     → replication_slot (default)
"slot_name": "UPPERCASE"            → uppercase (lowercased)
```

## Verification

After running the script, check the slot name:

```sql
-- On source database
SELECT slot_name, slot_type, active 
FROM pg_replication_slots 
WHERE slot_name LIKE '%encryption%';
```

**Expected**:
```
     slot_name          | slot_type | active
------------------------+-----------+--------
 airbyte_new_encryption_slot | logical   | t
```

## Troubleshooting

### If Slot Creation Still Fails

1. **Check the log** for sanitization message:
   ```
   INFO - Sanitized slot name: 'original' → 'sanitized'
   ```

2. **Verify** the sanitized name follows rules:
   - Only `a-z`, `0-9`, `_`
   - Doesn't start with number
   - Max 63 characters

3. **Test manually**:
   ```sql
   SELECT pg_create_logical_replication_slot('test_slot_name', 'pgoutput');
   ```

### If You Have Existing Slots with Invalid Names

This shouldn't happen, but if you somehow have an existing slot with an invalid name, you'll need to:

1. **Drop the old slot** (if possible):
   ```sql
   SELECT pg_drop_replication_slot('old-slot-name');
   ```

2. **Let the script create** a new one with sanitized name

### If Sanitized Name Conflicts

If the sanitized name conflicts with an existing slot:

```
ERROR - replication slot "airbyte_new_slot" already exists
```

**Solution**: Use a different custom name:
```json
"slot_name": "airbyte_new_v2_slot"
```

## Technical Details

### Sanitization Algorithm

1. **Lowercase**: `MySlot` → `myslot`
2. **Replace invalid chars**: `my-slot.v2` → `my_slot_v2`
3. **Fix numeric start**: `123slot` → `slot_123slot`
4. **Handle empty**: `` → `replication_slot`
5. **Truncate**: `very_long_name...` → `very_long_name...` (63 chars)

### Regex Pattern

```python
re.sub(r'[^a-z0-9_]', '_', sanitized)
```

Replaces anything that's **not** `a-z`, `0-9`, or `_` with underscore.

## Files Modified

**`rds_encryption_automation.py`**:
- Lines 52-58: Slot name sanitization in `__init__`
- Lines 60-97: New `_sanitize_slot_name()` method

## Summary

The script now:
- ✅ **Automatically sanitizes** all slot names
- ✅ **Follows PostgreSQL rules** strictly
- ✅ **Logs changes** for transparency
- ✅ **Handles edge cases** (numbers, empty, long names)
- ✅ **Works with custom names** from config

**Your slot names will always be valid!** 🎉

## Examples in Action

### Example: Your Case

**Config**:
```json
{
  "database": "airbyte-new",
  "slot_name": "airbyte-new_slot"
}
```

**Script Output**:
```
INFO - Sanitized slot name: 'airbyte-new_slot' → 'airbyte_new_slot'
INFO - Creating replication slot 'airbyte_new_slot' on source database...
INFO - ✓ Created replication slot: airbyte_new_slot
```

**Result**: Slot created successfully with sanitized name! ✅
