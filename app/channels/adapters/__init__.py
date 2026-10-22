"""
Channel adapter implementations.
Mock adapters for testing, real adapters for production.
"""

# Real adapters (production)
from app.channels.adapters.facebook_adapter import FacebookAdapter
from app.channels.adapters.instagram_adapter import InstagramAdapter
# Mock adapters (testing)
from app.channels.adapters.mock_facebook import MockFacebookAdapter
from app.channels.adapters.mock_instagram import MockInstagramAdapter
from app.channels.adapters.mock_whatsapp import MockWhatsAppAdapter
from app.channels.adapters.whatsapp_adapter import WhatsAppAdapter

__all__ = [
    # Mock
    "MockFacebookAdapter",
    "MockInstagramAdapter",
    "MockWhatsAppAdapter",
    # Real
    "FacebookAdapter",
    "InstagramAdapter",
    "WhatsAppAdapter",
]
