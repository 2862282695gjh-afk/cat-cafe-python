#!/usr/bin/env python3
"""
QQ机器人 Webhook 服务器
接收来自 NapCat 的消息并通过 cat_cafe_bot 处理
"""

import os
import sys
import asyncio
from pathlib import Path
from flask import Flask, request, jsonify

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

# 导入QQ机器人
from qq_bot.cat_cafe_bot import webhook_handler

# Flask应用
app = Flask(__name__)

# 配置
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/qq/webhook")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")  # 如果设置了，会验证请求


@app.route('/health', methods=['GET'])
def health():
    """健康检查"""
    return jsonify({"status": "ok", "service": "cat-cafe-qq-bot"})


@app.route(WEBHOOK_PATH, methods=['POST'])
def handle_qq_message():
    """处理来自OneBot的Webhook消息"""
    # 验证Secret（如果设置了）
    if WEBHOOK_SECRET:
        received_secret = request.headers.get('X-Signature', '')
        if not received_secret.endswith(WEBHOOK_SECRET):
            return jsonify({"status": "error", "message": "Invalid secret"}), 403

    # 获取消息
    message = request.get_json()

    if not message:
        return jsonify({"status": "error", "message": "No message data"}), 400

    # 异步处理消息
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        result = loop.run_until_complete(webhook_handler(message))
        return jsonify({"status": "success", "data": result or {}})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

    finally:
        loop.close()


@app.route('/', methods=['GET'])
def index():
    """首页"""
    return jsonify({
        "service": "猫咪咖啡馆 QQ 机器人",
        "version": "1.0.0",
        "endpoints": {
            "health": "/health",
            "webhook": WEBHOOK_PATH
        }
    })


if __name__ == "__main__":
    HOST = os.getenv("WEBHOOK_HOST", "0.0.0.0")
    PORT = int(os.getenv("WEBHOOK_PORT", "5000"))

    print("🐱 猫咪咖啡馆 QQ 机器人 Webhook 服务器")
    print("=" * 50)
    print(f"📍 监听地址: http://{HOST}:{PORT}")
    print(f"🔗 Webhook路径: {WEBHOOK_PATH}")
    print(f"🔐 Secret验证: {'启用' if WEBHOOK_SECRET else '禁用'}")
    print("")
    print("请确保 NapCat 的配置中设置了正确的反向Webhook地址:")
    print(f"  URL: http://<你的IP>:{PORT}{WEBHOOK_PATH}")
    print("")

    app.run(host=HOST, port=PORT, debug=False)
