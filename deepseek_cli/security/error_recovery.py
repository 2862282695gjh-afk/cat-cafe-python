"""
第五层：错误恢复层 (Error Recovery Layer)
- 异常捕获
- 错误分类
- 详细日志
- 自动重试降级处理
"""
import os
import re
import json
import time
import asyncio
import traceback
import logging
from typing import Any, Dict, List, Optional, Callable, Type, Union, TypeVar
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from abc import ABC, abstractmethod
from functools import wraps


T = TypeVar('T')


class ErrorCategory(Enum):
    """错误类别"""
    # 网络错误
    NETWORK_ERROR = "network_error"
    TIMEOUT_ERROR = "timeout_error"
    CONNECTION_ERROR = "connection_error"

    # API 错误
    API_ERROR = "api_error"
    RATE_LIMIT_ERROR = "rate_limit_error"
    AUTHENTICATION_ERROR = "authentication_error"
    AUTHORIZATION_ERROR = "authorization_error"

    # 资源错误
    RESOURCE_ERROR = "resource_error"
    MEMORY_ERROR = "memory_error"
    DISK_ERROR = "disk_error"

    # 执行错误
    EXECUTION_ERROR = "execution_error"
    VALIDATION_ERROR = "validation_error"
    PERMISSION_ERROR = "permission_error"
    CANCELLED_ERROR = "cancelled_error"

    # 工具错误
    TOOL_ERROR = "tool_error"
    TOOL_NOT_FOUND = "tool_not_found"
    TOOL_TIMEOUT = "tool_timeout"

    # 系统错误
    SYSTEM_ERROR = "system_error"
    INTERNAL_ERROR = "internal_error"
    UNKNOWN_ERROR = "unknown_error"


class ErrorSeverity(Enum):
    """错误严重程度"""
    LOW = "low"           # 低严重性，可忽略
    MEDIUM = "medium"     # 中等严重性，需要处理
    HIGH = "high"         # 高严重性，需要立即处理
    CRITICAL = "critical" # 严重错误，需要人工介入
    FATAL = "fatal"       # 致命错误，无法恢复


class RecoveryStrategy(Enum):
    """恢复策略"""
    IGNORE = "ignore"           # 忽略错误
    RETRY = "retry"             # 重试
    RETRY_BACKOFF = "retry_backoff"  # 指数退避重试
    FALLBACK = "fallback"       # 降级处理
    ABORT = "abort"             # 中止执行
    ESCALATE = "escalate"       # 上报错误
    MANUAL = "manual"           # 需要人工处理


@dataclass
class ErrorContext:
    """错误上下文"""
    error: Exception
    category: ErrorCategory
    severity: ErrorSeverity
    message: str
    timestamp: int = field(default_factory=lambda: int(time.time() * 1000))
    tool_name: Optional[str] = None
    execution_id: Optional[str] = None
    attempt: int = 1
    max_attempts: int = 3
    stack_trace: str = ""
    additional_info: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "error_type": type(self.error).__name__,
            "category": self.category.value,
            "severity": self.severity.value,
            "message": self.message,
            "timestamp": self.timestamp,
            "tool_name": self.tool_name,
            "execution_id": self.execution_id,
            "attempt": self.attempt,
            "max_attempts": self.max_attempts,
            "stack_trace": self.stack_trace,
            "additional_info": self.additional_info,
        }


@dataclass
class RecoveryResult:
    """恢复结果"""
    success: bool
    strategy: RecoveryStrategy
    message: str
    retry_after_ms: Optional[int] = None
    fallback_value: Any = None
    should_abort: bool = False
    needs_manual_intervention: bool = False


# ============================================================================
# 错误分类器
# ============================================================================

class ErrorClassifier:
    """错误分类器"""

    # 错误类型到类别的映射
    TYPE_CATEGORY_MAP = {
        # 网络
        "ConnectionError": ErrorCategory.CONNECTION_ERROR,
        "ConnectionRefusedError": ErrorCategory.CONNECTION_ERROR,
        "ConnectionResetError": ErrorCategory.CONNECTION_ERROR,
        "TimeoutError": ErrorCategory.TIMEOUT_ERROR,
        "asyncio.TimeoutError": ErrorCategory.TIMEOUT_ERROR,

        # 资源
        "MemoryError": ErrorCategory.MEMORY_ERROR,
        "OSError": ErrorCategory.SYSTEM_ERROR,
        "IOError": ErrorCategory.DISK_ERROR,
        "PermissionError": ErrorCategory.PERMISSION_ERROR,
        "FileNotFoundError": ErrorCategory.TOOL_ERROR,

        # 验证
        "ValueError": ErrorCategory.VALIDATION_ERROR,
        "TypeError": ErrorCategory.VALIDATION_ERROR,
        "KeyError": ErrorCategory.VALIDATION_ERROR,

        # 取消
        "CancelledError": ErrorCategory.CANCELLED_ERROR,
        "asyncio.CancelledError": ErrorCategory.CANCELLED_ERROR,
    }

    # 错误消息模式到类别的映射
    MESSAGE_PATTERNS = [
        (r"rate.?limit", ErrorCategory.RATE_LIMIT_ERROR),
        (r"429", ErrorCategory.RATE_LIMIT_ERROR),
        (r"too many requests", ErrorCategory.RATE_LIMIT_ERROR),
        (r"unauthorized|401", ErrorCategory.AUTHENTICATION_ERROR),
        (r"forbidden|403", ErrorCategory.AUTHORIZATION_ERROR),
        (r"not found|404", ErrorCategory.TOOL_NOT_FOUND),
        (r"internal server error|500", ErrorCategory.API_ERROR),
        (r"service unavailable|503", ErrorCategory.API_ERROR),
        (r"gateway timeout|504", ErrorCategory.TIMEOUT_ERROR),
        (r"timeout|timed out", ErrorCategory.TIMEOUT_ERROR),
        (r"connection refused|connection reset", ErrorCategory.CONNECTION_ERROR),
        (r"network", ErrorCategory.NETWORK_ERROR),
        (r"memory|out of memory", ErrorCategory.MEMORY_ERROR),
        (r"disk|no space", ErrorCategory.DISK_ERROR),
        (r"permission denied|access denied", ErrorCategory.PERMISSION_ERROR),
    ]

    @classmethod
    def classify(cls, error: Exception) -> ErrorCategory:
        """分类错误"""
        # 1. 按类型分类
        error_type = type(error).__name__
        if error_type in cls.TYPE_CATEGORY_MAP:
            return cls.TYPE_CATEGORY_MAP[error_type]

        # 2. 按模块名分类
        module = type(error).__module__
        full_type = f"{module}.{error_type}"
        if full_type in cls.TYPE_CATEGORY_MAP:
            return cls.TYPE_CATEGORY_MAP[full_type]

        # 3. 按消息模式分类
        error_message = str(error).lower()
        for pattern, category in cls.MESSAGE_PATTERNS:
            if re.search(pattern, error_message, re.IGNORECASE):
                return category

        # 4. 默认为未知错误
        return ErrorCategory.UNKNOWN_ERROR

    @classmethod
    def get_severity(cls, category: ErrorCategory) -> ErrorSeverity:
        """获取错误严重程度"""
        severity_map = {
            ErrorCategory.NETWORK_ERROR: ErrorSeverity.MEDIUM,
            ErrorCategory.TIMEOUT_ERROR: ErrorSeverity.MEDIUM,
            ErrorCategory.CONNECTION_ERROR: ErrorSeverity.MEDIUM,
            ErrorCategory.API_ERROR: ErrorSeverity.HIGH,
            ErrorCategory.RATE_LIMIT_ERROR: ErrorSeverity.LOW,
            ErrorCategory.AUTHENTICATION_ERROR: ErrorSeverity.CRITICAL,
            ErrorCategory.AUTHORIZATION_ERROR: ErrorSeverity.HIGH,
            ErrorCategory.RESOURCE_ERROR: ErrorSeverity.HIGH,
            ErrorCategory.MEMORY_ERROR: ErrorSeverity.CRITICAL,
            ErrorCategory.DISK_ERROR: ErrorSeverity.HIGH,
            ErrorCategory.EXECUTION_ERROR: ErrorSeverity.MEDIUM,
            ErrorCategory.VALIDATION_ERROR: ErrorSeverity.LOW,
            ErrorCategory.PERMISSION_ERROR: ErrorSeverity.HIGH,
            ErrorCategory.CANCELLED_ERROR: ErrorSeverity.LOW,
            ErrorCategory.TOOL_ERROR: ErrorSeverity.MEDIUM,
            ErrorCategory.TOOL_NOT_FOUND: ErrorSeverity.MEDIUM,
            ErrorCategory.TOOL_TIMEOUT: ErrorSeverity.MEDIUM,
            ErrorCategory.SYSTEM_ERROR: ErrorSeverity.CRITICAL,
            ErrorCategory.INTERNAL_ERROR: ErrorSeverity.HIGH,
            ErrorCategory.UNKNOWN_ERROR: ErrorSeverity.MEDIUM,
        }
        return severity_map.get(category, ErrorSeverity.MEDIUM)


# ============================================================================
# 恢复策略选择器
# ============================================================================

class RecoveryStrategySelector:
    """恢复策略选择器"""

    # 类别到策略的默认映射
    CATEGORY_STRATEGY_MAP = {
        ErrorCategory.NETWORK_ERROR: RecoveryStrategy.RETRY_BACKOFF,
        ErrorCategory.TIMEOUT_ERROR: RecoveryStrategy.RETRY,
        ErrorCategory.CONNECTION_ERROR: RecoveryStrategy.RETRY_BACKOFF,
        ErrorCategory.API_ERROR: RecoveryStrategy.RETRY,
        ErrorCategory.RATE_LIMIT_ERROR: RecoveryStrategy.RETRY_BACKOFF,
        ErrorCategory.AUTHENTICATION_ERROR: RecoveryStrategy.ABORT,
        ErrorCategory.AUTHORIZATION_ERROR: RecoveryStrategy.ABORT,
        ErrorCategory.RESOURCE_ERROR: RecoveryStrategy.ESCALATE,
        ErrorCategory.MEMORY_ERROR: RecoveryStrategy.ABORT,
        ErrorCategory.DISK_ERROR: RecoveryStrategy.ESCALATE,
        ErrorCategory.EXECUTION_ERROR: RecoveryStrategy.RETRY,
        ErrorCategory.VALIDATION_ERROR: RecoveryStrategy.ABORT,
        ErrorCategory.PERMISSION_ERROR: RecoveryStrategy.ABORT,
        ErrorCategory.CANCELLED_ERROR: RecoveryStrategy.ABORT,
        ErrorCategory.TOOL_ERROR: RecoveryStrategy.FALLBACK,
        ErrorCategory.TOOL_NOT_FOUND: RecoveryStrategy.ABORT,
        ErrorCategory.TOOL_TIMEOUT: RecoveryStrategy.RETRY,
        ErrorCategory.SYSTEM_ERROR: RecoveryStrategy.ESCALATE,
        ErrorCategory.INTERNAL_ERROR: RecoveryStrategy.ESCALATE,
        ErrorCategory.UNKNOWN_ERROR: RecoveryStrategy.RETRY,
    }

    @classmethod
    def select(
        cls,
        category: ErrorCategory,
        severity: ErrorSeverity,
        attempt: int,
        max_attempts: int
    ) -> RecoveryStrategy:
        """选择恢复策略"""
        # 基础策略
        base_strategy = cls.CATEGORY_STRATEGY_MAP.get(category, RecoveryStrategy.RETRY)

        # 根据严重程度调整
        if severity == ErrorSeverity.FATAL:
            return RecoveryStrategy.ABORT

        if severity == ErrorSeverity.CRITICAL:
            return RecoveryStrategy.ESCALATE

        # 根据重试次数调整
        if attempt >= max_attempts:
            if base_strategy in [RecoveryStrategy.RETRY, RecoveryStrategy.RETRY_BACKOFF]:
                return RecoveryStrategy.FALLBACK

        return base_strategy


# ============================================================================
# 重试机制
# ============================================================================

@dataclass
class RetryConfig:
    """重试配置"""
    max_attempts: int = 3
    base_delay_ms: int = 1000
    max_delay_ms: int = 30000
    exponential_base: float = 2.0
    jitter: bool = True
    retryable_categories: List[ErrorCategory] = field(default_factory=lambda: [
        ErrorCategory.NETWORK_ERROR,
        ErrorCategory.TIMEOUT_ERROR,
        ErrorCategory.CONNECTION_ERROR,
        ErrorCategory.RATE_LIMIT_ERROR,
        ErrorCategory.API_ERROR,
    ])


class RetryExecutor:
    """重试执行器"""

    def __init__(self, config: RetryConfig = None):
        self.config = config or RetryConfig()

    def calculate_delay(self, attempt: int) -> int:
        """计算延迟时间（指数退避）"""
        delay = self.config.base_delay_ms * (
            self.config.exponential_base ** (attempt - 1)
        )

        # 添加抖动
        if self.config.jitter:
            import random
            delay = delay * (0.5 + random.random())

        return min(int(delay), self.config.max_delay_ms)

    def should_retry(self, category: ErrorCategory, attempt: int) -> bool:
        """判断是否应该重试"""
        if attempt >= self.config.max_attempts:
            return False
        return category in self.config.retryable_categories

    async def execute_with_retry(
        self,
        func: Callable[..., Any],
        *args,
        on_retry: Callable[[int, ErrorContext], None] = None,
        **kwargs
    ) -> T:
        """带重试的执行"""
        attempt = 0
        last_error = None

        while attempt < self.config.max_attempts:
            attempt += 1

            try:
                result = func(*args, **kwargs)
                if asyncio.iscoroutine(result):
                    result = await result
                return result

            except Exception as e:
                last_error = e
                category = ErrorClassifier.classify(e)

                if not self.should_retry(category, attempt):
                    raise

                # 计算延迟
                delay_ms = self.calculate_delay(attempt)

                # 创建错误上下文
                ctx = ErrorContext(
                    error=e,
                    category=category,
                    severity=ErrorClassifier.get_severity(category),
                    message=str(e),
                    attempt=attempt,
                    max_attempts=self.config.max_attempts,
                    stack_trace=traceback.format_exc()
                )

                # 回调
                if on_retry:
                    on_retry(attempt, ctx)

                # 等待重试
                await asyncio.sleep(delay_ms / 1000)

        raise last_error


# ============================================================================
# 降级处理器
# ============================================================================

class FallbackHandler(ABC):
    """降级处理器基类"""

    @abstractmethod
    async def handle(self, error: ErrorContext) -> Any:
        """处理降级"""
        pass


class DefaultFallbackHandler(FallbackHandler):
    """默认降级处理器"""

    def __init__(self, fallback_value: Any = None):
        self.fallback_value = fallback_value

    async def handle(self, error: ErrorContext) -> Any:
        return self.fallback_value


class ToolFallbackHandler(FallbackHandler):
    """工具降级处理器"""

    # 工具降级映射
    TOOL_FALLBACKS = {
        "Bash": "回退到内置命令",
        "WebFetch": "返回缓存或空结果",
        "WebSearch": "返回本地索引或空结果",
    }

    async def handle(self, error: ErrorContext) -> Any:
        tool_name = error.tool_name
        if tool_name in self.TOOL_FALLBACKS:
            return {
                "fallback": True,
                "tool": tool_name,
                "message": self.TOOL_FALLBACKS[tool_name],
                "original_error": error.message
            }
        return None


# ============================================================================
# 详细日志
# ============================================================================

class ErrorLogger:
    """错误日志记录器"""

    def __init__(
        self,
        log_dir: str = None,
        max_log_size_mb: int = 10,
        max_log_files: int = 10
    ):
        self.log_dir = log_dir or os.path.join(os.getcwd(), ".deepseek", "logs")
        self.max_log_size_mb = max_log_size_mb
        self.max_log_files = max_log_files

        # 确保日志目录存在
        os.makedirs(self.log_dir, exist_ok=True)

        # 配置日志
        self._setup_logging()

    def _setup_logging(self):
        """配置日志"""
        self.logger = logging.getLogger("error_recovery")
        self.logger.setLevel(logging.DEBUG)

        # 文件处理器
        log_file = os.path.join(self.log_dir, "errors.log")
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)

        # 格式化
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)

        self.logger.addHandler(file_handler)

    def log_error(self, ctx: ErrorContext):
        """记录错误"""
        log_data = ctx.to_dict()

        # 根据严重程度选择日志级别
        if ctx.severity in [ErrorSeverity.FATAL, ErrorSeverity.CRITICAL]:
            self.logger.critical(json.dumps(log_data, ensure_ascii=False))
        elif ctx.severity == ErrorSeverity.HIGH:
            self.logger.error(json.dumps(log_data, ensure_ascii=False))
        elif ctx.severity == ErrorSeverity.MEDIUM:
            self.logger.warning(json.dumps(log_data, ensure_ascii=False))
        else:
            self.logger.info(json.dumps(log_data, ensure_ascii=False))

    def log_recovery(self, ctx: ErrorContext, result: RecoveryResult):
        """记录恢复结果"""
        log_data = {
            "type": "recovery",
            "error_context": ctx.to_dict(),
            "recovery_result": {
                "success": result.success,
                "strategy": result.strategy.value,
                "message": result.message,
            }
        }
        self.logger.info(json.dumps(log_data, ensure_ascii=False))


# ============================================================================
# 错误恢复层
# ============================================================================

class ErrorRecoveryLayer:
    """
    第五层：错误恢复层

    功能：
    - 异常捕获
    - 错误分类
    - 详细日志
    - 自动重试降级处理
    """

    def __init__(
        self,
        retry_config: RetryConfig = None,
        enable_logging: bool = True,
        log_dir: str = None,
        fallback_handlers: Dict[str, FallbackHandler] = None
    ):
        self.retry_config = retry_config or RetryConfig()
        self.retry_executor = RetryExecutor(self.retry_config)

        # 日志
        self.logger = ErrorLogger(log_dir) if enable_logging else None

        # 降级处理器
        self.fallback_handlers = fallback_handlers or {}
        self.default_fallback = DefaultFallbackHandler()

        # 错误历史
        self._error_history: List[ErrorContext] = []
        self._max_history = 1000

    async def execute_with_recovery(
        self,
        func: Callable[..., Any],
        *args,
        tool_name: str = None,
        execution_id: str = None,
        fallback_value: Any = None,
        **kwargs
    ) -> T:
        """
        带恢复机制的执行

        Args:
            func: 要执行的函数
            tool_name: 工具名称
            execution_id: 执行 ID
            fallback_value: 降级值
        """
        attempt = 0

        while True:
            attempt += 1

            try:
                result = func(*args, **kwargs)
                if asyncio.iscoroutine(result):
                    result = await result
                return result

            except Exception as e:
                # 分类错误
                category = ErrorClassifier.classify(e)
                severity = ErrorClassifier.get_severity(category)

                # 创建错误上下文
                ctx = ErrorContext(
                    error=e,
                    category=category,
                    severity=severity,
                    message=str(e),
                    tool_name=tool_name,
                    execution_id=execution_id,
                    attempt=attempt,
                    max_attempts=self.retry_config.max_attempts,
                    stack_trace=traceback.format_exc()
                )

                # 记录错误
                self._record_error(ctx)

                # 选择恢复策略
                strategy = RecoveryStrategySelector.select(
                    category, severity, attempt, self.retry_config.max_attempts
                )

                # 执行恢复
                result = await self._execute_recovery(ctx, strategy, fallback_value)

                if result.should_abort:
                    raise e

                if result.success:
                    return result.fallback_value

                # 继续重试
                if result.retry_after_ms:
                    await asyncio.sleep(result.retry_after_ms / 1000)

    async def _execute_recovery(
        self,
        ctx: ErrorContext,
        strategy: RecoveryStrategy,
        fallback_value: Any = None
    ) -> RecoveryResult:
        """执行恢复策略"""

        if strategy == RecoveryStrategy.IGNORE:
            return RecoveryResult(
                success=True,
                strategy=strategy,
                message="Error ignored"
            )

        elif strategy == RecoveryStrategy.RETRY:
            if ctx.attempt < ctx.max_attempts:
                delay = self.retry_executor.calculate_delay(ctx.attempt)
                return RecoveryResult(
                    success=False,
                    strategy=strategy,
                    message=f"Will retry (attempt {ctx.attempt + 1}/{ctx.max_attempts})",
                    retry_after_ms=delay
                )
            # 达到最大重试次数，降级
            return await self._do_fallback(ctx, fallback_value)

        elif strategy == RecoveryStrategy.RETRY_BACKOFF:
            if ctx.attempt < ctx.max_attempts:
                delay = self.retry_executor.calculate_delay(ctx.attempt)
                return RecoveryResult(
                    success=False,
                    strategy=strategy,
                    message=f"Will retry with backoff after {delay}ms",
                    retry_after_ms=delay
                )
            return await self._do_fallback(ctx, fallback_value)

        elif strategy == RecoveryStrategy.FALLBACK:
            return await self._do_fallback(ctx, fallback_value)

        elif strategy == RecoveryStrategy.ABORT:
            self._log_recovery(ctx, RecoveryResult(
                success=False,
                strategy=strategy,
                message="Execution aborted",
                should_abort=True
            ))
            return RecoveryResult(
                success=False,
                strategy=strategy,
                message="Execution aborted due to non-recoverable error",
                should_abort=True
            )

        elif strategy == RecoveryStrategy.ESCALATE:
            return RecoveryResult(
                success=False,
                strategy=strategy,
                message="Error escalated for manual intervention",
                should_abort=True,
                needs_manual_intervention=True
            )

        # 默认：降级处理
        return await self._do_fallback(ctx, fallback_value)

    async def _do_fallback(
        self,
        ctx: ErrorContext,
        fallback_value: Any = None
    ) -> RecoveryResult:
        """执行降级"""
        # 查找特定的降级处理器
        handler = self.fallback_handlers.get(ctx.tool_name)

        if not handler:
            handler = self.default_fallback
            if fallback_value is not None:
                handler = DefaultFallbackHandler(fallback_value)

        try:
            result = await handler.handle(ctx)
            return RecoveryResult(
                success=True,
                strategy=RecoveryStrategy.FALLBACK,
                message="Fallback executed successfully",
                fallback_value=result
            )
        except Exception as e:
            return RecoveryResult(
                success=False,
                strategy=RecoveryStrategy.FALLBACK,
                message=f"Fallback failed: {e}",
                should_abort=True
            )

    def _record_error(self, ctx: ErrorContext):
        """记录错误"""
        self._error_history.append(ctx)

        # 限制历史大小
        if len(self._error_history) > self._max_history:
            self._error_history = self._error_history[-self._max_history:]

        # 写入日志
        if self.logger:
            self.logger.log_error(ctx)

    def _log_recovery(self, ctx: ErrorContext, result: RecoveryResult):
        """记录恢复结果"""
        if self.logger:
            self.logger.log_recovery(ctx, result)

    def register_fallback_handler(self, tool_name: str, handler: FallbackHandler):
        """注册降级处理器"""
        self.fallback_handlers[tool_name] = handler

    def get_error_history(self, limit: int = 100) -> List[ErrorContext]:
        """获取错误历史"""
        return self._error_history[-limit:]

    def get_error_stats(self) -> Dict[str, Any]:
        """获取错误统计"""
        stats = {
            "total_errors": len(self._error_history),
            "by_category": {},
            "by_severity": {},
        }

        for ctx in self._error_history:
            category = ctx.category.value
            severity = ctx.severity.value

            stats["by_category"][category] = stats["by_category"].get(category, 0) + 1
            stats["by_severity"][severity] = stats["by_severity"].get(severity, 0) + 1

        return stats

    def clear_history(self):
        """清除历史"""
        self._error_history.clear()


# ============================================================================
# 装饰器
# ============================================================================

def with_error_recovery(
    layer: ErrorRecoveryLayer = None,
    tool_name: str = None,
    fallback_value: Any = None
):
    """
    错误恢复装饰器

    用法:
        @with_error_recovery(tool_name="Bash")
        async def execute_command(cmd):
            ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            nonlocal layer
            if layer is None:
                layer = ErrorRecoveryLayer()

            return await layer.execute_with_recovery(
                func,
                *args,
                tool_name=tool_name,
                fallback_value=fallback_value,
                **kwargs
            )
        return wrapper
    return decorator
