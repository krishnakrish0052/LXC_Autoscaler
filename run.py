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
from app.models.loadbalancer import LoadBalancer, LoadBalancerTarget

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
    redis_client = redis.StrictRedis(
        host=Config.REDIS_HOST,
        port=Config.REDIS_PORT,
        db=0,
        decode_responses=True
    )
    
    # Get containers with metrics
    containers = session.query(Container).all()
    containers_with_metrics = []
    
    for container in containers:
        # Get latest metrics from Redis
        metrics_key = f"container:{container.name}:metrics"
        metrics_data = redis_client.get(metrics_key)
        
        container_data = {
            'id': container.id,
            'name': container.name,
            'status': container.status,
            'created_at': container.created_at,
            'updated_at': container.updated_at,
            'metrics': json.loads(metrics_data) if metrics_data else {}
        }
        containers_with_metrics.append(container_data)
    
    # Get recent scaling history
    history = session.query(ScalingHistory).order_by(
        ScalingHistory.timestamp.desc()
    ).limit(10).all()
    
    # Get all scaling rules
    rules = session.query(ScalingRule).all()
    
    return render_template('dashboard.html',
                         containers=containers_with_metrics,
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

@app.route('/rules/<int:rule_id>/edit')
def edit_rule(rule_id):
    session = get_db_session()
    rule = session.query(ScalingRule).filter(ScalingRule.id == rule_id).first()
    
    if not rule:
        flash('Scaling rule not found', 'danger')
        return redirect(url_for('list_rules'))
    
    containers = session.query(Container).all()
    return render_template('rules/edit.html', rule=rule, containers=containers)


@app.route('/load-balancers')
def list_load_balancers():
    session = get_db_session()
    load_balancers = session.query(LoadBalancer).all()
    return render_template('load_balancers/list.html', load_balancers=load_balancers)

@app.route('/load-balancers/create')
def create_load_balancer():
    return render_template('load_balancers/create.html')

@app.route('/load-balancers/<int:lb_id>')
def load_balancer_detail(lb_id):
    session = get_db_session()
    load_balancer = session.query(LoadBalancer).filter(LoadBalancer.id == lb_id).first()
    
    if not load_balancer:
        flash('Load balancer not found', 'danger')
        return redirect(url_for('list_load_balancers'))
    
    containers = session.query(Container).filter(Container.status == 'Running').all()
    return render_template('load_balancers/detail.html', 
                         load_balancer=load_balancer, 
                         containers=containers)

@app.route('/load-balancers/<int:lb_id>/edit')
def load_balancer_edit(lb_id):
    session = get_db_session()
    load_balancer = session.query(LoadBalancer).filter(LoadBalancer.id == lb_id).first()
    
    if not load_balancer:
        flash('Load balancer not found', 'danger')
        return redirect(url_for('list_load_balancers'))
    
    return render_template('load_balancers/create.html', load_balancer=load_balancer)

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
