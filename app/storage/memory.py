"""
内存存储（用于测试，不依赖 Redis）
"""
import json
import time
import uuid
import random
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field


@dataclass
class Message:
    id: str
    thread_id: str
    agent_id: str
    role: str
    content: str
    timestamp: int
    process_logs: List[Dict] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'threadId': self.thread_id,
            'agentId': self.agent_id,
            'role': self.role,
            'content': self.content,
            'timestamp': self.timestamp,
            'processLogs': self.process_logs
        }


class MemoryStorage:
    def __init__(self):
        self.threads: Dict[str, List[Message]] = {}
        self.thread_metas: Dict[str, Dict] = {}
        self.thread_list: set = set()
        # 会话状态存储
        self.session_states: Dict[str, Dict] = {}
        # 待确认工具存储
        self.pending_tools: Dict[str, Dict] = {}
        # 长期记忆存储
        self.long_memories: Dict[str, Dict] = {}

    def save_message(self, thread_id: str, agent_id: str, content: str,
                    role: str = 'assistant', process_logs: List[Dict] = None) -> Message:
        key = f"thread:{thread_id}"
        if key not in self.threads:
            self.threads[key] = []

        message = Message(
            id=f"{int(time.time() * 1000)}-{random.randint(100000, 999999)}",
            thread_id=thread_id,
            agent_id=agent_id,
            role=role,
            content=content,
            timestamp=int(time.time() * 1000),
            process_logs=process_logs or []
        )

        self.threads[key].append(message)

        # 更新线程元信息
        self.thread_list.add(thread_id)
        meta = self.thread_metas.get(thread_id, {})
        if not meta.get('title') and role == 'user':
            meta['title'] = content[:30] + ('...' if len(content) > 30 else '')
        meta['lastActivity'] = int(time.time() * 1000)
        self.set_thread_meta(thread_id, meta)

        return message

    def get_messages(self, thread_id: str) -> List[Dict]:
        key = f"thread:{thread_id}"
        messages = self.threads.get(key, [])
        return [m.to_dict() for m in messages]

    def get_context(self, thread_id: str) -> str:
        messages = self.get_messages(thread_id)
        if not messages:
            return ''

        lines = []
        for msg in messages:
            prefix = '用户' if msg['role'] == 'user' else f"[{msg['agentId']}]"
            lines.append(f"{prefix}: {msg['content']}")

        return '\n\n'.join(lines) + '\n\n'

    def clear_thread(self, thread_id: str):
        key = f"thread:{thread_id}"
        self.threads.pop(key, None)
        self.thread_metas.pop(thread_id, None)
        self.thread_list.discard(thread_id)

    def get_all_threads(self) -> List[Dict]:
        threads = []
        for thread_id in self.thread_list:
            meta = self.get_thread_meta(thread_id)
            threads.append({
                'id': thread_id,
                **(meta or {})
            })

        # 按最后活跃时间倒序排列
        def get_time(t):
            return t.get('lastActivity') or t.get('updatedAt') or 0
        return sorted(threads, key=get_time, reverse=True)

    def get_thread_meta(self, thread_id: str) -> Optional[Dict]:
        return self.thread_metas.get(thread_id)

    def set_thread_meta(self, thread_id: str, meta: Dict):
        self.thread_list.add(thread_id)
        existing = self.thread_metas.get(thread_id, {})
        updated = {
            **existing,
            **meta,
            'updatedAt': int(time.time() * 1000)
        }
        if not existing.get('createdAt'):
            updated['createdAt'] = updated['updatedAt']
        self.thread_metas[thread_id] = updated

    # 异步兼容方法
    async def save_message_async(self, *args, **kwargs):
        return self.save_message(*args, **kwargs)

    async def get_messages_async(self, *args, **kwargs):
        return self.get_messages(*args, **kwargs)

    async def get_context_async(self, *args, **kwargs):
        return self.get_context(*args, **kwargs)

    async def clear_thread_async(self, *args, **kwargs):
        return self.clear_thread(*args, **kwargs)

    async def get_all_threads_async(self, *args, **kwargs):
        return self.get_all_threads(*args, **kwargs)

    async def get_thread_meta_async(self, *args, **kwargs):
        return self.get_thread_meta(*args, **kwargs)

    async def set_thread_meta_async(self, *args, **kwargs):
        return self.set_thread_meta(*args, **kwargs)

    # ===== 会话状态管理 =====
    def save_session_state(self, thread_id: str, state: Dict):
        """保存会话状态"""
        self.session_states[thread_id] = {
            **state,
            'updatedAt': int(time.time() * 1000)
        }

    def get_session_state(self, thread_id: str) -> Optional[Dict]:
        """获取会话状态"""
        return self.session_states.get(thread_id)

    def clear_session_state(self, thread_id: str):
        """清除会话状态"""
        self.session_states.pop(thread_id, None)

    # ===== 待确认工具管理 =====
    def save_pending_tool(self, thread_id: str, tool_call: Dict):
        """保存待确认的工具调用"""
        self.pending_tools[thread_id] = {
            **tool_call,
            'savedAt': int(time.time() * 1000)
        }

    def get_pending_tool(self, thread_id: str) -> Optional[Dict]:
        """获取待确认的工具调用"""
        return self.pending_tools.get(thread_id)

    def clear_pending_tool(self, thread_id: str):
        """清除待确认的工具调用"""
        self.pending_tools.pop(thread_id, None)

    # ===== 长期记忆管理 =====
    def save_long_memory(self, agent_id: str, memory: Dict):
        """保存长期记忆（完整替换）"""
        self.long_memories[agent_id] = {
            **memory,
            'updatedAt': int(time.time() * 1000)
        }

    def get_long_memory(self, agent_id: str) -> Optional[Dict]:
        """获取长期记忆"""
        return self.long_memories.get(agent_id)

    def add_memory_entry(self, agent_id: str, key: str, value: str):
        """添加一条长期记忆"""
        existing = self.long_memories.get(agent_id, {})
        existing[key] = value
        existing['updatedAt'] = int(time.time() * 1000)
        self.long_memories[agent_id] = existing

    def remove_memory_entry(self, agent_id: str, key: str):
        """删除一条长期记忆"""
        existing = self.long_memories.get(agent_id, {})
        if key in existing:
            del existing[key]
            existing['updatedAt'] = int(time.time() * 1000)
            self.long_memories[agent_id] = existing

    # ===== 增强上下文构建 =====
    def get_enhanced_context(self, thread_id: str, agent_id: str = None,
                            max_messages: int = 10) -> Dict:
        """获取增强的上下文信息"""
        messages = self.get_messages(thread_id)
        pending = self.get_pending_tool(thread_id)

        result = {
            'messages': messages[-max_messages:] if messages else [],
            'pending_tool': pending,
            'has_pending': pending is not None
        }

        # 如果指定了 agent_id，也获取长期记忆
        if agent_id:
            result['long_memory'] = self.get_long_memory(agent_id)

        return result

    def build_context_string(self, thread_id: str, agent_id: str = None,
                            max_messages: int = 10) -> str:
        """构建上下文字符串（用于 prompt）"""
        enhanced = self.get_enhanced_context(thread_id, agent_id, max_messages)
        lines = []

        # 对话历史
        if enhanced['messages']:
            lines.append("--- 对话历史 ---")
            for msg in enhanced['messages']:
                prefix = '用户' if msg['role'] == 'user' else f"[{msg.get('agentId', 'assistant')}]"
                lines.append(f"{prefix}: {msg['content']}")
            lines.append("")

        # 待确认操作
        if enhanced['pending_tool']:
            lines.append("--- 待确认操作 ---")
            tool = enhanced['pending_tool']
            lines.append(f"工具: {tool.get('name', 'unknown')}")
            if tool.get('input'):
                lines.append(f"参数: {json.dumps(tool['input'], ensure_ascii=False)}")
            lines.append("等待用户确认...")
            lines.append("")

        # 长期记忆
        if enhanced.get('long_memory'):
            memory = enhanced['long_memory']
            # 过滤掉元数据
            memory_items = {k: v for k, v in memory.items()
                          if k not in ('updatedAt', 'createdAt')}
            if memory_items:
                lines.append("--- 长期记忆 ---")
                for key, value in memory_items.items():
                    lines.append(f"{key}: {value}")
                lines.append("")

        return '\n'.join(lines)
