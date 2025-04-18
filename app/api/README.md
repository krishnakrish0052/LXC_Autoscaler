# API Routes Module

This directory contains the API routes for the LXC Autoscaler application.

## Files
- `routes.py` - Main API routes used by the application
- `lastroutes.py` - Legacy routes that are now mounted at a different URL prefix `/api/legacy`
- `metrics_routes.py` - Routes specific to metrics collection and reporting
- `auth.py` - Authentication utilities

## Notes
- Routes in `routes.py` are mounted at `/api/` prefix
- Routes in `lastroutes.py` are mounted at `/api/legacy/` prefix to avoid conflicts
- All primary functionality is in `routes.py` - the legacy routes are provided for backward compatibility

## Fix for Duplicate Rule Creation Issue
The issue where rules were being created twice was caused by two files (`routes.py` and `lastroutes.py`) both defining Blueprints with the same name and similar route handlers.

To fix this issue:
1. We renamed the blueprint in `lastroutes.py` from 'api' to 'legacy_api'
2. We mounted the legacy blueprint at a different URL prefix (`/api/legacy/`)
3. We disabled the POST method for the `/scaling-rules` endpoint in `lastroutes.py`

This solution preserves all routes while preventing duplicate rule creation, ensuring the dashboard continues to work correctly.

## Important Components
- Main API routes in `routes.py` are used by the web interface
- Legacy API routes in `lastroutes.py` are available at the /api/legacy prefix
- Authorization middleware is defined in `auth.py`
- Metrics collection endpoints are in `metrics_routes.py`