#!/bin/bash
set -e
echo "=== Starting prestart.sh ==="
echo "PORT=$PORT"
echo "PWD=$(pwd)"
echo "DATABASE_URL exists: $([ -n "$DATABASE_URL" ] && echo 'YES' || echo 'NO')"
ls -la /app/

# Skip migrations for now - test if gunicorn starts
echo "Starting Gunicorn on port $PORT..."
exec gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w 2 --bind 0.0.0.0:$PORT --timeout 60 --access-logfile - --error-logfile -