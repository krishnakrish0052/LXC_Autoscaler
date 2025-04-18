from flask import Blueprint, jsonify, request, current_app
from app.models.containers import Container, ScalingHistory
from app.models.scaling import ScalingRule
from app.utils.helpers import get_db_session
from datetime import datetime
import json
import redis
import pylxd
import logging
from config import Config
from app.models.loadbalancer import LoadBalancer, LoadBalancerTarget
import socket

bp = Blueprint('api', __name__)

def get_redis_connection():
    return redis.StrictRedis(
        host=Config.REDIS_HOST,
        port=Config.REDIS_PORT,
        db=0,
        decode_responses=True
    )

@bp.route('/containers')
def list_containers():
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
    
    # Add template filters for formatting
    @app.template_filter('format_bytes')
    def format_bytes(num, precision=1):
        if num is None:
            return "0 B"
        num = int(num)
        if num == 0:
            return "0 B"
        units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
        decimal_places = 0 if num < 1024 else precision
        for unit in units:
            if abs(num) < 1024.0:
                return f"{num:.{decimal_places}f} {unit}"
            num /= 1024.0
        return f"{num:.{precision}f} {units[-1]}"
    
    return render_template('containers/list.html', containers=containers_with_metrics)    
@bp.route('/containers/<name>', methods=['GET'])
def get_container(name):
    """Get detailed information about a specific container"""
    session = get_db_session()
    redis_client = get_redis_connection()
    
    container = session.query(Container).filter(Container.name == name).first()
    if not container:
        return jsonify({'error': 'Container not found'}), 404

    # Get detailed metrics from Redis
    metrics_key = f"container:{name}:metrics"
    metrics = redis_client.get(metrics_key)
    
    return jsonify({
        'id': container.id,
        'name': container.name,
        'status': container.status,
        'created_at': container.created_at.isoformat(),
        'updated_at': container.updated_at.isoformat() if container.updated_at else None,
        'metrics': json.loads(metrics) if metrics else None
    })

@bp.route('/containers/<name>/metrics', methods=['GET'])
def container_metrics(name):
    """Get current metrics for a specific container"""
    redis_client = get_redis_connection()
    
    # Try to get the full metrics object first
    metrics_key = f"container:{name}:metrics"
    metrics = redis_client.get(metrics_key)
    
    if metrics:
        return jsonify(json.loads(metrics))
    
    # Fallback to individual metrics
    cpu = redis_client.get(f"container:{name}:cpu") or 0
    memory = redis_client.get(f"container:{name}:memory") or 0
    
    return jsonify({
        'container': name,
        'cpu': float(cpu),
        'memory': float(memory),
        'timestamp': datetime.utcnow().isoformat()
    })

@bp.route('/containers/<name>/<action>', methods=['POST'])
def container_action(name, action):
    """Perform actions on a container (start, stop, restart, delete)"""
    try:
        import pylxd
        client = pylxd.Client()
        
        # Get the container
        try:
            container = client.containers.get(name)
        except pylxd.exceptions.NotFound:
            return jsonify({'error': f'Container {name} not found'}), 404
            
        session = get_db_session()
        db_container = session.query(Container).filter(Container.name == name).first()
        
        if action == 'start':
            if container.status != 'Running':
                container.start(wait=True)
                if db_container:
                    db_container.status = 'Running'
                    session.commit()
                return jsonify({'message': f'Container {name} started successfully'})
            else:
                return jsonify({'message': f'Container {name} is already running'})
                
        elif action == 'stop':
            if container.status == 'Running':
                container.stop(wait=True)
                if db_container:
                    db_container.status = 'Stopped'
                    session.commit()
                return jsonify({'message': f'Container {name} stopped successfully'})
            else:
                return jsonify({'message': f'Container {name} is already stopped'})
                
        elif action == 'restart':
            if container.status == 'Running':
                container.restart(wait=True)
                return jsonify({'message': f'Container {name} restarted successfully'})
            else:
                return jsonify({'error': f'Container {name} is not running, cannot restart'}), 400
                
        elif action == 'delete':
            # First check if it's part of a load balancer
            try:
                from app.models.loadbalancer import LoadBalancerTarget
                targets = session.query(LoadBalancerTarget).filter(
                    LoadBalancerTarget.container_name == name
                ).all()
                
                # Remove from all load balancers
                for target in targets:
                    session.delete(target)
            except Exception as e:
                logger.warning(f"Error checking load balancer targets: {str(e)}")
            
            # Stop if running
            if container.status == 'Running':
                container.stop(wait=True)
            
            # Delete container
            container.delete(wait=True)
            
            # Remove from database
            if db_container:
                session.delete(db_container)
                session.commit()
                
            return jsonify({'message': f'Container {name} deleted successfully'})
            
        else:
            return jsonify({'error': f'Unknown action: {action}'}), 400
            
    except Exception as e:
        logger.error(f"Error performing {action} on container {name}: {str(e)}")
        return jsonify({'error': f'Failed to {action} container: {str(e)}'}), 500

@bp.route('/containers/metrics', methods=['GET'])
def all_container_metrics():
    """Get metrics for all containers"""
    session = get_db_session()
    redis_client = get_redis_connection()
    
    containers = session.query(Container).all()
    metrics = []
    
    for container in containers:
        cpu = redis_client.get(f"container:{container.name}:cpu") or 0
        memory = redis_client.get(f"container:{container.name}:memory") or 0
        
        metrics.append({
            'id': container.id,
            'name': container.name,
            'status': container.status,
            'cpu': float(cpu),
            'memory': float(memory),
            'timestamp': datetime.utcnow().isoformat()
        })
    
    return jsonify(metrics)

@bp.route('/scaling-rules', methods=['GET', 'POST'])
def scaling_rules():
    """List all scaling rules or create a new one"""
    session = get_db_session()

    if request.method == 'POST':
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['container_name', 'metric', 'threshold', 'action_type', 'cooldown']
        if not all(field in data for field in required_fields):
            return jsonify({'error': 'Missing required fields'}), 400

        rule = ScalingRule(
            container_name=data['container_name'],
            metric=data['metric'],
            threshold=float(data['threshold']),
            action_type=data['action_type'],
            cooldown=int(data['cooldown'])
        )

        if data['action_type'] == 'horizontal':
            if 'increment' not in data:
                return jsonify({'error': 'Missing increment for horizontal scaling'}), 400
            rule.increment = int(data['increment'])
        else:
            if 'cpu_increment' in data:
                rule.cpu_increment = data['cpu_increment']
            if 'memory_increment' in data:
                rule.memory_increment = data['memory_increment']

        session.add(rule)
        session.commit()

        return jsonify({
            'id': rule.id,
            'container_name': rule.container_name,
            'metric': rule.metric,
            'threshold': rule.threshold,
            'action_type': rule.action_type,
            'increment': rule.increment,
            'cpu_increment': rule.cpu_increment,
            'memory_increment': rule.memory_increment,
            'cooldown': rule.cooldown
        }), 201

    # GET request - list all rules
    container_name = request.args.get('container')
    if container_name:
        rules = session.query(ScalingRule).filter(
            ScalingRule.container_name == container_name
        ).all()
    else:
        rules = session.query(ScalingRule).all()

    return jsonify([{
        'id': r.id,
        'container_name': r.container_name,
        'metric': r.metric,
        'threshold': r.threshold,
        'action_type': r.action_type,
        'increment': r.increment,
        'cpu_increment': r.cpu_increment,
        'memory_increment': r.memory_increment,
        'cooldown': r.cooldown,
        'created_at': r.created_at.isoformat()
    } for r in rules])

@bp.route('/scaling-rules/<int:rule_id>', methods=['GET', 'PUT', 'DELETE'])
def scaling_rule_detail(rule_id):
    """Get, update, or delete a specific scaling rule"""
    session = get_db_session()
    rule = session.query(ScalingRule).filter(ScalingRule.id == rule_id).first()
    
    if not rule:
        return jsonify({'error': 'Scaling rule not found'}), 404
    
    if request.method == 'GET':
        return jsonify({
            'id': rule.id,
            'container_name': rule.container_name,
            'metric': rule.metric,
            'threshold': rule.threshold,
            'action_type': rule.action_type,
            'increment': rule.increment,
            'cpu_increment': rule.cpu_increment,
            'memory_increment': rule.memory_increment,
            'cooldown': rule.cooldown,
            'created_at': rule.created_at.isoformat()
        })
    
    elif request.method == 'PUT':
        data = request.get_json()
        
        if 'metric' in data:
            rule.metric = data['metric']
        if 'threshold' in data:
            rule.threshold = float(data['threshold'])
        if 'action_type' in data:
            rule.action_type = data['action_type']
        if 'increment' in data:
            rule.increment = int(data['increment'])
        if 'cpu_increment' in data:
            rule.cpu_increment = data['cpu_increment']
        if 'memory_increment' in data:
            rule.memory_increment = data['memory_increment']
        if 'cooldown' in data:
            rule.cooldown = int(data['cooldown'])
            
        session.commit()
        return jsonify({'message': 'Scaling rule updated successfully'})
    
    elif request.method == 'DELETE':
        session.delete(rule)
        session.commit()
        return jsonify({'message': 'Scaling rule deleted successfully'})

@bp.route('/scaling-history', methods=['GET'])
def scaling_history():
    """Get scaling history with optional limit"""
    session = get_db_session()
    limit = min(int(request.args.get('limit', 100)), 1000)  # Max 1000 records
    
    history = session.query(ScalingHistory).order_by(
        ScalingHistory.timestamp.desc()
    ).limit(limit).all()

    return jsonify([{
        'id': h.id,
        'container_name': h.container_name,
        'action': h.action,
        'reason': h.reason,
        'parameters': json.loads(h.parameters) if h.parameters else None,
        'timestamp': h.timestamp.isoformat()
    } for h in history])

@bp.route('/metrics/stream', methods=['GET'])
def metrics_stream():
    """SSE stream for real-time metrics updates"""
    redis_client = get_redis_connection()
    pubsub = redis_client.pubsub()
    pubsub.subscribe('container_metrics')

    def generate():
        for message in pubsub.listen():
            if message['type'] == 'message':
                yield f"data: {message['data']}\n\n"

    return current_app.response_class(
        generate(),
        mimetype='text/event-stream'
    )

# Get container IP
def get_container_ip(container_name):
    try:
        container = pylxd.Client().containers.get(container_name)
        if container.status != 'Running':
            return None
            
        state = container.state()
        # This is a simplified version - in reality, you'd need to handle multiple interfaces
        if state.network and 'eth0' in state.network:
            addresses = state.network['eth0'].get('addresses', [])
            for addr in addresses:
                if addr.get('family') == 'inet':
                    return addr.get('address')
        return None
    except Exception as e:
        logger.error(f"Error getting IP for {container_name}: {str(e)}")
        return None

@bp.route('/load-balancers', methods=['GET', 'POST'])
def load_balancers():
    """List all load balancers or create a new one"""
    session = get_db_session()
    
    if request.method == 'POST':
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['name', 'port', 'algorithm']
        if not all(field in data for field in required_fields):
            return jsonify({'error': 'Missing required fields'}), 400
            
        # Validate port number
        if not 1 <= data['port'] <= 65535:
            return jsonify({'error': 'Invalid port number'}), 400
            
        # Create new load balancer
        load_balancer = LoadBalancer(
            name=data['name'],
            port=data['port'],
            algorithm=data['algorithm'],
            description=data.get('description', '')
        )
        
        session.add(load_balancer)
        session.commit()
        
        return jsonify({
            'id': load_balancer.id,
            'name': load_balancer.name,
            'port': load_balancer.port,
            'algorithm': load_balancer.algorithm,
            'status': load_balancer.status,
            'created_at': load_balancer.created_at.isoformat()
        }), 201
    
    # GET request - list all load balancers
    load_balancers = session.query(LoadBalancer).all()
    return jsonify([{
        'id': lb.id,
        'name': lb.name,
        'port': lb.port,
        'algorithm': lb.algorithm,
        'status': lb.status,
        'target_count': len(lb.targets),
        'created_at': lb.created_at.isoformat()
    } for lb in load_balancers])

@bp.route('/load-balancers/<int:lb_id>', methods=['GET', 'PUT', 'DELETE'])
def load_balancer_detail(lb_id):
    """Get, update or delete a load balancer"""
    session = get_db_session()
    load_balancer = session.query(LoadBalancer).filter(LoadBalancer.id == lb_id).first()
    
    if not load_balancer:
        return jsonify({'error': 'Load balancer not found'}), 404
        
    if request.method == 'GET':
        return jsonify({
            'id': load_balancer.id,
            'name': load_balancer.name,
            'port': load_balancer.port,
            'algorithm': load_balancer.algorithm,
            'status': load_balancer.status,
            'description': load_balancer.description,
            'created_at': load_balancer.created_at.isoformat(),
            'targets': [{
                'id': target.id,
                'container_name': target.container_name,
                'ip_address': target.ip_address,
                'port': target.port,
                'weight': target.weight,
                'active': target.active,
                'health_status': target.health_status
            } for target in load_balancer.targets]
        })
    
    elif request.method == 'PUT':
        data = request.get_json()
        
        if 'name' in data:
            load_balancer.name = data['name']
        if 'port' in data:
            load_balancer.port = data['port']
        if 'algorithm' in data:
            load_balancer.algorithm = data['algorithm']
        if 'description' in data:
            load_balancer.description = data['description']
        if 'status' in data:
            load_balancer.status = data['status']
            
        session.commit()
        return jsonify({'message': 'Load balancer updated successfully'})
    
    elif request.method == 'DELETE':
        session.delete(load_balancer)
        session.commit()
        return jsonify({'message': 'Load balancer deleted'})

@bp.route('/load-balancers/<int:lb_id>/targets', methods=['GET', 'POST'])
def load_balancer_targets(lb_id):
    """List all targets for a load balancer or add a new one"""
    session = get_db_session()
    load_balancer = session.query(LoadBalancer).filter(LoadBalancer.id == lb_id).first()
    
    if not load_balancer:
        return jsonify({'error': 'Load balancer not found'}), 404
        
    if request.method == 'POST':
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['container_name', 'port']
        if not all(field in data for field in required_fields):
            return jsonify({'error': 'Missing required fields'}), 400
            
        # Get container IP
        container_ip = data.get('ip_address') or get_container_ip(data['container_name'])
        if not container_ip:
            return jsonify({'error': f"Could not determine IP for container {data['container_name']}"}), 400
            
        # Create new target
        target = LoadBalancerTarget(
            load_balancer_id=lb_id,
            container_name=data['container_name'],
            ip_address=container_ip,
            port=data['port'],
            weight=data.get('weight', 1),
            active=data.get('active', True)
        )
        
        session.add(target)
        session.commit()
        
        return jsonify({
            'id': target.id,
            'container_name': target.container_name,
            'ip_address': target.ip_address,
            'port': target.port,
            'weight': target.weight,
            'active': target.active,
            'health_status': target.health_status
        }), 201
    
    # GET request - list all targets
    return jsonify([{
        'id': target.id,
        'container_name': target.container_name,
        'ip_address': target.ip_address,
        'port': target.port,
        'weight': target.weight,
        'active': target.active,
        'health_status': target.health_status
    } for target in load_balancer.targets])

@bp.route('/load-balancers/<int:lb_id>/targets/<int:target_id>', methods=['PUT', 'DELETE'])
def load_balancer_target_detail(lb_id, target_id):
    """Update or delete a load balancer target"""
    session = get_db_session()
    target = session.query(LoadBalancerTarget).filter(
        LoadBalancerTarget.id == target_id,
        LoadBalancerTarget.load_balancer_id == lb_id
    ).first()
    
    if not target:
        return jsonify({'error': 'Target not found'}), 404
        
    if request.method == 'PUT':
        data = request.get_json()
        
        if 'ip_address' in data:
            target.ip_address = data['ip_address']
        if 'port' in data:
            target.port = data['port']
        if 'weight' in data:
            target.weight = data['weight']
        if 'active' in data:
            target.active = data['active']
        if 'health_status' in data:
            target.health_status = data['health_status']
            
        session.commit()
        return jsonify({'message': 'Target updated successfully'})
    
    elif request.method == 'DELETE':
        session.delete(target)
        session.commit()
        return jsonify({'message': 'Target deleted'})
