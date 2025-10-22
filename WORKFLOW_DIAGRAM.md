# RDS PostgreSQL Encryption Migration - Visual Workflow

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                    BEFORE MIGRATION                                 │
└─────────────────────────────────────────────────────────────────────┘

    ┌──────────────┐
    │ Application  │
    │   Servers    │
    └──────┬───────┘
           │
           │ Read/Write
           ▼
    ┌──────────────┐
    │ Unencrypted  │
    │ RDS Database │
    │  (Source)    │
    └──────────────┘


┌─────────────────────────────────────────────────────────────────────┐
│                    DURING MIGRATION                                 │
└─────────────────────────────────────────────────────────────────────┘

    ┌──────────────┐
    │ Application  │
    │   Servers    │
    └──────┬───────┘
           │
           │ Read/Write (Still active)
           ▼
    ┌──────────────┐          Logical Replication          ┌──────────────┐
    │ Unencrypted  │ ════════════════════════════════════> │  Encrypted   │
    │ RDS Database │          (Publication →               │ RDS Database │
    │  (Source)    │           Subscription)               │   (Target)   │
    └──────────────┘                                       └──────────────┘
         │                                                        │
         │ Publication                                            │ Subscription
         │ + Slot                                                 │ (Receiving)
         └────────────────────────────────────────────────────────┘


┌─────────────────────────────────────────────────────────────────────┐
│                    AFTER MIGRATION                                  │
└─────────────────────────────────────────────────────────────────────┘

    ┌──────────────┐
    │ Application  │
    │   Servers    │
    └──────┬───────┘
           │
           │ Read/Write (Switched)
           ▼
    ┌──────────────┐                                       ┌──────────────┐
    │ Encrypted    │                                       │  Unencrypted │
    │ RDS Database │                                       │ RDS Database │
    │  (Active)    │                                       │    (Old)     │
    └──────────────┘                                       └──────────────┘
         (Can be deleted after verification)
```

## Detailed Migration Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│  PHASE 1: PREPARATION                                               │
└─────────────────────────────────────────────────────────────────────┘

    AWS Console/CLI
         │
         ├─> Create Custom Parameter Group
         │   └─> Set rds.logical_replication = 1
         │
         ├─> Attach to Source Database
         │
         └─> Reboot Database
             └─> wal_level = logical ✓


┌─────────────────────────────────────────────────────────────────────┐
│  PHASE 2: SOURCE DATABASE SETUP                                     │
└─────────────────────────────────────────────────────────────────────┘

    rds_encryption_automation.py --action setup-source
         │
         ├─> Connect to Source Database
         │   └─> Verify logical replication enabled
         │
         ├─> Create Publication
         │   └─> CREATE PUBLICATION <name> FOR ALL TABLES
         │       └─> Captures: INSERT, UPDATE, DELETE
         │
         └─> Create Replication Slot
             └─> pg_create_logical_replication_slot('<name>', 'pgoutput')
                 └─> Retains WAL logs for replication

    Result: Source ready to stream changes ✓


┌─────────────────────────────────────────────────────────────────────┐
│  PHASE 3: CREATE ENCRYPTED DATABASE                                 │
└─────────────────────────────────────────────────────────────────────┘

    aws_helper.sh OR Manual AWS Commands
         │
         ├─> Step 1: Create Snapshot
         │   └─> aws rds create-db-snapshot
         │       └─> Captures current state + LSN
         │
         ├─> Step 2: Copy with Encryption
         │   └─> aws rds copy-db-snapshot --kms-key-id <key>
         │       └─> Creates encrypted copy
         │
         └─> Step 3: Restore Encrypted Snapshot
             └─> aws rds restore-db-instance-from-db-snapshot
                 └─> New encrypted database created
                     └─> Contains data up to snapshot LSN

    Result: Encrypted database exists (but not synced yet)


┌─────────────────────────────────────────────────────────────────────┐
│  PHASE 4: TARGET DATABASE SETUP                                     │
└─────────────────────────────────────────────────────────────────────┘

    rds_encryption_automation.py --action setup-target
         │
         ├─> Step 1: Create Subscription
         │   └─> CREATE SUBSCRIPTION <name>
         │       CONNECTION 'host=<source>...'
         │       PUBLICATION <name>
         │       WITH (copy_data=false, enabled=false, ...)
         │
         ├─> Step 2: Get LSN from Logs
         │   └─> aws logs filter-log-events
         │       └─> Find "invalid record length at 0/XXXXXXXX"
         │           └─> This is the snapshot LSN
         │
         ├─> Step 3: Advance Replication Origin
         │   └─> pg_replication_origin_advance('<origin>', '<LSN>')
         │       └─> Tells target: "I already have data up to this LSN"
         │
         └─> Step 4: Enable Subscription
             └─> ALTER SUBSCRIPTION <name> ENABLE
                 └─> Starts streaming changes from source

    Result: Replication active, target catching up ✓


┌─────────────────────────────────────────────────────────────────────┐
│  PHASE 5: MONITOR REPLICATION                                       │
└─────────────────────────────────────────────────────────────────────┘

    monitor_replication.py
         │
         └─> Continuously checks:
             │
             ├─> Current WAL LSN on source
             ├─> Confirmed flush LSN on target
             └─> LSN Distance = Current - Flushed
                 │
                 ├─> Distance > 10000: 🔴 High lag
                 ├─> Distance > 1000:  🟡 Minor lag
                 ├─> Distance > 0:     🟢 Nearly synced
                 └─> Distance = 0:     ✅ FULLY SYNCED

    Wait until: LSN Distance = 0


┌─────────────────────────────────────────────────────────────────────┐
│  PHASE 6: APPLICATION CUTOVER                                       │
└─────────────────────────────────────────────────────────────────────┘

    Manual Steps
         │
         ├─> 1. Stop Application Writes
         │   └─> Scale down / maintenance mode
         │
         ├─> 2. Final Verification
         │   └─> Confirm LSN Distance = 0
         │
         ├─> 3. Update Connection Strings
         │   └─> Point to encrypted database endpoint
         │
         └─> 4. Start Applications
             └─> Applications now using encrypted database

    Result: Migration complete, apps on encrypted DB ✓


┌─────────────────────────────────────────────────────────────────────┐
│  PHASE 7: CLEANUP                                                   │
└─────────────────────────────────────────────────────────────────────┘

    rds_encryption_automation.py --action cleanup
         │
         ├─> Drop Subscription (on target)
         │   └─> DROP SUBSCRIPTION <name>
         │
         ├─> Drop Replication Slot (on source)
         │   └─> pg_drop_replication_slot('<name>')
         │
         └─> Drop Publication (on source)
             └─> DROP PUBLICATION <name>

    aws_helper.sh (after verification period)
         │
         ├─> Delete Snapshots
         └─> Delete Source Database

    Result: Clean environment, only encrypted DB remains ✓
```

## Data Flow During Replication

```
┌─────────────────────────────────────────────────────────────────────┐
│  HOW LOGICAL REPLICATION WORKS                                      │
└─────────────────────────────────────────────────────────────────────┘

SOURCE DATABASE:
    
    Application writes data
           │
           ▼
    ┌──────────────┐
    │   Tables     │
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐
    │  WAL Logs    │  ◄─── Write-Ahead Logs capture all changes
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐
    │ Publication  │  ◄─── Filters which tables to replicate
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐
    │ Replication  │  ◄─── Holds WAL logs for subscribers
    │    Slot      │
    └──────┬───────┘
           │
           │ Network
           │ (Logical Decoding via pgoutput plugin)
           │
           ▼

TARGET DATABASE:

    ┌──────────────┐
    │ Subscription │  ◄─── Receives changes from publication
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐
    │  Apply WAL   │  ◄─── Applies INSERT/UPDATE/DELETE
    │   Changes    │
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐
    │   Tables     │  ◄─── Data synchronized
    └──────────────┘
```

## LSN (Log Sequence Number) Explained

```
┌─────────────────────────────────────────────────────────────────────┐
│  UNDERSTANDING LSN                                                  │
└─────────────────────────────────────────────────────────────────────┘

LSN = Log Sequence Number (format: 0/XXXXXXXX)
    │
    └─> Unique identifier for position in WAL log
        Like a bookmark in a book


TIMELINE:

    Snapshot Created
         │
         │ LSN: 0/20000110  ◄─── This is captured in snapshot
         │
    ─────┴─────────────────────────────────────────────────────────>
    │                                                              │
    │ Changes before this LSN                                      │
    │ are in the snapshot                                          │
    │                                                              │
    └──────────────────────────────────────────────────────────────┘
                                                                   │
                                                                   │
    ┌──────────────────────────────────────────────────────────────┘
    │
    │ Changes after this LSN
    │ need to be replicated
    │
    └─────────────────────────────────────────────────────────────>
         │                                                        │
         │ Replication                                            │
         │ streams these                                          │
         │ changes                                                │
         │                                                        │
         └────────────────────────────────────────────────────────┘


WHY WE NEED TO ADVANCE REPLICATION ORIGIN:

    Without advancing:
        Target thinks: "I have no data, send me everything"
        Source tries: "Sending all data from beginning"
        Result: ❌ Duplicate data, conflicts, errors

    With advancing to snapshot LSN:
        Target thinks: "I have data up to 0/20000110"
        Source sends: "Only changes after 0/20000110"
        Result: ✅ Clean replication, no duplicates
```

## Script Interaction Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│  HOW THE SCRIPTS WORK TOGETHER                                      │
└─────────────────────────────────────────────────────────────────────┘

    ┌─────────────────────┐
    │  databases.json     │  ◄─── Configuration
    │  (Your config)      │
    └──────────┬──────────┘
               │
               │ Read by all scripts
               │
    ┏━━━━━━━━━┻━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
    ┃                                                      ┃
    ▼                          ▼                          ▼
┌─────────────┐      ┌──────────────────┐      ┌─────────────────┐
│ aws_helper  │      │ rds_encryption   │      │ monitor_        │
│   .sh       │      │ _automation.py   │      │ replication.py  │
└─────┬───────┘      └────────┬─────────┘      └────────┬────────┘
      │                       │                         │
      │ AWS CLI               │ psycopg2                │ psycopg2
      │                       │                         │
      ▼                       ▼                         ▼
┌─────────────┐      ┌──────────────────┐      ┌─────────────────┐
│ AWS RDS     │      │ PostgreSQL       │      │ PostgreSQL      │
│ (Snapshots, │      │ (Publications,   │      │ (Replication    │
│  Restore)   │      │  Subscriptions)  │      │  Status)        │
└─────────────┘      └──────────────────┘      └─────────────────┘


TYPICAL WORKFLOW:

1. rds_encryption_automation.py --action setup-source
   └─> Creates publication and slot

2. aws_helper.sh create-snapshot
   └─> Creates RDS snapshot

3. aws_helper.sh copy-snapshot
   └─> Copies with encryption

4. aws_helper.sh restore
   └─> Restores encrypted database

5. aws_helper.sh get-lsn
   └─> Gets LSN from CloudWatch

6. rds_encryption_automation.py --action setup-target --lsn <lsn>
   └─> Creates subscription and enables replication

7. monitor_replication.py
   └─> Monitors until synced

8. [Manual cutover]

9. rds_encryption_automation.py --action cleanup
   └─> Removes replication artifacts
```

## Error Handling Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│  WHAT HAPPENS IF SOMETHING GOES WRONG                               │
└─────────────────────────────────────────────────────────────────────┘

    Every operation
         │
         ├─> Try operation
         │   │
         │   ├─> Success ✓
         │   │   └─> Log success
         │   │       └─> Continue to next step
         │   │
         │   └─> Failure ✗
         │       └─> Log error with details
         │           └─> Return False
         │               └─> Script stops
         │                   └─> Review logs
         │                       └─> Fix issue
         │                           └─> Re-run from this step
         │
         └─> Logs written to:
             └─> rds_encryption_migration_YYYYMMDD_HHMMSS.log


    Safety prompts for destructive operations:
         │
         ├─> "Publication already exists. Drop and recreate? (yes/no)"
         ├─> "Replication slot exists. Drop and recreate? (yes/no)"
         └─> "Delete database? Create final snapshot? (yes/no)"


    Rollback scenarios:
         │
         ├─> Before cutover:
         │   └─> Just stop the process
         │       └─> Source database still active
         │           └─> No impact to applications
         │
         └─> After cutover:
             └─> Revert connection strings
                 └─> Point back to source database
                     └─> Applications back online
```

## Performance Considerations

```
┌─────────────────────────────────────────────────────────────────────┐
│  FACTORS AFFECTING MIGRATION TIME                                   │
└─────────────────────────────────────────────────────────────────────┘

    Database Size
         │
         ├─> Snapshot time: ~10-30 min for 10-50GB
         ├─> Copy time: ~10-30 min for 10-50GB
         └─> Restore time: ~10-20 min

    Write Activity
         │
         ├─> High writes = More WAL logs
         ├─> More WAL = Longer to catch up
         └─> Solution: Migrate during low-traffic hours

    Network Bandwidth
         │
         ├─> Replication streams over network
         ├─> Limited bandwidth = Slower replication
         └─> Solution: Same region, VPC peering

    Target Instance Size
         │
         ├─> Smaller instance = Slower to apply changes
         ├─> CPU/Memory constrained = Lag increases
         └─> Solution: Temporarily scale up during migration

    Replication Slot Disk Usage
         │
         ├─> Slot retains WAL logs
         ├─> Long migration = More WAL = More disk
         └─> Solution: Monitor disk space, migrate quickly
```

## Security Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  SECURITY LAYERS                                                    │
└─────────────────────────────────────────────────────────────────────┘

    ┌─────────────────────────────────────────────────────────────┐
    │  Network Security                                           │
    │  ├─> VPC Security Groups                                    │
    │  ├─> Network ACLs                                           │
    │  └─> VPN / Bastion Host                                     │
    └─────────────────────────────────────────────────────────────┘
                              │
                              ▼
    ┌─────────────────────────────────────────────────────────────┐
    │  Connection Security                                        │
    │  ├─> SSL/TLS for PostgreSQL connections                    │
    │  ├─> IAM Database Authentication (optional)                │
    │  └─> Password authentication                               │
    └─────────────────────────────────────────────────────────────┘
                              │
                              ▼
    ┌─────────────────────────────────────────────────────────────┐
    │  Data Security                                              │
    │  ├─> KMS Encryption at Rest (target database)              │
    │  ├─> Encrypted Snapshots                                   │
    │  └─> Encrypted Backups                                     │
    └─────────────────────────────────────────────────────────────┘
                              │
                              ▼
    ┌─────────────────────────────────────────────────────────────┐
    │  Credential Security                                        │
    │  ├─> .gitignore prevents commits                           │
    │  ├─> File permissions (chmod 600)                          │
    │  ├─> AWS Secrets Manager (recommended)                     │
    │  └─> Environment variables                                 │
    └─────────────────────────────────────────────────────────────┘
                              │
                              ▼
    ┌─────────────────────────────────────────────────────────────┐
    │  Audit & Compliance                                         │
    │  ├─> Comprehensive logging                                 │
    │  ├─> CloudWatch logs                                       │
    │  ├─> RDS audit logs                                        │
    │  └─> Migration checklist                                   │
    └─────────────────────────────────────────────────────────────┘
```

---

**This diagram provides a visual reference for understanding the complete migration workflow.**

For detailed instructions, see:
- **QUICKSTART.md** - Step-by-step guide
- **README.md** - Complete documentation
- **MIGRATION_CHECKLIST.md** - Execution checklist
