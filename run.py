#!/usr/bin/env python3
"""
Cat Café Python - 启动入口
"""
import os
import sys

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

# 加载环境变量
load_dotenv()


def main():
    """主函数"""
    from flask import Flask
    from flask_socketio import SocketIO
    from flask_cors import CORS

    USE_REDIS = os.getenv('USE_REDIS', 'true').lower() != 'false'
    PORT = int(os.getenv('PORT', 3001))
    DEBUG = os.getenv('DEBUG', 'true').lower() == 'true'
    TOKEN_BUDGET = float(os.getenv('TOKEN_BUDGET', 100))

    # 初始化存储
    if USE_REDIS:
        from app.storage.redis import RedisStorage
        storage = RedisStorage(os.getenv('REDIS_URL', 'redis://localhost:6379'))
        print('使用 Redis 存储')
        try:
            storage.connect()
            print('Redis 已连接')
        except Exception as e:
            print(f'Redis 连接失败，回退到内存存储: {e}')
            from app.storage.memory import MemoryStorage
            storage = MemoryStorage()
    else:
        from app.storage.memory import MemoryStorage
        storage = MemoryStorage()
        print('使用内存存储')

    # 初始化 Agents
    from app.agents.claude import ClaudeAgent
    agents = {
        'opus': ClaudeAgent({
            'id': 'opus',
            'name': '布偶猫',
            'avatar': '🐱',
            'description': '温柔友善的 Claude，擅长各种任务',
            'voice': {
                'pitch': 0.7,
                'rate': 0.85,
                'description': '温柔低沉'
            }
        })
    }

    # 初始化 Router
    from app.router.worklist import WorklistRouter
    router = WorklistRouter(agents, storage)

    # 创建 Flask 应用
    app = Flask(__name__,
                template_folder='templates',
                static_folder='static')
    CORS(app)
    socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

    # Agent 状态详情
    agent_status_details = {
        'opus': {'status': 'idle', 'message': '等待召唤', 'lastUpdate': 0}
    }

    # Token 使用量
    session_token_usage = {
        'input': 0,
        'output': 0,
        'total': 0,
        'cost': 0,
        'budget': TOKEN_BUDGET
    }

    # 词汇表
    vocabulary = {}

    # 动态 agents
    dynamic_agents = {}

    # 路由
    import uuid
    import time
    from datetime import datetime
    from flask import request, jsonify, render_template, Response
    from flask_socketio import emit, join_room, leave_room

    @app.route('/')
    def index():
        import os
        return open(os.path.join(os.path.dirname(__file__), 'static', 'index.html')).read()

    @app.route('/api/agents')
    def get_agents():
        return jsonify(router.get_available_agents())

    @app.route('/api/agents/status')
    def get_agents_status():
        status = {}
        for agent_id, agent in agents.items():
            details = agent_status_details.get(agent_id, {'status': 'idle', 'message': '等待召唤'})
            status[agent_id] = {
                'id': agent.id,
                'name': agent.name,
                'avatar': agent.avatar,
                'description': agent.description,
                'voice': agent.voice,
                'status': details['status'],
                'statusMessage': details['message'],
                'lastUpdate': details['lastUpdate']
            }
        return jsonify(status)

    def get_agents_status_dict():
        """返回 agent 状态的字典（用于 socket 发送）"""
        status = {}
        for agent_id, agent in agents.items():
            details = agent_status_details.get(agent_id, {'status': 'idle', 'message': '等待召唤'})
            status[agent_id] = {
                'id': agent.id,
                'name': agent.name,
                'avatar': agent.avatar,
                'description': agent.description,
                'voice': agent.voice,
                'status': details['status'],
                'statusMessage': details['message'],
                'lastUpdate': details['lastUpdate']
            }
        return status

    @app.route('/api/token-usage')
    def get_token_usage():
        return jsonify(session_token_usage)

    @app.route('/api/threads')
    def get_threads():
        threads = storage.get_all_threads()
        return jsonify(threads)

    @app.route('/api/threads', methods=['POST'])
    def create_thread():
        data = request.get_json() or {}
        thread_id = str(uuid.uuid4())
        if data.get('title'):
            storage.set_thread_meta(thread_id, {'title': data['title']})
        return jsonify({'threadId': thread_id})

    @app.route('/api/threads/<thread_id>')
    def get_thread(thread_id):
        meta = storage.get_thread_meta(thread_id)
        messages = storage.get_messages(thread_id)
        return jsonify({'id': thread_id, **(meta or {}), 'messages': messages})

    @app.route('/api/threads/<thread_id>', methods=['PATCH'])
    def update_thread(thread_id):
        data = request.get_json() or {}
        storage.set_thread_meta(thread_id, data)
        meta = storage.get_thread_meta(thread_id)
        return jsonify({'status': 'updated', **(meta or {})})

    @app.route('/api/threads/<thread_id>', methods=['DELETE'])
    def delete_thread(thread_id):
        storage.clear_thread(thread_id)
        return jsonify({'status': 'cleared'})

    @app.route('/api/threads/<thread_id>/messages')
    def get_messages_route(thread_id):
        messages = storage.get_messages(thread_id)
        return jsonify(messages)

    @app.route('/api/threads/<thread_id>/export')
    def export_thread(thread_id):
        messages = storage.get_messages(thread_id)
        meta = storage.get_thread_meta(thread_id) or {}

        markdown = f"# {meta.get('title', '对话记录')}\n\n"
        markdown += f"> 导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n---\n\n"

        for msg in messages:
            ts = datetime.fromtimestamp(msg['timestamp'] / 1000).strftime('%H:%M:%S')
            if msg['role'] == 'user':
                markdown += f"### 👤 用户 ({ts})\n\n"
            else:
                agent = agents.get(msg['agentId'])
                name = agent.name if agent else msg['agentId']
                avatar = agent.avatar if agent else '🐱'
                markdown += f"### {avatar} {name} ({ts})\n\n"
            markdown += f"{msg['content']}\n\n---\n\n"

        return Response(markdown, mimetype='text/markdown',
                       headers={'Content-Disposition': f'attachment; filename="{meta.get("title", "chat")}.md"'})

    @app.route('/api/vocabulary')
    def get_vocabulary():
        return jsonify(vocabulary)

    @app.route('/api/vocabulary', methods=['POST'])
    def add_vocabulary():
        data = request.get_json() or {}
        word = data.get('word')
        pronunciation = data.get('pronunciation')
        if word and pronunciation:
            vocabulary[word] = pronunciation
            return jsonify({'word': word, 'pronunciation': pronunciation})
        return jsonify({'error': '词汇和发音不能为空'}), 400

    @app.route('/api/vocabulary/<word>', methods=['DELETE'])
    def delete_vocabulary(word):
        if word in vocabulary:
            del vocabulary[word]
            return jsonify({'status': 'deleted'})
        return jsonify({'error': '词汇不存在'}), 404

    @app.route('/api/threads/<thread_id>/invoke', methods=['POST'])
    def invoke_thread(thread_id):
        data = request.get_json() or {}
        message = data.get('message')
        requested_agents = data.get('agents')

        if not message:
            return jsonify({'error': '消息不能为空'}), 400

        # 检查预算
        if session_token_usage['cost'] >= session_token_usage['budget']:
            return jsonify({'error': '预算已用尽，请增加预算后继续'}), 402

        # 解析输入
        parsed = router.parse_input(message)
        target_agents = requested_agents or parsed['mentions']

        if not target_agents:
            target_agents = ['opus']

        # 保存用户消息
        storage.save_message(thread_id, 'user', message, 'user')

        # 广播用户消息
        user_msg = {
            'id': f"user-{int(time.time() * 1000)}",
            'threadId': thread_id,
            'agentId': 'user',
            'role': 'user',
            'content': message,
            'timestamp': int(time.time() * 1000)
        }
        socketio.emit('message', user_msg, room=thread_id)

        # 启动后台任务处理
        def process_invoke():
            import asyncio
            import traceback
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            signal = {'aborted': False}

            async def run():
                try:
                    print(f'[ProcessInvoke] 开始处理，目标 agents: {target_agents}')
                    async for event in router.route(target_agents, parsed['message'], thread_id, signal):
                        event_type = event.get('type')
                        is_private = event.get('private', True)
                        agent_id = event.get('agentId')
                        print(f'[ProcessInvoke] 事件: {event_type}, private: {is_private}')

                        # 更新 agent 状态
                        if agent_id and agent_id in agent_status_details:
                            new_status = None
                            new_message = None

                            if event_type == 'start':
                                new_status = 'thinking'
                                new_message = '正在思考...'
                            elif event_type == 'status':
                                new_status = event.get('status', 'thinking')
                                new_message = event.get('message', '')
                            elif event_type == 'stream':
                                new_status = 'streaming'
                                new_message = '正在回复...'
                            elif event_type == 'complete':
                                new_status = 'idle'
                                new_message = '等待召唤'

                            if new_status:
                                agent_status_details[agent_id] = {
                                    'status': new_status,
                                    'message': new_message,
                                    'lastUpdate': int(time.time() * 1000)
                                }
                                # 广播状态更新到所有客户端
                                socketio.emit('agent-status-update', {
                                    'agentId': agent_id,
                                    'status': new_status,
                                    'message': new_message
                                }, namespace='/')

                        if event_type == 'complete':
                            socketio.emit('event', event, room=thread_id)
                        elif event_type == 'done':
                            socketio.emit('event', event, room=thread_id)
                        elif not is_private:
                            socketio.emit('event', event, room=thread_id)
                        else:
                            socketio.emit('status-event', event, room=thread_id)
                except Exception as e:
                    print(f'[Error] {e}')
                    traceback.print_exc()
                    socketio.emit('event', {'type': 'error', 'message': str(e)}, room=thread_id)
                    # 出错时重置所有 agent 状态
                    for aid in target_agents:
                        if aid in agent_status_details:
                            agent_status_details[aid] = {
                                'status': 'idle',
                                'message': '等待召唤',
                                'lastUpdate': int(time.time() * 1000)
                            }
                            socketio.emit('agent-status-update', {
                                'agentId': aid,
                                'status': 'idle',
                                'message': '等待召唤'
                            }, namespace='/')

            try:
                loop.run_until_complete(run())
            except Exception as e:
                print(f'[ThreadError] {e}')
                traceback.print_exc()
            finally:
                loop.close()

        import threading
        thread = threading.Thread(target=process_invoke)
        thread.start()

        return jsonify({
            'status': 'started',
            'threadId': thread_id,
            'agents': target_agents
        })

    @app.route('/api/threads/<thread_id>/stop', methods=['POST'])
    def stop_thread(thread_id):
        # TODO: 实现停止功能
        return jsonify({'status': 'stopped'})

    @app.route('/api/agents', methods=['POST'])
    def create_agent():
        data = request.get_json() or {}
        name = data.get('name')
        avatar = data.get('avatar', '🐱')
        description = data.get('description', '一只可爱的猫咪')
        system_prompt = data.get('systemPrompt', '你是一只可爱的猫咪，喜欢帮助人类。')
        voice = data.get('voice', {'pitch': 1.0, 'rate': 1.0, 'description': '标准声音'})

        if not name:
            return jsonify({'error': '名称不能为空'}), 400

        agent_id = f"cat-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"

        new_agent = ClaudeAgent({
            'id': agent_id,
            'name': name,
            'avatar': avatar,
            'description': description,
            'systemPrompt': system_prompt,
            'voice': voice
        })

        agents[agent_id] = new_agent
        agent_status_details[agent_id] = {
            'status': 'idle',
            'message': '等待召唤',
            'lastUpdate': int(time.time() * 1000)
        }
        dynamic_agents[agent_id] = {
            'name': name,
            'avatar': avatar,
            'description': description,
            'systemPrompt': system_prompt,
            'voice': new_agent.voice
        }

        return jsonify({
            'status': 'created',
            'agent': {
                'id': agent_id,
                'name': name,
                'avatar': avatar,
                'description': description,
                'voice': new_agent.voice
            }
        })

    @app.route('/api/agents/<agent_id>', methods=['DELETE'])
    def delete_agent(agent_id):
        if agent_id == 'opus':
            return jsonify({'error': '不能删除默认猫咪'}), 400

        if agent_id not in dynamic_agents:
            return jsonify({'error': '猫咪不存在'}), 404

        del agents[agent_id]
        del agent_status_details[agent_id]
        del dynamic_agents[agent_id]

        return jsonify({'status': 'deleted'})

    # ===== 记忆管理 API =====

    @app.route('/api/agents/<agent_id>/memory')
    def get_agent_memory(agent_id):
        """获取猫咪的长期记忆"""
        memory = storage.get_long_memory(agent_id)
        return jsonify(memory or {})

    @app.route('/api/agents/<agent_id>/memory', methods=['POST'])
    def add_agent_memory(agent_id):
        """添加猫咪的长期记忆"""
        data = request.get_json() or {}
        key = data.get('key')
        value = data.get('value')

        if not key or not value:
            return jsonify({'error': 'key 和 value 不能为空'}), 400

        storage.add_memory_entry(agent_id, key, value)
        memory = storage.get_long_memory(agent_id)
        return jsonify({'status': 'ok', 'memory': memory})

    @app.route('/api/agents/<agent_id>/memory/<key>', methods=['DELETE'])
    def delete_agent_memory(agent_id, key):
        """删除猫咪的特定记忆"""
        storage.remove_memory_entry(agent_id, key)
        return jsonify({'status': 'deleted'})

    @app.route('/api/threads/<thread_id>/session')
    def get_session_state(thread_id):
        """获取会话状态"""
        state = storage.get_session_state(thread_id)
        pending = storage.get_pending_tool(thread_id)
        return jsonify({
            'state': state or {},
            'pendingTool': pending
        })

    @app.route('/api/threads/<thread_id>/session', methods=['DELETE'])
    def clear_session(thread_id):
        """清除会话状态"""
        storage.clear_session_state(thread_id)
        storage.clear_pending_tool(thread_id)
        return jsonify({'status': 'cleared'})

    @app.route('/api/threads/<thread_id>/pending-tool')
    def get_pending_tool(thread_id):
        """获取待确认的工具"""
        pending = storage.get_pending_tool(thread_id)
        return jsonify(pending or {})

    @app.route('/api/threads/<thread_id>/pending-tool', methods=['DELETE'])
    def clear_pending_tool(thread_id):
        """清除待确认的工具"""
        storage.clear_pending_tool(thread_id)
        return jsonify({'status': 'cleared'})

    @app.route('/api/token-budget', methods=['POST'])
    def set_budget():
        data = request.get_json() or {}
        budget = data.get('budget', 0)
        if isinstance(budget, (int, float)) and budget >= 0:
            session_token_usage['budget'] = budget
            socketio.emit('token-usage', session_token_usage)
            return jsonify({'budget': budget})
        return jsonify({'error': '预算无效'}), 400

    @app.route('/api/token-usage/reset', methods=['POST'])
    def reset_usage():
        session_token_usage['input'] = 0
        session_token_usage['output'] = 0
        session_token_usage['total'] = 0
        session_token_usage['cost'] = 0
        socketio.emit('token-usage', session_token_usage)
        return jsonify(session_token_usage)

    # WebSocket 事件
    @socketio.on('connect')
    def handle_connect(auth=None):
        print(f'客户端连接: {request.sid}')
        emit('agents-status', get_agents_status_dict())
        emit('token-usage', session_token_usage)

    @socketio.on('join')
    def handle_join(thread_id):
        from flask_socketio import join_room
        join_room(thread_id)
        print(f'[Socket] 客户端加入线程 {thread_id}')

    @socketio.on('leave')
    def handle_leave(thread_id):
        from flask_socketio import leave_room
        leave_room(thread_id)

    @socketio.on('disconnect')
    def handle_disconnect():
        print(f'客户端断开: {request.sid}')

    print(f'Cat Café Python 运行在 http://localhost:{PORT}')
    socketio.run(app, host='0.0.0.0', port=PORT, debug=DEBUG, allow_unsafe_werkzeug=True)


if __name__ == '__main__':
    main()
