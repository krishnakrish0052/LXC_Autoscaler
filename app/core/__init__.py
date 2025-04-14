# app/core/__init__.py
# Import classes directly without causing circular imports
from .monitor import LXCMonitor
from .decision import DecisionEngine
from .scaling import LXCManager

__all__ = ['LXCMonitor', 'DecisionEngine', 'LXCManager']
