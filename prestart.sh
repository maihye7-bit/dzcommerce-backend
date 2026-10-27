#!/bin/bash
set -e
echo "=== Starting prestart.sh ==="
echo "PORT=$PORT"
echo "DATABASE_URL exists: $([ -n \"$DATABASE_URL\" ] && echo 'YES' || echo 'NO')"
echo "ADMIN_EMAIL exists: $([ -n \"$ADMIN_EMAIL\" ] && echo 'YES' || echo 'NO')"
echo "ADMIN_PASSWORD exists: $([ -n \"$ADMIN_PASSWORD\" ] && echo 'YES' || echo 'NO')"

echo "=== Running database migrations ==="
# 1. Fix orphaned revision hash in DB
echo "Step 1: Fixing alembic revision hash..."
python scripts/fix_alembic_railway.py || { echo "ERROR: fix_alembic_railway.py failed"; exit 1; }

# 2. Run migrations
echo "Step 2: Running alembic upgrade head..."
alembic upgrade head || { echo "ERROR: alembic upgrade head failed"; exit 1; }

# 3. Ensure/Update Admin user
echo "Step 3: Setting up admin user..."
python scripts/reset_admin_password.py || { echo "ERROR: reset_admin_password.py failed"; exit 1; }

# 4. Start application
# Railway injects PORT dynamically; no fallback to avoid binding to wrong port
echo "Step 4: Starting Gunicorn on port $PORT..."
exec gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w 2 --bind 0.0.0.0:$PORT
