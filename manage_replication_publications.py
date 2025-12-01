#!/usr/bin/env python3
"""
Automation script for deleting PostgreSQL publications and replication slots
at the replication database for RDS encryption with minimal downtime.

This script operates on the REPLICATION database (not the master database).
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
    """
    Convert special characters in database name to underscore.
    
    Args:
        name: Original database name
        
    Returns:
        Normalized name with special characters replaced by underscore
    """
    # Replace any non-alphanumeric character (except underscore) with underscore
    normalized = re.sub(r'[^a-zA-Z0-9_]', '_', name)
    logger.debug(f"Normalized '{name}' to '{normalized}'")
    return normalized


def get_connection(host: str, port: str, user: str, password: str, dbname: str):
    """
    Create a PostgreSQL database connection.
    
    Args:
        host: Database host
        port: Database port
        user: Database user
        password: Database password
        dbname: Database name
        
    Returns:
        psycopg2 connection object
    """
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


def delete_publication(replication_conn, dbname: str) -> bool:
    """
    Delete a publication from a database.
    
    Args:
        replication_conn: Connection to replication database
        dbname: Database name
        
    Returns:
        True if successful, False otherwise
    """
    normalized_name = normalize_name(dbname)
    publication_name = f"{normalized_name}_pub"
    
    try:
        cursor = replication_conn.cursor()
        
        # Check if publication exists
        cursor.execute(
            "SELECT pubname FROM pg_publication WHERE pubname = %s",
            (publication_name,)
        )
        if not cursor.fetchone():
            logger.warning(f"Publication '{publication_name}' does not exist. Skipping.")
            cursor.close()
            return False
        
        # Drop publication
        logger.info(f"Deleting publication '{publication_name}' for database '{dbname}'...")
        cursor.execute(f"DROP PUBLICATION {publication_name}")
        
        cursor.close()
        logger.info(f"✓ Successfully deleted publication '{publication_name}'")
        return True
        
    except Exception as e:
        logger.error(f"✗ Failed to delete publication for '{dbname}': {e}")
        return False


def delete_replication_slot(replication_conn, dbname: str) -> bool:
    """
    Delete a replication slot from a database.
    
    Args:
        replication_conn: Connection to replication database
        dbname: Database name
        
    Returns:
        True if successful, False otherwise
    """
    normalized_name = normalize_name(dbname)
    slot_name = f"{normalized_name}_slot"
    
    try:
        cursor = replication_conn.cursor()
        
        # Check if replication slot exists
        cursor.execute(
            "SELECT slot_name FROM pg_replication_slots WHERE slot_name = %s",
            (slot_name,)
        )
        if not cursor.fetchone():
            logger.warning(f"Replication slot '{slot_name}' does not exist. Skipping.")
            cursor.close()
            return False
        
        # Drop replication slot
        logger.info(f"Deleting replication slot '{slot_name}' for database '{dbname}'...")
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


def list_publications(replication_conn) -> List[Tuple]:
    """
    List all publications in the database.
    
    Args:
        replication_conn: Connection to replication database
        
    Returns:
        List of tuples containing publication information
    """
    try:
        cursor = replication_conn.cursor()
        cursor.execute("""
            SELECT 
                pubname,
                pubowner::regrole,
                puballtables,
                pubinsert,
                pubupdate,
                pubdelete
            FROM pg_publication
            ORDER BY pubname
        """)
        publications = cursor.fetchall()
        cursor.close()
        return publications
    except Exception as e:
        logger.error(f"Failed to list publications: {e}")
        return []


def list_replication_slots(replication_conn) -> List[Tuple]:
    """
    List all replication slots in the database.
    
    Args:
        replication_conn: Connection to replication database
        
    Returns:
        List of tuples containing replication slot information
    """
    try:
        cursor = replication_conn.cursor()
        cursor.execute("""
            SELECT 
                slot_name,
                plugin,
                slot_type,
                database,
                active,
                restart_lsn
            FROM pg_replication_slots
            ORDER BY slot_name
        """)
        slots = cursor.fetchall()
        cursor.close()
        return slots
    except Exception as e:
        logger.error(f"Failed to list replication slots: {e}")
        return []


def main():
    """Main function to manage publications and replication slots on replication database."""
    # Load environment variables
    load_dotenv()
    
    # Get configuration from environment - using REPLICATION_DB_HOST
    replication_host = os.getenv('REPLICATION_DB_HOST')
    replication_port = os.getenv('REPLICATION_DB_PORT', '5432')
    replication_user = os.getenv('REPLICATION_DB_USER')
    replication_password = os.getenv('REPLICATION_DB_PASSWORD')
    
    databases_str = os.getenv('DATABASES', '')
    
    # Validate configuration
    if not all([replication_host, replication_user, replication_password]):
        logger.error("Missing required environment variables. Please check your .env file.")
        logger.error("Required: REPLICATION_DB_HOST, REPLICATION_DB_USER, REPLICATION_DB_PASSWORD")
        sys.exit(1)
    
    if not databases_str:
        logger.error("No databases specified in DATABASES environment variable.")
        sys.exit(1)
    
    # Parse database list
    databases = [db.strip() for db in databases_str.split(',') if db.strip()]
    
    if not databases:
        logger.error("No valid databases found in DATABASES environment variable.")
        sys.exit(1)
    
    logger.info(f"Found {len(databases)} database(s) to process on REPLICATION database")
    logger.info(f"Replication Host: {replication_host}")
    
    # Get action from command line
    action = sys.argv[1] if len(sys.argv) > 1 else 'delete'
    
    if action not in ['delete', 'list']:
        logger.error(f"Invalid action '{action}'. Use 'delete' or 'list'.")
        sys.exit(1)
    
    # Process each database
    success_count = 0
    failure_count = 0
    
    for dbname in databases:
        logger.info(f"\n{'='*60}")
        logger.info(f"Processing database: {dbname}")
        logger.info(f"{'='*60}")
        
        try:
            # Connect to replication database
            conn = get_connection(
                replication_host,
                replication_port,
                replication_user,
                replication_password,
                dbname
            )
            
            if action == 'delete':
                # Delete replication slot first, then publication
                slot_success = delete_replication_slot(conn, dbname)
                pub_success = delete_publication(conn, dbname)
                
                if pub_success or slot_success:
                    success_count += 1
                else:
                    failure_count += 1
                    
            elif action == 'list':
                logger.info(f"\nPublications in '{dbname}':")
                publications = list_publications(conn)
                if publications:
                    for pub in publications:
                        logger.info(f"  - Name: {pub[0]}, Owner: {pub[1]}, All Tables: {pub[2]}")
                else:
                    logger.info(f"  No publications found")
                
                logger.info(f"\nReplication Slots in '{dbname}':")
                slots = list_replication_slots(conn)
                if slots:
                    for slot in slots:
                        logger.info(f"  - Name: {slot[0]}, Plugin: {slot[1]}, Type: {slot[2]}, Active: {slot[4]}, LSN: {slot[5]}")
                else:
                    logger.info(f"  No replication slots found")
                
                success_count += 1
            
            conn.close()
            
        except Exception as e:
            logger.error(f"Error processing database '{dbname}': {e}")
            failure_count += 1
    
    # Summary
    logger.info(f"\n{'='*60}")
    logger.info(f"SUMMARY")
    logger.info(f"{'='*60}")
    logger.info(f"Action: {action.upper()}")
    logger.info(f"Database Host: {replication_host}")
    logger.info(f"Total databases: {len(databases)}")
    logger.info(f"Successful: {success_count}")
    logger.info(f"Failed: {failure_count}")
    logger.info(f"{'='*60}\n")
    
    if failure_count > 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
