# app/services/metrics.py
import logging
import psutil
import json
import redis
import time
from datetime import datetime, timedelta
import pylxd
from app.utils.helpers import get_db_session, get_redis_connection
from app.models.instances import Instance
from config import Config

logger = logging.getLogger(__name__)

class MetricsService:
    def __init__(self, redis_host=None, redis_port=None):
        self.client = pylxd.Client()
        self.redis = get_redis_connection(
            host=redis_host, 
            port=redis_port
        )
        self.session = get_db_session()
        
    def get_system_metrics(self):
        """Get comprehensive system metrics"""
        try:
            # We're not using instances in this method, so we don't need to query them
            # This avoids potential 'str' object has no attribute 'name' errors
            
            # CPU metrics
            cpu_percent = psutil.cpu_percent(interval=0.1)
            cpu_times = psutil.cpu_times_percent(interval=0.1)
            cpu_count = psutil.cpu_count()
            cpu_freq = psutil.cpu_freq()
            cpu_stats = psutil.cpu_stats()
            
            # Memory metrics
            memory = psutil.virtual_memory()
            swap = psutil.swap_memory()
            
            # Disk metrics
            disk_partitions = []
            for partition in psutil.disk_partitions():
                try:
                    usage = psutil.disk_usage(partition.mountpoint)
                    disk_partitions.append({
                        'device': partition.device,
                        'mountpoint': partition.mountpoint,
                        'fstype': partition.fstype,
                        'total': usage.total,
                        'used': usage.used,
                        'free': usage.free,
                        'percent': usage.percent
                    })
                except PermissionError:
                    # Some mountpoints may require special permissions
                    pass
            
            # Network metrics
            network = {}
            net_io = psutil.net_io_counters(pernic=True)
            for interface, io_stats in net_io.items():
                network[interface] = {
                    'bytes_sent': io_stats.bytes_sent,
                    'bytes_recv': io_stats.bytes_recv,
                    'packets_sent': io_stats.packets_sent,
                    'packets_recv': io_stats.packets_recv,
                    'errin': io_stats.errin,
                    'errout': io_stats.errout,
                    'dropin': io_stats.dropin,
                    'dropout': io_stats.dropout
                }
            
            # Process metrics
            process_count = len(psutil.pids())
            
            # System information
            uname = psutil.os.uname()
            boot_time = datetime.fromtimestamp(psutil.boot_time()).isoformat()
            
            # Combine all metrics
            system_metrics = {
                'timestamp': datetime.utcnow().isoformat(),
                'cpu': {
                    'percent': cpu_percent,
                    'count': cpu_count,
                    'times_percent': {
                        'user': cpu_times.user,
                        'system': cpu_times.system,
                        'idle': cpu_times.idle,
                        'iowait': getattr(cpu_times, 'iowait', 0),
                    },
                    'freq': {
                        'current': cpu_freq.current if cpu_freq else None,
                        'min': cpu_freq.min if cpu_freq else None,
                        'max': cpu_freq.max if cpu_freq else None
                    },
                    'stats': {
                        'ctx_switches': cpu_stats.ctx_switches,
                        'interrupts': cpu_stats.interrupts,
                        'soft_interrupts': cpu_stats.soft_interrupts,
                        'syscalls': getattr(cpu_stats, 'syscalls', 0)
                    }
                },
                'memory': {
                    'total': memory.total,
                    'available': memory.available,
                    'used': memory.used,
                    'percent': memory.percent,
                    'swap': {
                        'total': swap.total,
                        'used': swap.used,
                        'free': swap.free,
                        'percent': swap.percent
                    }
                },
                'disk': {
                    'partitions': disk_partitions,
                    'io_counters': {
                        dev.name: {
                            'read_count': dev.read_count,
                            'write_count': dev.write_count,
                            'read_bytes': dev.read_bytes,
                            'write_bytes': dev.write_bytes,
                            'read_time': dev.read_time,
                            'write_time': dev.write_time
                        } for dev in psutil.disk_io_counters(perdisk=True, nowrap=True)
                    }
                },
                'network': network,
                'process': {
                    'count': process_count
                },
                'system': {
                    'hostname': uname.nodename,
                    'system': uname.sysname,
                    'release': uname.release,
                    'version': uname.version,
                    'machine': uname.machine,
                    'boot_time': boot_time
                }
            }
            
            # Store in Redis with expiration
            self.redis.setex(
                'system:metrics',
                Config.REDIS_METRICS_TTL,
                json.dumps(system_metrics)
            )
            
            return system_metrics
            
        except Exception as e:
            logger.error(f"Error collecting system metrics: {str(e)}")
            return None
            
    def get_instance_metrics(self, instance_name):
        """Get comprehensive metrics for a specific LXC instance"""
        try:
            # Check Redis cache first
            cache_key = f"instance:{instance_name}:metrics"
            cached_metrics = self.redis.get(cache_key)
            
            if cached_metrics:
                return json.loads(cached_metrics)
                
            # Get instance
            instance = self.client.instances.get(instance_name)
            
            if instance.status != 'Running':
                return {
                    'instance': instance_name,
                    'status': instance.status,
                    'timestamp': datetime.utcnow().isoformat(),
                    'error': 'Instance not running'
                }
                
            # Get state information
            state = instance.state()
            
            # Determine instance type
            instance_type = 'container'
            if hasattr(instance, 'type') and instance.type == 'virtual-machine':
                instance_type = 'virtual-machine'
            
            # Build metrics dictionary
            metrics = {
                'instance': instance_name,
                'type': instance_type,
                'status': instance.status,
                'timestamp': datetime.utcnow().isoformat()
            }
            
            # CPU metrics
            if isinstance(state.cpu, dict):
                # Calculate CPU usage percentage
                usage = state.cpu.get('usage', 0)
                system = state.cpu.get('system', 0)
                total = max(usage + system, 1)  # Avoid division by zero
                cpu_percent = min(usage / total * 100, 100)
                
                metrics['cpu'] = {
                    'usage': usage,
                    'percent': round(cpu_percent, 2),
                    'system': system,
                    'cores': state.cpu.get('cores', 0),
                    'limits': {
                        'cpu': instance.config.get('limits.cpu')
                    }
                }
            
            # Memory metrics
            if isinstance(state.memory, dict):
                memory_used = state.memory.get('usage', 0)
                memory_total = state.memory.get('limit', 0)
                
                # Calculate memory percentage
                if memory_total > 0:
                    memory_percent = min(memory_used / memory_total * 100, 100)
                else:
                    memory_percent = 0
                    
                metrics['memory'] = {
                    'usage': memory_used,
                    'total': memory_total,
                    'percent': round(memory_percent, 2),
                    'swap_usage': state.memory.get('swap_usage', 0),
                    'swap_total': state.memory.get('swap_limit', 0)
                }
            
            # Network metrics
            if state.network:
                network_metrics = {}
                
                for iface, stats in state.network.items():
                    if 'counters' in stats:
                        network_metrics[iface] = {
                            'bytes_received': stats['counters'].get('bytes_received', 0),
                            'bytes_sent': stats['counters'].get('bytes_sent', 0),
                            'packets_received': stats['counters'].get('packets_received', 0),
                            'packets_sent': stats['counters'].get('packets_sent', 0),
                            'addresses': stats.get('addresses', [])
                        }
                
                metrics['network'] = network_metrics
            
            # Disk metrics
            if state.disk:
                disk_metrics = {}
                
                for device, stats in state.disk.items():
                    if 'counters' in stats:
                        disk_metrics[device] = {
                            'bytes_read': stats['counters'].get('bytes_read', 0),
                            'bytes_written': stats['counters'].get('bytes_written', 0),
                            'read_operations': stats['counters'].get('read_operations', 0),
                            'write_operations': stats['counters'].get('write_operations', 0)
                        }
                    
                    # Add disk usage if available
                    if 'usage' in stats:
                        disk_metrics[device]['usage'] = stats['usage']
                
                metrics['disk'] = disk_metrics
            
            # Process metrics
            if hasattr(state, 'processes'):
                if isinstance(state.processes, dict):
                    metrics['processes'] = {
                        'count': state.processes.get('count', 0),
                        'fds': state.processes.get('fds', 0),
                        'threads': state.processes.get('threads', 0)
                    }
                elif isinstance(state.processes, int):
                    metrics['processes'] = {
                        'count': state.processes,
                        'fds': None,
                        'threads': None
                    }
            
            # Calculate uptime
            if instance.created_at:
                if isinstance(instance.created_at, str):
                    created_at = datetime.fromisoformat(instance.created_at.replace('Z', '+00:00'))
                else:
                    created_at = instance.created_at
                    
                uptime = (datetime.utcnow() - created_at).total_seconds()
                metrics['uptime'] = uptime
            
            # Store in Redis with expiration
            self.redis.setex(
                cache_key,
                Config.REDIS_METRICS_TTL,
                json.dumps(metrics)
            )
            
            # Store individual metrics for querying
            self.redis.setex(f"instance:{instance_name}:cpu", Config.REDIS_METRICS_TTL, metrics.get('cpu', {}).get('percent', 0))
            self.redis.setex(f"instance:{instance_name}:memory", Config.REDIS_METRICS_TTL, metrics.get('memory', {}).get('percent', 0))
            
            return metrics
            
        except Exception as e:
            logger.error(f"Error collecting metrics for instance {instance_name}: {str(e)}")
            return {
                'instance': instance_name,
                'timestamp': datetime.utcnow().isoformat(),
                'error': str(e)
            }
    
    def get_all_instance_metrics(self):
        """Get metrics for all instances"""
        try:
            all_metrics = []
            
            # First try to get instances from the database
            try:
                db_instances = self.session.query(Instance).all()
                for instance in db_instances:
                    if hasattr(instance, 'name'):
                        metrics = self.get_instance_metrics(instance.name)
                        all_metrics.append(metrics)
            except Exception as db_error:
                logger.warning(f"Error getting instances from database, falling back to LXD: {str(db_error)}")
                # If database fails, fall back to using LXD client
                try:
                    # Get all containers directly instead of instances
                    containers = self.client.containers.all()
                    
                    for container in containers:
                        try:
                            # Use container name directly
                            container_name = container.name
                            metrics = self.get_instance_metrics(container_name)
                            all_metrics.append(metrics)
                        except Exception as container_err:
                            logger.warning(f"Error processing container: {str(container_err)}")
                except Exception as lxd_err:
                    logger.warning(f"Error getting containers from LXD: {str(lxd_err)}")
            
            return all_metrics
            
        except Exception as e:
            logger.error(f"Error collecting metrics for all instances: {str(e)}")
            return []
            
    def get_historical_metrics(self, instance_name, metric_type, hours=24):
        """Get historical metrics for a specific instance and metric type"""
        try:
            # Get historical data from Redis Time Series (if available)
            # or from a database if implemented
            
            # For now, generate synthetic historical data
            end_time = time.time()
            start_time = end_time - hours * 3600
            step = 300  # 5 minutes
            
            datapoints = []
            current_time = start_time
            
            while current_time <= end_time:
                # Generate synthetic data point
                # In a real implementation, this would come from stored metrics
                if metric_type == 'cpu':
                    value = 50 + 30 * ((current_time / 3600) % 24) / 24
                    if current_time % 7200 < 3600:  # Spike every 2 hours
                        value += 20
                elif metric_type == 'memory':
                    value = 40 + 20 * ((current_time / 3600) % 24) / 24
                    if current_time % 14400 < 3600:  # Spike every 4 hours
                        value += 25
                elif metric_type == 'network':
                    value = 30 + 40 * ((current_time / 3600) % 24) / 24
                    if current_time % 10800 < 1800:  # Spike every 3 hours
                        value += 35
                else:
                    value = 20 + 10 * ((current_time / 3600) % 24) / 24
                
                # Add some random variation
                import random
                value += random.uniform(-5, 5)
                value = max(0, min(value, 100))  # Keep between 0-100
                
                datapoints.append({
                    'timestamp': datetime.fromtimestamp(current_time).isoformat(),
                    'value': round(value, 2)
                })
                
                current_time += step
            
            return {
                'instance': instance_name,
                'metric': metric_type,
                'period': f"{hours} hours",
                'datapoints': datapoints
            }
            
        except Exception as e:
            logger.error(f"Error getting historical metrics for {instance_name}: {str(e)}")
            return {
                'instance': instance_name,
                'metric': metric_type,
                'error': str(e)
            }
