#!/bin/sh
# Run Alembic migrations then hand off to the CMD.
set -e

echo "Running database migrations..."
for attempt in 1 2 3 4 5; do
    alembic upgrade head && break
    if [ "$attempt" = "5" ]; then
        echo "Migration failed after 5 attempts — aborting." >&2
        exit 1
    fi
    wait=$(( attempt * 3 ))
    echo "Migration attempt $attempt failed, retrying in ${wait}s..."
    sleep "$wait"
done
echo "Migrations complete."

exec "$@"
