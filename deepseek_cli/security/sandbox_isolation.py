"""
第三层：沙箱隔离层 (Sandbox Isolation Layer)
- Bash 沙箱
- 文件系统写入限制
- 网络访问域名白名单
"""
import os
import re
import json
import asyncio
import subprocess
import shutil
import tempfile
import resource
import ipaddress
from typing import Any, Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from pathlib import Path
from contextlib import asynccontextmanager


class IsolationLevel(Enum):
    """隔离级别"""
    NONE = "none"           # 无隔离
    BASIC = "basic"         # 基本隔离
    STANDARD = "standard"   # 标准隔离
    STRICT = "strict"       # 严格隔离
    MAXIMUM = "maximum"     # 最大隔离（容器化）


@dataclass
class ResourceLimits:
    """资源限制"""
    max_memory_mb: int = 512           # 最大内存 (MB)
    max_cpu_percent: int = 50          # 最大 CPU 使用率 (%)
    max_file_size_mb: int = 100        # 最大文件大小 (MB)
    max_open_files: int = 100          # 最大打开文件数
    max_processes: int = 10            # 最大进程数
    max_execution_time_s: int = 120    # 最大执行时间 (秒)
    max_network_connections: int = 10  # 最大网络连接数
    max_disk_write_mb: int = 1000      # 最大磁盘写入 (MB)


@dataclass
class SandboxConfig:
    """沙箱配置"""
    isolation_level: IsolationLevel = IsolationLevel.STANDARD
    allowed_paths: List[str] = field(default_factory=list)
    blocked_paths: List[str] = field(default_factory=lambda: [
        "/etc/passwd", "/etc/shadow", "/root/.ssh", "/boot", "/proc", "/sys"
    ])
    allowed_commands: List[str] = field(default_factory=list)
    blocked_commands: List[str] = field(default_factory=lambda: [
        "rm -rf /", "mkfs", "dd if=", "shutdown", "reboot", "init 0", "init 6"
    ])
    allowed_domains: List[str] = field(default_factory=lambda: [
        "api.deepseek.com",
        "api.openai.com",
        "api.anthropic.com",
        "github.com",
        "pypi.org",
        "npmjs.org",
    ])
    blocked_domains: List[str] = field(default_factory=list)
    allowed_ports: List[int] = field(default_factory=lambda: [80, 443, 22])
    blocked_ports: List[int] = field(default_factory=list)
    resource_limits: ResourceLimits = field(default_factory=ResourceLimits)
    read_only_paths: List[str] = field(default_factory=list)
    no_network: bool = False
    allow_local_network: bool = True


@dataclass
class SandboxResult:
    """沙箱执行结果"""
    success: bool
    output: str
    error: Optional[str] = None
    blocked: bool = False
    blocked_reason: Optional[str] = None
    resource_usage: Dict[str, Any] = field(default_factory=dict)
    sandbox_id: Optional[str] = None


# ============================================================================
# 文件系统隔离
# ============================================================================

class FileSystemSandbox:
    """文件系统沙箱"""

    def __init__(self, config: SandboxConfig, working_dir: str = None):
        self.config = config
        self.working_dir = working_dir or os.getcwd()
        self._write_tracker: Dict[str, int] = {}  # 路径 -> 写入字节数
        self._file_handles: Set[int] = set()

    def is_path_allowed(self, path: str, mode: str = "read") -> Tuple[bool, str]:
        """
        检查路径是否允许访问

        Args:
            path: 文件路径
            mode: 访问模式 ("read", "write", "execute")

        Returns:
            (allowed, reason)
        """
        # 规范化路径
        abs_path = self._resolve_path(path)

        # 检查黑名单
        for blocked in self.config.blocked_paths:
            if abs_path.startswith(blocked) or blocked in abs_path:
                return False, f"Path is blocked: {blocked}"

        # 检查白名单（如果配置了）
        if self.config.allowed_paths:
            allowed = any(
                abs_path.startswith(allowed)
                for allowed in self.config.allowed_paths
            )
            if not allowed:
                return False, "Path not in allowed list"

        # 检查只读路径
        if mode == "write":
            for read_only in self.config.read_only_paths:
                if abs_path.startswith(read_only):
                    return False, f"Path is read-only: {read_only}"

        return True, "OK"

    def check_write_limit(self, path: str, size: int) -> Tuple[bool, str]:
        """检查写入限制"""
        # 检查单文件大小限制
        max_file_size = self.config.resource_limits.max_file_size_mb * 1024 * 1024
        if size > max_file_size:
            return False, f"File size {size} exceeds limit {max_file_size}"

        # 检查总写入量限制
        max_total_write = self.config.resource_limits.max_disk_write_mb * 1024 * 1024
        total_written = sum(self._write_tracker.values())
        if total_written + size > max_total_write:
            return False, f"Total write limit exceeded"

        return True, "OK"

    def track_write(self, path: str, size: int):
        """追踪写入"""
        self._write_tracker[path] = self._write_tracker.get(path, 0) + size

    def get_chroot_path(self) -> str:
        """获取 chroot 路径（如果启用）"""
        if self.config.isolation_level == IsolationLevel.MAXIMUM:
            # 创建临时 chroot 环境
            chroot_dir = tempfile.mkdtemp(prefix="sandbox_")
            return chroot_dir
        return None

    def _resolve_path(self, path: str) -> str:
        """解析路径"""
        if not os.path.isabs(path):
            path = os.path.join(self.working_dir, path)
        return os.path.normpath(os.path.realpath(path))


# ============================================================================
# 命令沙箱
# ============================================================================

class BashSandbox:
    """Bash 命令沙箱"""

    # 安全命令列表（无需检查）
    SAFE_COMMANDS = {
        "ls", "cat", "head", "tail", "grep", "find", "wc", "sort", "uniq",
        "echo", "pwd", "whoami", "date", "which", "type", "file", "stat",
        "git", "npm", "node", "python", "python3", "pip", "pip3",
        "mkdir", "touch", "cp", "mv", "ln",
    }

    # 危险命令模式
    DANGEROUS_PATTERNS = [
        (r"rm\s+-rf\s+/", "递归删除根目录"),
        (r"rm\s+-rf\s+~", "递归删除用户目录"),
        (r"rm\s+-rf\s+\*", "递归删除所有"),
        (r"mkfs", "格式化文件系统"),
        (r"dd\s+if=", "磁盘直接写入"),
        (r">\s*/dev/sd", "直接写入磁盘设备"),
        (r"chmod\s+777", "不安全权限设置"),
        (r":\(\)\s*\{\s*:\|:&\s*\}", "Fork炸弹"),
        (r"wget.*\|\s*bash", "远程代码执行"),
        (r"curl.*\|\s*bash", "远程代码执行"),
    ]

    def __init__(self, config: SandboxConfig):
        self.config = config

    def is_command_allowed(self, command: str) -> Tuple[bool, str]:
        """
        检查命令是否允许执行

        Returns:
            (allowed, reason)
        """
        # 1. 检查黑名单
        for blocked in self.config.blocked_commands:
            if blocked.lower() in command.lower():
                return False, f"Command is blocked: {blocked}"

        # 2. 检查危险模式
        for pattern, description in self.DANGEROUS_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return False, f"Dangerous command detected: {description}"

        # 3. 检查白名单（如果配置了）
        if self.config.allowed_commands:
            # 提取命令名
            cmd_name = command.split()[0] if command.split() else ""
            if cmd_name not in self.config.allowed_commands and cmd_name not in self.SAFE_COMMANDS:
                return False, f"Command not in allowed list: {cmd_name}"

        # 4. 根据隔离级别进行额外检查
        if self.config.isolation_level == IsolationLevel.STRICT:
            # 严格模式下禁止管道和重定向到危险位置
            if re.search(r">\s*/", command):
                return False, "Redirect to absolute path not allowed in strict mode"

        return True, "OK"

    def sanitize_command(self, command: str) -> str:
        """清理命令"""
        # 移除危险字符
        # 注意：这是一个简单的清理，实际生产环境需要更严格的处理
        sanitized = command

        # 转义潜在的 shell 注入
        # 这里只做基本处理，实际应该在沙箱中执行
        dangerous_chars = ["`", "$(", "${"]
        for char in dangerous_chars:
            if char in sanitized:
                # 记录但不阻止，由 is_command_allowed 处理
                pass

        return sanitized

    def build_safe_command(
        self,
        command: str,
        timeout: int = None,
        env: Dict[str, str] = None
    ) -> Dict[str, Any]:
        """
        构建安全的命令执行配置

        Returns:
            执行配置字典
        """
        timeout = timeout or self.config.resource_limits.max_execution_time_s

        config = {
            "command": command,
            "timeout": min(timeout, self.config.resource_limits.max_execution_time_s),
            "env": self._build_safe_env(env),
            "preexec_fn": self._set_resource_limits,
            "shell": True,
            "cwd": None,  # 由调用者设置
        }

        return config

    def _build_safe_env(self, extra_env: Dict[str, str] = None) -> Dict[str, str]:
        """构建安全的环境变量"""
        # 从当前环境复制，但移除敏感信息
        safe_env = {
            k: v for k, v in os.environ.items()
            if not any(sensitive in k.upper() for sensitive in [
                "PASSWORD", "SECRET", "KEY", "TOKEN", "CREDENTIAL", "API_KEY"
            ])
        }

        # 添加额外环境变量
        if extra_env:
            safe_env.update(extra_env)

        return safe_env

    def _set_resource_limits(self):
        """设置进程资源限制（在子进程中调用）"""
        limits = self.config.resource_limits

        try:
            # 内存限制
            memory_bytes = limits.max_memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))

            # CPU 时间限制
            cpu_seconds = limits.max_execution_time_s
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))

            # 文件大小限制
            file_bytes = limits.max_file_size_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_FSIZE, (file_bytes, file_bytes))

            # 打开文件数限制
            resource.setrlimit(resource.RLIMIT_NOFILE, (
                limits.max_open_files,
                limits.max_open_files
            ))

            # 进程数限制
            resource.setrlimit(resource.RLIMIT_NPROC, (
                limits.max_processes,
                limits.max_processes
            ))
        except Exception as e:
            print(f"[Sandbox] Failed to set resource limits: {e}")


# ============================================================================
# 网络沙箱
# ============================================================================

class NetworkSandbox:
    """网络访问沙箱"""

    # 允许的本地地址
    LOCAL_ADDRESSES = {
        "127.0.0.1", "localhost", "::1",
    }

    # 私有 IP 范围
    PRIVATE_IP_RANGES = [
        (ipaddress.IPv4Address("10.0.0.0"), ipaddress.IPv4Address("10.255.255.255")),
        (ipaddress.IPv4Address("172.16.0.0"), ipaddress.IPv4Address("172.31.255.255")),
        (ipaddress.IPv4Address("192.168.0.0"), ipaddress.IPv4Address("192.168.255.255")),
    ]

    def __init__(self, config: SandboxConfig):
        self.config = config
        self._connection_count = 0

    def is_domain_allowed(self, domain: str) -> Tuple[bool, str]:
        """检查域名是否允许访问"""
        # 检查黑名单
        for blocked in self.config.blocked_domains:
            if blocked in domain:
                return False, f"Domain is blocked: {blocked}"

        # 检查白名单
        if self.config.allowed_domains:
            allowed = any(
                domain == allowed or domain.endswith(f".{allowed}")
                for allowed in self.config.allowed_domains
            )
            if not allowed:
                return False, f"Domain not in whitelist: {domain}"

        return True, "OK"

    def is_port_allowed(self, port: int) -> Tuple[bool, str]:
        """检查端口是否允许访问"""
        # 检查黑名单
        if port in self.config.blocked_ports:
            return False, f"Port is blocked: {port}"

        # 检查白名单
        if self.config.allowed_ports:
            if port not in self.config.allowed_ports:
                return False, f"Port not in whitelist: {port}"

        return True, "OK"

    def is_network_allowed(self, host: str, port: int = None) -> Tuple[bool, str]:
        """检查网络访问是否允许"""
        # 检查是否禁用网络
        if self.config.no_network:
            # 检查是否允许本地网络
            if self.config.allow_local_network and self._is_local_address(host):
                pass  # 允许
            else:
                return False, "Network access is disabled"

        # 检查连接数限制
        if self._connection_count >= self.config.resource_limits.max_network_connections:
            return False, "Max network connections exceeded"

        # 检查域名
        domain_allowed, domain_reason = self.is_domain_allowed(host)
        if not domain_allowed:
            return False, domain_reason

        # 检查端口
        if port:
            port_allowed, port_reason = self.is_port_allowed(port)
            if not port_allowed:
                return False, port_reason

        return True, "OK"

    def _is_local_address(self, host: str) -> bool:
        """检查是否为本地地址"""
        if host in self.LOCAL_ADDRESSES:
            return True

        try:
            import ipaddress
            ip = ipaddress.ip_address(host)
            for start, end in self.PRIVATE_IP_RANGES:
                if start <= ip <= end:
                    return True
        except ValueError:
            pass

        return False

    def track_connection(self):
        """追踪连接"""
        self._connection_count += 1

    def release_connection(self):
        """释放连接"""
        self._connection_count = max(0, self._connection_count - 1)


# ============================================================================
# 沙箱隔离层
# ============================================================================

class SandboxIsolationLayer:
    """
    第三层：沙箱隔离层

    功能：
    - Bash 沙箱
    - 文件系统写入限制
    - 网络访问域名白名单
    - 资源限制
    """

    def __init__(
        self,
        config: SandboxConfig = None,
        working_dir: str = None
    ):
        self.config = config or SandboxConfig()
        self.working_dir = working_dir or os.getcwd()

        # 初始化子沙箱
        self.fs_sandbox = FileSystemSandbox(self.config, self.working_dir)
        self.bash_sandbox = BashSandbox(self.config)
        self.network_sandbox = NetworkSandbox(self.config)

        # 沙箱 ID
        self.sandbox_id = f"sandbox_{int(datetime.now().timestamp() * 1000)}"

    # ==================== 文件系统隔离 ====================

    def check_file_access(
        self,
        path: str,
        mode: str = "read"
    ) -> Tuple[bool, str]:
        """检查文件访问权限"""
        return self.fs_sandbox.is_path_allowed(path, mode)

    def check_file_write(
        self,
        path: str,
        size: int
    ) -> Tuple[bool, str]:
        """检查文件写入权限"""
        # 检查路径权限
        allowed, reason = self.fs_sandbox.is_path_allowed(path, "write")
        if not allowed:
            return False, reason

        # 检查写入限制
        return self.fs_sandbox.check_write_limit(path, size)

    # ==================== 命令隔离 ====================

    def check_command(self, command: str) -> Tuple[bool, str]:
        """检查命令是否允许执行"""
        return self.bash_sandbox.is_command_allowed(command)

    @asynccontextmanager
    async def execute_in_sandbox(self, command: str, timeout: int = None):
        """在沙箱中执行命令"""
        # 检查命令
        allowed, reason = self.check_command(command)
        if not allowed:
            yield SandboxResult(
                success=False,
                output="",
                error=reason,
                blocked=True,
                blocked_reason=reason,
                sandbox_id=self.sandbox_id
            )
            return

        # 构建执行配置
        exec_config = self.bash_sandbox.build_safe_command(command, timeout)
        exec_config["cwd"] = self.working_dir

        # 执行命令
        process = None
        try:
            process = await asyncio.create_subprocess_shell(
                exec_config["command"],
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=exec_config["cwd"],
                env=exec_config["env"],
                preexec_fn=exec_config["preexec_fn"]
            )

            # 带超时执行
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=exec_config["timeout"]
                )
            except asyncio.TimeoutError:
                process.kill()
                yield SandboxResult(
                    success=False,
                    output="",
                    error=f"Command timed out after {exec_config['timeout']}s",
                    sandbox_id=self.sandbox_id
                )
                return

            yield SandboxResult(
                success=process.returncode == 0,
                output=stdout.decode('utf-8', errors='replace'),
                error=stderr.decode('utf-8', errors='replace') if stderr else None,
                sandbox_id=self.sandbox_id
            )

        except Exception as e:
            yield SandboxResult(
                success=False,
                output="",
                error=str(e),
                sandbox_id=self.sandbox_id
            )
        finally:
            if process and process.returncode is None:
                process.kill()

    # ==================== 网络隔离 ====================

    def check_network_access(
        self,
        host: str,
        port: int = None
    ) -> Tuple[bool, str]:
        """检查网络访问权限"""
        return self.network_sandbox.is_network_allowed(host, port)

    # ==================== 综合检查 ====================

    def check_tool_execution(
        self,
        tool_name: str,
        arguments: Dict[str, Any]
    ) -> Tuple[bool, str]:
        """
        检查工具执行是否符合沙箱规则

        Returns:
            (allowed, reason)
        """
        if tool_name == "Bash":
            command = arguments.get("command", "")
            return self.check_command(command)

        if tool_name in ["Write", "Edit", "MultiEdit"]:
            file_path = arguments.get("file_path", "")
            content = arguments.get("content", "")
            size = len(content) if content else 0

            if tool_name == "Write":
                return self.check_file_write(file_path, size)
            else:
                return self.check_file_access(file_path, "write")

        if tool_name in ["Read", "Glob", "Grep"]:
            path = arguments.get("file_path") or arguments.get("path", "")
            return self.check_file_access(path, "read")

        if tool_name in ["WebFetch", "WebSearch"]:
            if self.config.no_network:
                return False, "Network access is disabled"
            return True, "OK"

        return True, "OK"

    # ==================== 配置管理 ====================

    def add_allowed_path(self, path: str):
        """添加允许的路径"""
        abs_path = os.path.abspath(path)
        if abs_path not in self.config.allowed_paths:
            self.config.allowed_paths.append(abs_path)

    def add_allowed_domain(self, domain: str):
        """添加允许的域名"""
        if domain not in self.config.allowed_domains:
            self.config.allowed_domains.append(domain)

    def add_blocked_command(self, pattern: str):
        """添加禁止的命令模式"""
        if pattern not in self.config.blocked_commands:
            self.config.blocked_commands.append(pattern)

    def set_resource_limits(self, limits: ResourceLimits):
        """设置资源限制"""
        self.config.resource_limits = limits

    def get_sandbox_info(self) -> Dict[str, Any]:
        """获取沙箱信息"""
        return {
            "sandbox_id": self.sandbox_id,
            "isolation_level": self.config.isolation_level.value,
            "working_dir": self.working_dir,
            "allowed_paths": self.config.allowed_paths,
            "allowed_domains": self.config.allowed_domains,
            "resource_limits": {
                "max_memory_mb": self.config.resource_limits.max_memory_mb,
                "max_cpu_percent": self.config.resource_limits.max_cpu_percent,
                "max_file_size_mb": self.config.resource_limits.max_file_size_mb,
                "max_execution_time_s": self.config.resource_limits.max_execution_time_s,
            },
            "network_enabled": not self.config.no_network,
        }
