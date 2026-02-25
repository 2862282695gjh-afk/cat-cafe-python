"""
Worklist 调度器
实现基于工作列表的 Agent 调度，支持 A2A (Agent-to-Agent) 通信
"""
import re
import time
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
                          original_message: str, thread_context: str) -> str:
        """构建 A2A 调用的上下文"""
        target_agent = self.agents[target_agent_id]
        available_cats = [n for n in self.get_available_cat_names() if n != target_agent.name]

        return f"""[系统消息: {caller_agent.name} 正在呼叫 {target_agent.name}]

{caller_agent.name} 说："{original_message}"

---
[你是 {target_agent.name}，被 {caller_agent.name} 呼叫来协助]
[当前咖啡馆里还有这些猫咪可以协助: {'、'.join(available_cats)}]
[如果你需要其他猫咪的帮助，可以在回复末尾 @他们的名字]
[例如: "这个问题我不太擅长，@{available_cats[0] if available_cats else '布偶猫'} 可能更清楚"]

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

            # 获取上下文
            thread_context = ''
            try:
                thread_context = await self.storage.get_context(thread_id)
            except Exception as e:
                print(f'[Router] 获取上下文失败: {e}')

            # 构建提示词
            caller = self.agents.get(caller_id) if caller_id else None

            if caller:
                prompt = self.build_a2a_context(caller, agent_id, request_message, thread_context)
            else:
                available_cats = [n for n in self.get_available_cat_names() if n != agent.name]
                prompt = f"""{thread_context}

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
                await self.storage.save_message(thread_id, agent_id, full_response, 'assistant', process_logs)

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
