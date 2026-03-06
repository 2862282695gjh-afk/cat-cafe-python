#!/usr/bin/env python3
"""
APK 推送到 QQ 的脚本
需要配合 NapCat 或其他 OneBot 实现使用
"""

import os
import sys
import httpx
import asyncio
from pathlib import Path
from datetime import datetime

# ============ 配置区域 ============
# NapCat/OneBot 的 HTTP API 地址（默认端口 3000）
ONEBOT_API_URL = os.getenv("ONEBOT_API_URL", "http://127.0.0.1:3000")
# 你的 QQ 号（接收 APK 的目标）
TARGET_QQ = os.getenv("TARGET_QQ", "2862282695")  # 主人的大号（接收 APK）
# APK 文件路径
APK_PATH = Path(__file__).parent.parent / "android-app/FitTrack/app/build/outputs/apk/debug/app-debug.apk"
# ============ 配置结束 ============


async def get_file_info(file_path: Path) -> dict:
    """获取文件信息"""
    if not file_path.exists():
        raise FileNotFoundError(f"APK 文件不存在: {file_path}")

    stat = file_path.stat()
    return {
        "name": file_path.name,
        "size": stat.st_size,
        "size_mb": round(stat.st_size / 1024 / 1024, 2),
        "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    }


async def send_private_file(client: httpx.AsyncClient, user_id: str, file_path: Path) -> dict:
    """
    发送私聊文件
    使用 OneBot 11 的 upload_private_file API
    """
    # 获取绝对路径
    abs_path = file_path.resolve()

    # 构建文件 URI (file:// 协议)
    file_uri = f"file://{abs_path}"

    print(f"📤 正在发送文件到 QQ: {user_id}")
    print(f"📁 文件路径: {abs_path}")

    try:
        response = await client.post(
            f"{ONEBOT_API_URL}/upload_private_file",
            json={
                "user_id": int(user_id),
                "file": file_uri,
                "name": file_path.name
            },
            timeout=60.0  # 发送文件可能需要较长时间
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        print(f"❌ HTTP 错误: {e}")
        print(f"响应内容: {e.response.text}")
        raise
    except Exception as e:
        print(f"❌ 发送失败: {e}")
        raise


async def send_group_file(client: httpx.AsyncClient, group_id: str, file_path: Path) -> dict:
    """
    发送群文件
    使用 OneBot 11 的 upload_group_file API
    """
    abs_path = file_path.resolve()
    file_uri = f"file://{abs_path}"

    print(f"📤 正在发送文件到群: {group_id}")
    print(f"📁 文件路径: {abs_path}")

    try:
        response = await client.post(
            f"{ONEBOT_API_URL}/upload_group_file",
            json={
                "group_id": int(group_id),
                "file": file_uri,
                "name": file_path.name
            },
            timeout=60.0
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        print(f"❌ HTTP 错误: {e}")
        print(f"响应内容: {e.response.text}")
        raise
    except Exception as e:
        print(f"❌ 发送失败: {e}")
        raise


async def send_message(client: httpx.AsyncClient, user_id: str, message: str) -> dict:
    """发送私聊消息"""
    response = await client.post(
        f"{ONEBOT_API_URL}/send_private_msg",
        json={
            "user_id": int(user_id),
            "message": message
        }
    )
    response.raise_for_status()
    return response.json()


async def main():
    """主函数"""
    # 检查目标 QQ
    if not TARGET_QQ:
        print("❌ 错误：请设置 TARGET_QQ 环境变量或在脚本中填写你的 QQ 号")
        print("   示例: export TARGET_QQ=123456789")
        print("   或直接编辑脚本中的 TARGET_QQ 变量")
        sys.exit(1)

    # 检查 APK 文件
    if not APK_PATH.exists():
        print(f"❌ APK 文件不存在: {APK_PATH}")
        print("   请先编译 APK")
        sys.exit(1)

    # 获取文件信息
    file_info = await get_file_info(APK_PATH)
    print(f"📦 APK 文件信息:")
    print(f"   名称: {file_info['name']}")
    print(f"   大小: {file_info['size_mb']} MB")
    print(f"   修改时间: {file_info['modified']}")

    async with httpx.AsyncClient() as client:
        # 先发送通知消息
        print("\n💬 发送通知消息...")
        notification = f"""📱 FitTrack APK 编译完成！

📦 文件: {file_info['name']}
📏 大小: {file_info['size_mb']} MB
⏰ 时间: {file_info['modified']}

正在发送文件，请稍候..."""

        try:
            await send_message(client, TARGET_QQ, notification)
            print("✅ 通知消息发送成功")
        except Exception as e:
            print(f"⚠️ 发送通知失败: {e}")
            # 继续尝试发送文件

        # 发送文件
        print("\n📤 正在发送 APK 文件...")
        try:
            result = await send_private_file(client, TARGET_QQ, APK_PATH)
            print(f"✅ APK 发送成功！")
            print(f"   返回: {result}")
        except Exception as e:
            print(f"❌ APK 发送失败: {e}")
            sys.exit(1)


if __name__ == "__main__":
    print("🐱 FitTrack APK 推送工具")
    print("=" * 40)
    asyncio.run(main())
