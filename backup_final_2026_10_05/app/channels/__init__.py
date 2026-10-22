"""
Channel abstraction layer for social commerce.
This package contains the channel-agnostic interfaces and router.
Platform-specific adapters live in app.channels.adapters.*
"""

from app.channels.base import ChannelAdapter
from app.channels.router import ChannelRouter

__all__ = ["ChannelAdapter", "ChannelRouter"]
