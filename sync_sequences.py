#!/usr/bin/env python3
"""
Script to sync sequence values from master to replica database.
Sequences are NOT replicated by PostgreSQL logical replication,
so they need to be manually synchronized.
"""

import os
import sys
import psycopg2
from dotenv import load_dotenv
import logging
from datetime import datetime
from typing import List, Dict, Tuple
import re
import argparse

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def normalize_name(name: str) -> str:
    """Convert special characters in database name to underscore."""
    return re.sub(r'[^a-zA-Z0-9_]', '_', name)


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
        return conn
    except Exception as e:
        logger.error(f"Failed to connect to database '{dbname}': {e}")
        raise


def get_sequences_from_master(master_conn, dbname: str) -> List[Dict]:
    """
    Get all sequences and their current values from master database.
    
    Returns:
        List of dictionaries containing sequence information
    """
    try:
        cursor = master_conn.cursor()
        
        # Get all sequences with their current values
        cursor.execute("""
            SELECT 
                schemaname,
                sequencename,
                last_value,
                start_value,
                increment_by,
                max_value,
                min_value,
                cache_size,
                cycle,
                is_called
            FROM pg_sequences
            WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
            ORDER BY schemaname, sequencename
        """)
        
        sequences = []
        for row in cursor.fetchall():
            sequences.append({
                'schema': row[0],
                'name': row[1],
                'last_value': row[2],
                'start_value': row[3],
                'increment_by': row[4],
                'max_value': row[5],
                'min_value': row[6],
                'cache_size': row[7],
                'cycle': row[8],
                'is_called': row[9]
            })
        
        cursor.close()
        return sequences
        
    except Exception as e:
        logger.error(f"Failed to get sequences from master: {e}")
        raise


def get_sequences_from_replica(replica_conn, dbname: str) -> Dict[str, Dict]:
    """
    Get all sequences and their current values from replica database.
    
    Returns:
        Dictionary mapping sequence full name to sequence info
    """
    try:
        cursor = replica_conn.cursor()
        
        cursor.execute("""
            SELECT 
                schemaname,
                sequencename,
                last_value,
                is_called
            FROM pg_sequences
            WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
            ORDER BY schemaname, sequencename
        """)
        
        sequences = {}
        for row in cursor.fetchall():
            full_name = f"{row[0]}.{row[1]}"
            sequences[full_name] = {
                'schema': row[0],
                'name': row[1],
                'last_value': row[2],
                'is_called': row[3]
            }
        
        cursor.close()
        return sequences
        
    except Exception as e:
        logger.error(f"Failed to get sequences from replica: {e}")
        raise


def sync_sequence(replica_conn, schema: str, seq_name: str, last_value: int, is_called: bool, dry_run: bool = False) -> bool:
    """
    Sync a single sequence value from master to replica.
    
    Args:
        replica_conn: Connection to replica database
        schema: Schema name
        seq_name: Sequence name
        last_value: Last value from master
        is_called: Whether the sequence has been called
        dry_run: If True, only show what would be done
    
    Returns:
        True if successful, False otherwise
    """
    full_name = f'"{schema}"."{seq_name}"'
    
    try:
        if dry_run:
            logger.info(f"  [DRY RUN] Would set {full_name} to {last_value} (is_called={is_called})")
            return True
        
        cursor = replica_conn.cursor()
        
        # Use setval to set the sequence value
        # setval(sequence, value, is_called)
        # is_called: true means next nextval will return value+increment
        #            false means next nextval will return value
        cursor.execute(
            f"SELECT setval('{full_name}', %s, %s)",
            (last_value, is_called)
        )
        
        cursor.close()
        logger.info(f"  ✓ Synced {full_name} to {last_value}")
        return True
        
    except Exception as e:
        logger.error(f"  ✗ Failed to sync {full_name}: {e}")
        return False


def sync_sequences_for_database(dbname: str, dry_run: bool = False, force: bool = False) -> Tuple[int, int, int]:
    """
    Sync all sequences for a specific database.
    
    Args:
        dbname: Database name
        dry_run: If True, only show what would be done
        force: If True, sync even if replica value is higher
    
    Returns:
        Tuple of (synced_count, skipped_count, failed_count)
    """
    load_dotenv()
    
    master_host = os.getenv('MASTER_DB_HOST')
    master_port = os.getenv('MASTER_DB_PORT', '5432')
    master_user = os.getenv('MASTER_DB_USER')
    master_password = os.getenv('MASTER_DB_PASSWORD')
    
    replica_host = os.getenv('REPLICATION_DB_HOST')
    replica_port = os.getenv('REPLICATION_DB_PORT', '5432')
    replica_user = os.getenv('REPLICATION_DB_USER')
    replica_password = os.getenv('REPLICATION_DB_PASSWORD')
    
    logger.info(f"{'='*80}")
    logger.info(f"Syncing sequences for database: {dbname}")
    if dry_run:
        logger.info("[DRY RUN MODE - No changes will be made]")
    logger.info(f"Master: {master_host}:{master_port}")
    logger.info(f"Replica: {replica_host}:{replica_port}")
    logger.info(f"{'='*80}")
    
    master_conn = None
    replica_conn = None
    synced_count = 0
    skipped_count = 0
    failed_count = 0
    
    try:
        # Connect to both databases
        logger.info("Connecting to master database...")
        master_conn = get_connection(master_host, master_port, master_user, master_password, dbname)
        
        logger.info("Connecting to replica database...")
        replica_conn = get_connection(replica_host, replica_port, replica_user, replica_password, dbname)
        
        # Get sequences from master
        logger.info("\nFetching sequences from master...")
        master_sequences = get_sequences_from_master(master_conn, dbname)
        logger.info(f"Found {len(master_sequences)} sequences on master")
        
        if not master_sequences:
            logger.info("No sequences found on master. Nothing to sync.")
            return 0, 0, 0
        
        # Get sequences from replica
        logger.info("\nFetching sequences from replica...")
        replica_sequences = get_sequences_from_replica(replica_conn, dbname)
        logger.info(f"Found {len(replica_sequences)} sequences on replica")
        
        # Sync each sequence
        logger.info("\nSyncing sequences...")
        for seq in master_sequences:
            full_name = f"{seq['schema']}.{seq['name']}"
            master_value = seq['last_value']
            
            # Check if sequence exists on replica
            if full_name not in replica_sequences:
                logger.warning(f"  ⚠ Sequence {full_name} exists on master but not on replica - skipping")
                skipped_count += 1
                continue
            
            replica_value = replica_sequences[full_name]['last_value']
            
            # Check if we need to sync
            if replica_value > master_value and not force:
                logger.warning(f"  ⚠ Skipping {full_name}: replica value ({replica_value}) > master value ({master_value})")
                logger.warning(f"    Use --force to override")
                skipped_count += 1
                continue
            
            if replica_value == master_value:
                logger.info(f"  ≈ {full_name} already in sync ({master_value})")
                skipped_count += 1
                continue
            
            # Sync the sequence
            logger.info(f"  → Syncing {full_name}: {replica_value} → {master_value}")
            if sync_sequence(replica_conn, seq['schema'], seq['name'], master_value, seq['is_called'], dry_run):
                synced_count += 1
            else:
                failed_count += 1
        
        # Summary
        logger.info("\n" + "="*80)
        logger.info("SYNC SUMMARY")
        logger.info("="*80)
        logger.info(f"Total sequences on master: {len(master_sequences)}")
        logger.info(f"Synced: {synced_count}")
        logger.info(f"Skipped: {skipped_count}")
        logger.info(f"Failed: {failed_count}")
        
        if dry_run:
            logger.info("\n[DRY RUN] No changes were made. Run without --dry-run to apply changes.")
        elif synced_count > 0:
            logger.info(f"\n✓ Successfully synced {synced_count} sequences")
        
        return synced_count, skipped_count, failed_count
        
    except Exception as e:
        logger.error(f"Error syncing sequences: {e}")
        raise
    finally:
        if master_conn:
            master_conn.close()
        if replica_conn:
            replica_conn.close()


def main():
    parser = argparse.ArgumentParser(
        description='Sync sequence values from master to replica database',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run to see what would be synced
  python3 sync_sequences.py mydb --dry-run
  
  # Sync sequences for a database
  python3 sync_sequences.py mydb
  
  # Sync all databases from .env
  python3 sync_sequences.py --all
  
  # Force sync even if replica value is higher
  python3 sync_sequences.py mydb --force
  
  # Sync with confirmation prompt
  python3 sync_sequences.py mydb --execute
        """
    )
    
    parser.add_argument('database', nargs='?', help='Database name to sync sequences for')
    parser.add_argument('--all', action='store_true', help='Sync sequences for all databases in .env')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')
    parser.add_argument('--force', action='store_true', help='Force sync even if replica value is higher than master')
    parser.add_argument('--execute', action='store_true', help='Execute with confirmation prompt')
    
    args = parser.parse_args()
    
    # Validate arguments
    if not args.database and not args.all:
        parser.error("Either specify a database name or use --all flag")
    
    if args.database and args.all:
        parser.error("Cannot specify both database name and --all flag")
    
    # Get databases to process
    databases = []
    if args.all:
        load_dotenv()
        db_list = os.getenv('DATABASES', '')
        if not db_list:
            logger.error("No databases found in .env DATABASES variable")
            sys.exit(1)
        databases = [db.strip() for db in db_list.split(',')]
    else:
        databases = [args.database]
    
    # Confirmation prompt if --execute flag is used
    if args.execute and not args.dry_run:
        logger.info(f"\nYou are about to sync sequences for: {', '.join(databases)}")
        logger.info("This will update sequence values on the replica database.")
        response = input("\nAre you sure you want to continue? (yes/no): ")
        if response.lower() != 'yes':
            logger.info("Cancelled by user")
            sys.exit(0)
    
    # Process each database
    total_synced = 0
    total_skipped = 0
    total_failed = 0
    
    for dbname in databases:
        try:
            synced, skipped, failed = sync_sequences_for_database(dbname, args.dry_run, args.force)
            total_synced += synced
            total_skipped += skipped
            total_failed += failed
        except Exception as e:
            logger.error(f"Failed to sync sequences for {dbname}: {e}")
            total_failed += 1
    
    # Overall summary for multiple databases
    if len(databases) > 1:
        logger.info("\n" + "="*80)
        logger.info("OVERALL SUMMARY")
        logger.info("="*80)
        logger.info(f"Databases processed: {len(databases)}")
        logger.info(f"Total synced: {total_synced}")
        logger.info(f"Total skipped: {total_skipped}")
        logger.info(f"Total failed: {total_failed}")
    
    # Exit with appropriate code
    if total_failed > 0:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
