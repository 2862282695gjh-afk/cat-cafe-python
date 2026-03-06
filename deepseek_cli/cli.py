#!/usr/bin/env python3
"""
DeepSeek CLI 命令行入口
支持安全模式启动
"""
import os
import sys
import asyncio
import argparse
import json
from typing import Optional

# 添加父目录到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="DeepSeek CLI - 安全的 AI 编程助手",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 基本使用
  deepseek-cli -p "帮我读取 README.md 文件"

  # 使用安全模式
  deepseek-cli -p "执行 ls 命令" --security

  # 指定工作目录
  deepseek-cli -p "分析项目结构" --working-dir /path/to/project

  # 查看安全统计
  deepseek-cli --stats
        """
    )

    # 输入参数
    parser.add_argument(
        "-p", "--prompt",
        type=str,
        help="输入提示词"
    )
    parser.add_argument(
        "--system",
        type=str,
        help="自定义系统提示词"
    )

    # 模型配置
    parser.add_argument(
        "--model",
        type=str,
        default="deepseek-chat",
        choices=["deepseek-chat", "deepseek-coder"],
        help="使用的模型 (default: deepseek-chat)"
    )
    parser.add_argument(
        "--api-key",
        type=str,
        help="DeepSeek API Key (或设置 DEEPSEEK_API_KEY 环境变量)"
    )
    parser.add_argument(
        "--base-url",
        type=str,
        help="API Base URL"
    )

    # 工作目录
    parser.add_argument(
        "--working-dir",
        type=str,
        help="工作目录"
    )

    # 输出配置
    parser.add_argument(
        "--output-format",
        type=str,
        default="stream-json",
        choices=["stream-json", "text", "json"],
        help="输出格式 (default: stream-json)"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="显示详细输出"
    )

    # 安全相关
    security_group = parser.add_argument_group("安全选项")
    security_group.add_argument(
        "--security",
        action="store_true",
        help="启用六层安全防护架构"
    )
    security_group.add_argument(
        "--security-level",
        type=str,
        default="standard",
        choices=["none", "basic", "standard", "strict", "maximum"],
        help="安全隔离级别 (default: standard)"
    )
    security_group.add_argument(
        "--no-network",
        action="store_true",
        help="禁用网络访问"
    )
    security_group.add_argument(
        "--timeout",
        type=int,
        default=120000,
        help="执行超时时间（毫秒）(default: 120000)"
    )
    security_group.add_argument(
        "--max-memory",
        type=int,
        default=512,
        help="最大内存使用（MB）(default: 512)"
    )
    security_group.add_argument(
        "--allowed-path",
        action="append",
        help="允许访问的路径（可多次指定）"
    )
    security_group.add_argument(
        "--allowed-domain",
        action="append",
        help="允许访问的域名（可多次指定）"
    )
    security_group.add_argument(
        "--stats",
        action="store_true",
        help="显示安全统计信息"
    )
    security_group.add_argument(
        "--audit",
        action="store_true",
        help="启用审计日志"
    )

    # 配置文件
    parser.add_argument(
        "--config",
        type=str,
        help="配置文件路径 (JSON)"
    )

    return parser.parse_args()


def load_config(config_path: str) -> dict:
    """从文件加载配置"""
    if not os.path.exists(config_path):
        print(f"配置文件不存在: {config_path}", file=sys.stderr)
        return {}

    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


async def run_with_security(args):
    """使用安全架构运行"""
    from deepseek_cli.security import (
        SecurityManager,
        SecurityConfig,
        IsolationLevel,
        create_security_manager
    )

    # 构建安全配置
    isolation_level = {
        "none": IsolationLevel.NONE,
        "basic": IsolationLevel.BASIC,
        "standard": IsolationLevel.STANDARD,
        "strict": IsolationLevel.STRICT,
        "maximum": IsolationLevel.MAXIMUM,
    }.get(args.security_level, IsolationLevel.STANDARD)

    config = SecurityConfig(
        enable_input_validation=True,
        enable_permission_control=True,
        enable_sandbox=args.security,
        enable_monitoring=True,
        enable_error_recovery=True,
        enable_audit=args.audit,
        isolation_level=isolation_level,
        no_network=args.no_network,
        default_timeout_ms=args.timeout,
        max_memory_mb=args.max_memory,
        allowed_paths=args.allowed_path or [],
        allowed_domains=args.allowed_domain or [],
    )

    # 创建安全管理器
    security = SecurityManager(
        config=config,
        working_dir=args.working_dir or os.getcwd()
    )

    await security.start()

    try:
        # 检查执行权限
        # 对于简单提示词，我们使用一个虚拟的工具检查
        check_result = await security.check_execution(
            tool_name="Prompt",
            arguments={"prompt": args.prompt}
        )

        if not check_result.allowed:
            print(f"安全检查未通过: {check_result.reason}", file=sys.stderr)
            return

        if check_result.needs_confirmation:
            print(f"需要确认: {check_result.confirmation_message}", file=sys.stderr)
            response = input("是否继续? (y/n): ")
            if response.lower() != 'y':
                print("操作已取消")
                return

        # 执行 DeepSeek CLI
        from deepseek_cli.deepseek_cli_v3 import DeepSeekCLIv3

        cli = DeepSeekCLIv3(
            api_key=args.api_key,
            base_url=args.base_url,
            model=args.model,
            working_dir=args.working_dir or os.getcwd(),
            max_iterations=50
        )

        # 运行
        async for event in cli.run(
            prompt=args.prompt,
            system_prompt=args.system,
            verbose=args.verbose,
            stream_json=args.output_format == "stream-json"
        ):
            if args.output_format == "stream-json":
                print(json.dumps(event, ensure_ascii=False), flush=True)
            elif args.output_format == "json":
                # 只打印最终结果
                if event.get("type") == "complete":
                    print(json.dumps(event, ensure_ascii=False, indent=2))
            else:
                # 文本格式
                if event.get("type") == "text":
                    print(event.get("text", ""), end="", flush=True)
                elif event.get("type") == "complete":
                    print()  # 换行

        # 显示安全统计
        if args.stats:
            stats = await security.get_stats()
            print("\n\n=== 安全统计 ===", file=sys.stderr)
            print(json.dumps(stats, indent=2, ensure_ascii=False, default=str), file=sys.stderr)

    finally:
        await security.stop()


async def run_without_security(args):
    """不使用安全架构运行（传统模式）"""
    from deepseek_cli.deepseek_cli_v3 import DeepSeekCLIv3

    cli = DeepSeekCLIv3(
        api_key=args.api_key,
        base_url=args.base_url,
        model=args.model,
        working_dir=args.working_dir or os.getcwd(),
        max_iterations=50
    )

    async for event in cli.run(
        prompt=args.prompt,
        system_prompt=args.system,
        verbose=args.verbose,
        stream_json=args.output_format == "stream-json"
    ):
        if args.output_format == "stream-json":
            print(json.dumps(event, ensure_ascii=False), flush=True)
        elif args.output_format == "json":
            if event.get("type") == "complete":
                print(json.dumps(event, ensure_ascii=False, indent=2))
        else:
            if event.get("type") == "text":
                print(event.get("text", ""), end="", flush=True)
            elif event.get("type") == "complete":
                print()


async def main():
    """主函数"""
    args = parse_args()

    # 加载配置文件
    if args.config:
        config = load_config(args.config)
        # 用配置文件覆盖默认值
        for key, value in config.items():
            if hasattr(args, key) and getattr(args, key) is None:
                setattr(args, key, value)

    # 获取 API Key
    api_key = args.api_key or os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        print("错误: 请设置 DEEPSEEK_API_KEY 环境变量或使用 --api-key 参数", file=sys.stderr)
        sys.exit(1)
    args.api_key = api_key

    # 获取 prompt
    if args.prompt:
        pass
    elif not sys.stdin.isatty():
        args.prompt = sys.stdin.read().strip()
    else:
        print("错误: 请提供 prompt 参数 (-p 或 --prompt)", file=sys.stderr)
        sys.exit(1)

    # 根据安全模式选择执行方式
    if args.security or args.audit:
        await run_with_security(args)
    else:
        await run_without_security(args)


def cli_entry():
    """CLI 入口点"""
    asyncio.run(main())


if __name__ == "__main__":
    cli_entry()
