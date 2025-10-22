# RDS PostgreSQL Encryption Migration Automation

Automate the database-side operations for encrypting Amazon RDS PostgreSQL instances with minimal downtime using logical replication.

This tool is based on the AWS guide: [Encrypt Amazon RDS for PostgreSQL and Amazon Aurora PostgreSQL database with minimal downtime](https://aws.amazon.com/blogs/database/encrypt-amazon-rds-for-postgresql-and-amazon-aurora-postgresql-database-with-minimal-downtime/)

## Overview

This automation script handles the PostgreSQL logical replication setup for multiple database instances, allowing you to:

- ✅ Create publications on source (unencrypted) databases
- ✅ Create replication slots on source databases
- ✅ Create subscriptions on target (encrypted) databases
- ✅ Advance replication origins to specific LSN
- ✅ Enable and verify replication
- ✅ Clean up replication after migration
- ✅ Process multiple databases in batch

**Note:** AWS infrastructure operations (creating snapshots, restoring encrypted databases, modifying parameter groups) must be done manually through AWS Console or CLI.

## Prerequisites

### 1. Python Environment
- Python 3.7 or higher
- Install dependencies: `pip install -r requirements.txt`

### 2. AWS RDS Configuration

Before running this script, you must:

1. **Create a custom parameter group** with `rds.logical_replication = 1`
2. **Attach the parameter group** to both source and target databases
3. **Reboot the databases** to apply the parameter changes

### 3. Network Access
- Ensure the machine running this script can connect to both source and target RDS instances
- Configure security groups to allow PostgreSQL connections (port 5432)

## Installation

```bash
# Clone or download this repository
cd rds-encryption-automation

# Install Python dependencies
pip install -r requirements.txt

# Make the script executable (optional)
chmod +x rds_encryption_automation.py
```

## Configuration

### 1. Create Configuration File

Copy `databases.json` and update it with your database details:

```json
{
  "databases": [
    {
      "database": "myapp_production",
      "publication_name": "myapp_prod_encryption_pub",
      "slot_name": "myapp_prod_encryption_slot",
      "source": {
        "host": "unencrypted-db.xxxxx.us-east-1.rds.amazonaws.com",
        "port": 5432,
        "database": "myapp_production",
        "user": "postgres",
        "password": "your-password-here"
      },
      "target": {
        "host": "encrypted-db.xxxxx.us-east-1.rds.amazonaws.com",
        "port": 5432,
        "database": "myapp_production",
        "user": "postgres",
        "password": "your-password-here",
        "db_identifier": "encrypted-db"
      },
      "tables": null
    }
  ]
}
```

### Configuration Options

- **database**: Database name (for identification)
- **publication_name**: Name for the publication (auto-generated if not specified)
- **slot_name**: Name for the replication slot (auto-generated if not specified)
- **source**: Source (unencrypted) database connection details
- **target**: Target (encrypted) database connection details
- **tables**: List of specific tables to replicate, or `null` for all tables
- **db_identifier**: RDS instance identifier (used for CloudWatch logs)

### 2. Secure Your Credentials

**Important:** Never commit credentials to version control!

Options for securing credentials:
- Use AWS Secrets Manager and modify the script to fetch credentials
- Use environment variables
- Use a separate credentials file with restricted permissions
- Use AWS IAM database authentication

```bash
# Set restrictive permissions on config file
chmod 600 databases.json
```

## Usage

### Complete Migration Workflow

#### Step 1: Setup Source Database

This creates the publication and replication slot on the unencrypted database.

```bash
python rds_encryption_automation.py \
  --config databases.json \
  --action setup-source
```

**What it does:**
- Verifies logical replication is enabled
- Creates publication for specified tables (or all tables)
- Creates logical replication slot
- Verifies the setup

#### Step 2: Create Encrypted Database (Manual AWS Step)

**You must manually perform these AWS operations:**

1. **Create a snapshot** of the source database:
   ```bash
   aws rds create-db-snapshot \
     --db-instance-identifier unencrypted-db \
     --db-snapshot-identifier unencrypted-db-snapshot
   ```

2. **Copy the snapshot with encryption**:
   ```bash
   aws rds copy-db-snapshot \
     --source-db-snapshot-identifier unencrypted-db-snapshot \
     --target-db-snapshot-identifier encrypted-db-snapshot \
     --kms-key-id your-kms-key-id
   ```

3. **Restore the encrypted snapshot**:
   ```bash
   aws rds restore-db-instance-from-db-snapshot \
     --db-instance-identifier encrypted-db \
     --db-snapshot-identifier encrypted-db-snapshot \
     --db-parameter-group-name your-custom-param-group
   ```

4. **Wait for the database to be available**

#### Step 3: Setup Target Database

This creates the subscription on the encrypted database and starts replication.

```bash
python rds_encryption_automation.py \
  --config databases.json \
  --action setup-target
```

**What it does:**
- Verifies logical replication is enabled
- Creates subscription (initially disabled)
- Prompts you to get LSN from logs
- Advances replication origin to the LSN
- Enables subscription
- Verifies replication is working

**Getting the LSN:**

The script will pause and show instructions for getting the LSN. You can get it via:

**Option A: AWS Console**
1. Go to RDS Console → Your encrypted database
2. Click "Logs & events" tab
3. Open the most recent PostgreSQL log
4. Search for "invalid record length"
5. Copy the LSN (format: `0/XXXXXXXX`)

**Option B: AWS CLI**
```bash
aws logs filter-log-events \
  --log-group-name /aws/rds/instance/encrypted-db/postgresql \
  --filter-pattern 'invalid record length'
```

**Option C: Provide LSN directly**
```bash
python rds_encryption_automation.py \
  --config databases.json \
  --action setup-target \
  --lsn 0/20000110
```

#### Step 4: Verify Replication

Monitor replication status to ensure data is syncing:

```bash
python rds_encryption_automation.py \
  --config databases.json \
  --action verify
```

**What it does:**
- Checks LSN distance between source and target
- Reports replication lag
- Confirms when replication is caught up (LSN distance = 0)

#### Step 5: Cutover to Encrypted Database (Manual)

When replication is caught up:

1. **Stop application writes** to the source database
2. **Verify replication is at LSN distance = 0**
3. **Update application connection strings** to point to encrypted database
4. **Restart applications**
5. **Verify applications are working**

#### Step 6: Cleanup

After successful cutover, clean up the replication:

```bash
python rds_encryption_automation.py \
  --config databases.json \
  --action cleanup
```

**What it does:**
- Drops subscription on target database
- Drops replication slot on source database
- Drops publication on source database

## Advanced Usage

### Process Single Database

Process only one database from your configuration:

```bash
python rds_encryption_automation.py \
  --config databases.json \
  --action setup-source \
  --database myapp_production
```

### Replicate Specific Tables

In your configuration, specify tables to replicate:

```json
{
  "database": "customer_db",
  "tables": ["users", "orders", "payments"]
}
```

### Batch Processing

The script automatically processes all databases in the configuration file sequentially. Monitor the logs for progress.

## Monitoring and Troubleshooting

### Log Files

The script creates timestamped log files:
```
rds_encryption_migration_YYYYMMDD_HHMMSS.log
```

### Common Issues

#### 1. Logical Replication Not Enabled

**Error:** `✗ Logical replication is NOT properly configured`

**Solution:**
- Ensure `rds.logical_replication = 1` in parameter group
- Reboot the database instance
- Wait for instance to be available

#### 2. Connection Timeout

**Error:** `Failed to connect to database`

**Solution:**
- Check security group rules
- Verify network connectivity
- Confirm database endpoint is correct
- Check if database is available

#### 3. Replication Slot Already Exists

**Solution:**
- The script will prompt you to drop and recreate
- Or manually drop: `SELECT pg_drop_replication_slot('slot_name');`

#### 4. LSN Distance Not Decreasing

**Possible causes:**
- High write activity on source database
- Network latency
- Target database performance issues

**Solution:**
- Wait longer for replication to catch up
- Check target database performance metrics
- Consider scaling up target instance temporarily

### Monitoring Queries

Connect to the source database and run:

```sql
-- Check replication slot status
SELECT 
    slot_name,
    slot_type,
    database,
    active,
    confirmed_flush_lsn,
    pg_current_wal_lsn(),
    (pg_current_wal_lsn() - confirmed_flush_lsn) AS lsn_distance
FROM pg_replication_slots
WHERE slot_type = 'logical';

-- Check publication
SELECT * FROM pg_publication;

-- Check replication lag in bytes
SELECT 
    slot_name,
    pg_size_pretty(pg_current_wal_lsn() - confirmed_flush_lsn) AS replication_lag
FROM pg_replication_slots
WHERE slot_type = 'logical';
```

Connect to the target database and run:

```sql
-- Check subscription status
SELECT 
    subname,
    subenabled,
    subslotname
FROM pg_subscription;

-- Check replication origin
SELECT * FROM pg_replication_origin;
```

## Security Best Practices

1. **Credentials Management**
   - Use AWS Secrets Manager for production
   - Never commit credentials to version control
   - Use IAM database authentication when possible

2. **Network Security**
   - Use VPN or bastion host for database access
   - Restrict security group rules to specific IPs
   - Use SSL/TLS for database connections

3. **Audit Logging**
   - Enable RDS audit logging
   - Review migration logs regularly
   - Keep logs for compliance requirements

4. **Access Control**
   - Use least-privilege database users
   - Rotate passwords after migration
   - Review and revoke temporary access

## Performance Considerations

### Source Database Impact

Logical replication has minimal impact but consider:
- WAL generation increases (replication slot retains WAL)
- Monitor disk space on source database
- Plan for peak hours vs. off-peak migration

### Target Database Performance

- Ensure target instance has adequate resources
- Consider temporarily scaling up during initial sync
- Monitor CPU, memory, and I/O metrics

### Network Bandwidth

- Large databases may take time for initial sync
- Monitor network transfer costs
- Consider using VPC peering for same-region transfers

## Rollback Plan

If issues occur during migration:

1. **Before cutover:** Simply stop the replication and continue using source database
2. **After cutover:** You still have the source database as backup
3. **Emergency rollback:** Update connection strings back to source database

## Cost Optimization

- Delete snapshots after successful migration
- Terminate source database after verification period
- Monitor replication slot disk usage
- Clean up CloudWatch logs

## Support and Contribution

For issues or improvements:
1. Check the troubleshooting section
2. Review AWS documentation
3. Check PostgreSQL logical replication docs
4. Open an issue with detailed logs

## License

This script is provided as-is for automation purposes. Use at your own risk and test thoroughly in non-production environments first.

## References

- [AWS Blog: Encrypt RDS PostgreSQL with minimal downtime](https://aws.amazon.com/blogs/database/encrypt-amazon-rds-for-postgresql-and-amazon-aurora-postgresql-database-with-minimal-downtime/)
- [PostgreSQL Logical Replication Documentation](https://www.postgresql.org/docs/current/logical-replication.html)
- [RDS PostgreSQL Logical Replication](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/CHAP_PostgreSQL.html#PostgreSQL.Concepts.General.FeatureSupport.LogicalReplication)

## Changelog

### Version 1.0.0
- Initial release
- Support for multiple databases
- Publication and subscription automation
- Verification and cleanup features
- Comprehensive logging
