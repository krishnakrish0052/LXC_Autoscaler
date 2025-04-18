import os
import threading
import logging
import redis
import json
import sys
from flask import Flask, render_template
from flasgger import Swagger
from app.api.routes import bp as api_bp
from app.api.metrics_routes import metrics_bp  # Import the metrics blueprint
from app.models.instances import Instance
from app.models.scaling import ScalingRule, ScalingHistory
from app.utils.helpers import get_db_session, get_redis_connection
from config import Config
from app.models.loadbalancer import LoadBalancer, LoadBalancerTarget
from app.services.metrics import MetricsService  # Import the metrics service
from app.core.monitor import LXCMonitor
from app.core.decision import DecisionEngine

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
        "description": "API for managing containers, VMs, and scaling rules",
        "version": "1.0.0"
    },
    "basePath": "/api",
})

# Register API blueprints
app.register_blueprint(api_bp, url_prefix='/api')
app.register_blueprint(metrics_bp)  # Register metrics blueprint

@app.route('/')
def index():
    return render_template('dashboard.html')

def check_redis_connection():
    """Test Redis connection to ensure it's available and properly configured"""
    try:
        # Use our helper to get a properly configured Redis client
        redis_client = get_redis_connection()
        
        # Try to ping Redis server
        response = redis_client.ping()
        if response:
            logger.info("✅ Redis connection successful")
            return True
        else:
            logger.error("❌ Redis ping failed")
            return False
    except redis.exceptions.AuthenticationError:
        logger.error("❌ Redis authentication failed - please check REDIS_PASSWORD in .env")
        logger.error("   To disable authentication, set REDIS_PASSWORD to an empty string")
        return False
    except redis.exceptions.ConnectionError:
        logger.error(f"❌ Redis connection failed - is Redis running at {Config.REDIS_HOST}:{Config.REDIS_PORT}?")
        return False
    except Exception as e:
        logger.error(f"❌ Redis error: {str(e)}")
        return False

@app.route('/dashboard')
def dashboard():
    """Dashboard with system and instance metrics"""
    session = get_db_session()
    redis_client = get_redis_connection()
    
    # Get metrics service
    metrics_service = MetricsService()
    
    # Get system metrics
    system_metrics = metrics_service.get_system_metrics()
    
    # Get instances with metrics
    instances = session.query(Instance).all()
    instances_with_metrics = []
    
    for instance in instances:
        # Get latest metrics from Redis
        metrics_key = f"instance:{instance.name}:metrics"
        metrics_data = redis_client.get(metrics_key)
        
        instance_data = {
            'id': instance.id,
            'name': instance.name,
            'type': instance.type,
            'status': instance.status,
            'created_at': instance.created_at,
            'updated_at': instance.updated_at,
            'metrics': json.loads(metrics_data) if metrics_data else {}
        }
        instances_with_metrics.append(instance_data)
    
    # Get recent scaling history
    history = session.query(ScalingHistory).order_by(
        ScalingHistory.timestamp.desc()
    ).limit(10).all()
    
    # Get all scaling rules
    rules = session.query(ScalingRule).all()
    
    return render_template('dashboard.html',
                         system=system_metrics,
                         instances=instances_with_metrics,
                         rules=rules,
                         history=history)

@app.route('/instances')
def list_instances():
    """List all LXC instances (containers and VMs)"""
    session = get_db_session()
    instances = session.query(Instance).all()
    
    # Get metrics service
    metrics_service = MetricsService()
    
    # Get instance metrics
    instances_with_metrics = []
    for instance in instances:
        metrics = metrics_service.get_instance_metrics(instance.name)
        
        instance_data = {
            'id': instance.id,
            'name': instance.name,
            'type': instance.type,
            'status': instance.status,
            'created_at': instance.created_at,
            'updated_at': instance.updated_at,
            'metrics': metrics
        }
        instances_with_metrics.append(instance_data)
    
    return render_template('instances/list.html', instances=instances_with_metrics)

@app.route("/instances/<name>")
def instance_detail(name):
    """Detailed view of a specific instance with metrics"""
    session = get_db_session()
    instance = session.query(Instance).filter(Instance.name == name).first()
    
    if not instance:
        return render_template('404.html'), 404
    
    # Get metrics service
    metrics_service = MetricsService()
    
    # Get current metrics
    current_metrics = metrics_service.get_instance_metrics(name)
    
    # Get historical metrics for charts
    cpu_history = metrics_service.get_historical_metrics(name, 'cpu', hours=24)
    memory_history = metrics_service.get_historical_metrics(name, 'memory', hours=24)
    network_history = metrics_service.get_historical_metrics(name, 'network', hours=24)
    disk_history = metrics_service.get_historical_metrics(name, 'disk', hours=24)
    
    # Get scaling rules for this instance
    rules = session.query(ScalingRule).filter(
        ScalingRule.container_name == name
    ).all()
    
    # Get scaling history for this instance
    history = session.query(ScalingHistory).filter(
        ScalingHistory.instance_name == name
    ).order_by(ScalingHistory.timestamp.desc()).limit(10).all()
    
    return render_template('instances/detail.html',
                          instance=instance,
                          metrics=current_metrics,
                          cpu_history=cpu_history,
                          memory_history=memory_history,
                          network_history=network_history,
                          disk_history=disk_history,
                          rules=rules,
                          history=history)

@app.route('/rules')
def list_rules():
    """List all scaling rules"""
    session = get_db_session()
    rules = session.query(ScalingRule).all()
    return render_template('rules/list.html', rules=rules)

@app.route('/rules/create')
def create_rule():
    """Create a new scaling rule"""
    session = get_db_session()
    instances = session.query(Instance).all()
    return render_template('rules/create.html', instances=instances)

@app.route('/rules/<int:rule_id>/edit')
def edit_rule(rule_id):
    """Edit an existing scaling rule"""
    session = get_db_session()
    rule = session.query(ScalingRule).filter(ScalingRule.id == rule_id).first()
    
    if not rule:
        return render_template('404.html'), 404
    
    instances = session.query(Instance).all()
    return render_template('rules/edit.html', rule=rule, instances=instances)

@app.route('/load-balancers')
def list_load_balancers():
    """List all load balancers"""
    session = get_db_session()
    load_balancers = session.query(LoadBalancer).all()
    return render_template('load_balancers/list.html', load_balancers=load_balancers)

@app.route('/load-balancers/create')
def create_load_balancer():
    """Create a new load balancer"""
    return render_template('load_balancers/create.html')

@app.route('/load-balancers/<int:lb_id>')
def load_balancer_detail(lb_id):
    """Detailed view of a specific load balancer"""
    session = get_db_session()
    load_balancer = session.query(LoadBalancer).filter(LoadBalancer.id == lb_id).first()
    
    if not load_balancer:
        return render_template('404.html'), 404
    
    instances = session.query(Instance).filter(Instance.status == 'Running').all()
    return render_template('load_balancers/detail.html', 
                         load_balancer=load_balancer, 
                         instances=instances)

def start_monitor():
    """Start the LXC monitor service"""
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
    """Start the decision engine service"""
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

# Main application entry point
if __name__ == '__main__':
    # Verify templates directory exists
    template_dir = os.path.join(os.path.dirname(__file__), 'templates')
    if not os.path.exists(template_dir):
        logger.error(f"Template directory not found: {template_dir}")
        exit(1)

    if not os.path.exists(os.path.join(template_dir, 'dashboard.html')):
        logger.error("dashboard.html not found in templates directory")
        exit(1)
        
    # Check Redis connection before starting services
    logger.info("Checking Redis connection...")
    redis_ok = check_redis_connection()
    
    if not redis_ok:
        logger.warning("⚠️ Redis not available - some functionality will be limited")
        # Optional: Uncomment the line below to exit if Redis is required
        # exit(1)
    else:
        logger.info("Redis connection established successfully")

    try:
        # Start background services
        monitor_thread = threading.Thread(target=start_monitor)
        monitor_thread.daemon = True
        monitor_thread.start()

        decision_thread = threading.Thread(target=start_decision_engine)
        decision_thread.daemon = True
        decision_thread.start()

        logger.info(f"Starting Flask server on port {Config.FLASK_PORT}")
        app.run(host='0.0.0.0', port=Config.FLASK_PORT, debug=Config.FLASK_DEBUG)
    except Exception as e:
        logger.error(f"Application failed: {str(e)}")
        exit(1)