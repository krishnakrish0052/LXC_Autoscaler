#!/usr/bin/env python3
"""
LXC Container Monitoring Agent with Comprehensive Metrics
"""
from datetime import timezone
from dateutil.parser import parse as parse_datetime
import time
import logging
import psutil
import socket
from prometheus_client import start_http_server, Gauge, Counter, Summary, Histogram
import pylxd
from datetime import datetime
import redis
from config import Config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('mizzle-monitor')

class LXCMonitor:
    """Monitor LXC containers and publish comprehensive metrics"""

    def __init__(self, redis_host='localhost', redis_port=6379):
        self.client = pylxd.Client()
        self.prev_net_stats = {}
        self.prev_disk_stats = {}
        self.redis = redis.StrictRedis(
            host=redis_host,
            port=redis_port,
            db=0,
            decode_responses=True
        )

        # System/Node Level Metrics
        self.NODE_CPU_LOAD = Gauge('node_cpu_load', 'System CPU load percentage')
        self.NODE_MEMORY_USAGE = Gauge('node_memory_usage_bytes', 'System memory usage in bytes')
        self.NODE_DISK_USAGE = Gauge('node_disk_usage_bytes', 'System disk usage in bytes', ['device'])
        self.NODE_NETWORK_IN = Counter('node_network_in_bytes_total', 'System network inbound traffic total', ['interface'])
        self.NODE_NETWORK_OUT = Counter('node_network_out_bytes_total', 'System network outbound traffic total', ['interface'])

        # Container Level Metrics
        self.CPU_USAGE = Gauge('lxc_cpu_usage_percent', 'CPU usage percent', ['container_name'])
        self.CPU_LOAD = Gauge('lxc_cpu_load', 'CPU load average', ['container_name'])
        self.MEMORY_USAGE = Gauge('lxc_memory_usage_bytes', 'Memory usage in bytes', ['container_name'])
        self.MEMORY_LIMIT = Gauge('lxc_memory_limit_bytes', 'Memory limit in bytes', ['container_name'])
        self.SWAP_USAGE = Gauge('lxc_swap_usage_bytes', 'Swap usage in bytes', ['container_name'])
        self.DISK_READ = Counter('lxc_disk_read_bytes_total', 'Disk read bytes total', ['container_name', 'device'])
        self.DISK_WRITE = Counter('lxc_disk_write_bytes_total', 'Disk write bytes total', ['container_name', 'device'])
        self.DISK_USAGE = Gauge('lxc_disk_usage_bytes', 'Disk space used', ['container_name', 'mountpoint'])
        self.NETWORK_IN = Counter('lxc_network_in_bytes_total', 'Network inbound traffic total', ['container_name', 'interface'])
        self.NETWORK_OUT = Counter('lxc_network_out_bytes_total', 'Network outbound traffic total', ['container_name', 'interface'])
        self.PROCESS_COUNT = Gauge('lxc_process_count', 'Number of running processes', ['container_name'])
        self.OPEN_FDS = Gauge('lxc_open_fds', 'Number of open file descriptors', ['container_name'])
        self.THREAD_COUNT = Gauge('lxc_thread_count', 'Number of threads', ['container_name'])
        self.UPTIME = Gauge('lxc_uptime_seconds', 'Container uptime in seconds', ['container_name'])

        # Scaling Metrics
        self.SCALING_ACTIONS = Counter('lxc_scaling_actions_total', 'Total scaling actions triggered', ['container_name', 'action_type'])
        self.SCALING_DURATION = Histogram('lxc_scaling_duration_seconds', 'Duration of scaling operations', ['action_type'])
        self.SCALING_ERRORS = Counter('lxc_scaling_errors_total', 'Total scaling errors', ['container_name', 'error_type'])

        # Performance Metrics
        self.REQUEST_LATENCY = Histogram('lxc_request_latency_seconds', 'Request latency')
        self.API_RESPONSE_TIME = Summary('lxc_api_response_time_seconds', 'API response time')

    def collect_node_metrics(self):
        try:
            self.NODE_CPU_LOAD.set(psutil.cpu_percent())
            mem = psutil.virtual_memory()
            self.NODE_MEMORY_USAGE.set(mem.used)

            for part in psutil.disk_partitions():
                if part.fstype:
                    try:
                        usage = psutil.disk_usage(part.mountpoint)
                        self.NODE_DISK_USAGE.labels(device=part.device).set(usage.used)
                    except Exception as e:
                        logger.warning(f"Couldn't collect disk stats for {part.device}: {str(e)}")

            net_io = psutil.net_io_counters(pernic=True)
            for name, stats in net_io.items():
                self.NODE_NETWORK_IN.labels(interface=name).inc(stats.bytes_recv)
                self.NODE_NETWORK_OUT.labels(interface=name).inc(stats.bytes_sent)
        except Exception as e:
            logger.error(f"Node metrics collection failed: {str(e)}")

    def collect_container_metrics(self, container):
        try:
            if container.status != 'Running':
                return

            state = container.state()

            # CPU Metrics
            if isinstance(state.cpu, dict):
                cpu_usage = state.cpu.get('usage', 0) / (state.cpu.get('usage', 0) + 0.1) * 100
                self.CPU_USAGE.labels(container.name).set(cpu_usage)
                self.CPU_LOAD.labels(container.name).set(state.cpu.get('load', 0))
            else:
                logger.warning(f"{container.name}: Unexpected type for state.cpu: {type(state.cpu)}")

            # Memory Metrics
            if isinstance(state.memory, dict):
                self.MEMORY_USAGE.labels(container.name).set(state.memory.get('usage', 0))
                self.MEMORY_LIMIT.labels(container.name).set(state.memory.get('limit', 0))
                self.SWAP_USAGE.labels(container.name).set(state.memory.get('swap_usage', 0))
            else:
                logger.warning(f"{container.name}: Unexpected type for state.memory: {type(state.memory)}")

            # Disk Metrics
            if state.disk:
                for device, stats in state.disk.items():
                    if 'counters' in stats:
                        prev_stats = self.prev_disk_stats.get((container.name, device), {'read': 0, 'write': 0})
                        read_delta = stats['counters']['bytes_read'] - prev_stats['read']
                        write_delta = stats['counters']['bytes_written'] - prev_stats['write']

                        if read_delta > 0:
                            self.DISK_READ.labels(container.name, device).inc(read_delta)
                        if write_delta > 0:
                            self.DISK_WRITE.labels(container.name, device).inc(write_delta)

                        self.prev_disk_stats[(container.name, device)] = {
                            'read': stats['counters']['bytes_read'],
                            'write': stats['counters']['bytes_written']
                        }

            # Network Metrics
            if state.network:
                for iface, stats in state.network.items():
                    if 'counters' in stats:
                        prev_stats = self.prev_net_stats.get((container.name, iface), {'in': 0, 'out': 0})
                        in_delta = stats['counters']['bytes_received'] - prev_stats['in']
                        out_delta = stats['counters']['bytes_sent'] - prev_stats['out']

                        if in_delta > 0:
                            self.NETWORK_IN.labels(container.name, iface).inc(in_delta)
                        if out_delta > 0:
                            self.NETWORK_OUT.labels(container.name, iface).inc(out_delta)

                        self.prev_net_stats[(container.name, iface)] = {
                            'in': stats['counters']['bytes_received'],
                            'out': stats['counters']['bytes_sent']
                        }

            # Process Metrics
            if isinstance(state.processes, dict):
                self.PROCESS_COUNT.labels(container.name).set(state.processes.get('count', 0))
                self.OPEN_FDS.labels(container.name).set(state.processes.get('fds', 0))
                self.THREAD_COUNT.labels(container.name).set(state.processes.get('threads', 0))
            elif isinstance(state.processes, int):
                self.PROCESS_COUNT.labels(container.name).set(state.processes)
            else:
                logger.warning(f"{container.name}: Unexpected type for state.processes: {type(state.processes)}")

            # Uptime
            if container.created_at:
                try:
                    created_at = container.created_at
                    if isinstance(created_at, str):
                        created_at = parse_datetime(created_at)

                    if created_at.tzinfo is not None:
                        created_at = created_at.astimezone(timezone.utc).replace(tzinfo=None)

                    uptime = (datetime.utcnow() - created_at).total_seconds()
                    self.UPTIME.labels(container.name).set(uptime)
                except Exception as e:
                    logger.warning(f"{container.name}: Failed to calculate uptime - {str(e)}")
        except Exception as e:
            logger.error(f"{container.name}: Failed to collect container metrics - {str(e)}")

    def collect_metrics(self):
        try:
            self.collect_node_metrics()
            containers = self.client.containers.all()
            for container in containers:
                self.collect_container_metrics(container)
        except Exception as e:
            logger.error(f"Failed to collect metrics: {str(e)}")

    def is_port_available(self, port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('localhost', port)) != 0

    def run(self, interval=15):
        port = Config.MONITORING_PORT
        max_attempts = 5

        for attempt in range(max_attempts):
            if self.is_port_available(port):
                try:
                    start_http_server(port)
                    logger.info(f"Started monitoring agent on port {port} (interval: {interval}s)")
                    break
                except Exception as e:
                    logger.error(f"Failed to start HTTP server on port {port}: {str(e)}")
            else:
                logger.warning(f"Port {port} is in use, trying alternative")
                port += 1
        else:
            logger.error(f"Could not find available port after {max_attempts} attempts")
            raise RuntimeError("No available ports for monitoring server")

        try:
            while True:
                start_time = time.time()
                self.collect_metrics()
                elapsed = time.time() - start_time
                self.API_RESPONSE_TIME.observe(elapsed)

                sleep_time = interval - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)
        except KeyboardInterrupt:
            logger.info("Shutting down monitoring agent")
        except Exception as e:
            logger.error(f"Fatal error in monitoring agent: {str(e)}")
            raise

def start_monitor():
    monitor = LXCMonitor()
    try:
        monitor.run(interval=Config.MONITORING_INTERVAL)
    except Exception as e:
        logger.error(f"Monitor failed: {str(e)}")

if __name__ == "__main__":
    logger.info("Starting decision engine")
    start_monitor()
