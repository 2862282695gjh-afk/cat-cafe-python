#!/usr/bin/env python3
"""
Cat Café Python - 启动入口
"""
import os
import sys
import time

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

    # 尝试加载 DeepSeek Agent (如果配置了 API Key)
    DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
    if DEEPSEEK_API_KEY:
        try:
            from app.agents.deepseek import DeepSeekAgent
            agents['deepseek'] = DeepSeekAgent({
                'id': 'deepseek',
                'name': '狸花猫',
                'avatar': '🐯',
                'description': 'DeepSeek 驱动的猫咪，擅长编程和推理',
                'voice': {
                    'pitch': 1.0,
                    'rate': 1.0,
                    'description': '清晰有力'
                },
                'model': os.getenv('DEEPSEEK_MODEL', 'deepseek-chat')
            })
            print('[启动] 加载 DeepSeek Agent (狸花猫)')
        except Exception as e:
            print(f'[启动] 加载 DeepSeek Agent 失败: {e}')

    # Agent 状态详情 - 必须在加载动态 agents 之前初始化
    agent_status_details = {
        agent_id: {'status': 'idle', 'message': '等待召唤', 'lastUpdate': int(time.time() * 1000)}
        for agent_id in agents
    }

    # 动态 agents 字典
    dynamic_agents = {}

    # 从存储加载动态 Agents
    try:
        saved_agents = storage.get_all_agents()
        for agent_config in saved_agents:
            agent_id = agent_config.get('id')
            if agent_id and agent_id not in agents:
                agent_type = agent_config.get('type', 'claude')

                # 根据保存的类型创建对应的 Agent
                if agent_type == 'deepseek':
                    try:
                        from app.agents.deepseek import DeepSeekAgent
                        agents[agent_id] = DeepSeekAgent(agent_config)
                        print(f'[启动] 加载 DeepSeek 猫咪: {agent_config.get("name")} ({agent_id})')
                    except Exception as e:
                        print(f'[启动] DeepSeek Agent 加载失败，回退到 Claude: {e}')
                        agents[agent_id] = ClaudeAgent(agent_config)
                else:
                    agents[agent_id] = ClaudeAgent(agent_config)
                    print(f'[启动] 加载 Claude 猫咪: {agent_config.get("name")} ({agent_id})')

                # 初始化状态详情
                agent_status_details[agent_id] = {
                    'status': 'idle',
                    'message': '等待召唤',
                    'lastUpdate': int(time.time() * 1000)
                }
                # 添加到 dynamic_agents
                dynamic_agents[agent_id] = {
                    'name': agent_config.get('name'),
                    'avatar': agent_config.get('avatar'),
                    'description': agent_config.get('description'),
                    'systemPrompt': agent_config.get('systemPrompt'),
                    'voice': agent_config.get('voice'),
                    'type': agent_type
                }
    except Exception as e:
        print(f'[启动] 加载保存的猫咪失败: {e}')
        import traceback
        traceback.print_exc()

    # 初始化 Router - 传入状态获取器
    from app.router.worklist import WorklistRouter
    router = WorklistRouter(agents, storage, lambda: agent_status_details)

    # 初始化 MCP 管理器
    from app.mcp.manager import MCPManager
    mcp_manager = MCPManager(storage)
    print('[启动] MCP 管理器已初始化')

    # 初始化 Skill 管理器
    from app.skills.manager import SkillManager
    skill_manager = SkillManager(storage)
    print('[启动] Skill 管理器已初始化')

    # 创建 Flask 应用
    app = Flask(__name__,
                template_folder='templates',
                static_folder='static')
    CORS(app)
    socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

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

    # 路由
    import uuid
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
            details = agent_status_details.get(agent_id, {})
            dynamic_info = dynamic_agents.get(agent_id, {})
            status[agent_id] = {
                'id': agent.id,
                'name': agent.name,
                'avatar': agent.avatar,
                'description': agent.description,
                'voice': agent.voice,
                'status': details.get('status', 'idle'),
                'statusMessage': details.get('message', '等待召唤'),
                'lastUpdate': details.get('lastUpdate', 0),
                'type': dynamic_info.get('type', 'claude')
            }
        return jsonify(status)

    def get_agents_status_dict():
        """返回 agent 状态的字典（用于 socket 发送）"""
        status = {}
        for agent_id, agent in agents.items():
            details = agent_status_details.get(agent_id, {})
            dynamic_info = dynamic_agents.get(agent_id, {})
            status[agent_id] = {
                'id': agent.id,
                'name': agent.name,
                'avatar': agent.avatar,
                'description': agent.description,
                'voice': agent.voice,
                'status': details.get('status', 'idle'),
                'statusMessage': details.get('message', '等待召唤'),
                'lastUpdate': details.get('lastUpdate', 0),
                'type': dynamic_info.get('type', 'claude')
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
        print(f"[Invoke] 原始消息: {message[:100]}...")
        print(f"[Invoke] requested_agents={requested_agents}")
        print(f"[Invoke] parsed_mentions={parsed['mentions']}")
        target_agents = requested_agents or parsed['mentions']

        if not target_agents:
            # 默认使用 opus (布偶猫)
            print(f"[Invoke] 无明确目标，使用默认 agent: opus")
            target_agents = ['opus']

        print(f"[Invoke] 最终目标 agents: {target_agents}")

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
                        print(f'[ProcessInvoke] 事件: {event_type}, agentId: {agent_id}, private: {is_private}')

                        # 更新 agent 状态
                        if agent_id:
                            print(f"[状态更新] agent_id={agent_id}, in status_details={agent_id in agent_status_details}")
                            if agent_id in agent_status_details:
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
                                    print(f"[状态广播] {agent_id}: {new_status} - {new_message}")
                                    socketio.emit('agent-status-update', {
                                        'agentId': agent_id,
                                        'status': new_status,
                                        'message': new_message
                                    }, namespace='/')
                            else:
                                print(f"[警告] agent_id {agent_id} 不在 agent_status_details 中")

                        if event_type == 'complete':
                            socketio.emit('event', event, room=thread_id)
                        elif event_type == 'done':
                            socketio.emit('event', event, room=thread_id)
                        elif event_type == 'result':
                            # 更新 token 使用量
                            usage = event.get('usage', {})
                            print(f"[Token] 收到 usage 数据: {usage}")
                            if usage:
                                # Claude CLI 返回的字段可能是 input_tokens 或 cache_read_input_tokens 等
                                input_tokens = usage.get('input_tokens', 0)
                                # 也可能是 cached_input_tokens
                                if input_tokens == 0:
                                    input_tokens = usage.get('cache_read_input_tokens', 0)

                                output_tokens = usage.get('output_tokens', 0)

                                session_token_usage['input'] += input_tokens
                                session_token_usage['output'] += output_tokens
                                session_token_usage['total'] = session_token_usage['input'] + session_token_usage['output']
                                cost = event.get('cost')
                                if cost:
                                    session_token_usage['cost'] += cost
                                socketio.emit('token-usage', session_token_usage)
                                print(f"[Token] 更新使用量: input={session_token_usage['input']}, output={session_token_usage['output']}, 本次: in={input_tokens}, out={output_tokens}")
                            socketio.emit('status-event', event, room=thread_id)
                        elif not is_private:
                            socketio.emit('event', event, room=thread_id)
                        else:
                            socketio.emit('status-event', event, room=thread_id)
                except Exception as e:
                    print(f'[Error] {e}')
                    traceback.print_exc()
                    socketio.emit('event', {'type': 'error', 'message': str(e)}, room=thread_id)
                finally:
                    # 确保所有 agent 状态都被重置
                    print(f'[ProcessInvoke] 完成，重置 agent 状态: {target_agents}')
                    for aid in target_agents:
                        if aid in agent_status_details:
                            agent_status_details[aid] = {
                                'status': 'idle',
                                'message': '等待召唤',
                                'lastUpdate': int(time.time() * 1000)
                            }
                            print(f"[状态广播] {aid}: idle - 等待召唤 (finally)")
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

        # 安全配置选项
        enable_security = data.get('enableSecurity', False)
        security_level = data.get('securityLevel', 'standard')
        agent_type = data.get('type', 'claude')  # claude 或 deepseek

        if not name:
            return jsonify({'error': '名称不能为空'}), 400

        agent_id = f"cat-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"

        agent_config = {
            'id': agent_id,
            'name': name,
            'avatar': avatar,
            'description': description,
            'systemPrompt': system_prompt,
            'voice': voice,
            'enableSecurity': enable_security,
            'securityLevel': security_level,
            'type': agent_type
        }

        # 根据 agent 类型创建不同的 Agent
        if agent_type == 'deepseek':
            try:
                from app.agents.deepseek import DeepSeekAgent
                new_agent = DeepSeekAgent(agent_config)
                print(f'[创建] 创建 DeepSeek 猫咪: {name}')
            except Exception as e:
                print(f'[创建] DeepSeek Agent 创建失败，回退到 Claude: {e}')
                new_agent = ClaudeAgent(agent_config)
        else:
            new_agent = ClaudeAgent(agent_config)

        # 如果启用安全功能，初始化安全架构
        if enable_security:
            try:
                from deepseek_cli.security import SecurityManager, SecurityConfig, IsolationLevel

                isolation_level = {
                    "none": IsolationLevel.NONE,
                    "basic": IsolationLevel.BASIC,
                    "standard": IsolationLevel.STANDARD,
                    "strict": IsolationLevel.STRICT,
                    "maximum": IsolationLevel.MAXIMUM,
                }.get(security_level, IsolationLevel.STANDARD)

                security_config = SecurityConfig(
                    enable_input_validation=True,
                    enable_permission_control=True,
                    enable_sandbox=True,
                    enable_monitoring=True,
                    enable_error_recovery=True,
                    enable_audit=True,
                    isolation_level=isolation_level,
                    auto_approve_safe_tools=True,
                )

                security_manager = SecurityManager(
                    config=security_config,
                    working_dir=os.getcwd(),
                    user_id=agent_id
                )

                # 将安全管理器附加到 agent
                new_agent.security_manager = security_manager
                print(f'[安全] 为猫咪 {name} 启用安全架构 (级别: {security_level})')

            except Exception as e:
                print(f'[安全] 安全架构初始化失败: {e}')
                import traceback
                traceback.print_exc()

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
            'voice': new_agent.voice,
            'enableSecurity': enable_security,
            'securityLevel': security_level,
            'type': agent_type
        }

        # 保存到存储
        storage.save_agent(agent_id, {
            'id': agent_id,
            'name': name,
            'avatar': avatar,
            'description': description,
            'systemPrompt': system_prompt,
            'voice': new_agent.voice,
            'enableSecurity': enable_security,
            'securityLevel': security_level,
            'type': agent_type
        })

        return jsonify({
            'status': 'created',
            'agent': {
                'id': agent_id,
                'name': name,
                'avatar': avatar,
                'description': description,
                'voice': new_agent.voice,
                'enableSecurity': enable_security,
                'securityLevel': security_level,
                'type': agent_type
            }
        })

    @app.route('/api/agents/<agent_id>', methods=['DELETE'])
    def delete_agent(agent_id):
        print(f"[删除] 请求删除: {agent_id}")
        print(f"[删除] dynamic_agents keys: {list(dynamic_agents.keys())}")
        print(f"[删除] agents keys: {list(agents.keys())}")

        if agent_id == 'opus':
            return jsonify({'error': '不能删除默认猫咪'}), 400

        if agent_id not in dynamic_agents:
            print(f"[删除] 猫咪 {agent_id} 不在 dynamic_agents 中")
            return jsonify({'error': '猫咪不存在', 'available': list(dynamic_agents.keys())}), 404

        del agents[agent_id]
        if agent_id in agent_status_details:
            del agent_status_details[agent_id]
        del dynamic_agents[agent_id]

        # 从存储中删除
        storage.delete_agent(agent_id)

        print(f"[删除] 成功删除: {agent_id}")
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

    # ===== 安全管理 API =====

    @app.route('/api/agents/<agent_id>/security')
    def get_agent_security(agent_id):
        """获取猫咪的安全配置和统计"""
        agent = agents.get(agent_id)
        if not agent:
            return jsonify({'error': '猫咪不存在'}), 404

        if not hasattr(agent, 'security_manager') or not agent.security_manager:
            return jsonify({
                'enabled': False,
                'message': '该猫咪未启用安全架构'
            })

        # 返回安全统计
        import asyncio
        try:
            loop = asyncio.new_event_loop()
            stats = loop.run_until_complete(agent.security_manager.get_stats())
            health = loop.run_until_complete(agent.security_manager.health_check())
            loop.close()

            return jsonify({
                'enabled': True,
                'stats': stats,
                'health': health
            })
        except Exception as e:
            return jsonify({
                'enabled': True,
                'error': str(e)
            })

    @app.route('/api/agents/<agent_id>/security/alerts')
    def get_agent_security_alerts(agent_id):
        """获取猫咪的安全告警"""
        agent = agents.get(agent_id)
        if not agent:
            return jsonify({'error': '猫咪不存在'}), 404

        if not hasattr(agent, 'security_manager') or not agent.security_manager:
            return jsonify({'alerts': []})

        alerts = agent.security_manager.get_active_alerts()
        return jsonify({
            'alerts': [alert.to_dict() for alert in alerts]
        })

    @app.route('/api/agents/<agent_id>/security/alerts/<alert_id>/acknowledge', methods=['POST'])
    def acknowledge_security_alert(agent_id, alert_id):
        """确认安全告警"""
        agent = agents.get(agent_id)
        if not agent:
            return jsonify({'error': '猫咪不存在'}), 404

        if not hasattr(agent, 'security_manager') or not agent.security_manager:
            return jsonify({'error': '该猫咪未启用安全架构'}), 400

        data = request.get_json() or {}
        acknowledged_by = data.get('acknowledgedBy', 'user')

        agent.security_manager.acknowledge_alert(alert_id, acknowledged_by)
        return jsonify({'status': 'acknowledged'})

    @app.route('/api/agents/<agent_id>/security/audit')
    def get_agent_audit_log(agent_id):
        """获取猫咪的审计日志"""
        agent = agents.get(agent_id)
        if not agent:
            return jsonify({'error': '猫咪不存在'}), 404

        if not hasattr(agent, 'security_manager') or not agent.security_manager:
            return jsonify({'events': []})

        # 获取查询参数
        limit = int(request.args.get('limit', 100))

        import asyncio
        try:
            loop = asyncio.new_event_loop()
            events = loop.run_until_complete(
                agent.security_manager.get_audit_events(limit=limit)
            )
            loop.close()

            return jsonify({
                'events': [event.to_dict() for event in events]
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/agents/<agent_id>/security/approve', methods=['POST'])
    def approve_agent_action(agent_id):
        """批准猫咪的待确认操作"""
        agent = agents.get(agent_id)
        if not agent:
            return jsonify({'error': '猫咪不存在'}), 404

        if not hasattr(agent, 'security_manager') or not agent.security_manager:
            return jsonify({'error': '该猫咪未启用安全架构'}), 400

        data = request.get_json() or {}
        execution_id = data.get('executionId')
        tool_name = data.get('toolName')
        arguments = data.get('arguments', {})

        if not execution_id or not tool_name:
            return jsonify({'error': '缺少必要参数'}), 400

        agent.security_manager.approve_permission(execution_id, tool_name, arguments)
        return jsonify({'status': 'approved'})

    @app.route('/api/agents/<agent_id>/security/deny', methods=['POST'])
    def deny_agent_action(agent_id):
        """拒绝猫咪的待确认操作"""
        agent = agents.get(agent_id)
        if not agent:
            return jsonify({'error': '猫咪不存在'}), 404

        if not hasattr(agent, 'security_manager') or not agent.security_manager:
            return jsonify({'error': '该猫咪未启用安全架构'}), 400

        data = request.get_json() or {}
        execution_id = data.get('executionId')
        tool_name = data.get('toolName')
        arguments = data.get('arguments', {})

        if not execution_id or not tool_name:
            return jsonify({'error': '缺少必要参数'}), 400

        agent.security_manager.deny_permission(execution_id, tool_name, arguments)
        return jsonify({'status': 'denied'})

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

    # ===== 对话角色配置 API =====

    @app.route('/api/threads/<thread_id>/roles')
    def get_thread_roles(thread_id):
        """获取对话的角色配置"""
        roles = storage.get_thread_roles(thread_id) or {}
        return jsonify(roles)

    @app.route('/api/threads/<thread_id>/roles', methods=['PUT'])
    def set_thread_roles(thread_id):
        """设置对话的角色配置 { agentId: roleDescription }"""
        data = request.get_json() or {}
        storage.save_thread_roles(thread_id, data)
        return jsonify({'status': 'ok', 'roles': data})

    # ===== 房间级猫咪记忆 API =====

    @app.route('/api/threads/<thread_id>/memory/<agent_id>')
    def get_thread_agent_memory(thread_id, agent_id):
        """获取房间内特定猫咪的记忆"""
        memory = storage.get_thread_agent_memory(thread_id, agent_id) or {}
        return jsonify(memory)

    @app.route('/api/threads/<thread_id>/memory/<agent_id>', methods=['PUT'])
    def set_thread_agent_memory(thread_id, agent_id):
        """设置房间内猫咪的记忆（完整替换）"""
        data = request.get_json() or {}
        storage.save_thread_agent_memory(thread_id, agent_id, data)
        return jsonify({'status': 'ok', 'memory': data})

    @app.route('/api/threads/<thread_id>/memory/<agent_id>', methods=['POST'])
    def add_thread_agent_memory(thread_id, agent_id):
        """添加一条房间内猫咪的记忆"""
        data = request.get_json() or {}
        key = data.get('key')
        value = data.get('value')

        if not key or not value:
            return jsonify({'error': 'key 和 value 不能为空'}), 400

        storage.add_thread_agent_memory_entry(thread_id, agent_id, key, value)
        memory = storage.get_thread_agent_memory(thread_id, agent_id)
        return jsonify({'status': 'ok', 'memory': memory})

    @app.route('/api/threads/<thread_id>/memory/<agent_id>/<key>', methods=['DELETE'])
    def delete_thread_agent_memory(thread_id, agent_id, key):
        """删除房间内猫咪的特定记忆"""
        storage.remove_thread_agent_memory_entry(thread_id, agent_id, key)
        return jsonify({'status': 'deleted'})

    # ===== MCP 服务器 API =====

    @app.route('/api/mcp/servers')
    def get_mcp_servers():
        """获取所有 MCP 服务器"""
        servers = mcp_manager.list_servers()
        return jsonify(servers)

    @app.route('/api/mcp/servers', methods=['POST'])
    def create_mcp_server():
        """添加 MCP 服务器"""
        data = request.get_json() or {}
        name = data.get('name')
        server_type = data.get('type', 'stdio')

        if not name:
            return jsonify({'error': '名称不能为空'}), 400

        server = mcp_manager.add_server({
            'name': name,
            'type': server_type,
            'command': data.get('command'),
            'args': data.get('args', []),
            'url': data.get('url'),
            'env': data.get('env', {})
        })

        return jsonify({
            'status': 'created',
            'server': {
                'id': server.id,
                'name': server.name,
                'type': server.type,
                'status': server.status
            }
        })

    @app.route('/api/mcp/servers/<server_id>', methods=['DELETE'])
    def delete_mcp_server(server_id):
        """删除 MCP 服务器"""
        if mcp_manager.remove_server(server_id):
            return jsonify({'status': 'deleted'})
        return jsonify({'error': '服务器不存在'}), 404

    @app.route('/api/mcp/servers/<server_id>/start', methods=['POST'])
    def start_mcp_server(server_id):
        """启动 MCP 服务器连接"""
        import asyncio
        try:
            loop = asyncio.new_event_loop()
            success = loop.run_until_complete(mcp_manager.start_server(server_id))
            loop.close()

            if success:
                server = mcp_manager.get_server(server_id)
                return jsonify({
                    'status': 'started',
                    'server': {
                        'id': server_id,
                        'status': server.status if server else 'unknown'
                    }
                })
            else:
                server = mcp_manager.get_server(server_id)
                return jsonify({
                    'error': '启动失败',
                    'errorMessage': server.error_message if server else 'Unknown error'
                }), 500
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/mcp/servers/<server_id>/stop', methods=['POST'])
    def stop_mcp_server(server_id):
        """停止 MCP 服务器连接"""
        import asyncio
        try:
            loop = asyncio.new_event_loop()
            success = loop.run_until_complete(mcp_manager.stop_server(server_id))
            loop.close()

            if success:
                return jsonify({'status': 'stopped'})
            return jsonify({'error': '停止失败'}), 500
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/mcp/servers/<server_id>/tools')
    def get_mcp_server_tools(server_id):
        """获取 MCP 服务器的工具列表"""
        import asyncio
        try:
            loop = asyncio.new_event_loop()
            tools = loop.run_until_complete(mcp_manager.list_tools(server_id))
            loop.close()
            return jsonify(tools)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/mcp/tools')
    def get_all_mcp_tools():
        """获取所有运行中 MCP 服务器的工具"""
        tools = mcp_manager.get_all_tools()
        return jsonify(tools)

    # ===== Skill API =====

    @app.route('/api/skills')
    def get_skills():
        """获取所有 Skill"""
        skills = skill_manager.list_skills()
        return jsonify(skills)

    @app.route('/api/skills', methods=['POST'])
    def create_skill():
        """创建 Skill"""
        data = request.get_json() or {}
        name = data.get('name')

        if not name:
            return jsonify({'error': '名称不能为空'}), 400

        skill = skill_manager.create_skill(data)
        return jsonify({
            'status': 'created',
            'skill': skill
        })

    @app.route('/api/skills/<skill_id>')
    def get_skill(skill_id):
        """获取 Skill 详情"""
        skill = skill_manager.get_skill(skill_id)
        if skill:
            return jsonify(skill)
        return jsonify({'error': 'Skill 不存在'}), 404

    @app.route('/api/skills/<skill_id>/prompt')
    def get_skill_prompt(skill_id):
        """获取 Prompt 类型 Skill 的提示内容"""
        skill = skill_manager.get_skill(skill_id)
        if not skill:
            return jsonify({'error': 'Skill 不存在'}), 404

        if skill.get('type') != 'prompt':
            return jsonify({'error': '该技能不是 prompt 类型'}), 400

        config = skill.get('config', {})
        prompt = config.get('prompt', '')
        triggers = skill.get('triggers', [])

        return jsonify({
            'success': True,
            'name': skill.get('name'),
            'description': skill.get('description'),
            'prompt': prompt,
            'triggers': triggers
        })

    @app.route('/api/skills/<skill_id>', methods=['PUT'])
    def update_skill(skill_id):
        """更新 Skill"""
        data = request.get_json() or {}
        skill = skill_manager.update_skill(skill_id, data)
        if skill:
            return jsonify({
                'status': 'updated',
                'skill': skill
            })
        return jsonify({'error': 'Skill 不存在'}), 404

    @app.route('/api/skills/<skill_id>', methods=['DELETE'])
    def delete_skill(skill_id):
        """删除 Skill"""
        if skill_manager.delete_skill(skill_id):
            return jsonify({'status': 'deleted'})
        return jsonify({'error': 'Skill 不存在'}), 404

    @app.route('/api/skills/templates')
    def get_skill_templates():
        """获取预定义模板"""
        templates = skill_manager.get_templates()
        return jsonify(templates)

    @app.route('/api/skills/from-template', methods=['POST'])
    def create_skill_from_template():
        """从模板创建 Skill"""
        data = request.get_json() or {}
        template_id = data.get('templateId')

        if not template_id:
            return jsonify({'error': '模板 ID 不能为空'}), 400

        try:
            skill = skill_manager.create_skill_from_template(
                template_id,
                {'name': data.get('name'), 'description': data.get('description'), 'config': data.get('config')}
            )
            return jsonify({
                'status': 'created',
                'skill': skill
            })
        except ValueError as e:
            return jsonify({'error': str(e)}), 404

    @app.route('/api/skills/<skill_id>/execute', methods=['POST'])
    def execute_skill(skill_id):
        """执行 Skill"""
        data = request.get_json() or {}
        params = data.get('params', {})

        import asyncio
        try:
            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(skill_manager.execute_skill(skill_id, params))
            loop.close()
            return jsonify(result)
        except ValueError as e:
            return jsonify({'error': str(e)}), 404
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/skills/<skill_id>/tool-definition')
    def get_skill_tool_definition(skill_id):
        """获取 Skill 的工具定义格式"""
        skill = skill_manager.get_skill(skill_id)
        if not skill:
            return jsonify({'error': 'Skill 不存在'}), 404

        definition = skill_manager.to_tool_definition(skill)
        return jsonify(definition)

    @app.route('/api/skills/by-trigger/<trigger_text>')
    def get_skill_by_trigger(trigger_text):
        """根据触发词查找匹配的技能"""
        skill = skill_manager.get_skill_by_trigger(trigger_text)
        if skill:
            return jsonify(skill)
        return jsonify({'error': '未找到匹配的技能', 'trigger': trigger_text}), 404

    @app.route('/api/skills/category/<category>')
    def get_skills_by_category(category):
        """获取指定分类的所有技能"""
        skills = skill_manager.get_skills_by_category(category)
        return jsonify(skills)

    @app.route('/api/skills/triggers')
    def get_all_skill_triggers():
        """获取所有技能的触发词映射"""
        triggers = skill_manager.get_all_triggers()
        return jsonify(triggers)

    @app.route('/api/skills/code-review')
    def get_code_review_skills():
        """获取所有 Code Review 相关的技能"""
        skills = skill_manager.get_skills_by_category('code_review')
        return jsonify({
            'skills': skills,
            'triggers': {k: v for k, v in skill_manager.get_all_triggers().items()
                        if skill_manager.get_skill(v) and skill_manager.get_skill(v).get('category') == 'code_review'}
        })

    # ===== 工具授权 API =====

    @app.route('/api/agents/<agent_id>/tools')
    def get_agent_tools(agent_id):
        """获取猫咪的工具授权"""
        tools = storage.get_agent_tools(agent_id)
        return jsonify(tools or {'mcpTools': [], 'skills': []})

    @app.route('/api/agents/<agent_id>/tools', methods=['PUT'])
    def update_agent_tools(agent_id):
        """更新猫咪的工具授权"""
        data = request.get_json() or {}
        mcp_tools = data.get('mcpTools', [])
        skills = data.get('skills', [])

        storage.save_agent_tools(agent_id, {
            'mcpTools': mcp_tools,
            'skills': skills
        })

        return jsonify({
            'status': 'updated',
            'tools': {
                'mcpTools': mcp_tools,
                'skills': skills
            }
        })

    @app.route('/api/agents/<agent_id>/tools', methods=['DELETE'])
    def delete_agent_tools(agent_id):
        """清除猫咪的工具授权"""
        storage.delete_agent_tools(agent_id)
        return jsonify({'status': 'deleted'})

    # ===== Skill 授权 API（按 Skill 维度管理）=====

    @app.route('/api/skills/<skill_id>/agents')
    def get_skill_assigned_agents(skill_id):
        """获取 Skill 授权给了哪些猫咪"""
        agent_ids = storage.get_skill_assignment(skill_id)
        # 获取完整的 agent 信息
        assigned_agents = []
        for agent_id in agent_ids:
            agent = agents.get(agent_id)
            if agent:
                assigned_agents.append({
                    'id': agent_id,
                    'name': agent.name,
                    'avatar': agent.avatar
                })
        return jsonify({'agents': assigned_agents})

    @app.route('/api/skills/<skill_id>/agents', methods=['PUT'])
    def update_skill_assigned_agents(skill_id):
        """更新 Skill 授权给哪些猫咪"""
        data = request.get_json() or {}
        agent_ids = data.get('agentIds', [])

        storage.save_skill_assignment(skill_id, agent_ids)

        return jsonify({
            'status': 'updated',
            'skillId': skill_id,
            'agentIds': agent_ids
        })

    @app.route('/api/skills/assignments')
    def get_all_skill_assignments():
        """获取所有 Skill 的授权配置"""
        assignments = storage.get_all_skill_assignments()
        # 添加 agent 详情
        result = {}
        for skill_id, agent_ids in assignments.items():
            result[skill_id] = []
            for agent_id in agent_ids:
                agent = agents.get(agent_id)
                if agent:
                    result[skill_id].append({
                        'id': agent_id,
                        'name': agent.name,
                        'avatar': agent.avatar
                    })
        return jsonify(result)

    @app.route('/api/agents/<agent_id>/skills')
    def get_agent_assigned_skills(agent_id):
        """获取猫咪被授权的所有 Skill"""
        skill_ids = storage.get_agent_skill_ids(agent_id)
        skills = []
        for skill_id in skill_ids:
            skill = skill_manager.get_skill(skill_id)
            if skill:
                skills.append(skill)
        return jsonify({'skills': skills})

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
    # 禁用 reloader 避免文件修改时服务重启导致请求中断
    socketio.run(app, host='0.0.0.0', port=PORT, debug=DEBUG, use_reloader=False, allow_unsafe_werkzeug=True)


if __name__ == '__main__':
    main()
