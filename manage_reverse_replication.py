#!/usr/bin/env python3
"""
Script for managing REVERSE replication (rollback scenario).

This script helps you set up reverse replication where:
- REPLICA becomes the new MASTER (creates publications)
- OLD MASTER becomes the new REPLICA (creates subscriptions)

This is useful for rollback scenarios or when you want to switch roles.
"""

import os
import sys
import re
import psycopg2
from psycopg2 import sql
from dotenv import load_dotenv
from typing import List, Tuple
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def normalize_name(name: str) -> str:
    """Convert special characters in database name to underscore."""
    normalized = re.sub(r'[^a-zA-Z0-9_]', '_', name)
    return normalized


def get_connection(host: str, port: str, user: str, password: str, dbname: str):
    """Create a PostgreSQL database connection."""
    try:
        conn = psycopg2.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            dbname=dbname,
            connect_timeout=10
        )
        conn.autocommit = True
        logger.debug(f"Connected to database '{dbname}' on {host}")
        return conn
    except Exception as e:
        logger.error(f"Failed to connect to database '{dbname}': {e}")
        raise


def verify_replication_sync(conn) -> bool:
    """
    Verify that replication is fully synced (lag = 0).
    
    Returns:
        True if all slots are synced, False otherwise
    """
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                slot_name,
                (pg_current_wal_lsn() - confirmed_flush_lsn) AS lsn_distance_bytes
            FROM pg_catalog.pg_replication_slots
            WHERE slot_type = 'logical'
        """)
        
        results = cursor.fetchall()
        cursor.close()
        
        if not results:
            logger.warning("No replication slots found")
            return True  # No slots to check
        
        all_synced = True
        for slot_name, lag_bytes in results:
            if lag_bytes and lag_bytes > 0:
                logger.warning(f"Slot '{slot_name}' has lag: {lag_bytes} bytes")
                all_synced = False
            else:
                logger.info(f"Slot '{slot_name}' is fully synced")
        
        return all_synced
        
    except Exception as e:
        logger.error(f"Failed to verify replication sync: {e}")
        return False


def get_current_lsn(conn) -> str:
    """Get the current WAL LSN."""
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT pg_current_wal_lsn()")
        lsn = cursor.fetchone()[0]
        cursor.close()
        return lsn
    except Exception as e:
        logger.error(f"Failed to get current LSN: {e}")
        raise


def cleanup_old_subscriptions(conn, dbname: str) -> bool:
    """
    Clean up old subscriptions before setting up reverse replication.
    
    Args:
        conn: Database connection
        dbname: Database name
        
    Returns:
        True if successful, False otherwise
    """
    normalized_name = normalize_name(dbname)
    subscription_name = f"{normalized_name}_sub"
    
    try:
        cursor = conn.cursor()
        
        # Check if subscription exists
        cursor.execute(
            "SELECT subname FROM pg_subscription WHERE subname = %s",
            (subscription_name,)
        )
        
        if not cursor.fetchone():
            logger.info(f"No old subscription '{subscription_name}' to clean up")
            cursor.close()
            return True
        
        logger.info(f"Cleaning up old subscription '{subscription_name}'...")
        
        # Disable subscription
        cursor.execute(f"ALTER SUBSCRIPTION {subscription_name} DISABLE")
        logger.info(f"Disabled subscription '{subscription_name}'")
        
        # Remove slot
        cursor.execute(f"ALTER SUBSCRIPTION {subscription_name} SET (slot_name = NONE)")
        logger.info(f"Removed slot from subscription '{subscription_name}'")
        
        # Drop subscription
        cursor.execute(f"DROP SUBSCRIPTION {subscription_name}")
        logger.info(f"Dropped subscription '{subscription_name}'")
        
        cursor.close()
        logger.info(f"✓ Successfully cleaned up old subscription '{subscription_name}'")
        return True
        
    except Exception as e:
        logger.error(f"✗ Failed to clean up old subscription for '{dbname}': {e}")
        return False


def create_reverse_publication(conn, dbname: str) -> bool:
    """
    Create publication for reverse replication on the new master (old replica).
    
    Args:
        conn: Database connection
        dbname: Database name
        
    Returns:
        True if successful, False otherwise
    """
    normalized_name = normalize_name(dbname)
    publication_name = f"{normalized_name}_pub_reverse"
    
    try:
        cursor = conn.cursor()
        
        # Check if publication already exists
        cursor.execute(
            "SELECT pubname FROM pg_publication WHERE pubname = %s",
            (publication_name,)
        )
        
        if cursor.fetchone():
            logger.warning(f"Publication '{publication_name}' already exists. Skipping.")
            cursor.close()
            return False
        
        # Create publication
        logger.info(f"Creating publication '{publication_name}' for database '{dbname}'...")
        cursor.execute(f"CREATE PUBLICATION {publication_name} FOR ALL TABLES")
        
        cursor.close()
        logger.info(f"✓ Successfully created publication '{publication_name}'")
        return True
        
    except Exception as e:
        logger.error(f"✗ Failed to create publication for '{dbname}': {e}")
        return False


def create_reverse_replication_slot(conn, dbname: str) -> bool:
    """
    Create replication slot for reverse replication on the new master (old replica).
    
    Args:
        conn: Database connection
        dbname: Database name
        
    Returns:
        True if successful, False otherwise
    """
    normalized_name = normalize_name(dbname)
    slot_name = f"{normalized_name}_slot_reverse"
    
    try:
        cursor = conn.cursor()
        
        # Check if slot already exists
        cursor.execute(
            "SELECT slot_name FROM pg_replication_slots WHERE slot_name = %s",
            (slot_name,)
        )
        
        if cursor.fetchone():
            logger.warning(f"Replication slot '{slot_name}' already exists. Skipping.")
            cursor.close()
            return False
        
        # Create replication slot
        logger.info(f"Creating replication slot '{slot_name}' for database '{dbname}'...")
        cursor.execute(
            "SELECT * FROM pg_create_logical_replication_slot(%s, 'pgoutput')",
            (slot_name,)
        )
        
        cursor.close()
        logger.info(f"✓ Successfully created replication slot '{slot_name}'")
        return True
        
    except Exception as e:
        logger.error(f"✗ Failed to create replication slot for '{dbname}': {e}")
        return False


def delete_reverse_subscription(conn, dbname: str) -> bool:
    """
    Delete reverse subscription on the new replica (old master).
    
    Args:
        conn: Database connection
        dbname: Database name
        
    Returns:
        True if successful, False otherwise
    """
    normalized_name = normalize_name(dbname)
    subscription_name = f"{normalized_name}_sub_reverse"
    
    try:
        cursor = conn.cursor()
        
        # Check if subscription exists
        cursor.execute(
            "SELECT subname FROM pg_subscription WHERE subname = %s",
            (subscription_name,)
        )
        
        if not cursor.fetchone():
            logger.warning(f"Subscription '{subscription_name}' does not exist. Skipping.")
            cursor.close()
            return False
        
        logger.info(f"Deleting reverse subscription '{subscription_name}'...")
        
        # Disable subscription
        cursor.execute(f"ALTER SUBSCRIPTION {subscription_name} DISABLE")
        logger.info(f"Disabled subscription '{subscription_name}'")
        
        # Remove slot
        cursor.execute(f"ALTER SUBSCRIPTION {subscription_name} SET (slot_name = NONE)")
        logger.info(f"Removed slot from subscription '{subscription_name}'")
        
        # Drop subscription
        cursor.execute(f"DROP SUBSCRIPTION {subscription_name}")
        logger.info(f"Dropped subscription '{subscription_name}'")
        
        cursor.close()
        logger.info(f"✓ Successfully deleted reverse subscription '{subscription_name}'")
        return True
        
    except Exception as e:
        logger.error(f"✗ Failed to delete reverse subscription for '{dbname}': {e}")
        return False


def delete_reverse_replication_slot(conn, dbname: str) -> bool:
    """
    Delete reverse replication slot on the new master (old replica).
    
    Args:
        conn: Database connection
        dbname: Database name
        
    Returns:
        True if successful, False otherwise
    """
    normalized_name = normalize_name(dbname)
    slot_name = f"{normalized_name}_slot_reverse"
    
    try:
        cursor = conn.cursor()
        
        # Check if slot exists
        cursor.execute(
            "SELECT slot_name FROM pg_replication_slots WHERE slot_name = %s",
            (slot_name,)
        )
        
        if not cursor.fetchone():
            logger.warning(f"Replication slot '{slot_name}' does not exist. Skipping.")
            cursor.close()
            return False
        
        logger.info(f"Deleting replication slot '{slot_name}'...")
        cursor.execute(
            "SELECT pg_drop_replication_slot(%s)",
            (slot_name,)
        )
        
        cursor.close()
        logger.info(f"✓ Successfully deleted replication slot '{slot_name}'")
        return True
        
    except Exception as e:
        logger.error(f"✗ Failed to delete replication slot for '{dbname}': {e}")
        return False


def delete_reverse_publication(conn, dbname: str) -> bool:
    """
    Delete reverse publication on the new master (old replica).
    
    Args:
        conn: Database connection
        dbname: Database name
        
    Returns:
        True if successful, False otherwise
    """
    normalized_name = normalize_name(dbname)
    publication_name = f"{normalized_name}_pub_reverse"
    
    try:
        cursor = conn.cursor()
        
        # Check if publication exists
        cursor.execute(
            "SELECT pubname FROM pg_publication WHERE pubname = %s",
            (publication_name,)
        )
        
        if not cursor.fetchone():
            logger.warning(f"Publication '{publication_name}' does not exist. Skipping.")
            cursor.close()
            return False
        
        logger.info(f"Deleting publication '{publication_name}'...")
        cursor.execute(f"DROP PUBLICATION {publication_name}")
        
        cursor.close()
        logger.info(f"✓ Successfully deleted publication '{publication_name}'")
        return True
        
    except Exception as e:
        logger.error(f"✗ Failed to delete publication for '{dbname}': {e}")
        return False


def create_reverse_subscription(
    conn,
    dbname: str,
    new_master_host: str,
    new_master_user: str,
    new_master_password: str,
    lsn: str
) -> bool:
    """
    Create subscription for reverse replication on the new replica (old master).
    
    Args:
        conn: Database connection
        dbname: Database name
        new_master_host: New master database host (old replica)
        new_master_user: New master database user
        new_master_password: New master database password
        lsn: Log Sequence Number to start from
        
    Returns:
        True if successful, False otherwise
    """
    normalized_name = normalize_name(dbname)
    subscription_name = f"{normalized_name}_sub_reverse"
    publication_name = f"{normalized_name}_pub_reverse"
    slot_name = f"{normalized_name}_slot_reverse"
    
    try:
        cursor = conn.cursor()
        
        # Check if subscription already exists
        cursor.execute(
            "SELECT subname FROM pg_subscription WHERE subname = %s",
            (subscription_name,)
        )
        
        if cursor.fetchone():
            logger.warning(f"Subscription '{subscription_name}' already exists. Skipping.")
            cursor.close()
            return False
        
        # Create subscription
        connection_string = f"host={new_master_host} user={new_master_user} password={new_master_password} dbname={dbname}"
        
        create_sub_query = f"""
        CREATE SUBSCRIPTION {subscription_name}
        CONNECTION '{connection_string}'
        PUBLICATION {publication_name}
        WITH (
            copy_data = false,
            create_slot = false,
            enabled = false,
            synchronous_commit = false,
            connect = true,
            slot_name = '{slot_name}'
        )
        """
        
        logger.info(f"Creating reverse subscription '{subscription_name}' for database '{dbname}'...")
        cursor.execute(create_sub_query)
        
        # Find unused replication origin
        cursor.execute("SELECT roname FROM pg_replication_origin WHERE roname LIKE 'pg_%'")
        all_origins = [row[0] for row in cursor.fetchall()]
        
        cursor.execute("""
            SELECT o.roname 
            FROM pg_replication_origin o
            INNER JOIN pg_replication_origin_status s ON o.roident = s.local_id
            WHERE o.roname LIKE 'pg_%'
        """)
        used_origins = [row[0] for row in cursor.fetchall()]
        
        unused_origins = [origin for origin in all_origins if origin not in used_origins]
        
        if unused_origins:
            origin_name = unused_origins[0]
            logger.info(f"Found unused replication origin: '{origin_name}'")
            logger.info(f"Advancing replication origin '{origin_name}' to LSN '{lsn}'...")
            
            cursor.execute(
                sql.SQL("SELECT pg_replication_origin_advance(%s, %s)"),
                (origin_name, lsn)
            )
            
            logger.info(f"Successfully advanced origin '{origin_name}' to LSN '{lsn}'")
        else:
            logger.warning(f"No unused replication origins found. Subscription created but origin not advanced.")
        
        # Enable subscription
        logger.info(f"Enabling subscription '{subscription_name}'...")
        cursor.execute(f"ALTER SUBSCRIPTION {subscription_name} ENABLE")
        
        cursor.close()
        logger.info(f"✓ Successfully created and enabled reverse subscription '{subscription_name}'")
        return True
        
    except Exception as e:
        logger.error(f"✗ Failed to create reverse subscription for '{dbname}': {e}")
        return False


def main():
    """Main function to manage reverse replication."""
    load_dotenv()
    
    # Get action from command line
    if len(sys.argv) < 2:
        print("Usage: python manage_reverse_replication.py [setup_new_master|setup_new_replica|verify|cleanup]")
        print("\nActions:")
        print("  setup_new_master  - Create publications and slots on REPLICA (becomes new master)")
        print("  setup_new_replica - Create subscriptions on OLD MASTER (becomes new replica)")
        print("  verify            - Verify replication sync before rollback")
        print("  cleanup           - Delete all reverse replication resources")
        print("\nSetup Workflow:")
        print("  1. python manage_reverse_replication.py verify")
        print("  2. python get_lsn.py replica  # Record the LSN")
        print("  3. Update .env with LSN from step 2")
        print("  4. python manage_reverse_replication.py setup_new_master")
        print("  5. python manage_reverse_replication.py setup_new_replica")
        print("\nCleanup Workflow:")
        print("  1. python manage_reverse_replication.py cleanup")
        print("     This will delete:")
        print("     - Reverse subscriptions on new replica (old master)")
        print("     - Reverse replication slots on new master (old replica)")
        print("     - Reverse publications on new master (old replica)")
        sys.exit(1)
    
    action = sys.argv[1].lower()
    
    if action not in ['setup_new_master', 'setup_new_replica', 'verify', 'cleanup']:
        logger.error(f"Invalid action '{action}'")
        sys.exit(1)
    
    # Get configuration
    replication_host = os.getenv('REPLICATION_DB_HOST')  # Old replica, becomes new master
    replication_port = os.getenv('REPLICATION_DB_PORT', '5432')
    replication_user = os.getenv('REPLICATION_DB_USER')
    replication_password = os.getenv('REPLICATION_DB_PASSWORD')
    
    master_host = os.getenv('MASTER_DB_HOST')  # Old master, becomes new replica
    master_port = os.getenv('MASTER_DB_PORT', '5432')
    master_user = os.getenv('MASTER_DB_USER')
    master_password = os.getenv('MASTER_DB_PASSWORD')
    
    lsn = os.getenv('LSN')
    databases_str = os.getenv('DATABASES', '')
    
    # Validate configuration
    if not all([replication_host, replication_user, replication_password, master_host, master_user, master_password]):
        logger.error("Missing required environment variables. Please check your .env file.")
        sys.exit(1)
    
    if action in ['setup_new_replica'] and not lsn:
        logger.error("LSN is required for setup_new_replica action. Run 'python get_lsn.py replica' first.")
        sys.exit(1)
    
    databases = [db.strip() for db in databases_str.split(',') if db.strip()]
    
    if not databases:
        logger.error("No databases specified in DATABASES environment variable.")
        sys.exit(1)
    
    logger.info(f"Found {len(databases)} database(s) to process")
    
    success_count = 0
    failure_count = 0
    
    if action == 'verify':
        logger.info("\n" + "="*60)
        logger.info("VERIFYING REPLICATION SYNC")
        logger.info("="*60 + "\n")
        
        for dbname in databases:
            try:
                # Check on master (current publisher)
                conn = get_connection(master_host, master_port, master_user, master_password, dbname)
                logger.info(f"Checking database: {dbname}")
                
                if verify_replication_sync(conn):
                    logger.info(f"✓ Database '{dbname}' is fully synced")
                    success_count += 1
                else:
                    logger.warning(f"⚠️  Database '{dbname}' has replication lag")
                    failure_count += 1
                
                conn.close()
                
            except Exception as e:
                logger.error(f"Error verifying '{dbname}': {e}")
                failure_count += 1
        
        if failure_count == 0:
            logger.info("\n✓ ALL DATABASES ARE FULLY SYNCED")
            logger.info("You can now proceed with rollback:")
            logger.info("  1. Run: python get_lsn.py replica")
            logger.info("  2. Update .env with the LSN from step 1")
            logger.info("  3. Run: python manage_reverse_replication.py setup_new_master")
        else:
            logger.warning("\n⚠️  SOME DATABASES HAVE LAG - Wait for sync before proceeding")
    
    elif action == 'setup_new_master':
        logger.info("\n" + "="*60)
        logger.info("SETTING UP NEW MASTER (OLD REPLICA)")
        logger.info(f"Host: {replication_host}")
        logger.info("="*60 + "\n")
        
        for dbname in databases:
            logger.info(f"\n{'='*60}")
            logger.info(f"Processing database: {dbname}")
            logger.info(f"{'='*60}")
            
            try:
                conn = get_connection(replication_host, replication_port, replication_user, replication_password, dbname)
                
                # Clean up old subscriptions
                cleanup_old_subscriptions(conn, dbname)
                
                # Create publication
                create_reverse_publication(conn, dbname)
                
                # Create replication slot
                create_reverse_replication_slot(conn, dbname)
                
                conn.close()
                success_count += 1
                
            except Exception as e:
                logger.error(f"Error processing database '{dbname}': {e}")
                failure_count += 1
        
        if failure_count == 0:
            logger.info("\n✓ NEW MASTER SETUP COMPLETE")
            logger.info("Next step: python manage_reverse_replication.py setup_new_replica")
    
    elif action == 'setup_new_replica':
        logger.info("\n" + "="*60)
        logger.info("SETTING UP NEW REPLICA (OLD MASTER)")
        logger.info(f"Host: {master_host}")
        logger.info(f"Using LSN: {lsn}")
        logger.info("="*60 + "\n")
        
        for dbname in databases:
            logger.info(f"\n{'='*60}")
            logger.info(f"Processing database: {dbname}")
            logger.info(f"{'='*60}")
            
            try:
                conn = get_connection(master_host, master_port, master_user, master_password, dbname)
                
                # Create reverse subscription
                create_reverse_subscription(
                    conn,
                    dbname,
                    replication_host,
                    replication_user,
                    replication_password,
                    lsn
                )
                
                conn.close()
                success_count += 1
                
            except Exception as e:
                logger.error(f"Error processing database '{dbname}': {e}")
                failure_count += 1
        
        if failure_count == 0:
            logger.info("\n✓ REVERSE REPLICATION SETUP COMPLETE")
            logger.info("Verify replication is working:")
            logger.info("  python get_lsn.py replica  # Check new master")
            logger.info("  python get_lsn.py master   # Check new replica")
    
    elif action == 'cleanup':
        logger.info("\n" + "="*60)
        logger.info("CLEANING UP REVERSE REPLICATION")
        logger.info("="*60 + "\n")
        
        logger.warning("⚠️  This will delete all reverse replication resources!")
        logger.warning("Make sure you want to proceed before continuing.")
        
        # Step 1: Delete subscriptions on new replica (old master)
        logger.info("\nStep 1: Deleting reverse subscriptions on NEW REPLICA (old master)")
        logger.info(f"Host: {master_host}")
        logger.info("="*60)
        
        for dbname in databases:
            logger.info(f"\nProcessing database: {dbname}")
            try:
                conn = get_connection(master_host, master_port, master_user, master_password, dbname)
                if delete_reverse_subscription(conn, dbname):
                    success_count += 1
                conn.close()
            except Exception as e:
                logger.error(f"Error deleting subscription for '{dbname}': {e}")
                failure_count += 1
        
        # Step 2: Delete replication slots on new master (old replica)
        logger.info("\n" + "="*60)
        logger.info("Step 2: Deleting reverse replication slots on NEW MASTER (old replica)")
        logger.info(f"Host: {replication_host}")
        logger.info("="*60)
        
        for dbname in databases:
            logger.info(f"\nProcessing database: {dbname}")
            try:
                conn = get_connection(replication_host, replication_port, replication_user, replication_password, dbname)
                if delete_reverse_replication_slot(conn, dbname):
                    success_count += 1
                conn.close()
            except Exception as e:
                logger.error(f"Error deleting replication slot for '{dbname}': {e}")
                failure_count += 1
        
        # Step 3: Delete publications on new master (old replica)
        logger.info("\n" + "="*60)
        logger.info("Step 3: Deleting reverse publications on NEW MASTER (old replica)")
        logger.info(f"Host: {replication_host}")
        logger.info("="*60)
        
        for dbname in databases:
            logger.info(f"\nProcessing database: {dbname}")
            try:
                conn = get_connection(replication_host, replication_port, replication_user, replication_password, dbname)
                if delete_reverse_publication(conn, dbname):
                    success_count += 1
                conn.close()
            except Exception as e:
                logger.error(f"Error deleting publication for '{dbname}': {e}")
                failure_count += 1
        
        if failure_count == 0:
            logger.info("\n✓ CLEANUP COMPLETE")
            logger.info("All reverse replication resources have been deleted.")
        else:
            logger.warning(f"\n⚠️  CLEANUP COMPLETED WITH {failure_count} ERRORS")
            logger.warning("Check the logs above for details.")
    
    # Summary
    logger.info(f"\n{'='*60}")
    logger.info(f"SUMMARY")
    logger.info(f"{'='*60}")
    logger.info(f"Action: {action.upper()}")
    logger.info(f"Total databases: {len(databases)}")
    logger.info(f"Successful: {success_count}")
    logger.info(f"Failed: {failure_count}")
    logger.info(f"{'='*60}\n")
    
    if failure_count > 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
