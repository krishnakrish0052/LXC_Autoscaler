from flask import Flask
from config import Config

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    
    # Initialize extensions
    from app.models.containers import Base
    from app.utils.helpers import get_db_engine
    engine = get_db_engine()
    Base.metadata.create_all(engine)
    
    # Register blueprints
    from app.api.routes import bp as api_bp
    app.register_blueprint(api_bp, url_prefix='/api')
    
    # Also register the legacy routes blueprint (but disable the scaling-rules POST endpoint)
    from app.api.lastroutes import bp as legacy_api_bp
    app.register_blueprint(legacy_api_bp, url_prefix='/api/legacy')
    
    return app