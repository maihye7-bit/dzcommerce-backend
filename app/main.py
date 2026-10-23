import hashlib
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
# Import all routers including stats and conversations
from app.api import (
    agent,
    auth,
    conversations,
    dashboard,
    dashboard_ui,
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

app = FastAPI(
    title="DzCommerce Agent API",
    description="Backend API for the Algerian AI Commerce Agent.",
    version="0.12.0", # Updated version for Phase 12-D
)

# ✅ تم إضافة هذا السطر هنا لإصلاح مشكلة 404 في Render
app.router.redirect_slashes = False

# Register Tools
_search_tool = SearchProductsTool()
if not tool_registry.get(_search_tool.name):
    tool_registry.register(_search_tool)

# Enable CORS for frontend connection
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
session_secret = hashlib.sha256(
    f"dzcommerce-admin-session:{settings.JWT_SECRET_KEY}".encode("utf-8")
).hexdigest()
app.add_middleware(
    SessionMiddleware,
    secret_key=session_secret,
    session_cookie="dzcommerce_admin",
    max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    same_site="lax",
    https_only=settings.ENV.lower() in {"production", "prod"},
)

# Include Existing Routers
app.include_router(auth.router)
app.include_router(stores.router)
app.include_router(products.router)
app.include_router(inventory.router)
app.include_router(inventory.read_router)
app.include_router(orders.router)
app.include_router(agent.router)
app.include_router(webhooks.router)
app.include_router(stats.router)
app.include_router(conversations.router)
app.include_router(dashboard.router)
app.include_router(dashboard_ui.router)
app.include_router(super_admin.router)
app.mount(
    "/dashboard/static",
    StaticFiles(
        directory=str(Path(__file__).resolve().parents[1] / "static" / "dashboard")
    ),
    name="dashboard-static",
)


@app.get("/api/health", tags=["health"])
def health_check():
    return {"status": "ok"}
