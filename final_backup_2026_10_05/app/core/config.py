"""
Centralized configuration for the application.
Reads from environment variables with safe defaults.
"""

import os

from dotenv import load_dotenv

# Load .env file from project root (backend directory)
load_dotenv()

# Agent Provider Selection ("mock" or "qwen")
AGENT_PROVIDER = os.getenv("AGENT_PROVIDER", "mock")

# Qwen / DashScope Configuration
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "")
QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen-max")
# DashScope OpenAI-compatible endpoint (International)
QWEN_BASE_URL = os.getenv(
    "QWEN_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
)
QWEN_TIMEOUT = int(os.getenv("QWEN_TIMEOUT", "60"))

# Context Management
QWEN_RECENT_MESSAGES_LIMIT = int(os.getenv("QWEN_RECENT_MESSAGES_LIMIT", "10"))
QWEN_MAX_CONTEXT_TOKENS = int(os.getenv("QWEN_MAX_CONTEXT_TOKENS", "32000"))

# Facebook Integration Placeholders (To be filled in .env when ready)
FACEBOOK_APP_ID = os.getenv("FACEBOOK_APP_ID", "")
FACEBOOK_APP_SECRET = os.getenv("FACEBOOK_APP_SECRET", "")
FACEBOOK_PAGE_ACCESS_TOKEN = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN", "")
FACEBOOK_VERIFY_TOKEN = os.getenv("FACEBOOK_VERIFY_TOKEN", "dzcommerce_default_verify")
