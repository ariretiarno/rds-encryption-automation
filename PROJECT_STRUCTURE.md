# Project Structure

```
rds-encryption-automation/
│
├── README.md                           # Comprehensive documentation
├── QUICKSTART.md                       # Quick start guide (5-minute setup)
├── PROJECT_STRUCTURE.md                # This file
│
├── rds_encryption_automation.py        # Main automation script (Python)
├── monitor_replication.py              # Real-time replication monitoring
├── aws_helper.sh                       # AWS CLI helper script (Bash)
│
├── requirements.txt                    # Python dependencies
├── .gitignore                          # Git ignore rules
│
├── databases.json                      # Your database configuration (DO NOT COMMIT)
└── databases.example.json              # Example configuration template
```

## File Descriptions

### Documentation

- **README.md** (12KB)
  - Complete documentation for the automation tool
  - Prerequisites, installation, configuration
  - Detailed usage instructions for all operations
  - Troubleshooting guide and best practices
  - Security recommendations

- **QUICKSTART.md** (9KB)
  - Step-by-step quick start guide
  - Time estimates for each step
  - Common troubleshooting issues
  - Success checklist

- **PROJECT_STRUCTURE.md** (This file)
  - Overview of project organization
  - File descriptions and purposes
  - Quick reference for what each file does

### Core Scripts

- **rds_encryption_automation.py** (29KB) ⭐
  - Main automation script for PostgreSQL logical replication
  - Handles publication/subscription creation
  - Manages replication slots and origins
  - Supports batch processing of multiple databases
  - Comprehensive logging and error handling
  
  **Key Features:**
  - ✅ Setup source database (publication + replication slot)
  - ✅ Setup target database (subscription + LSN advancement)
  - ✅ Verify replication status
  - ✅ Cleanup after migration
  - ✅ Process multiple databases in batch
  - ✅ Interactive prompts for safety
  - ✅ Detailed logging to file and console

- **monitor_replication.py** (11KB)
  - Real-time replication monitoring dashboard
  - Displays LSN distance and lag size
  - Color-coded status indicators
  - Continuous updates with configurable interval
  
  **Key Features:**
  - 📊 Real-time replication status
  - 📈 Lag monitoring with visual indicators
  - 🔄 Auto-refresh display
  - ⏱️ Elapsed time tracking
  - 🎨 Color-coded status (synced/good/warning/critical)

- **aws_helper.sh** (11KB)
  - Bash script for AWS CLI operations
  - Automates snapshot creation and restoration
  - Helps retrieve LSN from CloudWatch logs
  - Database status checking
  
  **Key Features:**
  - 📸 Create database snapshots
  - 🔐 Copy snapshots with encryption
  - 🔄 Restore encrypted snapshots
  - 📋 Get LSN from CloudWatch logs
  - 🔍 Check database status
  - 🗑️ Cleanup snapshots and databases
  - 🚀 Full workflow automation

### Configuration

- **databases.json** (2KB)
  - Your actual database configuration
  - Contains connection details and credentials
  - **⚠️ NEVER commit this file to version control**
  - Automatically ignored by .gitignore

- **databases.example.json** (1.6KB)
  - Template configuration file
  - Shows the expected JSON structure
  - Safe to commit to version control
  - Copy this to create your databases.json

- **requirements.txt** (23 bytes)
  - Python package dependencies
  - Currently only requires: psycopg2-binary==2.9.9

- **.gitignore** (467 bytes)
  - Prevents committing sensitive files
  - Ignores configuration files with credentials
  - Ignores log files and Python cache

## Usage Flow

### 1. Initial Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Create configuration
cp databases.example.json databases.json
# Edit databases.json with your details

# Make scripts executable
chmod +x rds_encryption_automation.py aws_helper.sh monitor_replication.py
```

### 2. Migration Workflow

```
┌─────────────────────────────────────────────────────────────┐
│                    MIGRATION WORKFLOW                       │
└─────────────────────────────────────────────────────────────┘

Step 1: Setup Source Database
  └─> rds_encryption_automation.py --action setup-source
      ├─> Creates publication
      └─> Creates replication slot

Step 2: Create Encrypted Database (Manual AWS)
  └─> aws_helper.sh full-workflow [params]
      OR manual AWS CLI commands
      ├─> Create snapshot
      ├─> Copy with encryption
      └─> Restore encrypted snapshot

Step 3: Setup Target Database
  └─> rds_encryption_automation.py --action setup-target
      ├─> Creates subscription
      ├─> Gets LSN (via aws_helper.sh get-lsn)
      ├─> Advances replication origin
      └─> Enables subscription

Step 4: Monitor Replication
  └─> monitor_replication.py --config databases.json --database mydb
      └─> Real-time monitoring until LSN distance = 0

Step 5: Application Cutover (Manual)
  ├─> Stop application writes
  ├─> Verify replication caught up
  ├─> Update connection strings
  └─> Start applications

Step 6: Cleanup
  └─> rds_encryption_automation.py --action cleanup
      ├─> Drops subscription
      ├─> Drops replication slot
      └─> Drops publication
```

## Command Reference

### Main Automation Script

```bash
# Setup source database
python rds_encryption_automation.py --config databases.json --action setup-source

# Setup target database
python rds_encryption_automation.py --config databases.json --action setup-target

# Setup target with LSN
python rds_encryption_automation.py --config databases.json --action setup-target --lsn 0/20000110

# Verify replication
python rds_encryption_automation.py --config databases.json --action verify

# Cleanup
python rds_encryption_automation.py --config databases.json --action cleanup

# Process single database
python rds_encryption_automation.py --config databases.json --action setup-source --database mydb
```

### Monitoring Script

```bash
# Monitor using config file
python monitor_replication.py --config databases.json --database mydb

# Monitor with custom interval
python monitor_replication.py --config databases.json --database mydb --interval 10

# Monitor using direct connection
python monitor_replication.py \
  --host db.xxxxx.rds.amazonaws.com \
  --database mydb \
  --user postgres \
  --password mypass \
  --slot mydb_slot \
  --publication mydb_pub
```

### AWS Helper Script

```bash
# Create snapshot
./aws_helper.sh create-snapshot mydb-prod

# Get LSN from logs
./aws_helper.sh get-lsn mydb-encrypted

# Check database status
./aws_helper.sh check-status mydb-prod

# Full workflow
./aws_helper.sh full-workflow \
  source-db target-db kms-key subnet-group security-groups param-group instance-class

# Delete snapshot
./aws_helper.sh delete-snapshot snapshot-id

# Delete database
./aws_helper.sh delete-db db-instance
```

## Configuration Structure

```json
{
  "databases": [
    {
      "database": "myapp_production",
      "publication_name": "myapp_prod_encryption_pub",
      "slot_name": "myapp_prod_encryption_slot",
      "source": {
        "host": "unencrypted-db.xxxxx.rds.amazonaws.com",
        "port": 5432,
        "database": "myapp_production",
        "user": "postgres",
        "password": "your-password"
      },
      "target": {
        "host": "encrypted-db.xxxxx.rds.amazonaws.com",
        "port": 5432,
        "database": "myapp_production",
        "user": "postgres",
        "password": "your-password",
        "db_identifier": "encrypted-db"
      },
      "tables": null
    }
  ]
}
```

### Configuration Fields

- **database**: Database name (for identification)
- **publication_name**: Publication name (optional, auto-generated)
- **slot_name**: Replication slot name (optional, auto-generated)
- **source**: Source database connection details
  - **host**: RDS endpoint
  - **port**: Port number (default: 5432)
  - **database**: Database name
  - **user**: Database user
  - **password**: Database password
- **target**: Target database connection details (same structure as source)
  - **db_identifier**: RDS instance identifier (for CloudWatch logs)
- **tables**: Array of table names or null for all tables

## Log Files

The automation script creates timestamped log files:

```
rds_encryption_migration_YYYYMMDD_HHMMSS.log
```

Example:
```
rds_encryption_migration_20241015_112058.log
```

Logs contain:
- Timestamp for each operation
- Success/failure status
- SQL queries executed
- Error messages and stack traces
- Replication status updates

## Security Considerations

### Files with Sensitive Data

⚠️ **NEVER commit these files:**
- `databases.json` - Contains database credentials
- `*.log` - May contain connection strings
- Any file with `-databases.json` pattern

✅ **Safe to commit:**
- `databases.example.json` - Template only
- All `.py` and `.sh` scripts
- Documentation files

### Best Practices

1. **Credentials Management**
   - Use AWS Secrets Manager in production
   - Set restrictive file permissions: `chmod 600 databases.json`
   - Consider using environment variables
   - Rotate passwords after migration

2. **Network Security**
   - Use VPN or bastion host
   - Restrict security group rules
   - Enable SSL/TLS connections

3. **Access Control**
   - Use least-privilege database users
   - Enable audit logging
   - Review and revoke temporary access

## Dependencies

### Python Packages
- **psycopg2-binary** (2.9.9)
  - PostgreSQL database adapter
  - Binary distribution (no compilation needed)

### System Requirements
- Python 3.7+
- AWS CLI (for aws_helper.sh)
- Network access to RDS instances
- Sufficient permissions on databases

## Troubleshooting

### Common Issues

1. **Import Error: No module named 'psycopg2'**
   ```bash
   pip install -r requirements.txt
   ```

2. **Permission Denied**
   ```bash
   chmod +x rds_encryption_automation.py aws_helper.sh monitor_replication.py
   ```

3. **Connection Timeout**
   - Check security group rules
   - Verify database endpoint
   - Test with psql first

4. **Logical Replication Not Enabled**
   - Set `rds.logical_replication = 1` in parameter group
   - Reboot database instance

## Support

For issues:
1. Check log files for detailed error messages
2. Review QUICKSTART.md troubleshooting section
3. Verify AWS and database configurations
4. Check PostgreSQL logs in RDS console

## Version History

- **v1.0.0** (2024-10-15)
  - Initial release
  - Support for multiple databases
  - Publication/subscription automation
  - Real-time monitoring
  - AWS helper scripts
  - Comprehensive documentation

## License

This project is provided as-is for automation purposes. Use at your own risk and test thoroughly in non-production environments first.

## References

- [AWS Blog: Encrypt RDS PostgreSQL with minimal downtime](https://aws.amazon.com/blogs/database/encrypt-amazon-rds-for-postgresql-and-amazon-aurora-postgresql-database-with-minimal-downtime/)
- [PostgreSQL Logical Replication](https://www.postgresql.org/docs/current/logical-replication.html)
- [RDS PostgreSQL Documentation](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/CHAP_PostgreSQL.html)
