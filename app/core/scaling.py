import logging
import time
import pylxd
from datetime import datetime, timedelta
import redis
import json
from celery import Celery
from app.models.containers import Container, ScalingHistory
from app.utils.helpers import get_db_session

logger = logging.getLogger(__name__)

app = Celery('scaling_executor', broker='redis://localhost:6379/0')

class LXCManager:
    def __init__(self, redis_host='localhost', redis_port=6379):
        self.client = pylxd.Client()
        self.redis = redis.StrictRedis(
            host=redis_host, 
            port=redis_port, 
            db=0,
            decode_responses=True
        )
        self.session = get_db_session()
        self.cooldowns = {}
        
    def _record_history(self, container_name, action, reason, params):
        history = ScalingHistory(
            container_name=container_name,
            action=action,
            reason=reason,
            parameters=json.dumps(params),
            timestamp=datetime.utcnow()
        )
        self.session.add(history)
        self.session.commit()
        
    def _in_cooldown(self, container_name, action_type):
        key = f"{container_name}:{action_type}"
        return key in self.cooldowns and self.cooldowns[key] > time.time()

    def _set_cooldown(self, container_name, action_type, duration):
        key = f"{container_name}:{action_type}"
        self.cooldowns[key] = time.time() + duration
        
    def _get_container_group(self, base_name):
        return [c for c in self.client.containers.all() 
               if c.name.startswith(base_name)]
               
    def _get_container_config(self, container_name):
        container = self.client.containers.get(container_name)
        return {
            'name': container.name,
            'config': container.config,
            'devices': container.devices,
            'profiles': container.profiles
        }
        
    def scale_up(self, container_name, count=1):
        if self._in_cooldown(container_name, 'scale_up'):
            logger.info(f"Scale up for {container_name} in cooldown")
            return False
            
        try:
            template_config = self._get_container_config(container_name)
            
            for i in range(count):
                new_name = f"{container_name}-{int(time.time())}-{i}"
                config = {
                    'name': new_name,
                    'source': {
                        'type': 'copy',
                        'source': container_name
                    },
                    'config': template_config['config'],
                    'devices': template_config['devices'],
                    'profiles': template_config['profiles']
                }
                
                new_container = self.client.containers.create(config, wait=True)
                new_container.start(wait=True)
                
                # Record in database
                container = Container(
                    name=new_name,
                    status='Running',
                    created_at=datetime.utcnow()
                )
                self.session.add(container)
                self.session.commit()
                
                logger.info(f"Created and started new container {new_name}")
                
            self._record_history(
                container_name,
                'scale_up',
                f"Added {count} containers",
                {'count': count}
            )
            self._set_cooldown(container_name, 'scale_up', 300)
            return True
            
        except Exception as e:
            logger.error(f"Error scaling up {container_name}: {str(e)}")
            self.session.rollback()
            return False
            
    def scale_down(self, container_name, count=1):
        if self._in_cooldown(container_name, 'scale_down'):
            logger.info(f"Scale down for {container_name} in cooldown")
            return False
            
        try:
            containers = self._get_container_group(container_name)
            if len(containers) <= 1:  # Don't remove the last one
                return False
                
            to_remove = sorted(containers, key=lambda c: c.name)[-count:]
            
            for container in to_remove:
                if container.status == 'Running':
                    container.stop(wait=True)
                container.delete(wait=True)
                
                # Update database
                db_container = self.session.query(Container).filter(
                    Container.name == container.name
                ).first()
                if db_container:
                    db_container.status = 'Stopped'
                    self.session.commit()
                
                logger.info(f"Removed container {container.name}")
                
            self._record_history(
                container_name,
                'scale_down',
                f"Removed {len(to_remove)} containers",
                {'count': len(to_remove)}
            )
            self._set_cooldown(container_name, 'scale_down', 300)
            return True
            
        except Exception as e:
            logger.error(f"Error scaling down {container_name}: {str(e)}")
            self.session.rollback()
            return False
            
    def resize_container(self, container_name, params):
        if self._in_cooldown(container_name, 'resize'):
            logger.info(f"Resize for {container_name} in cooldown")
            return False
            
        try:
            container = self.client.containers.get(container_name)
            limits = container.config.get('limits', {})
            
            changes = {}
            if 'cpu' in params:
                limits['cpu'] = str(params['cpu'])
                changes['cpu'] = params['cpu']
            if 'memory' in params:
                limits['memory'] = str(params['memory'])
                changes['memory'] = params['memory']
                
            container.config['limits'] = limits
            container.save(wait=True)
            
            if container.status == 'Running':
                container.restart(wait=True)
                
            self._record_history(
                container_name,
                'resize',
                'Adjusted container resources',
                changes
            )
            self._set_cooldown(container_name, 'resize', 600)
            return True
            
        except Exception as e:
            logger.error(f"Error resizing {container_name}: {str(e)}")
            return False

@app.task
def execute_decision(decision):
    manager = LXCManager()
    decision = json.loads(decision)
    
    try:
        if decision['action'] == 'scale_up':
            success = manager.scale_up(
                decision['container_name'],
                decision['params'].get('count', 1)
            )
        elif decision['action'] == 'scale_down':
            success = manager.scale_down(
                decision['container_name'],
                decision['params'].get('count', 1)
            )
        elif decision['action'] == 'resize':
            success = manager.resize_container(
                decision['container_name'],
                decision['params']
            )
        else:
            success = False
            
        return {'success': success, 'decision': decision}
    except Exception as e:
        logger.error(f"Error executing decision: {str(e)}")
        return {'success': False, 'error': str(e)}