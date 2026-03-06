#!/usr/bin/env python3
"""
猫咪咖啡馆 QQ 机器人
基于 OneBot 11 协议，支持监听消息并与猫咪Agent对话
"""

import os
import sys
import asyncio
import json
import httpx
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime

# 添加父目录到路径以导入猫咪咖啡馆的模块
sys.path.insert(0, str(Path(__file__).parent.parent))

# ============ 配置区域 ============
# NapCat/OneBot 的 HTTP API 地址
ONEBOT_API_URL = os.getenv("ONEBOT_API_URL", "http://127.0.0.1:3000")
# OneBot 11 的反向Webhook地址（用于接收消息）
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "http://127.0.0.1:5000/qq/webhook")
# 允许使用机器人的QQ号列表（留空则允许所有人）
ALLOWED_QQ = os.getenv("ALLOWED_QQ", "").split(",") if os.getenv("ALLOWED_QQ") else []
# 默认使用的猫咪Agent
DEFAULT_AGENT = os.getenv("DEFAULT_AGENT", "claude")
# ============ 配置结束 ============


class QQBot:
    """QQ机器人基类"""

    def __init__(self, api_url: str = ONEBOT_API_URL):
        self.api_url = api_url
        self.client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        self.client = httpx.AsyncClient(timeout=30.0)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.client:
            await self.client.aclose()

    async def get_login_info(self) -> dict:
        """获取登录的QQ信息"""
        response = await self.client.get(f"{self.api_url}/get_login_info")
        response.raise_for_status()
        return response.json()

    async def send_private_msg(self, user_id: str, message: str) -> dict:
        """发送私聊消息"""
        response = await self.client.post(
            f"{self.api_url}/send_private_msg",
            json={
                "user_id": int(user_id),
                "message": message
            }
        )
        response.raise_for_status()
        return response.json()

    async def send_group_msg(self, group_id: str, message: str) -> dict:
        """发送群消息"""
        response = await self.client.post(
            f"{self.api_url}/send_group_msg",
            json={
                "group_id": int(group_id),
                "message": message
            }
        )
        response.raise_for_status()
        return response.json()

    async def get_msg_history(self, message_id: int) -> dict:
        """获取消息历史"""
        response = await self.client.post(
            f"{self.api_url}/get_msg_history",
            json={
                "message_id": message_id
            }
        )
        response.raise_for_status()
        return response.json()


class MessageHandler:
    """消息处理器"""

    def __init__(self, bot: QQBot):
        self.bot = bot
        self.user_sessions: Dict[str, str] = {}  # user_id -> agent_name

    def is_allowed(self, user_id: str) -> bool:
        """检查用户是否有权限使用机器人"""
        if not ALLOWED_QQ:
            return True
        return user_id in ALLOWED_QQ

    def extract_text(self, message: list) -> str:
        """从消息数组中提取纯文本"""
        text_parts = []
        for msg in message:
            if msg.get("type") == "text":
                text_parts.append(msg.get("data", {}).get("text", ""))
        return "".join(text_parts)

    async def handle_private_message(self, user_id: str, message: list) -> Optional[str]:
        """处理私聊消息"""
        # 检查权限
        if not self.is_allowed(user_id):
            return "喵~ 你没有权限使用这个机器人哦"

        text = self.extract_text(message).strip()

        # 空消息
        if not text:
            return None

        # 命令处理
        if text.startswith("/"):
            return await self.handle_command(user_id, text)

        # 普通聊天 - 调用猫咪Agent
        return await self.handle_chat(user_id, text)

    async def handle_group_message(self, group_id: str, user_id: str, message: list) -> Optional[str]:
        """处理群消息"""
        text = self.extract_text(message).strip()

        # 群里只响应@机器人的消息或以/开头的命令
        if not text.startswith("/"):
            return None

        if not self.is_allowed(user_id):
            return None

        return await self.handle_command(user_id, text, group_id=group_id)

    async def handle_command(self, user_id: str, text: str, group_id: str = None) -> Optional[str]:
        """处理命令"""
        parts = text.split()
        command = parts[0].lower()

        if command == "/help":
            return self.cmd_help()

        elif command == "/agent":
            return self.cmd_agent(user_id, parts[1:])

        elif command == "/agents":
            return self.cmd_agents()

        elif command == "/clear":
            self.user_sessions[user_id] = DEFAULT_AGENT
            return "🧹 会话已重置"

        else:
            return "❓ 未知命令。发送 /help 查看帮助"

    def cmd_help(self) -> str:
        """帮助命令"""
        return """🐱 猫咪咖啡馆 QQ 机器人 帮助

📝 可用命令:
  /help          - 显示帮助信息
  /agent [name]  - 切换猫咪Agent (claude, deepseek)
  /agents        - 列出所有可用的猫咪
  /clear         - 重置当前会话

💬 直接发送消息与猫咪聊天即可！
"""

    def cmd_agent(self, user_id: str, args: List[str]) -> str:
        """切换Agent命令"""
        if not args:
            current = self.user_sessions.get(user_id, DEFAULT_AGENT)
            return f"当前使用的猫咪: {current}"

        agent_name = args[0].lower()

        # 简单验证
        available_agents = ["claude", "deepseek"]
        if agent_name not in available_agents:
            return f"❌ 未知的猫咪: {agent_name}\n可用的猫咪: {', '.join(available_agents)}"

        self.user_sessions[user_id] = agent_name
        return f"✅ 已切换到: {agent_name}"

    def cmd_agents(self) -> str:
        """列出所有Agent"""
        return """🐱 可用的猫咪:
  • 布偶猫 (claude) - 温柔友善，专业且友好
  • DeepSeek (deepseek) - 编程助手，专注代码

使用 /agent [名字] 切换猫咪
"""

    async def handle_chat(self, user_id: str, text: str) -> str:
        """处理普通聊天消息 - 调用猫咪Agent"""
        agent_name = self.user_sessions.get(user_id, DEFAULT_AGENT)

        # 获取Agent实例
        try:
            # 动态导入Agent模块
            if agent_name == "deepseek":
                from app.agents.deepseek import DeepSeekAgent
                agent = DeepSeekAgent({
                    'id': 'deepseek',
                    'name': 'DeepSeek'
                })
                display_name = "DeepSeek"
            else:  # 默认 claude
                from app.agents.claude import ClaudeAgent
                agent = ClaudeAgent({
                    'id': 'opus',
                    'name': '布偶猫'
                })
                display_name = "布偶猫"

            # 调用Agent生成回复
            response = await agent.chat(text, user_id=str(user_id))

            # 清理响应，避免重复的前缀
            if response.startswith(f"🐱 {display_name}:"):
                return response
            else:
                return f"🐱 {display_name}: {response}"

        except Exception as e:
            import traceback
            traceback.print_exc()
            return f"❌ 抱歉，猫咪暂时无法回应: {str(e)}"


async def webhook_handler(message: dict) -> Optional[dict]:
    """
    Webhook消息处理器
    由Flask等Web框架调用，处理来自OneBot的POST消息
    """
    post_type = message.get("post_type")

    async with QQBot() as bot:
        handler = MessageHandler(bot)

        if post_type == "message":
            message_type = message.get("message_type")

            if message_type == "private":
                user_id = message.get("sender", {}).get("user_id")
                qq_message = message.get("message", [])

                reply = await handler.handle_private_message(str(user_id), qq_message)

                if reply:
                    return await bot.send_private_msg(str(user_id), reply)

            elif message_type == "group":
                group_id = message.get("group_id")
                user_id = message.get("sender", {}).get("user_id")
                qq_message = message.get("message", [])

                reply = await handler.handle_group_message(str(group_id), str(user_id), qq_message)

                if reply:
                    return await bot.send_group_msg(str(group_id), reply)

    return None


def parse_message(message_str: str) -> dict:
    """
    从字符串解析消息
    用于从Flask request.json获取消息
    """
    if isinstance(message_str, dict):
        return message_str
    return json.loads(message_str)


# 测试代码
async def test_bot():
    """测试机器人连接"""
    print("🐱 猫咪咖啡馆 QQ 机器人")
    print("=" * 40)

    async with QQBot() as bot:
        try:
            # 测试获取登录信息
            info = await bot.get_login_info()
            print(f"✅ 连接成功！")
            print(f"   QQ号: {info['data']['user_id']}")
            print(f"   昵称: {info['data']['nickname']}")
            print(f"\n机器人已就绪，等待消息...")

        except Exception as e:
            print(f"❌ 连接失败: {e}")
            print("\n请检查:")
            print("1. NapCat是否正在运行")
            print("2. ONEBOT_API_URL配置是否正确")
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(test_bot())
