"""
第四层：执行监控层 (Execution Monitoring Layer)
- AbortController 中断信号
- 超时控制防止卡死
- 资源限制内存/CPU
"""
import os
import re
import json
import asyncio
import time
import threading
import signal
import sys
from typing import Any, Dict, List, Optional, Callable, Set, Union, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from contextlib import asynccontextmanager
from collections import defaultdict


class ExecutionState(Enum):
    """执行状态"""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    RESOURCE_EXCEEDED = "resource_exceeded"


class MonitorEventType(Enum):
    """监控事件类型"""
    START = "start"
    PROGRESS = "progress"
    HEARTBEAT = "heartbeat"
    RESOURCE_CHECK = "resource_check"
    TIMEOUT_WARNING = "timeout_warning"
    CANCEL_REQUEST = "cancel_request"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass
class AbortSignal:
    """
    AbortController 信号
    类似 JavaScript 的 AbortController API
    """
    aborted: bool = False
    reason: Optional[str] = None
    _listeners: List[Callable] = field(default_factory=list)

    def abort(self, reason: str = None):
        """触发中止"""
        self.aborted = True
        self.reason = reason
        # 通知所有监听器
        for listener in self._listeners:
            try:
                listener(reason)
            except Exception:
                pass

    def throw_if_aborted(self):
        """如果已中止则抛出异常"""
        if self.aborted:
            raise ExecutionCancelledError(self.reason or "Execution aborted")

    def add_listener(self, callback: Callable):
        """添加中止监听器"""
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable):
        """移除中止监听器"""
        if callback in self._listeners:
            self._listeners.remove(callback)


class AbortController:
    """
    AbortController 控制器
    用于创建和管理 AbortSignal
    """

    def __init__(self):
        self.signal = AbortSignal()

    def abort(self, reason: str = None):
        """中止关联的操作"""
        self.signal.abort(reason)

    @staticmethod
    def any(*signals: AbortSignal) -> AbortSignal:
        """创建一个在任意信号中止时中止的新信号"""
        combined = AbortSignal()

        def on_abort(reason):
            if not combined.aborted:
                combined.abort(reason)

        for sig in signals:
            sig.add_listener(on_abort)

        return combined

    @staticmethod
    def timeout(ms: int) -> AbortSignal:
        """创建一个超时自动中止的信号"""
        signal = AbortSignal()

        def timeout_handler():
            if not signal.aborted:
                signal.abort(f"Timeout after {ms}ms")

        timer = threading.Timer(ms / 1000, timeout_handler)
        timer.start()

        # 确保在中止时取消定时器
        original_abort = signal.abort

        def abort_with_cleanup(reason=None):
            timer.cancel()
            original_abort(reason)

        signal.abort = abort_with_cleanup

        return signal


class ExecutionCancelledError(Exception):
    """执行取消错误"""
    pass


class ExecutionTimeoutError(Exception):
    """执行超时错误"""
    pass


class ResourceExceededError(Exception):
    """资源超限错误"""
    pass


# ============================================================================
# 资源监控器
# ============================================================================

@dataclass
class ResourceUsage:
    """资源使用情况"""
    memory_mb: float = 0
    cpu_percent: float = 0
    disk_read_mb: float = 0
    disk_write_mb: float = 0
    network_in_mb: float = 0
    network_out_mb: float = 0
    open_files: int = 0
    threads: int = 0
    timestamp: int = field(default_factory=lambda: int(time.time() * 1000))


@dataclass
class ResourceThresholds:
    """资源阈值"""
    max_memory_mb: int = 512
    max_cpu_percent: int = 80
    max_disk_read_mb: int = 1000
    max_disk_write_mb: int = 1000
    max_network_in_mb: int = 100
    max_network_out_mb: int = 100
    max_open_files: int = 200
    max_threads: int = 50


class ResourceMonitor:
    """资源监控器"""

    def __init__(self, thresholds: ResourceThresholds = None):
        self.thresholds = thresholds or ResourceThresholds()
        self._start_usage: Optional[ResourceUsage] = None
        self._current_usage: Optional[ResourceUsage] = None
        self._monitoring = False
        self._monitor_task: Optional[asyncio.Task] = None

    def start(self):
        """开始监控"""
        self._start_usage = self._get_current_usage()
        self._current_usage = self._start_usage
        self._monitoring = True

    def stop(self):
        """停止监控"""
        self._monitoring = False
        if self._monitor_task:
            self._monitor_task.cancel()

    async def monitor_continuously(self, interval_ms: int = 1000):
        """持续监控资源使用"""
        while self._monitoring:
            self._current_usage = self._get_current_usage()
            self._check_thresholds()
            await asyncio.sleep(interval_ms / 1000)

    def _get_current_usage(self) -> ResourceUsage:
        """获取当前资源使用"""
        usage = ResourceUsage()

        try:
            import psutil
            process = psutil.Process()

            # 内存使用
            mem_info = process.memory_info()
            usage.memory_mb = mem_info.rss / (1024 * 1024)

            # CPU 使用率
            usage.cpu_percent = process.cpu_percent(interval=0.1)

            # 磁盘 I/O
            try:
                io_counters = process.io_counters()
                usage.disk_read_mb = io_counters.read_bytes / (1024 * 1024)
                usage.disk_write_mb = io_counters.write_bytes / (1024 * 1024)
            except (AttributeError, psutil.AccessDenied):
                pass

            # 打开文件数
            try:
                usage.open_files = len(process.open_files())
            except psutil.AccessDenied:
                pass

            # 线程数
            usage.threads = process.num_threads()

        except ImportError:
            # psutil 不可用，使用基本方法
            pass

        return usage

    def _check_thresholds(self) -> List[str]:
        """检查是否超过阈值"""
        violations = []

        if self._current_usage.memory_mb > self.thresholds.max_memory_mb:
            violations.append(
                f"Memory {self._current_usage.memory_mb:.1f}MB exceeds "
                f"limit {self.thresholds.max_memory_mb}MB"
            )

        if self._current_usage.cpu_percent > self.thresholds.max_cpu_percent:
            violations.append(
                f"CPU {self._current_usage.cpu_percent:.1f}% exceeds "
                f"limit {self.thresholds.max_cpu_percent}%"
            )

        if self._current_usage.open_files > self.thresholds.max_open_files:
            violations.append(
                f"Open files {self._current_usage.open_files} exceeds "
                f"limit {self.thresholds.max_open_files}"
            )

        return violations

    def get_usage(self) -> ResourceUsage:
        """获取当前使用情况"""
        if not self._current_usage:
            self._current_usage = self._get_current_usage()
        return self._current_usage

    def get_usage_delta(self) -> ResourceUsage:
        """获取使用增量"""
        current = self._get_current_usage()
        if not self._start_usage:
            return current

        return ResourceUsage(
            memory_mb=current.memory_mb - self._start_usage.memory_mb,
            cpu_percent=current.cpu_percent,
            disk_read_mb=current.disk_read_mb - self._start_usage.disk_read_mb,
            disk_write_mb=current.disk_write_mb - self._start_usage.disk_write_mb,
            network_in_mb=current.network_in_mb - self._start_usage.network_in_mb,
            network_out_mb=current.network_out_mb - self._start_usage.network_out_mb,
            open_files=current.open_files,
            threads=current.threads,
        )


# ============================================================================
# 执行监控器
# ============================================================================

@dataclass
class ExecutionContext:
    """执行上下文"""
    execution_id: str
    tool_name: str
    arguments: Dict[str, Any]
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    state: ExecutionState = ExecutionState.IDLE
    progress: float = 0.0
    abort_signal: AbortSignal = field(default_factory=AbortSignal)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MonitorEvent:
    """监控事件"""
    event_type: MonitorEventType
    execution_id: str
    timestamp: int = field(default_factory=lambda: int(time.time() * 1000))
    data: Dict[str, Any] = field(default_factory=dict)


class ExecutionMonitor:
    """
    执行监控器

    功能：
    - 跟踪执行状态
    - 发送心跳
    - 资源使用监控
    - 进度更新
    """

    def __init__(
        self,
        heartbeat_interval_ms: int = 5000,
        on_event: Callable[[MonitorEvent], None] = None
    ):
        self.heartbeat_interval_ms = heartbeat_interval_ms
        self.on_event = on_event

        self._executions: Dict[str, ExecutionContext] = {}
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._running = False

    def start(self):
        """启动监控器"""
        self._running = True
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    def stop(self):
        """停止监控器"""
        self._running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()

    def register(self, ctx: ExecutionContext):
        """注册执行"""
        self._executions[ctx.execution_id] = ctx
        self._emit_event(MonitorEvent(
            event_type=MonitorEventType.START,
            execution_id=ctx.execution_id,
            data={"tool_name": ctx.tool_name}
        ))

    def unregister(self, execution_id: str):
        """注销执行"""
        if execution_id in self._executions:
            del self._executions[execution_id]

    def update_progress(self, execution_id: str, progress: float, data: Dict = None):
        """更新进度"""
        if execution_id in self._executions:
            ctx = self._executions[execution_id]
            ctx.progress = min(1.0, max(0.0, progress))
            ctx.state = ExecutionState.RUNNING

            self._emit_event(MonitorEvent(
                event_type=MonitorEventType.PROGRESS,
                execution_id=execution_id,
                data={"progress": ctx.progress, **(data or {})}
            ))

    def complete(self, execution_id: str, success: bool = True, data: Dict = None):
        """标记完成"""
        if execution_id in self._executions:
            ctx = self._executions[execution_id]
            ctx.end_time = time.time()
            ctx.state = ExecutionState.COMPLETED if success else ExecutionState.FAILED

            self._emit_event(MonitorEvent(
                event_type=MonitorEventType.COMPLETE,
                execution_id=execution_id,
                data={"success": success, "duration_ms": ctx.end_time - ctx.start_time, **(data or {})}
            ))

    def cancel(self, execution_id: str, reason: str = None):
        """取消执行"""
        if execution_id in self._executions:
            ctx = self._executions[execution_id]
            ctx.abort_signal.abort(reason)
            ctx.state = ExecutionState.CANCELLED
            ctx.end_time = time.time()

            self._emit_event(MonitorEvent(
                event_type=MonitorEventType.CANCEL_REQUEST,
                execution_id=execution_id,
                data={"reason": reason}
            ))

    def get_context(self, execution_id: str) -> Optional[ExecutionContext]:
        """获取执行上下文"""
        return self._executions.get(execution_id)

    def get_active_count(self) -> int:
        """获取活动执行数"""
        return sum(
            1 for ctx in self._executions.values()
            if ctx.state == ExecutionState.RUNNING
        )

    async def _heartbeat_loop(self):
        """心跳循环"""
        while self._running:
            for execution_id, ctx in self._executions.items():
                if ctx.state == ExecutionState.RUNNING:
                    self._emit_event(MonitorEvent(
                        event_type=MonitorEventType.HEARTBEAT,
                        execution_id=execution_id,
                        data={
                            "duration_ms": int((time.time() - ctx.start_time) * 1000),
                            "progress": ctx.progress
                        }
                    ))
            await asyncio.sleep(self.heartbeat_interval_ms / 1000)

    def _emit_event(self, event: MonitorEvent):
        """发送事件"""
        if self.on_event:
            try:
                self.on_event(event)
            except Exception:
                pass


# ============================================================================
# 超时控制器
# ============================================================================

class TimeoutController:
    """超时控制器"""

    def __init__(
        self,
        default_timeout_ms: int = 120000,
        warning_threshold: float = 0.8  # 80% 时发出警告
    ):
        self.default_timeout_ms = default_timeout_ms
        self.warning_threshold = warning_threshold

    @asynccontextmanager
    async def with_timeout(
        self,
        timeout_ms: int = None,
        abort_signal: AbortSignal = None,
        on_warning: Callable[[int, int], None] = None,
        on_timeout: Callable[[], None] = None
    ):
        """
        带超时控制的上下文管理器

        Args:
            timeout_ms: 超时时间（毫秒）
            abort_signal: 中止信号
            on_warning: 超时警告回调
            on_timeout: 超时回调
        """
        timeout_ms = timeout_ms or self.default_timeout_ms
        timeout_sec = timeout_ms / 1000
        start_time = time.time()

        # 创建超时信号
        timeout_signal = AbortController.timeout(timeout_ms)

        # 合并信号
        if abort_signal:
            combined_signal = AbortController.any(abort_signal, timeout_signal.signal)
        else:
            combined_signal = timeout_signal.signal

        # 警告检查任务
        warning_task = None
        if on_warning:
            warning_time = timeout_sec * self.warning_threshold

            async def check_warning():
                await asyncio.sleep(warning_time)
                if not combined_signal.aborted:
                    elapsed = int((time.time() - start_time) * 1000)
                    on_warning(elapsed, timeout_ms)

            warning_task = asyncio.create_task(check_warning())

        try:
            yield combined_signal
        except asyncio.TimeoutError:
            if on_timeout:
                on_timeout()
            raise ExecutionTimeoutError(f"Execution timed out after {timeout_ms}ms")
        finally:
            if warning_task:
                warning_task.cancel()
            # 清理超时定时器
            if not timeout_signal.signal.aborted:
                timeout_signal.signal.abort("cleanup")


# ============================================================================
# 执行监控层
# ============================================================================

class ExecutionMonitoringLayer:
    """
    第四层：执行监控层

    功能：
    - AbortController 中断信号
    - 超时控制防止卡死
    - 资源限制内存/CPU
    - 进度追踪
    """

    def __init__(
        self,
        default_timeout_ms: int = 120000,
        resource_thresholds: ResourceThresholds = None,
        heartbeat_interval_ms: int = 5000,
        on_monitor_event: Callable[[MonitorEvent], None] = None
    ):
        self.default_timeout_ms = default_timeout_ms

        # 初始化组件
        self.resource_monitor = ResourceMonitor(resource_thresholds)
        self.execution_monitor = ExecutionMonitor(
            heartbeat_interval_ms=heartbeat_interval_ms,
            on_event=on_monitor_event
        )
        self.timeout_controller = TimeoutController(default_timeout_ms)

        # 活跃的控制器
        self._active_controllers: Dict[str, AbortController] = {}
        self._lock = asyncio.Lock()

    async def start(self):
        """启动监控"""
        self.resource_monitor.start()
        self.execution_monitor.start()

        # 启动持续资源监控
        asyncio.create_task(self.resource_monitor.monitor_continuously())

    async def stop(self):
        """停止监控"""
        self.resource_monitor.stop()
        self.execution_monitor.stop()

        # 取消所有活跃执行
        for controller in self._active_controllers.values():
            controller.abort("Monitoring layer stopped")

    @asynccontextmanager
    async def monitored_execution(
        self,
        execution_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
        timeout_ms: int = None,
        on_progress: Callable[[float], None] = None,
        on_warning: Callable[[int, int], None] = None
    ):
        """
        受监控的执行上下文

        Args:
            execution_id: 执行 ID
            tool_name: 工具名称
            arguments: 工具参数
            timeout_ms: 超时时间
            on_progress: 进度回调
            on_warning: 警告回调
        """
        # 创建执行上下文
        controller = AbortController()
        ctx = ExecutionContext(
            execution_id=execution_id,
            tool_name=tool_name,
            arguments=arguments,
            state=ExecutionState.RUNNING,
            abort_signal=controller.signal
        )

        # 注册
        self._active_controllers[execution_id] = controller
        self.execution_monitor.register(ctx)

        # 开始资源监控
        self.resource_monitor.start()

        try:
            async with self.timeout_controller.with_timeout(
                timeout_ms=timeout_ms,
                abort_signal=controller.signal,
                on_warning=on_warning
            ) as signal:
                yield signal

            # 成功完成
            self.execution_monitor.complete(execution_id, success=True)

        except ExecutionCancelledError as e:
            ctx.state = ExecutionState.CANCELLED
            self.execution_monitor.complete(
                execution_id,
                success=False,
                data={"reason": str(e), "cancelled": True}
            )
            raise

        except ExecutionTimeoutError as e:
            ctx.state = ExecutionState.TIMEOUT
            self.execution_monitor.complete(
                execution_id,
                success=False,
                data={"reason": str(e), "timeout": True}
            )
            raise

        except ResourceExceededError as e:
            ctx.state = ExecutionState.RESOURCE_EXCEEDED
            self.execution_monitor.complete(
                execution_id,
                success=False,
                data={"reason": str(e), "resource_exceeded": True}
            )
            raise

        except Exception as e:
            ctx.state = ExecutionState.FAILED
            self.execution_monitor.complete(
                execution_id,
                success=False,
                data={"error": str(e)}
            )
            raise

        finally:
            # 清理
            self._active_controllers.pop(execution_id, None)
            self.resource_monitor.stop()

    def cancel_execution(self, execution_id: str, reason: str = None):
        """取消执行"""
        if execution_id in self._active_controllers:
            self._active_controllers[execution_id].abort(reason)
        self.execution_monitor.cancel(execution_id, reason)

    def update_progress(self, execution_id: str, progress: float):
        """更新进度"""
        self.execution_monitor.update_progress(execution_id, progress)

    def get_resource_usage(self) -> ResourceUsage:
        """获取资源使用"""
        return self.resource_monitor.get_usage()

    def get_resource_delta(self) -> ResourceUsage:
        """获取资源使用增量"""
        return self.resource_monitor.get_usage_delta()

    def get_active_executions(self) -> List[str]:
        """获取活动执行 ID 列表"""
        return list(self._active_controllers.keys())

    def get_execution_context(self, execution_id: str) -> Optional[ExecutionContext]:
        """获取执行上下文"""
        return self.execution_monitor.get_context(execution_id)

    def is_resource_healthy(self) -> Tuple[bool, List[str]]:
        """检查资源是否健康"""
        violations = self.resource_monitor._check_thresholds()
        return len(violations) == 0, violations

    def get_stats(self) -> Dict[str, Any]:
        """获取监控统计"""
        usage = self.resource_monitor.get_usage()
        return {
            "active_executions": len(self._active_controllers),
            "resource_usage": {
                "memory_mb": usage.memory_mb,
                "cpu_percent": usage.cpu_percent,
                "open_files": usage.open_files,
                "threads": usage.threads,
            },
            "default_timeout_ms": self.default_timeout_ms,
        }
