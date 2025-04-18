# app/services/loadbalancer.py
import logging
import pylxd
import json
import os
import tempfile
import time
from datetime import datetime
from sqlalchemy import exc
from app.models.lxc_profile import LoadBalancerConfig
from app.models.loadbalancer import LoadBalancer, LoadBalancerTarget
from app.utils.helpers import get_db_session

logger = logging.getLogger(__name__)

class LoadBalancerService:
    def __init__(self):
        self.client = pylxd.Client()
        self.session = get_db_session()
        
    def create_load_balancer(self, config_id):
        """
        Create a new load balancer container with a static IP based on the provided configuration
        """
        try:
            # Get the load balancer configuration
            lb_config = self.session.query(LoadBalancerConfig).filter(
                LoadBalancerConfig.id == config_id
            ).first()
            
            if not lb_config:
                logger.error(f"Load balancer configuration {config_id} not found")
                return None
                
            # Create a profile for the load balancer with a static IP
            profile_name = f"lb-profile-{lb_config.name}"
            profile_config = {
                "name": profile_name,
                "description": f"Profile for load balancer {lb_config.name}",
                "config": {
                    "user.description": f"Load balancer for {lb_config.name}"
                },
                "devices": {
                    "eth0": {
                        "name": "eth0",
                        "nictype": "bridged",
                        "parent": lb_config.network_bridge,
                        "type": "nic",
                        "ipv4.address": lb_config.static_ip
                    }
                }
            }
            
            # Check if profile already exists, delete if it does
            try:
                existing_profile = self.client.profiles.get(profile_name)
                existing_profile.delete()
                logger.info(f"Deleted existing profile {profile_name}")
            except pylxd.exceptions.NotFound:
                pass
                
            # Create the profile
            self.client.profiles.create(
                profile_name,
                config=profile_config.get("config", {}),
                devices=profile_config.get("devices", {})
            )
            logger.info(f"Created profile {profile_name} with static IP {lb_config.static_ip}")
            
            # Create the load balancer container
            container_name = f"lb-{lb_config.name}"
            
            # Check if container already exists
            try:
                existing_container = self.client.containers.get(container_name)
                existing_container.stop(wait=True)
                existing_container.delete(wait=True)
                logger.info(f"Deleted existing container {container_name}")
            except pylxd.exceptions.NotFound:
                pass
                
            # Create the container
            config = {
                "name": container_name,
                "source": {
                    "type": "image",
                    "alias": lb_config.container_image
                },
                "profiles": ["default", profile_name]
            }
            
            container = self.client.containers.create(config, wait=True)
            container.start(wait=True)
            logger.info(f"Created and started load balancer container {container_name}")
            
            # Wait for the container to get an IP
            max_attempts = 30
            for attempt in range(max_attempts):
                container = self.client.containers.get(container_name)
                state = container.state()
                if state.network and 'eth0' in state.network:
                    addresses = state.network['eth0'].get('addresses', [])
                    for addr in addresses:
                        if addr.get('family') == 'inet':
                            ip_address = addr.get('address')
                            if ip_address:
                                logger.info(f"Load balancer container {container_name} has IP {ip_address}")
                                break
                    if ip_address:
                        break
                        
                time.sleep(1)
            
            if not ip_address:
                logger.error(f"Failed to get IP address for container {container_name}")
                container.stop(wait=True)
                container.delete(wait=True)
                return None
                
            # Configure the load balancer software (Nginx, HAProxy, etc.)
            if lb_config.algorithm == 'round_robin':
                self._configure_nginx_lb(container, lb_config)
            else:
                self._configure_haproxy_lb(container, lb_config)
                
            # Create database entry for the load balancer
            load_balancer = LoadBalancer(
                name=lb_config.name,
                port=lb_config.port,
                algorithm=lb_config.algorithm,
                status='active',
                description=lb_config.description
            )
            
            self.session.add(load_balancer)
            self.session.commit()
            
            return load_balancer
            
        except Exception as e:
            logger.error(f"Error creating load balancer: {str(e)}")
            self.session.rollback()
            return None
            
    def _configure_nginx_lb(self, container, lb_config):
        """Configure Nginx as a load balancer"""
        try:
            # Install Nginx if not already installed
            exit_code, stdout, stderr = container.execute([
                'sh', '-c', 
                'which nginx || (apt-get update && apt-get install -y nginx)'
            ])
            
            if exit_code != 0:
                logger.error(f"Failed to install Nginx: {stderr}")
                return False
                
            # Create a basic Nginx configuration
            nginx_config = f"""
            upstream backend {{
                # Backend servers will be added dynamically
                server 127.0.0.1:8080 down; # Placeholder
            }}

            server {{
                listen {lb_config.port};
                server_name _;

                location / {{
                    proxy_pass http://backend;
                    proxy_set_header Host $host;
                    proxy_set_header X-Real-IP $remote_addr;
                    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
                    proxy_set_header X-Forwarded-Proto $scheme;
                }}
            }}
            """
            
            # Write configuration to a temporary file
            with tempfile.NamedTemporaryFile(mode='w', delete=False) as temp:
                temp.write(nginx_config)
                temp_path = temp.name
                
            # Push the configuration to the container
            with open(temp_path, 'rb') as config_file:
                container.files.put(f'/etc/nginx/conf.d/load-balancer.conf', config_file.read())
                
            # Remove the temporary file
            os.unlink(temp_path)
            
            # Restart Nginx
            container.execute(['systemctl', 'restart', 'nginx'])
            
            logger.info(f"Configured Nginx load balancer on container {container.name}")
            return True
            
        except Exception as e:
            logger.error(f"Error configuring Nginx: {str(e)}")
            return False
            
    def _configure_haproxy_lb(self, container, lb_config):
        """Configure HAProxy as a load balancer"""
        try:
            # Install HAProxy if not already installed
            exit_code, stdout, stderr = container.execute([
                'sh', '-c', 
                'which haproxy || (apt-get update && apt-get install -y haproxy)'
            ])
            
            if exit_code != 0:
                logger.error(f"Failed to install HAProxy: {stderr}")
                return False
                
            # Create a basic HAProxy configuration
            haproxy_config = f"""
            global
                log /dev/log local0
                log /dev/log local1 notice
                daemon

            defaults
                log global
                mode http
                option httplog
                option dontlognull
                timeout connect 5000
                timeout client 50000
                timeout server 50000

            frontend http_front
                bind *:{lb_config.port}
                default_backend http_back

            backend http_back
                balance {lb_config.algorithm}
                # Backend servers will be added dynamically
                server placeholder 127.0.0.1:8080 check disabled
            """
            
            # Write configuration to a temporary file
            with tempfile.NamedTemporaryFile(mode='w', delete=False) as temp:
                temp.write(haproxy_config)
                temp_path = temp.name
                
            # Push the configuration to the container
            with open(temp_path, 'rb') as config_file:
                container.files.put('/etc/haproxy/haproxy.cfg', config_file.read())
                
            # Remove the temporary file
            os.unlink(temp_path)
            
            # Restart HAProxy
            container.execute(['systemctl', 'restart', 'haproxy'])
            
            logger.info(f"Configured HAProxy load balancer on container {container.name}")
            return True
            
        except Exception as e:
            logger.error(f"Error configuring HAProxy: {str(e)}")
            return False
            
    def add_target(self, load_balancer_id, container_name, port=80, weight=1):
        """Add a target container to the load balancer"""
        try:
            # Get the load balancer
            load_balancer = self.session.query(LoadBalancer).filter(
                LoadBalancer.id == load_balancer_id
            ).first()
            
            if not load_balancer:
                logger.error(f"Load balancer {load_balancer_id} not found")
                return False
                
            # Get the target container IP
            container = self.client.containers.get(container_name)
            state = container.state()
            
            ip_address = None
            if state.network and 'eth0' in state.network:
                addresses = state.network['eth0'].get('addresses', [])
                for addr in addresses:
                    if addr.get('family') == 'inet':
                        ip_address = addr.get('address')
                        break
                        
            if not ip_address:
                logger.error(f"Failed to get IP address for container {container_name}")
                return False
                
            # Create database entry for the target
            target = LoadBalancerTarget(
                load_balancer_id=load_balancer_id,
                container_name=container_name,
                ip_address=ip_address,
                port=port,
                weight=weight,
                active=True,
                health_status='healthy'
            )
            
            self.session.add(target)
            self.session.commit()
            
            # Update the load balancer configuration
            lb_container = self.client.containers.get(f"lb-{load_balancer.name}")
            
            if load_balancer.algorithm.startswith('round_robin'):
                self._update_nginx_config(lb_container, load_balancer)
            else:
                self._update_haproxy_config(lb_container, load_balancer)
                
            return True
            
        except Exception as e:
            logger.error(f"Error adding target to load balancer: {str(e)}")
            self.session.rollback()
            return False
            
    def _update_nginx_config(self, container, load_balancer):
        """Update Nginx configuration with new target servers"""
        try:
            # Get all active targets
            targets = self.session.query(LoadBalancerTarget).filter(
                LoadBalancerTarget.load_balancer_id == load_balancer.id,
                LoadBalancerTarget.active == True
            ).all()
            
            # Create the updated upstream block
            upstream_config = "upstream backend {\n"
            for target in targets:
                upstream_config += f"    server {target.ip_address}:{target.port} weight={target.weight};\n"
            upstream_config += "}\n"
            
            # Get the current configuration
            nginx_config = container.files.get('/etc/nginx/conf.d/load-balancer.conf').decode('utf-8')
            
            # Replace the upstream block
            start_index = nginx_config.find('upstream backend {')
            end_index = nginx_config.find('}', start_index) + 1
            
            updated_config = nginx_config[:start_index] + upstream_config + nginx_config[end_index:]
            
            # Write configuration to a temporary file
            with tempfile.NamedTemporaryFile(mode='w', delete=False) as temp:
                temp.write(updated_config)
                temp_path = temp.name
                
            # Push the configuration to the container
            with open(temp_path, 'rb') as config_file:
                container.files.put('/etc/nginx/conf.d/load-balancer.conf', config_file.read())
                
            # Remove the temporary file
            os.unlink(temp_path)
            
            # Restart Nginx
            container.execute(['nginx', '-s', 'reload'])
            
            logger.info(f"Updated Nginx configuration with {len(targets)} targets")
            return True
            
        except Exception as e:
            logger.error(f"Error updating Nginx configuration: {str(e)}")
            return False
            
    def _update_haproxy_config(self, container, load_balancer):
        """Update HAProxy configuration with new target servers"""
        try:
            # Get all active targets
            targets = self.session.query(LoadBalancerTarget).filter(
                LoadBalancerTarget.load_balancer_id == load_balancer.id,
                LoadBalancerTarget.active == True
            ).all()
            
            # Get the current configuration
            haproxy_config = container.files.get('/etc/haproxy/haproxy.cfg').decode('utf-8')
            
            # Find the backend section
            backend_start = haproxy_config.find('backend http_back')
            backend_end = haproxy_config.find('\n\n', backend_start)
            if backend_end == -1:
                backend_end = len(haproxy_config)
                
            # Extract the backend header
            backend_header = haproxy_config[backend_start:haproxy_config.find('\n', backend_start) + 1]
            
            # Build the new backend section
            new_backend = backend_header
            new_backend += f"    balance {load_balancer.algorithm}\n"
            for i, target in enumerate(targets):
                new_backend += f"    server s{i} {target.ip_address}:{target.port} weight {target.weight} check\n"
                
            # Replace the backend section
            updated_config = haproxy_config[:backend_start] + new_backend + haproxy_config[backend_end:]
            
            # Write configuration to a temporary file
            with tempfile.NamedTemporaryFile(mode='w', delete=False) as temp:
                temp.write(updated_config)
                temp_path = temp.name
                
            # Push the configuration to the container
            with open(temp_path, 'rb') as config_file:
                container.files.put('/etc/haproxy/haproxy.cfg', config_file.read())
                
            # Remove the temporary file
            os.unlink(temp_path)
            
            # Restart HAProxy
            container.execute(['systemctl', 'restart', 'haproxy'])
            
            logger.info(f"Updated HAProxy configuration with {len(targets)} targets")
            return True
            
        except Exception as e:
            logger.error(f"Error updating HAProxy configuration: {str(e)}")
            return False
