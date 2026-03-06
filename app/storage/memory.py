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

    # ===== Agent 持久化 =====
    def save_agent(self, agent_id: str, agent_config: Dict):
        """保存 Agent 配置"""
        self.agent_configs = getattr(self, 'agent_configs', {})
        self.agent_configs[agent_id] = {
            **agent_config,
            'updatedAt': int(time.time() * 1000)
        }

    def get_agent(self, agent_id: str) -> Optional[Dict]:
        """获取 Agent 配置"""
        self.agent_configs = getattr(self, 'agent_configs', {})
        return self.agent_configs.get(agent_id)

    def get_all_agents(self) -> List[Dict]:
        """获取所有 Agent 配置"""
        self.agent_configs = getattr(self, 'agent_configs', {})
        return list(self.agent_configs.values())

    def delete_agent(self, agent_id: str):
        """删除 Agent 配置"""
        self.agent_configs = getattr(self, 'agent_configs', {})
        self.agent_configs.pop(agent_id, None)

    # ===== 对话角色配置 =====
    def save_thread_roles(self, thread_id: str, roles: Dict):
        """保存对话的角色配置 { agentId: roleDescription }"""
        self.thread_roles = getattr(self, 'thread_roles', {})
        self.thread_roles[thread_id] = {
            **roles,
            'updatedAt': int(time.time() * 1000)
        }

    def get_thread_roles(self, thread_id: str) -> Optional[Dict]:
        """获取对话的角色配置"""
        self.thread_roles = getattr(self, 'thread_roles', {})
        roles = self.thread_roles.get(thread_id, {})
        # 过滤元数据
        return {k: v for k, v in roles.items() if k != 'updatedAt'} if roles else {}

    # ===== 房间级别的猫咪记忆 =====
    def save_thread_agent_memory(self, thread_id: str, agent_id: str, memory: Dict):
        """保存房间内特定猫咪的记忆"""
        self.thread_agent_memories = getattr(self, 'thread_agent_memories', {})
        key = f"{thread_id}:{agent_id}"
        self.thread_agent_memories[key] = {
            **memory,
            'updatedAt': int(time.time() * 1000)
        }

    def get_thread_agent_memory(self, thread_id: str, agent_id: str) -> Optional[Dict]:
        """获取房间内特定猫咪的记忆"""
        self.thread_agent_memories = getattr(self, 'thread_agent_memories', {})
        key = f"{thread_id}:{agent_id}"
        memory = self.thread_agent_memories.get(key, {})
        # 过滤元数据
        return {k: v for k, v in memory.items() if k not in ('updatedAt', 'createdAt')} if memory else {}

    def add_thread_agent_memory_entry(self, thread_id: str, agent_id: str, key: str, value: str):
        """添加一条房间内猫咪的记忆"""
        self.thread_agent_memories = getattr(self, 'thread_agent_memories', {})
        mem_key = f"{thread_id}:{agent_id}"
        existing = self.thread_agent_memories.get(mem_key, {})
        existing[key] = value
        existing['updatedAt'] = int(time.time() * 1000)
        if not existing.get('createdAt'):
            existing['createdAt'] = existing['updatedAt']
        self.thread_agent_memories[mem_key] = existing

    def remove_thread_agent_memory_entry(self, thread_id: str, agent_id: str, key: str):
        """删除一条房间内猫咪的记忆"""
        self.thread_agent_memories = getattr(self, 'thread_agent_memories', {})
        mem_key = f"{thread_id}:{agent_id}"
        existing = self.thread_agent_memories.get(mem_key, {})
        if key in existing:
            del existing[key]
            existing['updatedAt'] = int(time.time() * 1000)
            self.thread_agent_memories[mem_key] = existing

    # ===== MCP 服务器管理 =====
    def save_mcp_server(self, server_id: str, config: Dict):
        """保存 MCP 服务器配置"""
        self.mcp_servers = getattr(self, 'mcp_servers', {})
        existing = self.mcp_servers.get(server_id, {})
        self.mcp_servers[server_id] = {
            **existing,
            **config,
            'updatedAt': int(time.time() * 1000)
        }
        if not existing.get('createdAt'):
            self.mcp_servers[server_id]['createdAt'] = self.mcp_servers[server_id]['updatedAt']

    def get_mcp_server(self, server_id: str) -> Optional[Dict]:
        """获取 MCP 服务器配置"""
        self.mcp_servers = getattr(self, 'mcp_servers', {})
        return self.mcp_servers.get(server_id)

    def get_all_mcp_servers(self) -> List[Dict]:
        """获取所有 MCP 服务器配置"""
        self.mcp_servers = getattr(self, 'mcp_servers', {})
        return list(self.mcp_servers.values())

    def delete_mcp_server(self, server_id: str):
        """删除 MCP 服务器配置"""
        self.mcp_servers = getattr(self, 'mcp_servers', {})
        self.mcp_servers.pop(server_id, None)

    # ===== Skill 管理 =====
    def save_skill(self, skill_id: str, config: Dict):
        """保存 Skill 配置"""
        self.skills = getattr(self, 'skills', {})
        existing = self.skills.get(skill_id, {})
        self.skills[skill_id] = {
            **existing,
            **config,
            'updatedAt': int(time.time() * 1000)
        }
        if not existing.get('createdAt'):
            self.skills[skill_id]['createdAt'] = self.skills[skill_id]['updatedAt']

    def get_skill(self, skill_id: str) -> Optional[Dict]:
        """获取 Skill 配置"""
        self.skills = getattr(self, 'skills', {})
        return self.skills.get(skill_id)

    def get_all_skills(self) -> List[Dict]:
        """获取所有 Skill 配置"""
        self.skills = getattr(self, 'skills', {})
        return list(self.skills.values())

    def delete_skill(self, skill_id: str):
        """删除 Skill 配置"""
        self.skills = getattr(self, 'skills', {})
        self.skills.pop(skill_id, None)

    # ===== Agent 工具授权 =====
    def save_agent_tools(self, agent_id: str, tools: Dict):
        """保存 Agent 的工具授权配置 { mcpTools: [...], skills: [...] }"""
        self.agent_tools = getattr(self, 'agent_tools', {})
        existing = self.agent_tools.get(agent_id, {})
        self.agent_tools[agent_id] = {
            **existing,
            **tools,
            'updatedAt': int(time.time() * 1000)
        }
        if not existing.get('createdAt'):
            self.agent_tools[agent_id]['createdAt'] = self.agent_tools[agent_id]['updatedAt']

    def get_agent_tools(self, agent_id: str) -> Optional[Dict]:
        """获取 Agent 的工具授权配置"""
        self.agent_tools = getattr(self, 'agent_tools', {})
        return self.agent_tools.get(agent_id)

    def delete_agent_tools(self, agent_id: str):
        """删除 Agent 的工具授权配置"""
        self.agent_tools = getattr(self, 'agent_tools', {})
        self.agent_tools.pop(agent_id, None)

    # ===== Skill 授权（按 Skill 维度管理）=====
    def save_skill_assignment(self, skill_id: str, agent_ids: List[str]):
        """保存 Skill 授权给哪些 Agent"""
        self.skill_assignments = getattr(self, 'skill_assignments', {})
        self.skill_assignments[skill_id] = {
            'agentIds': agent_ids,
            'updatedAt': int(time.time() * 1000)
        }

    def get_skill_assignment(self, skill_id: str) -> List[str]:
        """获取 Skill 授权给了哪些 Agent"""
        self.skill_assignments = getattr(self, 'skill_assignments', {})
        return self.skill_assignments.get(skill_id, {}).get('agentIds', [])

    def get_all_skill_assignments(self) -> Dict[str, List[str]]:
        """获取所有 Skill 的授权配置"""
        self.skill_assignments = getattr(self, 'skill_assignments', {})
        return {skill_id: data.get('agentIds', [])
                for skill_id, data in self.skill_assignments.items()}

    def get_agent_skill_ids(self, agent_id: str) -> List[str]:
        """获取 Agent 被授权的所有 Skill ID"""
        self.skill_assignments = getattr(self, 'skill_assignments', {})
        return [skill_id for skill_id, data in self.skill_assignments.items()
                if agent_id in data.get('agentIds', [])]

    def remove_agent_from_all_skills(self, agent_id: str):
        """从所有 Skill 中移除某个 Agent（删除 Agent 时调用）"""
        self.skill_assignments = getattr(self, 'skill_assignments', {})
        for skill_id, data in self.skill_assignments.items():
            if agent_id in data.get('agentIds', []):
                data['agentIds'] = [aid for aid in data['agentIds'] if aid != agent_id]
                data['updatedAt'] = int(time.time() * 1000)
