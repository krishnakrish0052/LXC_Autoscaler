#!/bin/bash

# Wait for the database to be ready
while ! nc -z $DB_HOST $DB_PORT; do
  sleep 0.1
done

# Initialize the database
python -c "from app.utils.helpers import init_db; init_db()"

# Start the main application
exec "$@"