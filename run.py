#!/usr/bin/env python3
"""
Cat Café Python - 启动入口
"""
import asyncio
import os
import sys

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

from app.main import create_app, storage, USE_REDIS, agents
from app.router.worklist import WorklistRouter


def main():
    """主函数"""
    application = create_app()

    # 异步初始化存储
    if USE_REDIS and hasattr(storage, 'connect'):
        try:
            asyncio.get_event_loop().run_until_complete(storage.connect())
            print('Redis 已连接')
        except Exception as e:
            print(f'Redis 连接失败，回退到内存存储: {e}')
            from app.storage.memory import MemoryStorage
            global storage
            storage = MemoryStorage()
            # 重新创建 router
            from app.main import router
            import app.main as main_module
            main_module.router = WorklistRouter(agents, storage)

    # 启动服务器
    from flask_socketio import SocketIO
    from app.main import socketio

    PORT = int(os.getenv('PORT', 3001))
    DEBUG = os.getenv('DEBUG', 'true').lower() == 'true'

    print(f'Cat Café Python 运行在 http://localhost:{PORT}')
    socketio.run(application, host='0.0.0.0', port=PORT, debug=DEBUG)


if __name__ == '__main__':
    main()
