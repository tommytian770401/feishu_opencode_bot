"""Feishu/Lark channel using WebSocket long connection."""

import asyncio
import json
import os
import re
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

from loguru import logger

from .base_channel import BaseChannel
from .config import FeishuConfig
from .feishu_helpers import (
    _extract_post_content,
    _extract_share_card_content,
)
from .message_bus import OutboundMessage


class FeishuChannel(BaseChannel):
    """
    Feishu/Lark channel using WebSocket long connection.
    
    Uses WebSocket to receive events - no public IP or webhook required.
    
    Requires:
    - App ID and App Secret from Feishu Open Platform
    - Bot capability enabled
    - Event subscription enabled (im.message.receive_v1)
    """
    
    name = "feishu"
    
    def __init__(self, config: FeishuConfig, bus: Any):
        super().__init__(config, bus)
        self.config: FeishuConfig = config
        self._client: Any = None
        self._ws_client: Any = None
        self._ws_thread: threading.Thread | None = None
        self._processed_message_ids: OrderedDict[str, None] = OrderedDict()
        self._loop: asyncio.AbstractEventLoop | None = None
    
    async def start(self) -> None:
        """Start the Feishu bot with WebSocket long connection."""
        try:
            import lark_oapi as lark
        except ImportError:
            logger.error("Feishu SDK not installed. Run: pip install lark-oapi")
            return
        
        if not self.config.app_id or not self.config.app_secret:
            logger.error("Feishu app_id and app_secret not configured")
            return
        
        self._running = True
        self._loop = asyncio.get_running_loop()
        
        # Create Lark client for sending messages (sync client, can be used across threads)
        self._client = lark.Client.builder() \
            .app_id(self.config.app_id) \
            .app_secret(self.config.app_secret) \
            .log_level(lark.LogLevel.INFO) \
            .build()
        
        # Start WebSocket client in a separate thread
        def run_ws():
            """Run WebSocket client in separate thread."""
            import asyncio
            import lark_oapi.ws.client as ws_client_mod  # Access module-level loop
            
            # Create a new event loop for this thread
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            # Override the global loop used by lark-oapi ws client
            ws_client_mod.loop = new_loop
            
            try:
                # lark-oapi types are imported within their respective methods as needed
                event_handler = lark.EventDispatcherHandler.builder(
                    self.config.encrypt_key or "",
                    self.config.verification_token or "",
                ).register_p2_im_message_receive_v1(
                    self._on_message_sync  # Sync callback
                ).build()
                
                ws_client = lark.ws.Client(
                    self.config.app_id,
                    self.config.app_secret,
                    event_handler=event_handler,
                    log_level=lark.LogLevel.INFO
                )
                self._ws_client = ws_client
                
                ws_client.start()
                
            except Exception as e:
                logger.warning("Feishu WebSocket error: {}", e)
        
        self._ws_thread = threading.Thread(target=run_ws, daemon=True)
        self._ws_thread.start()
        
        # 🔍 启动消费出站消息的任务
        self._outbound_consumer_task = asyncio.create_task(self._consume_outbound())
        logger.info("✅ Outbound message consumer started")
        
        logger.info("Feishu bot started with WebSocket long connection")
        logger.info("No public IP required - using WebSocket to receive events")
        
        # Keep running until stopped
        while self._running:
            await asyncio.sleep(1)
        
        # Cancel outbound consumer when stopping
        if self._outbound_consumer_task:
            self._outbound_consumer_task.cancel()
            try:
                await self._outbound_consumer_task
            except asyncio.CancelledError:
                pass
    
    async def stop(self) -> None:
        """
        Stop the Feishu bot.
        
        Notice: lark.ws.Client does not expose stop method, simply exiting the program will close the client.
        
        Reference: https://github.com/larksuite/oapi-sdk-python/blob/v2_main/lark_oapi/ws/client.py#L86
        """
        self._running = False
        logger.info("Feishu bot stopped")
    
    async def _consume_outbound(self) -> None:
        """消费 MessageBus 的出站消息队列，发送到飞书"""
        logger.info("🔄 Starting outbound message consumer...")
        
        while self._running:
            try:
                # 从消息总线获取出站消息（阻塞）
                msg: OutboundMessage = await self.bus.consume_outbound()
                
                # 检查是否应该处理此消息
                if msg.channel != self.name:
                    # 不是发往这个频道的消息，跳过
                    logger.debug(f"Skipping message for channel {msg.channel} (expected {self.name})")
                    continue
                
                # 🔍 调试：打印即将发送的消息
                print(f"\n[{self.name.upper()}] 准备发送消息到飞书:")
                print(f"  接收者类型: {'chat_id' if msg.chat_id.startswith('oc_') else 'open_id'}")
                print(f"  接收者ID: {msg.chat_id}")
                print(f"  内容: {msg.content[:200]}{'...' if len(msg.content) > 200 else ''}")
                print(f"  回复引用: {msg.reply_to or '无'}")
                print(f"  媒体文件: {msg.media}")
                print("-" * 60)
                
                logger.info(f"📤 Sending message to {msg.chat_id} (reply_to={msg.reply_to})")
                
                # 发送消息到飞书
                await self.send(msg)
                
                logger.info(f"✅ Message sent to {msg.chat_id}")
                
            except asyncio.CancelledError:
                logger.info("🛑 Outbound consumer cancelled")
                break
            except Exception as e:
                logger.error(f"❌ Error in outbound consumer: {e}", exc_info=True)
                await asyncio.sleep(1)
    
    def _add_reaction_sync(self, message_id: str, emoji_type: str) -> None:
        """Sync helper for adding reaction (runs in thread pool)."""
        try:
            from lark_oapi.api.im.v1 import CreateMessageReactionRequest, CreateMessageReactionRequestBody, Emoji
            request = CreateMessageReactionRequest.builder() \
                .message_id(message_id) \
                .request_body(
                    CreateMessageReactionRequestBody.builder()
                    .reaction_type(Emoji.builder().emoji_type(emoji_type).build())
                    .build()
                ).build()
            
            response = self._client.im.v1.message_reaction.create(request)
            
            if not response.success():
                logger.warning("Failed to add reaction: code={}, msg={}", response.code, response.msg)
            else:
                logger.debug("Added {} reaction to message {}", emoji_type, message_id)
        except Exception as e:
            logger.warning("Error adding reaction: {}", e)
    
    async def _add_reaction(self, message_id: str, emoji_type: str = "THUMBSUP") -> None:
        """
        Add a reaction emoji to a message (non-blocking).
        
        Common emoji types: THUMBSUP, OK, EYES, DONE, OnIt, HEART
        """
        if not self._client:
            return
        
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._add_reaction_sync, message_id, emoji_type)
    
    # Regex to match markdown tables (header + separator + data rows)
    _TABLE_RE = re.compile(
        r"((?:^[ \t]*\|.+\|[ \t]*\n)(?:^[ \t]*\|[-:\s|]+\|[ \t]*\n)(?:^[ \t]*\|.+\|[ \t]*\n?)+)",
        re.MULTILINE,
    )
    
    _HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
    
    _CODE_BLOCK_RE = re.compile(r"(```[\s\S]*?```)", re.MULTILINE)
    
    @staticmethod
    def _parse_md_table(table_text: str) -> dict | None:
        """Parse a markdown table into a Feishu table element."""
        lines = [_line.strip() for _line in table_text.strip().split("\n") if _line.strip()]
        if len(lines) < 3:
            return None
        def split(_line: str) -> list[str]:
            return [c.strip() for c in _line.strip("|").split("|")]
        headers = split(lines[0])
        rows = [split(_line) for _line in lines[2:]]
        columns = [{"tag": "column", "name": f"c{i}", "display_name": h, "width": "auto"}
                   for i, h in enumerate(headers)]
        return {
            "tag": "table",
            "page_size": len(rows) + 1,
            "columns": columns,
            "rows": [{f"c{i}": r[i] if i < len(r) else "" for i in range(len(headers))} for r in rows],
        }
    
    def _build_card_elements(self, content: str) -> list[dict]:
        """Split content into div/markdown + table elements for Feishu card."""
        elements, last_end = [], 0
        for m in self._TABLE_RE.finditer(content):
            before = content[last_end:m.start()]
            if before.strip():
                elements.extend(self._split_headings(before))
            elements.append(self._parse_md_table(m.group(1)) or {"tag": "markdown", "content": m.group(1)})
            last_end = m.end()
        remaining = content[last_end:]
        if remaining.strip():
            elements.extend(self._split_headings(remaining))
        return elements or [{"tag": "markdown", "content": content}]
    
    def _split_headings(self, content: str) -> list[dict]:
        """Split content by headings, converting headings to div elements."""
        protected = content
        code_blocks = []
        for m in self._CODE_BLOCK_RE.finditer(content):
            code_blocks.append(m.group(1))
            protected = protected.replace(m.group(1), f"\x00CODE{len(code_blocks)-1}\x00", 1)
        
        elements = []
        last_end = 0
        for m in self._HEADING_RE.finditer(protected):
            before = protected[last_end:m.start()].strip()
            if before:
                elements.append({"tag": "markdown", "content": before})
            text = m.group(2).strip()
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**{text}**",
                },
            })
            last_end = m.end()
        remaining = protected[last_end:].strip()
        if remaining:
            elements.append({"tag": "markdown", "content": remaining})
        
        for i, cb in enumerate(code_blocks):
            for el in elements:
                if el.get("tag") == "markdown":
                    el["content"] = el["content"].replace(f"\x00CODE{i}\x00", cb)
        
        return elements or [{"tag": "markdown", "content": content}]
    
    _IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico", ".tiff", ".tif"}
    _AUDIO_EXTS = {".opus"}
    _FILE_TYPE_MAP = {
        ".opus": "opus", ".mp4": "mp4", ".pdf": "pdf", ".doc": "doc", ".docx": "doc",
        ".xls": "xls", ".xlsx": "xls", ".ppt": "ppt", ".pptx": "ppt",
    }
    
    def _upload_image_sync(self, file_path: str) -> str | None:
        """Upload an image to Feishu and return the image_key."""
        try:
            from lark_oapi.api.im.v1 import CreateImageRequest, CreateImageRequestBody
            with open(file_path, "rb") as f:
                request = CreateImageRequest.builder() \
                    .request_body(
                        CreateImageRequestBody.builder()
                        .image_type("message")
                        .image(f)
                        .build()
                    ).build()
                response = self._client.im.v1.image.create(request)
                if response.success():
                    image_key = response.data.image_key
                    logger.debug("Uploaded image {}: {}", os.path.basename(file_path), image_key)
                    return image_key
                else:
                    logger.error("Failed to upload image: code={}, msg={}", response.code, response.msg)
                    return None
        except Exception as e:
            logger.error("Error uploading image {}: {}", file_path, e)
            return None
    
    def _upload_file_sync(self, file_path: str) -> str | None:
        """Upload a file to Feishu and return the file_key."""
        ext = os.path.splitext(file_path)[1].lower()
        file_type = self._FILE_TYPE_MAP.get(ext, "stream")
        file_name = os.path.basename(file_path)
        try:
            from lark_oapi.api.im.v1 import CreateFileRequest, CreateFileRequestBody
            with open(file_path, "rb") as f:
                request = CreateFileRequest.builder() \
                    .request_body(
                        CreateFileRequestBody.builder()
                        .file_type(file_type)
                        .file_name(file_name)
                        .file(f)
                        .build()
                    ).build()
                response = self._client.im.v1.file.create(request)
                if response.success():
                    file_key = response.data.file_key
                    logger.debug("Uploaded file {}: {}", file_name, file_key)
                    return file_key
                else:
                    logger.error("Failed to upload file: code={}, msg={}", response.code, response.msg)
                    return None
        except Exception as e:
            logger.error("Error uploading file {}: {}", file_path, e)
            return None
    
    def _download_image_sync(self, message_id: str, image_key: str) -> tuple[bytes | None, str | None]:
        """Download an image from Feishu message by message_id and image_key."""
        try:
            from lark_oapi.api.im.v1 import GetMessageResourceRequest
            request = GetMessageResourceRequest.builder() \
                .message_id(message_id) \
                .file_key(image_key) \
                .type("image") \
                .build()
            response = self._client.im.v1.message_resource.get(request)
            if response.success():
                file_data = response.file
                if hasattr(file_data, 'read'):
                    file_data = file_data.read()
                return file_data, response.file_name
            else:
                logger.error("Failed to download image: code={}, msg={}", response.code, response.msg)
                return None, None
        except Exception as e:
            logger.error("Error downloading image {}: {}", image_key, e)
            return None, None
    
    def _download_file_sync(
        self, message_id: str, file_key: str, resource_type: str = "file"
    ) -> tuple[bytes | None, str | None]:
        """Download a file/audio/media from a Feishu message by message_id and file_key."""
        try:
            from lark_oapi.api.im.v1 import GetMessageResourceRequest
            request = (
                GetMessageResourceRequest.builder()
                .message_id(message_id)
                .file_key(file_key)
                .type(resource_type)
                .build()
            )
            response = self._client.im.v1.message_resource.get(request)
            if response.success():
                file_data = response.file
                if hasattr(file_data, "read"):
                    file_data = file_data.read()
                return file_data, response.file_name
            else:
                logger.error("Failed to download {}: code={}, msg={}", resource_type, response.code, response.msg)
                return None, None
        except Exception:
            logger.exception("Error downloading {} {}", resource_type, file_key)
            return None, None
    
    async def _download_and_save_media(
        self,
        msg_type: str,
        content_json: dict,
        message_id: str | None = None
    ) -> tuple[str | None, str]:
        """
        Download media from Feishu and save to local disk.
        
        Returns:
            (file_path, content_text) - file_path is None if download failed
        """
        loop = asyncio.get_running_loop()
        media_dir = Path.home() / ".nanobot" / "media"
        media_dir.mkdir(parents=True, exist_ok=True)
        
        data, filename = None, None
        
        if msg_type == "image":
            image_key = content_json.get("image_key")
            if image_key and message_id:
                data, filename = await loop.run_in_executor(
                    None, self._download_image_sync, message_id, image_key
                )
                if not filename:
                    filename = f"{image_key[:16]}.jpg"
        
        elif msg_type in ("audio", "file", "media"):
            file_key = content_json.get("file_key")
            if file_key and message_id:
                data, filename = await loop.run_in_executor(
                    None, self._download_file_sync, message_id, file_key, msg_type
                )
                if not filename:
                    ext = {"audio": ".opus", "media": ".mp4"}.get(msg_type, "")
                    filename = f"{file_key[:16]}{ext}"
        
        if data and filename:
            file_path = media_dir / filename
            file_path.write_bytes(data)
            logger.debug("Downloaded {} to {}", msg_type, file_path)
            return str(file_path), f"[{msg_type}: {filename}]"
        
        return None, f"[{msg_type}: download failed]"
    
    def _send_message_sync(self, receive_id_type: str, receive_id: str, msg_type: str, content: str) -> bool:
        """Send a single message (text/image/file/interactive) synchronously."""
        try:
            from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody
            print(f"\n  [{self.name.upper()}] 调用飞书 API:")
            print(f"    类型: {msg_type}")
            print(f"    receive_id_type: {receive_id_type}")
            print(f"    receive_id: {receive_id}")
            print(f"    内容长度: {len(content)} 字符")
            
            request = CreateMessageRequest.builder() \
                .receive_id_type(receive_id_type) \
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(receive_id)
                    .msg_type(msg_type)
                    .content(content)
                    .build()
                ).build()
            
            print(f"  [{self.name.upper()}] 发送 HTTP 请求...")
            response = self._client.im.v1.message.create(request)
            
            if not response.success():
                logger.error(
                    "❌ Failed to send Feishu {} message: code={}, msg={}, log_id={}",
                    msg_type, response.code, response.msg, response.get_log_id()
                )
                print(f"  ❌ 飞书 API 调用失败:")
                print(f"     code: {response.code}")
                print(f"     msg: {response.msg}")
                print(f"     log_id: {response.get_log_id()}")
                return False
            
            logger.debug("✅ Feishu {} message sent to {}", msg_type, receive_id)
            print(f"  ✅ 飞书 API 调用成功，消息已发送")
            return True
            
        except Exception as e:
            logger.error("❌ Error sending Feishu {} message: {}", msg_type, e)
            print(f"  ❌ 发送消息异常: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through Feishu, including media (images/files) if present."""
        if not self._client:
            logger.warning("❌ Feishu client not initialized")
            return
        
        try:
            receive_id_type = "chat_id" if msg.chat_id.startswith("oc_") else "open_id"
            loop = asyncio.get_running_loop()
            
            print(f"\n[{self.name.upper()}] 调用 send() 方法:")
            print(f"  接收者类型: {receive_id_type}")
            print(f"  接收者ID: {msg.chat_id}")
            print(f"  内容长度: {len(msg.content) if msg.content else 0} 字符")
            print(f"  媒体文件数: {len(msg.media)}")
            
            # 发送媒体文件
            for file_path in msg.media:
                if not os.path.isfile(file_path):
                    logger.warning("⚠️  Media file not found: {}", file_path)
                    continue
                ext = os.path.splitext(file_path)[1].lower()
                if ext in self._IMAGE_EXTS:
                    key = await loop.run_in_executor(None, self._upload_image_sync, file_path)
                    if key:
                        print(f"  ✅ 上传图片成功: {os.path.basename(file_path)} -> {key}")
                        success = await loop.run_in_executor(
                            None, self._send_message_sync,
                            receive_id_type, msg.chat_id, "image", json.dumps({"image_key": key}, ensure_ascii=False),
                        )
                        if success:
                            print(f"  ✅ 发送图片消息成功")
                        else:
                            print(f"  ❌ 发送图片消息失败")
                    else:
                        print(f"  ❌ 上传图片失败: {os.path.basename(file_path)}")
                else:
                    key = await loop.run_in_executor(None, self._upload_file_sync, file_path)
                    if key:
                        media_type = "audio" if ext in self._AUDIO_EXTS else "file"
                        print(f"  ✅ 上传文件成功: {os.path.basename(file_path)} -> {key}")
                        success = await loop.run_in_executor(
                            None, self._send_message_sync,
                            receive_id_type, msg.chat_id, media_type, json.dumps({"file_key": key}, ensure_ascii=False),
                        )
                        if success:
                            print(f"  ✅ 发送文件消息成功")
                        else:
                            print(f"  ❌ 发送文件消息失败")
                    else:
                        print(f"  ❌ 上传文件失败: {os.path.basename(file_path)}")
            
            # 发送文本/卡片消息
            if msg.content and msg.content.strip():
                card = {"config": {"wide_screen_mode": True}, "elements": self._build_card_elements(msg.content)}
                card_json = json.dumps(card, ensure_ascii=False)
                print(f"\n💬 准备发送卡片消息:")
                print(f"  卡片JSON长度: {len(card_json)} 字符")
                print(f"  卡片元素数: {len(card.get('elements', []))}")
                
                success = await loop.run_in_executor(
                    None, self._send_message_sync,
                    receive_id_type, msg.chat_id, "interactive", card_json,
                )
                if success:
                    print(f"  ✅ 卡片消息发送成功")
                else:
                    print(f"  ❌ 卡片消息发送失败")
            else:
                print(f"  ⚠️  无文本内容，跳过发送")
            
        except Exception as e:
            logger.error("❌ Error sending Feishu message: {}", e)
            print(f"\n❌ send() 方法异常: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_message_sync(self, data: Any) -> None:
        """
        Sync handler for incoming messages (called from WebSocket thread).
        Schedules async handling in the main event loop.
        """
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._on_message(data), self._loop)
    
    async def _on_message(self, data: Any) -> None:
        """Handle incoming message from Feishu."""
        try:
            event = data.event
            message = event.message
            sender = event.sender
            
            # Deduplication check
            message_id = message.message_id
            if message_id in self._processed_message_ids:
                return
            self._processed_message_ids[message_id] = None
            
            # Trim cache
            while len(self._processed_message_ids) > 1000:
                self._processed_message_ids.popitem(last=False)
            
            # Skip bot messages
            if sender.sender_type == "bot":
                return
            
            sender_id = sender.sender_id.open_id if sender.sender_id else "unknown"
            chat_id = message.chat_id
            chat_type = message.chat_type
            msg_type = message.message_type
            
            # Add reaction
            await self._add_reaction(message_id, self.config.react_emoji)
            
            # Parse content
            content_parts = []
            media_paths = []
            
            try:
                content_json = json.loads(message.content) if message.content else {}
            except json.JSONDecodeError:
                content_json = {}
            
            if msg_type == "text":
                text = content_json.get("text", "")
                if text:
                    content_parts.append(text)
            
            elif msg_type == "post":
                text, image_keys = _extract_post_content(content_json)
                if text:
                    content_parts.append(text)
                # Download images embedded in post
                for img_key in image_keys:
                    file_path, content_text = await self._download_and_save_media(
                        "image", {"image_key": img_key}, message_id
                    )
                    if file_path:
                        media_paths.append(file_path)
                    content_parts.append(content_text)
            
            elif msg_type in ("image", "audio", "file", "media"):
                file_path, content_text = await self._download_and_save_media(msg_type, content_json, message_id)
                if file_path:
                    media_paths.append(file_path)
                content_parts.append(content_text)
            
            elif msg_type in ("share_chat", "share_user", "interactive", "share_calendar_event", "system", "merge_forward"):
                # Handle share cards and interactive messages
                text = _extract_share_card_content(content_json, msg_type)
                if text:
                    content_parts.append(text)
            
            else:
                MSG_TYPE_MAP = {
                    "image": "[image]",
                    "audio": "[audio]",
                    "file": "[file]",
                    "sticker": "[sticker]",
                }
                content_parts.append(MSG_TYPE_MAP.get(msg_type, f"[{msg_type}]"))
            
            content = "\n".join(content_parts) if content_parts else ""
            
            if not content and not media_paths:
                return
            
            # Forward to message bus
            reply_to = chat_id if chat_type == "group" else sender_id
            await self._handle_message(
                sender_id=sender_id,
                chat_id=reply_to,
                content=content,
                media=media_paths,
                metadata={
                    "message_id": message_id,
                    "chat_type": chat_type,
                    "msg_type": msg_type,
                }
            )
        
        except Exception as e:
            logger.error("Error processing Feishu message: {}", e)
