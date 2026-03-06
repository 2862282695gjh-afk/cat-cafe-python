"""
六层安全防护架构 - 安全管理器
整合所有安全层，提供统一接口
"""
import os
import json
import asyncio
from typing import Any, Dict, List, Optional, Callable, Union
from dataclasses import dataclass, field
from datetime import datetime
from contextlib import asynccontextmanager

from .input_validation import (
    InputValidationLayer, ValidationResult, ValidationError, ZodSchema
)
from .permission_control import (
    PermissionControlLayer, PermissionAction, PermissionContext, PermissionResult
)
from .sandbox_isolation import (
    SandboxIsolationLayer, SandboxConfig, SandboxResult, ResourceLimits, IsolationLevel
)
from .execution_monitoring import (
    ExecutionMonitoringLayer, ExecutionState, AbortSignal, ResourceUsage
)
from .error_recovery import (
    ErrorRecoveryLayer, ErrorCategory, ErrorSeverity, RecoveryStrategy, ErrorContext
)
from .audit_logging import (
    AuditLoggingLayer, AuditEventType, AuditSeverity, AuditEvent, SecurityAlert
)


@dataclass
class SecurityConfig:
    """安全配置"""
    # 输入验证配置
    enable_input_validation: bool = True
    strict_validation: bool = False
    enable_security_check: bool = True

    # 权限控制配置
    enable_permission_control: bool = True
    auto_approve_safe_tools: bool = True
    enable_permission_cache: bool = True

    # 沙箱配置
    enable_sandbox: bool = True
    isolation_level: IsolationLevel = IsolationLevel.STANDARD
    allowed_paths: List[str] = field(default_factory=list)
    blocked_paths: List[str] = field(default_factory=list)
    allowed_domains: List[str] = field(default_factory=list)
    no_network: bool = False

    # 执行监控配置
    enable_monitoring: bool = True
    default_timeout_ms: int = 120000
    max_memory_mb: int = 512
    max_cpu_percent: int = 80
    heartbeat_interval_ms: int = 5000

    # 错误恢复配置
    enable_error_recovery: bool = True
    max_retry_attempts: int = 3
    retry_base_delay_ms: int = 1000

    # 审计配置
    enable_audit: bool = True
    audit_log_dir: str = None
    enable_alerts: bool = True


@dataclass
class SecurityContext:
    """安全上下文"""
    execution_id: str
    tool_name: str
    arguments: Dict[str, Any]
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    working_dir: Optional[str] = None
    timestamp: int = field(default_factory=lambda: int(datetime.now().timestamp() * 1000))


@dataclass
class SecurityCheckResult:
    """安全检查结果"""
    allowed: bool
    layer: str  # 哪一层做的决定
    reason: str
    validation_result: Optional[ValidationResult] = None
    permission_result: Optional[PermissionResult] = None
    sandbox_result: Optional[SandboxResult] = None
    needs_confirmation: bool = False
    confirmation_message: Optional[str] = None


class SecurityManager:
    """
    六层安全防护架构管理器

    Layer 1: 输入验证层 - InputValidationLayer
    Layer 2: 权限控制层 - PermissionControlLayer
    Layer 3: 沙箱隔离层 - SandboxIsolationLayer
    Layer 4: 执行监控层 - ExecutionMonitoringLayer
    Layer 5: 错误恢复层 - ErrorRecoveryLayer
    Layer 6: 审计记录层 - AuditLoggingLayer
    """

    def __init__(
        self,
        config: SecurityConfig = None,
        working_dir: str = None,
        user_id: str = None,
        session_id: str = None
    ):
        self.config = config or SecurityConfig()
        self.working_dir = working_dir or os.getcwd()
        self.user_id = user_id
        self.session_id = session_id or self._generate_session_id()

        # 初始化各层
        self._init_layers()

        # 活跃的执行
        self._active_executions: Dict[str, SecurityContext] = {}

    def _generate_session_id(self) -> str:
        """生成会话 ID"""
        import uuid
        return f"sec_session_{uuid.uuid4().hex[:12]}"

    def _init_layers(self):
        """初始化所有安全层"""
        config = self.config

        # Layer 1: 输入验证层
        if config.enable_input_validation:
            self.input_validation = InputValidationLayer(
                enable_security_check=config.enable_security_check,
                strict_mode=config.strict_validation
            )
        else:
            self.input_validation = None

        # Layer 2: 权限控制层
        if config.enable_permission_control:
            self.permission_control = PermissionControlLayer(
                auto_approve_safe=config.auto_approve_safe_tools,
                enable_cache=config.enable_permission_cache
            )
        else:
            self.permission_control = None

        # Layer 3: 沙箱隔离层
        if config.enable_sandbox:
            sandbox_config = SandboxConfig(
                isolation_level=config.isolation_level,
                allowed_paths=config.allowed_paths,
                blocked_paths=config.blocked_paths,
                allowed_domains=config.allowed_domains,
                no_network=config.no_network,
                resource_limits=ResourceLimits(
                    max_memory_mb=config.max_memory_mb,
                    max_cpu_percent=config.max_cpu_percent,
                    max_execution_time_s=config.default_timeout_ms // 1000
                )
            )
            self.sandbox = SandboxIsolationLayer(
                config=sandbox_config,
                working_dir=self.working_dir
            )
        else:
            self.sandbox = None

        # Layer 4: 执行监控层
        if config.enable_monitoring:
            self.execution_monitoring = ExecutionMonitoringLayer(
                default_timeout_ms=config.default_timeout_ms,
                heartbeat_interval_ms=config.heartbeat_interval_ms
            )
        else:
            self.execution_monitoring = None

        # Layer 5: 错误恢复层
        if config.enable_error_recovery:
            from .error_recovery import RetryConfig
            retry_config = RetryConfig(
                max_attempts=config.max_retry_attempts,
                base_delay_ms=config.retry_base_delay_ms
            )
            self.error_recovery = ErrorRecoveryLayer(
                retry_config=retry_config,
                enable_logging=True,
                log_dir=config.audit_log_dir
            )
        else:
            self.error_recovery = None

        # Layer 6: 审计记录层
        if config.enable_audit:
            self.audit_logging = AuditLoggingLayer(
                storage=None,  # 使用默认文件存储
                enable_alerts=config.enable_alerts,
                user_id=self.user_id,
                session_id=self.session_id
            )
        else:
            self.audit_logging = None

    async def start(self):
        """启动安全架构"""
        if self.execution_monitoring:
            await self.execution_monitoring.start()

        if self.audit_logging:
            await self.audit_logging.start()

    async def stop(self):
        """停止安全架构"""
        if self.execution_monitoring:
            await self.execution_monitoring.stop()

        if self.audit_logging:
            await self.audit_logging.stop()

    # ==================== 安全检查入口 ====================

    async def check_execution(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        execution_id: str = None
    ) -> SecurityCheckResult:
        """
        执行前的安全检查

        按顺序检查：
        1. 输入验证
        2. 权限控制
        3. 沙箱规则

        Returns:
            SecurityCheckResult
        """
        import uuid
        execution_id = execution_id or f"exec_{uuid.uuid4().hex[:8]}"

        # Layer 1: 输入验证
        if self.input_validation:
            validation_result = self.input_validation.validate_tool_input(
                tool_name, arguments
            )
            if not validation_result.valid:
                await self._log_security_event(
                    AuditEventType.SECURITY_VIOLATION,
                    f"输入验证失败: {tool_name}",
                    {"errors": [e.to_dict() for e in validation_result.errors]}
                )
                return SecurityCheckResult(
                    allowed=False,
                    layer="input_validation",
                    reason="; ".join(e.message for e in validation_result.errors),
                    validation_result=validation_result
                )

        # Layer 2: 权限控制
        if self.permission_control:
            permission_context = PermissionContext(
                tool_name=tool_name,
                arguments=arguments,
                user_id=self.user_id,
                session_id=self.session_id,
                working_dir=self.working_dir
            )
            permission_result = await self.permission_control.check_permission(
                permission_context
            )

            if permission_result.action == PermissionAction.DENY:
                await self._log_permission_event(tool_name, "deny", permission_result.reason)
                return SecurityCheckResult(
                    allowed=False,
                    layer="permission_control",
                    reason=permission_result.reason,
                    permission_result=permission_result
                )

            if permission_result.action == PermissionAction.ASK:
                await self._log_permission_event(tool_name, "ask", permission_result.reason)
                return SecurityCheckResult(
                    allowed=False,
                    layer="permission_control",
                    reason=permission_result.reason,
                    permission_result=permission_result,
                    needs_confirmation=True,
                    confirmation_message=permission_result.confirmation_message
                )

            await self._log_permission_event(tool_name, "allow", permission_result.reason)

        # Layer 3: 沙箱检查
        if self.sandbox:
            allowed, reason = self.sandbox.check_tool_execution(tool_name, arguments)
            if not allowed:
                await self._log_security_event(
                    AuditEventType.SANDBOX_VIOLATION,
                    f"沙箱规则违反: {tool_name}",
                    {"reason": reason}
                )
                return SecurityCheckResult(
                    allowed=False,
                    layer="sandbox",
                    reason=reason
                )

        # 所有检查通过
        return SecurityCheckResult(
            allowed=True,
            layer="all",
            reason="All security checks passed"
        )

    @asynccontextmanager
    async def monitored_execution(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        execution_id: str = None,
        timeout_ms: int = None,
        on_progress: Callable[[float], None] = None
    ):
        """
        受监控的执行上下文

        用法:
            async with security_manager.monitored_execution("Bash", {"command": "ls"}) as signal:
                # 执行操作
                ...
        """
        import uuid
        execution_id = execution_id or f"exec_{uuid.uuid4().hex[:8]}"

        # 执行安全检查
        check_result = await self.check_execution(tool_name, arguments, execution_id)

        if not check_result.allowed:
            if check_result.needs_confirmation:
                raise PermissionNeededError(
                    check_result.confirmation_message,
                    execution_id,
                    tool_name
                )
            else:
                raise SecurityViolationError(
                    check_result.reason,
                    check_result.layer
                )

        # Layer 4: 执行监控
        if self.execution_monitoring:
            async with self.execution_monitoring.monitored_execution(
                execution_id=execution_id,
                tool_name=tool_name,
                arguments=arguments,
                timeout_ms=timeout_ms,
                on_progress=on_progress
            ) as signal:
                # 记录执行开始
                if self.audit_logging:
                    await self.audit_logging.log_event(
                        event_type=AuditEventType.TOOL_EXECUTE,
                        severity=AuditSeverity.INFO,
                        description=f"工具执行开始: {tool_name}",
                        tool_name=tool_name,
                        execution_id=execution_id,
                        details={"arguments": arguments}
                    )

                try:
                    yield signal

                    # 记录执行成功
                    if self.audit_logging:
                        await self.audit_logging.log_event(
                            event_type=AuditEventType.TOOL_SUCCESS,
                            severity=AuditSeverity.INFO,
                            description=f"工具执行成功: {tool_name}",
                            tool_name=tool_name,
                            execution_id=execution_id
                        )

                except Exception as e:
                    # Layer 5: 错误恢复
                    if self.error_recovery:
                        # 错误恢复层会处理重试和降级
                        raise

                    # 记录执行失败
                    if self.audit_logging:
                        await self.audit_logging.log_event(
                            event_type=AuditEventType.TOOL_FAILURE,
                            severity=AuditSeverity.WARNING,
                            description=f"工具执行失败: {tool_name}",
                            tool_name=tool_name,
                            execution_id=execution_id,
                            details={"error": str(e)}
                        )

                    raise
        else:
            # 无监控执行
            yield AbortSignal()

    # ==================== 权限管理 ====================

    def approve_permission(self, execution_id: str, tool_name: str, arguments: Dict):
        """批准权限请求"""
        if self.permission_control:
            context = PermissionContext(
                tool_name=tool_name,
                arguments=arguments,
                user_id=self.user_id,
                session_id=self.session_id
            )
            self.permission_control.approve(context)

    def deny_permission(self, execution_id: str, tool_name: str, arguments: Dict):
        """拒绝权限请求"""
        if self.permission_control:
            context = PermissionContext(
                tool_name=tool_name,
                arguments=arguments,
                user_id=self.user_id,
                session_id=self.session_id
            )
            self.permission_control.deny(context)

    # ==================== 沙箱管理 ====================

    def add_allowed_path(self, path: str):
        """添加允许的路径"""
        if self.sandbox:
            self.sandbox.add_allowed_path(path)

    def add_allowed_domain(self, domain: str):
        """添加允许的域名"""
        if self.sandbox:
            self.sandbox.add_allowed_domain(domain)

    # ==================== 审计和报告 ====================

    async def get_audit_events(
        self,
        start_time: int = None,
        end_time: int = None,
        limit: int = 100
    ) -> List[AuditEvent]:
        """获取审计事件"""
        if self.audit_logging:
            return await self.audit_logging.query_events(
                start_time=start_time,
                end_time=end_time,
                limit=limit
            )
        return []

    async def get_daily_report(self):
        """获取日报表"""
        if self.audit_logging:
            return await self.audit_logging.get_daily_report()
        return None

    def get_active_alerts(self) -> List[SecurityAlert]:
        """获取活动告警"""
        if self.audit_logging:
            return self.audit_logging.get_active_alerts()
        return []

    def acknowledge_alert(self, alert_id: str, acknowledged_by: str = None):
        """确认告警"""
        if self.audit_logging:
            self.audit_logging.acknowledge_alert(alert_id, acknowledged_by)

    # ==================== 状态和统计 ====================

    async def get_stats(self) -> Dict[str, Any]:
        """获取所有安全层的统计"""
        stats = {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "working_dir": self.working_dir,
            "layers": {}
        }

        if self.input_validation:
            stats["layers"]["input_validation"] = {
                "enabled": True,
                "tool_schemas": len(self.input_validation.schemas)
            }

        if self.permission_control:
            stats["layers"]["permission_control"] = self.permission_control.get_stats()

        if self.sandbox:
            stats["layers"]["sandbox"] = self.sandbox.get_sandbox_info()

        if self.execution_monitoring:
            stats["layers"]["execution_monitoring"] = self.execution_monitoring.get_stats()

        if self.error_recovery:
            stats["layers"]["error_recovery"] = self.error_recovery.get_error_stats()

        if self.audit_logging:
            stats["layers"]["audit_logging"] = await self.audit_logging.get_stats()

        return stats

    async def health_check(self) -> Dict[str, bool]:
        """健康检查"""
        health = {
            "input_validation": self.input_validation is not None,
            "permission_control": self.permission_control is not None,
            "sandbox": self.sandbox is not None,
            "execution_monitoring": self.execution_monitoring is not None,
            "error_recovery": self.error_recovery is not None,
            "audit_logging": self.audit_logging is not None,
        }

        # 检查资源
        if self.execution_monitoring:
            is_healthy, violations = self.execution_monitoring.is_resource_healthy()
            health["resource_healthy"] = is_healthy
            if violations:
                health["resource_violations"] = violations

        return health

    # ==================== 内部方法 ====================

    async def _log_permission_event(self, tool_name: str, action: str, reason: str):
        """记录权限事件"""
        if self.audit_logging:
            await self.audit_logging.log_permission_event(tool_name, action, reason)

    async def _log_security_event(
        self,
        event_type: AuditEventType,
        description: str,
        details: Dict[str, Any] = None
    ):
        """记录安全事件"""
        if self.audit_logging:
            await self.audit_logging.log_security_event(
                event_type=event_type,
                description=description,
                details=details
            )


# ============================================================================
# 异常类
# ============================================================================

class SecurityViolationError(Exception):
    """安全违规错误"""

    def __init__(self, message: str, layer: str):
        super().__init__(f"[{layer}] {message}")
        self.layer = layer


class PermissionNeededError(Exception):
    """需要权限确认错误"""

    def __init__(self, message: str, execution_id: str, tool_name: str):
        super().__init__(message)
        self.execution_id = execution_id
        self.tool_name = tool_name


# ============================================================================
# 便捷函数
# ============================================================================

def create_security_manager(
    working_dir: str = None,
    auto_approve_safe: bool = True,
    enable_sandbox: bool = True,
    enable_audit: bool = True
) -> SecurityManager:
    """
    创建安全管理器的便捷函数

    Args:
        working_dir: 工作目录
        auto_approve_safe: 自动批准安全工具
        enable_sandbox: 启用沙箱
        enable_audit: 启用审计

    Returns:
        SecurityManager
    """
    config = SecurityConfig(
        auto_approve_safe_tools=auto_approve_safe,
        enable_sandbox=enable_sandbox,
        enable_audit=enable_audit
    )

    return SecurityManager(
        config=config,
        working_dir=working_dir
    )
