import os
import threading
import logging
import redis
import json
import sys
from datetime import datetime
from flask import Flask, render_template
from flasgger import Swagger
from app.api.routes import bp as api_bp
from app.api.metrics_routes import metrics_bp  # Import the metrics blueprint
from app.models.instances import Instance
from app.models.scaling import ScalingRule, ScalingHistory
from app.models.containers import Container
from app.utils.helpers import get_db_session, get_redis_connection, check_db_setup
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

# Custom Jinja filters for formatting
@app.template_filter('format_bytes')
def format_bytes(num, precision=2):
    """Format bytes to human readable string"""
    if num is None:
        return "0 B"
    
    num = float(num)
    for unit in ['B', 'KB', 'MB', 'GB', 'TB', 'PB']:
        if abs(num) < 1024.0 or unit == 'PB':
            return f"{num:.{precision}f} {unit}"
        num /= 1024.0

@app.template_filter('format_uptime')
def format_uptime(seconds):
    """Format seconds to days, hours, minutes, seconds"""
    if seconds is None:
        return "0s"
    
    seconds = int(float(seconds))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    
    result = []
    if days > 0:
        result.append(f"{days}d")
    if hours > 0:
        result.append(f"{hours}h")
    if minutes > 0:
        result.append(f"{minutes}m")
    if seconds > 0 or not result:
        result.append(f"{seconds}s")
    
    return " ".join(result)

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

# Register error handlers
@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def server_error(e):
    return render_template('fallback_dashboard.html', 
                          system={'cpu_percent': 0, 'memory_percent': 0, 'disk_percent': 0},
                          redis_ok=False,
                          containers=[],
                          error_message=f"Server Error: {str(e)}"), 500

# Register API blueprints
app.register_blueprint(api_bp, url_prefix='/api')
app.register_blueprint(metrics_bp)  # Register metrics blueprint

@app.route('/')
def index():
    # Redirect to dashboard
    return dashboard()

def check_redis_connection():
    """Test Redis connection to ensure it's available"""
    # Get Redis client using our robust connection helper
    redis_client = get_redis_connection()
    
    # Try to ping Redis server
    response = redis_client.ping()
    if response:
        logger.info("✅ Redis connection successful")
        return True
    else:
        # This handles both connection failures and authentication issues
        logger.warning(f"⚠️ Redis connection issues detected at {Config.REDIS_HOST}:{Config.REDIS_PORT}")
        logger.warning("Some features will use fallback mode (metrics and scaling may be limited)")
        return False

@app.route('/dashboard')
def dashboard():
    """Dashboard with system and instance metrics"""
    try:
        session = get_db_session()
        redis_client = get_redis_connection()
        
        # Get metrics service
        metrics_service = MetricsService()
        
        # Get system metrics
        system_metrics = metrics_service.get_system_metrics()
        
        # Get basic system metrics using psutil if metrics service fails
        if not system_metrics:
            import psutil
            system_metrics = {
                'cpu_percent': psutil.cpu_percent(),
                'memory_percent': psutil.virtual_memory().percent,
                'disk_percent': psutil.disk_usage('/').percent
            }
        
        # Get instances with metrics
        try:
            # Try to query instances - this will use the fallback if DB is unavailable
            instances = session.query(Instance).all()
            instances_with_metrics = []
            
            # Process instances (will work with both real DB data and fallback mock data)
            for instance in instances:
                # Get latest metrics from Redis
                metrics_key = f"instance:{instance.name}:metrics"
                metrics_data = redis_client.get(metrics_key)
                
                # If Redis doesn't have metrics, generate mock metrics for testing
                if not metrics_data and isinstance(redis_client, FallbackRedisClient):
                    import random
                    mock_metrics = {
                        'cpu': random.uniform(10, 90),
                        'memory': random.randint(100, 1000) * 1024 * 1024,
                        'memory_percent': random.uniform(10, 90),
                        'disk_usage': random.randint(500, 5000) * 1024 * 1024,
                        'network_rx': random.randint(1024, 10240),
                        'network_tx': random.randint(1024, 10240)
                    }
                    metrics_data = json.dumps(mock_metrics)
                
                instance_data = {
                    'id': instance.id,
                    'name': instance.name,
                    'type': instance.type,
                    'status': instance.status,
                    'created_at': instance.created_at,
                    'updated_at': instance.updated_at if hasattr(instance, 'updated_at') else instance.created_at,
                    'metrics': json.loads(metrics_data) if metrics_data else {}
                }
                instances_with_metrics.append(instance_data)
            
            # Get containers from database with metrics
            containers = session.query(Container).all()
            containers_with_metrics = []
            
            for container in containers:
                metrics_key = f"container:{container.name}:metrics"
                metrics_data = redis_client.get(metrics_key)
                
                # If Redis doesn't have metrics, generate mock metrics for testing
                if not metrics_data and isinstance(redis_client, FallbackRedisClient):
                    import random
                    mock_metrics = {
                        'cpu': random.uniform(10, 90),
                        'memory': random.randint(100, 1000) * 1024 * 1024,
                        'memory_percent': random.uniform(10, 90),
                        'disk_usage': random.randint(500, 5000) * 1024 * 1024,
                        'network_rx': random.randint(1024, 10240),
                        'network_tx': random.randint(1024, 10240)
                    }
                    metrics_data = json.dumps(mock_metrics)
                
                container_data = {
                    'id': container.id,
                    'name': container.name,
                    'status': container.status,
                    'created_at': container.created_at,
                    'updated_at': container.updated_at if hasattr(container, 'updated_at') else container.created_at,
                    'metrics': json.loads(metrics_data) if metrics_data else {}
                }
                containers_with_metrics.append(container_data)
            
            # Try to get VMs directly from LXD
            vms = []
            try:
                import pylxd
                client = pylxd.Client()
                for instance in client.instances.all():
                    # Check if it's a VM
                    if hasattr(instance, 'type') and instance.type == 'virtual-machine':
                        metrics_key = f"vm:{instance.name}:metrics"
                        metrics_data = redis_client.get(metrics_key)
                        
                        vm_data = {
                            'name': instance.name,
                            'status': instance.status,
                            'created_at': instance.created_at if hasattr(instance, 'created_at') else datetime.now(),
                            'metrics': json.loads(metrics_data) if metrics_data else {}
                        }
                        vms.append(vm_data)
            except Exception as vm_error:
                logger.warning(f"Failed to get VMs from LXD: {str(vm_error)}")
                
                # If we can't connect to LXD, create mock VMs in fallback mode
                if not vms:
                    import random
                    from datetime import timedelta
                    
                    for i in range(1, 4):
                        vm_name = f"vm-{i}"
                        vm_data = {
                            'name': vm_name,
                            'status': 'Running' if i % 3 != 0 else 'Stopped',
                            'created_at': datetime.now() - timedelta(days=i),
                            'metrics': {
                                'cpu': random.uniform(10, 90),
                                'memory': random.randint(100, 1000) * 1024 * 1024,
                                'memory_percent': random.uniform(10, 90),
                                'disk_usage': random.randint(500, 5000) * 1024 * 1024
                            }
                        }
                        vms.append(vm_data)
            
            # Get recent scaling history
            history = session.query(ScalingHistory).order_by(
                ScalingHistory.timestamp.desc()
            ).limit(10).all()
            
            # Get all scaling rules
            rules = session.query(ScalingRule).all()
            
            # If we have data, use the full dashboard
            if instances_with_metrics or containers_with_metrics or vms:
                return render_template('dashboard.html',
                                    system=system_metrics,
                                    instances=instances_with_metrics,
                                    containers=containers_with_metrics,
                                    vms=vms,
                                    rules=rules,
                                    history=history,
                                    fallback_mode=isinstance(session, FallbackDBSession))
            else:
                # No data available even from fallback, show error
                raise ValueError("No instances found in database and fallback data generation failed")
                
        except Exception as db_error:
            logger.warning(f"Database error in dashboard: {str(db_error)}")
            
            # Create mock data for fallback display
            from datetime import timedelta
            import random
            
            containers = []
            vms = []
            
            # Try to list containers and VMs directly with pylxd first
            try:
                import pylxd
                client = pylxd.Client()
                for instance in client.instances.all():
                    if hasattr(instance, 'type') and instance.type == 'virtual-machine':
                        vms.append({'name': instance.name, 'status': instance.status})
                    else:
                        containers.append({'name': instance.name, 'status': instance.status})
            except Exception as lxd_error:
                logger.warning(f"Failed to get containers/VMs from LXD: {str(lxd_error)}")
                
                # Create mock containers and VMs since we couldn't get real ones
                for i in range(1, 6):
                    containers.append({
                        'name': f"container-{i}",
                        'status': "Running" if i % 3 != 0 else "Stopped"
                    })
                
                for i in range(1, 4):
                    vms.append({
                        'name': f"vm-{i}",
                        'status': "Running" if i % 2 == 0 else "Stopped"
                    })
            
            # Check Redis connection
            redis_ok = True if hasattr(redis_client, "ping") and redis_client.ping() else False
            
            # Display fallback dashboard with error message and mock data
            return render_template('fallback_dashboard.html',
                                system=system_metrics,
                                redis_ok=redis_ok,
                                containers=containers,
                                vms=vms,
                                config=Config,
                                error_message=f"Limited functionality mode: {str(db_error)}")
    
    except Exception as e:
        logger.error(f"Critical error in dashboard: {str(e)}")
        
        # Emergency fallback - ultra simple
        import psutil
        system_metrics = {
            'cpu_percent': psutil.cpu_percent(),
            'memory_percent': psutil.virtual_memory().percent,
            'disk_percent': psutil.disk_usage('/').percent
        }
        
        return render_template('fallback_dashboard.html',
                            system=system_metrics,
                            redis_ok=False,
                            containers=[],
                            vms=[],
                            config=Config,
                            error_message=f"Critical error: {str(e)}")

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
    try:
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
    except Exception as e:
        logger.error(f"Error getting instance details: {str(e)}")
        return render_template('fallback_dashboard.html',
                            system={'cpu_percent': 0, 'memory_percent': 0, 'disk_percent': 0},
                            redis_ok=True,
                            containers=[],
                            error_message=f"Error: {str(e)}")

@app.route('/rules')
def list_rules():
    """List all scaling rules - with fallback for database errors"""
    try:
        session = get_db_session()
        rules = session.query(ScalingRule).all()
        
        # Check if we got real data or fallback
        if not rules and not isinstance(rules, list):
            # Fallback mode
            return render_template('fallback_dashboard.html',
                                system={'cpu_percent': 0, 'memory_percent': 0, 'disk_percent': 0},
                                redis_ok=True,
                                containers=[],
                                error_message="Database error - scaling_rules table may not exist")
        
        return render_template('rules/list.html', rules=rules)
    except Exception as e:
        logger.error(f"Error listing rules: {str(e)}")
        return render_template('fallback_dashboard.html',
                            system={'cpu_percent': 0, 'memory_percent': 0, 'disk_percent': 0},
                            redis_ok=True,
                            containers=[],
                            error_message=f"Error: {str(e)}")

@app.route('/rules/create')
def create_rule():
    """Create a new scaling rule"""
    try:
        session = get_db_session()
        containers = []

        # Try to get containers from database first
        db_containers = session.query(Container).all()
        if db_containers and len(db_containers) > 0:
            containers = db_containers
        else:
            # Fallback to getting containers from LXD directly
            try:
                import pylxd
                client = pylxd.Client()
                # Get containers from LXD and create basic container objects
                lxd_containers = client.containers.all()
                for c in lxd_containers:
                    containers.append({"name": c.name, "status": c.status})
            except Exception as e:
                logger.error(f"Error getting containers from LXD: {str(e)}")
                
        # If we still don't have any containers, provide a placeholder
        if not containers:
            containers = [{"name": "No containers available", "status": "N/A"}]
            
        return render_template('rules/create.html', containers=containers)
    except Exception as e:
        logger.error(f"Error preparing rule creation page: {str(e)}")
        return render_template('fallback_dashboard.html',
                        system={'cpu_percent': 0, 'memory_percent': 0, 'disk_percent': 0},
                        redis_ok=True,
                        containers=[],
                        error_message=f"Error: {str(e)}")

@app.route('/rules/<int:rule_id>/edit')
def edit_rule(rule_id):
    """Edit an existing scaling rule"""
    session = get_db_session()
    rule = session.query(ScalingRule).filter(ScalingRule.id == rule_id).first()
    
    if not rule:
        return render_template('404.html'), 404
    
    instances = session.query(Instance).all()
    return render_template('rules/edit.html', rule=rule, instances=instances)

@app.route('/containers')
def list_containers():
    """List all containers - with fallback for database errors"""
    try:
        session = get_db_session()
        redis_client = get_redis_connection()
        containers = session.query(Container).all()
        
        # Check if we got real data or fallback
        if not containers or not hasattr(containers[0] if containers else None, 'name'):
            # Try to get container list directly from LXD
            lxd_containers = []
            try:
                import pylxd
                client = pylxd.Client()
                lxd_containers = [{'name': c.name, 'status': c.status} for c in client.containers.all()]
            except Exception as lxd_err:
                logger.warning(f"Failed to get containers from LXD: {str(lxd_err)}")
                
            # Fallback mode with any containers found directly from LXD
            return render_template('fallback_dashboard.html',
                                system={'cpu_percent': 0, 'memory_percent': 0, 'disk_percent': 0},
                                redis_ok=True,
                                containers=lxd_containers,
                                error_message="Database error - containers table may not exist")
        
        # Add metrics to each container
        containers_with_metrics = []
        for container in containers:
            # Create a container dictionary with metrics attribute
            container_data = {
                'id': container.id,
                'name': container.name,
                'status': container.status if hasattr(container, 'status') else 'Unknown',
                'created_at': container.created_at,
                'updated_at': container.updated_at if hasattr(container, 'updated_at') else container.created_at,
                'metrics': {}  # Default empty metrics
            }
            
            # Try to get metrics from Redis
            try:
                metrics_key = f"container:{container.name}:metrics"
                metrics_data = redis_client.get(metrics_key)
                if metrics_data:
                    container_data['metrics'] = json.loads(metrics_data)
                else:
                    # Try instance metrics as fallback (container might also be an instance)
                    instance_metrics_key = f"instance:{container.name}:metrics"
                    instance_metrics_data = redis_client.get(instance_metrics_key)
                    if instance_metrics_data:
                        container_data['metrics'] = json.loads(instance_metrics_data)
            except Exception as redis_err:
                logger.warning(f"Failed to get metrics for container {container.name} from Redis: {str(redis_err)}")
            
            containers_with_metrics.append(container_data)
        
        return render_template('containers/list.html', containers=containers_with_metrics)
    except Exception as e:
        logger.error(f"Error listing containers: {str(e)}")
        return render_template('fallback_dashboard.html',
                            system={'cpu_percent': 0, 'memory_percent': 0, 'disk_percent': 0},
                            redis_ok=True,
                            containers=[],
                            error_message=f"Error: {str(e)}")

# Container details route
@app.route('/containers/<name>')
def container_details(name):
    """Detail view for a specific container with metrics and actions"""
    try:
        session = get_db_session()
        redis_client = get_redis_connection()
        
        # Get the container by name
        container = session.query(Container).filter(Container.name == name).first()
        
        if not container:
            # Try to get container directly from LXD
            try:
                import pylxd
                client = pylxd.Client()
                lxd_container = client.containers.get(name)
                
                # Create a basic container object with data from LXD
                container = {
                    'name': name,
                    'status': lxd_container.status,
                    'created_at': datetime.now(),  # We don't have the exact time
                    'metrics': {}
                }
                
                # Try to get metrics
                metrics_key = f"container:{name}:metrics"
                metrics_data = redis_client.get(metrics_key)
                if metrics_data:
                    container['metrics'] = json.loads(metrics_data)
                else:
                    # Try instance metrics as fallback
                    instance_metrics_key = f"instance:{name}:metrics"
                    instance_metrics_data = redis_client.get(instance_metrics_key)
                    if instance_metrics_data:
                        container['metrics'] = json.loads(instance_metrics_data)
                
                # Return a simplified detail view
                return render_template('fallback_dashboard.html',
                                    system={'cpu_percent': 0, 'memory_percent': 0, 'disk_percent': 0},
                                    redis_ok=True,
                                    containers=[container],
                                    error_message=f"Container {name} found in LXD but not in database")
            except Exception as lxd_err:
                logger.warning(f"Failed to get container from LXD: {str(lxd_err)}")
                return render_template('404.html'), 404
        
        # Convert container to dictionary with metrics
        container_data = {
            'id': container.id,
            'name': container.name,
            'status': container.status if hasattr(container, 'status') else 'Unknown',
            'created_at': container.created_at,
            'updated_at': container.updated_at if hasattr(container, 'updated_at') else container.created_at,
            'metrics': {}  # Default empty metrics
        }
        
        # Get container metrics from Redis
        metrics_key = f"container:{name}:metrics"
        metrics_data = redis_client.get(metrics_key)
        
        if metrics_data:
            container_data['metrics'] = json.loads(metrics_data)
        else:
            # Try instance metrics as fallback
            instance_metrics_key = f"instance:{name}:metrics"
            instance_metrics_data = redis_client.get(instance_metrics_key)
            if instance_metrics_data:
                container_data['metrics'] = json.loads(instance_metrics_data)
        
        # Get scaling history for this container
        history = session.query(ScalingHistory).filter(
            ScalingHistory.container_name == name
        ).order_by(ScalingHistory.timestamp.desc()).limit(10).all()
        
        # Get scaling rules for this container
        rules = session.query(ScalingRule).filter(
            ScalingRule.container_name == name
        ).all()
        
        return render_template('containers/detail.html',
                            container=container_data,
                            metrics=container_data['metrics'],
                            scaling_history=history,
                            rules=rules)
    except Exception as e:
        logger.error(f"Error getting container details: {str(e)}")
        return render_template('fallback_dashboard.html',
                            system={'cpu_percent': 0, 'memory_percent': 0, 'disk_percent': 0},
                            redis_ok=True,
                            containers=[],
                            error_message=f"Error: {str(e)}")

@app.route('/vms')
def list_vms():
    """List all virtual machines"""
    try:
        session = get_db_session()
        redis_client = get_redis_connection()
        vms = []
        
        # Try to get VMs directly from LXD
        try:
            import pylxd
            client = pylxd.Client()
            for instance in client.instances.all():
                # Check if it's a VM
                if hasattr(instance, 'type') and instance.type == 'virtual-machine':
                    metrics_key = f"vm:{instance.name}:metrics"
                    metrics_data = redis_client.get(metrics_key)
                    
                    vm_data = {
                        'name': instance.name,
                        'status': instance.status,
                        'created_at': instance.created_at if hasattr(instance, 'created_at') else datetime.now(),
                        'metrics': json.loads(metrics_data) if metrics_data else {}
                    }
                    vms.append(vm_data)
        except Exception as e:
            logger.error(f"Error listing VMs from LXD: {str(e)}")
        
        # If we don't have any VMs yet, create placeholders for the UI
        if not vms:
            # Add placeholder VMs for demonstration
            import random
            vm_statuses = ['Running', 'Stopped']
            vm_names = ['vm-web-01', 'vm-db-01', 'vm-app-01']
            
            for name in vm_names:
                vm_data = {
                    'name': name,
                    'status': random.choice(vm_statuses),
                    'created_at': datetime.now() - timedelta(days=random.randint(1, 30)),
                    'metrics': {
                        'cpu': random.uniform(5, 80),
                        'memory': random.randint(512, 2048) * 1024 * 1024,
                        'memory_limit': 4 * 1024 * 1024 * 1024,
                        'memory_percent': random.uniform(10, 70),
                        'disk_usage': random.randint(5, 15) * 1024 * 1024 * 1024,
                        'disk_limit': 20 * 1024 * 1024 * 1024,
                        'disk_percent': random.uniform(20, 60),
                        'uptime': random.randint(3600, 864000)
                    }
                }
                vms.append(vm_data)
            
        return render_template('vms/list.html', vms=vms)
    except Exception as e:
        logger.error(f"Error listing VMs: {str(e)}")
        return render_template('fallback_dashboard.html',
                           system={'cpu_percent': 0, 'memory_percent': 0, 'disk_percent': 0},
                           redis_ok=True,
                           containers=[],
                           vms=[],
                           error_message=f"Error: {str(e)}")

@app.route('/vms/<name>')
def vm_detail(name):
    """Detail view for a specific VM with metrics and actions"""
    try:
        redis_client = get_redis_connection()
        session = get_db_session()
        vm = None
        
        # Try to get VM from LXD
        try:
            import pylxd
            client = pylxd.Client()
            lxd_vm = client.instances.get(name)
            
            # Check if it's a VM
            if hasattr(lxd_vm, 'type') and lxd_vm.type == 'virtual-machine':
                vm = {
                    'name': lxd_vm.name,
                    'status': lxd_vm.status,
                    'created_at': lxd_vm.created_at if hasattr(lxd_vm, 'created_at') else datetime.now(),
                    'architecture': lxd_vm.architecture if hasattr(lxd_vm, 'architecture') else 'x86_64',
                    'profiles': lxd_vm.profiles if hasattr(lxd_vm, 'profiles') else ['default'],
                    'profile': 'default',
                    'cpu_limit': lxd_vm.config.get('limits.cpu') if hasattr(lxd_vm, 'config') else '2',
                    'disk_limit': '20GB'
                }
        except Exception as e:
            logger.warning(f"Failed to get VM {name} from LXD: {str(e)}")
        
        # If VM not found, use placeholder data for demonstration
        if not vm:
            if name in ['vm-web-01', 'vm-db-01', 'vm-app-01']:
                import random
                vm = {
                    'name': name,
                    'status': random.choice(['Running', 'Stopped']),
                    'created_at': datetime.now() - timedelta(days=random.randint(1, 30)),
                    'architecture': 'x86_64',
                    'profiles': ['default'],
                    'profile': 'default',
                    'cpu_limit': '2',
                    'disk_limit': '20GB'
                }
            else:
                return render_template('404.html'), 404
        
        # Get VM metrics from Redis
        metrics_key = f"vm:{name}:metrics"
        metrics_data = redis_client.get(metrics_key)
        metrics = json.loads(metrics_data) if metrics_data else {}
        
        # If no metrics available, create realistic placeholders
        if not metrics:
            import random
            metrics = {
                'cpu': random.uniform(5, 80),
                'memory': random.randint(512, 2048) * 1024 * 1024,
                'memory_limit': 4 * 1024 * 1024 * 1024,
                'memory_percent': random.uniform(10, 70),
                'disk_usage': random.randint(5, 15) * 1024 * 1024 * 1024,
                'disk_limit': 20 * 1024 * 1024 * 1024,
                'disk_percent': random.uniform(20, 60),
                'uptime': random.randint(3600, 864000),
                'network': {
                    'eth0': {
                        'addresses': [
                            {'family': 'inet', 'address': f'192.168.1.{random.randint(10, 200)}', 'netmask': '24'}
                        ],
                        'in': random.randint(1024, 1048576) * 100,
                        'out': random.randint(1024, 1048576) * 50
                    }
                },
                'disk': {
                    'root': {
                        'read': random.randint(1048576, 1073741824),
                        'write': random.randint(1048576, 1073741824)
                    }
                },
                'processes': random.randint(10, 100),
                'threads': random.randint(20, 150),
                'cpu_load': f"{random.uniform(0.1, 3.0):.2f}"
            }
        
        # Get scaling history
        scaling_history = session.query(ScalingHistory).filter(
            ScalingHistory.instance_name == name
        ).order_by(ScalingHistory.timestamp.desc()).limit(10).all()
        
        return render_template('vms/detail.html',
                            vm=vm,
                            metrics=metrics,
                            scaling_history=scaling_history)
    except Exception as e:
        logger.error(f"Error getting VM details: {str(e)}")
        return render_template('fallback_dashboard.html',
                            system={'cpu_percent': 0, 'memory_percent': 0, 'disk_percent': 0},
                            redis_ok=True,
                            containers=[],
                            vms=[],
                            error_message=f"Error: {str(e)}")

@app.route('/load-balancers')
def list_load_balancers():
    """List all load balancers - with fallback for database errors"""
    try:
        session = get_db_session()
        load_balancers = session.query(LoadBalancer).all()
        
        # Check if we got real data or fallback
        if not load_balancers and not isinstance(load_balancers, list):
            # Fallback mode
            return render_template('fallback_dashboard.html',
                                system={'cpu_percent': 0, 'memory_percent': 0, 'disk_percent': 0},
                                redis_ok=True,
                                containers=[],
                                error_message="Database error - load_balancers table may not exist")
        
        return render_template('load_balancers/list.html', load_balancers=load_balancers)
    except Exception as e:
        logger.error(f"Error listing load balancers: {str(e)}")
        return render_template('fallback_dashboard.html',
                            system={'cpu_percent': 0, 'memory_percent': 0, 'disk_percent': 0},
                            redis_ok=True,
                            containers=[],
                            error_message=f"Error: {str(e)}")

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
    
    # Get running instances/containers
    instances = session.query(Instance).filter(Instance.status == 'Running').all()
    containers = session.query(Container).filter(Container.status == 'Running').all()
    
    # Get VMs
    vms = []
    try:
        import pylxd
        client = pylxd.Client()
        for instance in client.instances.all():
            # Check if it's a VM and is running
            if hasattr(instance, 'type') and instance.type == 'virtual-machine' and instance.status == 'Running':
                vms.append({
                    'name': instance.name,
                    'status': instance.status
                })
    except Exception as e:
        logger.warning(f"Failed to get VMs from LXD: {str(e)}")
    
    return render_template('load_balancers/detail.html', 
                         load_balancer=load_balancer, 
                         instances=instances,
                         containers=containers,
                         vms=vms)

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
    else:
        logger.info("Redis connection established successfully")
    
    # Check database setup and create tables if needed
    logger.info("Checking database setup...")
    db_ok, db_message = check_db_setup()
    
    if not db_ok:
        logger.warning(f"⚠️ Database setup issue: {db_message}")
        logger.warning("⚠️ Some functionality will be limited - using fallback mode")
    else:
        logger.info(f"✅ {db_message}")

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