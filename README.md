# RDS Replication Automation

Automation scripts for managing PostgreSQL publications, replication slots, and subscriptions for RDS encryption with minimal downtime.

Based on: [AWS Blog - Encrypt Amazon RDS for PostgreSQL and Amazon Aurora PostgreSQL database with minimal downtime](https://aws.amazon.com/blogs/database/encrypt-amazon-rds-for-postgresql-and-amazon-aurora-postgresql-database-with-minimal-downtime/)

## Features

### Publications & Replication Slots (`manage_publications.py`)
- ✅ Automatically create publications for multiple databases on MASTER DB
- ✅ Automatically create replication slots for multiple databases on MASTER DB
- ✅ Automatically delete publications and replication slots
- ✅ List all publications and replication slots

### Subscriptions (`manage_subscriptions.py`)
- ✅ Automatically create subscriptions for multiple databases on REPLICATION DB
- ✅ Automatically delete subscriptions for multiple databases
- ✅ List all subscriptions in databases
- ✅ Automatic LSN advancement for replication origins

### Common Features
- ✅ Handle special characters in database names (converts to underscore)
- ✅ Configurable via `.env` file
- ✅ Comprehensive logging and error handling

## Prerequisites

- Python 3.7+
- PostgreSQL database with logical replication enabled
- Network access to both source and target databases

## Installation

1. Install Python dependencies:
```bash
pip install -r requirements.txt
```

2. Copy the example environment file and configure it:
```bash
cp .env.example .env
```

3. Edit `.env` with your database credentials and configuration:
```bash
# Replication Database Configuration (where subscriptions will be created)
REPLICATION_DB_HOST=your-replication-db.region.rds.amazonaws.com
REPLICATION_DB_PORT=5432
REPLICATION_DB_USER=root
REPLICATION_DB_PASSWORD=your-password

# Master Database Configuration (the encrypted database to replicate from)
MASTER_DB_HOST=testing-replikasi-master.cfkdf7u4lstc.ap-southeast-1.rds.amazonaws.com
MASTER_DB_PORT=5432
MASTER_DB_USER=root
MASTER_DB_PASSWORD=vGrnlMZJUuMzAybb

# LSN from logs (check logs for "Invalid Length" keyword)
LSN=38E7/403FB58

# Database names (comma-separated, supports special characters)
DATABASES=airbyte,test-dbmate,db1,db2,db3
```

## Usage

### Complete Workflow

Follow these steps in order for the complete RDS encryption workflow:

#### Step 1: Create Publications and Replication Slots (MASTER DB)

```bash
python manage_publications.py create
```

This will connect to the **MASTER database** and:
1. Create a publication for all tables: `{dbname}_pub`
2. Create a logical replication slot: `{dbname}_slot`
3. Verify both were created successfully

#### Step 2: Take Snapshot, Copy, and Restore

Follow your standard AWS RDS snapshot process (steps 3-5 in FLOW.md).

#### Step 3: Create Subscriptions (REPLICATION DB)

```bash
python manage_subscriptions.py create
```

This will connect to the **REPLICATION database** and:
1. Create a subscription: `{dbname}_sub`
2. Connect to the MASTER database publication
3. **Automatically find an unused replication origin**
4. Advance the replication origin to the specified LSN
5. Enable the subscription

#### Step 4: Delete Subscriptions (REPLICATION DB)

When you need to clean up:

```bash
python manage_subscriptions.py delete
```

This will:
1. Disable the subscription
2. Remove the slot from the subscription
3. Drop the subscription

#### Step 5: Delete Replication Slots and Publications (MASTER DB)

```bash
python manage_publications.py delete
```

This will:
1. Drop the replication slot
2. Drop the publication

### List Resources

List all publications and replication slots:

```bash
python manage_publications.py list
```

List all subscriptions:

```bash
python manage_subscriptions.py list
```

## Naming Conventions

The script automatically handles special characters in database names:

| Original Database Name | Subscription Name | Publication Name | Slot Name |
|------------------------|-------------------|------------------|-----------|
| `airbyte` | `airbyte_sub` | `airbyte_pub` | `airbyte_slot` |
| `test-dbmate` | `test_dbmate_sub` | `test_dbmate_pub` | `test_dbmate_slot` |
| `my-db-1` | `my_db_1_sub` | `my_db_1_pub` | `my_db_1_slot` |
| `my.db.2` | `my_db_2_sub` | `my_db_2_pub` | `my_db_2_slot` |

## Configuration Details

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `REPLICATION_DB_HOST` | Replication database host (where subscriptions are created) | Yes |
| `REPLICATION_DB_PORT` | Replication database port | No (default: 5432) |
| `REPLICATION_DB_USER` | Replication database user | Yes |
| `REPLICATION_DB_PASSWORD` | Replication database password | Yes |
| `MASTER_DB_HOST` | Master database host (to replicate from) | Yes |
| `MASTER_DB_PORT` | Master database port | No (default: 5432) |
| `MASTER_DB_USER` | Master database user | Yes |
| `MASTER_DB_PASSWORD` | Master database password | Yes |
| `LSN` | Log Sequence Number from logs | Yes |
| `DATABASES` | Comma-separated list of database names | Yes |

### Finding the LSN

Check your PostgreSQL logs for the "Invalid Length" keyword to find the LSN value. Example:

```
2024-10-26 12:34:56 UTC::@:[12345]:LOG: invalid length of startup packet
LSN: 38E7/403FB58
```

## Subscription Configuration

The script creates subscriptions with the following settings:

```sql
CREATE SUBSCRIPTION {dbname}_sub
CONNECTION 'host={master_host} user={master_user} password={master_password} dbname={dbname}'
PUBLICATION {dbname}_pub
WITH (
    copy_data = false,
    create_slot = false,
    enabled = false,
    synchronous_commit = false,
    connect = true,
    slot_name = '{dbname}_slot'
);
```

### Publication Configuration

The `manage_publications.py` script creates publications and replication slots on the **MASTER database**:

**Publication:**
```sql
CREATE PUBLICATION {dbname}_pub FOR ALL TABLES;
```

**Replication Slot:**
```sql
SELECT * FROM pg_create_logical_replication_slot('{dbname}_slot', 'pgoutput');
```

These must be created **before** taking snapshots and creating subscriptions.

### Automatic Replication Origin Selection

The script automatically identifies and uses **unused replication origins** for each subscription:

1. **Query all replication origins:**
   ```sql
   SELECT roname FROM pg_replication_origin WHERE roname LIKE 'pg_%';
   ```

2. **Query active/used replication origins:**
   ```sql
   SELECT o.roname 
   FROM pg_replication_origin o
   INNER JOIN pg_replication_origin_status s ON o.roident = s.local_id
   WHERE o.roname LIKE 'pg_%';
   ```

3. **Find unused origins** by comparing the two lists

4. **Advance the unused origin** to the specified LSN:
   ```sql
   SELECT pg_replication_origin_advance('pg_2457', '0/20000110');
   ```

This ensures each subscription gets its own unique, unused replication origin without manual intervention. The script will warn you if no unused origins are available.

## Example: Managing 33 Databases

Complete workflow for managing 33 databases:

1. **Configure your `.env` file with all 33 databases:**

```bash
DATABASES=db1,db2,db3,db4,db5,db6,db7,db8,db9,db10,db11,db12,db13,db14,db15,db16,db17,db18,db19,db20,db21,db22,db23,db24,db25,db26,db27,db28,db29,db30,db31,db32,db33
```

2. **Create publications and replication slots on MASTER DB:**

```bash
python manage_publications.py create
```

3. **Take snapshot, copy to encrypted storage, and restore** (manual AWS steps)

4. **Create subscriptions on REPLICATION DB:**

```bash
python manage_subscriptions.py create
```

5. **Monitor the output for any errors**

6. **When ready to clean up, delete subscriptions:**

```bash
python manage_subscriptions.py delete
```

7. **Delete replication slots and publications:**

```bash
python manage_publications.py delete
```

## Troubleshooting

### Connection Issues

If you encounter connection issues:
- Verify database credentials in `.env`
- Check network connectivity to both source and target databases
- Ensure security groups/firewalls allow connections
- Verify the database user has appropriate permissions

### Permission Requirements

**For MASTER database** (publications and replication slots):
- `CREATE` on the database
- `REPLICATION` role attribute
- Superuser or `rds_replication` role (for RDS)

**For REPLICATION database** (subscriptions):
- `CREATE` on the database
- `REPLICATION` role attribute
- Access to `pg_replication_origin` system catalog

### Resource Already Exists

If a publication, replication slot, or subscription already exists, the script will skip it and continue with the next database.

### LSN Issues

If you encounter LSN-related errors:
- Verify the LSN format is correct (e.g., `38E7/403FB58`)
- Check that the LSN is from the correct point in time
- Ensure the replication slot exists on the target database

### Replication Conflicts

If you encounter duplicate key violations during replication:

```
ERROR:  duplicate key value violates unique constraint "uk_spaces_space_name"
DETAIL:  Key (space_name)=(*) already exists.
```

**Quick Fix:**
```bash
# Check the conflict
python fix_replication_conflict.py <database_name> status

# Delete the conflicting row
python fix_replication_conflict.py <database_name> delete_conflict

# Enable the subscription
python fix_replication_conflict.py <database_name> enable
```

**See detailed guide:** `REPLICATION_CONFLICT_GUIDE.md` or `QUICK_FIX.md`

## Logging

Both scripts provide detailed logging:
- `INFO`: Normal operation messages
- `WARNING`: Non-critical issues (e.g., resource already exists)
- `ERROR`: Critical errors that prevent operation

## Safety Features

- Validates all required environment variables before execution
- Checks if resources already exist before creating
- Provides detailed error messages for troubleshooting
- Uses parameterized queries to prevent SQL injection
- Automatic connection cleanup
- Separate scripts for MASTER and REPLICATION operations

## Scripts Overview

| Script | Purpose | Target Database | Operations |
|--------|---------|-----------------|------------|
| `manage_publications.py` | Manage publications and replication slots | MASTER DB | create, delete, list |
| `manage_subscriptions.py` | Manage subscriptions | REPLICATION DB | create, delete, list |
| `fix_replication_conflict.py` | Fix replication conflicts | REPLICATION DB | status, delete_conflict, advance_lsn, enable |

## Related Files

- `FLOW.md` - Manual workflow documentation
- `manage_publications.py` - Automate publications and replication slots (MASTER DB)
- `manage_subscriptions.py` - Automate subscriptions (REPLICATION DB)
- `fix_replication_conflict.py` - Fix replication conflicts (REPLICATION DB)
- `REPLICATION_CONFLICT_GUIDE.md` - Detailed conflict resolution guide
- `QUICK_FIX.md` - Quick reference for fixing conflicts
- `.env` - Configuration file (not tracked in git)
- `.env.example` - Example configuration template

## License

MIT
