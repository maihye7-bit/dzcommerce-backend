from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
# Import all routers including stats and conversations
from app.api import (agent, auth, conversations, inventory, products, stats,
stores, webhooks)

# Initialize Tool Registry at startup
from app.agent.tools import tool_registry
from app.agent.tools.search_products import SearchProductsTool

app = FastAPI(
    title="DzCommerce Agent API",
    description="Backend API for the Algerian AI Commerce Agent.",
    version="0.12.0", # Updated version for Phase 12-D
)

# Register Tools
_search_tool = SearchProductsTool()
if not tool_registry.get(_search_tool.name):
    tool_registry.register(_search_tool)

# Enable CORS for frontend connection
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Existing Routers
app.include_router(auth.router)
app.include_router(stores.router)
app.include_router(products.router)
app.include_router(inventory.router)
app.include_router(agent.router)
app.include_router(webhooks.router)
app.include_router(stats.router)
app.include_router(conversations.router)

@app.get("/api/health", tags=["health"])
def health_check():
    return {"status": "ok"}
