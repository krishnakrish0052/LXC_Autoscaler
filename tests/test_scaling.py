import pytest
from unittest.mock import MagicMock, patch
from app.core.scaling import LXCManager

@pytest.fixture
def mock_lxd_client():
    with patch('pylxd.Client') as mock:
        yield mock

@pytest.fixture
def mock_db_session():
    with patch('app.utils.helpers.get_db_session') as mock:
        session = MagicMock()
        mock.return_value = session
        yield session

def test_scale_up(mock_lxd_client, mock_db_session):
    manager = LXCManager()
    
    # Mock container
    mock_container = MagicMock()
    mock_container.name = 'test-container'
    mock_container.status = 'Running'
    mock_container.config = {'limits': {}}
    mock_container.devices = {}
    mock_container.profiles = ['default']
    
    mock_lxd_client.return_value.containers.get.return_value = mock_container
    mock_lxd_client.return_value.containers.create.return_value = MagicMock()
    
    result = manager.scale_up('test-container', 1)
    assert result is True
    mock_lxd_client.return_value.containers.create.assert_called_once()
    mock_db_session.add.assert_called_once()

def test_scale_down(mock_lxd_client, mock_db_session):
    manager = LXCManager()
    
    # Mock containers
    mock_container1 = MagicMock()
    mock_container1.name = 'test-container-1'
    mock_container1.status = 'Running'
    
    mock_container2 = MagicMock()
    mock_container2.name = 'test-container-2'
    mock_container2.status = 'Running'
    
    mock_lxd_client.return_value.containers.all.return_value = [mock_container1, mock_container2]
    
    result = manager.scale_down('test-container', 1)
    assert result is True
    mock_container2.stop.assert_called_once()
    mock_container2.delete.assert_called_once()