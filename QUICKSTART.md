# Quick Start Guide

Get started with RDS PostgreSQL encryption migration in 5 minutes.

## Prerequisites Checklist

- [ ] Python 3.7+ installed
- [ ] AWS CLI installed and configured
- [ ] Network access to RDS instances
- [ ] Custom parameter group with `rds.logical_replication = 1`
- [ ] Parameter group attached to databases and instances rebooted

## Installation

```bash
# Navigate to project directory
cd rds-encryption-automation

# Install dependencies
pip install -r requirements.txt

# Make scripts executable
chmod +x rds_encryption_automation.py aws_helper.sh
```

## Configuration

1. **Copy and edit the configuration file:**

```bash
cp databases.json my-databases.json
```

2. **Update `my-databases.json` with your database details:**

```json
{
  "databases": [
    {
      "database": "myapp_db",
      "source": {
        "host": "unencrypted-db.xxxxx.rds.amazonaws.com",
        "port": 5432,
        "database": "myapp_db",
        "user": "postgres",
        "password": "your-password"
      },
      "target": {
        "host": "encrypted-db.xxxxx.rds.amazonaws.com",
        "port": 5432,
        "database": "myapp_db",
        "user": "postgres",
        "password": "your-password",
        "db_identifier": "encrypted-db"
      }
    }
  ]
}
```

3. **Secure your configuration:**

```bash
chmod 600 my-databases.json
```

## Migration Steps

### Step 1: Setup Source Database (5 minutes)

Create publication and replication slot on the unencrypted database:

```bash
python rds_encryption_automation.py \
  --config my-databases.json \
  --action setup-source
```
or
```
source venv/bin/activate && python rds_encryption_automation.py --config my-databases.json --action setup-source
```

**Expected output:**
```
✓ Logical replication is properly configured
✓ Created publication: myapp_db_encryption_pub
✓ Created replication slot: myapp_db_encryption_slot
✓ Source database setup completed successfully
```

### Step 2: Create Encrypted Database (15-30 minutes)

#### Option A: Using AWS Helper Script

```bash
# Full automated workflow
./aws_helper.sh full-workflow \
  unencrypted-db \
  encrypted-db \
  arn:aws:kms:us-east-1:123456789012:key/your-kms-key \
  your-subnet-group \
  sg-xxxxxxxxx \
  your-param-group \
  db.t3.medium
```

#### Option B: Manual AWS Commands

```bash
# 1. Create snapshot
aws rds create-db-snapshot \
  --db-instance-identifier unencrypted-db \
  --db-snapshot-identifier unencrypted-db-snapshot

# 2. Wait for snapshot
aws rds wait db-snapshot-completed \
  --db-snapshot-identifier unencrypted-db-snapshot

# 3. Copy with encryption
aws rds copy-db-snapshot \
  --source-db-snapshot-identifier unencrypted-db-snapshot \
  --target-db-snapshot-identifier encrypted-db-snapshot \
  --kms-key-id your-kms-key-id

# 4. Wait for encrypted snapshot
aws rds wait db-snapshot-completed \
  --db-snapshot-identifier encrypted-db-snapshot

# 5. Restore encrypted snapshot
aws rds restore-db-instance-from-db-snapshot \
  --db-instance-identifier encrypted-db \
  --db-snapshot-identifier encrypted-db-snapshot \
  --db-parameter-group-name your-param-group

# 6. Wait for database
aws rds wait db-instance-available \
  --db-instance-identifier encrypted-db
```

### Step 3: Setup Target Database (5 minutes)

Create subscription and start replication:

```bash
python rds_encryption_automation.py \
  --config my-databases.json \
  --action setup-target
```
or
```
source venv/bin/activate && python rds_encryption_automation.py --config my-databases.json --action setup-target
```

**The script will pause and ask for LSN:**

**✨ NEW: Just press Enter to auto-fetch LSN from source database!**

The script can now automatically query the source database to get the current LSN. This is the easiest and most reliable method.

**Alternative methods if auto-fetch doesn't work:**

```bash
# Option 1: Get LSN using standalone command
python rds_encryption_automation.py \
  --config my-databases.json \
  --action get-lsn

# Option 2: Using helper script
./aws_helper.sh get-lsn encrypted-db

# Option 3: Using AWS CLI directly
aws logs filter-log-events \
  --log-group-name /aws/rds/instance/encrypted-db/postgresql \
  --filter-pattern 'invalid record length'
```

**Or provide LSN directly:**

```bash
python rds_encryption_automation.py \
  --config my-databases.json \
  --action setup-target \
  --lsn 0/20000110
```

**Expected output:**
```
✓ Created subscription: myapp_db_encryption_pub (disabled)
✓ Advanced replication origin 'pg_2457' to LSN 0/20000110
✓ Enabled subscription: myapp_db_encryption_pub
✓ Replication is fully caught up (LSN distance = 0)
✓ Target database setup completed successfully
```

### Step 4: Verify Replication (Ongoing)

Monitor replication status:

```bash
python rds_encryption_automation.py \
  --config my-databases.json \
  --action verify
```

**Expected output:**
```
Replication status: flushed=0/20000110, current=0/20000110, distance=0
✓ Replication is fully caught up (LSN distance = 0)
```

**Keep monitoring until LSN distance = 0**

### Step 5: Application Cutover (5-10 minutes)

When replication is caught up:

1. **Stop application writes:**
   ```bash
   # Stop your application or put it in read-only mode
   kubectl scale deployment myapp --replicas=0
   ```

2. **Final verification:**
   ```bash
   python rds_encryption_automation.py \
     --config my-databases.json \
     --action verify
   ```

3. **Update connection strings:**
   - Update environment variables
   - Update configuration files
   - Update secrets/config management

4. **Start applications:**
   ```bash
   kubectl scale deployment myapp --replicas=3
   ```

5. **Verify applications are working**

### Step 6: Cleanup (2 minutes)

After successful cutover and verification:

```bash
python rds_encryption_automation.py \
  --config my-databases.json \
  --action cleanup
```

**Expected output:**
```
✓ Dropped subscription: myapp_db_encryption_pub
✓ Dropped replication slot: myapp_db_encryption_slot
✓ Dropped publication: myapp_db_encryption_pub
✓ Cleanup completed successfully
```

### Step 7: AWS Cleanup (Optional)

After a few days of running on encrypted database:

```bash
# Delete snapshots
./aws_helper.sh delete-snapshot unencrypted-db-snapshot
./aws_helper.sh delete-snapshot encrypted-db-snapshot

# Delete old unencrypted database (after backup!)
./aws_helper.sh delete-db unencrypted-db
```

## Troubleshooting

### Issue: "Logical replication is NOT properly configured"

**Solution:**
```bash
# Check parameter group
aws rds describe-db-instances \
  --db-instance-identifier your-db \
  --query 'DBInstances[0].DBParameterGroups'

# Ensure rds.logical_replication = 1 and reboot
```

### Issue: "Connection timeout"

**Solution:**
```bash
# Check security group
aws rds describe-db-instances \
  --db-instance-identifier your-db \
  --query 'DBInstances[0].VpcSecurityGroups'

# Test connection
psql -h your-db.xxxxx.rds.amazonaws.com -U postgres -d myapp_db
```

### Issue: "LSN distance not decreasing"

**Solution:**
- Wait longer (high write activity)
- Check target database performance
- Verify network connectivity

### Issue: "Cannot find LSN in logs"

**Solution:**
```bash
# List recent log files
aws rds describe-db-log-files \
  --db-instance-identifier encrypted-db

# Download specific log file
aws rds download-db-log-file-portion \
  --db-instance-identifier encrypted-db \
  --log-file-name error/postgresql.log.2024-10-15-04 \
  --output text | grep "invalid record length"
```

## Multiple Databases

To migrate multiple databases, add them all to your configuration file:

```json
{
  "databases": [
    {"database": "db1", "source": {...}, "target": {...}},
    {"database": "db2", "source": {...}, "target": {...}},
    {"database": "db3", "source": {...}, "target": {...}}
  ]
}
```

Then run the same commands - the script will process them sequentially.

**Or process one at a time:**

```bash
python rds_encryption_automation.py \
  --config my-databases.json \
  --action setup-source \
  --database db1
```

## Best Practices

1. **Test in non-production first** - Always test the complete workflow in a dev/staging environment

2. **Schedule during low traffic** - Plan migration during maintenance window

3. **Monitor closely** - Watch CloudWatch metrics during migration

4. **Keep backups** - Don't delete source database immediately

5. **Document everything** - Keep notes of endpoints, LSNs, and timing

6. **Verify data integrity** - Run data validation queries after cutover

7. **Have rollback plan** - Know how to switch back if needed

## Time Estimates

| Step | Duration | Notes |
|------|----------|-------|
| Setup source | 5 min | Per database |
| Create snapshot | 10-30 min | Depends on database size |
| Copy encrypted | 10-30 min | Depends on database size |
| Restore database | 10-20 min | Depends on database size |
| Setup target | 5 min | Per database |
| Initial sync | 5-60 min | Depends on changes since snapshot |
| Verification | Ongoing | Until LSN distance = 0 |
| Cutover | 5-10 min | Application downtime |
| Cleanup | 2 min | Per database |

**Total: 1-3 hours per database** (excluding initial sync time)

## Next Steps

- Read the full [README.md](README.md) for detailed documentation
- Review [AWS documentation](https://aws.amazon.com/blogs/database/encrypt-amazon-rds-for-postgresql-and-amazon-aurora-postgresql-database-with-minimal-downtime/)
- Test in non-production environment
- Plan your migration schedule
- Prepare rollback procedures

## Support

For issues:
1. Check logs: `rds_encryption_migration_*.log`
2. Review troubleshooting section
3. Verify AWS and database configurations
4. Check PostgreSQL logs in RDS console

## Success Checklist

After migration:
- [ ] Applications are running on encrypted database
- [ ] No errors in application logs
- [ ] Data integrity verified
- [ ] Performance is acceptable
- [ ] Replication cleaned up
- [ ] Old snapshots deleted (after verification period)
- [ ] Documentation updated with new endpoints
- [ ] Team notified of successful migration
