# Fix: Support for Database Names with Special Characters

## Problem

Database names containing special characters like `-` (hyphen) or `.` (dot) caused SQL syntax errors:

```
ERROR - Error creating publication: syntax error at or near "-"
LINE 1: CREATE PUBLICATION recon-engine_pub FOR ALL TABLES
                                  ^
```

## Root Cause

PostgreSQL identifiers (publication names, subscription names, slot names) cannot contain special characters like `-` or `.` unless they are properly quoted with double quotes.

### Example of the Issue

If database name is `recon-engine`:
- ❌ `CREATE PUBLICATION recon-engine_pub` → Syntax error
- ✅ `CREATE PUBLICATION "recon-engine_pub"` → Works, but complex
- ✅ `CREATE PUBLICATION recon_engine_pub` → Works, simpler

## Solution

Implemented a two-part fix:

### 1. Sanitize Database Names

Replace special characters with underscores when generating publication/slot names:

```python
# Before
self.publication_name = f"{self.db_name}_encryption_pub"
# If db_name = "recon-engine", creates "recon-engine_encryption_pub" ❌

# After
sanitized_db_name = self.db_name.replace('-', '_').replace('.', '_')
self.publication_name = f"{sanitized_db_name}_encryption_pub"
# If db_name = "recon-engine", creates "recon_engine_encryption_pub" ✅
```

### 2. Quote All Identifiers in SQL

Added a helper method to properly quote identifiers:

```python
@staticmethod
def _quote_identifier(identifier: str) -> str:
    """Properly quote a PostgreSQL identifier."""
    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'
```

Then use it in all SQL statements:

```python
# Before
cur.execute(f"CREATE PUBLICATION {self.publication_name} FOR ALL TABLES")

# After
cur.execute(f"CREATE PUBLICATION {self._quote_identifier(self.publication_name)} FOR ALL TABLES")
```

## Supported Database Name Formats

The script now handles all these database name formats:

✅ `myapp` - Simple name
✅ `my-app` - With hyphen
✅ `my.app` - With dot
✅ `my-app.production` - Multiple special chars
✅ `recon-engine` - Your case
✅ `app_name` - With underscore (already valid)

## How It Works

### Example: Database name `recon-engine`

1. **Sanitization**:
   ```
   Database name: recon-engine
   Sanitized:     recon_engine
   Publication:   recon_engine_encryption_pub
   Slot:          recon_engine_encryption_slot
   ```

2. **SQL Generation**:
   ```sql
   CREATE PUBLICATION "recon_engine_encryption_pub" FOR ALL TABLES
   CREATE SUBSCRIPTION "recon_engine_encryption_pub" ...
   ALTER SUBSCRIPTION "recon_engine_encryption_pub" ENABLE
   ```

## What Changed

### Files Modified

**`rds_encryption_automation.py`**:

1. **Added sanitization in `__init__`** (lines 46-51):
   ```python
   sanitized_db_name = self.db_name.replace('-', '_').replace('.', '_')
   self.publication_name = config.get('publication_name', f"{sanitized_db_name}_encryption_pub")
   self.slot_name = config.get('slot_name', f"{sanitized_db_name}_encryption_slot")
   ```

2. **Added `_quote_identifier()` method** (lines 53-66):
   ```python
   @staticmethod
   def _quote_identifier(identifier: str) -> str:
       escaped = identifier.replace('"', '""')
       return f'"{escaped}"'
   ```

3. **Updated all SQL statements** to use `_quote_identifier()`:
   - `CREATE PUBLICATION`
   - `DROP PUBLICATION`
   - `CREATE SUBSCRIPTION`
   - `ALTER SUBSCRIPTION ... DISABLE`
   - `ALTER SUBSCRIPTION ... SET (slot_name = NONE)`
   - `ALTER SUBSCRIPTION ... ENABLE`
   - `DROP SUBSCRIPTION`

## Testing

### Test with hyphenated database name:

```json
{
  "databases": [
    {
      "database": "recon-engine",
      "source": {
        "host": "source.rds.amazonaws.com",
        "database": "recon-engine",
        "user": "postgres",
        "password": "xxx"
      },
      "target": {
        "host": "target.rds.amazonaws.com",
        "database": "recon-engine",
        "user": "postgres",
        "password": "xxx"
      }
    }
  ]
}
```

```bash
python rds_encryption_automation.py --config databases.json --action setup-source
```

**Expected output:**
```
✓ Created publication: recon_engine_encryption_pub
✓ Created replication slot: recon_engine_encryption_slot
```

### Test with dotted database name:

```json
{
  "database": "app.production"
}
```

**Generated names:**
- Publication: `app_production_encryption_pub`
- Slot: `app_production_encryption_slot`

## Custom Names Still Work

If you want to override the auto-generated names:

```json
{
  "database": "recon-engine",
  "publication_name": "my_custom_pub",
  "slot_name": "my_custom_slot"
}
```

These will be used as-is (and properly quoted in SQL).

## Edge Cases Handled

### 1. Multiple Special Characters
```
Database: my-app.production-v2
Sanitized: my_app_production_v2
```

### 2. Already Has Underscores
```
Database: my_app
Sanitized: my_app (unchanged)
```

### 3. Mixed Characters
```
Database: recon-engine.prod
Sanitized: recon_engine_prod
```

### 4. Double Quotes in Custom Names
If you provide a custom name with quotes:
```python
publication_name = 'my"pub'
Quoted: "my""pub"  # Properly escaped
```

## Benefits

1. **✅ Works with any database name** - No restrictions on naming
2. **✅ No manual quoting needed** - Automatic handling
3. **✅ Backward compatible** - Existing configs still work
4. **✅ Safe SQL generation** - Prevents injection issues
5. **✅ Clear naming** - Sanitized names are readable

## Troubleshooting

### If you see syntax errors:

1. **Check the log** for the actual SQL being executed
2. **Verify** the publication/slot names in the output
3. **Ensure** you're using the latest version of the script

### If you have existing publications/slots with old names:

Drop them manually before running:

```sql
-- On target
DROP SUBSCRIPTION IF EXISTS "recon-engine_encryption_pub";

-- On source
SELECT pg_drop_replication_slot('recon-engine_encryption_slot');
DROP PUBLICATION IF EXISTS "recon-engine_encryption_pub";
```

Then run the script again.

## Summary

The script now:
- ✅ Sanitizes database names (replaces `-` and `.` with `_`)
- ✅ Quotes all identifiers in SQL statements
- ✅ Handles any database name format
- ✅ Prevents SQL syntax errors

**Database names with special characters are now fully supported!** 🎉
