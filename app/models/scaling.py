from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, Text, DateTime
from .base import Base  # ✅ Required for model inheritance

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

    def __repr__(self):
        return f"<ScalingRule(container_name='{self.container_name}', metric='{self.metric}', action='{self.action_type}')>"

class ScalingHistory(Base):
    __tablename__ = 'scaling_history'
    __table_args__ = {'extend_existing': True}  # This allows redefining the table if it already exists

    id = Column(Integer, primary_key=True)
    container_name = Column(String(255), nullable=False)
    action = Column(String(50), nullable=False)  # e.g., 'scale_up', 'scale_down'
    metric = Column(String(50), nullable=True)
    value = Column(Float, nullable=True)
    reason = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<ScalingHistory(container_name='{self.container_name}', action='{self.action}', timestamp='{self.timestamp}')>"
