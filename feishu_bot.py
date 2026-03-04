"""
OpenCode Feishu Bot
通过飞书对接 OpenCode Server
"""

import os
import sys
import json
import logging
import asyncio
from typing import Optional
from dotenv import load_dotenv

try:
    from lark_oapi import Client, EventDispatcherHandler, LogLevel, im, ws, JSON
except ImportError:
    print("❌ 缺少飞书 SDK，请安装: pip install lark-oapi")
    sys.exit(1)

from feishu_client import FeishuOpenCodeBot

# 加载环境变量
load_dotenv()
load_dotenv(".env.feishu", override=False)

# 配置日志
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# 配置
FEISHU_APP_ID = os.getenv("FEISHU_APP_ID")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET")
OPENCODE_SERVER_URL = os.getenv("OPENCODE_SERVER_URL", "http://127.0.0.1:4096")
OPENCODE_USERNAME = os.getenv("OPENCODE_USERNAME")
OPENCODE_PASSWORD = os.getenv("OPENCODE_PASSWORD")

# 全局 Bot 实例
bot: Optional[FeishuOpenCodeBot] = None


async def init_bot():
    """初始化机器人"""
    global bot
    if not FEISHU_APP_ID or not FEISHU_APP_SECRET:
        raise ValueError("FEISHU_APP_ID and FEISHU_APP_SECRET are required")

    bot = FeishuOpenCodeBot(
        feishu_app_id=str(FEISHU_APP_ID),
        feishu_app_secret=str(FEISHU_APP_SECRET),
        opencode_server_url=str(OPENCODE_SERVER_URL),
        opencode_username=OPENCODE_USERNAME,
        opencode_password=OPENCODE_PASSWORD,
    )
    # 获取飞书租户 token（会自动创建 HTTP session）
    await bot.feishu_client._get_tenant_access_token()
    logger.info("✅ 机器人初始化完成")
    return bot


# 事件处理器函数
def event_dispatcher():
    """创建事件分发器（同步函数）"""
    handler = EventDispatcherHandler.builder("", "")

    def p2_message_handler(data):
        """消息处理器（同步入口）"""
        try:
            asyncio.create_task(handle_p2_message_v2(data))
        except Exception as e:
            logger.error(f"创建消息处理任务失败: {e}")

    handler = handler.register_p2_im_message_receive_v1(p2_message_handler)
    return handler.build()


async def handle_p2_message_v2(data):
    """处理 P2P/群聊消息接收（v2.0格式）"""
    global bot

    try:
        # data 是 lark_oapi 的事件对象
        if hasattr(data, "marshal"):
            event_json = JSON.marshal(data)
            event_dict = json.loads(event_json) if event_json and isinstance(event_json, str) else {}
        else:
            event_dict = data if isinstance(data, dict) else {}

        logger.info(f"📥 收到v2消息事件: {event_dict.get('header', {}).get('event_type')}")

        # 提取事件内容
        event = event_dict.get("event", {})
        message = event.get("message", {})
        message_id = message.get("message_id", "")
        chat_id = event.get("chat_id", "")

        # 发送者
        sender = event.get("sender", {})
        sender_id = sender.get("sender_id", {})
        user_id = sender_id.get("user_id", "") or sender_id.get("open_id", "")

        # 消息内容
        content_str = message.get("content", "{}")
        if not content_str or not isinstance(content_str, str):
            content_str = "{}"
        try:
            content = json.loads(content_str)
        except json.JSONDecodeError:
            content = {"text": content_str}

        text = content.get("text", "") if isinstance(content, dict) else ""

        # 提及
        mentions = message.get("mentions", [])

        logger.info(f"处理消息 - user: {user_id}, chat: {chat_id}, text: {text[:50]}...")

        if bot and text:
            await bot.handle_message(
                message_id=message_id,
                chat_id=chat_id,
                user_id=user_id,
                content=text,
                mentions=mentions,
            )

    except Exception as e:
        logger.error(f"处理消息失败: {e}", exc_info=True)


def main():
    """主函数 - 启动飞书Bot"""
    print("🚀 启动 OpenCode Feishu Bot")
    print("============================")

    # 初始化异步环境
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        # 初始化Bot
        logger.info("正在初始化机器人...")
        loop.run_until_complete(init_bot())

        print("✅ 机器人已初始化")
        print("📡 开始监听飞书事件...")
        print("💡 按 Ctrl+C 停止")
        print("")

        # 创建事件处理器
        event_handler = event_dispatcher()

        # 启动长连接客户端
        if not FEISHU_APP_ID or not FEISHU_APP_SECRET:
            raise ValueError("FEISHU_APP_ID and FEISHU_APP_SECRET must be set")

        cli = ws.Client(
            app_id=str(FEISHU_APP_ID),
            app_secret=str(FEISHU_APP_SECRET),
            event_handler=event_handler,
            log_level=LogLevel.INFO,
        )

        cli.start()

    except KeyboardInterrupt:
        print("\n\n👋 正在停止机器人...")
        logger.info("收到停止信号，正在关闭...")
    except Exception as e:
        logger.error(f"启动失败: {e}", exc_info=True)
        print(f"❌ 启动失败: {e}")
        sys.exit(1)
    finally:
        # 清理资源
        try:
            if bot and bot.feishu_client:
                loop.run_until_complete(bot.feishu_client.close())
        except Exception:
            pass
        loop.close()


if __name__ == "__main__":
    main()
