# app/models/loadbalancer.py
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, Text
from sqlalchemy.orm import relationship
from .base import Base

class LoadBalancer(Base):
    __tablename__ = 'load_balancers'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, nullable=False)
    algorithm = Column(String(50), default='round_robin')  # round_robin, least_connections, ip_hash
    port = Column(Integer, nullable=False)
    status = Column(String(50), default='inactive')
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    description = Column(Text, nullable=True)
    
    # Relationships
    targets = relationship("LoadBalancerTarget", back_populates="load_balancer", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<LoadBalancer(name='{self.name}', algorithm='{self.algorithm}')>"

class LoadBalancerTarget(Base):
    __tablename__ = 'load_balancer_targets'
    
    id = Column(Integer, primary_key=True)
    load_balancer_id = Column(Integer, ForeignKey('load_balancers.id'), nullable=False)
    container_name = Column(String(255), nullable=False)
    ip_address = Column(String(255), nullable=False)
    port = Column(Integer, nullable=False)
    weight = Column(Integer, default=1)
    active = Column(Boolean, default=True)
    health_status = Column(String(50), default='healthy')
    added_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationship
    load_balancer = relationship("LoadBalancer", back_populates="targets")
    
    def __repr__(self):
        return f"<LoadBalancerTarget(container='{self.container_name}', ip='{self.ip_address}:{self.port}')>"