from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class ScalingRule(Base):
    __tablename__ = 'scaling_rules'
    
    id = Column(Integer, primary_key=True)
    container_name = Column(String(255), nullable=False)
    metric = Column(String(50), nullable=False)
    threshold = Column(Float, nullable=False)
    action_type = Column(String(50), nullable=False)  # 'horizontal', 'vertical'
    increment = Column(Integer)  # For horizontal scaling
    cpu_increment = Column(String(50))  # e.g., '+1'
    memory_increment = Column(String(50))  # e.g., '+1GB'
    cooldown = Column(Integer, nullable=False)  # in seconds
    created_at = Column(DateTime, default=datetime.utcnow)