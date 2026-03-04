"""
Feishu OpenCode Bot Client
Handles communication with both Feishu API and OpenCode Server
"""

import os
import logging
import aiohttp
import json
from typing import Optional, Dict, Any, List
import asyncio
from datetime import datetime, timedelta

from opencode_client import OpenCodeClient

logger = logging.getLogger(__name__)


class FeishuClient:
    """Client for Feishu API interactions"""

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        opencode_client: Optional[OpenCodeClient] = None,
    ):
        self.app_id = app_id
        self.app_secret = app_secret
        self.opencode_client = opencode_client
        self._tenant_access_token: Optional[str] = None
        self._token_expire_time: Optional[datetime] = None
        self.session: Optional[aiohttp.ClientSession] = None

    async def ensure_session(self):
        """Ensure HTTP session is created"""
        if self.session is None:
            self.session = aiohttp.ClientSession()

    async def close(self):
        """Close the HTTP session"""
        if self.session:
            await self.session.close()
            self.session = None

    async def _get_tenant_access_token(self) -> str:
        """Get or refresh tenant access token"""
        if (
            self._tenant_access_token
            and self._token_expire_time
            and datetime.now() < self._token_expire_time
        ):
            return self._tenant_access_token

        await self.ensure_session()

        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        data = {"app_id": self.app_id, "app_secret": self.app_secret}

        async with self.session.post(url, json=data, timeout=aiohttp.ClientTimeout(total=10)) as response:
            if response.status >= 400:
                text = await response.text()
                raise Exception(f"Failed to get tenant token: HTTP {response.status} - {text}")

            result = await response.json()
            if result.get("code") != 0:
                raise Exception(f"Failed to get tenant token: {result.get('msg')}")

            self._tenant_access_token = result.get("tenant_access_token")
            expires_in = result.get("expire", 3600)
            self._token_expire_time = datetime.now() + timedelta(seconds=expires_in - 60)

            return self._tenant_access_token

    async def _ensure_token(self):
        """Ensure we have a valid token"""
        if not self._tenant_access_token:
            await self._get_tenant_access_token()

    async def reply_message(
        self,
        message_id: str,
        content: str,
        msg_type: str = "text",
        mention_user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Reply to a message

        Args:
            message_id: Message ID to reply to
            content: Message content
            msg_type: Message type (text, interactive, etc.)
            mention_user_id: Optional user to mention
        """
        await self._ensure_token()
        await self.ensure_session()

        url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reply"

        if msg_type == "text":
            msg_content = {"text": content}
            if mention_user_id:
                msg_content["text"] = f"<at userId=\"{mention_user_id}\"></at> {content}"
        elif msg_type == "markdown":
            msg_content = {"content": json.dumps({"markdown": {"content": content}})}
        else:
            msg_content = {"text": content}

        headers = {
            "Authorization": f"Bearer {self._tenant_access_token}",
            "Content-Type": "application/json; charset=utf-8",
        }

        data = {"content": json.dumps(msg_content) if msg_type != "text" else msg_content, "msg_type": msg_type}

        async with self.session.post(
            url, json=data, headers=headers, timeout=aiohttp.ClientTimeout(total=30)
        ) as response:
            if response.status >= 400:
                text = await response.text()
                raise Exception(f"Failed to reply message: HTTP {response.status} - {text}")

            result = await response.json()
            if result.get("code") != 0:
                raise Exception(f"Failed to reply message: {result.get('msg')}")

            return result.get("data", {})

    async def send_message(
        self,
        chat_id: str,
        content: str,
        msg_type: str = "text",
        receive_id_type: str = "chat_id",
    ) -> Dict[str, Any]:
        """
        Send a message to a chat

        Args:
            chat_id: Chat ID (group or personal)
            content: Message content
            msg_type: Message type
            receive_id_type: Type of receive_id (chat_id, open_id, user_id)
        """
        await self._ensure_token()
        await self.ensure_session()

        url = "https://open.feishu.cn/open-apis/im/v1/messages"

        if msg_type == "text":
            msg_content = {"text": content}
        elif msg_type == "markdown":
            msg_content = {"content": json.dumps({"markdown": {"content": content}})}
        else:
            msg_content = {"text": content}

        headers = {
            "Authorization": f"Bearer {self._tenant_access_token}",
            "Content-Type": "application/json; charset=utf-8",
        }

        data = {
            "receive_id": chat_id,
            "receive_id_type": receive_id_type,
            "content": json.dumps(msg_content) if msg_type != "text" else msg_content,
            "msg_type": msg_type,
        }

        async with self.session.post(
            url, json=data, headers=headers, timeout=aiohttp.ClientTimeout(total=30)
        ) as response:
            if response.status >= 400:
                text = await response.text()
                raise Exception(f"Failed to send message: HTTP {response.status} - {text}")

            result = await response.json()
            if result.get("code") != 0:
                raise Exception(f"Failed to send message: {result.get('msg')}")

            return result.get("data", {})

    async def get_message(self, message_id: str) -> Dict[str, Any]:
        """Get message details"""
        await self._ensure_token()
        await self.ensure_session()

        url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}"

        headers = {"Authorization": f"Bearer {self._tenant_access_token}"}

        async with self.session.get(
            url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)
        ) as response:
            if response.status >= 400:
                text = await response.text()
                raise Exception(f"Failed to get message: HTTP {response.status} - {text}")

            result = await response.json()
            if result.get("code") != 0:
                raise Exception(f"Failed to get message: {result.get('msg')}")

            return result.get("data", {})

    async def batch_get_user_info(
        self, user_ids: List[str], id_type: str = "open_id"
    ) -> Dict[str, Any]:
        """
        Get user information in batch

        Args:
            user_ids: List of user IDs
            id_type: Type of user ID (open_id, user_id, union_id)
        """
        await self._ensure_token()
        await self.ensure_session()

        url = "https://open.feishu.cn/open-apis/contact/v3/users/batch_get"

        headers = {"Authorization": f"Bearer {self._tenant_access_token}"}

        key = f"{id_type}_ids"
        data = {key: user_ids}

        async with self.session.post(
            url, json=data, headers=headers, timeout=aiohttp.ClientTimeout(total=10)
        ) as response:
            if response.status >= 400:
                text = await response.text()
                raise Exception(f"Failed to get user info: HTTP {response.status} - {text}")

            result = await response.json()
            if result.get("code") != 0:
                raise Exception(f"Failed to get user info: {result.get('msg')}")

            return result.get("data", {})

    async def list_chat_members(
        self, chat_id: str, page_size: int = 100, page_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """List members in a chat"""
        await self._ensure_token()
        await self.ensure_session()

        url = f"https://open.feishu.cn/open-apis/im/v1/chats/{chat_id}/members"

        headers = {"Authorization": f"Bearer {self._tenant_access_token}"}

        params = {"page_size": page_size}
        if page_token:
            params["page_token"] = page_token

        async with self.session.get(
            url, headers=headers, params=params, timeout=aiohttp.ClientTimeout(total=10)
        ) as response:
            if response.status >= 400:
                text = await response.text()
                raise Exception(f"Failed to list chat members: HTTP {response.status} - {text}")

            result = await response.json()
            if result.get("code") != 0:
                raise Exception(f"Failed to list chat members: {result.get('msg')}")

            return result.get("data", {})

    async def get_chat_info(self, chat_id: str) -> Dict[str, Any]:
        """Get chat information"""
        await self._ensure_token()
        await self.ensure_session()

        url = f"https://open.feishu.cn/open-apis/im/v1/chats/{chat_id}"

        headers = {"Authorization": f"Bearer {self._tenant_access_token}"}

        async with self.session.get(
            url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)
        ) as response:
            if response.status >= 400:
                text = await response.text()
                raise Exception(f"Failed to get chat info: HTTP {response.status} - {text}")

            result = await response.json()
            if result.get("code") != 0:
                raise Exception(f"Failed to get chat info: {result.get('msg')}")

            return result.get("data", {})


class FeishuOpenCodeBot:
    """
    Integrated bot that connects Feishu with OpenCode Server
    """

    def __init__(
        self,
        feishu_app_id: str,
        feishu_app_secret: str,
        opencode_server_url: str,
        opencode_username: Optional[str] = None,
        opencode_password: Optional[str] = None,
    ):
        self.feishu_client = FeishuClient(
            app_id=feishu_app_id,
            app_secret=feishu_app_secret,
            opencode_client=OpenCodeClient(
                base_url=opencode_server_url,
                username=opencode_username,
                password=opencode_password,
            ),
        )
        # 用户会话映射：feishu_user_id -> opencode_session_id
        self.user_sessions: Dict[str, str] = {}
        # 会话元数据存储
        self.session_metadata: Dict[str, Dict[str, Any]] = {}

    async def init_user_session(
        self, user_id: str, chat_id: str, session_title: Optional[str] = None
    ) -> str:
        """Initialize or get user's OpenCode session"""
        if user_id in self.user_sessions:
            return self.user_sessions[user_id]

        async with await self._get_opencode_client() as client:
            session = await client.create_session(
                title=session_title or f"Feishu Chat {chat_id}"
            )
            session_id = session.get("id")
            self.user_sessions[user_id] = session_id
            self.session_metadata[session_id] = {
                "user_id": user_id,
                "chat_id": chat_id,
                "created_at": datetime.now(),
                "platform": "feishu",
            }
            return session_id

    async def get_or_create_session(
        self, user_id: str, chat_id: str, title: Optional[str] = None
    ) -> str:
        """Get existing or create new session"""
        return await self.init_user_session(user_id, chat_id, title)

    async def handle_message(
        self,
        message_id: str,
        chat_id: str,
        user_id: str,
        content: str,
        mentions: Optional[List[str]] = None,
    ):
        """
        Handle incoming message from Feishu

        Args:
            message_id: Feishu message ID
            chat_id: Chat ID where message came from
            user_id: Sender user ID
            content: Message text content
            mentions: List of mentioned user IDs
        """
        try:
            # Check for special commands
            if content.startswith("/"):
                await self._handle_command(message_id, chat_id, user_id, content)
                return

            # Get or create session
            session_id = await self.get_or_create_session(user_id, chat_id)

            # Send message to OpenCode
            async with await self._get_opencode_client() as client:
                # 添加平台格式提示
                formatted_content = f"""[飞书对话]
来自用户: {user_id}
聊天群组: {chat_id}
提及: {mentions or '无'}

用户消息:
{content}

请用简洁明了的语言回复，支持Markdown格式。
"""

                result = await client.send_message(
                    session_id=session_id, content=formatted_content
                )

                # 提取回复内容
                response_text = self._extract_response_text(result)

                # 回复用户
                await self.feishu_client.reply_message(
                    message_id=message_id, content=response_text, msg_type="markdown"
                )

        except Exception as e:
            logger.error(f"Error handling message: {e}")
            try:
                await self.feishu_client.reply_message(
                    message_id=message_id,
                    content=f"❌ 处理消息时出错: {str(e)}",
                    msg_type="text",
                )
            except Exception as reply_error:
                logger.error(f"Failed to send error reply: {reply_error}")

    async def _handle_command(
        self, message_id: str, chat_id: str, user_id: str, command: str
    ):
        """Handle bot commands"""
        cmd_parts = command.strip().split()
        cmd = cmd_parts[0].lower()

        if cmd == "/new":
            # Create new session
            title = " ".join(cmd_parts[1:]) if len(cmd_parts) > 1 else None
            if user_id in self.user_sessions:
                del self.user_sessions[user_id]

            session_id = await self.init_user_session(user_id, chat_id, title)
            await self.feishu_client.reply_message(
                message_id=message_id,
                content=f"✅ 已创建新的会话\n🆔 会话ID: {session_id}",
                msg_type="text",
            )

        elif cmd == "/sessions":
            # List sessions
            async with await self._get_opencode_client() as client:
                sessions = await client.list_sessions()
                user_sessions_info = []
                for sess in sessions:
                    sid = sess.get("id")
                    meta = self.session_metadata.get(sid, {})
                    if meta.get("user_id") == user_id:
                        user_sessions_info.append(f"• {sid}: {sess.get('title', '未命名')}")

                text = "📋 你的会话列表:\n" + "\n".join(user_sessions_info)
                await self.feishu_client.reply_message(
                    message_id=message_id, content=text, msg_type="text"
                )

        elif cmd == "/switch":
            # Switch session
            if len(cmd_parts) < 2:
                await self.feishu_client.reply_message(
                    message_id=message_id,
                    content="❌ 请提供会话ID: /switch <session_id>",
                    msg_type="text",
                )
                return

            session_id = cmd_parts[1]
            async with await self._get_opencode_client() as client:
                try:
                    session = await client.get_session(session_id)
                    self.user_sessions[user_id] = session_id
                    await self.feishu_client.reply_message(
                        message_id=message_id,
                        content=f"✅ 已切换到会话: {session.get('title', session_id)}",
                        msg_type="text",
                    )
                except Exception:
                    await self.feishu_client.reply_message(
                        message_id=message_id,
                        content="❌ 会话不存在或无法访问",
                        msg_type="text",
                    )

        elif cmd == "/delete":
            # Delete current session
            if user_id not in self.user_sessions:
                await self.feishu_client.reply_message(
                    message_id=message_id,
                    content="❌ 没有活动的会话",
                    msg_type="text",
                )
                return

            session_id = self.user_sessions[user_id]
            async with await self._get_opencode_client() as client:
                try:
                    await client.delete_session(session_id)
                    del self.user_sessions[user_id]
                    if session_id in self.session_metadata:
                        del self.session_metadata[session_id]
                    await self.feishu_client.reply_message(
                        message_id=message_id,
                        content="✅ 会话已删除",
                        msg_type="text",
                    )
                except Exception as e:
                    await self.feishu_client.reply_message(
                        message_id=message_id,
                        content=f"❌ 删除会话失败: {str(e)}",
                        msg_type="text",
                    )

        elif cmd == "/status":
            # Check server status
            try:
                async with await self._get_opencode_client() as client:
                    health = await client.health_check()
                    status = "✅ 在线" if health.get("status") == "ok" else "⚠️ 异常"
                    await self.feishu_client.reply_message(
                        message_id=message_id,
                        content=f"🖥️ OpenCode Server 状态: {status}\n📍 地址: {client.base_url}",
                        msg_type="text",
                    )
            except Exception as e:
                await self.feishu_client.reply_message(
                    message_id=message_id,
                    content=f"❌ 服务器连接失败: {str(e)}",
                    msg_type="text",
                )

        elif cmd == "/undo":
            # Undo last operation
            if user_id not in self.user_sessions:
                await self.feishu_client.reply_message(
                    message_id=message_id,
                    content="❌ 没有活动的会话",
                    msg_type="text",
                )
                return

            session_id = self.user_sessions[user_id]
            async with await self._get_opencode_client() as client:
                try:
                    messages = await client.list_messages(session_id=session_id, limit=5)
                    assistant_msg = None
                    for msg in reversed(messages):
                        if msg.get("info", {}).get("role") == "assistant":
                            assistant_msg = msg
                            break

                    if assistant_msg:
                        msg_id = assistant_msg.get("info", {}).get("id")
                        await client.revert_message(session_id=session_id, message_id=msg_id)
                        await self.feishu_client.reply_message(
                            message_id=message_id, content="✅ 已撤销上一步操作", msg_type="text"
                        )
                    else:
                        await self.feishu_client.reply_message(
                            message_id=message_id,
                            content="❌ 没有找到可撤销的助手回复",
                            msg_type="text",
                        )
                except Exception as e:
                    await self.feishu_client.reply_message(
                        message_id=message_id,
                        content=f"❌ 撤销失败: {str(e)}",
                        msg_type="text",
                    )

        elif cmd == "/help":
            # Show help
            help_text = """📖 OpenCode 飞书机器人使用指南

🚀 基础命令：
/new [标题] - 创建新会话
/sessions - 查看会话列表
/switch <id> - 切换会话
/delete - 删除当前会话
/status - 查看服务器状态
/undo - 撤销上一步
/help - 显示此帮助

💬 普通对话：
直接发送消息即可与 OpenCode AI 对话

💡 提示：
• 支持代码分析、文件操作等所有 OpenCode 功能
• 回复会包含完整的 Markdown 格式
• 会话绑定到你的用户ID，跨群组可用"""
            await self.feishu_client.reply_message(
                message_id=message_id, content=help_text, msg_type="text"
            )

        else:
            await self.feishu_client.reply_message(
                message_id=message_id,
                content=f"❌ 未知命令: {cmd}\n输入 /help 查看可用命令",
                msg_type="text",
            )

    async def _get_opencode_client(self) -> OpenCodeClient:
        """Get OpenCode client instance"""
        return self.feishu_client.opencode_client

    def _extract_response_text(self, result: Dict[str, Any]) -> str:
        """Extract text from OpenCode response"""
        try:
            parts = result.get("parts", [])
            if parts:
                text_parts = []
                for part in parts:
                    if part.get("type") == "text":
                        text = part.get("content") or part.get("text") or ""
                        text_parts.append(text)
                return "\n".join(text_parts)

            # Fallback: try to find any text-like content
            if "content" in result:
                return str(result["content"])
            if "text" in result:
                return str(result["text"])

            return "无法解析回复内容"
        except Exception as e:
            logger.error(f"Error extracting response: {e}")
            return "解析回复时出错"
