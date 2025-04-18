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
    Get a Redis connection with explicit auth handling.
    Try multiple auth methods to handle various Redis configurations.
    """
    import redis
    
    redis_host = host or Config.REDIS_HOST
    redis_port = port or Config.REDIS_PORT
    
    # Try to connect with various credential patterns
    # This tries to handle different Redis configurations without requiring code changes
    for auth_method in range(1, 4):
        try:
            if auth_method == 1:
                # First try: No auth
                client = redis.StrictRedis(
                    host=redis_host,
                    port=redis_port,
                    db=0,
                    decode_responses=True
                )
            elif auth_method == 2:
                # Second try: Empty string password
                client = redis.StrictRedis(
                    host=redis_host,
                    port=redis_port,
                    password="",
                    db=0,
                    decode_responses=True
                )
            elif auth_method == 3:
                # Third try: Default password (if your Redis uses this common default)
                client = redis.StrictRedis(
                    host=redis_host,
                    port=redis_port,
                    password="default",
                    db=0,
                    decode_responses=True
                )
            
            # Test connection with ping
            client.ping()
            # If we reach here, connection was successful
            return client
                
        except redis.exceptions.AuthenticationError:
            # Try next auth method
            continue
        except Exception as e:
            # For other errors like connection refused, immediately return and don't try other methods
            import logging
            logging.getLogger(__name__).error(f"Redis connection error: {str(e)}")
            # Return a no-op Redis client that ignores operations without raising exceptions
            return FallbackRedisClient()
    
    # If we get here, all auth methods failed; return a fallback client
    import logging
    logging.getLogger(__name__).error("All Redis authentication methods failed")
    return FallbackRedisClient()

# Fallback Redis client that ignores operations when Redis is unavailable
class FallbackRedisClient:
    """
    A fallback Redis client that silently handles failures.
    Used when Redis is unavailable to prevent application crashes.
    """
    def __getattr__(self, name):
        # Return a no-op function for any method call
        return self._noop
    
    def _noop(self, *args, **kwargs):
        # This function does nothing and returns None
        return None
    
    def pubsub(self):
        # Return an object with a subscribe method
        return FallbackPubSub()
    
    def ping(self):
        # Ping always returns False for fallback client
        return False

class FallbackPubSub:
    """Fallback for Redis pubsub when Redis is unavailable"""
    def subscribe(self, *args, **kwargs):
        pass
    
    def listen(self):
        # Return an empty generator that never yields anything
        return iter(())
