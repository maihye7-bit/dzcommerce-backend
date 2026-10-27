# ---- Build Stage ----
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

# No CMD here – railway.json controls startup via prestart.sh