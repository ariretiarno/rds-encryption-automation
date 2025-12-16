#!/usr/bin/env python3
"""
Script to monitor sequence drift between master and replica databases.
Helps identify when sequences are out of sync and need to be synchronized.
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
from tabulate import tabulate

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


def get_sequences(conn, dbname: str) -> Dict[str, Dict]:
    """
    Get all sequences and their current values from a database.
    
    Returns:
        Dictionary mapping sequence full name to sequence info
    """
    try:
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                schemaname,
                sequencename,
                last_value,
                start_value,
                increment_by,
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
                'start_value': row[3],
                'increment_by': row[4],
                'is_called': row[5]
            }
        
        cursor.close()
        return sequences
        
    except Exception as e:
        logger.error(f"Failed to get sequences: {e}")
        raise


def calculate_drift(master_value: int, replica_value: int, increment_by: int = 1) -> Dict:
    """
    Calculate drift between master and replica sequence values.
    
    Returns:
        Dictionary with drift information
    """
    diff = master_value - replica_value
    diff_pct = (diff / master_value * 100) if master_value > 0 else 0
    
    # Estimate how many inserts the drift represents
    inserts_behind = abs(diff) // abs(increment_by) if increment_by != 0 else 0
    
    return {
        'diff': diff,
        'diff_pct': diff_pct,
        'inserts_behind': inserts_behind,
        'status': 'OK' if diff == 0 else ('AHEAD' if diff < 0 else 'BEHIND')
    }


def monitor_sequences_for_database(dbname: str, threshold: int = 0, show_all: bool = False) -> Tuple[int, int, int]:
    """
    Monitor sequence drift for a specific database.
    
    Args:
        dbname: Database name
        threshold: Only show sequences with drift >= threshold
        show_all: Show all sequences, even those in sync
    
    Returns:
        Tuple of (total_sequences, out_of_sync_count, critical_count)
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
    logger.info(f"Monitoring sequences for database: {dbname}")
    logger.info(f"Master: {master_host}:{master_port}")
    logger.info(f"Replica: {replica_host}:{replica_port}")
    logger.info(f"{'='*80}")
    
    master_conn = None
    replica_conn = None
    
    try:
        # Connect to both databases
        logger.info("Connecting to master database...")
        master_conn = get_connection(master_host, master_port, master_user, master_password, dbname)
        
        logger.info("Connecting to replica database...")
        replica_conn = get_connection(replica_host, replica_port, replica_user, replica_password, dbname)
        
        # Get sequences from both databases
        logger.info("\nFetching sequences from master...")
        master_sequences = get_sequences(master_conn, dbname)
        logger.info(f"Found {len(master_sequences)} sequences on master")
        
        logger.info("Fetching sequences from replica...")
        replica_sequences = get_sequences(replica_conn, dbname)
        logger.info(f"Found {len(replica_sequences)} sequences on replica")
        
        if not master_sequences:
            logger.info("\nNo sequences found on master.")
            return 0, 0, 0
        
        # Compare sequences
        logger.info("\nAnalyzing sequence drift...\n")
        
        table_data = []
        out_of_sync_count = 0
        critical_count = 0
        
        # Check each master sequence
        for full_name, master_seq in master_sequences.items():
            master_value = master_seq['last_value']
            increment_by = master_seq['increment_by']
            
            # Check if sequence exists on replica
            if full_name not in replica_sequences:
                table_data.append([
                    full_name,
                    master_value,
                    'MISSING',
                    'N/A',
                    'N/A',
                    '❌ MISSING'
                ])
                out_of_sync_count += 1
                critical_count += 1
                continue
            
            replica_value = replica_sequences[full_name]['last_value']
            drift = calculate_drift(master_value, replica_value, increment_by)
            
            # Determine status icon
            if drift['diff'] == 0:
                status_icon = '✓ IN SYNC'
            elif abs(drift['diff']) > 1000:
                status_icon = '❌ CRITICAL'
                critical_count += 1
                out_of_sync_count += 1
            elif abs(drift['diff']) > 100:
                status_icon = '⚠ WARNING'
                out_of_sync_count += 1
            else:
                status_icon = '⚠ DRIFT'
                out_of_sync_count += 1
            
            # Apply threshold filter
            if not show_all and abs(drift['diff']) < threshold:
                continue
            
            table_data.append([
                full_name,
                master_value,
                replica_value,
                drift['diff'],
                f"{drift['diff_pct']:.1f}%",
                status_icon
            ])
        
        # Check for sequences only on replica
        for full_name in replica_sequences:
            if full_name not in master_sequences:
                table_data.append([
                    full_name,
                    'MISSING',
                    replica_sequences[full_name]['last_value'],
                    'N/A',
                    'N/A',
                    '⚠ EXTRA'
                ])
        
        # Display results
        if table_data:
            headers = ['Sequence', 'Master Value', 'Replica Value', 'Drift', 'Drift %', 'Status']
            print(tabulate(table_data, headers=headers, tablefmt='grid'))
        else:
            logger.info("✓ All sequences are in sync!")
        
        # Summary
        logger.info("\n" + "="*80)
        logger.info("MONITORING SUMMARY")
        logger.info("="*80)
        logger.info(f"Total sequences: {len(master_sequences)}")
        logger.info(f"In sync: {len(master_sequences) - out_of_sync_count}")
        logger.info(f"Out of sync: {out_of_sync_count}")
        logger.info(f"Critical drift (>1000): {critical_count}")
        
        if out_of_sync_count > 0:
            logger.info("\n⚠ Sequences are out of sync!")
            logger.info("Run sync_sequences.py to synchronize:")
            logger.info(f"  python3 sync_sequences.py {dbname} --dry-run")
            logger.info(f"  python3 sync_sequences.py {dbname}")
        else:
            logger.info("\n✓ All sequences are in sync")
        
        return len(master_sequences), out_of_sync_count, critical_count
        
    except Exception as e:
        logger.error(f"Error monitoring sequences: {e}")
        raise
    finally:
        if master_conn:
            master_conn.close()
        if replica_conn:
            replica_conn.close()


def main():
    parser = argparse.ArgumentParser(
        description='Monitor sequence drift between master and replica databases',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Monitor sequences for a database
  python3 monitor_sequences.py mydb
  
  # Monitor all databases from .env
  python3 monitor_sequences.py --all
  
  # Show all sequences including those in sync
  python3 monitor_sequences.py mydb --show-all
  
  # Only show sequences with drift >= 100
  python3 monitor_sequences.py mydb --threshold 100
  
  # Continuous monitoring (every 60 seconds)
  python3 monitor_sequences.py mydb --watch 60
        """
    )
    
    parser.add_argument('database', nargs='?', help='Database name to monitor sequences for')
    parser.add_argument('--all', action='store_true', help='Monitor sequences for all databases in .env')
    parser.add_argument('--show-all', action='store_true', help='Show all sequences, even those in sync')
    parser.add_argument('--threshold', type=int, default=0, help='Only show sequences with drift >= threshold')
    parser.add_argument('--watch', type=int, metavar='SECONDS', help='Continuous monitoring mode (refresh interval in seconds)')
    
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
    
    # Watch mode
    if args.watch:
        import time
        logger.info(f"Starting continuous monitoring (refresh every {args.watch} seconds)")
        logger.info("Press Ctrl+C to stop\n")
        
        try:
            while True:
                os.system('clear' if os.name == 'posix' else 'cls')
                logger.info(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                
                for dbname in databases:
                    try:
                        monitor_sequences_for_database(dbname, args.threshold, args.show_all)
                        if len(databases) > 1:
                            logger.info("\n")
                    except Exception as e:
                        logger.error(f"Failed to monitor sequences for {dbname}: {e}")
                
                time.sleep(args.watch)
        except KeyboardInterrupt:
            logger.info("\nMonitoring stopped by user")
            sys.exit(0)
    else:
        # Single run mode
        total_sequences = 0
        total_out_of_sync = 0
        total_critical = 0
        
        for dbname in databases:
            try:
                seq_count, out_of_sync, critical = monitor_sequences_for_database(
                    dbname, args.threshold, args.show_all
                )
                total_sequences += seq_count
                total_out_of_sync += out_of_sync
                total_critical += critical
                
                if len(databases) > 1:
                    logger.info("\n")
            except Exception as e:
                logger.error(f"Failed to monitor sequences for {dbname}: {e}")
        
        # Overall summary for multiple databases
        if len(databases) > 1:
            logger.info("="*80)
            logger.info("OVERALL SUMMARY")
            logger.info("="*80)
            logger.info(f"Databases monitored: {len(databases)}")
            logger.info(f"Total sequences: {total_sequences}")
            logger.info(f"Out of sync: {total_out_of_sync}")
            logger.info(f"Critical: {total_critical}")
        
        # Exit with appropriate code
        if total_critical > 0:
            sys.exit(2)  # Critical issues
        elif total_out_of_sync > 0:
            sys.exit(1)  # Warning
        else:
            sys.exit(0)  # All good


if __name__ == '__main__':
    main()
