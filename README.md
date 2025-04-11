# LXC Autoscaler

A comprehensive autoscaling solution for LXC containers and VMs with both horizontal and vertical scaling capabilities.

## Features

- Real-time monitoring of LXC containers and VMs
- Customizable scaling rules based on multiple metrics
- Horizontal scaling (adding/removing instances)
- Vertical scaling (resizing existing instances)
- Predictive scaling based on historical patterns
- Web-based management interface
- REST API for integration

## Installation

### Prerequisites

- Python 3.8+
- LXC/LXD installed and configured
- PostgreSQL database
- Redis server

### Using Docker

1. Clone the repository
2. Run `docker-compose up -d --build`
3. Access the web interface at `http://localhost:5000`

### Manual Installation

1. Clone the repository
2. Create and activate a virtual environment
3. Install dependencies: `pip install -r requirements.txt`
4. Initialize the database: `alembic upgrade head`
5. Start the services:
   - API server: `python run.py`
   - Celery worker: `celery -A celery_worker worker --loglevel=info`

## Configuration

Copy `.env.example` to `.env` and modify the settings as needed.

## API Documentation

The API is available at `/api` with the following endpoints:

- `GET /api/containers` - List all containers
- `GET /api/containers/<name>` - Get container details
- `GET /api/scaling-rules` - List scaling rules
- `POST /api/scaling-rules` - Create new scaling rule
- `GET /api/scaling-history` - View scaling history

## License

Under the Owner Krishna