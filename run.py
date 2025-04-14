import os
import threading
import logging
from flask import Flask, render_template
from flasgger import Swagger
from app.api.routes import bp as api_bp
from app.core.monitor import LXCMonitor
from app.core.decision import DecisionEngine
from app.models.containers import Container
from app.models.scaling import ScalingRule, ScalingHistory
from app.utils.helpers import get_db_session
from config import Config

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("scaler")

# Initialize Flask app
app = Flask(__name__)
app.config.from_object(Config)

# Setup Swagger
swagger = Swagger(app, template={
    "swagger": "2.0",
    "info": {
        "title": "LXC AutoScaler API",
        "description": "API for managing containers and scaling rules",
        "version": "1.0.0"
    },
    "basePath": "/api",
})

# Register API blueprint
app.register_blueprint(api_bp, url_prefix='/api')

@app.route('/')
def index():
    return render_template('dashboard.html')

@app.route('/dashboard')
def dashboard():
    session = get_db_session()
    containers = session.query(Container).all()
    rules = session.query(ScalingRule).all()
    history = session.query(ScalingHistory).order_by(ScalingHistory.timestamp.desc()).limit(5).all()
    return render_template('dashboard.html',
                         containers=containers,
                         rules=rules,
                         history=history)

@app.route('/containers')
def list_containers():
    session = get_db_session()
    containers = session.query(Container).all()
    return render_template('containers/list.html', containers=containers)

@app.route('/rules')
def list_rules():
    session = get_db_session()
    rules = session.query(ScalingRule).all()
    return render_template('rules/list.html', rules=rules)

@app.route('/rules/create')
def create_rule():
    session = get_db_session()
    containers = session.query(Container).all()
    return render_template('rules/create.html', containers=containers)

def start_monitor():
    try:
        monitor = LXCMonitor(
            redis_host=Config.REDIS_HOST,
            redis_port=Config.REDIS_PORT
        )
        logger.info(f"Starting monitor on port {Config.MONITORING_PORT}")
        monitor.run(interval=Config.MONITORING_INTERVAL)
    except Exception as e:
        logger.error(f"Monitor failed: {str(e)}")
        raise

def start_decision_engine():
    try:
        engine = DecisionEngine(
            redis_host=Config.REDIS_HOST,
            redis_port=Config.REDIS_PORT
        )
        logger.info("Starting decision engine")
        engine.run()
    except Exception as e:
        logger.error(f"Decision engine failed: {str(e)}")
        raise

if __name__ == '__main__':
    # Verify templates directory and dashboard.html exist
    template_dir = os.path.join(os.path.dirname(__file__), 'templates')
    if not os.path.exists(template_dir):
        logger.error(f"Template directory not found: {template_dir}")
        exit(1)

    if not os.path.exists(os.path.join(template_dir, 'dashboard.html')):
        logger.error("dashboard.html not found in templates directory")
        exit(1)

    try:
        # Start background services
        monitor_thread = threading.Thread(target=start_monitor)
        monitor_thread.daemon = True
        monitor_thread.start()

        decision_thread = threading.Thread(target=start_decision_engine)
        decision_thread.daemon = True
        decision_thread.start()

        logger.info(f"Starting Flask server on port {Config.FLASK_PORT}")
        app.run(host='0.0.0.0', port=Config.FLASK_PORT, debug=True)
    except Exception as e:
        logger.error(f"Application failed: {str(e)}")
        exit(1)
