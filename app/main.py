import hashlib
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import Response

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


class TrailingSlashFixMiddleware(BaseHTTPMiddleware):
    """
    Custom middleware to fix 404 errors on POST requests due to trailing slashes.
    
    Meta/Facebook sometimes sends POST requests with a trailing slash (e.g., /webhooks/meta/)
    even if the registered URL doesn't have one. FastAPI's default behavior might reject 
    these as 404 if strict routing is enabled or if there's a proxy conflict.
    
    This middleware strips the trailing slash for specific webhook paths before processing.
    """
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Only target the meta webhook path specifically
        if request.method == "POST" and request.url.path.endswith("/webhooks/meta"):
            # Remove the trailing slash if present
            new_path = request.url.path.rstrip("/")
            
            # Create a modified scope for the downstream application
            scope = dict(request.scope)
            scope["path"] = new_path
            
            # Reconstruct the raw_path if needed by some frameworks
            if "raw_path" in scope:
                scope["raw_path"] = new_path.encode("utf-8")
                
            # Forward the modified request
            return await call_next(Request(scope=scope))
        
        return await call_next(request)


app = FastAPI(
    title="DzCommerce Agent API",
    description="Backend API for the Algerian AI Commerce Agent.",
    version="0.12.1", # Version bumped for critical webhook fix
)

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

# Add the custom middleware LAST so it wraps everything else correctly
# Note: In Starlette/FastAPI, middlewares are executed in reverse order of addition.
# So adding this last means it runs first upon receiving a request.
app.add_middleware(TrailingSlashFixMiddleware)

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


@app.on_event("startup")
def startup_event():
    """Ensure a default store exists on startup to prevent cold-start failures."""
    from app.database import SessionLocal
    from app.models.store import Store
    import logging

    logger = logging.getLogger(__name__)
    db = SessionLocal()
    try:
        store_count = db.query(Store).count()
        if store_count == 0:
            store = Store(
                name="Default Store",
                slug="default-store",
                is_active=True,
                address="Main Branch",
                delivery_policy_text="Standard delivery policy",
                served_wilayas="All",
            )
            db.add(store)
            db.commit()
            logger.info("Auto-created 'Default Store' during startup.")
    except Exception as e:
        db.rollback()
        logger.error("Failed to auto-create default store on startup: %s", str(e))
    finally:
        db.close()
