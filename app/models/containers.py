from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
import json

Base = declarative_base()

class Container(Base):
    __tablename__ = 'containers'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, nullable=False)
    status = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ScalingHistory(Base):
    __tablename__ = 'scaling_history'
    
    id = Column(Integer, primary_key=True)
    container_name = Column(String(255), nullable=False)
    action = Column(String(50), nullable=False)
    reason = Column(Text)
    parameters = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)