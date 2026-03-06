"""
六层安全防护架构

Layer 1: 输入验证层 (InputValidationLayer)
    - Zod Schema 严格验证
    - 参数类型强制检查
    - 格式验证边界约束

Layer 2: 权限控制层 (PermissionControlLayer)
    - 权限验证三元组 (allow, deny, ask)
    - Hook 机制绕过通道

Layer 3: 沙箱隔离层 (SandboxIsolationLayer)
    - Bash 沙箱
    - 文件系统写入限制
    - 网络访问域名白名单

Layer 4: 执行监控层 (ExecutionMonitoringLayer)
    - AbortController 中断信号
    - 超时控制防止卡死
    - 资源限制内存/CPU

Layer 5: 错误恢复层 (ErrorRecoveryLayer)
    - 异常捕获
    - 错误分类
    - 详细日志
    - 自动重试降级处理

Layer 6: 审计记录层 (AuditLoggingLayer)
    - 操作日志完整追踪
    - 安全事件实时告警
    - 合规报告定期审计
"""

from .input_validation import (
    InputValidationLayer,
    ZodSchema,
    ValidationResult,
    ValidationError,
    ZodString,
    ZodNumber,
    ZodBoolean,
    ZodArray,
    ZodObject,
    ZodUnion,
    ZodEnum,
    SecurityPatternChecker
)
from .permission_control import (
    PermissionControlLayer,
    PermissionAction,
    PermissionContext,
    PermissionResult,
    PermissionSource,
    RiskLevel,
    Hook,
    HookType,
    HookRegistry,
    PermissionPolicy,
    DefaultPolicy,
    WhitelistPolicy,
    DangerPatternRegistry
)
from .sandbox_isolation import (
    SandboxIsolationLayer,
    SandboxConfig,
    SandboxResult,
    ResourceLimits,
    IsolationLevel,
    FileSystemSandbox,
    BashSandbox,
    NetworkSandbox
)
from .execution_monitoring import (
    ExecutionMonitoringLayer,
    ExecutionMonitor,
    ExecutionState,
    ExecutionContext,
    AbortController,
    AbortSignal,
    ResourceMonitor,
    ResourceUsage,
    ResourceThresholds,
    TimeoutController,
    ExecutionCancelledError,
    ExecutionTimeoutError,
    ResourceExceededError
)
from .error_recovery import (
    ErrorRecoveryLayer,
    ErrorCategory,
    ErrorSeverity,
    ErrorContext,
    RecoveryStrategy,
    RecoveryResult,
    RetryConfig,
    RetryExecutor,
    ErrorClassifier,
    RecoveryStrategySelector,
    FallbackHandler,
    with_error_recovery
)
from .audit_logging import (
    AuditLoggingLayer,
    AuditEvent,
    AuditEventType,
    AuditSeverity,
    SecurityAlert,
    AlertType,
    AlertManager,
    AlertRule,
    AuditStorage,
    FileAuditStorage,
    ComplianceReport,
    ComplianceReporter
)
from .security_manager import (
    SecurityManager,
    SecurityConfig,
    SecurityContext,
    SecurityCheckResult,
    SecurityViolationError,
    PermissionNeededError,
    create_security_manager
)

__all__ = [
    # Layer 1: 输入验证层
    'InputValidationLayer',
    'ZodSchema',
    'ValidationResult',
    'ValidationError',
    'ZodString',
    'ZodNumber',
    'ZodBoolean',
    'ZodArray',
    'ZodObject',
    'ZodUnion',
    'ZodEnum',
    'SecurityPatternChecker',

    # Layer 2: 权限控制层
    'PermissionControlLayer',
    'PermissionAction',
    'PermissionContext',
    'PermissionResult',
    'PermissionSource',
    'RiskLevel',
    'Hook',
    'HookType',
    'HookRegistry',
    'PermissionPolicy',
    'DefaultPolicy',
    'WhitelistPolicy',
    'DangerPatternRegistry',

    # Layer 3: 沙箱隔离层
    'SandboxIsolationLayer',
    'SandboxConfig',
    'SandboxResult',
    'ResourceLimits',
    'IsolationLevel',
    'FileSystemSandbox',
    'BashSandbox',
    'NetworkSandbox',

    # Layer 4: 执行监控层
    'ExecutionMonitoringLayer',
    'ExecutionMonitor',
    'ExecutionState',
    'ExecutionContext',
    'AbortController',
    'AbortSignal',
    'ResourceMonitor',
    'ResourceUsage',
    'ResourceThresholds',
    'TimeoutController',
    'ExecutionCancelledError',
    'ExecutionTimeoutError',
    'ResourceExceededError',

    # Layer 5: 错误恢复层
    'ErrorRecoveryLayer',
    'ErrorCategory',
    'ErrorSeverity',
    'ErrorContext',
    'RecoveryStrategy',
    'RecoveryResult',
    'RetryConfig',
    'RetryExecutor',
    'ErrorClassifier',
    'RecoveryStrategySelector',
    'FallbackHandler',
    'with_error_recovery',

    # Layer 6: 审计记录层
    'AuditLoggingLayer',
    'AuditEvent',
    'AuditEventType',
    'AuditSeverity',
    'SecurityAlert',
    'AlertType',
    'AlertManager',
    'AlertRule',
    'AuditStorage',
    'FileAuditStorage',
    'ComplianceReport',
    'ComplianceReporter',

    # 统一管理器
    'SecurityManager',
    'SecurityConfig',
    'SecurityContext',
    'SecurityCheckResult',
    'SecurityViolationError',
    'PermissionNeededError',
    'create_security_manager',
]
