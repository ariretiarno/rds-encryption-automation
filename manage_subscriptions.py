#!/usr/bin/env python3
"""
Automation script for creating and deleting PostgreSQL subscriptions
for RDS encryption with minimal downtime.

Based on: https://aws.amazon.com/blogs/database/encrypt-amazon-rds-for-postgresql-and-amazon-aurora-postgresql-database-with-minimal-downtime/
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


def create_subscription(
    replication_conn,
    dbname: str,
    master_host: str,
    master_user: str,
    master_password: str,
    lsn: str
) -> bool:
    """
    Create a subscription for a database.
    
    Args:
        replication_conn: Connection to replication database
        dbname: Database name
        master_host: Master database host
        master_user: Master database user
        master_password: Master database password
        lsn: Log Sequence Number
        
    Returns:
        True if successful, False otherwise
    """
    normalized_name = normalize_name(dbname)
    subscription_name = f"{normalized_name}_sub"
    publication_name = f"{normalized_name}_pub"
    slot_name = f"{normalized_name}_slot"
    
    try:
        cursor = replication_conn.cursor()
        
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
        connection_string = f"host={master_host} user={master_user} password={master_password} dbname={dbname}"
        
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
        
        logger.info(f"Creating subscription '{subscription_name}' for database '{dbname}'...")
        cursor.execute(create_sub_query)
        
        # Find unused replication origin for this subscription
        # Get all replication origins
        cursor.execute("SELECT roname FROM pg_replication_origin WHERE roname LIKE 'pg_%'")
        all_origins = [row[0] for row in cursor.fetchall()]
        
        # Get used/active replication origins by joining with pg_replication_origin
        cursor.execute("""
            SELECT o.roname 
            FROM pg_replication_origin o
            INNER JOIN pg_replication_origin_status s ON o.roident = s.local_id
            WHERE o.roname LIKE 'pg_%'
        """)
        used_origins = [row[0] for row in cursor.fetchall()]
        
        # Find unused origins
        unused_origins = [origin for origin in all_origins if origin not in used_origins]
        
        if unused_origins:
            # Use the first unused origin
            origin_name = unused_origins[0]
            logger.info(f"Found unused replication origin: '{origin_name}'")
            logger.info(f"Advancing replication origin '{origin_name}' to LSN '{lsn}'...")
            
            # Advance replication origin
            cursor.execute(
                sql.SQL("SELECT pg_replication_origin_advance(%s, %s)"),
                (origin_name, lsn)
            )
            
            logger.info(f"Successfully advanced origin '{origin_name}' to LSN '{lsn}'")
        else:
            logger.warning(f"No unused replication origins found. Subscription created but origin not advanced.")
            logger.warning(f"Available origins: {len(all_origins)}, Used origins: {len(used_origins)}")
        
        # Enable subscription
        logger.info(f"Enabling subscription '{subscription_name}'...")
        cursor.execute(f"ALTER SUBSCRIPTION {subscription_name} ENABLE")
        
        cursor.close()
        logger.info(f"✓ Successfully created and enabled subscription '{subscription_name}'")
        return True
        
    except Exception as e:
        logger.error(f"✗ Failed to create subscription for '{dbname}': {e}")
        return False


def delete_subscription(replication_conn, dbname: str) -> bool:
    """
    Delete a subscription for a database.
    
    Args:
        replication_conn: Connection to replication database
        dbname: Database name
        
    Returns:
        True if successful, False otherwise
    """
    normalized_name = normalize_name(dbname)
    subscription_name = f"{normalized_name}_sub"
    
    try:
        cursor = replication_conn.cursor()
        
        # Check if subscription exists
        cursor.execute(
            "SELECT subname FROM pg_subscription WHERE subname = %s",
            (subscription_name,)
        )
        if not cursor.fetchone():
            logger.warning(f"Subscription '{subscription_name}' does not exist. Skipping.")
            cursor.close()
            return False
        
        logger.info(f"Deleting subscription '{subscription_name}' for database '{dbname}'...")
        
        # Disable subscription
        logger.info(f"Disabling subscription '{subscription_name}'...")
        cursor.execute(f"ALTER SUBSCRIPTION {subscription_name} DISABLE")
        
        # Remove slot
        logger.info(f"Removing slot from subscription '{subscription_name}'...")
        cursor.execute(f"ALTER SUBSCRIPTION {subscription_name} SET (slot_name = NONE)")
        
        # Drop subscription
        logger.info(f"Dropping subscription '{subscription_name}'...")
        cursor.execute(f"DROP SUBSCRIPTION {subscription_name}")
        
        cursor.close()
        logger.info(f"✓ Successfully deleted subscription '{subscription_name}'")
        return True
        
    except Exception as e:
        logger.error(f"✗ Failed to delete subscription for '{dbname}': {e}")
        return False


def list_subscriptions(replication_conn) -> List[Tuple]:
    """
    List all subscriptions in the database.
    
    Args:
        replication_conn: Connection to replication database
        
    Returns:
        List of tuples containing subscription information
    """
    try:
        cursor = replication_conn.cursor()
        cursor.execute("""
            SELECT 
                subname,
                subenabled,
                subslotname,
                subpublications
            FROM pg_subscription
            ORDER BY subname
        """)
        subscriptions = cursor.fetchall()
        cursor.close()
        return subscriptions
    except Exception as e:
        logger.error(f"Failed to list subscriptions: {e}")
        return []


def main():
    """Main function to manage subscriptions."""
    # Load environment variables
    load_dotenv()
    
    # Get configuration from environment
    replication_host = os.getenv('REPLICATION_DB_HOST')
    replication_port = os.getenv('REPLICATION_DB_PORT', '5432')
    replication_user = os.getenv('REPLICATION_DB_USER')
    replication_password = os.getenv('REPLICATION_DB_PASSWORD')
    
    master_host = os.getenv('MASTER_DB_HOST')
    master_port = os.getenv('MASTER_DB_PORT', '5432')
    master_user = os.getenv('MASTER_DB_USER')
    master_password = os.getenv('MASTER_DB_PASSWORD')
    
    lsn = os.getenv('LSN')
    databases_str = os.getenv('DATABASES', '')
    
    # Validate configuration
    if not all([replication_host, replication_user, replication_password, master_host, master_user, master_password, lsn]):
        logger.error("Missing required environment variables. Please check your .env file.")
        logger.error("Required: REPLICATION_DB_HOST, REPLICATION_DB_USER, REPLICATION_DB_PASSWORD, MASTER_DB_HOST, MASTER_DB_USER, MASTER_DB_PASSWORD, LSN")
        sys.exit(1)
    
    if not databases_str:
        logger.error("No databases specified in DATABASES environment variable.")
        sys.exit(1)
    
    # Parse database list
    databases = [db.strip() for db in databases_str.split(',') if db.strip()]
    
    if not databases:
        logger.error("No valid databases found in DATABASES environment variable.")
        sys.exit(1)
    
    logger.info(f"Found {len(databases)} database(s) to process")
    
    # Get action from command line
    action = sys.argv[1] if len(sys.argv) > 1 else 'create'
    
    if action not in ['create', 'delete', 'list']:
        logger.error(f"Invalid action '{action}'. Use 'create', 'delete', or 'list'.")
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
            
            if action == 'create':
                if create_subscription(conn, dbname, master_host, master_user, master_password, lsn):
                    success_count += 1
                else:
                    failure_count += 1
                    
            elif action == 'delete':
                if delete_subscription(conn, dbname):
                    success_count += 1
                else:
                    failure_count += 1
                    
            elif action == 'list':
                subscriptions = list_subscriptions(conn)
                if subscriptions:
                    logger.info(f"\nSubscriptions in '{dbname}':")
                    for sub in subscriptions:
                        logger.info(f"  - Name: {sub[0]}, Enabled: {sub[1]}, Slot: {sub[2]}, Publications: {sub[3]}")
                else:
                    logger.info(f"No subscriptions found in '{dbname}'")
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
    logger.info(f"Total databases: {len(databases)}")
    logger.info(f"Successful: {success_count}")
    logger.info(f"Failed: {failure_count}")
    logger.info(f"{'='*60}\n")
    
    if failure_count > 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
