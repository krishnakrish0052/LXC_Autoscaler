from app.core.decision import app as decision_app
from app.core.scaling import app as scaling_app
from celery import Celery
from config import Config

app = Celery('mizzle_worker')
app.config_from_object(Config)

if __name__ == '__main__':
    app.start()