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
# In helpers.py or where you define Redis connections:
def get_redis_connection():
    if Config.REDIS_PASSWORD:
        return redis.StrictRedis(
            host=Config.REDIS_HOST,
            port=Config.REDIS_PORT,
            password=Config.REDIS_PASSWORD,
            db=0,
            decode_responses=True
        )
    else:
        # Connect without password
        return redis.StrictRedis(
            host=Config.REDIS_HOST,
            port=Config.REDIS_PORT,
            db=0,
            decode_responses=True
        )
