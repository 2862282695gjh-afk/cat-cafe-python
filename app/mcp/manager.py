"""
MCP (Model Context Protocol) 管理器
支持 Stdio 和 HTTP/SSE 两种连接方式
"""
import asyncio
import json
import subprocess
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
import aiohttp


@dataclass
class MCPServer:
    """MCP 服务器配置"""
    id: str
    name: str
    type: str  # 'stdio' or 'http'
    command: Optional[str] = None  # for stdio
    args: List[str] = field(default_factory=list)  # for stdio
    url: Optional[str] = None  # for http/sse
    env: Dict[str, str] = field(default_factory=dict)
    status: str = 'stopped'  # stopped, starting, running, error
    tools: List[Dict] = field(default_factory=list)
    error_message: Optional[str] = None
    created_at: int = 0
    updated_at: int = 0


class MCPManager:
    """管理 MCP 服务器连接"""

    def __init__(self, storage=None):
        self.storage = storage
        self.servers: Dict[str, MCPServer] = {}
        self.processes: Dict[str, subprocess.Popen] = {}
        self.sessions: Dict[str, aiohttp.ClientSession] = {}
        self._load_servers()

    def _load_servers(self):
        """从存储加载服务器配置"""
        if not self.storage:
            return
        try:
            server_configs = self.storage.get_all_mcp_servers()
            for config in server_configs:
                server = MCPServer(
                    id=config.get('id'),
                    name=config.get('name', 'Unnamed'),
                    type=config.get('type', 'stdio'),
                    command=config.get('command'),
                    args=config.get('args', []),
                    url=config.get('url'),
                    env=config.get('env', {}),
                    created_at=config.get('createdAt', 0),
                    updated_at=config.get('updatedAt', 0)
                )
                self.servers[server.id] = server
        except Exception as e:
            print(f'[MCP] 加载服务器配置失败: {e}')

    def add_server(self, config: Dict) -> MCPServer:
        """添加 MCP 服务器"""
        import uuid
        server_id = config.get('id') or f"mcp-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"

        server = MCPServer(
            id=server_id,
            name=config.get('name', 'Unnamed'),
            type=config.get('type', 'stdio'),
            command=config.get('command'),
            args=config.get('args', []),
            url=config.get('url'),
            env=config.get('env', {}),
            created_at=int(time.time() * 1000),
            updated_at=int(time.time() * 1000)
        )

        self.servers[server_id] = server

        # 保存到存储
        if self.storage:
            self.storage.save_mcp_server(server_id, {
                'id': server_id,
                'name': server.name,
                'type': server.type,
                'command': server.command,
                'args': server.args,
                'url': server.url,
                'env': server.env
            })

        return server

    def remove_server(self, server_id: str) -> bool:
        """移除 MCP 服务器"""
        if server_id not in self.servers:
            return False

        # 先停止服务器
        if self.servers[server_id].status == 'running':
            asyncio.create_task(self.stop_server(server_id))

        del self.servers[server_id]

        # 从存储中删除
        if self.storage:
            self.storage.delete_mcp_server(server_id)

        return True

    def get_server(self, server_id: str) -> Optional[MCPServer]:
        """获取服务器配置"""
        return self.servers.get(server_id)

    def list_servers(self) -> List[Dict]:
        """列出所有服务器"""
        return [
            {
                'id': s.id,
                'name': s.name,
                'type': s.type,
                'status': s.status,
                'tools': s.tools,
                'errorMessage': s.error_message,
                'command': s.command,
                'url': s.url
            }
            for s in self.servers.values()
        ]

    async def start_server(self, server_id: str) -> bool:
        """启动 MCP 服务器"""
        server = self.servers.get(server_id)
        if not server:
            return False

        if server.status == 'running':
            return True

        server.status = 'starting'
        server.error_message = None

        try:
            if server.type == 'stdio':
                return await self._start_stdio_server(server)
            elif server.type == 'http':
                return await self._start_http_server(server)
            else:
                server.status = 'error'
                server.error_message = f'Unknown server type: {server.type}'
                return False
        except Exception as e:
            server.status = 'error'
            server.error_message = str(e)
            return False

    async def _start_stdio_server(self, server: MCPServer) -> bool:
        """启动 Stdio 类型的 MCP 服务器"""
        if not server.command:
            server.status = 'error'
            server.error_message = 'No command specified'
            return False

        try:
            import os
            env = os.environ.copy()
            env.update(server.env)

            process = subprocess.Popen(
                [server.command] + server.args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env
            )

            self.processes[server.id] = process
            server.status = 'running'

            # 初始化 MCP 连接并获取工具列表
            await self._initialize_stdio_connection(server)

            return True
        except Exception as e:
            server.status = 'error'
            server.error_message = str(e)
            return False

    async def _initialize_stdio_connection(self, server: MCPServer):
        """初始化 Stdio MCP 连接"""
        process = self.processes.get(server.id)
        if not process:
            return

        try:
            # 发送 initialize 请求
            init_request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "clientInfo": {
                        "name": "cat-cafe",
                        "version": "1.0.0"
                    }
                }
            }

            process.stdin.write((json.dumps(init_request) + '\n').encode())
            process.stdin.flush()

            # 读取响应（带超时）
            await asyncio.sleep(0.5)  # 给服务器时间响应

            # 获取工具列表
            await self._fetch_stdio_tools(server)

        except Exception as e:
            print(f'[MCP] 初始化连接失败: {e}')
            server.error_message = str(e)

    async def _fetch_stdio_tools(self, server: MCPServer):
        """从 Stdio 服务器获取工具列表"""
        process = self.processes.get(server.id)
        if not process:
            return

        try:
            # 发送 tools/list 请求
            tools_request = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {}
            }

            process.stdin.write((json.dumps(tools_request) + '\n').encode())
            process.stdin.flush()

            # 尝试读取响应
            await asyncio.sleep(0.3)

            # 由于是异步，我们设置一个默认的工具列表
            # 实际实现中需要更复杂的进程通信
            server.tools = []

        except Exception as e:
            print(f'[MCP] 获取工具列表失败: {e}')

    async def _start_http_server(self, server: MCPServer) -> bool:
        """启动 HTTP/SSE 类型的 MCP 服务器"""
        if not server.url:
            server.status = 'error'
            server.error_message = 'No URL specified'
            return False

        try:
            session = aiohttp.ClientSession()
            self.sessions[server.id] = session

            # 发送初始化请求
            async with session.post(
                f"{server.url}/initialize",
                json={
                    "protocolVersion": "2024-11-05",
                    "clientInfo": {
                        "name": "cat-cafe",
                        "version": "1.0.0"
                    }
                }
            ) as resp:
                if resp.status == 200:
                    server.status = 'running'
                    # 获取工具列表
                    await self._fetch_http_tools(server)
                    return True
                else:
                    server.status = 'error'
                    server.error_message = f'HTTP {resp.status}'
                    return False

        except Exception as e:
            server.status = 'error'
            server.error_message = str(e)
            return False

    async def _fetch_http_tools(self, server: MCPServer):
        """从 HTTP 服务器获取工具列表"""
        session = self.sessions.get(server.id)
        if not session or not server.url:
            return

        try:
            async with session.get(f"{server.url}/tools") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    server.tools = data.get('tools', [])
        except Exception as e:
            print(f'[MCP] 获取工具列表失败: {e}')
            server.tools = []

    async def stop_server(self, server_id: str) -> bool:
        """停止 MCP 服务器"""
        server = self.servers.get(server_id)
        if not server:
            return False

        if server.type == 'stdio':
            process = self.processes.get(server_id)
            if process:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                del self.processes[server_id]

        elif server.type == 'http':
            session = self.sessions.get(server_id)
            if session:
                await session.close()
                del self.sessions[server_id]

        server.status = 'stopped'
        server.tools = []
        return True

    async def list_tools(self, server_id: str) -> List[Dict]:
        """获取服务器提供的工具列表"""
        server = self.servers.get(server_id)
        if not server or server.status != 'running':
            return []
        return server.tools

    async def invoke_tool(self, server_id: str, tool_name: str, params: Dict) -> Any:
        """调用 MCP 工具"""
        server = self.servers.get(server_id)
        if not server:
            raise ValueError(f'Server not found: {server_id}')

        if server.status != 'running':
            raise ValueError(f'Server not running: {server_id}')

        if server.type == 'stdio':
            return await self._invoke_stdio_tool(server, tool_name, params)
        elif server.type == 'http':
            return await self._invoke_http_tool(server, tool_name, params)
        else:
            raise ValueError(f'Unknown server type: {server.type}')

    async def _invoke_stdio_tool(self, server: MCPServer, tool_name: str, params: Dict) -> Any:
        """调用 Stdio 工具"""
        process = self.processes.get(server.id)
        if not process:
            raise ValueError('Process not found')

        request = {
            "jsonrpc": "2.0",
            "id": int(time.time() * 1000),
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": params
            }
        }

        process.stdin.write((json.dumps(request) + '\n').encode())
        process.stdin.flush()

        # 简化实现：返回一个占位结果
        # 实际实现需要正确处理进程输出
        return {"status": "invoked", "tool": tool_name}

    async def _invoke_http_tool(self, server: MCPServer, tool_name: str, params: Dict) -> Any:
        """调用 HTTP 工具"""
        session = self.sessions.get(server.id)
        if not session:
            raise ValueError('Session not found')

        async with session.post(
            f"{server.url}/tools/{tool_name}/call",
            json={"arguments": params}
        ) as resp:
            if resp.status == 200:
                return await resp.json()
            else:
                raise Exception(f'Tool call failed: HTTP {resp.status}')

    def get_all_tools(self) -> List[Dict]:
        """获取所有运行中服务器的工具"""
        tools = []
        for server in self.servers.values():
            if server.status == 'running':
                for tool in server.tools:
                    tools.append({
                        'serverId': server.id,
                        'serverName': server.name,
                        'name': tool.get('name'),
                        'description': tool.get('description', ''),
                        'inputSchema': tool.get('inputSchema', {})
                    })
        return tools
