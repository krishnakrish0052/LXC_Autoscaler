import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Database
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', 'postgresql://mizzle:password@localhost/mizzle')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Redis
    REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
    REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
    
    # LXD
    LXD_SOCKET = os.getenv('LXD_SOCKET', '/var/snap/lxd/common/lxd/unix.socket')
    
    # Security
    SECRET_KEY = os.getenv('SECRET_KEY', 'your-secret-key-here')
    
    # Monitoring
    MONITORING_INTERVAL = int(os.getenv('MONITORING_INTERVAL', 15))  # seconds
