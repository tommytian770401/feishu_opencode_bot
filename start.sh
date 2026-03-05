#!/bin/bash

# OpenCode Feishu Bot 启动脚本
# 使用 MessageBus 架构启动飞书机器人

set -e  # 遇到错误退出

echo "🚀 OpenCode Feishu Bot"
echo "======================="

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "❌ 错误: 未找到 Python3"
    echo "请先安装 Python 3.8+"
    exit 1
fi

echo "✅ Python: $(python3 --version)"

# 检查 .env.feishu 文件
if [ ! -f ".env.feishu" ]; then
    echo "⚠️  未找到 .env.feishu 文件"
    echo "正在从 .env.feishu.example 创建..."
    if [ ! -f ".env.feishu.example" ]; then
        echo "❌ 错误: 未找到 .env.feishu.example 模板文件"
        exit 1
    fi
    cp .env.feishu.example .env.feishu
    echo "✅ 已创建 .env.feishu 文件"
    echo "⚠️  请编辑 .env.feishu 配置以下必需项："
    echo "  FEISHU_APP_ID"
    echo "  FEISHU_APP_SECRET"
    echo ""
    echo "配置完成后重新运行: ./start.sh"
    exit 1
fi

echo "✅ 配置文件: .env.feishu"

# 检查关键环境变量
source .env.feishu 2>/dev/null || true

if [ -z "$FEISHU_APP_ID" ] || [ -z "$FEISHU_APP_SECRET" ]; then
    echo "❌ 错误: .env.feishu 中缺少必需配置"
    echo "请确保设置了："
    echo "  FEISHU_APP_ID"
    echo "  FEISHU_APP_SECRET"
    exit 1
fi

echo "✅ 飞书应用凭证已配置"

# 检查依赖
echo "📦 检查依赖..."
REQUIRED_PKGS=("lark-oapi" "aiohttp" "loguru")
MISSING_PKGS=()

for pkg in "${REQUIRED_PKGS[@]}"; do
    if ! python3 -c "import ${pkg//-/_}" 2>/dev/null; then
        MISSING_PKGS+=("$pkg")
    fi
done

if [ ${#MISSING_PKGS[@]} -gt 0 ]; then
    echo "❌ 缺少依赖: ${MISSING_PKGS[*]}"
    echo "请运行: pip install -r requirements.txt"
    exit 1
fi

echo "✅ 所有依赖已安装"

# 检查 OpenCode Server（非必需，仅警告）
echo "🔍 检查 OpenCode Server..."
OPENCODE_URL="${OPENCODE_SERVER_URL:-http://127.0.0.1:4096}"
if curl -s --connect-timeout 3 "${OPENCODE_URL}/global/health" > /dev/null 2>&1; then
    echo "✅ OpenCode Server 运行正常 (${OPENCODE_URL})"
else
    echo "⚠️  警告: 无法连接到 OpenCode Server"
    echo "   地址: ${OPENCODE_URL}"
    echo "   请确保 OpenCode Server 已启动:"
    echo "   opencode serve --port ${OPENCODE_URL##*:}"
    echo ""
    read -p "是否继续启动 Bot? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo ""
echo "🤖 启动 Feishu Bot..."
echo "📡 使用 WebSocket 长连接接收消息"
echo "💡 按 Ctrl+C 停止"
echo ""

# 运行主程序
exec python3 feishu_bot.py
