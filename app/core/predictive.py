import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import RandomForestRegressor
from datetime import datetime, timedelta
import logging
from app.utils.helpers import get_db_session
from app.models.containers import ScalingHistory

logger = logging.getLogger(__name__)

class PredictiveScaler:
    def __init__(self, model_type='linear'):
        self.model_type = model_type
        self.session = get_db_session()
        
    def train_model(self, container_name, metric='cpu', lookback_days=7):
        """Train a predictive model for a container"""
        history = self._get_historical_data(container_name, metric, lookback_days)
        
        if not history or len(history) < 24:  # Need at least 24 data points
            return None
            
        X = np.array([i for i in range(len(history))]).reshape(-1, 1)
        y = np.array([h['value'] for h in history])
        
        if self.model_type == 'linear':
            model = LinearRegression()
        else:
            model = RandomForestRegressor(n_estimators=100)
            
        model.fit(X, y)
        return model
        
    def predict_load(self, container_name, metric='cpu', lookahead=1):
        """Predict future load for a container"""
        model = self.train_model(container_name, metric)
        if not model:
            return None
            
        history = self._get_historical_data(container_name, metric)
        next_point = len(history)
        prediction = model.predict([[next_point + lookahead]])[0]
        
        return max(0, min(100, prediction))  # Clamp between 0-100%
        
    def _get_historical_data(self, container_name, metric, days=7):
        """Get historical metric data for a container"""
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(days=days)
        
        # In a real implementation, query actual metrics database
        # This is a simplified version
        return [
            {'timestamp': start_time + timedelta(hours=i), 'value': i % 80 + 20}
            for i in range(24 * days)
        ]