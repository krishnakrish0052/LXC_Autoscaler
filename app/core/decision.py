import json
import logging
import redis
from datetime import datetime, timedelta
from celery import Celery
from app.models.scaling import ScalingRule
from app.utils.helpers import get_db_session

logger = logging.getLogger(__name__)

app = Celery('decision_engine', broker='redis://localhost:6379/0')

class ScalingDecision:
    def __init__(self, container_name, action, reason, params=None):
        self.container_name = container_name
        self.action = action  # 'scale_up', 'scale_down', 'resize'
        self.reason = reason
        self.params = params or {}
        self.timestamp = datetime.utcnow()
        
    def to_dict(self):
        return {
            'container_name': self.container_name,
            'action': self.action,
            'reason': self.reason,
            'params': self.params,
            'timestamp': self.timestamp.isoformat()
        }

class DecisionEngine:
    def __init__(self, redis_host='localhost', redis_port=6379):
        self.redis = redis.StrictRedis(
            host=redis_host, 
            port=redis_port, 
            db=0,
            decode_responses=True
        )
        self.pubsub = self.redis.pubsub()
        self.pubsub.subscribe('metrics')
        self.session = get_db_session()
        
    def evaluate_rules(self, metrics):
        try:
            container_name = metrics['container']
            rules = self.session.query(ScalingRule).filter(
                ScalingRule.container_name == container_name
            ).all()
            
            if not rules:
                return ScalingDecision(
                    container_name,
                    'no_action',
                    'No scaling rules defined for container'
                )
            
            # Check each rule
            for rule in rules:
                metric_value = metrics.get(rule.metric)
                if metric_value is None:
                    continue
                    
                if metric_value > rule.threshold:
                    # Check cooldown
                    last_action = self._get_last_action(container_name, rule.action_type)
                    if last_action and (datetime.utcnow() - last_action) < timedelta(seconds=rule.cooldown):
                        continue
                        
                    return ScalingDecision(
                        container_name,
                        rule.action_type,
                        f"{rule.metric} {metric_value} exceeds threshold {rule.threshold}",
                        self._get_action_params(rule)
                    )
                        
            return ScalingDecision(
                container_name,
                'no_action',
                'No rules triggered'
            )   
        except Exception as e:
            logger.error(f"Error evaluating rules: {str(e)}")
            return None
            
    def _get_last_action(self, container_name, action_type):
        # In a real implementation, query the database for last action timestamp
        return None
        
    def _get_action_params(self, rule):
        params = {}
        if rule.action_type == 'horizontal':
            params['count'] = rule.increment
        elif rule.action_type == 'vertical':
            if rule.cpu_increment:
                params['cpu'] = rule.cpu_increment
            if rule.memory_increment:
                params['memory'] = rule.memory_increment
        return params
        
    def run(self):
        logger.info("Decision engine started")
        for message in self.pubsub.listen():
            if message['type'] == 'message':
                try:
                    metrics = json.loads(message['data'])
                    decision = self.evaluate_rules(metrics)
                    if decision and decision.action != 'no_action':
                        self.redis.publish('decisions', json.dumps(decision.to_dict()))
                        logger.info(f"Decision made: {decision.action} for {decision.container_name}")
                except Exception as e:
                    logger.error(f"Error processing message: {str(e)}")

@app.task
def process_metrics(metrics):
    engine = DecisionEngine()
    decision = engine.evaluate_rules(metrics)
    if decision and decision.action != 'no_action':
        return decision.to_dict()
    return None