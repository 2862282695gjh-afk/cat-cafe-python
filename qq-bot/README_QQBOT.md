# 猫咪咖啡馆 QQ 机器人

这是一个基于 OneBot 11 协议的 QQ 机器人，可以让你在 QQ 上与猫咪咖啡馆的 AI 猫咪对话！

## 功能特点

- 🐱 多只猫咪 Agent 可选（布偶猫/Claude、DeepSeek）
- 💬 私聊和群聊支持
- 🔄 支持切换不同的猫咪
- 🚀 基于 OneBot 11 协议，兼容 NapCat、LLOneBot 等实现
- 📱 支持发送命令和自由对话

## 快速开始

### 前置要求

1. **安装 NapCat**（或其他 OneBot 11 实现）
2. **Python 3.8+**
3. **猫咪咖啡馆项目依赖**

### 安装步骤

#### 1. 安装 NapCat

参考 `README.md` 中的详细说明，这里简单概述：

```bash
# 下载 NapCat
mkdir -p ~/napcat && cd ~/napcat
curl -L -o napcat.zip https://github.com/NapNeko/NapCatQQ/releases/latest/download/napcat.mac.zip
unzip napcat.zip

# 启动 NapCat 并登录 QQ
./napcat
```

#### 2. 配置 NapCat

编辑 `~/napcat/config/onebot11.json`，启用 HTTP API：

```json
{
  "http": {
    "enable": true,
    "host": "0.0.0.0",
    "port": 3000,
    "secret": "",
    "enableHeart": false,
    "enablePost": false
  },
  "ws": {
    "enable": false
  },
  "reverseWs": {
    "enable": false
  }
}
```

**重要**：如果你需要消息推送到机器人，需要配置 `reverseWs` 或使用消息上报模式。目前机器人使用**轮询模式**，不需要配置 Webhook。

#### 3. 安装 Python 依赖

```bash
cd qq-bot
pip3 install httpx flask
```

#### 4. 配置环境变量（可选）

创建 `.env` 文件或直接设置环境变量：

```bash
# NapCat API 地址（通常不需要修改）
export ONEBOT_API_URL=http://127.0.0.1:3000

# 允许使用的 QQ 号（留空则允许所有人）
export ALLOWED_QQ=123456789,987654321

# 默认使用的猫咪
export DEFAULT_AGENT=claude

# Webhook 服务器配置（如果启用）
export WEBHOOK_HOST=0.0.0.0
export WEBHOOK_PORT=5000
```

#### 5. 启动机器人

```bash
cd qq-bot
./start.sh
```

或者手动启动：

```bash
# 测试连接
python3 cat_cafe_bot.py

# 启动 Webhook 服务器（需要配置 NapCat 的上报地址）
python3 webhook_server.py
```

## 使用方法

### 模式一：轮询模式（推荐，简单）

目前机器人默认使用轮询模式，不需要配置 NapCat 的 Webhook。

1. 确保 NapCat 正在运行
2. 在 QQ 中私聊机器人（或者让机器人自己发消息给你）
3. 直接开始对话！

### 模式二：Webhook 模式（实时消息）

如果你想要机器人实时响应 QQ 消息，需要配置 NapCat 的消息上报：

1. 启动 Webhook 服务器：
   ```bash
   python3 webhook_server.py
   ```

2. 配置 NapCat 的 `onebot11.json`，添加反向 Webhook：
   ```json
   {
     "reverseWs": {
       "enable": true,
       "urls": ["ws://127.0.0.1:5000"]
     }
   }
   ```

## 命令列表

在 QQ 中发送以下命令与机器人交互：

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助信息 |
| `/agent [name]` | 切换猫咪Agent |
| `/agents` | 列出所有可用的猫咪 |
| `/clear` | 重置当前会话 |

### 示例对话

```
你: 你好！
🐱 布偶猫: 喵~ 你好呀！有什么我可以帮你的吗？

你: /agent deepseek
✅ 已切换到: deepseek

你: 帮我写一个Python函数
🐱 DeepSeek: 当然可以！你想写什么功能的函数呢？
```

## 可用的猫咪

| 名字 | 代号 | 特点 |
|------|------|------|
| 布偶猫 | claude | 温柔友善，专业且友好 |
| DeepSeek | deepseek | 编程助手，专注代码 |

## 项目结构

```
qq-bot/
├── cat_cafe_bot.py       # QQ 机器人核心逻辑
├── webhook_server.py     # Webhook 服务器（接收QQ消息）
├── push_apk.py          # APK 推送工具
├── build_and_push.sh    # 编译+推送脚本
├── start.sh             # 启动脚本
├── README.md            # APK 推送说明
└── README_QQBOT.md      # 本文档
```

## 常见问题

### Q: 机器人不回复消息？
A:
1. 检查 NapCat 是否正在运行
2. 检查 ONEBOT_API_URL 配置是否正确
3. 确认你的 QQ 号在 ALLOWED_QQ 列表中（如果设置了）
4. 运行 `python3 cat_cafe_bot.py` 测试连接

### Q: 如何限制谁可以使用机器人？
A: 设置 `ALLOWED_QQ` 环境变量，用逗号分隔多个 QQ 号：
```bash
export ALLOWED_QQ=123456789,987654321
```

### Q: 支持群聊吗？
A: 支持！在群里发送以 `/` 开头的命令即可。目前群聊只响应命令，不会自动回复所有消息。

### Q: 如何添加新的猫咪？
A: 编辑 `cat_cafe_bot.py` 的 `cmd_agents()` 和 `handle_chat()` 方法，添加新的 Agent。

## 技术架构

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│     QQ      │ ◀─▶ │   NapCat    │ ◀─▶ │  QQ Bot     │
│  (用户)     │     │  (OneBot)   │     │  (Python)   │
└─────────────┘     └─────────────┘     └─────────────┘
                                                │
                                                ▼
                                        ┌─────────────┐
                                        │  Cat Café   │
                                        │   Agents    │
                                        └─────────────┘
```

## 开发

### 添加新命令

在 `cat_cafe_bot.py` 的 `handle_command()` 方法中添加：

```python
elif command == "/newcmd":
    return self.cmd_newcmd(user_id, parts[1:])
```

然后在 `MessageHandler` 类中添加命令处理方法：

```python
def cmd_newcmd(self, user_id: str, args: List[str]) -> str:
    # 实现你的命令逻辑
    return "命令结果"
```

## 许可证

本项目遵循猫咪咖啡馆项目的许可证。
