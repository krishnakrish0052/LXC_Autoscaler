# LXC Autoscaler

A comprehensive monitoring and auto-scaling solution for LXD containers and virtual machines with both horizontal and vertical scaling capabilities.

## Main Features

- **Real-time Monitoring**: Track CPU, memory, disk, and network usage metrics for all LXC containers and VMs
- **Auto-scaling**: Define custom scaling rules based on resource utilization thresholds
- **Horizontal Scaling**: Add or remove container instances based on load
- **Vertical Scaling**: Resize existing instances by adjusting CPU or memory limits
- **Load Balancing**: Distribute traffic across multiple containers
- **Web Dashboard**: Visualize system and container metrics through an intuitive web interface
- **REST API**: Programmatically manage containers, scaling rules, and load balancers
- **Predictive Scaling**: Anticipate load increases based on historical patterns
- **Fallback Mechanisms**: Resilient operation when Redis or database services are unavailable

## Components

1. **Monitoring Service**: Collects metrics from containers and the host system
2. **Decision Engine**: Evaluates scaling rules and triggers appropriate actions
3. **Web Dashboard**: Provides a UI for monitoring and management
4. **API Server**: Offers RESTful endpoints for automation
5. **Load Balancer Manager**: Configures and manages the load distribution

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

### Troubleshooting

#### Database Issues

If you see "relation does not exist" errors:

1. Make sure your database is properly configured in `.env`:
   ```
   DATABASE_URL=postgresql://username:password@localhost/dbname
   ```

2. Run the database setup utility:
   ```
   ./db_setup.py
   ```
   This will create missing tables and fix common database issues.

3. Manually run migrations:
   ```
   alembic upgrade head
   ```

#### Redis Issues

If you encounter Redis authentication errors:

1. Run the Redis configuration utility:
   ```
   ./redis_config.py
   ```
   This will help you find the correct password for your Redis server.

2. Configure Redis to not require authentication:
   - Edit Redis config (usually at /etc/redis/redis.conf)
   - Comment out or remove the requirepass line
   - Restart Redis

## Configuration

Copy `.env.example` to `.env` and modify the settings as needed.

## API Documentation

The API is available at `/api` with Swagger documentation at `/apidocs/`.

### Container Management

- `GET /api/containers` - List all containers with metrics
- `GET /api/containers/{name}` - Get container details
- `GET /api/containers/{name}/metrics` - Get container metrics
- `POST /api/containers/{name}/{action}` - Perform action (start, stop, restart, delete)
- `GET /api/containers/metrics` - Get metrics for all containers

### Scaling Rules

- `GET /api/scaling-rules` - List all scaling rules
- `POST /api/scaling-rules` - Create new scaling rule
- `GET /api/scaling-rules/{rule_id}` - Get specific rule
- `PUT /api/scaling-rules/{rule_id}` - Update rule
- `DELETE /api/scaling-rules/{rule_id}` - Delete rule

### Scaling History

- `GET /api/scaling-history` - View scaling history

### Load Balancing

- `GET /api/load-balancers` - List all load balancers
- `POST /api/load-balancers` - Create new load balancer
- `GET /api/load-balancers/{lb_id}` - Get load balancer details
- `PUT /api/load-balancers/{lb_id}` - Update load balancer
- `DELETE /api/load-balancers/{lb_id}` - Delete load balancer
- `GET /api/load-balancers/{lb_id}/targets` - List targets
- `POST /api/load-balancers/{lb_id}/targets` - Add target
- `PUT /api/load-balancers/{lb_id}/targets/{target_id}` - Update target
- `DELETE /api/load-balancers/{lb_id}/targets/{target_id}` - Remove target

### Metrics Streaming

- `GET /api/metrics/stream` - SSE stream for real-time metrics updates

## License

Under the Owner Krishna