"""
工具执行引擎 - 完整6阶段架构

阶段1: Discovery - 工具发现和验证
  - 工具名称解析
  - 工具注册表查找
  - 可用性检查

阶段2: Validation - 输入验证
  - Zod-like schema 验证
  - 参数类型检查
  - 必填参数验证
  - 格式化错误消息

阶段3: Authorization - 权限检查和门控
  - checkPermission 调用
  - allow/delay/ask 三种行为
  - hook 机制支持
  - 安全策略应用

阶段4: Cancellation - 取消检查
  - AbortController 信号
  - 用户中断处理
  - 超时控制

阶段5: Execution - 工具执行
  - pw5 具体执行函数
  - 异步生成器处理
  - 流式结果输出
  - 错误捕获与处理

阶段6: PostProcessing - 结构格式化和清理
  - mapToolResultToToolResultBlock
  - 结果标准化
  - 状态清理
  - 分析事件记录

输出: 结果到 agent loop
"""
import os
import json
import asyncio
import time
import hashlib
import re
import traceback
from typing import Dict, List, Optional, Any, Callable, Awaitable, AsyncGenerator, Union
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from abc import ABC, abstractmethod


# ============================================================================
# 枚举和数据类
# ============================================================================

class ToolStatus(Enum):
    """工具调用状态"""
    PENDING = "pending"
    DISCOVERED = "discovered"
    VALIDATED = "validated"
    AUTHORIZED = "authorized"
    RUNNING = "running"
    STREAMING = "streaming"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    NEEDS_CONFIRMATION = "needs_confirmation"
    DENIED = "denied"
    TIMEOUT = "timeout"


class ToolPhase(Enum):
    """工具执行6阶段"""
    DISCOVERY = "discovery"           # 1. 工具发现
    VALIDATION = "validation"         # 2. 参数验证
    AUTHORIZATION = "authorization"   # 3. 权限检测
    CANCELLATION = "cancellation"     # 4. 取消检查
    EXECUTION = "execution"           # 5. 实际执行
    POST_PROCESSING = "post_processing"  # 6. 结果处理


class PermissionAction(Enum):
    """权限行为"""
    ALLOW = "allow"      # 允许执行
    DELAY = "delay"      # 延迟（需要确认）
    ASK = "ask"          # 询问用户


class DangerLevel(Enum):
    """危险等级"""
    SAFE = "safe"
    LOW = "low"
    MODERATE = "moderate"
    DANGEROUS = "dangerous"
    CRITICAL = "critical"


@dataclass
class AbortSignal:
    """取消信号 (类似 AbortController)"""
    aborted: bool = False
    reason: Optional[str] = None

    def abort(self, reason: str = None):
        self.aborted = True
        self.reason = reason

    def throw_if_aborted(self):
        if self.aborted:
            raise ToolCancelledError(self.reason or "Operation aborted")


@dataclass
class ToolCall:
    """工具调用"""
    id: str
    name: str
    arguments: Dict[str, Any]
    status: ToolStatus = ToolStatus.PENDING
    phase: ToolPhase = ToolPhase.DISCOVERY
    start_time: float = 0
    end_time: float = 0
    error: Optional[str] = None
    result: Optional[str] = None
    phase_history: List[Dict] = field(default_factory=list)
    abort_signal: AbortSignal = field(default_factory=AbortSignal)
    timeout_ms: int = 120000
    metadata: Dict = field(default_factory=dict)


@dataclass
class ValidationResult:
    """验证结果"""
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    normalized_args: Optional[Dict[str, Any]] = None


@dataclass
class AuthorizationResult:
    """授权结果"""
    action: PermissionAction
    allowed: bool
    danger_level: DangerLevel
    reason: Optional[str] = None
    requires_confirmation: bool = False
    confirmation_message: Optional[str] = None


@dataclass
class ToolResultBlock:
    """标准化工具结果块"""
    tool_call_id: str
    tool_name: str
    type: str  # "tool_result" | "tool_error"
    content: str
    is_error: bool = False
    duration_ms: int = 0
    phase_timings: Dict[str, int] = field(default_factory=dict)
    metadata: Dict = field(default_factory=dict)


@dataclass
class ExecutionResult:
    """执行结果 (向后兼容)"""
    tool_call_id: str
    tool_name: str
    success: bool
    output: str
    duration_ms: int
    phase_timings: Dict[str, int]
    needs_confirmation: bool = False
    result_block: Optional[ToolResultBlock] = None


class ToolError(Exception):
    """工具错误基类"""
    pass


class ToolCancelledError(ToolError):
    """工具取消错误"""
    pass


class ToolTimeoutError(ToolError):
    """工具超时错误"""
    pass


class ValidationError(ToolError):
    """验证错误"""
    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__(f"Validation failed: {'; '.join(errors)}")


# ============================================================================
# 阶段1: 工具发现 - ToolRegistry
# ============================================================================

class ToolDefinition:
    """工具定义"""
    def __init__(
        self,
        name: str,
        description: str,
        executor: Callable,
        schema: Dict = None,
        timeout_ms: int = 120000,
        dangerous: bool = False
    ):
        self.name = name
        self.description = description
        self.executor = executor
        self.schema = schema or {}
        self.timeout_ms = timeout_ms
        self.dangerous = dangerous


class ToolRegistry:
    """
    工具注册表
    阶段1: 工具发现
    """
    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}
        self._aliases: Dict[str, str] = {}

    def register(self, definition: ToolDefinition):
        """注册工具"""
        self._tools[definition.name] = definition

    def register_alias(self, alias: str, tool_name: str):
        """注册别名"""
        self._aliases[alias] = tool_name

    def resolve(self, name: str) -> Optional[str]:
        """解析工具名称（支持别名）"""
        if name in self._tools:
            return name
        return self._aliases.get(name)

    def lookup(self, name: str) -> Optional[ToolDefinition]:
        """查找工具定义"""
        resolved_name = self.resolve(name)
        if resolved_name:
            return self._tools[resolved_name]
        return None

    def is_available(self, name: str) -> bool:
        """检查工具是否可用"""
        return self.resolve(name) is not None

    def get_all_tools(self) -> List[str]:
        """获取所有工具名称"""
        return list(self._tools.keys())


# ============================================================================
# 阶段2: 参数验证 - Zod-like Schema Validator
# ============================================================================

class SchemaValidator:
    """
    Zod-like Schema 验证器
    阶段2: 输入验证
    """

    @staticmethod
    def validate_string(value: Any, schema: Dict) -> tuple[bool, str]:
        if not isinstance(value, str):
            return False, f"Expected string, got {type(value).__name__}"
        min_len = schema.get("minLength")
        max_len = schema.get("maxLength")
        pattern = schema.get("pattern")
        if min_len and len(value) < min_len:
            return False, f"String length {len(value)} is less than minimum {min_len}"
        if max_len and len(value) > max_len:
            return False, f"String length {len(value)} exceeds maximum {max_len}"
        if pattern and not re.match(pattern, value):
            return False, f"String does not match pattern: {pattern}"
        return True, ""

    @staticmethod
    def validate_integer(value: Any, schema: Dict) -> tuple[bool, str]:
        if not isinstance(value, int) or isinstance(value, bool):
            return False, f"Expected integer, got {type(value).__name__}"
        min_val = schema.get("minimum")
        max_val = schema.get("maximum")
        if min_val is not None and value < min_val:
            return False, f"Value {value} is less than minimum {min_val}"
        if max_val is not None and value > max_val:
            return False, f"Value {value} exceeds maximum {max_val}"
        return True, ""

    @staticmethod
    def validate_boolean(value: Any, schema: Dict) -> tuple[bool, str]:
        if not isinstance(value, bool):
            return False, f"Expected boolean, got {type(value).__name__}"
        return True, ""

    @staticmethod
    def validate_array(value: Any, schema: Dict) -> tuple[bool, str]:
        if not isinstance(value, list):
            return False, f"Expected array, got {type(value).__name__}"
        min_items = schema.get("minItems")
        max_items = schema.get("maxItems")
        if min_items is not None and len(value) < min_items:
            return False, f"Array length {len(value)} is less than minimum {min_items}"
        if max_items is not None and len(value) > max_items:
            return False, f"Array length {len(value)} exceeds maximum {max_items}"
        return True, ""

    @classmethod
    def validate(cls, args: Dict, schema: Dict) -> ValidationResult:
        """验证参数"""
        errors = []
        warnings = []
        normalized = {}

        properties = schema.get("properties", {})
        required = schema.get("required", [])

        # 检查必填参数
        for req in required:
            if req not in args:
                errors.append(f"Missing required parameter: {req}")

        # 验证每个参数
        for key, value in args.items():
            if key not in properties:
                warnings.append(f"Unknown parameter: {key}")
                normalized[key] = value
                continue

            prop_schema = properties[key]
            expected_type = prop_schema.get("type")

            # 类型验证
            valid = True
            error_msg = ""

            if expected_type == "string":
                valid, error_msg = cls.validate_string(value, prop_schema)
            elif expected_type == "integer":
                valid, error_msg = cls.validate_integer(value, prop_schema)
            elif expected_type == "boolean":
                valid, error_msg = cls.validate_boolean(value, prop_schema)
            elif expected_type == "array":
                valid, error_msg = cls.validate_array(value, prop_schema)
            elif expected_type == "object":
                if not isinstance(value, dict):
                    valid = False
                    error_msg = f"Expected object, got {type(value).__name__}"

            if not valid:
                errors.append(f"Parameter '{key}': {error_msg}")
            else:
                normalized[key] = value

        # 应用默认值
        for key, prop_schema in properties.items():
            if key not in normalized and "default" in prop_schema:
                normalized[key] = prop_schema["default"]

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            normalized_args=normalized
        )


# ============================================================================
# 阶段3: 权限检查和门控 - PermissionGate
# ============================================================================

# 危险操作模式
DANGEROUS_PATTERNS = {
    "Bash": [
        (r"rm\s+-rf\s+/", DangerLevel.CRITICAL, "Recursive force delete from root"),
        (r"rm\s+-rf\s+~", DangerLevel.CRITICAL, "Recursive force delete home directory"),
        (r"rm\s+-rf\s+\*", DangerLevel.CRITICAL, "Recursive force delete all"),
        (r"mkfs", DangerLevel.CRITICAL, "Format filesystem"),
        (r"dd\s+if=", DangerLevel.DANGEROUS, "Disk dump operation"),
        (r":\(\)\s*\{\s*:\|:&\s*\}", DangerLevel.CRITICAL, "Fork bomb detected"),
        (r"wget.*\|\s*bash", DangerLevel.DANGEROUS, "Remote code execution"),
        (r"curl.*\|\s*bash", DangerLevel.DANGEROUS, "Remote code execution"),
        (r"git\s+push\s+--force", DangerLevel.DANGEROUS, "Force push to remote"),
        (r"git\s+push\s+-f", DangerLevel.DANGEROUS, "Force push to remote"),
        (r"drop\s+database", DangerLevel.CRITICAL, "Drop database"),
        (r"truncate\s+table", DangerLevel.DANGEROUS, "Truncate table"),
        (r"sudo\s+", DangerLevel.MODERATE, "Sudo command"),
        (r"chmod\s+777", DangerLevel.MODERATE, "Insecure permissions"),
    ],
    "Write": [
        (r"/etc/passwd", DangerLevel.CRITICAL, "Writing to passwd file"),
        (r"/etc/shadow", DangerLevel.CRITICAL, "Writing to shadow file"),
        (r"\.ssh/authorized_keys", DangerLevel.DANGEROUS, "Modifying SSH keys"),
        (r"\.env$", DangerLevel.MODERATE, "Writing to .env file"),
        (r"__pycache__", DangerLevel.LOW, "Writing to cache directory"),
    ],
    "Edit": [
        (r"/etc/passwd", DangerLevel.CRITICAL, "Editing passwd file"),
        (r"/etc/shadow", DangerLevel.CRITICAL, "Editing shadow file"),
        (r"\.env$", DangerLevel.MODERATE, "Editing .env file"),
    ],
    "MultiEdit": [
        (r"/etc/passwd", DangerLevel.CRITICAL, "Multi-editing passwd file"),
        (r"/etc/shadow", DangerLevel.CRITICAL, "Multi-editing shadow file"),
        (r"\.env$", DangerLevel.MODERATE, "Multi-editing .env file"),
    ],
    "NotebookEdit": [
        (r"__pycache__", DangerLevel.LOW, "Editing notebook in cache"),
    ]
}

# 安全工具（自动批准）- 只读操作
SAFE_TOOLS = {
    "Glob", "Grep", "Read", "LS",  # 文件系统只读
    "TodoRead",                      # 任务只读
    "WebFetch", "WebSearch",         # 网络（相对安全）
    "NotebookRead"                   # Notebook 只读
}


class HookType(Enum):
    """Hook 类型"""
    PRE_EXECUTE = "pre_execute"
    POST_EXECUTE = "post_execute"
    ON_ERROR = "on_error"
    ON_CONFIRM = "on_confirm"


@dataclass
class HookContext:
    """Hook 上下文"""
    tool_call: ToolCall
    phase: ToolPhase
    result: Any = None
    error: Optional[Exception] = None


class PermissionGate:
    """
    权限门控
    阶段3: 权限检查和门控

    支持:
    - checkPermission 调用
    - allow/delay/ask 三种行为
    - hook 机制支持
    - 安全策略应用
    """

    def __init__(self, auto_approve_safe: bool = True):
        self.auto_approve_safe = auto_approve_safe
        self.approved_tools: set = set()
        self.denied_tools: set = set()
        self.session_approvals: Dict[str, bool] = {}
        self._hooks: Dict[HookType, List[Callable]] = {
            hook_type: [] for hook_type in HookType
        }
        self._security_policies: List[Callable] = []

    def register_hook(self, hook_type: HookType, callback: Callable):
        """注册 hook"""
        self._hooks[hook_type].append(callback)

    def register_security_policy(self, policy: Callable):
        """注册安全策略"""
        self._security_policies.append(policy)

    async def _run_hooks(self, hook_type: HookType, context: HookContext):
        """运行 hooks"""
        for hook in self._hooks[hook_type]:
            try:
                result = hook(context)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                print(f"[Hook Error] {hook_type.value}: {e}")

    def check_permission(self, tool_call: ToolCall) -> AuthorizationResult:
        """
        检查工具调用权限
        返回 allow/delay/ask 三种行为
        """
        tool_name = tool_call.name
        args = tool_call.arguments

        # 生成工具唯一标识
        tool_key = self._get_tool_key(tool_call)

        # 检查是否已批准/拒绝
        if tool_key in self.approved_tools:
            return AuthorizationResult(
                action=PermissionAction.ALLOW,
                allowed=True,
                danger_level=DangerLevel.SAFE,
                reason="Previously approved"
            )

        if tool_key in self.denied_tools:
            return AuthorizationResult(
                action=PermissionAction.ALLOW,
                allowed=False,
                danger_level=DangerLevel.SAFE,
                reason="Previously denied"
            )

        # 应用安全策略
        for policy in self._security_policies:
            policy_result = policy(tool_call)
            if policy_result:
                return policy_result

        # 确定危险等级
        danger_level, reason = self._get_danger_level(tool_name, args)

        # 根据危险等级决定行为
        if danger_level == DangerLevel.SAFE and self.auto_approve_safe:
            return AuthorizationResult(
                action=PermissionAction.ALLOW,
                allowed=True,
                danger_level=danger_level,
                reason="Auto-approved safe tool"
            )

        if danger_level in [DangerLevel.DANGEROUS, DangerLevel.CRITICAL]:
            return AuthorizationResult(
                action=PermissionAction.ASK,
                allowed=False,
                danger_level=danger_level,
                requires_confirmation=True,
                reason=reason,
                confirmation_message=f"Dangerous operation ({danger_level.value}): {reason}"
            )

        if danger_level == DangerLevel.MODERATE:
            return AuthorizationResult(
                action=PermissionAction.DELAY,
                allowed=False,
                danger_level=danger_level,
                requires_confirmation=True,
                reason=reason,
                confirmation_message=f"Requires confirmation: {reason}"
            )

        # 低风险，允许执行
        return AuthorizationResult(
            action=PermissionAction.ALLOW,
            allowed=True,
            danger_level=danger_level,
            reason="Low risk operation"
        )

    def _get_danger_level(self, tool_name: str, args: Dict) -> tuple[DangerLevel, str]:
        """获取危险等级"""
        # 安全工具（只读）
        if tool_name in SAFE_TOOLS:
            return DangerLevel.SAFE, "Read-only operation"

        # 检查危险模式
        patterns = DANGEROUS_PATTERNS.get(tool_name, [])
        target = ""

        # 根据工具类型确定检查目标
        if tool_name == "Bash":
            target = args.get("command", "")
        elif tool_name in ["Write", "Edit", "MultiEdit"]:
            target = args.get("file_path", "")
        elif tool_name == "NotebookEdit":
            target = args.get("notebook_path", "")
        elif tool_name == "Task":
            # Task 工具需要检查 prompt 中的潜在危险
            target = args.get("prompt", "")

        for pattern, level, description in patterns:
            if re.search(pattern, target, re.IGNORECASE):
                return level, description

        # 默认风险评估
        write_tools = ["Write", "Edit", "MultiEdit", "NotebookEdit"]
        exec_tools = ["Bash", "Task"]

        if tool_name in write_tools:
            return DangerLevel.MODERATE, "Write operation"
        elif tool_name in exec_tools:
            return DangerLevel.MODERATE, "Execute operation"
        elif tool_name == "TodoWrite":
            return DangerLevel.LOW, "Task management"

        return DangerLevel.LOW, "Unknown operation"

    def _get_tool_key(self, tool_call: ToolCall) -> str:
        """生成工具唯一标识"""
        key_data = f"{tool_call.name}:{json.dumps(tool_call.arguments, sort_keys=True)}"
        return hashlib.md5(key_data.encode()).hexdigest()[:16]

    def approve(self, tool_call: ToolCall):
        """批准工具调用"""
        tool_key = self._get_tool_key(tool_call)
        self.approved_tools.add(tool_key)

    def deny(self, tool_call: ToolCall):
        """拒绝工具调用"""
        tool_key = self._get_tool_key(tool_call)
        self.denied_tools.add(tool_key)


# ============================================================================
# 阶段4: 取消检查 - CancellationController
# ============================================================================

class CancellationController:
    """
    取消控制器
    阶段4: 取消检查

    支持:
    - AbortController 信号
    - 用户中断处理
    - 超时控制
    """

    def __init__(self, default_timeout_ms: int = 120000):
        self.default_timeout_ms = default_timeout_ms
        self._active_tasks: Dict[str, asyncio.Task] = {}

    def check_aborted(self, tool_call: ToolCall):
        """检查是否已取消"""
        tool_call.abort_signal.throw_if_aborted()

    async def with_timeout(
        self,
        tool_call: ToolCall,
        coro: Awaitable
    ) -> Any:
        """带超时控制执行"""
        timeout_ms = tool_call.timeout_ms or self.default_timeout_ms
        timeout_sec = timeout_ms / 1000

        try:
            return await asyncio.wait_for(coro, timeout=timeout_sec)
        except asyncio.TimeoutError:
            raise ToolTimeoutError(f"Tool execution timed out after {timeout_ms}ms")

    def register_task(self, tool_call_id: str, task: asyncio.Task):
        """注册任务"""
        self._active_tasks[tool_call_id] = task

    def cancel_task(self, tool_call_id: str, reason: str = None):
        """取消任务"""
        if tool_call_id in self._active_tasks:
            task = self._active_tasks[tool_call_id]
            task.cancel(reason)

    def cleanup_task(self, tool_call_id: str):
        """清理任务"""
        self._active_tasks.pop(tool_call_id, None)


# ============================================================================
# 阶段5: 工具执行 - ToolExecutor
# ============================================================================

class ToolExecutor:
    """
    工具执行器
    阶段5: 工具执行

    支持:
    - pw5 具体执行函数
    - 异步生成器处理
    - 流式结果输出
    - 错误捕获与处理
    """

    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    async def execute(
        self,
        tool_call: ToolCall,
        abort_signal: AbortSignal = None
    ) -> AsyncGenerator[Dict, None]:
        """
        执行工具，支持流式输出
        """
        tool_def = self.registry.lookup(tool_call.name)
        if not tool_def:
            yield {
                "type": "error",
                "error": f"Tool not found: {tool_call.name}"
            }
            return

        executor = tool_def.executor

        try:
            # 检查取消信号
            if abort_signal:
                abort_signal.throw_if_aborted()

            # 执行工具
            tool_call.status = ToolStatus.RUNNING

            # 判断是否是生成器
            result = executor(tool_call)

            if asyncio.isasyncgen(result):
                # 流式输出
                tool_call.status = ToolStatus.STREAMING
                final_result = ""
                async for chunk in result:
                    # 检查取消
                    if abort_signal:
                        abort_signal.throw_if_aborted()

                    if isinstance(chunk, dict):
                        yield chunk
                        if chunk.get("type") == "text":
                            final_result += chunk.get("text", "")
                    else:
                        text = str(chunk)
                        final_result += text
                        yield {"type": "text", "text": text}

                yield {"type": "complete", "result": final_result}

            elif asyncio.iscoroutine(result):
                # 异步执行
                output = await result
                yield {"type": "complete", "result": str(output)}

            else:
                # 同步执行
                yield {"type": "complete", "result": str(result)}

        except ToolCancelledError as e:
            tool_call.status = ToolStatus.CANCELLED
            yield {"type": "cancelled", "reason": str(e)}

        except ToolTimeoutError as e:
            tool_call.status = ToolStatus.TIMEOUT
            yield {"type": "timeout", "error": str(e)}

        except Exception as e:
            tool_call.status = ToolStatus.FAILED
            error_msg = f"{type(e).__name__}: {str(e)}"
            traceback.print_exc()
            yield {"type": "error", "error": error_msg}


# ============================================================================
# 阶段6: 结果格式化和清理 - ResultFormatter
# ============================================================================

class ResultFormatter:
    """
    结果格式化器
    阶段6: 结构格式化和清理

    支持:
    - mapToolResultToToolResultBlock
    - 结果标准化
    - 状态清理
    - 分析事件记录
    """

    MAX_OUTPUT_LENGTH = 10000

    @classmethod
    def map_to_result_block(
        cls,
        tool_call: ToolCall,
        execution_result: Dict,
        phase_timings: Dict[str, int]
    ) -> ToolResultBlock:
        """将执行结果映射为标准化结果块"""
        result_type = execution_result.get("type", "complete")
        content = execution_result.get("result") or execution_result.get("error", "")
        is_error = result_type in ["error", "timeout", "cancelled"]

        # 限制输出长度
        if len(content) > cls.MAX_OUTPUT_LENGTH:
            content = content[:cls.MAX_OUTPUT_LENGTH] + f"\n... (truncated, {len(content)} total bytes)"

        return ToolResultBlock(
            tool_call_id=tool_call.id,
            tool_name=tool_call.name,
            type="tool_error" if is_error else "tool_result",
            content=content,
            is_error=is_error,
            duration_ms=int((tool_call.end_time - tool_call.start_time) * 1000) if tool_call.end_time else 0,
            phase_timings=phase_timings,
            metadata={
                "status": tool_call.status.value,
                "phase": tool_call.phase.value,
                "result_type": result_type
            }
        )

    @classmethod
    def cleanup(cls, tool_call: ToolCall):
        """清理工具调用状态"""
        tool_call.end_time = time.time()
        # 保留必要信息，清理临时数据
        tool_call.metadata.pop("temp", None)

    @classmethod
    def record_analytics(
        cls,
        tool_call: ToolCall,
        result_block: ToolResultBlock
    ) -> Dict:
        """记录分析事件"""
        return {
            "event_type": "tool_execution",
            "tool_name": tool_call.name,
            "tool_call_id": tool_call.id,
            "status": tool_call.status.value,
            "duration_ms": result_block.duration_ms,
            "phase_timings": result_block.phase_timings,
            "is_error": result_block.is_error,
            "timestamp": datetime.now().isoformat()
        }


# ============================================================================
# 并发控制器
# ============================================================================

class ConcurrencyController:
    """
    并发控制器
    最大支持 10 并发
    """

    def __init__(self, max_concurrent: int = 10):
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.active_tasks: Dict[str, asyncio.Task] = {}
        self.completed_count = 0
        self.failed_count = 0

    async def submit(self, tool_call: ToolCall, executor: Callable[..., Awaitable]) -> Any:
        """提交工具调用"""
        async with self.semaphore:
            tool_call.status = ToolStatus.RUNNING
            tool_call.start_time = time.time()

            try:
                result = await executor(tool_call)
                tool_call.status = ToolStatus.COMPLETED
                self.completed_count += 1
                return result
            except Exception as e:
                tool_call.status = ToolStatus.FAILED
                tool_call.error = str(e)
                self.failed_count += 1
                raise
            finally:
                tool_call.end_time = time.time()

    async def submit_batch(self, tool_calls: List[ToolCall], executor: Callable[..., Awaitable]) -> List[Any]:
        """批量提交（并行执行）"""
        tasks = [
            self.submit(tc, executor)
            for tc in tool_calls
        ]
        return await asyncio.gather(*tasks, return_exceptions=True)

    def get_stats(self) -> Dict:
        """获取并发统计"""
        return {
            "max_concurrent": self.max_concurrent,
            "active_tasks": len(self.active_tasks),
            "completed": self.completed_count,
            "failed": self.failed_count
        }


# ============================================================================
# 6阶段工具执行管道
# ============================================================================

class ToolExecutionPipeline:
    """
    6阶段工具执行管道

    Phase 1: Discovery - 工具发现
    Phase 2: Validation - 参数验证
    Phase 3: Authorization - 权限检查
    Phase 4: Cancellation - 取消检查
    Phase 5: Execution - 工具执行
    Phase 6: PostProcessing - 结果处理
    """

    def __init__(
        self,
        tools: Dict[str, Callable],
        permission_gate: PermissionGate = None,
        max_concurrent: int = 10,
        default_timeout_ms: int = 120000,
        on_phase_change: Callable[[ToolCall, ToolPhase], None] = None,
        on_streaming: Callable[[Dict], None] = None
    ):
        # 构建工具注册表
        self.registry = ToolRegistry()
        for name, executor in tools.items():
            self.registry.register(ToolDefinition(
                name=name,
                description=f"Tool: {name}",
                executor=executor
            ))

        self.permission_gate = permission_gate or PermissionGate()
        self.cancellation = CancellationController(default_timeout_ms)
        self.executor = ToolExecutor(self.registry)
        self.concurrency = ConcurrencyController(max_concurrent)
        self.validator = SchemaValidator()

        self.on_phase_change = on_phase_change
        self.on_streaming = on_streaming

        # 工具 Schema
        self.tool_schemas = self._build_tool_schemas()

        # 分析事件
        self.analytics: List[Dict] = []

    def _build_tool_schemas(self) -> Dict[str, Dict]:
        """构建工具 Schema - 15类工具"""
        return {
            # ===== 文件操作类 (5个) =====
            "Read": {
                "type": "object",
                "required": ["file_path"],
                "properties": {
                    "file_path": {"type": "string", "minLength": 1},
                    "offset": {"type": "integer", "default": 1, "minimum": 1},
                    "limit": {"type": "integer", "default": 2000, "minimum": 1, "maximum": 10000}
                }
            },
            "Write": {
                "type": "object",
                "required": ["file_path", "content"],
                "properties": {
                    "file_path": {"type": "string", "minLength": 1},
                    "content": {"type": "string"}
                }
            },
            "Edit": {
                "type": "object",
                "required": ["file_path", "old_string", "new_string"],
                "properties": {
                    "file_path": {"type": "string", "minLength": 1},
                    "old_string": {"type": "string", "minLength": 1},
                    "new_string": {"type": "string"},
                    "replace_all": {"type": "boolean", "default": False}
                }
            },
            "MultiEdit": {
                "type": "object",
                "required": ["file_path", "edits"],
                "properties": {
                    "file_path": {"type": "string", "minLength": 1},
                    "edits": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "old_string": {"type": "string"},
                                "new_string": {"type": "string"},
                                "replace_all": {"type": "boolean"}
                            }
                        }
                    }
                }
            },
            "LS": {
                "type": "object",
                "required": [],
                "properties": {
                    "path": {"type": "string"},
                    "ignore": {"type": "array", "items": {"type": "string"}}
                }
            },

            # ===== 搜索类 (2个) =====
            "Glob": {
                "type": "object",
                "required": ["pattern"],
                "properties": {
                    "pattern": {"type": "string", "minLength": 1},
                    "path": {"type": "string"}
                }
            },
            "Grep": {
                "type": "object",
                "required": ["pattern"],
                "properties": {
                    "pattern": {"type": "string", "minLength": 1},
                    "path": {"type": "string"},
                    "output_mode": {"type": "string", "default": "content"},
                    "-i": {"type": "boolean", "default": False},
                    "-n": {"type": "boolean", "default": True}
                }
            },

            # ===== 任务管理类 (3个) =====
            "TodoRead": {
                "type": "object",
                "required": [],
                "properties": {}
            },
            "TodoWrite": {
                "type": "object",
                "required": ["todos"],
                "properties": {
                    "todos": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "content": {"type": "string"},
                                "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
                                "priority": {"type": "string", "enum": ["low", "medium", "high"]}
                            }
                        }
                    }
                }
            },
            "Task": {
                "type": "object",
                "required": ["prompt"],
                "properties": {
                    "prompt": {"type": "string", "minLength": 1},
                    "subagent_type": {"type": "string"},
                    "description": {"type": "string"},
                    "model": {"type": "string"}
                }
            },

            # ===== 命令执行类 (1个) =====
            "Bash": {
                "type": "object",
                "required": ["command"],
                "properties": {
                    "command": {"type": "string", "minLength": 1},
                    "timeout": {"type": "integer", "default": 120000, "minimum": 1000, "maximum": 600000},
                    "description": {"type": "string"}
                }
            },

            # ===== 网络类 (2个) =====
            "WebFetch": {
                "type": "object",
                "required": ["url"],
                "properties": {
                    "url": {"type": "string", "format": "uri"},
                    "timeout": {"type": "integer", "default": 30000},
                    "headers": {"type": "object"}
                }
            },
            "WebSearch": {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "minLength": 1},
                    "allowed_domains": {"type": "array", "items": {"type": "string"}},
                    "blocked_domains": {"type": "array", "items": {"type": "string"}}
                }
            },

            # ===== Notebook类 (2个) =====
            "NotebookRead": {
                "type": "object",
                "required": ["notebook_path"],
                "properties": {
                    "notebook_path": {"type": "string", "minLength": 1},
                    "cell_id": {"type": "string"}
                }
            },
            "NotebookEdit": {
                "type": "object",
                "required": ["notebook_path", "new_source", "cell_id"],
                "properties": {
                    "notebook_path": {"type": "string", "minLength": 1},
                    "cell_id": {"type": "string"},
                    "new_source": {"type": "string"},
                    "cell_type": {"type": "string", "enum": ["code", "markdown"]},
                    "edit_mode": {"type": "string", "enum": ["replace", "insert", "delete"]}
                }
            }
        }

    def _advance_phase(self, tool_call: ToolCall, new_phase: ToolPhase):
        """推进到下一阶段"""
        old_phase = tool_call.phase
        tool_call.phase = new_phase

        # 记录阶段历史
        tool_call.phase_history.append({
            "phase": new_phase.value,
            "timestamp": time.time(),
            "from_phase": old_phase.value
        })

        # 回调
        if self.on_phase_change:
            self.on_phase_change(tool_call, new_phase)

        print(f"[ToolPipeline] {tool_call.id}: {old_phase.value} → {new_phase.value}")

    # ========================================================================
    # Phase 1: Discovery - 工具发现
    # ========================================================================
    def _phase_discovery(self, tool_call: ToolCall) -> Dict:
        """
        阶段1: 工具发现
        - 工具名称解析
        - 工具注册表查找
        - 可用性检查
        """
        # 解析名称（支持别名）
        resolved_name = self.registry.resolve(tool_call.name)

        if not resolved_name:
            return {
                "success": False,
                "error": f"Tool not found: {tool_call.name}",
                "available_tools": self.registry.get_all_tools()
            }

        # 更新为解析后的名称
        tool_call.name = resolved_name
        tool_call.status = ToolStatus.DISCOVERED

        return {"success": True, "tool_name": resolved_name}

    # ========================================================================
    # Phase 2: Validation - 参数验证
    # ========================================================================
    def _phase_validation(self, tool_call: ToolCall) -> ValidationResult:
        """
        阶段2: 输入验证
        - Zod-like schema 验证
        - 参数类型检查
        - 必填参数验证
        - 格式化错误消息
        """
        schema = self.tool_schemas.get(tool_call.name)

        if not schema:
            # 无 schema，跳过验证
            return ValidationResult(
                valid=True,
                normalized_args=tool_call.arguments
            )

        result = self.validator.validate(tool_call.arguments, schema)

        if result.valid and result.normalized_args:
            # 使用规范化后的参数
            tool_call.arguments = result.normalized_args
            tool_call.status = ToolStatus.VALIDATED

        return result

    # ========================================================================
    # Phase 3: Authorization - 权限检查
    # ========================================================================
    async def _phase_authorization(self, tool_call: ToolCall) -> AuthorizationResult:
        """
        阶段3: 权限检查和门控
        - checkPermission 调用
        - allow/delay/ask 三种行为
        - hook 机制支持
        - 安全策略应用
        """
        result = self.permission_gate.check_permission(tool_call)

        # 运行 pre-execute hooks
        hook_ctx = HookContext(tool_call=tool_call, phase=ToolPhase.AUTHORIZATION)
        await self.permission_gate._run_hooks(HookType.PRE_EXECUTE, hook_ctx)

        if result.action == PermissionAction.ALLOW:
            tool_call.status = ToolStatus.AUTHORIZED

        return result

    # ========================================================================
    # Phase 4: Cancellation - 取消检查
    # ========================================================================
    def _phase_cancellation(self, tool_call: ToolCall) -> bool:
        """
        阶段4: 取消检查
        - AbortController 信号
        - 用户中断处理
        - 超时控制
        """
        try:
            self.cancellation.check_aborted(tool_call)
            return True  # 可以继续执行
        except ToolCancelledError:
            tool_call.status = ToolStatus.CANCELLED
            return False

    # ========================================================================
    # Phase 5: Execution - 工具执行
    # ========================================================================
    async def _phase_execution(
        self,
        tool_call: ToolCall
    ) -> AsyncGenerator[Dict, None]:
        """
        阶段5: 工具执行
        - pw5 具体执行函数
        - 异步生成器处理
        - 流式结果输出
        - 错误捕获与处理
        """
        async for event in self.executor.execute(tool_call, tool_call.abort_signal):
            # 流式回调
            if self.on_streaming:
                self.on_streaming(event)
            yield event

    # ========================================================================
    # Phase 6: PostProcessing - 结果处理
    # ========================================================================
    def _phase_post_processing(
        self,
        tool_call: ToolCall,
        execution_result: Dict,
        phase_timings: Dict
    ) -> ToolResultBlock:
        """
        阶段6: 结构格式化和清理
        - mapToolResultToToolResultBlock
        - 结果标准化
        - 状态清理
        - 分析事件记录
        """
        # 映射为结果块
        result_block = ResultFormatter.map_to_result_block(
            tool_call,
            execution_result,
            phase_timings
        )

        # 清理状态
        ResultFormatter.cleanup(tool_call)

        # 记录分析事件
        analytics_event = ResultFormatter.record_analytics(tool_call, result_block)
        self.analytics.append(analytics_event)

        return result_block

    def _create_result(
        self,
        tool_call: ToolCall,
        success: bool,
        output: str,
        start_time: float,
        phase_timings: Dict,
        result_block: ToolResultBlock = None
    ) -> ExecutionResult:
        """创建执行结果"""
        return ExecutionResult(
            tool_call_id=tool_call.id,
            tool_name=tool_call.name,
            success=success,
            output=output,
            duration_ms=int((time.time() - start_time) * 1000),
            phase_timings=phase_timings,
            needs_confirmation=tool_call.status == ToolStatus.NEEDS_CONFIRMATION,
            result_block=result_block
        )

    async def execute(self, tool_call: ToolCall) -> ExecutionResult:
        """
        执行完整的6阶段管道
        """
        start_time = time.time()
        phase_timings = {}
        execution_result = {"type": "complete", "result": ""}

        # ========== Phase 1: Discovery ==========
        phase_start = time.time()
        self._advance_phase(tool_call, ToolPhase.DISCOVERY)

        discovery_result = self._phase_discovery(tool_call)
        if not discovery_result.get("success"):
            return self._create_result(
                tool_call, False,
                discovery_result.get("error", "Tool discovery failed"),
                start_time, phase_timings
            )
        phase_timings["discovery"] = int((time.time() - phase_start) * 1000)

        # ========== Phase 2: Validation ==========
        phase_start = time.time()
        self._advance_phase(tool_call, ToolPhase.VALIDATION)

        validation_result = self._phase_validation(tool_call)
        if not validation_result.valid:
            error_msg = "; ".join(validation_result.errors)
            return self._create_result(
                tool_call, False,
                f"Validation failed: {error_msg}",
                start_time, phase_timings
            )
        phase_timings["validation"] = int((time.time() - phase_start) * 1000)

        # ========== Phase 3: Authorization ==========
        phase_start = time.time()
        self._advance_phase(tool_call, ToolPhase.AUTHORIZATION)

        auth_result = await self._phase_authorization(tool_call)
        if auth_result.requires_confirmation:
            tool_call.status = ToolStatus.NEEDS_CONFIRMATION
            return self._create_result(
                tool_call, False,
                f"NEEDS_CONFIRMATION: {auth_result.confirmation_message}",
                start_time, phase_timings
            )
        if not auth_result.allowed:
            tool_call.status = ToolStatus.DENIED
            return self._create_result(
                tool_call, False,
                f"Permission denied: {auth_result.reason}",
                start_time, phase_timings
            )
        phase_timings["authorization"] = int((time.time() - phase_start) * 1000)

        # ========== Phase 4: Cancellation ==========
        phase_start = time.time()
        self._advance_phase(tool_call, ToolPhase.CANCELLATION)

        if not self._phase_cancellation(tool_call):
            return self._create_result(
                tool_call, False,
                "Operation cancelled",
                start_time, phase_timings
            )
        phase_timings["cancellation"] = int((time.time() - phase_start) * 1000)

        # ========== Phase 5: Execution ==========
        phase_start = time.time()
        self._advance_phase(tool_call, ToolPhase.EXECUTION)

        try:
            # 使用超时控制
            async def run_execution():
                nonlocal execution_result
                final_result = ""
                async for event in self._phase_execution(tool_call):
                    if event.get("type") == "complete":
                        final_result = event.get("result", "")
                    elif event.get("type") == "error":
                        execution_result = {"type": "error", "result": event.get("error", "Unknown error")}
                        return
                execution_result = {"type": "complete", "result": final_result}

            await self.cancellation.with_timeout(tool_call, run_execution())

        except ToolTimeoutError as e:
            execution_result = {"type": "timeout", "result": str(e)}
            tool_call.status = ToolStatus.TIMEOUT
        except ToolCancelledError as e:
            execution_result = {"type": "cancelled", "result": str(e)}
            tool_call.status = ToolStatus.CANCELLED
        except Exception as e:
            execution_result = {"type": "error", "result": str(e)}
            tool_call.status = ToolStatus.FAILED

        phase_timings["execution"] = int((time.time() - phase_start) * 1000)

        # ========== Phase 6: PostProcessing ==========
        phase_start = time.time()
        self._advance_phase(tool_call, ToolPhase.POST_PROCESSING)

        result_block = self._phase_post_processing(tool_call, execution_result, phase_timings)
        phase_timings["post_processing"] = int((time.time() - phase_start) * 1000)

        # 更新最终状态
        if execution_result.get("type") == "complete":
            tool_call.status = ToolStatus.COMPLETED

        return self._create_result(
            tool_call,
            tool_call.status == ToolStatus.COMPLETED,
            execution_result.get("result", ""),
            start_time,
            phase_timings,
            result_block
        )

    async def execute_streaming(
        self,
        tool_call: ToolCall
    ) -> AsyncGenerator[Dict, None]:
        """
        流式执行工具（支持流式输出到 agent loop）
        """
        start_time = time.time()
        phase_timings = {}

        # Phase 1-4 (与 execute 相同)
        self._advance_phase(tool_call, ToolPhase.DISCOVERY)
        discovery_result = self._phase_discovery(tool_call)
        if not discovery_result.get("success"):
            yield {"type": "error", "error": discovery_result.get("error")}
            return

        self._advance_phase(tool_call, ToolPhase.VALIDATION)
        validation_result = self._phase_validation(tool_call)
        if not validation_result.valid:
            yield {"type": "error", "error": f"Validation: {'; '.join(validation_result.errors)}"}
            return

        self._advance_phase(tool_call, ToolPhase.AUTHORIZATION)
        auth_result = await self._phase_authorization(tool_call)
        if auth_result.requires_confirmation:
            yield {"type": "needs_confirmation", "message": auth_result.confirmation_message}
            return
        if not auth_result.allowed:
            yield {"type": "error", "error": f"Permission denied: {auth_result.reason}"}
            return

        self._advance_phase(tool_call, ToolPhase.CANCELLATION)
        if not self._phase_cancellation(tool_call):
            yield {"type": "cancelled"}
            return

        # Phase 5: 流式执行
        self._advance_phase(tool_call, ToolPhase.EXECUTION)
        async for event in self._phase_execution(tool_call):
            yield event

        # Phase 6
        self._advance_phase(tool_call, ToolPhase.POST_PROCESSING)
        yield {"type": "phase_complete", "phase": "post_processing"}

    async def execute_batch(self, tool_calls: List[ToolCall]) -> List[ExecutionResult]:
        """批量执行（并行）"""
        return await self.concurrency.submit_batch(
            tool_calls,
            self.execute
        )

    def approve_tool(self, tool_call: ToolCall):
        """批准工具调用"""
        self.permission_gate.approve(tool_call)

    def deny_tool(self, tool_call: ToolCall):
        """拒绝工具调用"""
        self.permission_gate.deny(tool_call)

    def cancel_tool(self, tool_call_id: str, reason: str = None):
        """取消工具调用"""
        self.cancellation.cancel_task(tool_call_id, reason)

    def get_stats(self) -> Dict:
        """获取管道统计"""
        return {
            "concurrency": self.concurrency.get_stats(),
            "tools_available": self.registry.get_all_tools(),
            "analytics_count": len(self.analytics)
        }


# ============================================================================
# 工具引擎 (高层接口)
# ============================================================================

class ToolEngine:
    """
    工具引擎
    整合工具执行管道和权限门控
    输出结果到 agent loop
    """

    def __init__(
        self,
        tools: Dict[str, Callable],
        max_concurrent: int = 10,
        auto_approve_safe: bool = True,
        default_timeout_ms: int = 120000
    ):
        self.tools = tools
        self.pipeline = ToolExecutionPipeline(
            tools=tools,
            permission_gate=PermissionGate(auto_approve_safe=auto_approve_safe),
            max_concurrent=max_concurrent,
            default_timeout_ms=default_timeout_ms
        )
        self.execution_history: List[ExecutionResult] = []

    async def execute(self, tool_call: ToolCall) -> ExecutionResult:
        """执行工具调用"""
        result = await self.pipeline.execute(tool_call)
        self.execution_history.append(result)
        return result

    async def execute_streaming(
        self,
        tool_call: ToolCall
    ) -> AsyncGenerator[Dict, None]:
        """流式执行（输出到 agent loop）"""
        async for event in self.pipeline.execute_streaming(tool_call):
            yield event

    async def execute_batch(self, tool_calls: List[ToolCall]) -> List[ExecutionResult]:
        """批量执行"""
        results = await self.pipeline.execute_batch(tool_calls)
        self.execution_history.extend([r for r in results if isinstance(r, ExecutionResult)])
        return results

    def approve_tool(self, tool_call: ToolCall):
        """批准工具调用"""
        self.pipeline.approve_tool(tool_call)

    def deny_tool(self, tool_call: ToolCall):
        """拒绝工具调用"""
        self.pipeline.deny_tool(tool_call)

    def cancel_tool(self, tool_call_id: str, reason: str = None):
        """取消工具调用"""
        self.pipeline.cancel_tool(tool_call_id, reason)

    def get_stats(self) -> Dict:
        """获取引擎统计"""
        return {
            "pipeline": self.pipeline.get_stats(),
            "executions": len(self.execution_history),
            "success_rate": (
                sum(1 for r in self.execution_history if r.success) / len(self.execution_history)
                if self.execution_history else 0
            )
        }
