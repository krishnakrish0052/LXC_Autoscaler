import json
import logging
import redis
from datetime import datetime, timedelta
from celery import Celery
from app.models.scaling import ScalingRule
from app.utils.helpers import get_db_session

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_celery_app():
    app = Celery('decision_engine')
    app.config_from_object('config', namespace='CELERY')
    app.autodiscover_tasks(['app.core'])
    return app

celery = create_celery_app()

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
            container_name = metrics.get('container')
            if not container_name:
                logger.error("Metrics missing container name")
                return None
                
            rules = self.session.query(ScalingRule).filter(
                ScalingRule.container_name == container_name
            ).all()
            
            if not rules:
                logger.debug(f"No rules defined for container {container_name}")
                return ScalingDecision(
                    container_name,
                    'no_action',
                    'No scaling rules defined for container'
                )
            
            # Check each rule
            for rule in rules:
                metric_value = metrics.get(rule.metric)
                if metric_value is None:
                    logger.debug(f"Metric {rule.metric} not found in metrics")
                    continue
                    
                if metric_value > rule.threshold:
                    # Check cooldown
                    last_action = self._get_last_action(container_name, rule.action_type)
                    if last_action and (datetime.utcnow() - last_action) < timedelta(seconds=rule.cooldown):
                        logger.debug(f"Action {rule.action_type} for {container_name} in cooldown")
                        continue
                        
                    logger.info(f"Rule triggered: {rule.metric} {metric_value} > {rule.threshold}")
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
            logger.error(f"Error evaluating rules: {str(e)}", exc_info=True)
            return None
            
    def _get_last_action(self, container_name, action_type):
        from app.models.containers import ScalingHistory
        last_action = self.session.query(ScalingHistory).filter(
            ScalingHistory.container_name == container_name,
            ScalingHistory.action == action_type
        ).order_by(ScalingHistory.timestamp.desc()).first()
        
        return last_action.timestamp if last_action else None
        
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
        try:
            for message in self.pubsub.listen():
                if message['type'] == 'message':
                    try:
                        metrics = json.loads(message['data'])
                        logger.debug(f"Received metrics: {metrics}")
                        decision = self.evaluate_rules(metrics)
                        if decision and decision.action != 'no_action':
                            self.redis.publish('decisions', json.dumps(decision.to_dict()))
                            logger.info(f"Published decision: {decision.action} for {decision.container_name}")
                    except json.JSONDecodeError:
                        logger.error("Failed to decode metrics message")
                    except Exception as e:
                        logger.error(f"Error processing message: {str(e)}", exc_info=True)
        except KeyboardInterrupt:
            logger.info("Decision engine stopped")
        except Exception as e:
            logger.error(f"Decision engine failed: {str(e)}", exc_info=True)
        finally:
            self.pubsub.close()

@celery.task(name='decision_engine.process_metrics')
def process_metrics(metrics):
    try:
        engine = DecisionEngine()
        decision = engine.evaluate_rules(metrics)
        if decision and decision.action != 'no_action':
            return decision.to_dict()
        return None
    except Exception as e:
        logger.error(f"Error in process_metrics task: {str(e)}", exc_info=True)
        raise

def start_decision_engine():
    engine = DecisionEngine()
    engine.run()

if __name__ == '__main__':
    start_decision_engine()
