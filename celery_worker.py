from app.core.scaling import app as celery_app
from config import Config

# This makes the Celery app available for the worker
app = celery_app

if __name__ == '__main__':
    app.start()
