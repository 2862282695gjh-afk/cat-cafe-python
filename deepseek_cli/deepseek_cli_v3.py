#!/usr/bin/env python3
"""
DeepSeek CLI v3 - 完整六层架构实现

架构:
- 2 调度层: Agent主循环 + 消息队列
- 2 执行层: 工具引擎 + 并发控制
- 2 管理层: 上下文压缩 + SubAgent

特性:
- 实时 steering 机制
- 6阶段工具执行管道
- 3层记忆系统
- 智能上下文压缩
"""
import os
import sys
import json
import asyncio
import argparse
import time
import signal
from typing import AsyncGenerator, Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deepseek_cli.api_client import DeepSeekClient
from deepseek_cli.orchestrator import Orchestrator, LoopState
from deepseek_cli.memory import MemoryManager
from deepseek_cli.tool_engine import ToolEngine
from deepseek_cli.environment import EnvironmentLayer
from deepseek_cli.prompt_engine import PromptAugmentationEngine


# 默认系统提示词
DEFAULT_SYSTEM_PROMPT = """你是 DeepSeek CLI，一个强大的 AI 编程助手。

## 核心能力
你是一个具有完整记忆系统的智能助手，能够：
- 记住之前的对话和决策
- 理解项目上下文
- 执行复杂的编程任务

## 工作模式
采用 Think → Act → Observe 循环：
1. 思考：分析问题，制定计划
2. 行动：执行工具调用
3. 观察：分析结果，决定下一步

## 可用工具
- Read: 读取文件内容
- Write: 写入文件
- Edit: 编辑文件
- Bash: 执行命令
- Glob: 查找文件
- Grep: 搜索内容

## 安全机制
- 危险操作需要确认
- 文件操作有权限检查
- 命令执行有超时限制

## 注意事项
- 复杂任务分解为小步骤
- 遇到错误时调整策略
- 保持代码风格一致
"""


class DeepSeekCLIv3:
    """
    DeepSeek CLI v3 - 完整六层架构
    """

    def __init__(
        self,
        api_key: str = None,
        base_url: str = None,
        model: str = "deepseek-chat",
        working_dir: str = None,
        max_iterations: int = 50,
        max_tokens: int = 128000,
        compression_threshold: float = 0.92
    ):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        self.base_url = base_url or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        self.model = model
        self.working_dir = working_dir or os.getcwd()

        # 初始化环境层
        self.environment = EnvironmentLayer(working_dir=self.working_dir)

        # 初始化工具
        self.tools = self._init_tools()

        # 初始化提示词增强引擎
        self.prompt_engine = PromptAugmentationEngine(working_dir=self.working_dir)

        # 初始化 LLM 客户端
        self.client = DeepSeekClient(self.api_key, self.base_url)

        # 初始化协调器
        self.orchestrator = Orchestrator(
            llm_client=self.client,
            tools=self.tools,
            working_dir=self.working_dir,
            max_iterations=max_iterations,
            max_tokens=max_tokens,
            compression_threshold=compression_threshold,
            on_state_change=self._on_state_change
        )

        # 中断信号
        self.interrupted = False
        self._setup_signal_handlers()

    def _setup_signal_handlers(self):
        """设置信号处理器"""
        def handler(signum, frame):
            print("\n[Interrupt] 收到中断信号，正在停止...")
            self.interrupted = True

        signal.signal(signal.SIGINT, handler)

    def _on_state_change(self, state: LoopState, message: str):
        """状态变化回调"""
        pass  # 可以在外部重写

    def _init_tools(self) -> Dict:
        """初始化工具函数"""
        return {
            "Read": self._tool_read,
            "Write": self._tool_write,
            "Edit": self._tool_edit,
            "Bash": self._tool_bash,
            "Glob": self._tool_glob,
            "Grep": self._tool_grep
        }

    async def _tool_read(self, tool_call) -> str:
        """Read 工具"""
        args = tool_call.arguments
        result, success = self.environment.read_file(
            args.get("file_path"),
            args.get("offset", 1) - 1,  # 转换为 0-indexed
            args.get("limit", 2000)
        )
        return result

    async def _tool_write(self, tool_call) -> str:
        """Write 工具"""
        args = tool_call.arguments
        result, success = self.environment.write_file(
            args.get("file_path"),
            args.get("content")
        )
        return result

    async def _tool_edit(self, tool_call) -> str:
        """Edit 工具"""
        args = tool_call.arguments
        result, success, count = self.environment.edit_file(
            args.get("file_path"),
            args.get("old_string"),
            args.get("new_string"),
            args.get("replace_all", False)
        )
        return result

    async def _tool_bash(self, tool_call) -> str:
        """Bash 工具"""
        args = tool_call.arguments
        result = await self.environment.execute_command(
            args.get("command"),
            args.get("timeout", 120000)
        )
        output = result.stdout
        if result.stderr:
            output += f"\n[stderr]\n{result.stderr}"
        if result.exit_code != 0:
            output += f"\n[exit code: {result.exit_code}]"
        return output or "(no output)"

    async def _tool_glob(self, tool_call) -> str:
        """Glob 工具"""
        args = tool_call.arguments
        import glob
        pattern = args.get("pattern")
        path = args.get("path") or self.working_dir

        matches = glob.glob(os.path.join(path, pattern), recursive=True)
        if not matches:
            return f"No files matching: {pattern}"

        return '\n'.join(
            os.path.relpath(m, path) for m in sorted(matches)[:100]
        )

    async def _tool_grep(self, tool_call) -> str:
        """Grep 工具"""
        args = tool_call.arguments
        results = self.environment.search_content(
            args.get("pattern"),
            args.get("path", "."),
            output_mode=args.get("output_mode", "content")
        )

        if not results:
            return "No matches found"

        if isinstance(results[0], dict) and "error" in results[0]:
            return results[0]["error"]

        return '\n'.join(
            f"{r['file']}:{r['line']}: {r['content'][:100]}"
            for r in results[:50]
        )

    async def run(
        self,
        prompt: str,
        system_prompt: str = None,
        verbose: bool = False,
        stream_json: bool = True
    ) -> AsyncGenerator[Dict, None]:
        """
        运行 DeepSeek CLI v3
        """
        self.verbose = verbose

        # 分析项目上下文
        if verbose:
            print("[DeepSeek v3] 分析项目上下文...", file=sys.stderr)

        self.prompt_engine.analyze_project()

        # 构建增强的系统提示词
        base_system = system_prompt or DEFAULT_SYSTEM_PROMPT
        augmented_system = self.prompt_engine.build_system_prompt(
            base_system,
            include_project_context=True,
            include_git_info=True,
            include_directory_structure=True
        )

        # 执行主循环
        async for event in self.orchestrator.run(prompt, augmented_system):
            if self.interrupted:
                yield {"type": "interrupted", "message": "User interrupted"}
                break

            # 转换为 stream-json 格式
            if stream_json:
                yield self._format_event(event)
            else:
                yield event

    def _format_event(self, event: Dict) -> Dict:
        """格式化事件为 stream-json 格式"""
        event_type = event.get("type")

        if event_type == "text":
            return {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": event.get("text", "")}]}
            }

        elif event_type == "tool_call_detected":
            tc = event.get("tool", {})
            return {
                "type": "assistant",
                "message": {
                    "content": [{
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": tc.get("function", {}).get("name", ""),
                        "input": json.loads(tc.get("function", {}).get("arguments", "{}"))
                    }]
                }
            }

        elif event_type == "tool_result":
            return {
                "type": "tool_result",
                "tool_name": event.get("name"),
                "content": event.get("result", "")[:2000],
                "success": event.get("success", True)
            }

        elif event_type == "complete":
            return {
                "type": "result",
                "result": event.get("response", ""),
                "usage": {"total_tokens": event.get("stats", {}).get("total_tokens", 0)},
                "stats": event.get("stats")
            }

        elif event_type == "tool_needs_confirmation":
            return {
                "type": "tool_needs_confirmation",
                "tool_call_id": event.get("tool_call_id"),
                "name": event.get("name"),
                "message": event.get("message")
            }

        return event

    def confirm_tool(self, tool_call_id: str) -> bool:
        """确认工具调用"""
        return self.orchestrator.confirm_tool(tool_call_id)

    def deny_tool(self, tool_call_id: str) -> bool:
        """拒绝工具调用"""
        return self.orchestrator.deny_tool(tool_call_id)

    def get_stats(self) -> Dict:
        """获取完整统计"""
        return self.orchestrator.get_stats()


async def main():
    parser = argparse.ArgumentParser(description="DeepSeek CLI v3 - 完整六层架构")
    parser.add_argument("-p", "--prompt", type=str, help="输入提示词")
    parser.add_argument("--system", type=str, help="系统提示词")
    parser.add_argument("--model", type=str, default="deepseek-chat")
    parser.add_argument("--output-format", type=str, default="stream-json")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--working-dir", type=str, help="工作目录")
    parser.add_argument("--max-iterations", type=int, default=50)
    parser.add_argument("--stats", action="store_true", help="运行后显示统计")

    args = parser.parse_args()

    # 获取 prompt
    if args.prompt:
        prompt = args.prompt
    elif not sys.stdin.isatty():
        prompt = sys.stdin.read().strip()
    else:
        parser.print_help()
        sys.exit(1)

    # 检查 API Key
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        print("错误: 请设置 DEEPSEEK_API_KEY 环境变量", file=sys.stderr)
        sys.exit(1)

    # 创建 CLI 实例
    cli = DeepSeekCLIv3(
        api_key=api_key,
        model=args.model,
        working_dir=args.working_dir,
        max_iterations=args.max_iterations
    )

    # 运行
    stream_json = args.output_format == "stream-json"

    async for event in cli.run(
        prompt=prompt,
        system_prompt=args.system,
        verbose=args.verbose,
        stream_json=stream_json
    ):
        if stream_json:
            print(json.dumps(event, ensure_ascii=False), flush=True)
        else:
            if event.get("type") == "text":
                print(event.get("text", ""), end="", flush=True)
            elif event.get("type") == "complete":
                print()

    # 显示统计
    if args.stats:
        stats = cli.get_stats()
        print("\n\n=== 执行统计 ===", file=sys.stderr)
        print(json.dumps(stats, indent=2, ensure_ascii=False), file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
