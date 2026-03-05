"""Feishu/Lark bot module - modular implementation.

Provides complete Feishu/Lark channel integration with message bus decoupling.

Components:
- message_bus: MessageBus, InboundMessage, OutboundMessage
- base_channel: BaseChannel abstract class
- config: FeishuConfig
- feishu_helpers: Content extraction utilities
- feishu_channel: FeishuChannel implementation
"""

from .config import FeishuConfig
from .feishu_channel import FeishuChannel
from .base_channel import BaseChannel
from .message_bus import MessageBus, InboundMessage, OutboundMessage

__all__ = [
    "FeishuChannel",
    "FeishuConfig", 
    "BaseChannel",
    "MessageBus",
    "InboundMessage",
    "OutboundMessage",
]
