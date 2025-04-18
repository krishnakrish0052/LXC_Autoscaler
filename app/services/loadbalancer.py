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
            
    def add_target(self, load_balancer_id, container_name, port=80, weight=1, use_static_ip=False):
        """
        Add a target container to the load balancer
        
        Args:
            load_balancer_id: ID of the load balancer
            container_name: Name of the container to add
            port: Port number on the container
            weight: Target weight for load balancing
            use_static_ip: If True, assign a static IP to the container
        """
        try:
            # Get the load balancer
            load_balancer = self.session.query(LoadBalancer).filter(
                LoadBalancer.id == load_balancer_id
            ).first()
            
            if not load_balancer:
                logger.error(f"Load balancer {load_balancer_id} not found")
                return False
                
            # Get the target container
            container = self.client.containers.get(container_name)
            
            # If static IP requested, try to assign one
            if use_static_ip:
                ip_address = self._assign_static_ip(container, load_balancer)
                if not ip_address:
                    logger.error(f"Failed to assign static IP to container {container_name}")
                    # Fall back to dynamic IP
                    use_static_ip = False
            
            # If not using static IP, get the container's current IP
            if not use_static_ip:
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
            
    def _assign_static_ip(self, container, load_balancer):
        """
        Assign a static IP to a container by creating/applying an LXC profile
        
        Returns:
            The assigned static IP or None if failed
        """
        try:
            # Get LB config to determine network settings
            lb_config = self.session.query(LoadBalancerConfig).filter(
                LoadBalancerConfig.name == load_balancer.name
            ).first()
            
            if not lb_config:
                logger.error(f"No config found for load balancer {load_balancer.name}")
                return None
                
            # Generate a static IP in the same subnet as the load balancer
            static_ip = self._generate_static_ip(lb_config.static_ip)
            if not static_ip:
                return None
                
            # Create a profile for the container with a static IP
            profile_name = f"lb-target-{container.name}"
            
            # Check if profile already exists, delete if it does
            try:
                existing_profile = self.client.profiles.get(profile_name)
                existing_profile.delete()
                logger.info(f"Deleted existing profile {profile_name}")
            except pylxd.exceptions.NotFound:
                pass
                
            # Create the profile with network config
            profile_config = {
                "name": profile_name,
                "description": f"Profile for load balancer target {container.name}",
                "config": {
                    "user.description": f"Load balancer target for {load_balancer.name}"
                },
                "devices": {
                    "eth0": {
                        "name": "eth0",
                        "nictype": "bridged",
                        "parent": lb_config.network_bridge,
                        "type": "nic",
                        "ipv4.address": static_ip
                    }
                }
            }
            
            # Create the profile
            self.client.profiles.create(
                profile_name,
                config=profile_config.get("config", {}),
                devices=profile_config.get("devices", {})
            )
            logger.info(f"Created profile {profile_name} with static IP {static_ip}")
            
            # Apply the profile to the container
            current_profiles = container.profiles
            if profile_name not in current_profiles:
                container.profiles = current_profiles + [profile_name]
                container.save()
                
            # If container is running, restart to apply network changes
            if container.status == 'Running':
                container.restart(wait=True)
                
            return static_ip
                
        except Exception as e:
            logger.error(f"Error assigning static IP: {str(e)}")
            return None
            
    def _generate_static_ip(self, base_ip):
        """
        Generate a new static IP in the same subnet as the base IP
        
        Args:
            base_ip: The base IP to use for subnet calculation
            
        Returns:
            A new IP address or None if failed
        """
        try:
            # Parse the base IP to get subnet information
            ip_parts = base_ip.split('.')
            if len(ip_parts) != 4:
                return None
                
            # Create a new IP in the same subnet (last octet different)
            from random import randint
            
            # Try up to 100 times to find an unused IP
            for _ in range(100):
                last_octet = randint(10, 250)  # Avoid common gateway IPs
                if last_octet == int(ip_parts[3]):
                    continue  # Skip the base IP
                    
                new_ip = f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}.{last_octet}"
                
                # Check if this IP is in use
                if not self._is_ip_in_use(new_ip):
                    return new_ip
                    
            return None
        except Exception as e:
            logger.error(f"Error generating static IP: {str(e)}")
            return None
            
    def _is_ip_in_use(self, ip_address):
        """
        Check if an IP address is already in use
        
        Args:
            ip_address: The IP address to check
            
        Returns:
            True if in use, False otherwise
        """
        try:
            # Check existing targets
            existing_target = self.session.query(LoadBalancerTarget).filter(
                LoadBalancerTarget.ip_address == ip_address
            ).first()
            
            if existing_target:
                return True
                
            # Check if IP responds to ping
            import subprocess
            
            try:
                result = subprocess.run(
                    ['ping', '-c', '1', '-W', '1', ip_address],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                return result.returncode == 0
            except:
                # If ping fails, assume IP is not in use
                pass
                
            return False
        except Exception as e:
            logger.error(f"Error checking if IP is in use: {str(e)}")
            return True  # Assume in use on error
            
    def add_vm_target(self, load_balancer_id, vm_name, port=80, weight=1, use_static_ip=True):
        """
        Add a virtual machine to the load balancer
        
        Args:
            load_balancer_id: ID of the load balancer
            vm_name: Name of the VM to add
            port: Port number on the VM
            weight: Target weight for load balancing
            use_static_ip: If True, assign a static IP to the VM
        """
        try:
            # Get the load balancer
            load_balancer = self.session.query(LoadBalancer).filter(
                LoadBalancer.id == load_balancer_id
            ).first()
            
            if not load_balancer:
                logger.error(f"Load balancer {load_balancer_id} not found")
                return False
                
            # Get the target VM
            vm = self.client.instances.get(vm_name)
            
            # Check if it's a VM
            if not hasattr(vm, 'type') or vm.type != 'virtual-machine':
                logger.error(f"{vm_name} is not a virtual machine")
                return False
            
            # If static IP requested, try to assign one
            if use_static_ip:
                ip_address = self._assign_static_ip_to_vm(vm, load_balancer)
                if not ip_address:
                    logger.error(f"Failed to assign static IP to VM {vm_name}")
                    # Fall back to dynamic IP
                    use_static_ip = False
            
            # If not using static IP, get the VM's current IP
            if not use_static_ip:
                state = vm.state()
                ip_address = None
                if state.network and 'eth0' in state.network:
                    addresses = state.network['eth0'].get('addresses', [])
                    for addr in addresses:
                        if addr.get('family') == 'inet':
                            ip_address = addr.get('address')
                            break
                            
            if not ip_address:
                logger.error(f"Failed to get IP address for VM {vm_name}")
                return False
                
            # Create database entry for the target
            target = LoadBalancerTarget(
                load_balancer_id=load_balancer_id,
                container_name=vm_name,  # Use the VM name in the container_name field
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
            logger.error(f"Error adding VM target to load balancer: {str(e)}")
            self.session.rollback()
            return False
            
    def _assign_static_ip_to_vm(self, vm, load_balancer):
        """
        Assign a static IP to a VM by creating/applying an LXC profile
        
        Returns:
            The assigned static IP or None if failed
        """
        try:
            # Get LB config to determine network settings
            lb_config = self.session.query(LoadBalancerConfig).filter(
                LoadBalancerConfig.name == load_balancer.name
            ).first()
            
            if not lb_config:
                logger.error(f"No config found for load balancer {load_balancer.name}")
                return None
                
            # Generate a static IP in the same subnet as the load balancer
            static_ip = self._generate_static_ip(lb_config.static_ip)
            if not static_ip:
                return None
                
            # Create a profile for the VM with a static IP
            profile_name = f"lb-vm-target-{vm.name}"
            
            # Check if profile already exists, delete if it does
            try:
                existing_profile = self.client.profiles.get(profile_name)
                existing_profile.delete()
                logger.info(f"Deleted existing profile {profile_name}")
            except pylxd.exceptions.NotFound:
                pass
                
            # Create the profile with network config (for VMs config is slightly different)
            profile_config = {
                "name": profile_name,
                "description": f"Profile for load balancer VM target {vm.name}",
                "config": {
                    "user.description": f"Load balancer VM target for {load_balancer.name}"
                },
                "devices": {
                    "eth0": {
                        "name": "eth0",
                        "nictype": "bridged",
                        "parent": lb_config.network_bridge,
                        "type": "nic",
                        "ipv4.address": static_ip
                    }
                }
            }
            
            # Create the profile
            self.client.profiles.create(
                profile_name,
                config=profile_config.get("config", {}),
                devices=profile_config.get("devices", {})
            )
            logger.info(f"Created profile {profile_name} with static IP {static_ip}")
            
            # Apply the profile to the VM
            current_profiles = vm.profiles
            if profile_name not in current_profiles:
                vm.profiles = current_profiles + [profile_name]
                vm.save()
                
            # If VM is running, restart to apply network changes
            if vm.status == 'Running':
                vm.restart(wait=True)
                
            return static_ip
                
        except Exception as e:
            logger.error(f"Error assigning static IP to VM: {str(e)}")
            return None
            
    def auto_scale_lb_targets(self, container_prefix, min_targets=2, max_targets=5):
        """
        Auto-scale load balancer targets based on container prefix
        
        Args:
            container_prefix: The prefix for containers to add (e.g., 'web-')
            min_targets: Minimum number of targets to maintain
            max_targets: Maximum number of targets to add
        
        Returns:
            Dict with status information
        """
        try:
            # Get all active load balancers
            load_balancers = self.session.query(LoadBalancer).filter(
                LoadBalancer.status == 'active'
            ).all()
            
            results = {}
            
            for lb in load_balancers:
                lb_result = {
                    'name': lb.name,
                    'current_targets': len(lb.targets),
                    'added_targets': 0,
                    'removed_targets': 0,
                    'errors': []
                }
                
                # Count current active targets for this prefix
                active_targets = [t for t in lb.targets 
                               if t.active and t.container_name.startswith(container_prefix)]
                
                current_count = len(active_targets)
                
                # If we need to add more targets
                if current_count < min_targets:
                    # Find all containers with the prefix
                    containers = []
                    try:
                        for c in self.client.containers.all():
                            if c.name.startswith(container_prefix) and c.status == 'Running':
                                # Check if already a target
                                is_target = False
                                for t in lb.targets:
                                    if t.container_name == c.name:
                                        is_target = True
                                        break
                                        
                                if not is_target:
                                    containers.append(c.name)
                    except Exception as e:
                        lb_result['errors'].append(f"Error getting containers: {str(e)}")
                    
                    # Add containers as targets until we reach min_targets
                    to_add = min(min_targets - current_count, len(containers))
                    for i in range(to_add):
                        if i < len(containers):
                            try:
                                if self.add_target(lb.id, containers[i], use_static_ip=True):
                                    lb_result['added_targets'] += 1
                            except Exception as e:
                                lb_result['errors'].append(f"Error adding {containers[i]}: {str(e)}")
                
                # If we need to remove targets (above max_targets)
                elif current_count > max_targets:
                    # Sort targets by health status (remove unhealthy first)
                    targets_to_remove = sorted(
                        active_targets,
                        key=lambda t: 0 if t.health_status == 'healthy' else 1
                    )
                    
                    # Keep only the excess targets
                    targets_to_remove = targets_to_remove[:(current_count - max_targets)]
                    
                    for target in targets_to_remove:
                        try:
                            target.active = False
                            self.session.commit()
                            lb_result['removed_targets'] += 1
                        except Exception as e:
                            lb_result['errors'].append(f"Error removing {target.container_name}: {str(e)}")
                
                # Update load balancer configuration after all changes
                if lb_result['added_targets'] > 0 or lb_result['removed_targets'] > 0:
                    try:
                        lb_container = self.client.containers.get(f"lb-{lb.name}")
                        if lb.algorithm.startswith('round_robin'):
                            self._update_nginx_config(lb_container, lb)
                        else:
                            self._update_haproxy_config(lb_container, lb)
                    except Exception as e:
                        lb_result['errors'].append(f"Error updating LB config: {str(e)}")
                
                results[lb.id] = lb_result
            
            return results
            
        except Exception as e:
            logger.error(f"Error auto-scaling LB targets: {str(e)}")
            return {'error': str(e)}
            
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
