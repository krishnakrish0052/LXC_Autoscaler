from flask import Blueprint, jsonify, request, current_app
from app.models.containers import Container, ScalingHistory
from app.models.scaling import ScalingRule
from app.utils.helpers import get_db_session
from datetime import datetime
import json
import redis
from config import Config

bp = Blueprint('api', __name__)

def get_redis_connection():
    return redis.StrictRedis(
        host=Config.REDIS_HOST,
        port=Config.REDIS_PORT,
        db=0,
        decode_responses=True
    )

@bp.route('/containers', methods=['GET'])
def list_containers():
    """List all containers with their current status and metrics"""
    session = get_db_session()
    redis_client = get_redis_connection()
    
    containers = session.query(Container).all()
    result = []
    
    for container in containers:
        # Get latest metrics from Redis
        metrics_key = f"container:{container.name}:metrics"
        metrics = redis_client.get(metrics_key)
        
        container_data = {
            'id': container.id,
            'name': container.name,
            'status': container.status,
            'created_at': container.created_at.isoformat(),
            'updated_at': container.updated_at.isoformat() if container.updated_at else None,
            'metrics': json.loads(metrics) if metrics else None
        }
        result.append(container_data)
    
    return jsonify(result)

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
