#!/usr/bin/env python3
"""
LXC Container Monitoring Agent with Comprehensive Metrics and Redis Storage
"""
from datetime import timezone
from dateutil.parser import parse as parse_datetime
import random

import time
import logging
import psutil
import socket
import json
from prometheus_client import start_http_server, Gauge, Counter, Summary, Histogram
import pylxd
from datetime import datetime
import redis
from config import Config

# Import DB and models
from app.utils.helpers import get_db_session
from app.models.containers import Container

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('mizzle-monitor')

class LXCMonitor:
    """Monitor LXC containers and publish comprehensive metrics to Redis"""

    def __init__(self, redis_host=None, redis_port=None):
        self.client = pylxd.Client()
        self.prev_net_stats = {}
        self.prev_disk_stats = {}

        # Initialize Redis connection with optional password
        redis_params = {
            'host': redis_host or Config.REDIS_HOST,
            'port': redis_port or Config.REDIS_PORT,
            'db': 0,
            'decode_responses': True
        }
        # Only add password if it's not None
        if Config.REDIS_PASSWORD:
            redis_params['password'] = Config.REDIS_PASSWORD
            
        self.redis = redis.StrictRedis(**redis_params)

        # Initialize metrics
        self.NODE_CPU_LOAD = Gauge('node_cpu_load', 'System CPU load percentage')
        self.NODE_MEMORY_USAGE = Gauge('node_memory_usage_bytes', 'System memory usage in bytes')
    def collect_metrics_loop(self, interval=15):
        """Run the monitor to periodically collect container metrics."""
        logger.info(f"Starting metrics collection with {interval} seconds interval.")

        try:
            while True:
                containers = self.client.containers.all()
                for container in containers:
                    metrics = self.collect_container_metrics(container)
                    if metrics:
                        logger.info(f"Collected metrics for {container.name}")

                time.sleep(interval)
        except KeyboardInterrupt:
            logger.info("Monitor stopped by user")
        except Exception as e:
            logger.error(f"Monitor error: {str(e)}")
            raise

    def store_metrics_in_redis(self, container_name, metrics):
        """Store container metrics in Redis with expiration"""
        try:
            metrics_key = f"container:{container_name}:metrics"
            self.redis.setex(
                metrics_key,
                Config.REDIS_METRICS_TTL or 300,
                json.dumps(metrics)
            )
            self.redis.setex(f"container:{container_name}:cpu", Config.REDIS_METRICS_TTL or 300, metrics.get('cpu', 0))
            self.redis.setex(f"container:{container_name}:memory", Config.REDIS_METRICS_TTL or 300, metrics.get('memory', 0))

            # Publish to Redis Pub/Sub
            self.redis.publish('container_metrics', json.dumps({
                'container': container_name,
                'timestamp': datetime.utcnow().isoformat(),
                'metrics': metrics
            }))

        except Exception as e:
            logger.error(f"Failed to store metrics in Redis for {container_name}: {str(e)}")

    def sync_container_to_db(self, container_name, container_status):
        """Ensure container exists in database, create or update as needed"""
        try:
            session = get_db_session()
            existing = session.query(Container).filter(Container.name == container_name).first()

            if existing:
                existing.status = container_status
                existing.updated_at = datetime.utcnow()
            else:
                new_container = Container(
                    name=container_name,
                    status=container_status,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                session.add(new_container)

            session.commit()
        except Exception as db_err:
            logger.error(f"{container_name}: DB sync error - {str(db_err)}")
# Update in app/core/monitor.py - enhance collect_container_metrics method

    def collect_container_metrics(self, container):
        """Collect metrics for a single container and store in Redis"""
        try:
            if container.status != 'Running':
                metrics = {
                    'container': container.name,
                    'timestamp': datetime.utcnow().isoformat(),
                    'status': container.status,
                    'cpu': 0,
                    'memory': 0,
                    'memory_limit': 0
                }
                self.store_metrics_in_redis(container.name, metrics)
                self.sync_container_to_db(container.name, container.status)
                return metrics
    
            state = container.state()
            metrics = {
                'container': container.name,
                'timestamp': datetime.utcnow().isoformat(),
                'status': container.status,
                'cpu': 0,
                'memory': 0,
                'memory_limit': 0,
                'swap': 0,
                'swap_limit': 0,
                'network': {},
                'disk': {},
                'processes': 0,
                'threads': 0,
                'file_descriptors': 0,
                'uptime': 0,
                'cpu_limit': 'Unlimited',
                'storage_limit': 'Unlimited'
            }
    
            # Collect CPU metrics
            if isinstance(state.cpu, dict):
                # Fix CPU calculation to provide realistic values (0-100%)
                cpu_usage = min(
                    state.cpu.get('usage', 0) / 
                    max(state.cpu.get('usage', 0) + state.cpu.get('system', 0) + 1, 1) * 100,
                    100
                )
                metrics['cpu'] = round(cpu_usage, 2)
                
                # Add CPU limit if available
                if 'allowance' in state.cpu:
                    metrics['cpu_limit'] = state.cpu['allowance']
                
                # Add CPU load if available
                if 'load' in state.cpu:
                    metrics['cpu_load'] = state.cpu['load']
    
            # Collect memory metrics
            if isinstance(state.memory, dict):
                metrics['memory'] = state.memory.get('usage', 0)
                metrics['memory_limit'] = state.memory.get('limit', 0)
                metrics['swap'] = state.memory.get('swap_usage', 0)
                metrics['swap_limit'] = state.memory.get('swap_limit', 0)
    
            # Collect disk metrics
            if state.disk:
                for device, stats in state.disk.items():
                    if 'counters' in stats:
                        prev_stats = self.prev_disk_stats.get((container.name, device), {'read': 0, 'write': 0})
                        read_delta = stats['counters']['bytes_read'] - prev_stats['read']
                        write_delta = stats['counters']['bytes_written'] - prev_stats['write']
                        metrics['disk'][device] = {
                            'read': stats['counters']['bytes_read'],
                            'write': stats['counters']['bytes_written'],
                            'read_delta': read_delta,
                            'write_delta': write_delta
                        }
                        self.prev_disk_stats[(container.name, device)] = {
                            'read': stats['counters']['bytes_read'],
                            'write': stats['counters']['bytes_written']
                        }
    
            # Collect network metrics
            if state.network:
                for iface, stats in state.network.items():
                    metrics['network'][iface] = {
                        'addresses': stats.get('addresses', []),
                        'hwaddr': stats.get('hwaddr', ''),
                        'mtu': stats.get('mtu', 0),
                        'state': stats.get('state', '')
                    }
                    
                    if 'counters' in stats:
                        prev_stats = self.prev_net_stats.get((container.name, iface), {'in': 0, 'out': 0})
                        in_delta = stats['counters']['bytes_received'] - prev_stats['in']
                        out_delta = stats['counters']['bytes_sent'] - prev_stats['out']
                        metrics['network'][iface].update({
                            'in': stats['counters']['bytes_received'],
                            'out': stats['counters']['bytes_sent'],
                            'in_delta': in_delta,
                            'out_delta': out_delta,
                            'packets_received': stats['counters'].get('packets_received', 0),
                            'packets_sent': stats['counters'].get('packets_sent', 0)
                        })
                        self.prev_net_stats[(container.name, iface)] = {
                            'in': stats['counters']['bytes_received'],
                            'out': stats['counters']['bytes_sent']
                        }
    
            # Collect process metrics
            if isinstance(state.processes, dict):
                metrics['processes'] = state.processes.get('count', 0)
                metrics['file_descriptors'] = state.processes.get('fds', 0)
                metrics['threads'] = state.processes.get('threads', 0)
            elif isinstance(state.processes, int):
                metrics['processes'] = state.processes
    
            # Calculate uptime
            if container.created_at:
                try:
                    created_at = container.created_at
                    if isinstance(created_at, str):
                        created_at = parse_datetime(created_at)
    
                    if created_at.tzinfo is not None:
                        created_at = created_at.astimezone(timezone.utc).replace(tzinfo=None)
    
                    uptime = (datetime.utcnow() - created_at).total_seconds()
                    metrics['uptime'] = uptime
                except Exception as e:
                    logger.warning(f"{container.name}: Failed to calculate uptime - {str(e)}")
    
            # Store in Redis and DB
            self.store_metrics_in_redis(container.name, metrics)
            self.sync_container_to_db(container.name, container.status)
    
            return metrics
    
        except Exception as e:
            logger.error(f"{container.name}: Failed to collect container metrics - {str(e)}")
            return None

    def run(self, interval=60):
        """Run the monitor to periodically collect container metrics."""
        logger.info(f"Starting monitor with {interval} seconds interval.")

        try:
            while True:
                try:
                    containers = self.client.containers.all()
                    for container in containers:
                        metrics = self.collect_container_metrics(container)
                        if metrics:
                            logger.info(f"Collected metrics for {container.name}")

                    time.sleep(interval)

                except Exception as e:
                    logger.error(f"Monitor error: {str(e)}")
                    time.sleep(interval)
        except KeyboardInterrupt:
            logger.info("Monitor stopped by user")
        except Exception as e:
            logger.error(f"Monitor error: {str(e)}")
            raise
# Entry point
def start_monitor():
    monitor = LXCMonitor()
    try:
        monitor.run(interval=Config.MONITORING_INTERVAL)
    except Exception as e:
        logger.error(f"Monitor failed: {str(e)}")

if __name__ == "__main__":
    logger.info("Starting LXC monitor")
    start_monitor()
