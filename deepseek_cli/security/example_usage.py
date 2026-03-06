#!/usr/bin/env python3
"""
六层安全防护架构使用示例

展示如何使用 SecurityManager 整合所有安全层
"""
import asyncio
import os
import sys

# 添加父目录到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from deepseek_cli.security import (
    SecurityManager,
    SecurityConfig,
    create_security_manager,
    ZodString,
    ZodNumber,
    ZodObject,
    PermissionAction,
    IsolationLevel,
    ResourceLimits,
    AuditEventType,
    AuditSeverity,
)


async def example_basic_usage():
    """基本使用示例"""
    print("=" * 60)
    print("示例 1: 基本使用")
    print("=" * 60)

    # 创建安全管理器
    security = create_security_manager(
        working_dir=os.getcwd(),
        auto_approve_safe=True,
        enable_sandbox=True,
        enable_audit=True
    )

    # 启动
    await security.start()

    try:
        # 检查工具执行
        result = await security.check_execution(
            tool_name="Read",
            arguments={"file_path": "/etc/passwd"}
        )

        print(f"Read /etc/passwd: allowed={result.allowed}, layer={result.layer}, reason={result.reason}")

        # 检查另一个工具
        result = await security.check_execution(
            tool_name="Bash",
            arguments={"command": "ls -la"}
        )

        print(f"Bash ls -la: allowed={result.allowed}, layer={result.layer}, reason={result.reason}")

        # 检查危险命令
        result = await security.check_execution(
            tool_name="Bash",
            arguments={"command": "rm -rf /"}
        )

        print(f"Bash rm -rf /: allowed={result.allowed}, layer={result.layer}, reason={result.reason}")

        # 获取统计
        stats = await security.get_stats()
        print(f"\n安全层统计: {json.dumps(stats, indent=2, default=str)}")

    finally:
        await security.stop()


async def example_monitored_execution():
    """受监控执行示例"""
    print("\n" + "=" * 60)
    print("示例 2: 受监控执行")
    print("=" * 60)

    security = create_security_manager(working_dir=os.getcwd())
    await security.start()

    try:
        # 使用监控上下文执行
        async with security.monitored_execution(
            tool_name="Bash",
            arguments={"command": "echo 'Hello, Security!'"},
            timeout_ms=5000
        ) as signal:
            # 检查是否被取消
            if signal.aborted:
                print("执行被取消")
                return

            # 模拟执行
            print("执行命令...")
            await asyncio.sleep(0.1)
            print("命令执行完成")

    except Exception as e:
        print(f"执行错误: {e}")
    finally:
        await security.stop()


async def example_custom_validation():
    """自定义验证示例"""
    print("\n" + "=" * 60)
    print("示例 3: 自定义输入验证")
    print("=" * 60)

    from deepseek_cli.security import InputValidationLayer

    # 创建验证层
    validation = InputValidationLayer(enable_security_check=True)

    # 定义自定义 Schema
    custom_schema = ZodObject({
        "file_path": ZodString().min(1).max(500),
        "mode": ZodString().pattern(r"^(read|write|append)$"),
        "encoding": ZodString().optional().default("utf-8"),
        "limit": ZodNumber().int().positive().max(10000).optional().default(1000),
    })

    validation.register_schema("CustomRead", custom_schema)

    # 验证有效输入
    result = validation.validate_tool_input("CustomRead", {
        "file_path": "/home/user/test.txt",
        "mode": "read"
    })
    print(f"有效输入: valid={result.valid}, normalized={result.normalized_value}")

    # 验证无效输入
    result = validation.validate_tool_input("CustomRead", {
        "file_path": "",  # 空路径
        "mode": "invalid"  # 无效模式
    })
    print(f"无效输入: valid={result.valid}, errors={[e.message for e in result.errors]}")


async def example_permission_hooks():
    """权限 Hook 示例"""
    print("\n" + "=" * 60)
    print("示例 4: 权限控制 Hook")
    print("=" * 60)

    from deepseek_cli.security import (
        PermissionControlLayer,
        Hook,
        HookType,
        HookResult
    )

    # 创建权限控制层
    permission = PermissionControlLayer(auto_approve_safe=True)

    # 定义一个 Hook：在执行 Bash 命令前记录日志
    async def log_bash_command(context):
        print(f"[Hook] 准备执行 Bash 命令: {context.arguments.get('command', '')}")
        return HookResult(continue_=True)

    # 注册 Hook
    hook = Hook(
        hook_id="log_bash",
        hook_type=HookType.PRE_EXECUTE,
        callback=lambda ctx: log_bash_command(ctx),
        tools={"Bash"}
    )
    permission.register_hook(hook)

    # 检查权限
    from deepseek_cli.security import PermissionContext
    ctx = PermissionContext(
        tool_name="Bash",
        arguments={"command": "ls -la"},
        working_dir=os.getcwd()
    )

    result = await permission.check_permission(ctx)
    print(f"权限检查结果: action={result.action.value}, allowed={result.allowed}")


async def example_sandbox():
    """沙箱隔离示例"""
    print("\n" + "=" * 60)
    print("示例 5: 沙箱隔离")
    print("=" * 60)

    from deepseek_cli.security import SandboxIsolationLayer, SandboxConfig

    # 配置沙箱
    config = SandboxConfig(
        isolation_level=IsolationLevel.STRICT,
        allowed_paths=[os.getcwd()],
        blocked_paths=["/etc/passwd", "/etc/shadow"],
        no_network=False,
        resource_limits=ResourceLimits(
            max_memory_mb=256,
            max_execution_time_s=30
        )
    )

    sandbox = SandboxIsolationLayer(config=config, working_dir=os.getcwd())

    # 检查文件访问
    allowed, reason = sandbox.check_file_access("/etc/passwd", "read")
    print(f"访问 /etc/passwd: allowed={allowed}, reason={reason}")

    allowed, reason = sandbox.check_file_access(os.path.join(os.getcwd(), "test.txt"), "write")
    print(f"写入 {os.getcwd()}/test.txt: allowed={allowed}, reason={reason}")

    # 检查命令
    allowed, reason = sandbox.check_command("rm -rf /")
    print(f"执行 rm -rf /: allowed={allowed}, reason={reason}")

    allowed, reason = sandbox.check_command("ls -la")
    print(f"执行 ls -la: allowed={allowed}, reason={reason}")

    # 获取沙箱信息
    print(f"\n沙箱信息: {sandbox.get_sandbox_info()}")


async def example_audit():
    """审计日志示例"""
    print("\n" + "=" * 60)
    print("示例 6: 审计日志")
    print("=" * 60)

    from deepseek_cli.security import AuditLoggingLayer

    # 创建审计层
    audit = AuditLoggingLayer(
        user_id="demo_user",
        session_id="demo_session"
    )

    await audit.start()

    try:
        # 记录一些事件
        await audit.log_event(
            event_type=AuditEventType.TOOL_EXECUTE,
            severity=AuditSeverity.INFO,
            description="执行 Bash 命令",
            tool_name="Bash",
            details={"command": "ls -la"}
        )

        await audit.log_event(
            event_type=AuditEventType.PERMISSION_GRANTED,
            severity=AuditSeverity.INFO,
            description="权限已授予",
            tool_name="Bash"
        )

        await audit.log_event(
            event_type=AuditEventType.SECURITY_VIOLATION,
            severity=AuditSeverity.WARNING,
            description="检测到潜在危险操作",
            tool_name="Bash",
            details={"attempted_command": "rm -rf /"}
        )

        # 获取活动告警
        alerts = audit.get_active_alerts()
        print(f"活动告警数量: {len(alerts)}")
        for alert in alerts:
            print(f"  - {alert.title}: {alert.message}")

        # 获取统计
        stats = await audit.get_stats()
        print(f"\n审计统计: {stats}")

    finally:
        await audit.stop()


async def example_error_recovery():
    """错误恢复示例"""
    print("\n" + "=" * 60)
    print("示例 7: 错误恢复")
    print("=" * 60)

    from deepseek_cli.security import (
        ErrorRecoveryLayer,
        RetryConfig,
        ErrorCategory,
        with_error_recovery
    )

    # 配置重试
    retry_config = RetryConfig(
        max_attempts=3,
        base_delay_ms=500,
        exponential_base=2.0
    )

    recovery = ErrorRecoveryLayer(
        retry_config=retry_config,
        enable_logging=True
    )

    # 模拟一个可能失败的操作
    attempt_count = 0

    async def unstable_operation():
        nonlocal attempt_count
        attempt_count += 1
        print(f"尝试 #{attempt_count}")

        if attempt_count < 3:
            raise ConnectionError("模拟连接失败")

        return "成功!"

    # 使用错误恢复执行
    try:
        result = await recovery.execute_with_recovery(
            unstable_operation,
            tool_name="TestOperation",
            fallback_value="降级结果"
        )
        print(f"最终结果: {result}")
    except Exception as e:
        print(f"执行失败: {e}")

    # 获取错误统计
    stats = recovery.get_error_stats()
    print(f"\n错误统计: {stats}")


async def example_full_integration():
    """完整集成示例"""
    print("\n" + "=" * 60)
    print("示例 8: 完整集成")
    print("=" * 60)

    # 配置所有安全层
    config = SecurityConfig(
        enable_input_validation=True,
        enable_permission_control=True,
        enable_sandbox=True,
        enable_monitoring=True,
        enable_error_recovery=True,
        enable_audit=True,
        auto_approve_safe_tools=True,
        isolation_level=IsolationLevel.STANDARD,
        default_timeout_ms=30000,
        max_retry_attempts=3
    )

    # 创建安全管理器
    security = SecurityManager(
        config=config,
        working_dir=os.getcwd(),
        user_id="integration_test_user"
    )

    await security.start()

    try:
        print("\n1. 健康检查")
        health = await security.health_check()
        print(f"   健康状态: {health}")

        print("\n2. 安全检查")
        # 安全的只读操作
        result = await security.check_execution("Read", {"file_path": "example.txt"})
        print(f"   Read: {result.allowed}")

        # 写入操作（需要确认）
        result = await security.check_execution("Write", {
            "file_path": "test.txt",
            "content": "test"
        })
        print(f"   Write: {result.allowed}, needs_confirmation={result.needs_confirmation}")

        # 危险命令
        result = await security.check_execution("Bash", {"command": "rm -rf /"})
        print(f"   Dangerous Bash: {result.allowed}")

        print("\n3. 获取统计")
        stats = await security.get_stats()
        for layer, layer_stats in stats.get("layers", {}).items():
            print(f"   {layer}: {layer_stats}")

        print("\n4. 获取审计报告")
        report = await security.get_daily_report()
        if report:
            print(f"   日报表: {report.summary}")

    finally:
        await security.stop()


# 添加 json 导入
import json


async def main():
    """运行所有示例"""
    print("六层安全防护架构示例")
    print("=" * 60)

    await example_basic_usage()
    await example_monitored_execution()
    await example_custom_validation()
    await example_permission_hooks()
    await example_sandbox()
    await example_audit()
    await example_error_recovery()
    await example_full_integration()

    print("\n" + "=" * 60)
    print("所有示例完成!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
