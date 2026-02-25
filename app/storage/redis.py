"""
Redis 存储
"""
import json
import time
from typing import Dict, List, Optional
import redis.asyncio as redis


class RedisStorage:
    def __init__(self, url: str = 'redis://localhost:6379'):
        self.url = url
        self.client: Optional[redis.Redis] = None

    async def connect(self):
        if self.client is None:
            self.client = redis.from_url(self.url)

    async def disconnect(self):
        if self.client:
            await self.client.close()
            self.client = None

    async def save_message(self, thread_id: str, agent_id: str, content: str,
                          role: str = 'assistant', process_logs: List[Dict] = None) -> Dict:
        import uuid
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

        await self.client.rpush(f"thread:{thread_id}:messages", json.dumps(message))

        # 更新线程元信息
        meta = await self.get_thread_meta(thread_id) or {}
        if not meta.get('title') and role == 'user':
            meta['title'] = content[:30] + ('...' if len(content) > 30 else '')
        meta['lastActivity'] = int(time.time() * 1000)
        await self.set_thread_meta(thread_id, meta)

        return message

    async def get_messages(self, thread_id: str) -> List[Dict]:
        messages = await self.client.lrange(f"thread:{thread_id}:messages", 0, -1)
        return [json.loads(m) for m in messages]

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
        await self.client.delete(f"thread:{thread_id}:messages")
        await self.client.delete(f"thread:{thread_id}:context")
        await self.client.delete(f"thread:{thread_id}:meta")
        await self.client.srem('threads', thread_id)

    async def get_all_threads(self) -> List[Dict]:
        thread_ids = await self.client.smembers('threads')
        threads = []
        for tid in thread_ids:
            thread_id = tid.decode() if isinstance(tid, bytes) else tid
            meta = await self.get_thread_meta(thread_id)
            threads.append({
                'id': thread_id,
                **(meta or {})
            })

        def get_time(t):
            return t.get('lastActivity') or t.get('updatedAt') or 0
        return sorted(threads, key=get_time, reverse=True)

    async def get_thread_meta(self, thread_id: str) -> Optional[Dict]:
        meta = await self.client.get(f"thread:{thread_id}:meta")
        return json.loads(meta) if meta else None

    async def set_thread_meta(self, thread_id: str, meta: Dict):
        await self.client.sadd('threads', thread_id)
        existing = await self.get_thread_meta(thread_id) or {}
        updated = {
            **existing,
            **meta,
            'updatedAt': int(time.time() * 1000)
        }
        if not existing.get('createdAt'):
            updated['createdAt'] = updated['updatedAt']
        await self.client.set(f"thread:{thread_id}:meta", json.dumps(updated))
