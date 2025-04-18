from flask import Blueprint, jsonify, request
from app.models.containers import Container, ScalingHistory
from app.models.scaling import ScalingRule
from app.utils.helpers import get_db_session
from datetime import datetime
import json

bp = Blueprint('legacy_api', __name__)

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

@bp.route('/scaling-rules', methods=['GET'])
def scaling_rules():
    session = get_db_session()
    
    # POST method has been removed to prevent duplicate rule creation
    
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