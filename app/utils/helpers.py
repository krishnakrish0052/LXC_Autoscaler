from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from config import Config
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_db_engine():
    return create_engine(Config.SQLALCHEMY_DATABASE_URI)

def get_db_session():
    engine = get_db_engine()
    Session = sessionmaker(bind=engine)
    return Session()

def init_db():
    """Initialize the database with required tables"""
    from app.models.containers import Base
    engine = get_db_engine()
    Base.metadata.create_all(engine)
    logger.info("Database tables created")
# Redis connection helper
def get_redis_connection(host=None, port=None):
    """
    Get a Redis connection with proper authentication handling.
    Empty or None password will skip authentication.
    """
    import redis
    
    redis_host = host or Config.REDIS_HOST
    redis_port = port or Config.REDIS_PORT
    
    # Only provide password parameter if it's not empty
    if Config.REDIS_PASSWORD:
        return redis.StrictRedis(
            host=redis_host,
            port=redis_port,
            password=Config.REDIS_PASSWORD,
            db=0,
            decode_responses=True
        )
    else:
        # Connect without password
        return redis.StrictRedis(
            host=redis_host,
            port=redis_port,
            db=0,
            decode_responses=True
        )
