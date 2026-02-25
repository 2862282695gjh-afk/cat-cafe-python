"""
内存存储（用于测试，不依赖 Redis）
"""
import time
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

    async def save_message(self, thread_id: str, agent_id: str, content: str,
                          role: str = 'assistant', process_logs: List[Dict] = None) -> Message:
        import uuid
        import random

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
        await self.set_thread_meta(thread_id, meta)

        return message

    async def get_messages(self, thread_id: str) -> List[Dict]:
        key = f"thread:{thread_id}"
        messages = self.threads.get(key, [])
        return [m.to_dict() for m in messages]

    async def get_context(self, thread_id: str) -> str:
        messages = await self.get_messages(thread_id)
        if not messages:
            return ''

        lines = []
        for msg in messages:
            prefix = '用户' if msg['role'] == 'user' else f"[{msg['agentId']}]"
            lines.append(f"{prefix}: {msg['content']}")

        return '\n\n'.join(lines) + '\n\n'

    async def clear_thread(self, thread_id: str):
        key = f"thread:{thread_id}"
        self.threads.pop(key, None)
        self.thread_metas.pop(thread_id, None)
        self.thread_list.discard(thread_id)

    async def get_all_threads(self) -> List[Dict]:
        threads = []
        for thread_id in self.thread_list:
            meta = await self.get_thread_meta(thread_id)
            threads.append({
                'id': thread_id,
                **(meta or {})
            })

        # 按最后活跃时间倒序排列
        def get_time(t):
            return t.get('lastActivity') or t.get('updatedAt') or 0
        return sorted(threads, key=get_time, reverse=True)

    async def get_thread_meta(self, thread_id: str) -> Optional[Dict]:
        return self.thread_metas.get(thread_id)

    async def set_thread_meta(self, thread_id: str, meta: Dict):
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
