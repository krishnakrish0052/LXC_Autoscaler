#!/usr/bin/env python3
"""
Database initialization script for LXC Autoscaler
- Creates all required tables if they don't exist
- Populates with sample data if the tables are empty
"""

import sys
import logging
from datetime import datetime, timedelta
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from app.models.base import Base
from app.models.instances import Instance, ScalingHistory
from app.models.containers import Container
from app.models.scaling import ScalingRule
from app.models.loadbalancer import LoadBalancer, LoadBalancerTarget
from app.utils.helpers import get_db_engine, get_db_session
from config import Config

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_db():
    """Initialize the database schema"""
    try:
        logger.info("Creating database tables...")
        
        # Get engine
        engine = get_db_engine()
        Base.metadata.create_all(engine)
        
        logger.info("Database tables created successfully")
        return True
    except Exception as e:
        logger.error(f"Error creating database tables: {str(e)}")
        return False

def check_table_exists(engine, table_name):
    """Check if a table exists in the database"""
    inspector = inspect(engine)
    return table_name in inspector.get_table_names()

def populate_sample_data():
    """Populate the database with sample data for testing"""
    try:
        logger.info("Populating database with sample data...")
        
        # Get engine and session
        engine = get_db_engine()
        Session = sessionmaker(bind=engine)
        session = Session()
        
        # Check if tables exist
        required_tables = ['instances', 'containers', 'scaling_rules', 'load_balancers']
        for table in required_tables:
            if not check_table_exists(engine, table):
                logger.error(f"Table {table} does not exist")
                return False
        
        # Only add sample data if tables are empty
        if session.query(Instance).count() == 0:
            # Create sample instances
            instances = [
                Instance(
                    name=f"instance-{i}",
                    type="container" if i % 2 == 0 else "virtual-machine",
                    status="Running" if i % 3 != 0 else "Stopped",
                    image="ubuntu:20.04",
                    profile="default",
                    created_at=datetime.utcnow() - timedelta(days=i),
                    cpu_limit="2",
                    memory_limit="2GB",
                    disk_limit="10GB"
                )
                for i in range(1, 6)
            ]
            session.add_all(instances)
            logger.info("Added sample instances")
        
        if session.query(Container).count() == 0:
            # Create sample containers
            containers = [
                Container(
                    name=f"container-{i}",
                    status="Running" if i % 3 != 0 else "Stopped",
                    image="ubuntu:20.04",
                    created_at=datetime.utcnow() - timedelta(days=i)
                )
                for i in range(1, 6)
            ]
            session.add_all(containers)
            logger.info("Added sample containers")
        
        if session.query(ScalingRule).count() == 0:
            # Create sample scaling rules
            rules = [
                ScalingRule(
                    container_name=f"container-{i}",
                    metric="cpu" if i % 2 == 0 else "memory",
                    threshold=80.0,
                    action_type="horizontal" if i % 2 == 0 else "vertical",
                    increment=1,
                    cooldown=300
                )
                for i in range(1, 4)
            ]
            session.add_all(rules)
            logger.info("Added sample scaling rules")
        
        if session.query(LoadBalancer).count() == 0:
            # Create sample load balancers
            load_balancers = [
                LoadBalancer(
                    name=f"lb-{i}",
                    port=80 + i,
                    algorithm="round_robin" if i % 2 == 0 else "least_conn",
                    status="active" if i % 2 == 0 else "inactive",
                    description=f"Load balancer {i} for testing"
                )
                for i in range(1, 3)
            ]
            session.add_all(load_balancers)
            session.commit()  # Commit to get IDs for the targets
            logger.info("Added sample load balancers")
            
            # Add sample targets to the load balancers
            targets = []
            for lb in load_balancers:
                for i in range(1, 4):
                    targets.append(
                        LoadBalancerTarget(
                            load_balancer_id=lb.id,
                            container_name=f"container-{i}",
                            ip_address=f"192.168.1.{10 + i}",
                            port=8080,
                            weight=1,
                            active=True,
                            health_status="healthy"
                        )
                    )
            session.add_all(targets)
            logger.info("Added sample load balancer targets")
        
        # Commit all changes
        session.commit()
        logger.info("Sample data added successfully")
        return True
        
    except Exception as e:
        logger.error(f"Error populating sample data: {str(e)}")
        if 'session' in locals():
            session.rollback()
        return False
    finally:
        if 'session' in locals():
            session.close()

if __name__ == "__main__":
    logger.info("Starting database initialization...")
    
    # Initialize database schema
    if not init_db():
        logger.error("Failed to initialize database schema. Exiting.")
        sys.exit(1)
    
    # Populate with sample data
    if not populate_sample_data():
        logger.warning("Failed to populate sample data. Continuing with empty database.")
    
    logger.info("Database initialization completed.")