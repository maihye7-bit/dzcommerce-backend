"""
Enums for social commerce channels and event types.
These are first-class concepts in the channel-agnostic architecture.
"""

import enum


class ChannelType(str, enum.Enum):
    """Supported social commerce channels."""

    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"
    WHATSAPP = "whatsapp"
    API = "api"  # Existing direct API channel


class EventType(str, enum.Enum):
    """Types of inbound events from social platforms."""

    MESSAGE_RECEIVED = "message_received"
    COMMENT_CREATED = "comment_created"


class MessageType(str, enum.Enum):
    """Internal message classification."""

    TEXT = "text"
    COMMENT = "comment"
