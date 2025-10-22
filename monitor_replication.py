#!/usr/bin/env python3
"""
Continuous Replication Monitoring Script

This script continuously monitors PostgreSQL logical replication status
and provides real-time updates on replication lag and progress.
"""

import json
import sys
import argparse
import time
from datetime import datetime
import psycopg2

def clear_screen():
    """Clear the terminal screen."""
    print("\033[2J\033[H", end="")

def format_bytes(bytes_val):
    """Format bytes into human-readable format."""
    if bytes_val is None:
        return "N/A"
    
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_val < 1024.0:
            return f"{bytes_val:.2f} {unit}"
        bytes_val /= 1024.0
    return f"{bytes_val:.2f} PB"

def get_replication_status(conn, slot_name):
    """
    Get current replication status.
    
    Returns:
        dict: Replication status information
    """
    try:
        with conn.cursor() as cur:
            # Get replication slot status
            cur.execute("""
                SELECT 
                    slot_name,
                    slot_type,
                    database,
                    active,
                    confirmed_flush_lsn,
                    pg_current_wal_lsn() AS current_lsn,
                    (pg_current_wal_lsn() - confirmed_flush_lsn) AS lsn_distance,
                    pg_size_pretty(pg_current_wal_lsn() - confirmed_flush_lsn) AS lag_size
                FROM pg_replication_slots
                WHERE slot_name = %s AND slot_type = 'logical'
            """, (slot_name,))
            
            result = cur.fetchone()
            
            if not result:
                return None
            
            return {
                'slot_name': result[0],
                'slot_type': result[1],
                'database': result[2],
                'active': result[3],
                'confirmed_flush_lsn': result[4],
                'current_lsn': result[5],
                'lsn_distance': result[6],
                'lag_size': result[7]
            }
    except Exception as e:
        return {'error': str(e)}

def get_publication_info(conn, publication_name):
    """Get publication information."""
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    pubname,
                    puballtables,
                    pubinsert,
                    pubupdate,
                    pubdelete
                FROM pg_publication
                WHERE pubname = %s
            """, (publication_name,))
            
            result = cur.fetchone()
            
            if not result:
                return None
            
            return {
                'name': result[0],
                'all_tables': result[1],
                'insert': result[2],
                'update': result[3],
                'delete': result[4]
            }
    except Exception as e:
        return {'error': str(e)}

def display_status(status, publication_info, iteration, start_time):
    """Display replication status in a formatted way."""
    clear_screen()
    
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    elapsed = time.time() - start_time
    elapsed_str = f"{int(elapsed // 3600):02d}:{int((elapsed % 3600) // 60):02d}:{int(elapsed % 60):02d}"
    
    print("=" * 80)
    print(f"  PostgreSQL Logical Replication Monitor")
    print("=" * 80)
    print(f"  Time: {current_time} | Elapsed: {elapsed_str} | Iteration: {iteration}")
    print("=" * 80)
    print()
    
    if 'error' in status:
        print(f"❌ ERROR: {status['error']}")
        return
    
    if status is None:
        print("❌ Replication slot not found or not active")
        return
    
    # Replication Status
    print("📊 REPLICATION STATUS")
    print("-" * 80)
    print(f"  Slot Name:        {status['slot_name']}")
    print(f"  Database:         {status['database']}")
    print(f"  Active:           {'✅ Yes' if status['active'] else '❌ No'}")
    print(f"  Current LSN:      {status['current_lsn']}")
    print(f"  Flushed LSN:      {status['confirmed_flush_lsn']}")
    print()
    
    # Lag Information
    lsn_distance = status['lsn_distance']
    lag_size = status['lag_size']
    
    print("📈 REPLICATION LAG")
    print("-" * 80)
    
    if lsn_distance == 0:
        print(f"  Status:           ✅ FULLY SYNCED")
        print(f"  LSN Distance:     {lsn_distance}")
        print(f"  Lag Size:         {lag_size}")
    elif lsn_distance < 1000:
        print(f"  Status:           🟢 EXCELLENT (Nearly synced)")
        print(f"  LSN Distance:     {lsn_distance}")
        print(f"  Lag Size:         {lag_size}")
    elif lsn_distance < 10000:
        print(f"  Status:           🟡 GOOD (Minor lag)")
        print(f"  LSN Distance:     {lsn_distance}")
        print(f"  Lag Size:         {lag_size}")
    elif lsn_distance < 100000:
        print(f"  Status:           🟠 WARNING (Moderate lag)")
        print(f"  LSN Distance:     {lsn_distance}")
        print(f"  Lag Size:         {lag_size}")
    else:
        print(f"  Status:           🔴 CRITICAL (High lag)")
        print(f"  LSN Distance:     {lsn_distance}")
        print(f"  Lag Size:         {lag_size}")
    print()
    
    # Publication Info
    if publication_info and 'error' not in publication_info:
        print("📚 PUBLICATION INFO")
        print("-" * 80)
        print(f"  Name:             {publication_info['name']}")
        print(f"  All Tables:       {'Yes' if publication_info['all_tables'] else 'No'}")
        print(f"  Replicate INSERT: {'Yes' if publication_info['insert'] else 'No'}")
        print(f"  Replicate UPDATE: {'Yes' if publication_info['update'] else 'No'}")
        print(f"  Replicate DELETE: {'Yes' if publication_info['delete'] else 'No'}")
        print()
    
    print("=" * 80)
    print("  Press Ctrl+C to stop monitoring")
    print("=" * 80)

def monitor_replication(host, port, database, user, password, slot_name, publication_name, interval):
    """
    Continuously monitor replication status.
    
    Args:
        host: Database host
        port: Database port
        database: Database name
        user: Database user
        password: Database password
        slot_name: Replication slot name
        publication_name: Publication name
        interval: Update interval in seconds
    """
    print(f"Connecting to {host}:{port}/{database}...")
    
    try:
        conn = psycopg2.connect(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password,
            connect_timeout=30
        )
        print("✅ Connected successfully")
        time.sleep(1)
    except Exception as e:
        print(f"❌ Connection failed: {str(e)}")
        sys.exit(1)
    
    iteration = 0
    start_time = time.time()
    
    try:
        while True:
            iteration += 1
            
            # Get replication status
            status = get_replication_status(conn, slot_name)
            
            # Get publication info (only on first iteration)
            publication_info = None
            if iteration == 1:
                publication_info = get_publication_info(conn, publication_name)
            
            # Display status
            display_status(status, publication_info, iteration, start_time)
            
            # Wait for next iteration
            time.sleep(interval)
            
    except KeyboardInterrupt:
        print("\n\n✅ Monitoring stopped by user")
    except Exception as e:
        print(f"\n\n❌ Error: {str(e)}")
    finally:
        conn.close()
        print("Connection closed")

def load_config(config_file, database_name):
    """Load database configuration from JSON file."""
    try:
        with open(config_file, 'r') as f:
            config = json.load(f)
        
        databases = config.get('databases', [])
        
        for db in databases:
            if db.get('database') == database_name:
                return db
        
        print(f"❌ Database '{database_name}' not found in configuration")
        sys.exit(1)
        
    except Exception as e:
        print(f"❌ Error loading configuration: {str(e)}")
        sys.exit(1)

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Monitor PostgreSQL logical replication status in real-time',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Monitor using configuration file
  python monitor_replication.py --config databases.json --database myapp_production
  
  # Monitor with custom interval (default is 5 seconds)
  python monitor_replication.py --config databases.json --database myapp_production --interval 10
  
  # Monitor using direct connection parameters
  python monitor_replication.py \\
    --host unencrypted-db.xxxxx.rds.amazonaws.com \\
    --database myapp_production \\
    --user postgres \\
    --password mypassword \\
    --slot myapp_prod_encryption_slot \\
    --publication myapp_prod_encryption_pub
        """
    )
    
    # Configuration file options
    parser.add_argument('--config', help='Path to JSON configuration file')
    parser.add_argument('--database', help='Database name from configuration')
    
    # Direct connection options
    parser.add_argument('--host', help='Database host')
    parser.add_argument('--port', type=int, default=5432, help='Database port (default: 5432)')
    parser.add_argument('--user', help='Database user')
    parser.add_argument('--password', help='Database password')
    parser.add_argument('--slot', help='Replication slot name')
    parser.add_argument('--publication', help='Publication name')
    
    # Monitoring options
    parser.add_argument('--interval', type=int, default=5, 
                       help='Update interval in seconds (default: 5)')
    
    args = parser.parse_args()
    
    # Determine connection parameters
    if args.config and args.database:
        # Load from configuration file
        db_config = load_config(args.config, args.database)
        
        host = db_config['source']['host']
        port = db_config['source'].get('port', 5432)
        database = db_config['source']['database']
        user = db_config['source']['user']
        password = db_config['source']['password']
        slot_name = db_config.get('slot_name', f"{database}_encryption_slot")
        publication_name = db_config.get('publication_name', f"{database}_encryption_pub")
        
    elif args.host and args.user and args.password and args.slot and args.publication:
        # Use direct parameters
        host = args.host
        port = args.port
        database = args.database or 'postgres'
        user = args.user
        password = args.password
        slot_name = args.slot
        publication_name = args.publication
        
    else:
        parser.print_help()
        print("\n❌ Error: Either provide --config and --database, or all direct connection parameters")
        sys.exit(1)
    
    # Start monitoring
    monitor_replication(
        host=host,
        port=port,
        database=database,
        user=user,
        password=password,
        slot_name=slot_name,
        publication_name=publication_name,
        interval=args.interval
    )

if __name__ == '__main__':
    main()
