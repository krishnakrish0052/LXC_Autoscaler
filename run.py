from flask import Flask
from app.api.routes import bp as api_bp
from app.core.monitor import LXCMonitor
from app.core.decision import DecisionEngine
import threading
from config import Config

app = Flask(__name__)
app.config.from_object(Config)
app.register_blueprint(api_bp, url_prefix='/api')

def start_monitor():
    monitor = LXCMonitor(
        redis_host=app.config['REDIS_HOST'],
        redis_port=app.config['REDIS_PORT']
    )
    monitor.run(interval=app.config['MONITORING_INTERVAL'])

def start_decision_engine():
    engine = DecisionEngine(
        redis_host=app.config['REDIS_HOST'],
        redis_port=app.config['REDIS_PORT']
    )
    engine.run()

if __name__ == '__main__':
    # Start monitor in background thread
    monitor_thread = threading.Thread(target=start_monitor)
    monitor_thread.daemon = True
    monitor_thread.start()
    
    # Start decision engine in background thread
    decision_thread = threading.Thread(target=start_decision_engine)
    decision_thread.daemon = True
    decision_thread.start()
    
    # Start Flask app
    app.run(host='0.0.0.0', port=5000)