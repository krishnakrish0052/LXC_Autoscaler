# app/models/lxc_profile.py
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, JSON, Boolean
from sqlalchemy.orm import relationship
from .base import Base

class LXCProfile(Base):
    __tablename__ = 'lxc_profiles'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    config = Column(JSON, nullable=True)  # Store profile config as JSON
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<LXCProfile(name='{self.name}')>"
        
class LoadBalancerConfig(Base):
    __tablename__ = 'load_balancer_configs'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    container_image = Column(String(255), default="ubuntu:20.04")
    static_ip = Column(String(255), nullable=True)
    network_bridge = Column(String(255), default="lxdbr0")
    port = Column(Integer, default=80)
    algorithm = Column(String(50), default='round_robin')  # round_robin, least_connections, ip_hash
    configuration = Column(JSON, nullable=True)  # Nginx/HAProxy config options
    is_active = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<LoadBalancerConfig(name='{self.name}', ip='{self.static_ip}')>"
