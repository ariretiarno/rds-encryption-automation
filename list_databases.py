#!/usr/bin/env python3
"""
Script to list all databases from PostgreSQL and save them to a text file
in comma-separated format: DB1,DB2,DB3,DB4
"""

import os
import sys
import psycopg2
from dotenv import load_dotenv
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_connection(host: str, port: str, user: str, password: str, dbname: str = 'postgres'):
    """
    Create a PostgreSQL database connection.
    
    Args:
        host: Database host
        port: Database port
        user: Database user
        password: Database password
        dbname: Database name (default: postgres)
        
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
        logger.debug(f"Connected to database '{dbname}' on {host}")
        return conn
    except Exception as e:
        logger.error(f"Failed to connect to database '{dbname}': {e}")
        raise


def list_all_databases(conn):
    """
    List all databases excluding system databases.
    
    Args:
        conn: PostgreSQL connection object
        
    Returns:
        List of database names
    """
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT datname 
            FROM pg_database 
            WHERE datistemplate = false 
            AND datname NOT IN ('postgres', 'rdsadmin')
            ORDER BY datname
        """)
        databases = [row[0] for row in cursor.fetchall()]
        cursor.close()
        return databases
    except Exception as e:
        logger.error(f"Failed to list databases: {e}")
        raise


def main():
    """Main function to list databases and save to file."""
    # Load environment variables
    load_dotenv()
    
    # Get target database from command line argument (default: master)
    target = sys.argv[1].lower() if len(sys.argv) > 1 else 'master'
    
    if target not in ['master', 'replication']:
        logger.error(f"Invalid target '{target}'. Use 'master' or 'replication'.")
        logger.error("Usage: python3 list_databases.py [master|replication]")
        sys.exit(1)
    
    # Determine which database configuration to use based on target
    if target == 'master':
        db_host = os.getenv('MASTER_DB_HOST')
        db_port = os.getenv('MASTER_DB_PORT', '5432')
        db_user = os.getenv('MASTER_DB_USER')
        db_password = os.getenv('MASTER_DB_PASSWORD')
    else:  # replication
        db_host = os.getenv('REPLICATION_DB_HOST')
        db_port = os.getenv('REPLICATION_DB_PORT', '5432')
        db_user = os.getenv('REPLICATION_DB_USER')
        db_password = os.getenv('REPLICATION_DB_PASSWORD')
    
    # Validate configuration
    if not all([db_host, db_user, db_password]):
        logger.error(f"Missing required environment variables for {target.upper()} database.")
        logger.error(f"Required: {target.upper()}_DB_HOST, {target.upper()}_DB_USER, {target.upper()}_DB_PASSWORD")
        sys.exit(1)
    
    logger.info(f"Target: {target.upper()} database")
    
    output_file = 'databases_list.txt'
    
    try:
        logger.info(f"Connecting to PostgreSQL server at {db_host}:{db_port}...")
        
        # Connect to postgres database to list all databases
        conn = get_connection(db_host, db_port, db_user, db_password, 'postgres')
        
        logger.info("Fetching list of databases...")
        databases = list_all_databases(conn)
        
        conn.close()
        
        if not databases:
            logger.warning("No databases found.")
            sys.exit(0)
        
        # Format as comma-separated list
        databases_str = ','.join(databases)
        
        # Write to file
        with open(output_file, 'w') as f:
            f.write(databases_str)
        
        logger.info(f"✓ Successfully listed {len(databases)} database(s)")
        logger.info(f"✓ Saved to: {output_file}")
        logger.info(f"\nDatabases: {databases_str}")
        
    except Exception as e:
        logger.error(f"✗ Error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
