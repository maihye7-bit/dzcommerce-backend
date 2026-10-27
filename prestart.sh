#!/bin/bash
set -e
echo "Running database migrations..."
# 1. Fix orphaned revision hash in DB
python scripts/fix_alembic_railway.py
# 2. Run migrations
alembic upgrade head
# 3. Ensure/Update Admin user
python scripts/reset_admin_password.py
# 4. Start application
# Use PORT with fallback for safety
PORT="${PORT:-8080}"
echo "Starting Gunicorn on port $PORT..."
exec gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w 2 --bind 0.0.0.0:$PORT
