#!/usr/bin/env python3
"""
Database Setup Utility for LXC_Autoscaler

This script helps initialize or repair the database for the LXC_Autoscaler application.
It will:
1. Check database connectivity
2. Create missing tables
3. Optionally populate initial data
"""

import os
import sys
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
import logging
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("db_setup")

# Load environment variables
load_dotenv()

def get_connection_string():
    """Get database connection string from environment or config"""
    # Check environment first
    db_url = os.getenv('DATABASE_URL')
    
    # If not in environment, check config.py
    if not db_url:
        try:
            sys.path.append(os.path.dirname(os.path.abspath(__file__)))
            from config import Config
            db_url = Config.SQLALCHEMY_DATABASE_URI
        except (ImportError, AttributeError):
            db_url = None
    
    # If still not found, use default connection
    if not db_url:
        db_url = 'postgresql://postgres:postgres@localhost/lxc_autoscaler'
        
    return db_url

def test_connection(connection_string):
    """Test database connection"""
    try:
        engine = create_engine(connection_string)
        # Try to connect
        with engine.connect() as conn:
            logger.info("✅ Successfully connected to database")
        return True, engine
    except Exception as e:
        logger.error(f"❌ Database connection failed: {str(e)}")
        return False, None

def check_tables(engine):
    """Check which tables exist in the database"""
    try:
        inspector = inspect(engine)
        existing_tables = inspector.get_table_names()
        
        # List of required tables
        required_tables = [
            'instances', 
            'scaling_rules', 
            'scaling_history',
            'containers',
            'load_balancers',
            'load_balancer_targets'
        ]
        
        missing_tables = [table for table in required_tables if table not in existing_tables]
        
        if missing_tables:
            logger.warning(f"Missing tables: {', '.join(missing_tables)}")
        else:
            logger.info("✅ All required tables exist")
            
        return missing_tables
    except Exception as e:
        logger.error(f"❌ Error checking tables: {str(e)}")
        return required_tables  # Assume all are missing if we can't check

def create_tables(engine):
    """Create all necessary database tables"""
    try:
        # Import models
        from app.models.base import Base
        from app.models.containers import Container
        from app.models.instances import Instance, ScalingHistory
        from app.models.scaling import ScalingRule
        from app.models.loadbalancer import LoadBalancer, LoadBalancerTarget
        
        # Create tables
        Base.metadata.create_all(engine)
        logger.info("✅ Database tables created successfully")
        return True
    except Exception as e:
        logger.error(f"❌ Error creating tables: {str(e)}")
        return False

def create_database(connection_string):
    """Create the database if it doesn't exist"""
    try:
        # Extract database name from connection string
        db_name = connection_string.split('/')[-1]
        
        # Create connection string to default database
        admin_conn_string = connection_string.rsplit('/', 1)[0] + '/postgres'
        
        logger.info(f"Attempting to create database {db_name}")
        
        # Connect to default database
        engine = create_engine(admin_conn_string)
        with engine.connect() as conn:
            # Disconnect all users
            conn.execute(f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{db_name}'")
            
            # Check if database exists
            result = conn.execute(f"SELECT 1 FROM pg_database WHERE datname = '{db_name}'")
            if result.scalar():
                logger.info(f"Database {db_name} already exists")
                # If exists, drop it to recreate fresh
                conn.execute("COMMIT")  # need to commit before DROP DATABASE
                conn.execute(f"DROP DATABASE {db_name}")
                logger.info(f"Dropped existing database {db_name}")
            
            # Create database
            conn.execute("COMMIT")
            conn.execute(f"CREATE DATABASE {db_name}")
            logger.info(f"✅ Created database {db_name}")
            
        return True
    except Exception as e:
        logger.error(f"❌ Error creating database: {str(e)}")
        return False

def main():
    print("""
┌───────────────────────────────────────────────────────┐
│ DATABASE SETUP UTILITY                                │
│                                                       │
│ This utility will help you set up the database for    │
│ the LXC_Autoscaler application.                       │
│                                                       │
│ • Check database connectivity                         │
│ • Create missing tables                               │
│ • Repair database issues                              │
└───────────────────────────────────────────────────────┘
    """)
    
    # Get database connection string
    connection_string = get_connection_string()
    logger.info(f"Using connection string: {connection_string}")
    
    # Test connection
    connected, engine = test_connection(connection_string)
    
    if not connected:
        create_db = input("Would you like to try creating the database? (y/n): ")
        if create_db.lower() == 'y':
            if create_database(connection_string):
                # Retry connection
                connected, engine = test_connection(connection_string)
                if not connected:
                    logger.error("❌ Still unable to connect after creating database")
                    sys.exit(1)
            else:
                logger.error("❌ Failed to create database")
                sys.exit(1)
        else:
            logger.error("❌ Cannot proceed without database connection")
            sys.exit(1)
    
    # Check tables
    missing_tables = check_tables(engine)
    
    if missing_tables:
        create = input("Would you like to create the missing tables? (y/n): ")
        if create.lower() == 'y':
            if create_tables(engine):
                logger.info("✅ Database setup complete")
            else:
                logger.error("❌ Failed to create tables")
                sys.exit(1)
        else:
            logger.warning("⚠️ Database tables will not be created")
    else:
        logger.info("✅ Database is fully set up and ready to use")

if __name__ == "__main__":
    main()