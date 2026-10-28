import hashlib
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import Response

# Import all routers including stats and conversations
from app.api import (
    agent,
    auth,
    conversations,
    dashboard,
    inventory,
    orders,
    products,
    stats,
    stores,
    super_admin,
    webhooks,
)

# Initialize Tool Registry at startup
from app.agent.tools import tool_registry
from app.agent.tools.search_products import SearchProductsTool
from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: tools are registered in app/agent/tools/__init__.py
    yield
    # Shutdown: cleanup if needed


app = FastAPI(
    title="DzCommerce API",
    version="1.0.0",
    lifespan=lifespan,
)

# ---- Middleware ----
# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.ENV != "production" else ["https://yourdomain.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Session middleware (for admin dashboard auth)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.JWT_SECRET_KEY,
    https_only=settings.ENV == "production",
    same_site="lax",
)

# ---- API Routes ----
# Health check FIRST - must be before other routes
@app.get("/api/health", tags=["health"])
def health_check():
    return {"status": "ok"}

# Include all API routers
app.include_router(auth.router, prefix="/api")
app.include_router(agent.router, prefix="/api")
app.include_router(conversations.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(inventory.router, prefix="/api")
app.include_router(orders.router, prefix="/api")
app.include_router(products.router, prefix="/api")
app.include_router(stats.router, prefix="/api")
app.include_router(stores.router, prefix="/api")
app.include_router(super_admin.router, prefix="/api")
app.include_router(webhooks.router, prefix="/api")


# ---- Frontend Static Files (built React app) ----
# Path calculation: from app/main.py go to parents[1] (= /backend folder), then add /frontend/dist
main_py_path = Path(__file__).resolve()
backend_folder = main_py_path.parents[1]  # C:\Users\Win10LTSC\Documents\backend
frontend_dist = backend_folder / "frontend" / "dist"

if frontend_dist.exists():
    # Serve static assets (JS, CSS, images) with cache headers
    app.mount(
        "/assets",
        StaticFiles(directory=frontend_dist / "assets"),
        name="assets",
    )

    # Serve other static files (favicon, etc.)
    app.mount(
        "/static",
        StaticFiles(directory=frontend_dist),
        name="static",
    )

    # SPA Fallback: serve index.html for all non-API routes
    # This enables client-side routing (React Router) to work on refresh
    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        # Don't intercept API routes
        if full_path.startswith("api/"):
            return Response(status_code=404)
        
        index_file = frontend_dist / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        return Response(status_code=404, content="Frontend not built. Run 'npm run build' in frontend/")
else:
    @app.get("/{full_path:path}", include_in_schema=False)
    async def frontend_not_built(full_path: str):
        if full_path.startswith("api/"):
            return Response(status_code=404)
        return Response(
            status_code=503,
            content="Frontend not built. Run 'npm run build' in frontend/ or check Docker build.",
        )
