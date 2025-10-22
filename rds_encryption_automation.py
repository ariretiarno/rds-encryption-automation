#!/usr/bin/env python3
"""
RDS PostgreSQL Encryption Migration Automation Script

This script automates the database-side operations for encrypting RDS PostgreSQL
instances with minimal downtime using logical replication.

Based on: https://aws.amazon.com/blogs/database/encrypt-amazon-rds-for-postgresql-and-amazon-aurora-postgresql-database-with-minimal-downtime/
"""

import json
import sys
import argparse
import logging
from typing import Dict, List, Optional
from datetime import datetime
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'rds_encryption_migration_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class PostgreSQLReplicationManager:
    """Manages PostgreSQL logical replication setup for encryption migration."""
    
    def __init__(self, config: Dict):
        """
        Initialize the replication manager.
        
        Args:
            config: Database configuration dictionary
        """
        self.config = config
        self.db_name = config['database']
        
        # Sanitize names: replace special characters with underscores
        # PostgreSQL identifiers can't contain - or . without quoting
        sanitized_db_name = self.db_name.replace('-', '_').replace('.', '_')
        
        self.publication_name = config.get('publication_name', f"{sanitized_db_name}_encryption_pub")
        
        # Slot names have stricter rules: only lowercase letters, numbers, and underscores
        raw_slot_name = config.get('slot_name', f"{sanitized_db_name}_encryption_slot")
        self.slot_name = self._sanitize_slot_name(raw_slot_name)
        
        # Log if slot name was changed
        if raw_slot_name != self.slot_name:
            logger.info(f"Sanitized slot name: '{raw_slot_name}' → '{self.slot_name}'")
    
    @staticmethod
    def _sanitize_slot_name(slot_name: str) -> str:
        """
        Sanitize a replication slot name.
        
        PostgreSQL replication slot names must:
        - Contain only lowercase letters, numbers, and underscores
        - Not start with a number
        - Be at most 63 characters
        
        Args:
            slot_name: The slot name to sanitize
            
        Returns:
            Sanitized slot name safe for PostgreSQL
        """
        import re
        
        # Convert to lowercase
        sanitized = slot_name.lower()
        
        # Replace invalid characters with underscores
        # Valid: a-z, 0-9, underscore
        sanitized = re.sub(r'[^a-z0-9_]', '_', sanitized)
        
        # Ensure it doesn't start with a number
        if sanitized and sanitized[0].isdigit():
            sanitized = f"slot_{sanitized}"
        
        # Ensure it's not empty
        if not sanitized:
            sanitized = "replication_slot"
        
        # Truncate to 63 characters (PostgreSQL identifier limit)
        if len(sanitized) > 63:
            sanitized = sanitized[:63]
        
        return sanitized
    
    @staticmethod
    def _quote_identifier(identifier: str) -> str:
        """
        Properly quote a PostgreSQL identifier.
        
        Args:
            identifier: The identifier to quote
            
        Returns:
            Quoted identifier safe for use in SQL
        """
        # Escape any double quotes in the identifier
        escaped = identifier.replace('"', '""')
        return f'"{escaped}"'
        
    def _get_connection(self, db_config: Dict, autocommit: bool = False):
        """
        Create a database connection.
        
        Args:
            db_config: Database connection parameters
            autocommit: Whether to enable autocommit mode
            
        Returns:
            psycopg2 connection object
        """
        try:
            conn = psycopg2.connect(
                host=db_config['host'],
                port=db_config.get('port', 5432),
                database=db_config['database'],
                user=db_config['user'],
                password=db_config['password'],
                connect_timeout=30
            )
            if autocommit:
                conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
            logger.info(f"Successfully connected to {db_config['host']}/{db_config['database']}")
            return conn
        except Exception as e:
            logger.error(f"Failed to connect to {db_config['host']}/{db_config['database']}: {str(e)}")
            raise
    
    def verify_logical_replication_enabled(self, conn) -> bool:
        """
        Verify that logical replication is enabled on the database.
        
        Args:
            conn: Database connection
            
        Returns:
            True if logical replication is enabled, False otherwise
        """
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT name, setting 
                    FROM pg_settings 
                    WHERE name IN ('wal_level', 'rds.logical_replication')
                """)
                settings = dict(cur.fetchall())
                
                wal_level = settings.get('wal_level', '')
                logical_replication = settings.get('rds.logical_replication', '')
                
                logger.info(f"wal_level: {wal_level}, rds.logical_replication: {logical_replication}")
                
                if wal_level == 'logical' and logical_replication in ('on', '1'):
                    logger.info("✓ Logical replication is properly configured")
                    return True
                else:
                    logger.warning("✗ Logical replication is NOT properly configured")
                    logger.warning("Please set rds.logical_replication=1 in parameter group and reboot")
                    return False
        except Exception as e:
            logger.error(f"Error verifying logical replication: {str(e)}")
            return False
    
    def create_publication(self, source_config: Dict, tables: Optional[List[str]] = None) -> bool:
        """
        Create publication on the source (unencrypted) database.
        
        Args:
            source_config: Source database configuration
            tables: Optional list of specific tables. If None, creates for ALL TABLES
            
        Returns:
            True if successful, False otherwise
        """
        logger.info(f"Creating publication '{self.publication_name}' on source database...")
        
        try:
            conn = self._get_connection(source_config, autocommit=True)
            
            # Verify logical replication is enabled
            if not self.verify_logical_replication_enabled(conn):
                logger.error("Cannot create publication: logical replication not enabled")
                conn.close()
                return False
            
            with conn.cursor() as cur:
                # Check if publication already exists
                cur.execute("""
                    SELECT pubname FROM pg_publication WHERE pubname = %s
                """, (self.publication_name,))
                
                if cur.fetchone():
                    logger.warning(f"Publication '{self.publication_name}' already exists")
                    print("\n" + "="*80)
                    print(f"⚠️  PUBLICATION '{self.publication_name}' ALREADY EXISTS")
                    print("="*80)
                    sys.stdout.flush()
                    user_input = input("Drop and recreate? (yes/no): ").strip().lower()
                    if user_input == 'yes':
                        cur.execute(f"DROP PUBLICATION {self._quote_identifier(self.publication_name)}")
                        logger.info(f"Dropped existing publication '{self.publication_name}'")
                    else:
                        logger.info("Skipping publication creation")
                        conn.close()
                        return True
                
                # Create publication
                if tables:
                    tables_str = ', '.join(tables)
                    create_sql = f"CREATE PUBLICATION {self._quote_identifier(self.publication_name)} FOR TABLE {tables_str}"
                else:
                    create_sql = f"CREATE PUBLICATION {self._quote_identifier(self.publication_name)} FOR ALL TABLES"
                
                cur.execute(create_sql)
                logger.info(f"✓ Created publication: {self.publication_name}")
                
                # Verify publication
                cur.execute("SELECT * FROM pg_publication WHERE pubname = %s", (self.publication_name,))
                pub = cur.fetchone()
                logger.info(f"Publication details: {pub}")
            
            conn.close()
            return True
            
        except Exception as e:
            logger.error(f"Error creating publication: {str(e)}")
            return False
    
    def create_replication_slot(self, source_config: Dict) -> bool:
        """
        Create logical replication slot on the source database.
        
        Args:
            source_config: Source database configuration
            
        Returns:
            True if successful, False otherwise
        """
        logger.info(f"Creating replication slot '{self.slot_name}' on source database...")
        
        try:
            conn = self._get_connection(source_config, autocommit=True)
            
            with conn.cursor() as cur:
                # Check if slot already exists
                cur.execute("""
                    SELECT slot_name FROM pg_replication_slots WHERE slot_name = %s
                """, (self.slot_name,))
                
                if cur.fetchone():
                    logger.warning(f"Replication slot '{self.slot_name}' already exists")
                    print("\n" + "="*80)
                    print(f"⚠️  REPLICATION SLOT '{self.slot_name}' ALREADY EXISTS")
                    print("="*80)
                    sys.stdout.flush()
                    user_input = input("Drop and recreate? (yes/no): ").strip().lower()
                    if user_input == 'yes':
                        cur.execute(f"SELECT pg_drop_replication_slot('{self.slot_name}')")
                        logger.info(f"Dropped existing replication slot '{self.slot_name}'")
                    else:
                        logger.info("Skipping replication slot creation")
                        conn.close()
                        return True
                
                # Create replication slot
                cur.execute("""
                    SELECT * FROM pg_create_logical_replication_slot(%s, 'pgoutput')
                """, (self.slot_name,))
                
                result = cur.fetchone()
                logger.info(f"✓ Created replication slot: {result}")
                
                # Verify replication slot
                cur.execute("SELECT * FROM pg_replication_slots WHERE slot_name = %s", (self.slot_name,))
                slot = cur.fetchone()
                logger.info(f"Replication slot details: {slot}")
            
            conn.close()
            return True
            
        except Exception as e:
            logger.error(f"Error creating replication slot: {str(e)}")
            return False
    
    def setup_source_database(self, source_config: Dict, tables: Optional[List[str]] = None) -> bool:
        """
        Complete setup on source (unencrypted) database: publication + replication slot.
        
        Args:
            source_config: Source database configuration
            tables: Optional list of specific tables
            
        Returns:
            True if successful, False otherwise
        """
        logger.info("=" * 80)
        logger.info(f"SETTING UP SOURCE DATABASE: {source_config['host']}/{source_config['database']}")
        logger.info("=" * 80)
        
        # Create publication
        if not self.create_publication(source_config, tables):
            return False
        
        # Create replication slot
        if not self.create_replication_slot(source_config):
            return False
        
        logger.info("✓ Source database setup completed successfully")
        return True
    
    def create_subscription(self, target_config: Dict, source_config: Dict, 
                          copy_data: bool = False) -> str:
        """
        Create subscription on the target (encrypted) database.
        
        Args:
            target_config: Target database configuration
            source_config: Source database configuration
            copy_data: Whether to copy initial data (should be False for snapshot restore)
            
        Returns:
            'created' if subscription was created
            'skipped' if subscription already exists and user chose to skip
            'failed' if an error occurred
        """
        logger.info(f"Creating subscription '{self.publication_name}' on target database...")
        
        try:
            conn = self._get_connection(target_config, autocommit=True)
            
            # Verify logical replication is enabled
            if not self.verify_logical_replication_enabled(conn):
                logger.error("Cannot create subscription: logical replication not enabled")
                conn.close()
                return 'failed'
            
            with conn.cursor() as cur:
                # Check if subscription already exists
                cur.execute("""
                    SELECT subname FROM pg_subscription WHERE subname = %s
                """, (self.publication_name,))
                
                if cur.fetchone():
                    logger.warning(f"Subscription '{self.publication_name}' already exists")
                    print("\n" + "="*80)
                    print(f"⚠️  SUBSCRIPTION '{self.publication_name}' ALREADY EXISTS")
                    print("="*80)
                    sys.stdout.flush()
                    user_input = input("Drop and recreate? (yes/no): ").strip().lower()
                    if user_input == 'yes':
                        # Properly drop subscription: disable -> detach slot -> drop
                        logger.info(f"Disabling subscription '{self.publication_name}'...")
                        cur.execute(f"ALTER SUBSCRIPTION {self._quote_identifier(self.publication_name)} DISABLE")
                        
                        logger.info(f"Detaching slot from subscription '{self.publication_name}'...")
                        cur.execute(f"ALTER SUBSCRIPTION {self._quote_identifier(self.publication_name)} SET (slot_name = NONE)")
                        
                        logger.info(f"Dropping subscription '{self.publication_name}'...")
                        cur.execute(f"DROP SUBSCRIPTION {self._quote_identifier(self.publication_name)}")
                        
                        logger.info(f"✓ Dropped existing subscription '{self.publication_name}'")
                    else:
                        logger.info("Skipping subscription creation and all subsequent setup steps")
                        conn.close()
                        return 'skipped'
                
                # Build connection string
                conn_string = (
                    f"host={source_config['host']} "
                    f"port={source_config.get('port', 5432)} "
                    f"user={source_config['user']} "
                    f"password={source_config['password']} "
                    f"dbname={source_config['database']}"
                )
                
                # Create subscription (initially disabled)
                create_sub_sql = f"""
                    CREATE SUBSCRIPTION {self._quote_identifier(self.publication_name)}
                    CONNECTION '{conn_string}'
                    PUBLICATION {self._quote_identifier(self.publication_name)}
                    WITH (
                        copy_data = {str(copy_data).lower()},
                        create_slot = false,
                        enabled = false,
                        synchronous_commit = false,
                        connect = true,
                        slot_name = '{self.slot_name}'
                    )
                """
                
                cur.execute(create_sub_sql)
                logger.info(f"✓ Created subscription: {self.publication_name} (disabled)")
                
                # Verify subscription
                cur.execute("SELECT * FROM pg_subscription WHERE subname = %s", (self.publication_name,))
                sub = cur.fetchone()
                logger.info(f"Subscription details: {sub}")
            
            conn.close()
            return 'created'
            
        except Exception as e:
            logger.error(f"Error creating subscription: {str(e)}")
            return 'failed'
    
    def get_lsn_from_source(self, source_config: Dict) -> Optional[str]:
        """
        Get the current LSN directly from the source database.
        
        This is useful as an alternative to getting LSN from CloudWatch logs.
        The LSN from the source represents the current replication position.
        
        Args:
            source_config: Source database configuration
            
        Returns:
            LSN string (format: 0/XXXXXXXX) or None if failed
        """
        logger.info("Getting current LSN from source database...")
        
        try:
            conn = self._get_connection(source_config)
            
            with conn.cursor() as cur:
                # Get the confirmed flush LSN from the replication slot
                cur.execute("""
                    SELECT confirmed_flush_lsn
                    FROM pg_replication_slots
                    WHERE slot_name = %s AND slot_type = 'logical'
                """, (self.slot_name,))
                
                result = cur.fetchone()
                
                if result and result[0]:
                    lsn = result[0]
                    logger.info(f"✓ Current LSN from source: {lsn}")
                    conn.close()
                    return lsn
                else:
                    logger.warning(f"Could not get LSN from replication slot '{self.slot_name}'")
                    
                    # Fallback: get current WAL LSN
                    cur.execute("SELECT pg_current_wal_lsn()")
                    result = cur.fetchone()
                    if result and result[0]:
                        lsn = result[0]
                        logger.info(f"✓ Current WAL LSN from source: {lsn}")
                        conn.close()
                        return lsn
            
            conn.close()
            return None
            
        except Exception as e:
            logger.error(f"Error getting LSN from source: {str(e)}")
            return None
    
    def get_lsn_from_logs_instruction(self, target_config: Dict) -> str:
        """
        Provide instructions for getting LSN from logs.
        
        Args:
            target_config: Target database configuration
            
        Returns:
            Instruction string
        """
        db_identifier = target_config.get('db_identifier', 'encrypted-db')
        
        instruction = f"""
        
        ╔════════════════════════════════════════════════════════════════════════════╗
        ║                    GET LSN FOR REPLICATION                                 ║
        ╚════════════════════════════════════════════════════════════════════════════╝
        
        After restoring the encrypted database from snapshot, you need to get the LSN.
        
        Option 1: Get from Source Database (RECOMMENDED - Easiest)
        ──────────────────────────────────────────────────────────
        The script can automatically query the source database for the current LSN.
        This is the simplest and most reliable method.
        
        Press Enter to auto-fetch LSN from source database, or enter LSN manually below.
        
        Option 2: Using AWS Console
        ─────────────────────────────
        1. Go to RDS Console → Your encrypted database
        2. Click "Logs & events" tab
        3. Open the most recent PostgreSQL log file
        4. Search for "invalid record length"
        5. Copy the LSN value (format: 0/XXXXXXXX)
        
        Option 3: Using AWS CLI
        ───────────────────────
        Run this command:
        
        aws logs filter-log-events \\
            --log-group-name /aws/rds/instance/{db_identifier}/postgresql \\
            --filter-pattern 'invalid record length'
        
        Look for the LSN in the output (format: 0/XXXXXXXX)
        
        ════════════════════════════════════════════════════════════════════════════
        """
        return instruction
    
    def advance_replication_origin(self, target_config: Dict, lsn: str) -> bool:
        """
        Advance the replication origin to the specified LSN.
        
        This uses a session-based approach to avoid the "origin is already active" error.
        
        Args:
            target_config: Target database configuration
            lsn: LSN value to advance to (format: 0/XXXXXXXX)
            
        Returns:
            True if successful, False otherwise
        """
        logger.info(f"Advancing replication origin to LSN: {lsn}")
        
        try:
            conn = self._get_connection(target_config, autocommit=True)
            
            with conn.cursor() as cur:
                # Get replication origin information with subscription status
                cur.execute("""
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
                """)
                origins = cur.fetchall()
                
                if not origins:
                    logger.error("No replication origin found")
                    conn.close()
                    return False
                
                logger.info(f"Found {len(origins)} replication origin(s)")
                
                # Automatically select the best origin
                origin_name = None
                
                # Strategy 1: Find INACTIVE origins (disabled subscriptions)
                inactive_origins = [o for o in origins if o[4] == 'INACTIVE']
                
                # Strategy 2: Find the origin matching our subscription name
                matching_origins = [o for o in origins if o[2] == self.publication_name]
                
                # Strategy 3: Find ORPHANED origins (no subscription)
                orphaned_origins = [o for o in origins if o[4] == 'ORPHANED']
                
                if matching_origins:
                    # Prefer the origin that matches our subscription
                    origin_name = matching_origins[0][1]
                    status = matching_origins[0][4]
                    logger.info(f"✓ Auto-selected origin matching subscription: {origin_name} (Status: {status})")
                elif inactive_origins:
                    # Use an inactive origin
                    origin_name = inactive_origins[0][1]
                    logger.info(f"✓ Auto-selected inactive origin: {origin_name}")
                elif len(origins) == 1:
                    # Only one origin, use it (session-based approach handles active origins)
                    origin_name = origins[0][1]
                    status = origins[0][4]
                    logger.info(f"✓ Using only available origin: {origin_name} (Status: {status})")
                elif orphaned_origins:
                    # Use an orphaned origin
                    origin_name = orphaned_origins[0][1]
                    logger.info(f"✓ Auto-selected orphaned origin: {origin_name}")
                else:
                    # Multiple active origins - need user input
                    print("\n" + "="*80)
                    print("MULTIPLE ACTIVE REPLICATION ORIGINS FOUND")
                    print("="*80)
                    for idx, (oid, name, sub_name, enabled, status) in enumerate(origins, 1):
                        print(f"{idx}. OID: {oid}, Name: {name}")
                        print(f"   Subscription: {sub_name or 'None'}, Status: {status}")
                    print("="*80)
                    sys.stdout.flush()
                    
                    while True:
                        choice = input(f"Select origin to advance (1-{len(origins)}): ").strip()
                        try:
                            choice_idx = int(choice) - 1
                            if 0 <= choice_idx < len(origins):
                                origin_name = origins[choice_idx][1]
                                logger.info(f"User selected origin: {origin_name}")
                                break
                            else:
                                print(f"Please enter a number between 1 and {len(origins)}")
                        except ValueError:
                            print("Please enter a valid number")
                
                # Use session-based approach to advance the origin
                # This avoids the "origin is already active" error
                logger.info(f"Creating session for origin: {origin_name}")
                
                # Setup replication origin session
                cur.execute("""
                    SELECT pg_replication_origin_session_setup(%s)
                """, (origin_name,))
                
                logger.info(f"Advancing origin to LSN: {lsn}")
                
                # Advance the replication origin
                cur.execute("""
                    SELECT pg_replication_origin_xact_setup(%s, %s)
                """, (lsn, '1970-01-01'))  # timestamp is required but not critical for this use case
                
                # Reset the session
                cur.execute("SELECT pg_replication_origin_session_reset()")
                
                logger.info(f"✓ Advanced replication origin '{origin_name}' to LSN {lsn}")
            
            conn.close()
            return True
            
        except Exception as e:
            logger.error(f"Error advancing replication origin: {str(e)}")
            # Try to reset session if it was setup
            try:
                conn = self._get_connection(target_config, autocommit=True)
                with conn.cursor() as cur:
                    cur.execute("SELECT pg_replication_origin_session_reset()")
                conn.close()
            except:
                pass
            return False
    
    def enable_subscription(self, target_config: Dict) -> bool:
        """
        Enable the subscription to start replication.
        
        Args:
            target_config: Target database configuration
            
        Returns:
            True if successful, False otherwise
        """
        logger.info(f"Enabling subscription '{self.publication_name}'...")
        
        try:
            conn = self._get_connection(target_config, autocommit=True)
            
            with conn.cursor() as cur:
                cur.execute(f"ALTER SUBSCRIPTION {self._quote_identifier(self.publication_name)} ENABLE")
                logger.info(f"✓ Enabled subscription: {self.publication_name}")
            
            conn.close()
            return True
            
        except Exception as e:
            logger.error(f"Error enabling subscription: {str(e)}")
            return False
    
    def verify_replication(self, source_config: Dict, wait_seconds: int = 30) -> bool:
        """
        Verify that replication is working by checking LSN distance.
        
        Args:
            source_config: Source database configuration
            wait_seconds: Seconds to wait for replication to catch up
            
        Returns:
            True if replication is working, False otherwise
        """
        logger.info("Verifying replication status...")
        
        try:
            conn = self._get_connection(source_config)
            
            time.sleep(5)  # Wait a bit for initial sync
            
            with conn.cursor() as cur:
                for i in range(wait_seconds // 5):
                    cur.execute("""
                        SELECT 
                            slot_name,
                            confirmed_flush_lsn AS flushed,
                            pg_current_wal_lsn() AS current_lsn,
                            (pg_current_wal_lsn() - confirmed_flush_lsn) AS lsn_distance
                        FROM pg_catalog.pg_replication_slots
                        WHERE slot_type = 'logical' AND slot_name = %s
                    """, (self.slot_name,))
                    
                    result = cur.fetchone()
                    if result:
                        slot_name, flushed, current_lsn, lsn_distance = result
                        logger.info(f"Replication status: flushed={flushed}, current={current_lsn}, distance={lsn_distance}")
                        
                        if lsn_distance == 0:
                            logger.info("✓ Replication is fully caught up (LSN distance = 0)")
                            conn.close()
                            return True
                    else:
                        logger.warning(f"Replication slot '{self.slot_name}' not found")
                    
                    if i < (wait_seconds // 5) - 1:
                        logger.info(f"Waiting for replication to catch up... ({(i+1)*5}s)")
                        time.sleep(5)
                
                logger.warning(f"Replication has not fully caught up after {wait_seconds}s")
                logger.info("This is normal if there's ongoing write activity. Monitor the LSN distance.")
            
            conn.close()
            return True
            
        except Exception as e:
            logger.error(f"Error verifying replication: {str(e)}")
            return False
    
    def setup_target_database(self, target_config: Dict, source_config: Dict, 
                             lsn: Optional[str] = None, skip_origin_check: bool = False,
                             auto_confirm: bool = False) -> bool:
        """
        Complete setup on target (encrypted) database: subscription + enable replication.
        
        Args:
            target_config: Target database configuration
            source_config: Source database configuration
            lsn: Optional LSN to advance to. If None, will prompt for it.
            skip_origin_check: If True, skip the origin usage check and confirmation
            
        Returns:
            True if successful, False otherwise
        """
        logger.info("=" * 80)
        logger.info(f"SETTING UP TARGET DATABASE: {target_config['host']}/{target_config['database']}")
        logger.info("=" * 80)
        
        # Create subscription
        subscription_result = self.create_subscription(target_config, source_config, copy_data=False)
        
        if subscription_result == 'failed':
            return False
        elif subscription_result == 'skipped':
            logger.info("✓ Target database setup skipped (subscription already exists)")
            return True
        
        # Get LSN
        if not lsn:
            if auto_confirm:
                # Auto-confirm mode: automatically fetch LSN from source
                logger.info("Auto-confirm mode: fetching LSN from source database...")
                lsn = self.get_lsn_from_source(source_config)
                
                if lsn:
                    logger.info(f"✓ Auto-fetched LSN from source: {lsn}")
                    logger.info(f"✓ Auto-confirmed: Using LSN {lsn}")
                else:
                    logger.error("Could not auto-fetch LSN from source in auto-confirm mode")
                    return False
            else:
                # Interactive mode: prompt user
                print(self.get_lsn_from_logs_instruction(target_config))
                lsn_input = input("\nEnter LSN manually, or press Enter to auto-fetch from source: ").strip()
                
                if not lsn_input:
                    # Auto-fetch LSN from source database
                    logger.info("Attempting to auto-fetch LSN from source database...")
                    lsn = self.get_lsn_from_source(source_config)
                    
                    if lsn:
                        logger.info(f"✓ Auto-fetched LSN from source: {lsn}")
                        confirm = input(f"Use this LSN ({lsn})? (yes/no): ").strip().lower()
                        if confirm != 'yes':
                            lsn_input = input("Enter LSN manually (format: 0/XXXXXXXX): ").strip()
                            lsn = lsn_input if lsn_input else None
                    else:
                        logger.warning("Could not auto-fetch LSN from source")
                        lsn_input = input("Enter LSN manually (format: 0/XXXXXXXX): ").strip()
                        lsn = lsn_input if lsn_input else None
                else:
                    lsn = lsn_input
        
        if not lsn:
            logger.error("LSN is required to proceed")
            return False
        
        # Check replication origin usage before advancing (unless skipped)
        if not skip_origin_check:
            logger.info("\n" + "=" * 80)
            logger.info("CHECKING REPLICATION ORIGIN USAGE")
            logger.info("=" * 80)
            self.check_origin_usage(target_config)
            
            if auto_confirm:
                # Auto-confirm mode: skip confirmation prompt
                logger.info("\n" + "=" * 80)
                logger.info("⚠️  ADVANCING REPLICATION ORIGIN (AUTO-CONFIRMED)")
                logger.info("=" * 80)
                logger.info(f"LSN to advance to: {lsn}")
                logger.info("Using session-based approach to handle active origins.")
                logger.info("=" * 80)
            else:
                # Interactive mode: confirm before proceeding
                print("\n" + "=" * 80)
                print("⚠️  ABOUT TO ADVANCE REPLICATION ORIGIN")
                print("=" * 80)
                print(f"LSN to advance to: {lsn}")
                print("The script will use session-based approach to handle active origins.")
                print("=" * 80)
                sys.stdout.flush()
                proceed = input("Proceed with advancing replication origin? (yes/no): ").strip().lower()
                
                if proceed != 'yes':
                    logger.info("User chose not to proceed with origin advancement")
                    return False
        else:
            logger.info("Skipping origin usage check (--skip-origin-check flag set)")
        
        # Advance replication origin
        if not self.advance_replication_origin(target_config, lsn):
            return False
        
        # Enable subscription
        if not self.enable_subscription(target_config):
            return False
        
        # Verify replication
        logger.info("\nWaiting for replication to sync...")
        self.verify_replication(source_config, wait_seconds=30)
        
        logger.info("✓ Target database setup completed successfully")
        return True
    
    def cleanup_replication(self, source_config: Dict, target_config: Dict) -> bool:
        """
        Clean up replication (drop subscription and publication).
        
        Args:
            source_config: Source database configuration
            target_config: Target database configuration
            
        Returns:
            True if successful, False otherwise
        """
        logger.info("=" * 80)
        logger.info("CLEANING UP REPLICATION")
        logger.info("=" * 80)
        
        success = True
        
        # Drop subscription on target (properly: disable -> detach slot -> drop)
        try:
            conn = self._get_connection(target_config, autocommit=True)
            with conn.cursor() as cur:
                # Check if subscription exists
                cur.execute("""
                    SELECT subname FROM pg_subscription WHERE subname = %s
                """, (self.publication_name,))
                
                if cur.fetchone():
                    logger.info(f"Disabling subscription '{self.publication_name}'...")
                    cur.execute(f"ALTER SUBSCRIPTION {self._quote_identifier(self.publication_name)} DISABLE")
                    
                    logger.info(f"Detaching slot from subscription '{self.publication_name}'...")
                    cur.execute(f"ALTER SUBSCRIPTION {self._quote_identifier(self.publication_name)} SET (slot_name = NONE)")
                    
                    logger.info(f"Dropping subscription '{self.publication_name}'...")
                    cur.execute(f"DROP SUBSCRIPTION {self._quote_identifier(self.publication_name)}")
                    
                    logger.info(f"✓ Dropped subscription: {self.publication_name}")
                else:
                    logger.info(f"Subscription '{self.publication_name}' does not exist, skipping")
            conn.close()
        except Exception as e:
            logger.error(f"Error dropping subscription: {str(e)}")
            success = False
        
        # Drop replication slot on source
        try:
            conn = self._get_connection(source_config, autocommit=True)
            with conn.cursor() as cur:
                cur.execute(f"SELECT pg_drop_replication_slot('{self.slot_name}')")
                logger.info(f"✓ Dropped replication slot: {self.slot_name}")
        except Exception as e:
            logger.error(f"Error dropping replication slot: {str(e)}")
            success = False
        
        # Drop publication on source
        try:
            conn = self._get_connection(source_config, autocommit=True)
            with conn.cursor() as cur:
                cur.execute(f"DROP PUBLICATION IF EXISTS {self._quote_identifier(self.publication_name)}")
                logger.info(f"✓ Dropped publication: {self.publication_name}")
            conn.close()
        except Exception as e:
            logger.error(f"Error dropping publication: {str(e)}")
            success = False
        
        if success:
            logger.info("✓ Cleanup completed successfully")
        
        return success
    
    def list_replication_origins(self, target_config: Dict) -> bool:
        """
        List all replication origins on the target database.
        
        This is useful for debugging and understanding the replication state.
        
        Args:
            target_config: Target database configuration
            
        Returns:
            True if successful, False otherwise
        """
        logger.info("Listing replication origins on target database...")
        
        try:
            conn = self._get_connection(target_config)
            
            with conn.cursor() as cur:
                # Get replication origin information
                cur.execute("""
                    SELECT 
                        roident AS oid,
                        roname AS name
                    FROM pg_replication_origin
                    ORDER BY roident
                """)
                origins = cur.fetchall()
                
                if not origins:
                    logger.info("No replication origins found")
                    print("\n" + "="*80)
                    print("NO REPLICATION ORIGINS FOUND")
                    print("="*80)
                    print("This is normal if subscription hasn't been created yet.")
                    print("="*80 + "\n")
                else:
                    print("\n" + "="*80)
                    print("REPLICATION ORIGINS")
                    print("="*80)
                    for oid, name in origins:
                        print(f"OID: {oid}")
                        print(f"  Name: {name}")
                        print("-" * 80)
                    print("="*80 + "\n")
                    logger.info(f"Found {len(origins)} replication origin(s)")
            
            conn.close()
            return True
            
        except Exception as e:
            logger.error(f"Error listing replication origins: {str(e)}")
            return False
    
    def check_origin_usage(self, target_config: Dict) -> bool:
        """
        Check which processes are using replication origins.
        
        This helps diagnose "origin is already active" errors by showing:
        - Active subscription workers
        - Processes with active origin sessions
        - Mapping between origins and subscriptions
        
        Args:
            target_config: Target database configuration
            
        Returns:
            True if successful, False otherwise
        """
        logger.info("Checking replication origin usage on target database...")
        
        try:
            conn = self._get_connection(target_config)
            
            with conn.cursor() as cur:
                print("\n" + "="*80)
                print("REPLICATION ORIGIN USAGE REPORT")
                print("="*80)
                
                # 1. List all origins
                print("\n1. ALL REPLICATION ORIGINS")
                print("-" * 80)
                cur.execute("""
                    SELECT 
                        roident AS oid,
                        roname AS name
                    FROM pg_replication_origin
                    ORDER BY roident
                """)
                origins = cur.fetchall()
                
                if not origins:
                    print("No replication origins found")
                else:
                    for oid, name in origins:
                        print(f"  OID: {oid}, Name: {name}")
                
                # 2. Check subscription workers
                print("\n2. SUBSCRIPTION WORKERS (These use replication origins)")
                print("-" * 80)
                cur.execute("""
                    SELECT 
                        s.subname AS subscription_name,
                        s.subenabled AS enabled,
                        s.subslotname AS slot_name,
                        sa.pid AS worker_pid,
                        sa.state AS worker_state,
                        sa.backend_type
                    FROM pg_subscription s
                    LEFT JOIN pg_stat_activity sa 
                        ON sa.application_name LIKE '%' || s.subname || '%'
                        OR sa.backend_type = 'logical replication worker'
                    ORDER BY s.subname
                """)
                workers = cur.fetchall()
                
                if not workers:
                    print("No subscriptions found")
                else:
                    for sub_name, enabled, slot_name, pid, state, backend_type in workers:
                        status = "ENABLED" if enabled else "DISABLED"
                        print(f"  Subscription: {sub_name} [{status}]")
                        print(f"    Slot: {slot_name}")
                        if pid:
                            print(f"    Worker PID: {pid}, State: {state}, Type: {backend_type}")
                        else:
                            print(f"    Worker: Not active")
                
                # 3. Map origins to subscriptions
                print("\n3. ORIGIN-TO-SUBSCRIPTION MAPPING")
                print("-" * 80)
                cur.execute("""
                    SELECT 
                        ro.roident AS origin_id,
                        ro.roname AS origin_name,
                        s.oid AS subscription_oid,
                        s.subname AS subscription_name,
                        s.subenabled AS is_enabled,
                        CASE 
                            WHEN s.subenabled THEN 'ACTIVE (enabled)'
                            WHEN s.subname IS NOT NULL THEN 'INACTIVE (disabled)'
                            ELSE 'ORPHANED (no subscription)'
                        END AS status
                    FROM pg_replication_origin ro
                    LEFT JOIN pg_subscription s 
                        ON ro.roname = 'pg_' || s.oid::text
                    ORDER BY ro.roident
                """)
                mappings = cur.fetchall()
                
                if not mappings:
                    print("No origin-subscription mappings found")
                else:
                    for origin_id, origin_name, sub_oid, sub_name, enabled, status in mappings:
                        print(f"  Origin {origin_id} ({origin_name})")
                        if sub_name:
                            print(f"    → Subscription: {sub_name} (OID: {sub_oid})")
                            print(f"    → Status: {status}")
                        else:
                            print(f"    → Status: {status}")
                
                # 4. Check for active sessions
                print("\n4. ACTIVE REPLICATION-RELATED PROCESSES")
                print("-" * 80)
                cur.execute("""
                    SELECT 
                        pid,
                        usename,
                        application_name,
                        state,
                        backend_type,
                        query_start
                    FROM pg_stat_activity
                    WHERE backend_type = 'logical replication worker'
                       OR backend_type = 'logical replication launcher'
                       OR application_name LIKE '%subscription%'
                    ORDER BY pid
                """)
                processes = cur.fetchall()
                
                if not processes:
                    print("No active replication processes found")
                else:
                    for pid, user, app_name, state, backend_type, query_start in processes:
                        print(f"  PID: {pid}")
                        print(f"    User: {user}, App: {app_name}")
                        print(f"    Type: {backend_type}, State: {state}")
                        print(f"    Started: {query_start}")
                
                print("\n" + "="*80)
                print("INTERPRETATION:")
                print("="*80)
                print("• If 'Status' shows 'ACTIVE (enabled)', the origin is in use")
                print("• Active subscription workers hold the origin session")
                print("• To advance origin, use session-based approach (already in script)")
                print("• Or temporarily: ALTER SUBSCRIPTION <name> DISABLE;")
                print("="*80 + "\n")
            
            conn.close()
            return True
            
        except Exception as e:
            logger.error(f"Error checking origin usage: {str(e)}")
            return False


def load_config(config_file: str) -> Dict:
    """Load configuration from JSON file."""
    try:
        with open(config_file, 'r') as f:
            config = json.load(f)
        logger.info(f"Loaded configuration from {config_file}")
        return config
    except Exception as e:
        logger.error(f"Error loading configuration: {str(e)}")
        sys.exit(1)


def process_database(db_config: Dict, action: str, lsn: Optional[str] = None, 
                    skip_origin_check: bool = False, auto_confirm: bool = False) -> bool:
    """
    Process a single database configuration.
    
    Args:
        db_config: Database configuration
        action: Action to perform (setup-source, setup-target, verify, cleanup, get-lsn, list-origins, check-origin-usage)
        lsn: Optional LSN for target setup
        skip_origin_check: If True, skip origin usage check in setup-target
        
    Returns:
        True if successful, False otherwise
    """
    manager = PostgreSQLReplicationManager(db_config)
    
    if action == 'setup-source':
        tables = db_config.get('tables')
        return manager.setup_source_database(db_config['source'], tables)
    
    elif action == 'setup-target':
        return manager.setup_target_database(
            db_config['target'], 
            db_config['source'],
            lsn,
            skip_origin_check,
            auto_confirm
        )
    
    elif action == 'verify':
        return manager.verify_replication(db_config['source'])
    
    elif action == 'get-lsn':
        lsn = manager.get_lsn_from_source(db_config['source'])
        if lsn:
            print(f"\n{'='*80}")
            print(f"Current LSN from source database: {lsn}")
            print(f"{'='*80}\n")
            return True
        else:
            logger.error("Failed to get LSN from source database")
            return False
    
    elif action == 'list-origins':
        return manager.list_replication_origins(db_config['target'])
    
    elif action == 'check-origin-usage':
        return manager.check_origin_usage(db_config['target'])
    
    elif action == 'cleanup':
        return manager.cleanup_replication(db_config['source'], db_config['target'])
    
    else:
        logger.error(f"Unknown action: {action}")
        return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Automate RDS PostgreSQL encryption migration using logical replication',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Setup source database (create publication and replication slot)
  python rds_encryption_automation.py --config databases.json --action setup-source
  
  # Get current LSN from source database
  python rds_encryption_automation.py --config databases.json --action get-lsn
  
  # List replication origins on target database (useful for debugging)
  python rds_encryption_automation.py --config databases.json --action list-origins
  
  # Check which processes are using replication origins (diagnose "already active" errors)
  python rds_encryption_automation.py --config databases.json --action check-origin-usage
  
  # Setup target database (create subscription and enable replication)
  # LSN will be auto-fetched from source if not provided
  python rds_encryption_automation.py --config databases.json --action setup-target
  
  # Setup target with LSN provided manually
  python rds_encryption_automation.py --config databases.json --action setup-target --lsn 0/20000110
  
  # Setup target without origin check (for automation/CI)
  python rds_encryption_automation.py --config databases.json --action setup-target --skip-origin-check
  
  # Setup target in fully automated mode (no prompts, auto-fetch LSN, auto-confirm)
  python rds_encryption_automation.py --config databases.json --action setup-target --yes
  
  # Setup target in fully automated mode with LSN provided
  python rds_encryption_automation.py --config databases.json --action setup-target --lsn 0/20000110 --yes
  
  # Verify replication status
  python rds_encryption_automation.py --config databases.json --action verify
  
  # Cleanup replication after migration
  python rds_encryption_automation.py --config databases.json --action cleanup
        """
    )
    
    parser.add_argument(
        '--config',
        required=True,
        help='Path to JSON configuration file'
    )
    
    parser.add_argument(
        '--action',
        required=True,
        choices=['setup-source', 'setup-target', 'verify', 'get-lsn', 'list-origins', 'check-origin-usage', 'cleanup'],
        help='Action to perform'
    )
    
    parser.add_argument(
        '--lsn',
        help='LSN value for target setup (format: 0/XXXXXXXX)'
    )
    
    parser.add_argument(
        '--database',
        help='Process only specific database by name (optional)'
    )
    
    parser.add_argument(
        '--skip-origin-check',
        action='store_true',
        help='Skip origin usage check and confirmation in setup-target (for automation)'
    )
    
    parser.add_argument(
        '--yes', '-y',
        action='store_true',
        dest='auto_confirm',
        help='Automatically confirm all prompts (non-interactive mode)'
    )
    
    args = parser.parse_args()
    
    # Load configuration
    config = load_config(args.config)
    
    # Get list of databases to process
    databases = config.get('databases', [])
    if not databases:
        logger.error("No databases found in configuration")
        sys.exit(1)
    
    # Filter by database name if specified
    if args.database:
        databases = [db for db in databases if db.get('database') == args.database]
        if not databases:
            logger.error(f"Database '{args.database}' not found in configuration")
            sys.exit(1)
    
    # Process each database
    success_count = 0
    failure_count = 0
    
    for db_config in databases:
        db_name = db_config.get('database', 'unknown')
        logger.info("\n" + "=" * 80)
        logger.info(f"PROCESSING DATABASE: {db_name}")
        logger.info("=" * 80 + "\n")
        
        try:
            if process_database(db_config, args.action, args.lsn, args.skip_origin_check, args.auto_confirm):
                success_count += 1
                logger.info(f"✓ Successfully processed {db_name}")
            else:
                failure_count += 1
                logger.error(f"✗ Failed to process {db_name}")
        except Exception as e:
            failure_count += 1
            logger.error(f"✗ Error processing {db_name}: {str(e)}")
        
        # Add delay between databases to avoid overwhelming the system
        if len(databases) > 1:
            time.sleep(2)
    
    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("MIGRATION SUMMARY")
    logger.info("=" * 80)
    logger.info(f"Total databases: {len(databases)}")
    logger.info(f"Successful: {success_count}")
    logger.info(f"Failed: {failure_count}")
    logger.info("=" * 80)
    
    if failure_count > 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
