import os
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables
load_dotenv()

class Config:
    # Application
    FLASK_PORT = int(os.getenv('FLASK_PORT', 5102))
    FLASK_DEBUG = os.getenv('FLASK_DEBUG', 'true').lower() == 'true'
    
    # Database
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', 'postgresql://mizzle:password@localhost/mizzle')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Redis
    REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', None)  # None disables authentication
    REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
    REDIS_PORT = 6379
    REDIS_METRICS_TTL = int(os.getenv('REDIS_METRICS_TTL', 300))  # TTL in seconds

    
    # LXD
    LXD_SOCKET = os.getenv('LXD_SOCKET', '/var/snap/lxd/common/lxd/unix.socket')
    
    # Monitoring
    MONITORING_PORT = int(os.getenv('MONITORING_PORT', 8103))
    MONITORING_INTERVAL = int(os.getenv('MONITORING_INTERVAL', 15))  # seconds
    
    # Paths
    BASE_DIR = Path(__file__).parent.parent
    TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates')
    STATIC_DIR = os.path.join(BASE_DIR, 'static')
    
    # Security
    SECRET_KEY = os.getenv('SECRET_KEY', '72gbdhbhdbjbjkbkkskb')

    @classmethod
    def validate_paths(cls):
        """Validate that required directories exist"""
        required_dirs = [cls.TEMPLATE_DIR, cls.STATIC_DIR]
        for dir_path in required_dirs:
            if not os.path.exists(dir_path):
                raise FileNotFoundError(f"Required directory not found: {dir_path}")
        
        required_templates = ['dashboard.html', 'base.html']
        for template in required_templates:
            if not os.path.exists(os.path.join(cls.TEMPLATE_DIR, template)):
                raise FileNotFoundError(f"Required template not found: {template}")
