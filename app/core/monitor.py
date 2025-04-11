import time
import psutil
import logging
from prometheus_client import start_http_server, Gauge, Counter
import pylxd
from datetime import datetime
import json
import redis

logger = logging.getLogger(__name__)

class LXCMonitor:
    def __init__(self, redis_host='localhost', redis_port=6379):
        self.client = pylxd.Client()
        self.prev_net_stats = {}
        self.redis = redis.StrictRedis(
            host=redis_host, 
            port=redis_port, 
            db=0,
            decode_responses=True
        )
        
        # Metrics definitions
        self.CPU_USAGE = Gauge(
            'lxc_cpu_usage_percent', 
            'CPU usage percent', 
            ['container_name']
        )
        self.MEMORY_USAGE = Gauge(
            'lxc_memory_usage_bytes', 
            'Memory usage in bytes', 
            ['container_name']
        )
        self.NETWORK_IN = Gauge(
            'lxc_network_in_bytes', 
            'Network inbound traffic', 
            ['container_name']
        )
        self.NETWORK_OUT = Gauge(
            'lxc_network_out_bytes', 
            'Network outbound traffic', 
            ['container_name']
        )
        self.SCALING_ACTIONS = Counter(
            'lxc_scaling_actions_total',
            'Total scaling actions triggered',
            ['container_name', 'action_type']
        )

    def collect_metrics(self):
        for container in self.client.containers.all():
            try:
                if container.status != 'Running':
                    continue
                    
                state = container.state()
                metrics = {
                    'container': container.name,
                    'timestamp': datetime.utcnow().isoformat(),
                    'cpu': 0,
                    'memory': 0,
                    'network_in': 0,
                    'network_out': 0
                }

                # CPU metrics
                if state.cpu:
                    metrics['cpu'] = state.cpu['usage'] / (state.cpu['usage'] + 0.1) * 100
                    self.CPU_USAGE.labels(container.name).set(metrics['cpu'])
                
                # Memory metrics
                if state.memory:
                    metrics['memory'] = state.memory['usage']
                    self.MEMORY_USAGE.labels(container.name).set(metrics['memory'])
                
                # Network metrics
                if state.network:
                    for iface, stats in state.network.items():
                        if 'counters' in stats:
                            if iface in self.prev_net_stats:
                                metrics['network_in'] += stats['counters']['bytes_received'] - self.prev_net_stats[iface]['in']
                                metrics['network_out'] += stats['counters']['bytes_sent'] - self.prev_net_stats[iface]['out']
                            
                            self.prev_net_stats[iface] = {
                                'in': stats['counters']['bytes_received'],
                                'out': stats['counters']['bytes_sent']
                            }
                    
                    self.NETWORK_IN.labels(container.name).set(metrics['network_in'])
                    self.NETWORK_OUT.labels(container.name).set(metrics['network_out'])
                
                # Publish metrics to Redis for decision engine
                self.redis.publish('metrics', json.dumps(metrics))
                
            except Exception as e:
                logger.error(f"Error collecting metrics for {container.name}: {str(e)}")
                continue

    def run(self, interval=15):
        start_http_server(8000)
        logger.info("Monitoring agent started on port 8000")
        while True:
            self.collect_metrics()
            time.sleep(interval)