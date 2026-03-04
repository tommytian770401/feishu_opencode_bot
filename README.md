# OpenCode Feishu Bot

通过飞书机器人对接 OpenCode Server。

## 功能特性

- 💬 与 OpenCode AI 自然对话
- 🆕 创建和管理多个会话
- 📁 代码分析和文件操作
- 🔄 撤销/重做操作支持
- ⚡ 基于 WebSocket 长连接，响应迅速
- 🎯 支持所有 OpenCode 功能

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置飞书应用

1. 访问 [飞书开发者后台](https://open.feishu.cn/app)
2. 创建企业内部应用（机器人类型）
3. 获取 **App ID** 和 **App Secret**
4. 在"订阅事件"中添加以下事件：
   - `im.message.receive_v1`（消息接收）
5. 在"权限管理"中申请所需权限：
   - 读取和发送消息：`im:read`, `im:write`
6. 发布应用（或添加到测试群组）

### 3. 配置环境变量

复制配置文件：

```bash
cp .env.feishu.example .env.feishu
```

编辑 `.env.feishu` 文件，填入你的配置：

```env
# 飞书应用凭证
FEISHU_APP_ID=cli_xxxxxxxxxxxxxxx
FEISHU_APP_SECRET=your_app_secret_here

# OpenCode Server 配置
OPENCODE_SERVER_URL=http://127.0.0.1:4096

# 如果启用了 OpenCode 认证，取消下面注释并填写
# OPENCODE_USERNAME=opencode
# OPENCODE_PASSWORD=你的密码
```

### 4. 启动 Bot

确保 OpenCode Server 已在运行：

```bash
# 在另一个终端运行
opencode serve --port 4096
```

然后启动 Feishu Bot：

```bash
python feishu_bot.py
```

或使用启动脚本：

```bash
./start.sh
```

### 5. 在飞书中使用

1. 在飞书开发者后台，将机器人添加到目标群组或个人对话
2. 在群组或私聊中发送 `/help` 查看可用命令
3. 开始与 OpenCode AI 对话！

## 使用指南

### 基础命令

| 命令 | 说明 |
|------|------|
| `/new [标题]` | 创建新的 OpenCode 会话 |
| `/sessions` | 查看会话列表 |
| `/switch <id>` | 切换到指定会话 |
| `/delete` | 删除当前会话 |
| `/status` | 检查 OpenCode Server 状态 |
| `/undo` | 撤销上一步操作 |
| `/help` | 显示帮助信息 |

### 示例对话

创建会话后，直接发送消息即可：

```
用户: 帮我分析这个项目的代码结构

OpenCode: 我来分析一下项目结构...
```

```
用户: 如何优化 src/main.py 中的这个函数？

OpenCode: 建议如下优化...
```

```
用户: /new 代码分析会话

OpenCode: ✅ 已创建新的会话
```

## 项目结构

```
opencode-feishu-bot/
├── feishu_client.py     # 飞书 API 客户端 + OpenCode 集成
├── feishu_bot.py        # 主程序（事件监听）
├── requirements.txt     # 依赖列表
├── .env.feishu.example  # 环境变量示例
├── start_feishu.sh      # 启动脚本
└── README_feishu.md     # 本文档
```

## 技术实现

### 架构设计

```
飞书事件 → FeishuClient → OpenCodeClient → OpenCode Server
                                    ↓
                             用户会话管理
                                    ↓
                              飞书消息回复
```

### 会话管理

- 每个飞书用户 ID 映射到一个独立的 OpenCode 会话
- 使用 `/new` 创建新会话
- 使用 `/switch` 在多个会话间切换
- 会话元数据存储在内存中（重启后清空）

### 事件处理

- **订阅事件**：`im.message.receive_v1`
- **事件格式**：飞书 v2.0 事件结构
- **长连接模式**：使用 `lark-oapi` SDK 的 WebSocket 长连接
- **异步处理**：所有 I/O 操作使用异步，提高并发能力

### 消息格式

- 支持 Markdown 格式回复（飞书卡片消息可扩展）
- 自动适配飞书消息格式限制

## 常见问题

### Q: 无法连接到 OpenCode Server？

确保 OpenCode Server 正在运行：

```bash
opencode serve --port 4096
```

检查地址是否正确（默认是 `http://127.0.0.1:4096`）

### Q: 飞书机器人不响应？

1. 确保 App ID 和 App Secret 正确
2. 确保已添加 `im.message.receive_v1` 事件订阅
3. 确保已添加到目标群组或个人对话
4. 查看日志输出排查错误

### Q: 消息太长被截断？

飞书单条消息限制约 3000 字符。长回复会被自动截断，可以在配置文件中调整。

### Q: 事件订阅设置？

在飞书开发者后台：
1. 进入"事件订阅"配置
2. 选择"使用长连接接收事件"
3. 添加事件：`im.message.receive_v1`
4. 保存配置

## 安全提示

⚠️ **重要**：
- 不要分享你的 `FEISHU_APP_ID` 和 `FEISHU_APP_SECRET`
- 应用发布时选择"仅限内部使用"或控制可访问范围
- 如果启用 OpenCode Server 认证，请使用强密码
- 定期检查飞书应用权限

## 与 Telegram Bot 的区别

| 特性 | Telegram Bot | Feishu Bot |
|------|-------------|------------|
| 事件订阅 | Webhook / Long Polling | WebSocket 长连接 |
| 消息格式 | Telegram Markdown | 标准 Markdown / 文本 |
| 用户标识 | Telegram user_id | 飞书 user_id / open_id |
| 会话绑定 | 每个 Telegram 用户独立 | 每个飞书用户独立（支持跨群组） |
| API 风格 | python-telegram-bot | lark-oapi SDK |
| 部署要求 | 需要公网地址（Webhook）或轮询 | 需要公网开放 WebSocket 连接 |

## 开发说明

### 扩展功能

可以在 `feishu_client.py` 中扩展 `FeishuOpenCodeBot` 类：

- 添加更多飞书 API 调用（如获取用户信息、创建卡片消息等）
- 实现交互式卡片按钮处理
- 添加数据库持久化存储
- 扩展会话管理功能

### 调试技巧

查看详细日志：

```bash
python feishu_bot.py --log-level DEBUG
```

或修改代码中的 `logging.basicConfig(level=logging.DEBUG)`。

## 许可证

MIT
