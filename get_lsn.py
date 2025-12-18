#!/usr/bin/env python3
"""
Helper script to get the correct LSN for rollback/reverse replication.

This script helps you determine the correct LSN to use when setting up
reverse replication (rollback from replica to master).
"""

import os
import sys
import psycopg2
from dotenv import load_dotenv
import logging
from typing import Optional, Dict, List

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


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
        logger.error(f"Failed to connect to database '{dbname}' on {host}: {e}")
        raise


def get_current_wal_lsn(conn) -> Optional[str]:
    """Get the current WAL LSN from the database."""
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT pg_current_wal_lsn()")
        lsn = cursor.fetchone()[0]
        cursor.close()
        return lsn
    except Exception as e:
        logger.error(f"Failed to get current WAL LSN: {e}")
        return None


def get_replication_slot_lsn(conn) -> List[Dict]:
    """Get LSN information from replication slots."""
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                slot_name,
                slot_type,
                confirmed_flush_lsn,
                restart_lsn,
                (pg_current_wal_lsn() - confirmed_flush_lsn) AS lag_bytes
            FROM pg_replication_slots
            WHERE slot_type = 'logical'
            ORDER BY slot_name
        """)
        
        slots = []
        for row in cursor.fetchall():
            slots.append({
                'slot_name': row[0],
                'slot_type': row[1],
                'confirmed_flush_lsn': row[2],
                'restart_lsn': row[3],
                'lag_bytes': row[4]
            })
        
        cursor.close()
        return slots
    except Exception as e:
        logger.error(f"Failed to get replication slot LSN: {e}")
        return []


def get_replication_origin_lsn(conn) -> List[Dict]:
    """Get LSN information from replication origins."""
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                ros.external_id,
                ros.remote_lsn,
                ros.local_lsn,
                s.subname AS subscription_name,
                s.subenabled AS enabled,
                ro.roname AS origin_name
            FROM pg_replication_origin_status ros
            JOIN pg_replication_origin ro ON ros.local_id = ro.roident
            JOIN pg_subscription s ON ro.roname = 'pg_' || s.oid::text
            ORDER BY s.subname
        """)
        
        origins = []
        for row in cursor.fetchall():
            origins.append({
                'external_id': row[0],
                'remote_lsn': row[1],
                'local_lsn': row[2],
                'subscription_name': row[3],
                'enabled': row[4],
                'origin_name': row[5]
            })
        
        cursor.close()
        return origins
    except Exception as e:
        logger.error(f"Failed to get replication origin LSN: {e}")
        return []


def check_replication_lag(conn) -> Optional[Dict]:
    """Check replication lag for logical replication."""
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                slot_name,
                confirmed_flush_lsn AS flushed,
                pg_current_wal_lsn() AS current_lsn,
                (pg_current_wal_lsn() - confirmed_flush_lsn) AS lsn_distance_bytes,
                pg_size_pretty(pg_current_wal_lsn() - confirmed_flush_lsn) AS lsn_distance
            FROM pg_catalog.pg_replication_slots
            WHERE slot_type = 'logical'
        """)
        
        results = []
        for row in cursor.fetchall():
            results.append({
                'slot_name': row[0],
                'flushed': row[1],
                'current_lsn': row[2],
                'lsn_distance_bytes': row[3],
                'lsn_distance': row[4]
            })
        
        cursor.close()
        return results
    except Exception as e:
        logger.error(f"Failed to check replication lag: {e}")
        return None


def print_separator():
    """Print a separator line."""
    print("=" * 80)


def main():
    """Main function to get LSN information."""
    load_dotenv()
    
    # Get database type from command line
    if len(sys.argv) < 2:
        print("Usage: python get_lsn.py [master|replica]")
        print("\nExamples:")
        print("  python get_lsn.py master   # Get LSN info from master database")
        print("  python get_lsn.py replica  # Get LSN info from replica database")
        sys.exit(1)
    
    db_type = sys.argv[1].lower()
    
    if db_type not in ['master', 'replica']:
        logger.error("Invalid database type. Use 'master' or 'replica'")
        sys.exit(1)
    
    # Get configuration based on database type
    if db_type == 'master':
        host = os.getenv('MASTER_DB_HOST')
        port = os.getenv('MASTER_DB_PORT', '5432')
        user = os.getenv('MASTER_DB_USER')
        password = os.getenv('MASTER_DB_PASSWORD')
        db_label = "MASTER"
    else:  # replica
        host = os.getenv('REPLICATION_DB_HOST')
        port = os.getenv('REPLICATION_DB_PORT', '5432')
        user = os.getenv('REPLICATION_DB_USER')
        password = os.getenv('REPLICATION_DB_PASSWORD')
        db_label = "REPLICA"
    
    # Get database list
    databases_str = os.getenv('DATABASES', '')
    databases = [db.strip() for db in databases_str.split(',') if db.strip()]
    
    if not databases:
        logger.error("No databases specified in DATABASES environment variable")
        sys.exit(1)
    
    # Validate configuration
    if not all([host, user, password]):
        logger.error(f"Missing required environment variables for {db_label} database")
        sys.exit(1)
    
    print_separator()
    print(f"LSN INFORMATION FOR {db_label} DATABASE")
    print(f"Host: {host}")
    print_separator()
    print()
    
    # Process first database for general info
    dbname = databases[0]
    
    try:
        conn = get_connection(host, port, user, password, dbname)
        
        # 1. Get current WAL LSN
        print("1. CURRENT WAL LSN (Use this for rollback if replica is fully synced)")
        print_separator()
        current_lsn = get_current_wal_lsn(conn)
        if current_lsn:
            print(f"   Current WAL LSN: {current_lsn}")
            print(f"\n   ✓ RECOMMENDED FOR ROLLBACK: {current_lsn}")
            print("   (Only if this is the REPLICA and it's fully caught up)")
        print()
        
        # 2. Get replication slot information
        print("2. REPLICATION SLOTS (Shows what subscribers have confirmed)")
        print_separator()
        slots = get_replication_slot_lsn(conn)
        if slots:
            for slot in slots:
                print(f"   Slot: {slot['slot_name']}")
                print(f"   - Confirmed Flush LSN: {slot['confirmed_flush_lsn']}")
                print(f"   - Restart LSN: {slot['restart_lsn']}")
                print(f"   - Lag: {slot['lag_bytes']} bytes")
                print()
        else:
            print("   No replication slots found")
        print()
        
        # 3. Get replication origin information
        print("3. REPLICATION ORIGINS (Shows what this database has received)")
        print_separator()
        origins = get_replication_origin_lsn(conn)
        if origins:
            for origin in origins:
                print(f"   Subscription: {origin['subscription_name']}")
                print(f"   - Remote LSN: {origin['remote_lsn']}")
                print(f"   - Local LSN: {origin['local_lsn']}")
                print(f"   - Enabled: {origin['enabled']}")
                print(f"   - Origin Name: {origin['origin_name']}")
                print()
        else:
            print("   No replication origins found")
        print()
        
        # 4. Check replication lag
        print("4. REPLICATION LAG (Check if fully synced)")
        print_separator()
        lag_info = check_replication_lag(conn)
        if lag_info:
            all_synced = True
            for lag in lag_info:
                print(f"   Slot: {lag['slot_name']}")
                print(f"   - Current LSN: {lag['current_lsn']}")
                print(f"   - Flushed LSN: {lag['flushed']}")
                print(f"   - Distance: {lag['lsn_distance']} ({lag['lsn_distance_bytes']} bytes)")
                
                if lag['lsn_distance_bytes'] > 0:
                    print(f"   - Status: ⚠️  NOT SYNCED (lag: {lag['lsn_distance']})")
                    all_synced = False
                else:
                    print(f"   - Status: ✓ FULLY SYNCED")
                print()
            
            if all_synced:
                print("   ✓ ALL SLOTS ARE FULLY SYNCED - Safe to record LSN for rollback")
            else:
                print("   ⚠️  SOME SLOTS HAVE LAG - Wait for sync before recording LSN")
        else:
            print("   No replication lag information available")
        print()
        
        conn.close()
        
        # Summary and recommendations
        print_separator()
        print("RECOMMENDATIONS FOR ROLLBACK")
        print_separator()
        print()
        
        if db_type == 'replica':
            print("You are checking the REPLICA database.")
            print()
            print("For ROLLBACK (Replica becomes Master):")
            print("1. Ensure all replication slots show 'FULLY SYNCED' above")
            print("2. Stop all writes to the current MASTER")
            print("3. Wait for replication to catch up (lag = 0)")
            print(f"4. Use this LSN for reverse subscription: {current_lsn}")
            print()
            print("Next steps:")
            print("  a. Update .env file with LSN=" + (current_lsn or ""))
            print("  b. Create publications on REPLICA (new master)")
            print("  c. Create subscriptions on OLD MASTER (new replica)")
        else:
            print("You are checking the MASTER database.")
            print()
            print("For ROLLBACK preparation:")
            print("1. Check replication lag is 0 (all slots fully synced)")
            print("2. Then run: python get_lsn.py replica")
            print("3. Record the LSN from the REPLICA")
            print("4. Use that LSN when creating reverse subscriptions")
        
        print()
        print_separator()
        
    except Exception as e:
        logger.error(f"Error getting LSN information: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
