# RDS PostgreSQL Encryption Migration Checklist

Use this checklist to track your migration progress for each database.

## Pre-Migration Checklist

### Environment Setup
- [ ] Python 3.7+ installed
- [ ] AWS CLI installed and configured
- [ ] Dependencies installed (`pip install -r requirements.txt`)
- [ ] Scripts are executable (`chmod +x *.py *.sh`)
- [ ] Configuration file created and secured (`chmod 600 databases.json`)

### AWS Prerequisites
- [ ] Custom parameter group created
- [ ] `rds.logical_replication = 1` set in parameter group
- [ ] Parameter group attached to source database
- [ ] Source database rebooted
- [ ] Logical replication verified on source database
- [ ] KMS key available for encryption
- [ ] Sufficient RDS quota for new instance
- [ ] Security groups configured for access

### Database Information Gathered
- [ ] Source database endpoint: ___________________________
- [ ] Source database name: ___________________________
- [ ] Database size: ___________________________
- [ ] Peak traffic hours documented
- [ ] Maintenance window scheduled
- [ ] Stakeholders notified

### Testing
- [ ] Tested complete workflow in non-production environment
- [ ] Verified application compatibility with encrypted database
- [ ] Backup and restore procedures tested
- [ ] Rollback plan documented

## Migration Execution

### Database: ___________________________
**Date**: ___________________________  
**Engineer**: ___________________________

---

### Phase 1: Source Database Setup (Est. 5 min)

**Start Time**: ___________  **End Time**: ___________

- [ ] Run setup-source command
  ```bash
  python rds_encryption_automation.py --config databases.json --action setup-source --database <name>
  ```
- [ ] Verify publication created
- [ ] Verify replication slot created
- [ ] Note publication name: ___________________________
- [ ] Note slot name: ___________________________
- [ ] Check log file for errors

**Status**: ⬜ Not Started | ⬜ In Progress | ⬜ Completed | ⬜ Failed

**Notes**:
```


```

---

### Phase 2: Create Encrypted Database (Est. 20-60 min)

**Start Time**: ___________  **End Time**: ___________

#### Step 2.1: Create Snapshot
- [ ] Run snapshot creation
  ```bash
  ./aws_helper.sh create-snapshot <source-db-instance>
  ```
- [ ] Snapshot ID: ___________________________
- [ ] Snapshot status: Available
- [ ] Snapshot size: ___________________________

#### Step 2.2: Copy with Encryption
- [ ] Run encrypted copy
  ```bash
  ./aws_helper.sh copy-snapshot <snapshot-id> <kms-key-id>
  ```
- [ ] Encrypted snapshot ID: ___________________________
- [ ] Encryption verified: Yes
- [ ] KMS key used: ___________________________

#### Step 2.3: Restore Encrypted Database
- [ ] Run restore command
  ```bash
  ./aws_helper.sh restore <snapshot> <target-db> <subnet> <sg> <param> <class>
  ```
- [ ] Target instance ID: ___________________________
- [ ] Target endpoint: ___________________________
- [ ] Database status: Available
- [ ] Encryption verified in console
- [ ] Parameter group attached: ___________________________
- [ ] Database rebooted (if needed)

**Status**: ⬜ Not Started | ⬜ In Progress | ⬜ Completed | ⬜ Failed

**Notes**:
```


```

---

### Phase 3: Target Database Setup (Est. 5 min)

**Start Time**: ___________  **End Time**: ___________

#### Step 3.1: Get LSN
- [ ] Run LSN retrieval
  ```bash
  ./aws_helper.sh get-lsn <target-db-instance>
  ```
- [ ] LSN value: ___________________________

#### Step 3.2: Setup Target
- [ ] Run setup-target command
  ```bash
  python rds_encryption_automation.py --config databases.json --action setup-target --database <name> --lsn <lsn>
  ```
- [ ] Subscription created
- [ ] Replication origin advanced
- [ ] Subscription enabled
- [ ] Initial verification passed

**Status**: ⬜ Not Started | ⬜ In Progress | ⬜ Completed | ⬜ Failed

**Notes**:
```


```

---

### Phase 4: Monitor Replication (Until LSN distance = 0)

**Start Time**: ___________  **End Time**: ___________

- [ ] Start monitoring
  ```bash
  python monitor_replication.py --config databases.json --database <name>
  ```
- [ ] Initial LSN distance: ___________________________
- [ ] Replication lag: ___________________________
- [ ] Monitor for at least 30 minutes
- [ ] LSN distance reached 0
- [ ] Verify replication
  ```bash
  python rds_encryption_automation.py --config databases.json --action verify --database <name>
  ```

**Monitoring Log**:
| Time | LSN Distance | Lag Size | Status |
|------|--------------|----------|--------|
| _____ | _____ | _____ | _____ |
| _____ | _____ | _____ | _____ |
| _____ | _____ | _____ | _____ |
| _____ | _____ | _____ | _____ |

**Status**: ⬜ Not Started | ⬜ In Progress | ⬜ Completed | ⬜ Failed

**Notes**:
```


```

---

### Phase 5: Application Cutover (Est. 5-10 min)

**Start Time**: ___________  **End Time**: ___________

#### Step 5.1: Pre-Cutover Verification
- [ ] Replication fully caught up (LSN distance = 0)
- [ ] No errors in replication logs
- [ ] Target database performance acceptable
- [ ] Backup of current state taken
- [ ] Rollback plan reviewed

#### Step 5.2: Stop Application Writes
- [ ] Application maintenance mode enabled
- [ ] Application scaled down / stopped
- [ ] Verify no active connections to source database
- [ ] Final replication verification (LSN distance = 0)

#### Step 5.3: Update Connection Strings
- [ ] Environment variables updated
- [ ] Configuration files updated
- [ ] Secrets manager updated
- [ ] DNS records updated (if applicable)
- [ ] Connection strings documented:
  - Old: ___________________________
  - New: ___________________________

#### Step 5.4: Start Applications
- [ ] Applications started with new connection strings
- [ ] Application health checks passing
- [ ] Test transactions executed successfully
- [ ] Logs checked for database errors
- [ ] Performance metrics normal

**Downtime Duration**: ___________

**Status**: ⬜ Not Started | ⬜ In Progress | ⬜ Completed | ⬜ Failed

**Notes**:
```


```

---

### Phase 6: Post-Cutover Verification (Est. 30 min)

**Start Time**: ___________  **End Time**: ___________

- [ ] Applications running normally
- [ ] No errors in application logs
- [ ] Database connections stable
- [ ] Performance metrics acceptable
- [ ] Data integrity spot checks passed
- [ ] User acceptance testing completed
- [ ] Monitor for at least 30 minutes

**Verification Queries**:
```sql
-- Record counts match
SELECT COUNT(*) FROM important_table;
-- Source: _____  Target: _____

-- Recent data present
SELECT MAX(created_at) FROM important_table;
-- Source: _____  Target: _____

-- No replication errors
SELECT * FROM pg_stat_replication;
```

**Status**: ⬜ Not Started | ⬜ In Progress | ⬜ Completed | ⬜ Failed

**Notes**:
```


```

---

### Phase 7: Cleanup (Est. 2 min)

**Start Time**: ___________  **End Time**: ___________

#### Step 7.1: Remove Replication
- [ ] Run cleanup command
  ```bash
  python rds_encryption_automation.py --config databases.json --action cleanup --database <name>
  ```
- [ ] Subscription dropped
- [ ] Replication slot dropped
- [ ] Publication dropped
- [ ] Verify cleanup in logs

#### Step 7.2: AWS Resource Cleanup (After verification period)
- [ ] Delete unencrypted snapshot: ___________________________
- [ ] Delete encrypted snapshot: ___________________________
- [ ] Schedule source database deletion (after X days)
- [ ] Document retention period: ___________________________

**Status**: ⬜ Not Started | ⬜ In Progress | ⬜ Completed | ⬜ Failed

**Notes**:
```


```

---

## Post-Migration Tasks

### Immediate (Day 1)
- [ ] Update documentation with new endpoints
- [ ] Update runbooks and procedures
- [ ] Notify team of successful migration
- [ ] Monitor application and database metrics
- [ ] Keep source database running (for rollback)

### Short-term (Week 1)
- [ ] Daily monitoring of encrypted database
- [ ] Performance comparison with source
- [ ] User feedback collected
- [ ] Any issues documented and resolved
- [ ] Backup and restore tested on encrypted database

### Long-term (After 30 days)
- [ ] Delete source database (after final backup)
- [ ] Remove old connection strings from secrets
- [ ] Update disaster recovery procedures
- [ ] Archive migration logs
- [ ] Conduct post-mortem / lessons learned

---

## Rollback Plan

**If issues occur during migration:**

### Before Cutover
- [ ] Stop the migration process
- [ ] Keep source database running
- [ ] No application changes needed
- [ ] Document issues encountered

### After Cutover (Emergency Rollback)
- [ ] Stop applications
- [ ] Revert connection strings to source database
- [ ] Restart applications
- [ ] Verify applications working
- [ ] Document data loss window (if any)
- [ ] Plan re-migration after fixing issues

**Rollback Decision Criteria**:
- Application errors > X%
- Performance degradation > Y%
- Data integrity issues detected
- Replication not catching up after Z minutes

---

## Success Criteria

Migration is considered successful when:
- ✅ Encrypted database running and accessible
- ✅ Applications connected to encrypted database
- ✅ Zero data loss verified
- ✅ Performance metrics within acceptable range
- ✅ No errors in application logs
- ✅ Replication cleaned up
- ✅ Team notified and documentation updated
- ✅ Stakeholders satisfied

---

## Contact Information

**Migration Team**:
- Lead Engineer: ___________________________
- DBA: ___________________________
- DevOps: ___________________________
- Application Team: ___________________________

**Escalation**:
- Level 1: ___________________________
- Level 2: ___________________________
- Level 3: ___________________________

**Emergency Contacts**:
- On-call: ___________________________
- Manager: ___________________________

---

## Notes and Observations

### What Went Well
```




```

### Issues Encountered
```




```

### Lessons Learned
```




```

### Recommendations for Next Time
```




```

---

## Sign-off

**Migration Completed By**: ___________________________

**Date**: ___________________________

**Sign-off**: ___________________________

**Verified By**: ___________________________

**Date**: ___________________________

**Sign-off**: ___________________________

---

**Total Migration Time**: ___________

**Downtime Duration**: ___________

**Status**: ⬜ Successful | ⬜ Successful with Issues | ⬜ Failed

---

## Appendix

### Useful Commands

```bash
# Check replication status
python rds_encryption_automation.py --config databases.json --action verify --database <name>

# Monitor in real-time
python monitor_replication.py --config databases.json --database <name>

# Get database status
./aws_helper.sh check-status <db-instance>

# Connect to database
psql -h <endpoint> -U <user> -d <database>

# Check replication slots
SELECT * FROM pg_replication_slots;

# Check publications
SELECT * FROM pg_publication;

# Check subscriptions
SELECT * FROM pg_subscription;
```

### Log Files
- Main log: `rds_encryption_migration_YYYYMMDD_HHMMSS.log`
- AWS CloudWatch: `/aws/rds/instance/<db-instance>/postgresql`

### Configuration Files
- Database config: `databases.json`
- AWS config: `~/.aws/config`
- AWS credentials: `~/.aws/credentials`
