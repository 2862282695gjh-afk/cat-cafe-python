"""
第二层：权限控制层 (Permission Control Layer)
- 权限验证三元组 (allow, deny, ask)
- Hook 机制绕过通道
- 细粒度权限策略
"""
import os
import re
import json
import hashlib
import asyncio
from typing import Any, Dict, List, Optional, Callable, Set, Union
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from abc import ABC, abstractmethod


class PermissionAction(Enum):
    """权限行为三元组"""
    ALLOW = "allow"   # 直接允许
    DENY = "deny"     # 直接拒绝
    ASK = "ask"       # 询问用户


class PermissionSource(Enum):
    """权限来源"""
    DEFAULT = "default"           # 默认策略
    USER_APPROVED = "user_approved"  # 用户批准
    SESSION_CACHE = "session_cache"  # 会话缓存
    HOOK_OVERRIDE = "hook_override"  # Hook 覆盖
    POLICY = "policy"             # 策略规则


class RiskLevel(Enum):
    """风险等级"""
    SAFE = "safe"           # 安全操作（只读）
    LOW = "low"             # 低风险
    MEDIUM = "medium"       # 中等风险
    HIGH = "high"           # 高风险
    CRITICAL = "critical"   # 危险操作


@dataclass
class PermissionContext:
    """权限上下文"""
    tool_name: str
    arguments: Dict[str, Any]
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    working_dir: Optional[str] = None
    timestamp: int = field(default_factory=lambda: int(datetime.now().timestamp() * 1000))
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get_tool_key(self) -> str:
        """生成工具唯一标识"""
        key_data = f"{self.tool_name}:{json.dumps(self.arguments, sort_keys=True)}"
        return hashlib.md5(key_data.encode()).hexdigest()[:16]


@dataclass
class PermissionResult:
    """权限检查结果"""
    action: PermissionAction
    allowed: bool
    risk_level: RiskLevel
    source: PermissionSource
    reason: str
    requires_confirmation: bool = False
    confirmation_message: Optional[str] = None
    hook_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


# ============================================================================
# 危险模式定义
# ============================================================================

class DangerPatternRegistry:
    """危险模式注册表"""

    # Bash 命令危险等级
    BASH_PATTERNS = [
        # CRITICAL - 系统级危险操作
        (r"rm\s+-rf\s+/", RiskLevel.CRITICAL, "递归删除根目录"),
        (r"rm\s+-rf\s+~", RiskLevel.CRITICAL, "递归删除用户目录"),
        (r"rm\s+-rf\s+\*", RiskLevel.CRITICAL, "递归删除所有文件"),
        (r"mkfs", RiskLevel.CRITICAL, "格式化文件系统"),
        (r"dd\s+if=", RiskLevel.CRITICAL, "磁盘直接写入"),
        (r":\(\)\s*\{\s*:\|:&\s*\}", RiskLevel.CRITICAL, "Fork炸弹"),
        (r"shutdown", RiskLevel.CRITICAL, "系统关机"),
        (r"reboot", RiskLevel.CRITICAL, "系统重启"),
        (r"init\s+[06]", RiskLevel.CRITICAL, "系统关机/重启"),

        # HIGH - 高风险操作
        (r"wget.*\|\s*(bash|sh)", RiskLevel.HIGH, "远程代码执行"),
        (r"curl.*\|\s*(bash|sh)", RiskLevel.HIGH, "远程代码执行"),
        (r"git\s+push\s+--force", RiskLevel.HIGH, "强制推送"),
        (r"git\s+push\s+-f", RiskLevel.HIGH, "强制推送"),
        (r"drop\s+(database|table)", RiskLevel.HIGH, "删除数据库/表"),
        (r"truncate\s+table", RiskLevel.HIGH, "清空表"),
        (r"eval\s+", RiskLevel.HIGH, "动态代码执行"),
        (r"exec\s+", RiskLevel.HIGH, "动态代码执行"),

        # MEDIUM - 中等风险
        (r"sudo\s+", RiskLevel.MEDIUM, "Sudo 权限提升"),
        (r"chmod\s+777", RiskLevel.MEDIUM, "不安全权限设置"),
        (r"chown\s+", RiskLevel.MEDIUM, "更改文件所有者"),
        (r"kill\s+-9", RiskLevel.MEDIUM, "强制终止进程"),
        (r"pkill\s+", RiskLevel.MEDIUM, "批量终止进程"),
        (r"iptables", RiskLevel.MEDIUM, "防火墙规则修改"),
        (r"ufw\s+", RiskLevel.MEDIUM, "防火墙规则修改"),

        # LOW - 低风险
        (r"npm\s+install", RiskLevel.LOW, "NPM 包安装"),
        (r"pip\s+install", RiskLevel.LOW, "Pip 包安装"),
        (r"git\s+commit", RiskLevel.LOW, "Git 提交"),
        (r"git\s+push", RiskLevel.LOW, "Git 推送"),
    ]

    # 文件路径危险等级
    FILE_PATTERNS = [
        # CRITICAL - 系统关键文件
        (r"^/etc/passwd$", RiskLevel.CRITICAL, "系统用户文件"),
        (r"^/etc/shadow$", RiskLevel.CRITICAL, "系统密码文件"),
        (r"^/etc/sudoers", RiskLevel.CRITICAL, "Sudo 配置"),
        (r"^/boot/", RiskLevel.CRITICAL, "系统启动文件"),
        (r"^/proc/", RiskLevel.CRITICAL, "系统进程信息"),
        (r"^/sys/", RiskLevel.CRITICAL, "系统内核信息"),

        # HIGH - 高风险文件
        (r"\.ssh/authorized_keys", RiskLevel.HIGH, "SSH 授权密钥"),
        (r"\.ssh/id_rsa", RiskLevel.HIGH, "SSH 私钥"),
        (r"\.pem$", RiskLevel.HIGH, "PEM 证书"),
        (r"\.key$", RiskLevel.HIGH, "密钥文件"),
        (r"^/etc/", RiskLevel.HIGH, "系统配置目录"),

        # MEDIUM - 中等风险
        (r"\.env$", RiskLevel.MEDIUM, "环境变量文件"),
        (r"\.git/config$", RiskLevel.MEDIUM, "Git 配置"),
        (r"credentials", RiskLevel.MEDIUM, "凭证文件"),
        (r"secrets?", RiskLevel.MEDIUM, "密钥文件"),

        # LOW - 低风险
        (r"__pycache__", RiskLevel.LOW, "Python 缓存"),
        (r"\.log$", RiskLevel.LOW, "日志文件"),
        (r"node_modules", RiskLevel.LOW, "Node 模块"),
    ]

    # 安全工具列表（只读操作，自动批准）
    SAFE_TOOLS = {
        "Read", "Glob", "Grep", "LS",
        "TodoRead", "NotebookRead",
        "WebFetch", "WebSearch",
    }

    # 写入工具列表
    WRITE_TOOLS = {
        "Write", "Edit", "MultiEdit", "NotebookEdit",
    }

    # 执行工具列表
    EXEC_TOOLS = {
        "Bash", "Task",
    }

    @classmethod
    def get_bash_risk(cls, command: str) -> tuple[RiskLevel, str]:
        """获取 Bash 命令风险等级"""
        for pattern, level, description in cls.BASH_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return level, description
        return RiskLevel.LOW, "普通命令"

    @classmethod
    def get_file_risk(cls, file_path: str) -> tuple[RiskLevel, str]:
        """获取文件路径风险等级"""
        for pattern, level, description in cls.FILE_PATTERNS:
            if re.search(pattern, file_path, re.IGNORECASE):
                return level, description
        return RiskLevel.SAFE, "普通文件"

    @classmethod
    def is_safe_tool(cls, tool_name: str) -> bool:
        """检查是否为安全工具"""
        return tool_name in cls.SAFE_TOOLS


# ============================================================================
# Hook 机制
# ============================================================================

class HookType(Enum):
    """Hook 类型"""
    PRE_CHECK = "pre_check"           # 权限检查前
    POST_CHECK = "post_check"         # 权限检查后
    PRE_EXECUTE = "pre_execute"       # 执行前
    POST_EXECUTE = "post_execute"     # 执行后
    ON_ALLOW = "on_allow"             # 允许时
    ON_DENY = "on_deny"               # 拒绝时
    ON_ASK = "on_ask"                 # 询问时


@dataclass
class HookResult:
    """Hook 结果"""
    continue_: bool = True            # 是否继续执行
    override_action: Optional[PermissionAction] = None  # 覆盖权限行为
    override_reason: Optional[str] = None               # 覆盖原因
    metadata: Dict[str, Any] = field(default_factory=dict)


class Hook:
    """Hook 定义"""

    def __init__(
        self,
        hook_id: str,
        hook_type: HookType,
        callback: Callable[[PermissionContext], Union[HookResult, asyncio.Future]],
        priority: int = 0,
        enabled: bool = True,
        tools: Optional[Set[str]] = None  # 限制特定工具
    ):
        self.hook_id = hook_id
        self.hook_type = hook_type
        self.callback = callback
        self.priority = priority
        self.enabled = enabled
        self.tools = tools

    async def execute(self, context: PermissionContext) -> HookResult:
        """执行 Hook"""
        if self.tools and context.tool_name not in self.tools:
            return HookResult(continue_=True)

        try:
            result = self.callback(context)
            if asyncio.iscoroutine(result):
                result = await result
            return result if isinstance(result, HookResult) else HookResult(continue_=True)
        except Exception as e:
            return HookResult(
                continue_=True,
                metadata={"hook_error": str(e)}
            )


class HookRegistry:
    """Hook 注册表"""

    def __init__(self):
        self._hooks: Dict[HookType, List[Hook]] = {
            hook_type: [] for hook_type in HookType
        }

    def register(self, hook: Hook):
        """注册 Hook"""
        self._hooks[hook.hook_type].append(hook)
        # 按优先级排序（高优先级先执行）
        self._hooks[hook.hook_type].sort(key=lambda h: -h.priority)

    def unregister(self, hook_id: str):
        """注销 Hook"""
        for hook_type in HookType:
            self._hooks[hook_type] = [
                h for h in self._hooks[hook_type] if h.hook_id != hook_id
            ]

    async def run_hooks(
        self,
        hook_type: HookType,
        context: PermissionContext
    ) -> HookResult:
        """运行指定类型的所有 Hook"""
        final_result = HookResult(continue_=True)

        for hook in self._hooks[hook_type]:
            if not hook.enabled:
                continue

            result = await hook.execute(context)

            # 记录覆盖行为
            if result.override_action:
                final_result.override_action = result.override_action
                final_result.override_reason = result.override_reason

            # 合并元数据
            final_result.metadata.update(result.metadata)

            # 如果 Hook 返回不继续，停止执行
            if not result.continue_:
                final_result.continue_ = False
                break

        return final_result


# ============================================================================
# 权限策略
# ============================================================================

class PermissionPolicy(ABC):
    """权限策略基类"""

    @abstractmethod
    def check(self, context: PermissionContext) -> Optional[PermissionResult]:
        """检查权限，返回 None 表示不适用此策略"""
        pass


class DefaultPolicy(PermissionPolicy):
    """默认权限策略"""

    def __init__(
        self,
        auto_approve_safe: bool = True,
        ask_threshold: RiskLevel = RiskLevel.MEDIUM,
        deny_threshold: RiskLevel = RiskLevel.CRITICAL
    ):
        self.auto_approve_safe = auto_approve_safe
        self.ask_threshold = ask_threshold
        self.deny_threshold = deny_threshold

    def check(self, context: PermissionContext) -> Optional[PermissionResult]:
        tool_name = context.tool_name
        args = context.arguments

        # 1. 检查安全工具
        if DangerPatternRegistry.is_safe_tool(tool_name):
            return PermissionResult(
                action=PermissionAction.ALLOW,
                allowed=True,
                risk_level=RiskLevel.SAFE,
                source=PermissionSource.DEFAULT,
                reason="Safe tool (read-only)"
            )

        # 2. 确定风险等级
        risk_level, risk_reason = self._determine_risk(tool_name, args)

        # 3. 根据风险等级决定行为
        if risk_level == RiskLevel.CRITICAL:
            # 危险操作，默认拒绝但可以询问
            return PermissionResult(
                action=PermissionAction.ASK,
                allowed=False,
                risk_level=risk_level,
                source=PermissionSource.DEFAULT,
                reason=risk_reason,
                requires_confirmation=True,
                confirmation_message=f"危险操作 ({risk_level.value}): {risk_reason}"
            )

        if risk_level == RiskLevel.HIGH:
            # 高风险，需要确认
            return PermissionResult(
                action=PermissionAction.ASK,
                allowed=False,
                risk_level=risk_level,
                source=PermissionSource.DEFAULT,
                reason=risk_reason,
                requires_confirmation=True,
                confirmation_message=f"高风险操作: {risk_reason}"
            )

        if risk_level == RiskLevel.MEDIUM:
            # 中等风险，需要确认
            return PermissionResult(
                action=PermissionAction.ASK,
                allowed=False,
                risk_level=risk_level,
                source=PermissionSource.DEFAULT,
                reason=risk_reason,
                requires_confirmation=True,
                confirmation_message=f"需要确认: {risk_reason}"
            )

        # 低风险，自动批准
        return PermissionResult(
            action=PermissionAction.ALLOW,
            allowed=True,
            risk_level=risk_level,
            source=PermissionSource.DEFAULT,
            reason=risk_reason
        )

    def _determine_risk(self, tool_name: str, args: Dict) -> tuple[RiskLevel, str]:
        """确定操作风险等级"""
        if tool_name == "Bash":
            command = args.get("command", "")
            return DangerPatternRegistry.get_bash_risk(command)

        if tool_name in DangerPatternRegistry.WRITE_TOOLS:
            file_path = args.get("file_path", "")
            return DangerPatternRegistry.get_file_risk(file_path)

        if tool_name in DangerPatternRegistry.EXEC_TOOLS:
            return RiskLevel.MEDIUM, "执行操作"

        return RiskLevel.LOW, "未知操作"


class WhitelistPolicy(PermissionPolicy):
    """白名单策略"""

    def __init__(
        self,
        allowed_paths: List[str] = None,
        allowed_commands: List[str] = None,
        blocked_paths: List[str] = None,
        blocked_commands: List[str] = None
    ):
        self.allowed_paths = allowed_paths or []
        self.allowed_commands = allowed_commands or []
        self.blocked_paths = blocked_paths or []
        self.blocked_commands = blocked_commands or []

    def check(self, context: PermissionContext) -> Optional[PermissionResult]:
        tool_name = context.tool_name
        args = context.arguments

        # 检查文件路径白名单
        if tool_name in DangerPatternRegistry.WRITE_TOOLS:
            file_path = args.get("file_path", "")
            return self._check_path(file_path)

        # 检查命令白名单
        if tool_name == "Bash":
            command = args.get("command", "")
            return self._check_command(command)

        return None

    def _check_path(self, path: str) -> PermissionResult:
        """检查路径权限"""
        # 检查黑名单
        for blocked in self.blocked_paths:
            if blocked in path:
                return PermissionResult(
                    action=PermissionAction.DENY,
                    allowed=False,
                    risk_level=RiskLevel.HIGH,
                    source=PermissionSource.POLICY,
                    reason=f"Path is blocked: {blocked}"
                )

        # 检查白名单（如果配置了）
        if self.allowed_paths:
            allowed = any(
                path.startswith(allowed) or allowed in path
                for allowed in self.allowed_paths
            )
            if not allowed:
                return PermissionResult(
                    action=PermissionAction.DENY,
                    allowed=False,
                    risk_level=RiskLevel.MEDIUM,
                    source=PermissionSource.POLICY,
                    reason="Path not in whitelist"
                )

        return None  # 不适用，继续其他策略

    def _check_command(self, command: str) -> PermissionResult:
        """检查命令权限"""
        # 检查黑名单
        for blocked in self.blocked_commands:
            if blocked in command:
                return PermissionResult(
                    action=PermissionAction.DENY,
                    allowed=False,
                    risk_level=RiskLevel.HIGH,
                    source=PermissionSource.POLICY,
                    reason=f"Command pattern blocked: {blocked}"
                )

        return None


# ============================================================================
# 权限缓存
# ============================================================================

class PermissionCache:
    """权限缓存（会话级别）"""

    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self._approved: Dict[str, datetime] = {}
        self._denied: Dict[str, datetime] = {}

    def is_approved(self, tool_key: str) -> bool:
        """检查是否已批准"""
        return tool_key in self._approved

    def is_denied(self, tool_key: str) -> bool:
        """检查是否已拒绝"""
        return tool_key in self._denied

    def approve(self, tool_key: str):
        """记录批准"""
        self._cleanup()
        self._approved[tool_key] = datetime.now()
        self._denied.pop(tool_key, None)

    def deny(self, tool_key: str):
        """记录拒绝"""
        self._cleanup()
        self._denied[tool_key] = datetime.now()
        self._approved.pop(tool_key, None)

    def clear(self):
        """清除缓存"""
        self._approved.clear()
        self._denied.clear()

    def _cleanup(self):
        """清理过期缓存"""
        if len(self._approved) + len(self._denied) > self.max_size:
            # 清除一半最旧的记录
            items = sorted(
                list(self._approved.items()) + list(self._denied.items()),
                key=lambda x: x[1]
            )
            for key, _ in items[:self.max_size // 2]:
                self._approved.pop(key, None)
                self._denied.pop(key, None)


# ============================================================================
# 权限控制层
# ============================================================================

class PermissionControlLayer:
    """
    第二层：权限控制层

    功能：
    - 权限验证三元组 (allow, deny, ask)
    - Hook 机制绕过通道
    - 细粒度权限策略
    - 会话级权限缓存
    """

    def __init__(
        self,
        auto_approve_safe: bool = True,
        enable_cache: bool = True,
        policies: List[PermissionPolicy] = None
    ):
        self.hook_registry = HookRegistry()
        self.cache = PermissionCache() if enable_cache else None

        # 初始化策略
        self.policies = policies or []
        self.policies.insert(0, DefaultPolicy(auto_approve_safe=auto_approve_safe))

        # 待确认的操作
        self._pending_confirmations: Dict[str, PermissionContext] = {}

    async def check_permission(self, context: PermissionContext) -> PermissionResult:
        """
        检查权限

        Args:
            context: 权限上下文

        Returns:
            PermissionResult
        """
        tool_key = context.get_tool_key()

        # 1. 运行 PRE_CHECK hooks
        hook_result = await self.hook_registry.run_hooks(HookType.PRE_CHECK, context)
        if not hook_result.continue_:
            return PermissionResult(
                action=PermissionAction.DENY,
                allowed=False,
                risk_level=RiskLevel.HIGH,
                source=PermissionSource.HOOK_OVERRIDE,
                reason=hook_result.override_reason or "Blocked by hook"
            )

        # 2. 检查 Hook 覆盖
        if hook_result.override_action:
            return PermissionResult(
                action=hook_result.override_action,
                allowed=hook_result.override_action == PermissionAction.ALLOW,
                risk_level=RiskLevel.LOW,
                source=PermissionSource.HOOK_OVERRIDE,
                reason=hook_result.override_reason or "Overridden by hook",
                hook_id=hook_result.metadata.get("hook_id")
            )

        # 3. 检查缓存
        if self.cache:
            if self.cache.is_approved(tool_key):
                return PermissionResult(
                    action=PermissionAction.ALLOW,
                    allowed=True,
                    risk_level=RiskLevel.SAFE,
                    source=PermissionSource.SESSION_CACHE,
                    reason="Previously approved in this session"
                )
            if self.cache.is_denied(tool_key):
                return PermissionResult(
                    action=PermissionAction.DENY,
                    allowed=False,
                    risk_level=RiskLevel.SAFE,
                    source=PermissionSource.SESSION_CACHE,
                    reason="Previously denied in this session"
                )

        # 4. 应用策略
        for policy in self.policies:
            result = policy.check(context)
            if result:
                # 运行 POST_CHECK hooks
                post_hook_result = await self.hook_registry.run_hooks(
                    HookType.POST_CHECK, context
                )
                if post_hook_result.override_action:
                    result.action = post_hook_result.override_action
                    result.allowed = result.action == PermissionAction.ALLOW
                    result.source = PermissionSource.HOOK_OVERRIDE

                # 运行特定行为 hooks
                if result.action == PermissionAction.ALLOW:
                    await self.hook_registry.run_hooks(HookType.ON_ALLOW, context)
                elif result.action == PermissionAction.DENY:
                    await self.hook_registry.run_hooks(HookType.ON_DENY, context)
                elif result.action == PermissionAction.ASK:
                    await self.hook_registry.run_hooks(HookType.ON_ASK, context)

                return result

        # 5. 默认拒绝
        return PermissionResult(
            action=PermissionAction.DENY,
            allowed=False,
            risk_level=RiskLevel.HIGH,
            source=PermissionSource.DEFAULT,
            reason="No matching policy found"
        )

    def approve(self, context: PermissionContext):
        """批准操作"""
        tool_key = context.get_tool_key()
        if self.cache:
            self.cache.approve(tool_key)
        self._pending_confirmations.pop(tool_key, None)

    def deny(self, context: PermissionContext):
        """拒绝操作"""
        tool_key = context.get_tool_key()
        if self.cache:
            self.cache.deny(tool_key)
        self._pending_confirmations.pop(tool_key, None)

    def register_hook(self, hook: Hook):
        """注册 Hook"""
        self.hook_registry.register(hook)

    def unregister_hook(self, hook_id: str):
        """注销 Hook"""
        self.hook_registry.unregister(hook_id)

    def add_policy(self, policy: PermissionPolicy, index: int = 0):
        """添加策略"""
        self.policies.insert(index, policy)

    def clear_cache(self):
        """清除缓存"""
        if self.cache:
            self.cache.clear()

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "policies_count": len(self.policies),
            "hooks_count": sum(
                len(hooks) for hooks in self.hook_registry._hooks.values()
            ),
            "cache_size": len(self.cache._approved) + len(self.cache._denied) if self.cache else 0,
            "pending_confirmations": len(self._pending_confirmations)
        }
