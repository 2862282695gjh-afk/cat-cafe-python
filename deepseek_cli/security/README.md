# 六层安全防护架构

## 概述

本模块实现了完整的六层安全防护架构，用于保护 AI Agent 系统的执行安全。

## 架构层次

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Layer 6: 审计记录层                           │
│   操作日志完整追踪 | 安全事件实时告警 | 合规报告定期审计                  │
├─────────────────────────────────────────────────────────────────────┤
│                        Layer 5: 错误恢复层                           │
│   异常捕获 | 错误分类 | 详细日志 | 自动重试降级处理                      │
├─────────────────────────────────────────────────────────────────────┤
│                        Layer 4: 执行监控层                           │
│   AbortController中断信号 | 超时控制防止卡死 | 资源限制内存/CPU          │
├─────────────────────────────────────────────────────────────────────┤
│                        Layer 3: 沙箱隔离层                           │
│   Bash沙箱 | 文件系统写入限制 | 网络访问域名白名单                       │
├─────────────────────────────────────────────────────────────────────┤
│                        Layer 2: 权限控制层                           │
│   权限验证三元组(allow/deny/ask) | Hook机制绕过通道                     │
├─────────────────────────────────────────────────────────────────────┤
│                        Layer 1: 输入验证层                           │
│   Zod Schema严格验证 | 参数类型强制检查 | 格式验证边界约束                 │
└─────────────────────────────────────────────────────────────────────┘
```

## 快速开始

```python
from deepseek_cli.security import create_security_manager

# 创建安全管理器
security = create_security_manager(
    working_dir="/path/to/project",
    auto_approve_safe=True,
    enable_sandbox=True,
    enable_audit=True
)

# 启动
await security.start()

# 安全检查
result = await security.check_execution(
    tool_name="Bash",
    arguments={"command": "ls -la"}
)

if result.allowed:
    # 执行操作
    async with security.monitored_execution(
        tool_name="Bash",
        arguments={"command": "ls -la"}
    ) as signal:
        # 你的代码
        pass
else:
    print(f"操作被拒绝: {result.reason}")

# 停止
await security.stop()
```

## 各层详解

### Layer 1: 输入验证层 (InputValidationLayer)

提供 Zod 风格的 Schema 验证：

```python
from deepseek_cli.security import ZodObject, ZodString, ZodNumber

# 定义 Schema
schema = ZodObject({
    "file_path": ZodString().min(1).max(500),
    "mode": ZodString().pattern(r"^(read|write)$"),
    "limit": ZodNumber().int().positive().max(10000).optional().default(1000)
})

# 验证
result = schema.validate({"file_path": "/test.txt", "mode": "read"})
```

**功能：**
- 类型强制检查
- 必填参数验证
- 格式验证（email, url, uuid 等）
- 边界约束（min, max, minLength, maxLength）
- 安全模式检测（SQL注入、命令注入、XSS、路径遍历）

### Layer 2: 权限控制层 (PermissionControlLayer)

实现 allow/deny/ask 三元组权限控制：

```python
from deepseek_cli.security import PermissionControlLayer, PermissionContext

permission = PermissionControlLayer(auto_approve_safe=True)

context = PermissionContext(
    tool_name="Bash",
    arguments={"command": "ls -la"}
)

result = await permission.check_permission(context)
# result.action: ALLOW / DENY / ASK
```

**功能：**
- 三元组权限验证 (allow, deny, ask)
- Hook 机制（PRE_CHECK, POST_CHECK, PRE_EXECUTE 等）
- 危险等级评估（SAFE, LOW, MEDIUM, HIGH, CRITICAL）
- 会话级权限缓存

### Layer 3: 沙箱隔离层 (SandboxIsolationLayer)

提供多层隔离保护：

```python
from deepseek_cli.security import SandboxIsolationLayer, SandboxConfig, IsolationLevel

config = SandboxConfig(
    isolation_level=IsolationLevel.STANDARD,
    allowed_paths=["/home/user/project"],
    blocked_paths=["/etc/passwd", "/etc/shadow"],
    allowed_domains=["api.deepseek.com", "github.com"],
    no_network=False
)

sandbox = SandboxIsolationLayer(config=config)

# 检查文件访问
allowed, reason = sandbox.check_file_access("/etc/passwd", "read")

# 检查命令
allowed, reason = sandbox.check_command("rm -rf /")
```

**功能：**
- Bash 命令沙箱
- 文件系统访问控制
- 网络域名白名单
- 资源限制（内存、CPU、文件大小等）

### Layer 4: 执行监控层 (ExecutionMonitoringLayer)

实时监控执行状态：

```python
from deepseek_cli.security import ExecutionMonitoringLayer, AbortController

monitoring = ExecutionMonitoringLayer(
    default_timeout_ms=120000,
    heartbeat_interval_ms=5000
)

await monitoring.start()

# 使用监控上下文
async with monitoring.monitored_execution(
    execution_id="exec_001",
    tool_name="Bash",
    arguments={"command": "long-running-task"},
    timeout_ms=30000
) as signal:
    # 定期检查取消状态
    signal.throw_if_aborted()
    # 你的代码

# 取消执行
monitoring.cancel_execution("exec_001", "用户取消")
```

**功能：**
- AbortController 中断信号
- 超时控制
- 资源使用监控
- 进度追踪
- 心跳检测

### Layer 5: 错误恢复层 (ErrorRecoveryLayer)

智能错误处理和恢复：

```python
from deepseek_cli.security import ErrorRecoveryLayer, RetryConfig

config = RetryConfig(
    max_attempts=3,
    base_delay_ms=1000,
    exponential_base=2.0
)

recovery = ErrorRecoveryLayer(retry_config=config)

# 带恢复的执行
result = await recovery.execute_with_recovery(
    my_async_function,
    arg1, arg2,
    tool_name="MyTool",
    fallback_value="默认值"
)
```

**功能：**
- 异常捕获和分类
- 自动重试（指数退避）
- 降级处理
- 详细错误日志
- 错误统计

### Layer 6: 审计记录层 (AuditLoggingLayer)

完整的审计追踪：

```python
from deepseek_cli.security import AuditLoggingLayer, AuditEventType, AuditSeverity

audit = AuditLoggingLayer(
    user_id="user_001",
    session_id="session_001"
)

await audit.start()

# 记录事件
await audit.log_event(
    event_type=AuditEventType.TOOL_EXECUTE,
    severity=AuditSeverity.INFO,
    description="执行命令",
    tool_name="Bash",
    details={"command": "ls -la"}
)

# 获取告警
alerts = audit.get_active_alerts()

# 生成报告
report = await audit.get_daily_report()
```

**功能：**
- 操作日志完整追踪
- 安全事件实时告警
- 合规报告生成
- 事件查询

## 统一管理器

使用 `SecurityManager` 统一管理所有层：

```python
from deepseek_cli.security import SecurityManager, SecurityConfig, IsolationLevel

config = SecurityConfig(
    enable_input_validation=True,
    enable_permission_control=True,
    enable_sandbox=True,
    enable_monitoring=True,
    enable_error_recovery=True,
    enable_audit=True,
    isolation_level=IsolationLevel.STANDARD,
    default_timeout_ms=120000,
    max_memory_mb=512,
    auto_approve_safe_tools=True
)

security = SecurityManager(
    config=config,
    working_dir="/path/to/project",
    user_id="user_001"
)

await security.start()

# 完整的安全检查和执行流程
check_result = await security.check_execution(tool_name, arguments)

if check_result.needs_confirmation:
    # 需要用户确认
    security.approve_permission(execution_id, tool_name, arguments)

if check_result.allowed:
    async with security.monitored_execution(tool_name, arguments) as signal:
        # 安全执行
        pass

# 获取统计信息
stats = await security.get_stats()

# 健康检查
health = await security.health_check()

await security.stop()
```

## 运行示例

```bash
cd cat-cafe-python
python -m deepseek_cli.security.example_usage
```

## 文件结构

```
deepseek_cli/security/
├── __init__.py           # 模块导出
├── input_validation.py   # Layer 1: 输入验证层
├── permission_control.py # Layer 2: 权限控制层
├── sandbox_isolation.py  # Layer 3: 沙箱隔离层
├── execution_monitoring.py # Layer 4: 执行监控层
├── error_recovery.py     # Layer 5: 错误恢复层
├── audit_logging.py      # Layer 6: 审计记录层
├── security_manager.py   # 统一安全管理器
├── example_usage.py      # 使用示例
└── README.md             # 本文档
```

## 依赖

- Python 3.8+
- asyncio
- 可选: psutil (用于资源监控)

## 注意事项

1. 生产环境建议启用所有安全层
2. 根据实际需求调整沙箱隔离级别
3. 定期检查审计日志和告警
4. 合理设置资源限制和超时时间
