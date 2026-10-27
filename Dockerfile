# ---- Build Stage ----
ARG CACHE_BUST=1793121320
FROM node:20-alpine AS frontend-builder
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- Runtime Stage ----
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy Python deps first for cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy compiled frontend assets
COPY --from=frontend-builder /frontend/dist ./frontend/dist

# Copy backend code
COPY . .

EXPOSE 8000

# Use shell form to ensure $PORT is expanded correctly
# Railway injects PORT dynamically; no fallback to prevent binding to wrong port
CMD ["sh", "-c", "gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w 2 --bind 0.0.0.0:$PORT"]