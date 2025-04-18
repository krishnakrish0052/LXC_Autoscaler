# app/services/scaling.py
import logging
import time
import json
import pylxd
from datetime import datetime, timedelta
import redis
from celery import Celery
from app.models.instances import Instance, ScalingHistory
from app.models.scaling import ScalingRule
from app.utils.helpers import get_db_session
from app.models.loadbalancer import LoadBalancer, LoadBalancerTarget
from config import Config

logger = logging.getLogger(__name__)

app = Celery('scaling_executor', broker=f'redis://{Config.REDIS_HOST}:{Config.REDIS_PORT}/0')

class LXCScalingService:
    def __init__(self, redis_host=None, redis_port=None):
        self.client = pylxd.Client()
        self.redis = redis.StrictRedis(
            host=redis_host or Config.REDIS_HOST, 
            port=redis_port or Config.REDIS_PORT, 
            db=0,
            decode_responses=True
        )
        self.session = get_db_session()
        self.cooldowns = {}
        
    def _record_history(self, instance_name, instance_type, action, reason, params):
        """Record a scaling action in the history"""
        history = ScalingHistory(
            instance_name=instance_name,
            instance_type=instance_type,
            action=action,
            reason=reason,
            parameters=json.dumps(params),
            timestamp=datetime.utcnow()
        )
        self.session.add(history)
        self.session.commit()
        
    def _in_cooldown(self, instance_name, action_type):
        """Check if an instance is in cooldown period"""
        key = f"{instance_name}:{action_type}"
        return key in self.cooldowns and self.cooldowns[key] > time.time()

    def _set_cooldown(self, instance_name, action_type, duration):
        """Set a cooldown period for an instance"""
        key = f"{instance_name}:{action_type}"
        self.cooldowns[key] = time.time() + duration
        
    def _get_instance_group(self, base_name):
        """Get all instances that belong to the same scaling group"""
        instances = []
        for c in self.client.instances.all():
            if c.name.startswith(base_name):
                instances.append(c)
        return instances
               
    def _get_instance_config(self, instance_name):
        """Get the configuration of an instance"""
        instance = self.client.instances.get(instance_name)
        is_vm = instance.type == 'virtual-machine'
        
        return {
            'name': instance.name,
            'type': instance.type,
            'config': instance.config,
            'devices': instance.devices,
            'profiles': instance.profiles,
            'is_vm': is_vm
        }
    
    def scale_up(self, instance_name, count=1):
        """Scale up by adding more instances"""
        if self._in_cooldown(instance_name, 'scale_up'):
            logger.info(f"Scale up for {instance_name} in cooldown")
            return False
        
        try:
            # Get the instance configuration to use as a template
            template_config = self._get_instance_config(instance_name)
            new_instances = []
            
            # Get the instance type from database
            db_instance = self.session.query(Instance).filter(
                Instance.name == instance_name
            ).first()
            
            instance_type = 'container'  # Default
            if db_instance:
                instance_type = db_instance.type
            elif template_config.get('is_vm'):
                instance_type = 'virtual-machine'
            
            for i in range(count):
                new_name = f"{instance_name}-{int(time.time())}-{i}"
                config = {
                    'name': new_name,
                    'source': {
                        'type': 'copy',
                        'source': instance_name
                    },
                    'config': template_config['config'],
                    'devices': template_config['devices'],
                    'profiles': template_config['profiles']
                }
                
                # Create the new instance
                new_instance = self.client.instances.create(config, wait=True)
                new_instance.start(wait=True)
                new_instances.append(new_name)
                
                # Record in database
                instance = Instance(
                    name=new_name,
                    type=instance_type,
                    status='Running',
                    image=db_instance.image if db_instance else None,
                    profile=','.join(template_config['profiles']),
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                    cpu_limit=template_config['config'].get('limits.cpu'),
                    memory_limit=template_config['config'].get('limits.memory'),
                    disk_limit=template_config['config'].get('limits.disk')
                )
                self.session.add(instance)
                
                logger.info(f"Created and started new {instance_type} {new_name}")
            
            self.session.commit()
            
            # Add instances to associated load balancers
            self._add_to_load_balancers(instance_name, new_instances)
            
            self._record_history(
                instance_name,
                instance_type,
                'scale_up',
                f"Added {count} instances",
                {'count': count, 'names': new_instances}
            )
            self._set_cooldown(instance_name, 'scale_up', 300)
            return True
            
        except Exception as e:
            logger.error(f"Error scaling up {instance_name}: {str(e)}")
            self.session.rollback()
            return False
    
    def scale_down(self, instance_name, count=1):
        """Scale down by removing instances"""
        if self._in_cooldown(instance_name, 'scale_down'):
            logger.info(f"Scale down for {instance_name} in cooldown")
            return False
            
        try:
            instances = self._get_instance_group(instance_name)
            if len(instances) <= 1:  # Don't remove the last one
                return False
                
            # Sort by name to keep the original one
            to_remove = sorted(instances, key=lambda i: i.name)[-count:]
            removed_names = []
            
            # Get instance type for history
            db_instance = self.session.query(Instance).filter(
                Instance.name == instance_name
            ).first()
            
            instance_type = 'container'  # Default
            if db_instance:
                instance_type = db_instance.type
            elif hasattr(instances[0], 'type') and instances[0].type == 'virtual-machine':
                instance_type = 'virtual-machine'
                
            for instance in to_remove:
                # Remove from load balancers before stopping the instance
                self._remove_from_load_balancers(instance.name)
                
                if instance.status == 'Running':
                    instance.stop(wait=True)
                instance.delete(wait=True)
                removed_names.append(instance.name)
                
                # Update database
                db_instance = self.session.query(Instance).filter(
                    Instance.name == instance.name
                ).first()
                if db_instance:
                    self.session.delete(db_instance)
                
                logger.info(f"Removed {instance_type} {instance.name}")
                
            self.session.commit()
                
            self._record_history(
                instance_name,
                instance_type,
                'scale_down',
                f"Removed {len(to_remove)} instances",
                {'count': len(to_remove), 'instances': removed_names}
            )
            self._set_cooldown(instance_name, 'scale_down', 300)
            return True
            
        except Exception as e:
            logger.error(f"Error scaling down {instance_name}: {str(e)}")
            self.session.rollback()
            return False
            
    def resize_instance(self, instance_name, params):
        """Resize an existing instance (vertical scaling)"""
        if self._in_cooldown(instance_name, 'resize'):
            logger.info(f"Resize for {instance_name} in cooldown")
            return False
            
        try:
            instance = self.client.instances.get(instance_name)
            
            # Determine instance type
            instance_type = 'container'
            if hasattr(instance, 'type') and instance.type == 'virtual-machine':
                instance_type = 'virtual-machine'
                
            # Get existing limits
            limits = instance.config.get('limits', {})
            
            changes = {}
            if 'cpu' in params:
                limits['cpu'] = str(params['cpu'])
                changes['cpu'] = params['cpu']
            if 'memory' in params:
                limits['memory'] = str(params['memory'])
                changes['memory'] = params['memory']
            if 'disk' in params and instance_type == 'virtual-machine':
                # Disk resizing typically only applies to VMs
                limits['disk'] = str(params['disk'])
                changes['disk'] = params['disk']
                
            instance.config['limits'] = limits
            instance.save(wait=True)
            
            # Update database
            db_instance = self.session.query(Instance).filter(
                Instance.name == instance_name
            ).first()
            
            if db_instance:
                if 'cpu' in changes:
                    db_instance.cpu_limit = changes['cpu']
                if 'memory' in changes:
                    db_instance.memory_limit = changes['memory']
                if 'disk' in changes:
                    db_instance.disk_limit = changes['disk']
                db_instance.updated_at = datetime.utcnow()
                self.session.commit()
            
            if instance.status == 'Running':
                instance.restart(wait=True)
                
            self._record_history(
                instance_name,
                instance_type,
                'resize',
                'Adjusted instance resources',
                changes
            )
            self._set_cooldown(instance_name, 'resize', 600)
            return True
            
        except Exception as e:
            logger.error(f"Error resizing {instance_name}: {str(e)}")
            self.session.rollback()
            return False
            
    def _add_to_load_balancers(self, template_instance_name, new_instances):
        """Add new instances to any load balancers that have the template instance"""
        try:
            # Find load balancers that have the template instance as a target
            load_balancers = self.session.query(LoadBalancer).join(
                LoadBalancerTarget
            ).filter(
                LoadBalancerTarget.container_name == template_instance_name
            ).all()
            
            if not load_balancers:
                logger.info(f"No load balancers found with {template_instance_name} as a target")
                return
                
            # Get the target configuration from the template instance
            template_target = self.session.query(LoadBalancerTarget).filter(
                LoadBalancerTarget.container_name == template_instance_name
            ).first()
            
            if not template_target:
                logger.warning(f"Template target not found for {template_instance_name}")
                return
            
            # Add each new instance to each load balancer
            for lb in load_balancers:
                logger.info(f"Adding {len(new_instances)} new instances to load balancer {lb.name}")
                
                for instance_name in new_instances:
                    # Get instance IP
                    instance_ip = self._get_instance_ip(instance_name)
                    if not instance_ip:
                        logger.warning(f"Could not get IP for {instance_name}, skipping")
                        continue
                        
                    # Create new target
                    new_target = LoadBalancerTarget(
                        load_balancer_id=lb.id,
                        container_name=instance_name,
                        ip_address=instance_ip,
                        port=template_target.port,
                        weight=template_target.weight,
                        active=True
                    )
                    
                    self.session.add(new_target)
            
            self.session.commit()
            logger.info(f"Successfully added new instances to load balancers")
            
            # Update the load balancer configuration
            for lb in load_balancers:
                try:
                    # Get the load balancer service to update the configuration
                    from app.services.loadbalancer import LoadBalancerService
                    lb_service = LoadBalancerService()
                    
                    # Get lb container
                    lb_container = self.client.instances.get(f"lb-{lb.name}")
                    
                    # Update config based on algorithm
                    if lb.algorithm.startswith('round_robin'):
                        lb_service._update_nginx_config(lb_container, lb)
                    else:
                        lb_service._update_haproxy_config(lb_container, lb)
                except Exception as e:
                    logger.error(f"Error updating load balancer configuration: {str(e)}")
            
        except Exception as e:
            logger.error(f"Error adding instances to load balancers: {str(e)}")
            # Don't fail the entire operation if load balancer integration fails
            self.session.rollback()
            
    def _remove_from_load_balancers(self, instance_name):
        """Remove an instance from all load balancers"""
        try:
            # Find and delete all load balancer targets for this instance
            targets = self.session.query(LoadBalancerTarget).filter(
                LoadBalancerTarget.container_name == instance_name
            ).all()
            
            if not targets:
                logger.info(f"No load balancer targets found for {instance_name}")
                return
                
            load_balancers = set()
            
            for target in targets:
                logger.info(f"Removing {instance_name} from load balancer {target.load_balancer_id}")
                load_balancers.add(target.load_balancer_id)
                self.session.delete(target)
                
            self.session.commit()
            logger.info(f"Successfully removed {instance_name} from all load balancers")
            
            # Update the load balancer configuration
            for lb_id in load_balancers:
                try:
                    # Get the load balancer
                    lb = self.session.query(LoadBalancer).filter(
                        LoadBalancer.id == lb_id
                    ).first()
                    
                    if not lb:
                        continue
                        
                    # Get the load balancer service
                    from app.services.loadbalancer import LoadBalancerService
                    lb_service = LoadBalancerService()
                    
                    # Get lb container
                    lb_container = self.client.instances.get(f"lb-{lb.name}")
                    
                    # Update config based on algorithm
                    if lb.algorithm.startswith('round_robin'):
                        lb_service._update_nginx_config(lb_container, lb)
                    else:
                        lb_service._update_haproxy_config(lb_container, lb)
                except Exception as e:
                    logger.error(f"Error updating load balancer configuration: {str(e)}")
            
        except Exception as e:
            logger.error(f"Error removing {instance_name} from load balancers: {str(e)}")
            # Don't fail the entire operation if load balancer integration fails
            self.session.rollback()
            
    def _get_instance_ip(self, instance_name):
        """Get the IP address of an instance"""
        try:
            instance = self.client.instances.get(instance_name)
            if instance.status != 'Running':
                return None
                
            state = instance.state()
            if state.network and 'eth0' in state.network:
                addresses = state.network['eth0'].get('addresses', [])
                for addr in addresses:
                    if addr.get('family') == 'inet':
                        return addr.get('address')
            return None
        except Exception as e:
            logger.error(f"Error getting IP for {instance_name}: {str(e)}")
            return None

@app.task
def execute_scaling_decision(decision):
    """Execute a scaling decision (for Celery worker)"""
    service = LXCScalingService()
    decision = json.loads(decision)
    
    try:
        if decision['action'] == 'scale_up':
            success = service.scale_up(
                decision['instance_name'],
                decision['params'].get('count', 1)
            )
        elif decision['action'] == 'scale_down':
            success = service.scale_down(
                decision['instance_name'],
                decision['params'].get('count', 1)
            )
        elif decision['action'] == 'resize':
            success = service.resize_instance(
                decision['instance_name'],
                decision['params']
            )
        else:
            success = False
            
        return {'success': success, 'decision': decision}
    except Exception as e:
        logger.error(f"Error executing scaling decision: {str(e)}")
        return {'success': False, 'error': str(e)}
