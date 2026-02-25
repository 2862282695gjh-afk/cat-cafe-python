"""
Cat Café Python - Flask 主应用
"""
import os
import uuid
import time
import json
import asyncio
from datetime import datetime
from typing import Dict, Optional
from flask import Flask, request, jsonify, render_template, Response
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_cors import CORS
from dotenv import load_dotenv

from app.storage.memory import MemoryStorage
from app.storage.redis import RedisStorage
from app.agents.claude import ClaudeAgent
from app.router.worklist import WorklistRouter

# 加载环境变量
load_dotenv()

# 初始化 Flask
app = Flask(__name__,
            template_folder='../templates',
            static_folder='../static')
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# 配置
USE_REDIS = os.getenv('USE_REDIS', 'true').lower() != 'false'
TOKEN_BUDGET = float(os.getenv('TOKEN_BUDGET', 100))

# 初始化存储
storage: Optional[RedisStorage | MemoryStorage] = None

# Agents
agents: Dict = {}

# 动态注册的 Agent
dynamic_agents: Dict = {}

# Agent 状态详情
agent_status_details: Dict = {}

# Session token 使用量
session_token_usage = {
    'input': 0,
    'output': 0,
    'total': 0,
    'cost': 0,
    'budget': TOKEN_BUDGET
}

# 活跃的 AbortController
active_controllers: Dict = {}

# 自定义词汇表
vocabulary: Dict = {}


def init_storage():
    """初始化存储"""
    global storage
    if USE_REDIS:
        storage = RedisStorage(os.getenv('REDIS_URL', 'redis://localhost:6379'))
        print('使用 Redis 存储')
    else:
        storage = MemoryStorage()
        print('使用内存存储')


def init_agents():
    """初始化默认 Agent"""
    global agents, agent_status_details

    agents['opus'] = ClaudeAgent({
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

    # 初始化静态 agent 状态
    for agent_id in agents:
        agent_status_details[agent_id] = {
            'status': 'idle',
            'message': '等待召唤',
            'lastUpdate': int(time.time() * 1000)
        }


# Router 将在初始化后创建
router: Optional[WorklistRouter] = None


def update_agent_status(agent_id: str, status: str, message: str):
    """更新 agent 状态并广播"""
    agent_status_details[agent_id] = {
        'status': status,
        'message': message,
        'lastUpdate': int(time.time() * 1000)
    }
    socketio.emit('agent-status-update', {
        'agentId': agent_id,
        'status': status,
        'message': message,
        'timestamp': int(time.time() * 1000)
    })


def update_token_usage(usage: Dict = None, cost: float = None):
    """更新 token 使用量并广播"""
    global session_token_usage
    if usage:
        session_token_usage['input'] += usage.get('input_tokens', 0)
        session_token_usage['output'] += usage.get('output_tokens', 0)
        session_token_usage['total'] = session_token_usage['input'] + session_token_usage['output']
    if cost:
        session_token_usage['cost'] += cost
    socketio.emit('token-usage', session_token_usage)


def get_all_agent_status() -> Dict:
    """获取所有 agent 的详细状态"""
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


# ============ REST API ============

@app.route('/')
def index():
    """主页"""
    return render_template('index.html')


@app.route('/api/agents')
def get_agents():
    """获取所有可用 Agent"""
    return jsonify(router.get_available_agents())


@app.route('/api/token-usage')
def get_token_usage():
    """获取 token 使用量"""
    return jsonify(session_token_usage)


@app.route('/api/threads/<thread_id>/messages')
async def get_thread_messages(thread_id):
    """获取线程消息"""
    try:
        messages = await storage.get_messages(thread_id)
        return jsonify(messages)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/threads', methods=['POST'])
async def create_thread():
    """创建新线程"""
    data = request.get_json() or {}
    title = data.get('title')
    thread_id = str(uuid.uuid4())

    if title:
        await storage.set_thread_meta(thread_id, {'title': title})

    return jsonify({'threadId': thread_id})


@app.route('/api/threads/<thread_id>/invoke', methods=['POST'])
async def invoke_thread(thread_id):
    """调用 Agent"""
    data = request.get_json() or {}
    message = data.get('message')
    requested_agents = data.get('agents')

    if not message:
        return jsonify({'error': '消息不能为空'}), 400

    # 检查预算
    if session_token_usage['cost'] >= session_token_usage['budget']:
        return jsonify({'error': '预算已用尽，请增加预算后继续'}), 402

    parsed = router.parse_input(message)
    target_agents = requested_agents or parsed['mentions']

    if not target_agents:
        target_agents = ['opus']

    # 创建取消信号
    signal = {'aborted': False}
    active_controllers[thread_id] = signal

    # 启动异步任务
    socketio.start_background_task(handle_invoke, thread_id, target_agents, message, signal, parsed)

    return jsonify({
        'status': 'started',
        'threadId': thread_id,
        'agents': target_agents
    })


def handle_invoke(thread_id, target_agents, message, signal, parsed):
    """处理 Agent 调用（后台任务）"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        loop.run_until_complete(
            _handle_invoke_async(thread_id, target_agents, message, signal, parsed)
        )
    finally:
        loop.close()


async def _handle_invoke_async(thread_id, target_agents, message, signal, parsed):
    """异步处理 Agent 调用"""
    current_agent_id = None

    try:
        print(f'[DEBUG] 开始处理消息: {message}')

        # 保存用户消息
        await storage.save_message(thread_id, 'user', message, 'user')
        print('[DEBUG] 用户消息已保存')

        # 广播用户消息
        socketio.emit('message', {
            'id': f'user-{int(time.time() * 1000)}',
            'threadId': thread_id,
            'agentId': 'user',
            'role': 'user',
            'content': message,
            'timestamp': int(time.time() * 1000)
        }, room=thread_id)

        print(f'[DEBUG] 开始执行路由, agents: {target_agents}')

        async for event in router.route(target_agents, parsed['message'], thread_id, signal):
            event_type = event.get('type')

            if event_type == 'start':
                current_agent_id = event.get('agent', {}).get('id')
                if current_agent_id:
                    update_agent_status(current_agent_id, 'thinking', '正在思考...')

            elif event_type == 'thinking' and current_agent_id:
                update_agent_status(current_agent_id, 'thinking', '深度思考中...')

            elif event_type == 'status' and current_agent_id:
                update_agent_status(current_agent_id, event.get('status'), event.get('message'))

            elif event_type == 'result':
                update_token_usage(event.get('usage'), event.get('cost'))

            elif event_type == 'complete' and current_agent_id:
                update_agent_status(current_agent_id, 'idle', '完成')

            elif event_type == 'error':
                print(f'[DEBUG] 错误事件: {event.get("message")}')
                if current_agent_id:
                    update_agent_status(current_agent_id, 'idle', '出错')

            elif event_type == 'done':
                print(f'[DEBUG] 路由完成, processed: {event.get("agentStats")}')

            # 广播事件
            is_private = event.get('private', True)
            if not is_private:
                print(f'[DEBUG] 广播事件: {event_type}')
                socketio.emit('event', event, room=thread_id)
            else:
                print(f'[DEBUG] 发送 status-event: {event_type}')
                socketio.emit('status-event', event, room=thread_id)

        print('[DEBUG] 路由执行完成')

    except Exception as e:
        print(f'[DEBUG] 错误: {e}')
        socketio.emit('event', {'type': 'error', 'message': str(e)}, room=thread_id)
        if current_agent_id:
            update_agent_status(current_agent_id, 'idle', '出错')
    finally:
        active_controllers.pop(thread_id, None)


@app.route('/api/threads/<thread_id>/stop', methods=['POST'])
def stop_thread(thread_id):
    """停止执行"""
    signal = active_controllers.get(thread_id)

    if signal:
        signal['aborted'] = True
        active_controllers.pop(thread_id, None)

        # 重置所有 agent 状态
        for agent_id in agents:
            update_agent_status(agent_id, 'idle', '已停止')

        return jsonify({'status': 'stopped'})
    else:
        return jsonify({'status': 'no_active_task'})


@app.route('/api/threads/<thread_id>', methods=['DELETE'])
async def delete_thread(thread_id):
    """清空线程"""
    try:
        await storage.clear_thread(thread_id)
        return jsonify({'status': 'cleared'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/threads', methods=['GET'])
async def get_threads():
    """获取所有线程列表"""
    try:
        threads = await storage.get_all_threads()
        return jsonify(threads)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/threads/<thread_id>', methods=['PATCH'])
async def update_thread(thread_id):
    """更新线程"""
    data = request.get_json() or {}

    updates = {}
    if 'title' in data:
        updates['title'] = data['title']
    if 'archived' in data:
        updates['archived'] = data['archived']
    if 'lastActivity' in data:
        updates['lastActivity'] = data['lastActivity']

    if not updates:
        return jsonify({'error': '没有要更新的字段'}), 400

    await storage.set_thread_meta(thread_id, updates)
    meta = await storage.get_thread_meta(thread_id)
    return jsonify({'status': 'updated', **meta})


@app.route('/api/threads/<thread_id>/export')
async def export_thread(thread_id):
    """导出线程为 Markdown"""
    try:
        messages = await storage.get_messages(thread_id)
        meta = await storage.get_thread_meta(thread_id)

        if not messages:
            return jsonify({'error': '线程为空或不存在'}), 404

        # 生成 Markdown
        markdown = f"# {meta.get('title', '对话记录')}\n\n"
        markdown += f"> 导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        markdown += f"> 线程 ID: {thread_id}\n\n"
        markdown += "---\n\n"

        for msg in messages:
            timestamp = datetime.fromtimestamp(msg['timestamp'] / 1000).strftime('%Y-%m-%d %H:%M:%S')
            if msg['role'] == 'user':
                markdown += f"### 👤 用户 ({timestamp})\n\n"
            else:
                agent = agents.get(msg['agentId'])
                agent_name = agent.name if agent else msg['agentId']
                avatar = agent.avatar if agent else '🐱'
                markdown += f"### {avatar} {agent_name} ({timestamp})\n\n"
            markdown += f"{msg['content']}\n\n"
            markdown += "---\n\n"

        return Response(
            markdown,
            mimetype='text/markdown',
            headers={'Content-Disposition': f'attachment; filename="{meta.get("title", "chat")}.md"'}
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/agents', methods=['POST'])
def create_agent():
    """注册新猫咪（动态 Agent）"""
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
    """删除猫咪"""
    if agent_id == 'opus':
        return jsonify({'error': '不能删除默认猫咪'}), 400

    if agent_id not in dynamic_agents:
        return jsonify({'error': '猫咪不存在'}), 404

    agents.pop(agent_id, None)
    agent_status_details.pop(agent_id, None)
    del dynamic_agents[agent_id]

    return jsonify({'status': 'deleted'})


@app.route('/api/agents/status')
def get_agents_status():
    """获取所有猫咪状态"""
    return jsonify(get_all_agent_status())


@app.route('/api/token-budget', methods=['POST'])
def set_token_budget():
    """设置 token 预算"""
    data = request.get_json() or {}
    budget = data.get('budget')

    if not isinstance(budget, (int, float)) or budget < 0:
        return jsonify({'error': '预算必须是非负数'}), 400

    session_token_usage['budget'] = budget
    socketio.emit('token-usage', session_token_usage)
    return jsonify({'budget': budget})


@app.route('/api/token-usage/reset', methods=['POST'])
def reset_token_usage():
    """重置 token 统计"""
    session_token_usage['input'] = 0
    session_token_usage['output'] = 0
    session_token_usage['total'] = 0
    session_token_usage['cost'] = 0
    socketio.emit('token-usage', session_token_usage)
    return jsonify(session_token_usage)


# ============ 词汇表 API ============

@app.route('/api/vocabulary')
def get_vocabulary():
    """获取词汇表"""
    return jsonify(vocabulary)


@app.route('/api/vocabulary', methods=['POST'])
def add_vocabulary():
    """添加词汇"""
    data = request.get_json() or {}
    word = data.get('word')
    pronunciation = data.get('pronunciation')

    if not word or not pronunciation:
        return jsonify({'error': '词汇和发音都不能为空'}), 400

    vocabulary[word] = pronunciation
    return jsonify({'word': word, 'pronunciation': pronunciation})


@app.route('/api/vocabulary/<word>', methods=['DELETE'])
def delete_vocabulary(word):
    """删除词汇"""
    if word not in vocabulary:
        return jsonify({'error': '词汇不存在'}), 404

    del vocabulary[word]
    return jsonify({'status': 'deleted'})


# ============ WebSocket ============

@socketio.on('connect')
def handle_connect():
    """客户端连接"""
    print(f'客户端连接: {request.sid}')
    emit('agents-status', get_all_agent_status())
    emit('token-usage', session_token_usage)


@socketio.on('join')
def handle_join(thread_id):
    """加入线程房间"""
    join_room(thread_id)
    print(f'[Socket] 客户端 {request.sid} 加入线程 {thread_id}')


@socketio.on('leave')
def handle_leave(thread_id):
    """离开线程房间"""
    leave_room(thread_id)


@socketio.on('disconnect')
def handle_disconnect():
    """客户端断开"""
    print(f'客户端断开: {request.sid}')


# ============ 启动服务器 ============

def create_app():
    """创建应用"""
    init_storage()
    init_agents()

    global router
    router = WorklistRouter(agents, storage)

    return app


if __name__ == '__main__':
    application = create_app()

    # 异步初始化存储
    if USE_REDIS and hasattr(storage, 'connect'):
        import asyncio
        try:
            asyncio.get_event_loop().run_until_complete(storage.connect())
            print('Redis 已连接')
        except Exception as e:
            print(f'Redis 连接失败，回退到内存存储: {e}')
            storage = MemoryStorage()
            router = WorklistRouter(agents, storage)

    PORT = int(os.getenv('PORT', 3001))
    print(f'Cat Café Python 运行在 http://localhost:{PORT}')
    socketio.run(app, host='0.0.0.0', port=PORT, debug=True)
