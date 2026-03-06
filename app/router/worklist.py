"""
Worklist 调度器
实现基于工作列表的 Agent 调度，支持 A2A (Agent-to-Agent) 通信
"""
import re
import time
import json
from typing import Dict, List, Optional, AsyncGenerator, Any
from dataclasses import dataclass, field


@dataclass
class Task:
    agent_id: str
    caller_id: Optional[str] = None
    request_message: Optional[str] = None
    depth: int = 1


class InvocationTracker:
    """调用追踪器"""
    def __init__(self):
        self.invocations: Dict[str, Dict] = {}

    def start(self, thread_id: str, signal: Dict = None):
        self.invocations[thread_id] = {
            'worklist': [],
            'signal': signal,
            'status': 'running',
            'startTime': int(time.time() * 1000)
        }

    def get(self, thread_id: str) -> Optional[Dict]:
        return self.invocations.get(thread_id)

    def finish(self, thread_id: str):
        if thread_id in self.invocations:
            del self.invocations[thread_id]


class WorklistRouter:
    def __init__(self, agents: Dict, storage, agent_status_getter=None):
        self.agents = agents  # { id: AgentInstance }
        self.storage = storage
        self.max_depth = 10  # 最大 A2A 调用深度
        self.max_agents_per_round = 20  # 每个 agent 最大被调用次数
        self.tracker = InvocationTracker()
        self.agent_status_getter = agent_status_getter  # 获取其他猫咪状态的回调函数

    def get_other_agents_status(self, current_agent_id: str) -> str:
        """获取其他猫咪的状态描述"""
        if not self.agent_status_getter:
            return ""

        status_info = self.agent_status_getter()
        if not status_info:
            return ""

        other_status = []
        for agent_id, status in status_info.items():
            if agent_id != current_agent_id and agent_id in self.agents:
                agent = self.agents[agent_id]
                status_text = status.get('status', 'idle')
                message = status.get('message', '')

                # 翻译状态
                status_map = {
                    'idle': '空闲',
                    'thinking': '思考中',
                    'streaming': '回复中',
                    'tool': '使用工具中'
                }
                status_cn = status_map.get(status_text, status_text)

                if status_text != 'idle':
                    other_status.append(f"  - {agent.name}: {status_cn}（{message}）")

        if other_status:
            return "\n--- 其他猫咪当前状态 ---\n" + "\n".join(other_status) + "\n"
        return ""

    def resolve_agent_id(self, name_or_id: str) -> Optional[str]:
        """根据名称或 ID 查找 Agent ID"""
        if name_or_id in self.agents:
            return name_or_id

        for agent_id, agent in self.agents.items():
            if agent.name == name_or_id:
                return agent_id

        return None

    def get_available_cat_names(self) -> List[str]:
        """获取所有可用的猫咪名称列表"""
        return [agent.name for agent in self.agents.values()]

    def parse_input(self, input_text: str) -> Dict:
        """解析用户输入中的 @mentions"""
        # 匹配 @ 后面的名称，遇到空格、@、标点符号时停止
        # 支持中文、英文、数字、下划线、连字符
        mention_regex = r'@([\w\u4e00-\u9fff\-]+)'
        mentions = []
        clean_message = input_text

        print(f"[Router.parse_input] 开始解析: {input_text[:100]}...")
        print(f"[Router.parse_input] 可用 agents: {list(self.agents.keys())}")
        print(f"[Router.parse_input] 可用猫名: {self.get_available_cat_names()}")

        for match in re.finditer(mention_regex, input_text):
            mention = match.group(1)
            print(f"[Router.parse_input] 发现 @提及: {mention}")

            # 检查是否是 @全体成员
            if mention in ('全体成员', '所有人', 'all', '大家'):
                # 添加所有猫咪
                all_agents = list(self.agents.keys())
                mentions.extend(all_agents)
                print(f"[Router.parse_input] 解析 @全体成员 -> {all_agents}")
            else:
                agent_id = self.resolve_agent_id(mention)
                if agent_id:
                    mentions.append(agent_id)
                    print(f"[Router.parse_input] 解析 @提及: @{mention} -> {agent_id}")
                else:
                    print(f"[Router.parse_input] 无法解析 @{mention}，未找到对应 agent")

            clean_message = clean_message.replace(match.group(0), '')

        result = {
            'mentions': list(set(mentions)),
            'message': clean_message.strip()
        }
        print(f"[Router.parse_input] 解析结果: mentions={result['mentions']}")
        return result

    def strip_code_blocks(self, text: str) -> str:
        """移除代码块和内联代码"""
        # 移除 fenced code blocks
        cleaned = re.sub(r'```[\s\S]*?```', '', text)
        # 移除 indented code blocks
        cleaned = re.sub(r'^(    |\t).*$', '', cleaned, flags=re.MULTILINE)
        # 移除 inline code
        cleaned = re.sub(r'`[^`]+`', '', cleaned)
        return cleaned

    def parse_mentions(self, response: str) -> List[str]:
        """解析回复中的 @mentions（A2A 调用）"""
        cleaned_response = self.strip_code_blocks(response)
        mentions = []

        # 简化的匹配模式：@ 后面跟着中文、英文、数字、下划线、连字符
        # 遇到空格、标点符号时停止
        mention_regex = r'@([\w\u4e00-\u9fff\-]+)'

        for match in re.finditer(mention_regex, cleaned_response):
            mention = match.group(1)
            agent_id = self.resolve_agent_id(mention)
            if agent_id:
                mentions.append(agent_id)
                print(f"[Router] 解析到 A2A mention: @{mention} -> {agent_id}")

        return list(dict.fromkeys(mentions))  # 去重但保持顺序

    def build_a2a_context(self, caller_agent, target_agent_id: str,
                          original_message: str, thread_context: str,
                          pending_tool: Dict = None) -> str:
        """构建 A2A 调用的上下文"""
        target_agent = self.agents[target_agent_id]
        available_cats = [n for n in self.get_available_cat_names() if n != target_agent.name]

        # 如果有待确认的工具，添加确认提示
        confirm_section = ""
        if pending_tool:
            confirm_section = f"""
--- 待确认操作 ---
用户已确认执行以下操作：
工具: {pending_tool.get('name', 'unknown')}
参数: {json.dumps(pending_tool.get('input', {}), ensure_ascii=False)}
请继续执行已确认的操作。
"""

        return f"""[系统消息: {caller_agent.name} 正在呼叫 {target_agent.name}]

{caller_agent.name} 说："{original_message}"

---
[你是 {target_agent.name}，被 {caller_agent.name} 呼叫来协助]
[当前咖啡馆里还有这些猫咪可以协助: {'、'.join(available_cats)}]
[如果你需要其他猫咪的帮助，可以在回复末尾 @他们的名字]
[例如: "这个问题我不太擅长，@{available_cats[0] if available_cats else '布偶猫'} 可能更清楚"]
{confirm_section}
--- 历史对话记录 ---
{thread_context}
--- 历史对话结束 ---

请回复 {caller_agent.name} 的请求。"""

    async def route(self, initial_cats: List[str], message: str,
                   thread_id: str, signal: Dict = None) -> AsyncGenerator[Dict, None]:
        """路由并执行 Agent 调用链，支持并行执行"""
        import asyncio

        self.tracker.start(thread_id, signal)

        agent_count: Dict[str, int] = {}
        call_chain: List[Dict] = []
        event_queue = asyncio.Queue()

        # 用于跟踪并行任务
        running_tasks = set()

        async def invoke_agent_task(task: Task):
            """单个 agent 的调用任务"""
            agent_id = task.agent_id
            caller_id = task.caller_id
            request_message = task.request_message
            current_depth = task.depth

            # 检查取消信号
            if signal and signal.get('aborted', False):
                return

            # 深度限制检查
            if current_depth > self.max_depth:
                await event_queue.put({'type': 'depth-limit', 'depth': current_depth, 'maxDepth': self.max_depth, 'private': True})
                return

            # 调用次数限制检查
            call_count = agent_count.get(agent_id, 0)
            if call_count >= self.max_agents_per_round:
                print(f"[Router] {agent_id} 已达到最大调用次数 {self.max_agents_per_round}，跳过")
                return

            # 防止自调用
            if caller_id == agent_id:
                print(f"[Router] {agent_id} 不能呼叫自己，跳过")
                return

            agent = self.agents.get(agent_id)
            if not agent:
                await event_queue.put({'type': 'error', 'message': f'未知的猫咪: {agent_id}', 'private': True})
                return

            # 记录调用
            agent_count[agent_id] = call_count + 1
            call_chain.append({'agentId': agent_id, 'callerId': caller_id, 'time': int(time.time() * 1000)})

            # 获取上下文
            thread_context = ''
            pending_tool = None
            try:
                enhanced = self.storage.get_enhanced_context(thread_id, agent_id, max_messages=10)
                thread_context = self.storage.build_context_string(thread_id, agent_id, max_messages=10)
                pending_tool = enhanced.get('pending_tool')

                if pending_tool and caller_id is None and self.is_confirmation_message(request_message, pending_tool):
                    print(f"[Router] 用户确认执行待确认工具: {pending_tool.get('name')}")
                    confirm_prompt = f"""
--- 待确认操作 ---
用户已确认执行以下操作：
工具: {pending_tool.get('name', 'unknown')}
参数: {json.dumps(pending_tool.get('input', {}), ensure_ascii=False)}
描述: {pending_tool.get('description', '无描述')}

请继续执行已确认的操作。
"""
                    thread_context = confirm_prompt + "\n" + thread_context
                    self.storage.clear_pending_tool(thread_id)
                elif pending_tool and caller_id is None and self.is_cancellation_message(request_message):
                    print(f"[Router] 用户取消待确认工具: {pending_tool.get('name')}")
                    self.storage.clear_pending_tool(thread_id)
                    await event_queue.put({
                        'type': 'complete',
                        'agentId': agent_id,
                        'response': f"已取消操作：{pending_tool.get('name', 'unknown')}",
                        'isA2A': False,
                        'processLogs': [],
                        'private': False
                    })
                    return
            except Exception as e:
                print(f'[Router] 获取上下文失败: {e}')

            # 构建提示词
            caller = self.agents.get(caller_id) if caller_id else None

            # 获取角色配置和房间级记忆
            thread_roles = {}
            thread_agent_memory = {}
            try:
                thread_roles = self.storage.get_thread_roles(thread_id) or {}
                thread_agent_memory = self.storage.get_thread_agent_memory(thread_id, agent_id) or {}
            except Exception:
                pass

            # 构建角色描述部分
            role_section = ""
            if thread_roles:
                # 获取当前猫咪的角色
                current_role = thread_roles.get(agent_id)
                if current_role:
                    role_section = f"\n--- 你的角色 ---\n在这个对话中，你的角色是: {current_role}\n"

                # 获取其他猫咪的角色
                other_roles = []
                for aid, role in thread_roles.items():
                    if aid != agent_id and aid in self.agents:
                        other_agent = self.agents[aid]
                        other_roles.append(f"  - {other_agent.name}: {role}")
                if other_roles:
                    role_section += "\n其他猫咪的角色:\n" + "\n".join(other_roles) + "\n"

            # 构建房间级记忆部分
            room_memory_section = ""
            if thread_agent_memory:
                memory_items = {k: v for k, v in thread_agent_memory.items()
                              if k not in ('updatedAt', 'createdAt')}
                if memory_items:
                    room_memory_section = "\n--- 房间记忆（这个对话中的专属记忆） ---\n"
                    for key, value in memory_items.items():
                        room_memory_section += f"{key}: {value}\n"

            # 获取其他猫咪的状态
            other_status = self.get_other_agents_status(agent_id)

            if caller:
                prompt = self.build_a2a_context(caller, agent_id, request_message, thread_context, pending_tool)
                # 在 A2A 调用中也添加角色信息
                if role_section:
                    prompt = role_section + "\n" + prompt
                if room_memory_section:
                    prompt = room_memory_section + "\n" + prompt
            else:
                available_cats = [n for n in self.get_available_cat_names() if n != agent.name]
                long_memory = None
                try:
                    long_memory = self.storage.get_long_memory(agent_id)
                except Exception:
                    pass

                memory_section = ""
                if long_memory:
                    memory_items = {k: v for k, v in long_memory.items()
                                  if k not in ('updatedAt', 'createdAt')}
                    if memory_items:
                        memory_section = "\n--- 记住的信息 ---\n"
                        for key, value in memory_items.items():
                            memory_section += f"{key}: {value}\n"

                prompt = f"""{thread_context}
{memory_section}{room_memory_section}{role_section}{other_status}[当前咖啡馆里还有这些猫咪可以协助: {'、'.join(available_cats)}]
[如果你需要其他猫咪的帮助，可以在回复末尾 @他们的名字]

用户消息: {request_message}"""

            # 发出开始事件
            await event_queue.put({
                'type': 'start',
                'agent': agent.get_info(),
                'caller': caller.get_info() if caller else None,
                'isA2A': bool(caller),
                'private': False
            })

            full_response = ''
            process_logs = []

            try:
                async for event in agent.invoke(prompt, signal):
                    if signal and signal.get('aborted', False):
                        break

                    event['agentId'] = agent_id

                    if event['type'] == 'status':
                        process_logs.append({'type': 'status', 'status': event['status'],
                                           'message': event['message'], 'time': int(time.time() * 1000)})
                    elif event['type'] == 'text':
                        full_response += event['text']
                    elif event['type'] == 'tool':
                        print(f"[Router] tool event: {event['name']}")
                        process_logs.append({'type': 'tool', 'name': event['name'],
                                           'input': event.get('input'), 'time': int(time.time() * 1000)})
                        if event.get('needsConfirmation'):
                            print(f"[Router] 检测到需要确认的工具: {event['name']}")
                            self.storage.save_pending_tool(thread_id, {
                                'name': event['name'],
                                'input': event.get('input', {}),
                                'description': event.get('description', ''),
                                'agentId': agent_id
                            })
                    elif event['type'] == 'done':
                        full_response = event['response']
                    elif event['type'] == 'thinking':
                        process_logs.append({'type': 'thinking', 'text': event['text'],
                                           'time': int(time.time() * 1000)})

                    await event_queue.put(event)

                # 保存消息
                self.storage.save_message(thread_id, agent_id, full_response, 'assistant', process_logs)

                # 发出完成事件
                await event_queue.put({
                    'type': 'complete',
                    'agentId': agent_id,
                    'response': full_response,
                    'isA2A': bool(caller),
                    'processLogs': process_logs,
                    'private': False
                })

                # 检测 @mentions 并添加 A2A 任务（串行执行，避免复杂性）
                mentions = self.parse_mentions(full_response)
                print(f"[Router] {agent.name} 回复中的 A2A mentions: {mentions}")
                print(f"[Router] 当前调用次数统计: {agent_count}")
                max_a2a_per_response = 3
                added_a2a = 0

                for mention in mentions:
                    if mention == agent_id:
                        print(f"[Router] 跳过自调用: {agent.name} -> {agent.name}")
                        continue
                    target_count = agent_count.get(mention, 0)
                    if target_count >= self.max_agents_per_round:
                        print(f"[Router] 跳过已达到上限的 agent: {mention}")
                        continue
                    if mention in self.agents:
                        target_agent = self.agents[mention]
                        print(f"[Router] ========== A2A 调用 ==========")
                        print(f"[Router] A2A: {agent.name} -> {target_agent.name}, 深度: {current_depth + 1}")
                        # A2A 任务串行执行
                        async for event in self.invoke_single_agent(Task(
                            agent_id=mention,
                            caller_id=agent_id,
                            request_message=request_message,
                            depth=current_depth + 1
                        ), agent_count, call_chain, signal, thread_id):
                            await event_queue.put(event)
                        added_a2a += 1
                        if added_a2a >= max_a2a_per_response:
                            break
                    else:
                        print(f"[Router] A2A 目标不存在: {mention}")

            except Exception as e:
                print(f'[Router] Agent 调用错误: {e}')
                await event_queue.put({'type': 'error', 'agentId': agent_id, 'message': str(e), 'private': True})

        # 启动并行任务
        print(f"[Router.route] ========== 开始调度 ==========")
        print(f"[Router.route] initial_cats = {initial_cats}")
        print(f"[Router.route] 将并行启动 {len(initial_cats)} 个 agent 任务")
        initial_tasks = [Task(agent_id=cat_id, request_message=message, depth=1)
                        for cat_id in initial_cats]

        for i, task in enumerate(initial_tasks):
            agent = self.agents.get(task.agent_id)
            agent_name = agent.name if agent else task.agent_id
            print(f"[Router.route] 启动任务 {i+1}: agent_id={task.agent_id}, name={agent_name}")
            t = asyncio.create_task(invoke_agent_task(task))
            running_tasks.add(t)
            t.add_done_callback(running_tasks.discard)

        # 从队列中 yield 事件
        while running_tasks or not event_queue.empty():
            if signal and signal.get('aborted', False):
                yield {'type': 'aborted', 'message': '用户取消', 'private': True}
                break

            try:
                event = await asyncio.wait_for(event_queue.get(), timeout=0.1)
                yield event
            except asyncio.TimeoutError:
                continue

        self.tracker.finish(thread_id)

        yield {
            'type': 'done',
            'isFinal': True,
            'callChain': [{'agentId': c['agentId'], 'callerId': c['callerId'],
                          'agentName': self.agents[c['agentId']].name}
                         for c in call_chain if c['agentId'] in self.agents],
            'totalCalls': sum(agent_count.values()),
            'agentStats': dict(agent_count),
            'private': False
        }

    async def invoke_single_agent(self, task: Task, agent_count: Dict, call_chain: List,
                                   signal: Dict, thread_id: str) -> AsyncGenerator[Dict, None]:
        """串行调用单个 agent（用于 A2A）"""
        agent_id = task.agent_id
        caller_id = task.caller_id
        request_message = task.request_message
        current_depth = task.depth

        if signal and signal.get('aborted', False):
            return

        if current_depth > self.max_depth:
            return

        call_count = agent_count.get(agent_id, 0)
        if call_count >= self.max_agents_per_round:
            return

        if caller_id == agent_id:
            return

        agent = self.agents.get(agent_id)
        if not agent:
            return

        agent_count[agent_id] = call_count + 1
        call_chain.append({'agentId': agent_id, 'callerId': caller_id, 'time': int(time.time() * 1000)})

        thread_context = ''
        try:
            thread_context = self.storage.build_context_string(thread_id, agent_id, max_messages=10)
        except Exception:
            pass

        caller = self.agents.get(caller_id) if caller_id else None
        prompt = self.build_a2a_context(caller, agent_id, request_message, thread_context, None)

        yield {
            'type': 'start',
            'agent': agent.get_info(),
            'caller': caller.get_info() if caller else None,
            'isA2A': True,
            'private': False
        }

        full_response = ''
        process_logs = []

        try:
            async for event in agent.invoke(prompt, signal):
                event['agentId'] = agent_id
                if event['type'] == 'status':
                    process_logs.append({'type': 'status', 'status': event['status'],
                                       'message': event['message'], 'time': int(time.time() * 1000)})
                elif event['type'] == 'text':
                    full_response += event['text']
                elif event['type'] == 'tool':
                    process_logs.append({'type': 'tool', 'name': event['name'],
                                       'input': event.get('input'), 'time': int(time.time() * 1000)})
                elif event['type'] == 'done':
                    full_response = event['response']
                elif event['type'] == 'thinking':
                    process_logs.append({'type': 'thinking', 'text': event['text'],
                                       'time': int(time.time() * 1000)})
                yield event

            self.storage.save_message(thread_id, agent_id, full_response, 'assistant', process_logs)

            yield {
                'type': 'complete',
                'agentId': agent_id,
                'response': full_response,
                'isA2A': True,
                'processLogs': process_logs,
                'private': False
            }
        except Exception as e:
            print(f'[Router] A2A Agent 调用错误: {e}')
            yield {'type': 'error', 'agentId': agent_id, 'message': str(e), 'private': True}

    def get_available_agents(self) -> List[Dict]:
        """获取所有可用 Agent 信息"""
        return [agent.get_info() for agent in self.agents.values()]

    def is_confirmation_message(self, message: str, pending_tool: Dict) -> bool:
        """检测用户消息是否是对待确认操作的确认"""
        if not pending_tool:
            return False

        # 确认关键词
        confirm_keywords = [
            '确认', 'confirm', 'yes', 'y', 'ok', '好的', '可以', '执行',
            '同意', '继续', 'proceed', '同意执行', '没问题'
        ]

        # 取消关键词
        cancel_keywords = [
            '取消', 'cancel', 'no', 'n', '不', '不要', '拒绝', '放弃',
            'abort', 'stop', '停止', '不行'
        ]

        msg_lower = message.strip().lower()

        # 检查是否是取消
        for keyword in cancel_keywords:
            if keyword in msg_lower or msg_lower == keyword:
                return False  # 这是取消，不是确认

        # 检查是否是确认
        for keyword in confirm_keywords:
            if keyword in msg_lower or msg_lower == keyword:
                return True

        # 如果消息很短（< 5 个字符）且不是取消，可能是确认
        if len(msg_lower) < 5 and not any(k in msg_lower for k in cancel_keywords):
            return True

        return False

    def is_cancellation_message(self, message: str) -> bool:
        """检测用户消息是否是取消操作"""
        cancel_keywords = [
            '取消', 'cancel', 'no', 'n', '不', '不要', '拒绝', '放弃',
            'abort', 'stop', '停止', '不行'
        ]
        msg_lower = message.strip().lower()
        return any(keyword in msg_lower for keyword in cancel_keywords)
