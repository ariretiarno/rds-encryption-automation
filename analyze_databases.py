#!/usr/bin/env python3
"""
Script to execute ANALYZE VERBOSE on each database listed in the .env DATABASES variable.
This helps update PostgreSQL statistics for query optimization.
"""

import os
import sys
import psycopg2
from dotenv import load_dotenv
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# Setup logging with thread safety
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(threadName)s] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Thread-local storage to track processed databases
_thread_local = threading.local()


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


def analyze_database_worker(dbname: str, db_host: str, db_port: str, db_user: str, db_password: str) -> dict:
    """
    Worker function to analyze a single database (designed for parallel execution).
    
    Args:
        dbname: Database name
        db_host: Database host
        db_port: Database port
        db_user: Database user
        db_password: Database password
        
    Returns:
        Dictionary with result information
    """
    result = {
        'dbname': dbname,
        'success': False,
        'duration': 0,
        'error': None
    }
    
    try:
        logger.info(f"Starting ANALYZE for database '{dbname}'...")
        start_time = datetime.now()
        
        # Create connection for this database
        conn = get_connection(db_host, db_port, db_user, db_password, dbname)
        cursor = conn.cursor()
        
        # Execute ANALYZE VERBOSE
        logger.info(f"Running ANALYZE VERBOSE on database '{dbname}'...")
        cursor.execute("ANALYZE VERBOSE")
        
        # Fetch all output messages
        notices = []
        if conn.notices:
            notices = conn.notices.copy()
            conn.notices.clear()
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        result['duration'] = duration
        
        cursor.close()
        conn.close()
        
        logger.info(f"✓ ANALYZE completed for '{dbname}' in {duration:.2f} seconds")
        
        # Log verbose output if available (limit to avoid spam)
        if notices and len(notices) <= 10:
            logger.debug(f"ANALYZE output for '{dbname}':")
            for notice in notices[:10]:
                logger.debug(f"  {notice.strip()}")
        
        result['success'] = True
        
    except Exception as e:
        logger.error(f"✗ Failed to analyze database '{dbname}': {e}")
        result['error'] = str(e)
    
    return result


def main():
    """Main function to analyze databases."""
    # Load environment variables
    load_dotenv()
    
    # Parse command line arguments
    target = 'master'
    workers = 4  # Default number of parallel workers
    
    # Parse arguments
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg.lower() in ['master', 'replication']:
            target = arg.lower()
        elif arg == '--workers' and i + 1 < len(args):
            try:
                workers = int(args[i + 1])
                if workers < 1:
                    logger.error("Workers must be at least 1")
                    sys.exit(1)
                i += 1  # Skip next argument
            except ValueError:
                logger.error(f"Invalid workers value: {args[i + 1]}")
                sys.exit(1)
        else:
            logger.error(f"Invalid argument '{arg}'")
            logger.error("Usage: python3 analyze_databases.py [master|replication] [--workers N]")
            sys.exit(1)
        i += 1
    
    if target not in ['master', 'replication']:
        logger.error(f"Invalid target '{target}'. Use 'master' or 'replication'.")
        logger.error("Usage: python3 analyze_databases.py [master|replication] [--workers N]")
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
    
    databases_str = os.getenv('DATABASES', '')
    
    # Validate configuration
    if not all([db_host, db_user, db_password]):
        logger.error(f"Missing required environment variables for {target.upper()} database.")
        logger.error(f"Required: {target.upper()}_DB_HOST, {target.upper()}_DB_USER, {target.upper()}_DB_PASSWORD")
        sys.exit(1)
    
    if not databases_str:
        logger.error("No databases specified in DATABASES environment variable.")
        sys.exit(1)
    
    # Parse database list
    databases = [db.strip() for db in databases_str.split(',') if db.strip()]
    
    if not databases:
        logger.error("No valid databases found in DATABASES environment variable.")
        sys.exit(1)
    
    logger.info(f"Target: {target.upper()} database")
    logger.info(f"Found {len(databases)} database(s) to analyze: {', '.join(databases)}")
    logger.info(f"Target server: {db_host}:{db_port}")
    logger.info(f"Parallel workers: {workers}")
    
    # Remove duplicates to prevent double execution
    databases = list(dict.fromkeys(databases))
    if len(databases) != len([db.strip() for db in databases_str.split(',') if db.strip()]):
        logger.warning("Duplicate databases detected and removed")
    
    # Process databases in parallel
    success_count = 0
    failure_count = 0
    start_time = datetime.now()
    results = []
    
    logger.info(f"\n{'='*60}")
    logger.info(f"Starting parallel analysis of {len(databases)} database(s)")
    logger.info(f"{'='*60}\n")
    
    # Use ThreadPoolExecutor for parallel execution
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix='AnalyzeWorker') as executor:
        # Submit all tasks
        future_to_db = {
            executor.submit(analyze_database_worker, dbname, db_host, db_port, db_user, db_password): dbname
            for dbname in databases
        }
        
        # Process completed tasks as they finish
        for future in as_completed(future_to_db):
            dbname = future_to_db[future]
            try:
                result = future.result()
                results.append(result)
                
                if result['success']:
                    success_count += 1
                else:
                    failure_count += 1
                    
            except Exception as e:
                logger.error(f"Unexpected error processing database '{dbname}': {e}")
                failure_count += 1
                results.append({
                    'dbname': dbname,
                    'success': False,
                    'duration': 0,
                    'error': str(e)
                })
    
    # Summary
    end_time = datetime.now()
    total_duration = (end_time - start_time).total_seconds()
    
    logger.info(f"\n{'='*60}")
    logger.info(f"SUMMARY")
    logger.info(f"{'='*60}")
    logger.info(f"Target: {target.upper()}")
    logger.info(f"Workers: {workers}")
    logger.info(f"Total databases: {len(databases)}")
    logger.info(f"Successful: {success_count}")
    logger.info(f"Failed: {failure_count}")
    logger.info(f"Total duration: {total_duration:.2f} seconds")
    
    # Show individual results
    if results:
        logger.info(f"\nDetailed Results:")
        for result in sorted(results, key=lambda x: x['dbname']):
            status = "✓" if result['success'] else "✗"
            duration_str = f"{result['duration']:.2f}s" if result['success'] else "N/A"
            error_str = f" - {result['error']}" if result['error'] else ""
            logger.info(f"  {status} {result['dbname']}: {duration_str}{error_str}")
    
    logger.info(f"{'='*60}\n")
    
    if failure_count > 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
