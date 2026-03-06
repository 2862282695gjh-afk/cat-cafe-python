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

    # ===== Agent 持久化 =====
    def save_agent(self, agent_id: str, agent_config: Dict):
        """保存 Agent 配置"""
        existing = self.get_agent(agent_id) or {}
        updated = {
            **existing,
            **agent_config,
            'updatedAt': int(time.time() * 1000)
        }
        if not existing.get('createdAt'):
            updated['createdAt'] = updated['updatedAt']
        self.client.set(f"agent:{agent_id}:config", json.dumps(updated))
        self.client.sadd('agents', agent_id)

    def get_agent(self, agent_id: str) -> Optional[Dict]:
        """获取 Agent 配置"""
        data = self.client.get(f"agent:{agent_id}:config")
        return json.loads(data) if data else None

    def get_all_agents(self) -> List[Dict]:
        """获取所有 Agent 配置"""
        agent_ids = self.client.smembers('agents')
        agents = []
        for aid in agent_ids:
            agent_id = aid.decode() if isinstance(aid, bytes) else aid
            config = self.get_agent(agent_id)
            if config:
                agents.append(config)
        return agents

    def delete_agent(self, agent_id: str):
        """删除 Agent 配置"""
        self.client.delete(f"agent:{agent_id}:config")
        self.client.srem('agents', agent_id)

    # ===== 对话角色配置 =====
    def save_thread_roles(self, thread_id: str, roles: Dict):
        """保存对话的角色配置 { agentId: roleDescription }"""
        existing = self.get_thread_roles(thread_id) or {}
        updated = {
            **existing,
            **roles,
            'updatedAt': int(time.time() * 1000)
        }
        if not existing.get('createdAt'):
            updated['createdAt'] = updated['updatedAt']
        self.client.set(f"thread:{thread_id}:roles", json.dumps(updated))

    def get_thread_roles(self, thread_id: str) -> Optional[Dict]:
        """获取对话的角色配置"""
        data = self.client.get(f"thread:{thread_id}:roles")
        roles = json.loads(data) if data else {}
        # 过滤元数据
        return {k: v for k, v in roles.items() if k not in ('updatedAt', 'createdAt')} if roles else {}

    # ===== 房间级别的猫咪记忆 =====
    def save_thread_agent_memory(self, thread_id: str, agent_id: str, memory: Dict):
        """保存房间内特定猫咪的记忆"""
        existing = self.get_thread_agent_memory(thread_id, agent_id) or {}
        updated = {
            **existing,
            **memory,
            'updatedAt': int(time.time() * 1000)
        }
        if not existing.get('createdAt'):
            updated['createdAt'] = updated['updatedAt']
        self.client.set(f"thread:{thread_id}:agent:{agent_id}:memory", json.dumps(updated))

    def get_thread_agent_memory(self, thread_id: str, agent_id: str) -> Optional[Dict]:
        """获取房间内特定猫咪的记忆"""
        data = self.client.get(f"thread:{thread_id}:agent:{agent_id}:memory")
        memory = json.loads(data) if data else {}
        # 过滤元数据
        return {k: v for k, v in memory.items() if k not in ('updatedAt', 'createdAt')} if memory else {}

    def add_thread_agent_memory_entry(self, thread_id: str, agent_id: str, key: str, value: str):
        """添加一条房间内猫咪的记忆"""
        existing = self.get_thread_agent_memory(thread_id, agent_id) or {}
        existing[key] = value
        existing['updatedAt'] = int(time.time() * 1000)
        if not existing.get('createdAt'):
            existing['createdAt'] = existing['updatedAt']
        self.client.set(f"thread:{thread_id}:agent:{agent_id}:memory", json.dumps(existing))

    def remove_thread_agent_memory_entry(self, thread_id: str, agent_id: str, key: str):
        """删除一条房间内猫咪的记忆"""
        data = self.client.get(f"thread:{thread_id}:agent:{agent_id}:memory")
        existing = json.loads(data) if data else {}
        if key in existing:
            del existing[key]
            existing['updatedAt'] = int(time.time() * 1000)
            self.client.set(f"thread:{thread_id}:agent:{agent_id}:memory", json.dumps(existing))

    # ===== MCP 服务器管理 =====
    def save_mcp_server(self, server_id: str, config: Dict):
        """保存 MCP 服务器配置"""
        existing = self.get_mcp_server(server_id) or {}
        updated = {
            **existing,
            **config,
            'updatedAt': int(time.time() * 1000)
        }
        if not existing.get('createdAt'):
            updated['createdAt'] = updated['updatedAt']
        self.client.set(f"mcp:server:{server_id}", json.dumps(updated))
        self.client.sadd('mcp:servers', server_id)

    def get_mcp_server(self, server_id: str) -> Optional[Dict]:
        """获取 MCP 服务器配置"""
        data = self.client.get(f"mcp:server:{server_id}")
        return json.loads(data) if data else None

    def get_all_mcp_servers(self) -> List[Dict]:
        """获取所有 MCP 服务器配置"""
        server_ids = self.client.smembers('mcp:servers')
        servers = []
        for sid in server_ids:
            server_id = sid.decode() if isinstance(sid, bytes) else sid
            config = self.get_mcp_server(server_id)
            if config:
                servers.append(config)
        return servers

    def delete_mcp_server(self, server_id: str):
        """删除 MCP 服务器配置"""
        self.client.delete(f"mcp:server:{server_id}")
        self.client.srem('mcp:servers', server_id)

    # ===== Skill 管理 =====
    def save_skill(self, skill_id: str, config: Dict):
        """保存 Skill 配置"""
        existing = self.get_skill(skill_id) or {}
        updated = {
            **existing,
            **config,
            'updatedAt': int(time.time() * 1000)
        }
        if not existing.get('createdAt'):
            updated['createdAt'] = updated['updatedAt']
        self.client.set(f"skill:{skill_id}", json.dumps(updated))
        self.client.sadd('skills', skill_id)

    def get_skill(self, skill_id: str) -> Optional[Dict]:
        """获取 Skill 配置"""
        data = self.client.get(f"skill:{skill_id}")
        return json.loads(data) if data else None

    def get_all_skills(self) -> List[Dict]:
        """获取所有 Skill 配置"""
        skill_ids = self.client.smembers('skills')
        skills = []
        for sid in skill_ids:
            skill_id = sid.decode() if isinstance(sid, bytes) else sid
            config = self.get_skill(skill_id)
            if config:
                skills.append(config)
        return skills

    def delete_skill(self, skill_id: str):
        """删除 Skill 配置"""
        self.client.delete(f"skill:{skill_id}")
        self.client.srem('skills', skill_id)

    # ===== Agent 工具授权 =====
    def save_agent_tools(self, agent_id: str, tools: Dict):
        """保存 Agent 的工具授权配置 { mcpTools: [...], skills: [...] }"""
        existing = self.get_agent_tools(agent_id) or {}
        updated = {
            **existing,
            **tools,
            'updatedAt': int(time.time() * 1000)
        }
        if not existing.get('createdAt'):
            updated['createdAt'] = updated['updatedAt']
        self.client.set(f"agent:{agent_id}:tools", json.dumps(updated))

    def get_agent_tools(self, agent_id: str) -> Optional[Dict]:
        """获取 Agent 的工具授权配置"""
        data = self.client.get(f"agent:{agent_id}:tools")
        return json.loads(data) if data else None

    def delete_agent_tools(self, agent_id: str):
        """删除 Agent 的工具授权配置"""
        self.client.delete(f"agent:{agent_id}:tools")

    # ===== Skill 授权（按 Skill 维度管理）=====
    def save_skill_assignment(self, skill_id: str, agent_ids: List[str]):
        """保存 Skill 授权给哪些 Agent"""
        self.client.set(f"skill:{skill_id}:agents", json.dumps({
            'agentIds': agent_ids,
            'updatedAt': int(time.time() * 1000)
        }))

    def get_skill_assignment(self, skill_id: str) -> List[str]:
        """获取 Skill 授权给了哪些 Agent"""
        data = self.client.get(f"skill:{skill_id}:agents")
        if data:
            return json.loads(data).get('agentIds', [])
        return []

    def get_all_skill_assignments(self) -> Dict[str, List[str]]:
        """获取所有 Skill 的授权配置"""
        # 获取所有 skill IDs
        skill_ids = self.client.smembers('skills')
        result = {}
        for sid in skill_ids:
            skill_id = sid.decode() if isinstance(sid, bytes) else sid
            result[skill_id] = self.get_skill_assignment(skill_id)
        return result

    def get_agent_skill_ids(self, agent_id: str) -> List[str]:
        """获取 Agent 被授权的所有 Skill ID"""
        assignments = self.get_all_skill_assignments()
        return [skill_id for skill_id, agent_ids in assignments.items()
                if agent_id in agent_ids]

    def remove_agent_from_all_skills(self, agent_id: str):
        """从所有 Skill 中移除某个 Agent（删除 Agent 时调用）"""
        skill_ids = self.client.smembers('skills')
        for sid in skill_ids:
            skill_id = sid.decode() if isinstance(sid, bytes) else sid
            agent_ids = self.get_skill_assignment(skill_id)
            if agent_id in agent_ids:
                new_ids = [aid for aid in agent_ids if aid != agent_id]
                self.save_skill_assignment(skill_id, new_ids)

