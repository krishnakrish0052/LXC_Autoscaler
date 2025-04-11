import pytest
from unittest.mock import MagicMock, patch
from app.core.monitor import LXCMonitor

@pytest.fixture
def mock_lxd_client():
    with patch('pylxd.Client') as mock:
        yield mock

@pytest.fixture
def mock_redis():
    with patch('redis.StrictRedis') as mock:
        yield mock

def test_monitor_initialization(mock_lxd_client, mock_redis):
    monitor = LXCMonitor()
    assert monitor is not None
    mock_lxd_client.assert_called_once()
    mock_redis.assert_called_once()

def test_collect_metrics(mock_lxd_client, mock_redis):
    # Setup mock container
    mock_container = MagicMock()
    mock_container.status = 'Running'
    mock_container.name = 'test-container'
    
    mock_state = MagicMock()
    mock_state.cpu = {'usage': 500}
    mock_state.memory = {'usage': 1024 * 1024 * 100}  # 100MB
    mock_state.network = {
        'eth0': {
            'counters': {
                'bytes_received': 1000,
                'bytes_sent': 500
            }
        }
    }
    mock_container.state.return_value = mock_state
    
    mock_lxd_client.return_value.containers.all.return_value = [mock_container]
    
    monitor = LXCMonitor()
    monitor.collect_metrics()
    
    # Verify metrics were collected
    mock_container.state.assert_called_once()
    mock_redis.return_value.publish.assert_called_once()