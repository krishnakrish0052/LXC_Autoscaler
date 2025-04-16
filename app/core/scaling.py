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
        
    # Update in app/core/scaling.py - modify the scale_up method to add new containers to load balancers

def scale_up(self, container_name, count=1):
    if self._in_cooldown(container_name, 'scale_up'):
        logger.info(f"Scale up for {container_name} in cooldown")
        return False
        
    try:
        template_config = self._get_container_config(container_name)
        new_containers = []
        
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
            new_containers.append(new_name)
            
            # Record in database
            container = Container(
                name=new_name,
                status='Running',
                created_at=datetime.utcnow()
            )
            self.session.add(container)
            
            logger.info(f"Created and started new container {new_name}")
        
        self.session.commit()
        
        # Add containers to associated load balancers
        self._add_to_load_balancers(container_name, new_containers)
        
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

def _add_to_load_balancers(self, container_name, new_containers):
    """Add new containers to any load balancers that have the template container"""
    try:
        from app.models.loadbalancer import LoadBalancer, LoadBalancerTarget
        
        # Find load balancers that have the template container as a target
        load_balancers = self.session.query(LoadBalancer).join(
            LoadBalancerTarget
        ).filter(
            LoadBalancerTarget.container_name == container_name
        ).all()
        
        if not load_balancers:
            logger.info(f"No load balancers found with {container_name} as a target")
            return
            
        # Get the target configuration from the template container
        template_target = self.session.query(LoadBalancerTarget).filter(
            LoadBalancerTarget.container_name == container_name
        ).first()
        
        if not template_target:
            logger.warning(f"Template target not found for {container_name}")
            return
        
        # Add each new container to each load balancer
        for lb in load_balancers:
            logger.info(f"Adding {len(new_containers)} new containers to load balancer {lb.name}")
            
            for container_name in new_containers:
                # Get container IP
                container_ip = self._get_container_ip(container_name)
                if not container_ip:
                    logger.warning(f"Could not get IP for {container_name}, skipping")
                    continue
                    
                # Create new target
                new_target = LoadBalancerTarget(
                    load_balancer_id=lb.id,
                    container_name=container_name,
                    ip_address=container_ip,
                    port=template_target.port,
                    weight=template_target.weight,
                    active=True
                )
                
                self.session.add(new_target)
            
        self.session.commit()
        logger.info(f"Successfully added new containers to load balancers")
    except Exception as e:
        logger.error(f"Error adding containers to load balancers: {str(e)}")
        # Don't fail the entire operation if load balancer integration fails
        pass

def _get_container_ip(self, container_name):
    """Get the IP address of a container"""
    try:
        container = self.client.containers.get(container_name)
        if container.status != 'Running':
            return None
            
        state = container.state()
        if state.network and 'eth0' in state.network:
            addresses = state.network['eth0'].get('addresses', [])
            for addr in addresses:
                if addr.get('family') == 'inet':
                    return addr.get('address')
        return None
    except Exception as e:
        logger.error(f"Error getting IP for {container_name}: {str(e)}")
        return None
            
def scale_down(self, container_name, count=1):
    if self._in_cooldown(container_name, 'scale_down'):
        logger.info(f"Scale down for {container_name} in cooldown")
        return False
        
    try:
        containers = self._get_container_group(container_name)
        if len(containers) <= 1:  # Don't remove the last one
            return False
            
        to_remove = sorted(containers, key=lambda c: c.name)[-count:]
        removed_names = []
        
        for container in to_remove:
            # Remove from load balancers before stopping the container
            self._remove_from_load_balancers(container.name)
            
            if container.status == 'Running':
                container.stop(wait=True)
            container.delete(wait=True)
            removed_names.append(container.name)
            
            # Update database
            db_container = self.session.query(Container).filter(
                Container.name == container.name
            ).first()
            if db_container:
                self.session.delete(db_container)
            
            logger.info(f"Removed container {container.name}")
            
        self.session.commit()
            
        self._record_history(
            container_name,
            'scale_down',
            f"Removed {len(to_remove)} containers",
            {'count': len(to_remove), 'containers': removed_names}
        )
        self._set_cooldown(container_name, 'scale_down', 300)
        return True
        
    except Exception as e:
        logger.error(f"Error scaling down {container_name}: {str(e)}")
        self.session.rollback()
        return False

def _remove_from_load_balancers(self, container_name):
    """Remove container from all load balancers"""
    try:
        from app.models.loadbalancer import LoadBalancerTarget
        
        # Find and delete all load balancer targets for this container
        targets = self.session.query(LoadBalancerTarget).filter(
            LoadBalancerTarget.container_name == container_name
        ).all()
        
        if not targets:
            logger.info(f"No load balancer targets found for {container_name}")
            return
            
        for target in targets:
            logger.info(f"Removing {container_name} from load balancer {target.load_balancer_id}")
            self.session.delete(target)
            
        self.session.commit()
        logger.info(f"Successfully removed {container_name} from all load balancers")
    except Exception as e:
        logger.error(f"Error removing {container_name} from load balancers: {str(e)}")
        # Don't fail the entire operation if load balancer integration fails
        pass
            
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