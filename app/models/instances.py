# app/models/instances.py
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean
from .base import Base

class Instance(Base):
    __tablename__ = 'instances'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, nullable=False)
    type = Column(String(50), nullable=False)  # 'container' or 'virtual-machine'
    status = Column(String(50))
    image = Column(String(255))
    profile = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    cpu_limit = Column(String(50))
    memory_limit = Column(String(50))
    disk_limit = Column(String(50))
    
    def __repr__(self):
        return f"<Instance(name='{self.name}', type='{self.type}')>"

class ScalingHistory(Base):
    __tablename__ = 'scaling_history'
    __table_args__ = {'extend_existing': True}
    
    id = Column(Integer, primary_key=True)
    instance_name = Column(String(255), nullable=False)
    instance_type = Column(String(50), nullable=False)  # 'container' or 'virtual-machine'
    action = Column(String(50), nullable=False)
    reason = Column(Text)
    parameters = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f"<ScalingHistory(instance='{self.instance_name}', action='{self.action}')>"
