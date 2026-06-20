#!/bin/sh
# Run Alembic migrations then hand off to the CMD.
set -e

echo "Running database migrations..."
alembic upgrade head
echo "Migrations complete."

exec "$@"
