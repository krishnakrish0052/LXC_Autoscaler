# app/api/metrics_routes.py
from flask import Blueprint, jsonify, request, current_app
from app.services.metrics import MetricsService
import json
import redis
from config import Config
from app.utils.helpers import get_redis_connection

metrics_bp = Blueprint('metrics', __name__, url_prefix='/api/metrics')

@metrics_bp.route('/system', methods=['GET'])
def system_metrics():
    """Get comprehensive system metrics"""
    metrics_service = MetricsService()
    metrics = metrics_service.get_system_metrics()
    
    if metrics:
        return jsonify(metrics)
    else:
        return jsonify({'error': 'Failed to retrieve system metrics'}), 500

@metrics_bp.route('/instances', methods=['GET'])
def all_instance_metrics():
    """Get metrics for all instances (containers and VMs)"""
    metrics_service = MetricsService()
    metrics = metrics_service.get_all_instance_metrics()
    
    return jsonify(metrics)

@metrics_bp.route('/instances/<name>', methods=['GET'])
def instance_metrics(name):
    """Get comprehensive metrics for a specific instance"""
    metrics_service = MetricsService()
    metrics = metrics_service.get_instance_metrics(name)
    
    if 'error' in metrics and metrics.get('status') != 'Running':
        return jsonify(metrics), 404
        
    return jsonify(metrics)

@metrics_bp.route('/instances/<name>/history', methods=['GET'])
def instance_history(name):
    """Get historical metrics for a specific instance"""
    metric_type = request.args.get('metric', 'cpu')
    hours = int(request.args.get('hours', 24))
    
    metrics_service = MetricsService()
    history = metrics_service.get_historical_metrics(name, metric_type, hours)
    
    return jsonify(history)

@metrics_bp.route('/stream', methods=['GET'])
def metrics_stream():
    """SSE stream for real-time metrics updates"""
    redis_client = get_redis_connection()
    pubsub = redis_client.pubsub()
    pubsub.subscribe('instance_metrics')

    def generate():
        for message in pubsub.listen():
            if message['type'] == 'message':
                yield f"data: {message['data']}\n\n"

    return current_app.response_class(
        generate(),
        mimetype='text/event-stream'
    )

# Additional routes for specific metric types

@metrics_bp.route('/cpu', methods=['GET'])
def cpu_metrics():
    """Get CPU metrics for all instances"""
    redis_client = get_redis_connection()
    
    # Get system CPU metrics
    system_metrics_str = redis_client.get('system:metrics')
    system_metrics = json.loads(system_metrics_str) if system_metrics_str else {}
    
    # Get all instance keys with CPU metrics
    instance_keys = redis_client.keys('instance:*:cpu')
    
    instances = []
    for key in instance_keys:
        instance_name = key.split(':')[1]
        cpu_value = float(redis_client.get(key) or 0)
        
        instances.append({
            'name': instance_name,
            'cpu': cpu_value
        })
    
    return jsonify({
        'system': system_metrics.get('cpu', {}),
        'instances': instances
    })

@metrics_bp.route('/memory', methods=['GET'])
def memory_metrics():
    """Get memory metrics for all instances"""
    redis_client = get_redis_connection()
    
    # Get system memory metrics
    system_metrics_str = redis_client.get('system:metrics')
    system_metrics = json.loads(system_metrics_str) if system_metrics_str else {}
    
    # Get all instance keys with memory metrics
    instance_keys = redis_client.keys('instance:*:memory')
    
    instances = []
    for key in instance_keys:
        instance_name = key.split(':')[1]
        memory_value = float(redis_client.get(key) or 0)
        
        instances.append({
            'name': instance_name,
            'memory': memory_value
        })
    
    return jsonify({
        'system': system_metrics.get('memory', {}),
        'instances': instances
    })

@metrics_bp.route('/network', methods=['GET'])
def network_metrics():
    """Get network metrics for all instances"""
    metrics_service = MetricsService()
    
    # Get system metrics
    system_metrics = metrics_service.get_system_metrics() or {}
    
    # Get all instance metrics
    all_metrics = metrics_service.get_all_instance_metrics()
    
    # Extract network metrics
    instances = []
    for metrics in all_metrics:
        if 'network' in metrics:
            instances.append({
                'name': metrics.get('instance'),
                'network': metrics.get('network', {})
            })
    
    return jsonify({
        'system': system_metrics.get('network', {}),
        'instances': instances
    })

@metrics_bp.route('/disk', methods=['GET'])
def disk_metrics():
    """Get disk metrics for all instances"""
    metrics_service = MetricsService()
    
    # Get system metrics
    system_metrics = metrics_service.get_system_metrics() or {}
    
    # Get all instance metrics
    all_metrics = metrics_service.get_all_instance_metrics()
    
    # Extract disk metrics
    instances = []
    for metrics in all_metrics:
        if 'disk' in metrics:
            instances.append({
                'name': metrics.get('instance'),
                'disk': metrics.get('disk', {})
            })
    
    return jsonify({
        'system': system_metrics.get('disk', {}),
        'instances': instances
    })

@metrics_bp.route('/heatmap', methods=['GET'])
def metrics_heatmap():
    """Get heatmap data for resource usage"""
    metrics_service = MetricsService()
    all_metrics = metrics_service.get_all_instance_metrics()
    
    heatmap_data = []
    for metrics in all_metrics:
        if metrics.get('status') != 'Running':
            continue
            
        instance_data = {
            'name': metrics.get('instance'),
            'type': metrics.get('type', 'container'),
            'cpu': metrics.get('cpu', {}).get('percent', 0),
            'memory': metrics.get('memory', {}).get('percent', 0)
        }
        
        # Calculate network activity (sum of sent and received bytes across all interfaces)
        network_activity = 0
        for iface, net_stats in metrics.get('network', {}).items():
            network_activity += net_stats.get('bytes_sent', 0) + net_stats.get('bytes_received', 0)
        
        # Normalize network activity to a 0-100 scale
        if network_activity > 0:
            network_percent = min(network_activity / (1024 * 1024 * 10) * 100, 100)  # Normalize to 10MB max
        else:
            network_percent = 0
            
        instance_data['network'] = network_percent
        
        # Calculate disk activity (sum of read and written bytes across all devices)
        disk_activity = 0
        for device, disk_stats in metrics.get('disk', {}).items():
            disk_activity += disk_stats.get('bytes_read', 0) + disk_stats.get('bytes_written', 0)
        
        # Normalize disk activity to a 0-100 scale
        if disk_activity > 0:
            disk_percent = min(disk_activity / (1024 * 1024 * 100) * 100, 100)  # Normalize to 100MB max
        else:
            disk_percent = 0
            
        instance_data['disk'] = disk_percent
        
        heatmap_data.append(instance_data)
    
    return jsonify(heatmap_data)
