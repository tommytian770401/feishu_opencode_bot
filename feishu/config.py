"""Feishu/Lark channel configuration using WebSocket long connection."""


class FeishuConfig:
    """Configuration schema for Feishu/Lark integration."""
    
    enabled: bool = False
    app_id: str = ""
    app_secret: str = ""
    encrypt_key: str = ""
    verification_token: str = ""
    allow_from: list[str] = []
    react_emoji: str = "THUMBSUP"
