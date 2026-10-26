#!/bin/bash
echo "Running database migrations..."
# 1. Fix orphaned revision hash in DB
python scripts/fix_alembic_railway.py
# 2. Run migrations
alembic upgrade head
# 3. Ensure/Update Admin user
python scripts/reset_admin_password.py
# 4. Start application
exec gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w 2 --bind 0.0.0.0:$PORT
