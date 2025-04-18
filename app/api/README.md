# API Routes Module

This directory contains the API routes for the LXC Autoscaler application.

## Files
- `routes.py` - Main API routes used by the application
- `metrics_routes.py` - Routes specific to metrics collection and reporting
- `auth.py` - Authentication utilities

## Notes
- The file `lastroutes.py.bak` is a backup of an older version of the routes and should not be used.
- If rules are being created twice when submitted from the web interface, it's likely due to having both `routes.py` and `lastroutes.py` active at the same time with the same Blueprint name.

## Fix for Duplicate Rule Creation Issue
The issue where rules were being created twice was caused by two files (`routes.py` and `lastroutes.py`) both defining Blueprints with the same name and similar route handlers.

To fix this issue:
1. The file `lastroutes.py` has been renamed to `lastroutes.py.bak` to prevent it from being loaded
2. Only the routes in `routes.py` will now be processed when rules are submitted

If you need to restore the backup, make sure to either:
- Change the Blueprint name in the file to avoid collision
- Remove one of the duplicate route implementations