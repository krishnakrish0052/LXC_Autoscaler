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