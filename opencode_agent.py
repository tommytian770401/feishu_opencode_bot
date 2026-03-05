"""
OpenCode Agent - Message processor for OpenCode integration.
订阅消息总线，处理业务逻辑，发布响应。
"""

import asyncio
import json
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime
from dataclasses import dataclass

from opencode_client import OpenCodeClient
from feishu.message_bus import InboundMessage, OutboundMessage, MessageBus

logger = logging.getLogger(__name__)


@dataclass
class SessionMetadata:
    """会话元数据"""
    user_id: str
    chat_id: str
    created_at: datetime
    platform: str = "feishu"
    title: Optional[str] = None


class OpenCodeAgent:
    """
    处理来自 MessageBus 的消息，与 OpenCode 服务器交互。
    
    职责：
    - 订阅 inbound 消息队列
    - 管理用户会话
    - 调用 OpenCode 处理消息
    - 发布响应到 outbound 队列
    """
    
    def __init__(
        self,
        bus: MessageBus,
        opencode_server_url: str,
        opencode_username: Optional[str] = None,
        opencode_password: Optional[str] = None,
    ):
        self.bus = bus
        self.opencode_server_url = opencode_server_url
        self.opencode_username = opencode_username
        self.opencode_password = opencode_password
        
        # 会话管理
        self.user_sessions: Dict[str, str] = {}  # user_id -> session_id
        self.session_metadata: Dict[str, SessionMetadata] = {}
        
        self._running = False
        self._consumer_task: Optional[asyncio.Task] = None
    
    async def start(self) -> None:
        """启动 agent，开始消费消息"""
        self._running = True
        self._consumer_task = asyncio.create_task(self._consume_messages())
        logger.info("OpenCode Agent started")
    
    async def stop(self) -> None:
        """停止 agent"""
        self._running = False
        if self._consumer_task:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
        logger.info("OpenCode Agent stopped")
    
    async def _consume_messages(self) -> None:
        """持续消费 inbound 消息"""
        logger.info("OpenCode Agent consuming messages...")
        
        while self._running:
            try:
                # 获取入站消息（阻塞）
                msg: InboundMessage = await self.bus.consume_inbound()
                
                # 处理消息（不等待）
                asyncio.create_task(self._handle_message(msg))
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in message consumer: {e}")
                await asyncio.sleep(1)
    
    async def _handle_message(self, msg: InboundMessage) -> None:
        """处理单条消息"""
        try:
            logger.info(
                f"Processing message from {msg.sender_id} in {msg.chat_id}: "
                f"{msg.content[:50]}..."
            )
            
            # 检查是否为命令
            if msg.content.startswith("/"):
                await self._handle_command(msg)
                return
            
            # 获取或创建会话
            session_id = await self._get_or_create_session(
                user_id=msg.sender_id,
                chat_id=msg.chat_id,
                platform=msg.channel,
            )
            
            # 调用 OpenCode
            async with self._get_opencode_client() as client:
                # 添加平台上下文
                formatted_content = f"""[{msg.channel.upper()}对话]
来自用户: {msg.sender_id}
聊天ID: {msg.chat_id}

用户消息:
{msg.content}

请用简洁明了的语言回复，支持Markdown格式。
"""
                
                # 🔍 调试：打印发送给 OpenCode 的内容
                print(f"\n[{msg.channel.upper()}] 发送到 OpenCode:")
                print(f"  会话ID: {session_id}")
                print(f"  用户: {msg.sender_id}")
                print(f"  聊天: {msg.chat_id}")
                print(f"  原始消息: {msg.content}")
                print(f"  格式化后:\n{formatted_content}")
                print("-" * 60)
                
                result = await client.send_message(
                    session_id=session_id,
                    content=formatted_content
                )
                
                # 🔍 调试：打印 OpenCode 原始响应
                print(f"\n[{msg.channel.upper()}] OpenCode 原始响应:")
                print(json.dumps(result, ensure_ascii=False, indent=2))
                print("-" * 60)
                
                # 提取回复
                response_text = self._extract_response_text(result)
                
                # 🔍 调试：打印提取的回复
                print(f"\n[{msg.channel.upper()}] 提取的回复文本:")
                print(f"  {response_text}")
                print("=" * 60)
                
                # 发布出站消息
                reply_msg = OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=response_text,
                    reply_to=msg.metadata.get("message_id"),
                    media=msg.media,  # 可以携带媒体文件
                    metadata={"session_id": session_id},
                )
                
                await self.bus.publish_outbound(reply_msg)
                logger.debug(f"Published response to {msg.chat_id}")
        
        except Exception as e:
            logger.error(f"Error handling message: {e}", exc_info=True)
            # 发送错误提示
            try:
                error_msg = OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=f"❌ 处理消息时出错: {str(e)}",
                    reply_to=msg.metadata.get("message_id"),
                )
                await self.bus.publish_outbound(error_msg)
            except Exception as reply_err:
                logger.error(f"Failed to send error reply: {reply_err}")
    
    async def _handle_command(self, msg: InboundMessage) -> None:
        """处理命令"""
        cmd_parts = msg.content.strip().split()
        cmd = cmd_parts[0].lower()
        
        handlers = {
            "/new": self._cmd_new,
            "/sessions": self._cmd_sessions,
            "/switch": self._cmd_switch,
            "/delete": self._cmd_delete,
            "/status": self._cmd_status,
            "/undo": self._cmd_undo,
            "/help": self._cmd_help,
        }
        
        handler = handlers.get(cmd, self._cmd_unknown)
        await handler(msg, cmd_parts)
    
    async def _cmd_new(self, msg: InboundMessage, cmd_parts: List[str]) -> None:
        """创建新会话"""
        title = " ".join(cmd_parts[1:]) if len(cmd_parts) > 1 else None
        
        # 清理旧会话
        if msg.sender_id in self.user_sessions:
            old_session_id = self.user_sessions[msg.sender_id]
            if old_session_id in self.session_metadata:
                del self.session_metadata[old_session_id]
            del self.user_sessions[msg.sender_id]
        
        session_id = await self._init_user_session(msg.sender_id, msg.chat_id, title)
        
        response = f"✅ 已创建新的会话\n🆔 会话ID: {session_id}"
        await self._send_reply(msg, response)
    
    async def _cmd_sessions(self, msg: InboundMessage, cmd_parts: List[str]) -> None:
        """列出会话"""
        async with self._get_opencode_client() as client:
            sessions = await client.list_sessions()
            user_sessions_info = []
            for sess in sessions:
                sid = sess.get("id")
                if sid is None:
                    continue
                meta = self.session_metadata.get(sid)
                if meta and meta.user_id == msg.sender_id:
                    user_sessions_info.append(f"• {sid}: {sess.get('title', '未命名')}")
            
            text = "📋 你的会话列表:\n" + ("\n".join(user_sessions_info) if user_sessions_info else "暂无会话")
            await self._send_reply(msg, text)
    
    async def _cmd_switch(self, msg: InboundMessage, cmd_parts: List[str]) -> None:
        """切换会话"""
        if len(cmd_parts) < 2:
            await self._send_reply(msg, "❌ 请提供会话ID: /switch <session_id>")
            return
        
        session_id = cmd_parts[1]
        async with self._get_opencode_client() as client:
            try:
                session = await client.get_session(session_id)
                self.user_sessions[msg.sender_id] = session_id
                await self._send_reply(
                    msg, 
                    f"✅ 已切换到会话: {session.get('title', session_id)}"
                )
            except Exception:
                await self._send_reply(msg, "❌ 会话不存在或无法访问")
    
    async def _cmd_delete(self, msg: InboundMessage, cmd_parts: List[str]) -> None:
        """删除当前会话"""
        if msg.sender_id not in self.user_sessions:
            await self._send_reply(msg, "❌ 没有活动的会话")
            return
        
        session_id = self.user_sessions[msg.sender_id]
        async with self._get_opencode_client() as client:
            try:
                await client.delete_session(session_id)
                del self.user_sessions[msg.sender_id]
                if session_id in self.session_metadata:
                    del self.session_metadata[session_id]
                await self._send_reply(msg, "✅ 会话已删除")
            except Exception as e:
                await self._send_reply(msg, f"❌ 删除会话失败: {str(e)}")
    
    async def _cmd_status(self, msg: InboundMessage, cmd_parts: List[str]) -> None:
        """服务器状态"""
        try:
            async with self._get_opencode_client() as client:
                health = await client.health_check()
                status = "✅ 在线" if health.get("status") == "ok" else "⚠️ 异常"
                await self._send_reply(
                    msg,
                    f"🖥️ OpenCode Server 状态: {status}\n📍 地址: {client.base_url}"
                )
        except Exception as e:
            await self._send_reply(msg, f"❌ 服务器连接失败: {str(e)}")
    
    async def _cmd_undo(self, msg: InboundMessage, cmd_parts: List[str]) -> None:
        """撤销上一步"""
        if msg.sender_id not in self.user_sessions:
            await self._send_reply(msg, "❌ 没有活动的会话")
            return
        
        session_id = self.user_sessions[msg.sender_id]
        async with self._get_opencode_client() as client:
            try:
                messages = await client.list_messages(session_id=session_id, limit=5)
                assistant_msg = None
                for m in reversed(messages):
                    if m.get("info", {}).get("role") == "assistant":
                        assistant_msg = m
                        break
                
                if assistant_msg:
                    msg_id = assistant_msg.get("info", {}).get("id")
                    await client.revert_message(session_id=session_id, message_id=msg_id)
                    await self._send_reply(msg, "✅ 已撤销上一步操作")
                else:
                    await self._send_reply(msg, "❌ 没有找到可撤销的助手回复")
            except Exception as e:
                await self._send_reply(msg, f"❌ 撤销失败: {str(e)}")
    
    async def _cmd_help(self, msg: InboundMessage, cmd_parts: List[str]) -> None:
        """帮助信息"""
        help_text = """📖 OpenCode 机器人使用指南

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
        await self._send_reply(msg, help_text)
    
    async def _cmd_unknown(self, msg: InboundMessage, cmd_parts: List[str]) -> None:
        """未知命令"""
        await self._send_reply(
            msg,
            f"❌ 未知命令: {cmd_parts[0]}\n输入 /help 查看可用命令"
        )
    
    async def _send_reply(self, msg: InboundMessage, content: str) -> None:
        """发送回复到消息总线"""
        reply = OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=content,
            reply_to=msg.metadata.get("message_id"),
            media=msg.media,
        )
        await self.bus.publish_outbound(reply)
    
    async def _init_user_session(
        self, user_id: str, chat_id: str, title: Optional[str] = None, platform: str = "feishu"
    ) -> str:
        """初始化或获取用户会话"""
        if user_id in self.user_sessions:
            return self.user_sessions[user_id]
        
        async with self._get_opencode_client() as client:
            session = await client.create_session(
                title=title or f"Chat {chat_id}"
            )
            session_id = session.get("id")
            if session_id is None:
                raise ValueError("Failed to create session: no session ID returned")
            self.user_sessions[user_id] = session_id
            self.session_metadata[session_id] = SessionMetadata(
                user_id=user_id,
                chat_id=chat_id,
                created_at=datetime.now(),
                platform=platform,
                title=title,
            )
            return session_id
    
    async def _get_or_create_session(
        self, user_id: str, chat_id: str, title: Optional[str] = None, platform: str = "feishu"
    ) -> str:
        """获取或创建会话"""
        return await self._init_user_session(user_id, chat_id, title, platform)
    
    def _get_opencode_client(self) -> OpenCodeClient:
        """获取 OpenCode 客户端"""
        return OpenCodeClient(
            base_url=self.opencode_server_url,
            username=self.opencode_username,
            password=self.opencode_password,
        )
    
    def _extract_response_text(self, result: Dict[str, Any]) -> str:
        """从 OpenCode 响应中提取文本"""
        try:
            if result is None:
                return "无响应内容"
            
            parts = result.get("parts", []) or []
            if parts:
                text_parts = []
                for part in parts:
                    if isinstance(part, dict) and part.get("type") == "text":
                        text = part.get("content") or part.get("text") or ""
                        if text:
                            text_parts.append(str(text))
                if text_parts:
                    return "\n".join(text_parts)
            
            # 备用方案
            if "content" in result and result["content"] is not None:
                return str(result["content"])
            if "text" in result and result["text"] is not None:
                return str(result["text"])
            
            return "无法解析回复内容"
        except Exception as e:
            logger.error(f"Error extracting response: {e}")
            return "解析回复时出错"
