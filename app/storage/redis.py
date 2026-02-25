"""
Redis 存储 (同步版本)
"""
import json
import time
from typing import Dict, List, Optional
import redis


class RedisStorage:
    def __init__(self, url: str = 'redis://localhost:6379'):
        self.url = url
        self.client: Optional[redis.Redis] = None

    def connect(self):
        if self.client is None:
            self.client = redis.from_url(self.url)

    def disconnect(self):
        if self.client:
            self.client.close()
            self.client = None

    def save_message(self, thread_id: str, agent_id: str, content: str,
                    role: str = 'assistant', process_logs: List[Dict] = None) -> Dict:
        import random

        message = {
            'id': f"{int(time.time() * 1000)}-{random.randint(100000, 999999)}",
            'threadId': thread_id,
            'agentId': agent_id,
            'role': role,
            'content': content,
            'timestamp': int(time.time() * 1000),
            'processLogs': process_logs or []
        }

        self.client.rpush(f"thread:{thread_id}:messages", json.dumps(message))

        # 更新线程元信息
        meta = self.get_thread_meta(thread_id) or {}
        if not meta.get('title') and role == 'user':
            meta['title'] = content[:30] + ('...' if len(content) > 30 else '')
        meta['lastActivity'] = int(time.time() * 1000)
        self.set_thread_meta(thread_id, meta)

        return message

    def get_messages(self, thread_id: str) -> List[Dict]:
        messages = self.client.lrange(f"thread:{thread_id}:messages", 0, -1)
        return [json.loads(m) for m in messages]

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
        self.client.delete(f"thread:{thread_id}:messages")
        self.client.delete(f"thread:{thread_id}:context")
        self.client.delete(f"thread:{thread_id}:meta")
        self.client.srem('threads', thread_id)

    def get_all_threads(self) -> List[Dict]:
        thread_ids = self.client.smembers('threads')
        threads = []
        for tid in thread_ids:
            thread_id = tid.decode() if isinstance(tid, bytes) else tid
            meta = self.get_thread_meta(thread_id)
            threads.append({
                'id': thread_id,
                **(meta or {})
            })

        def get_time(t):
            return t.get('lastActivity') or t.get('updatedAt') or 0
        return sorted(threads, key=get_time, reverse=True)

    def get_thread_meta(self, thread_id: str) -> Optional[Dict]:
        meta = self.client.get(f"thread:{thread_id}:meta")
        return json.loads(meta) if meta else None

    def set_thread_meta(self, thread_id: str, meta: Dict):
        self.client.sadd('threads', thread_id)
        existing = self.get_thread_meta(thread_id) or {}
        updated = {
            **existing,
            **meta,
            'updatedAt': int(time.time() * 1000)
        }
        if not existing.get('createdAt'):
            updated['createdAt'] = updated['updatedAt']
        self.client.set(f"thread:{thread_id}:meta", json.dumps(updated))

    # ===== 会话状态管理 =====
    def save_session_state(self, thread_id: str, state: Dict):
        """保存会话状态"""
        existing = self.get_session_state(thread_id) or {}
        updated = {
            **existing,
            **state,
            'updatedAt': int(time.time() * 1000)
        }
        self.client.set(f"thread:{thread_id}:session", json.dumps(updated))

    def get_session_state(self, thread_id: str) -> Optional[Dict]:
        """获取会话状态"""
        data = self.client.get(f"thread:{thread_id}:session")
        return json.loads(data) if data else None

    def clear_session_state(self, thread_id: str):
        """清除会话状态"""
        self.client.delete(f"thread:{thread_id}:session")

    # ===== 待确认工具管理 =====
    def save_pending_tool(self, thread_id: str, tool_call: Dict):
        """保存待确认的工具调用"""
        data = {
            **tool_call,
            'savedAt': int(time.time() * 1000)
        }
        self.client.set(f"thread:{thread_id}:pending_tool", json.dumps(data))

    def get_pending_tool(self, thread_id: str) -> Optional[Dict]:
        """获取待确认的工具调用"""
        data = self.client.get(f"thread:{thread_id}:pending_tool")
        return json.loads(data) if data else None

    def clear_pending_tool(self, thread_id: str):
        """清除待确认的工具调用"""
        self.client.delete(f"thread:{thread_id}:pending_tool")

    # ===== 长期记忆管理 =====
    def save_long_memory(self, agent_id: str, memory: Dict):
        """保存长期记忆（完整替换）"""
        existing = self.get_long_memory(agent_id) or {}
        updated = {
            **existing,
            **memory,
            'updatedAt': int(time.time() * 1000)
        }
        if not existing.get('createdAt'):
            updated['createdAt'] = updated['updatedAt']
        self.client.set(f"agent:{agent_id}:long_memory", json.dumps(updated))

    def get_long_memory(self, agent_id: str) -> Optional[Dict]:
        """获取长期记忆"""
        data = self.client.get(f"agent:{agent_id}:long_memory")
        return json.loads(data) if data else None

    def add_memory_entry(self, agent_id: str, key: str, value: str):
        """添加一条长期记忆"""
        existing = self.get_long_memory(agent_id) or {}
        existing[key] = value
        existing['updatedAt'] = int(time.time() * 1000)
        if not existing.get('createdAt'):
            existing['createdAt'] = existing['updatedAt']
        self.client.set(f"agent:{agent_id}:long_memory", json.dumps(existing))

    def remove_memory_entry(self, agent_id: str, key: str):
        """删除一条长期记忆"""
        existing = self.get_long_memory(agent_id) or {}
        if key in existing:
            del existing[key]
            existing['updatedAt'] = int(time.time() * 1000)
            self.client.set(f"agent:{agent_id}:long_memory", json.dumps(existing))

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
