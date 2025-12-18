#!/usr/bin/env python3
"""
Script to monitor replication health and detect inactive slots.
Helps identify when replication is broken due to DDL changes or other issues.
"""

import os
import sys
import psycopg2
from dotenv import load_dotenv
import logging
from datetime import datetime
from typing import List, Dict, Tuple
import re

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


def check_replication_slot_status(master_conn, dbname: str) -> Dict:
    """
    Check the status of a replication slot on master database.
    
    Returns:
        Dictionary with slot information including active status and lag
    """
    normalized_name = normalize_name(dbname)
    slot_name = f"{normalized_name}_slot"
    
    try:
        cursor = master_conn.cursor()
        
        # Get detailed slot information
        cursor.execute("""
            SELECT 
                slot_name,
                slot_type,
                database,
                active,
                restart_lsn,
                confirmed_flush_lsn,
                pg_current_wal_lsn() as current_lsn,
                pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) as restart_lag_bytes,
                pg_wal_lsn_diff(pg_current_wal_lsn(), confirmed_flush_lsn) as flush_lag_bytes
            FROM pg_replication_slots
            WHERE slot_name = %s
        """, (slot_name,))
        
        result = cursor.fetchone()
        cursor.close()
        
        if not result:
            return {
                'exists': False,
                'dbname': dbname,
                'slot_name': slot_name
            }
        
        return {
            'exists': True,
            'dbname': dbname,
            'slot_name': result[0],
            'slot_type': result[1],
            'database': result[2],
            'active': result[3],
            'restart_lsn': result[4],
            'confirmed_flush_lsn': result[5],
            'current_lsn': result[6],
            'restart_lag_bytes': result[7] if result[7] else 0,
            'flush_lag_bytes': result[8] if result[8] else 0,
            'restart_lag_mb': round(result[7] / 1024 / 1024, 2) if result[7] else 0,
            'flush_lag_mb': round(result[8] / 1024 / 1024, 2) if result[8] else 0
        }
        
    except Exception as e:
        logger.error(f"Failed to check slot status for '{dbname}': {e}")
        return {'exists': False, 'error': str(e)}


def check_subscription_status(replication_conn, dbname: str) -> Dict:
    """
    Check the status of a subscription on replication database.
    
    Returns:
        Dictionary with subscription information
    """
    normalized_name = normalize_name(dbname)
    subscription_name = f"{normalized_name}_sub"
    
    try:
        cursor = replication_conn.cursor()
        
        # Get subscription status
        cursor.execute("""
            SELECT 
                s.subname,
                s.subenabled,
                s.subslotname,
                s.subpublications,
                sr.srsubid,
                sr.srrelid::regclass as table_name,
                sr.srsubstate,
                sr.srsublsn
            FROM pg_subscription s
            LEFT JOIN pg_subscription_rel sr ON s.oid = sr.srsubid
            WHERE s.subname = %s
            ORDER BY sr.srrelid
        """, (subscription_name,))
        
        results = cursor.fetchall()
        cursor.close()
        
        if not results:
            return {
                'exists': False,
                'dbname': dbname,
                'subscription_name': subscription_name
            }
        
        # First row has subscription info
        first_row = results[0]
        
        # Count table states
        table_states = {}
        for row in results:
            if row[6]:  # srsubstate
                state = row[6]
                table_states[state] = table_states.get(state, 0) + 1
        
        return {
            'exists': True,
            'dbname': dbname,
            'subscription_name': first_row[0],
            'enabled': first_row[1],
            'slot_name': first_row[2],
            'publications': first_row[3],
            'total_tables': len(results),
            'table_states': table_states,
            'all_ready': all(row[6] == 'r' for row in results if row[6])
        }
        
    except Exception as e:
        logger.error(f"Failed to check subscription status for '{dbname}': {e}")
        return {'exists': False, 'error': str(e)}


def check_replication_lag(master_conn, replication_conn, dbname: str) -> Dict:
    """
    Check replication lag by comparing LSN positions.
    
    Returns:
        Dictionary with lag information
    """
    try:
        # Get master current LSN
        master_cursor = master_conn.cursor()
        master_cursor.execute("SELECT pg_current_wal_lsn()")
        master_lsn = master_cursor.fetchone()[0]
        master_cursor.close()
        
        # Get replication received and replayed LSN
        repl_cursor = replication_conn.cursor()
        repl_cursor.execute("""
            SELECT 
                pg_last_wal_receive_lsn() as received_lsn,
                pg_last_wal_replay_lsn() as replayed_lsn,
                pg_wal_lsn_diff(pg_last_wal_receive_lsn(), pg_last_wal_replay_lsn()) as replay_lag_bytes
        """)
        result = repl_cursor.fetchone()
        repl_cursor.close()
        
        if result and result[0] and result[1]:
            return {
                'dbname': dbname,
                'master_lsn': master_lsn,
                'received_lsn': result[0],
                'replayed_lsn': result[1],
                'replay_lag_bytes': result[2] if result[2] else 0,
                'replay_lag_mb': round(result[2] / 1024 / 1024, 2) if result[2] else 0
            }
        else:
            return {
                'dbname': dbname,
                'error': 'No replication activity detected'
            }
            
    except Exception as e:
        logger.error(f"Failed to check replication lag for '{dbname}': {e}")
        return {'dbname': dbname, 'error': str(e)}


def main():
    """Main function to monitor replication health."""
    load_dotenv()
    
    # Get configuration
    master_host = os.getenv('MASTER_DB_HOST')
    master_port = os.getenv('MASTER_DB_PORT', '5432')
    master_user = os.getenv('MASTER_DB_USER')
    master_password = os.getenv('MASTER_DB_PASSWORD')
    
    replication_host = os.getenv('REPLICATION_DB_HOST')
    replication_port = os.getenv('REPLICATION_DB_PORT', '5432')
    replication_user = os.getenv('REPLICATION_DB_USER')
    replication_password = os.getenv('REPLICATION_DB_PASSWORD')
    
    databases_str = os.getenv('DATABASES', '')
    
    # Validate configuration
    if not all([master_host, master_user, master_password, replication_host, replication_user, replication_password]):
        logger.error("Missing required environment variables.")
        sys.exit(1)
    
    if not databases_str:
        logger.error("No databases specified in DATABASES environment variable.")
        sys.exit(1)
    
    databases = [db.strip() for db in databases_str.split(',') if db.strip()]
    
    logger.info(f"Monitoring replication health for {len(databases)} database(s)")
    logger.info(f"Master: {master_host}:{master_port}")
    logger.info(f"Replication: {replication_host}:{replication_port}")
    
    # Track issues
    inactive_slots = []
    disabled_subscriptions = []
    high_lag_databases = []
    errors = []
    
    for dbname in databases:
        logger.info(f"\n{'='*60}")
        logger.info(f"Checking: {dbname}")
        logger.info(f"{'='*60}")
        
        try:
            # Connect to both master and replication
            master_conn = get_connection(master_host, master_port, master_user, master_password, dbname)
            replication_conn = get_connection(replication_host, replication_port, replication_user, replication_password, dbname)
            
            # Check replication slot on master
            slot_status = check_replication_slot_status(master_conn, dbname)
            
            if slot_status.get('exists'):
                logger.info(f"Slot Status:")
                logger.info(f"  - Active: {slot_status['active']}")
                logger.info(f"  - Restart LSN: {slot_status['restart_lsn']}")
                logger.info(f"  - Confirmed Flush LSN: {slot_status['confirmed_flush_lsn']}")
                logger.info(f"  - Restart Lag: {slot_status['restart_lag_mb']} MB")
                logger.info(f"  - Flush Lag: {slot_status['flush_lag_mb']} MB")
                
                if not slot_status['active']:
                    logger.warning(f"⚠️  INACTIVE SLOT detected for '{dbname}'")
                    inactive_slots.append(dbname)
                
                if slot_status['flush_lag_mb'] > 100:  # More than 100MB lag
                    logger.warning(f"⚠️  HIGH LAG detected for '{dbname}': {slot_status['flush_lag_mb']} MB")
                    high_lag_databases.append({
                        'dbname': dbname,
                        'lag_mb': slot_status['flush_lag_mb']
                    })
            else:
                logger.warning(f"⚠️  Replication slot not found for '{dbname}'")
            
            # Check subscription on replication
            sub_status = check_subscription_status(replication_conn, dbname)
            
            if sub_status.get('exists'):
                logger.info(f"Subscription Status:")
                logger.info(f"  - Enabled: {sub_status['enabled']}")
                logger.info(f"  - Total Tables: {sub_status['total_tables']}")
                logger.info(f"  - Table States: {sub_status['table_states']}")
                logger.info(f"  - All Ready: {sub_status['all_ready']}")
                
                if not sub_status['enabled']:
                    logger.warning(f"⚠️  DISABLED SUBSCRIPTION detected for '{dbname}'")
                    disabled_subscriptions.append(dbname)
                
                if not sub_status['all_ready']:
                    logger.warning(f"⚠️  Some tables not in 'ready' state for '{dbname}'")
            else:
                logger.warning(f"⚠️  Subscription not found for '{dbname}'")
            
            # Check replication lag
            lag_info = check_replication_lag(master_conn, replication_conn, dbname)
            if 'error' not in lag_info:
                logger.info(f"Replication Lag:")
                logger.info(f"  - Replay Lag: {lag_info['replay_lag_mb']} MB")
            
            master_conn.close()
            replication_conn.close()
            
        except Exception as e:
            logger.error(f"Error checking '{dbname}': {e}")
            errors.append({'dbname': dbname, 'error': str(e)})
    
    # Summary Report
    logger.info(f"\n{'='*60}")
    logger.info(f"MONITORING SUMMARY")
    logger.info(f"{'='*60}")
    logger.info(f"Total Databases Checked: {len(databases)}")
    logger.info(f"Inactive Slots: {len(inactive_slots)}")
    logger.info(f"Disabled Subscriptions: {len(disabled_subscriptions)}")
    logger.info(f"High Lag Databases: {len(high_lag_databases)}")
    logger.info(f"Errors: {len(errors)}")
    
    if inactive_slots:
        logger.warning(f"\n⚠️  INACTIVE SLOTS DETECTED:")
        for db in inactive_slots:
            logger.warning(f"  - {db}")
        logger.warning(f"\nAction Required: Run recovery script to reconnect these slots")
    
    if disabled_subscriptions:
        logger.warning(f"\n⚠️  DISABLED SUBSCRIPTIONS DETECTED:")
        for db in disabled_subscriptions:
            logger.warning(f"  - {db}")
    
    if high_lag_databases:
        logger.warning(f"\n⚠️  HIGH LAG DETECTED:")
        for item in high_lag_databases:
            logger.warning(f"  - {item['dbname']}: {item['lag_mb']} MB")
    
    logger.info(f"{'='*60}\n")
    
    # Exit with error if issues found
    if inactive_slots or disabled_subscriptions or errors:
        sys.exit(1)


if __name__ == '__main__':
    main()
