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
    def __init__(self, agents: Dict, storage):
        self.agents = agents  # { id: AgentInstance }
        self.storage = storage
        self.max_depth = 10
        self.max_agents_per_round = 5
        self.tracker = InvocationTracker()

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
        mention_regex = r'@([^\s@]+)'
        mentions = []
        clean_message = input_text

        for match in re.finditer(mention_regex, input_text):
            mention = match.group(1)
            agent_id = self.resolve_agent_id(mention)
            if agent_id:
                mentions.append(agent_id)
            clean_message = clean_message.replace(match.group(0), '')

        return {
            'mentions': list(set(mentions)),
            'message': clean_message.strip()
        }

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

        # 匹配模式：行首、标点后、或空格后的 @mention
        mention_regex = r'(?:^|[。！？，、；：""''（）\s])@([^\s@]+)'

        for match in re.finditer(mention_regex, cleaned_response, re.MULTILINE):
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
        """路由并执行 Agent 调用链"""
        self.tracker.start(thread_id, signal)

        # worklist
        worklist = [Task(agent_id=cat_id, request_message=message, depth=1)
                   for cat_id in initial_cats]

        agent_count: Dict[str, int] = {}
        call_chain: List[Dict] = []

        while worklist:
            # 检查取消信号
            if signal and signal.get('aborted', False):
                yield {'type': 'aborted', 'message': '用户取消', 'private': True}
                self.tracker.finish(thread_id)
                break

            task = worklist.pop(0)
            agent_id = task.agent_id
            caller_id = task.caller_id
            request_message = task.request_message
            current_depth = task.depth

            # 深度限制检查
            if current_depth > self.max_depth:
                print(f"[Router] 达到最大深度 {self.max_depth}，停止调度")
                yield {'type': 'depth-limit', 'depth': current_depth, 'maxDepth': self.max_depth, 'private': True}
                continue

            # 调用次数限制检查
            call_count = agent_count.get(agent_id, 0)
            if call_count >= self.max_agents_per_round:
                print(f"[Router] {agent_id} 已达到最大调用次数 {self.max_agents_per_round}，跳过")
                continue

            # 防止自调用
            if caller_id == agent_id:
                print(f"[Router] {agent_id} 不能呼叫自己，跳过")
                continue

            # 防止 A-B-A 循环
            recent_callers = [c['agentId'] for c in call_chain[-4:]]
            if caller_id and agent_id in recent_callers and caller_id in recent_callers:
                print(f"[Router] 检测到可能的 A-B-A 循环 ({caller_id} <-> {agent_id})，跳过")
                continue

            agent = self.agents.get(agent_id)
            if not agent:
                yield {'type': 'error', 'message': f'未知的猫咪: {agent_id}', 'private': True}
                continue

            # 记录调用
            agent_count[agent_id] = call_count + 1
            call_chain.append({'agentId': agent_id, 'callerId': caller_id, 'time': int(time.time() * 1000)})

            # 获取上下文（使用增强版）
            thread_context = ''
            pending_tool = None
            try:
                # 使用增强的上下文构建方法
                enhanced = self.storage.get_enhanced_context(thread_id, agent_id, max_messages=10)
                thread_context = self.storage.build_context_string(thread_id, agent_id, max_messages=10)
                pending_tool = enhanced.get('pending_tool')

                # 检查用户是否在确认待确认的操作（仅对第一个 agent 且没有 caller 时）
                if pending_tool and caller_id is None and self.is_confirmation_message(request_message, pending_tool):
                    print(f"[Router] 用户确认执行待确认工具: {pending_tool.get('name')}")
                    # 构建确认提示词
                    confirm_prompt = f"""
--- 待确认操作 ---
用户已确认执行以下操作：
工具: {pending_tool.get('name', 'unknown')}
参数: {json.dumps(pending_tool.get('input', {}), ensure_ascii=False)}
描述: {pending_tool.get('description', '无描述')}

请继续执行已确认的操作。
"""
                    thread_context = confirm_prompt + "\n" + thread_context
                    # 清除待确认工具
                    self.storage.clear_pending_tool(thread_id)
                elif pending_tool and caller_id is None and self.is_cancellation_message(request_message):
                    print(f"[Router] 用户取消待确认工具: {pending_tool.get('name')}")
                    self.storage.clear_pending_tool(thread_id)
                    # 返回取消确认消息
                    yield {
                        'type': 'complete',
                        'agentId': agent_id,
                        'response': f"已取消操作：{pending_tool.get('name', 'unknown')}",
                        'isA2A': False,
                        'processLogs': [],
                        'private': False
                    }
                    continue
            except Exception as e:
                print(f'[Router] 获取上下文失败: {e}')

            # 构建提示词
            caller = self.agents.get(caller_id) if caller_id else None

            if caller:
                prompt = self.build_a2a_context(caller, agent_id, request_message, thread_context, pending_tool)
            else:
                available_cats = [n for n in self.get_available_cat_names() if n != agent.name]

                # 获取长期记忆
                long_memory = None
                try:
                    long_memory = self.storage.get_long_memory(agent_id)
                except Exception:
                    pass

                # 构建长期记忆部分
                memory_section = ""
                if long_memory:
                    memory_items = {k: v for k, v in long_memory.items()
                                  if k not in ('updatedAt', 'createdAt')}
                    if memory_items:
                        memory_section = "\n--- 记住的信息 ---\n"
                        for key, value in memory_items.items():
                            memory_section += f"{key}: {value}\n"

                prompt = f"""{thread_context}
{memory_section}
[当前咖啡馆里还有这些猫咪可以协助: {'、'.join(available_cats)}]
[如果你需要其他猫咪的帮助，可以在回复末尾 @他们的名字]

用户消息: {request_message}"""

            # 发出开始事件
            yield {
                'type': 'start',
                'agent': agent.get_info(),
                'caller': caller.get_info() if caller else None,
                'isA2A': bool(caller),
                'private': True
            }

            full_response = ''
            process_logs = []

            try:
                # 流式调用 Agent
                async for event in agent.invoke(prompt, signal):
                    if signal and signal.get('aborted', False):
                        break

                    if event['type'] == 'status':
                        process_logs.append({'type': 'status', 'status': event['status'],
                                           'message': event['message'], 'time': int(time.time() * 1000)})
                        yield {'type': 'status', 'agentId': agent_id, **event}

                    elif event['type'] == 'text':
                        full_response += event['text']
                        yield {'type': 'stream', 'agentId': agent_id, 'text': event['text'], 'private': event.get('private', True)}

                    elif event['type'] == 'tool':
                        print(f"[Router] tool event: {event['name']}")
                        process_logs.append({'type': 'tool', 'name': event['name'],
                                           'input': event.get('input'), 'time': int(time.time() * 1000)})

                        # 如果工具需要确认，保存为待确认工具
                        if event.get('needsConfirmation'):
                            print(f"[Router] 检测到需要确认的工具: {event['name']}")
                            self.storage.save_pending_tool(thread_id, {
                                'name': event['name'],
                                'input': event.get('input', {}),
                                'description': event.get('description', ''),
                                'agentId': agent_id
                            })
                            # 发出待确认事件
                            yield {
                                'type': 'pending_confirmation',
                                'agentId': agent_id,
                                'tool': event['name'],
                                'description': event.get('description', ''),
                                'input': event.get('input', {}),
                                'private': False
                            }

                        yield {'type': 'tool', 'agentId': agent_id, **event}

                    elif event['type'] == 'result':
                        yield {'type': 'result', 'agentId': agent_id, **event}

                    elif event['type'] == 'done':
                        full_response = event['response']

                    elif event['type'] == 'thinking':
                        process_logs.append({'type': 'thinking', 'text': event['text'],
                                           'time': int(time.time() * 1000)})
                        yield {'type': 'thinking', 'agentId': agent_id, 'text': event['text'], 'private': True}

                # 保存消息
                self.storage.save_message(thread_id, agent_id, full_response, 'assistant', process_logs)

                # 发出完成事件
                yield {
                    'type': 'complete',
                    'agentId': agent_id,
                    'response': full_response,
                    'isA2A': bool(caller),
                    'processLogs': process_logs,
                    'private': False
                }

                # 检测 @mentions 并追加到 worklist（A2A）
                mentions = self.parse_mentions(full_response)
                max_a2a_per_response = 3
                added_a2a = 0

                for mention in mentions:
                    if mention == agent_id:
                        continue

                    target_count = agent_count.get(mention, 0)
                    if target_count >= self.max_agents_per_round:
                        print(f"[Router] A2A 跳过: {mention} 已达调用上限")
                        continue

                    if mention in self.agents:
                        agent_name = self.agents[mention].name
                        print(f"[Router] A2A: {agent.name} -> {agent_name}")
                        worklist.append(Task(
                            agent_id=mention,
                            caller_id=agent_id,
                            request_message=request_message,
                            depth=current_depth + 1
                        ))
                        added_a2a += 1
                        if added_a2a >= max_a2a_per_response:
                            break

            except Exception as e:
                print(f'[Router] Agent 调用错误: {e}')
                yield {'type': 'error', 'agentId': agent_id, 'message': str(e), 'private': True}

        # 发出最终完成事件
        self.tracker.finish(thread_id)

        yield {
            'type': 'done',
            'isFinal': True,
            'callChain': [{'agentId': c['agentId'], 'callerId': c['callerId'],
                          'agentName': self.agents[c['agentId']].name}
                         for c in call_chain],
            'totalCalls': sum(agent_count.values()),
            'agentStats': dict(agent_count),
            'private': False
        }

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
