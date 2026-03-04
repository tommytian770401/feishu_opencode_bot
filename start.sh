#!/bin/bash

# OpenCode Feishu Bot 启动脚本

echo "🚀 OpenCode Feishu Bot"
echo "======================="

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "❌ 错误: 未找到 Python3"
    echo "请先安装 Python 3.8+"
    exit 1
fi

# 检查 .env.feishu 文件
if [ ! -f ".env.feishu" ]; then
    echo "⚠️  未找到 .env.feishu 文件"
    echo "正在从 .env.feishu.example 创建..."
    cp .env.feishu.example .env.feishu
    echo "✅ 已创建 .env.feishu 文件，请编辑配置后重新运行"
    echo ""
    echo "需要配置:"
    echo "  - FEISHU_APP_ID"
    echo "  - FEISHU_APP_SECRET"
    exit 1
fi

# 检查依赖
echo "📦 检查依赖..."
if ! python3 -c "import lark_oapi" 2>/dev/null; then
    echo "❌ 缺少飞书 SDK"
    echo "请运行: pip install -r requirements.txt"
    exit 1
fi

# 检查 OpenCode Server
echo "🔍 检查 OpenCode Server..."
if curl -s http://127.0.0.1:4096/global/health > /dev/null 2>&1; then
    echo "✅ OpenCode Server 运行正常"
else
    echo "⚠️  警告: 无法连接到 OpenCode Server"
    echo "   地址: http://127.0.0.1:4096"
    echo "   请确保 OpenCode Server 已启动:"
    echo "   opencode serve --port 4096"
    echo ""
    read -p "是否继续启动 Bot? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo ""
echo "🤖 启动 Feishu Bot..."
echo "💡 按 Ctrl+C 停止"
echo ""

python3 feishu_bot.py
