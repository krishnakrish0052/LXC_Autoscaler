from flask import Blueprint, jsonify, request
from app.models.containers import Container, ScalingHistory
from app.models.scaling import ScalingRule
from app.utils.helpers import get_db_session
from datetime import datetime
import json

bp = Blueprint('api', __name__)

@bp.route('/containers', methods=['GET'])
def list_containers():
    session = get_db_session()
    containers = session.query(Container).all()
    return jsonify([{
        'id': c.id,
        'name': c.name,
        'status': c.status,
        'created_at': c.created_at.isoformat(),
        'updated_at': c.updated_at.isoformat() if c.updated_at else None
    } for c in containers])

@bp.route('/containers/<name>', methods=['GET'])
def get_container(name):
    session = get_db_session()
    container = session.query(Container).filter(Container.name == name).first()
    if not container:
        return jsonify({'error': 'Container not found'}), 404
        
    return jsonify({
        'id': container.id,
        'name': container.name,
        'status': container.status,
        'created_at': container.created_at.isoformat(),
        'updated_at': container.updated_at.isoformat() if container.updated_at else None
    })

@bp.route('/scaling-rules', methods=['GET', 'POST'])
def scaling_rules():
    session = get_db_session()
    
    if request.method == 'POST':
        data = request.get_json()
        
        rule = ScalingRule(
            container_name=data['container_name'],
            metric=data['metric'],
            threshold=float(data['threshold']),
            action_type=data['action_type'],
            cooldown=int(data['cooldown'])
        )
        
        if data['action_type'] == 'horizontal':
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
    
    # GET request
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
    session = get_db_session()
    limit = request.args.get('limit', 100)
    
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