"""
OpenCode Feishu Bot - 主入口
使用 MessageBus 架构，基于 FeishuChannel 实现
"""

import os
import sys
import asyncio
import logging
from dotenv import load_dotenv

from feishu import FeishuChannel, FeishuConfig, MessageBus
from opencode_agent import OpenCodeAgent

# 加载环境变量
load_dotenv()
load_dotenv(".env.feishu", override=False)

# 配置日志
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def main_async():
    """主异步入口"""
    # 1. 加载配置
    config = FeishuConfig()
    config.enabled = True
    config.app_id = os.getenv("FEISHU_APP_ID", "")
    config.app_secret = os.getenv("FEISHU_APP_SECRET", "")
    config.encrypt_key = os.getenv("FEISHU_ENCRYPT_KEY", "")
    config.verification_token = os.getenv("FEISHU_VERIFICATION_TOKEN", "")
    config.allow_from = ["*"]  # 允许所有用户
    config.react_emoji = "THUMBSUP"
    
    # 验证必需配置
    if not config.app_id or not config.app_secret:
        print("=" * 60)
        print("ERROR: 请配置飞书凭证！")
        print("设置环境变量:")
        print("  export FEISHU_APP_ID=your_app_id")
        print("  export FEISHU_APP_SECRET=your_app_secret")
        print("=" * 60)
        sys.exit(1)
    
    opencode_server_url = os.getenv("OPENCODE_SERVER_URL", "http://127.0.0.1:4096")
    opencode_username = os.getenv("OPENCODE_USERNAME")
    opencode_password = os.getenv("OPENCODE_PASSWORD")
    
    # 2. 创建消息总线
    bus = MessageBus()
    logger.info("✅ MessageBus 创建完成")
    
    # 3. 创建并启动 FeishuChannel
    channel = FeishuChannel(config, bus)
    logger.info("✅ FeishuChannel 创建完成")
    
    # 4. 创建并启动 OpenCodeAgent
    agent = OpenCodeAgent(
        bus=bus,
        opencode_server_url=opencode_server_url,
        opencode_username=opencode_username,
        opencode_password=opencode_password,
    )
    await agent.start()
    logger.info("✅ OpenCodeAgent 启动完成")
    
    # 5. 启动飞书频道（开始监听 WebSocket 事件）
    logger.info("🚀 启动 Feishu Bot...")
    try:
        await channel.start()
    except KeyboardInterrupt:
        logger.info("收到停止信号")
    finally:
        # 6. 优雅关闭
        logger.info("正在关闭...")
        await agent.stop()
        await channel.stop()
        logger.info("已关闭")


def main():
    """主入口"""
    print("🚀 启动 OpenCode Feishu Bot")
    print("============================")
    
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\n👋 Bot 已停止")
    except Exception as e:
        logger.error(f"启动失败: {e}", exc_info=True)
        print(f"❌ 启动失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
