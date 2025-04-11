import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta
from app.core.decision import DecisionEngine, ScalingDecision

@pytest.fixture
def mock_db_session():
    with patch('app.utils.helpers.get_db_session') as mock:
        session = MagicMock()
        mock.return_value = session
        yield session

def test_decision_creation():
    decision = ScalingDecision(
        'test-container',
        'scale_up',
        'CPU threshold exceeded',
        {'count': 1}
    )
    assert decision.container_name == 'test-container'
    assert decision.action == 'scale_up'
    assert isinstance(decision.timestamp, datetime)

def test_evaluate_rules_no_action(mock_db_session):
    engine = DecisionEngine()
    metrics = {'container': 'test-container', 'cpu': 50}
    
    # Mock no rules found
    mock_db_session.query.return_value.filter.return_value.all.return_value = []
    
    decision = engine.evaluate_rules(metrics)
    assert decision.action == 'no_action'

def test_evaluate_rules_scale_up(mock_db_session):
    engine = DecisionEngine()
    metrics = {'container': 'test-container', 'cpu': 85}
    
    # Mock a scaling rule
    mock_rule = MagicMock()
    mock_rule.metric = 'cpu'
    mock_rule.threshold = 80
    mock_rule.action_type = 'horizontal'
    mock_rule.increment = 1
    mock_rule.cooldown = 300
    
    mock_db_session.query.return_value.filter.return_value.all.return_value = [mock_rule]
    
    decision = engine.evaluate_rules(metrics)
    assert decision.action == 'scale_up'
    assert decision.params == {'count': 1}