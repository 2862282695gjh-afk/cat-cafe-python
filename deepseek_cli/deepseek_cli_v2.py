#!/usr/bin/env python3
"""
DeepSeek CLI - 完整四层架构实现
1. Agentic Runtime - Agent 运行时
2. Prompt Augmentation Engine - 提示词增强
3. Skills/Sub-agents - 技能与子代理
4. Environment Interaction Layer - 环境交互
"""
import os
import sys
import json
import asyncio
import argparse
import time
from typing import AsyncGenerator, Dict, List, Optional

# 添加父目录到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deepseek_cli.api_client import DeepSeekClient
from deepseek_cli.runtime import AgenticRuntime, AgentState
from deepseek_cli.prompt_engine import PromptAugmentationEngine, DynamicPromptBuilder
from deepseek_cli.skills import SkillRegistry, SubAgentManager
from deepseek_cli.environment import EnvironmentLayer
from deepseek_cli.tools import ToolExecutor


# 默认系统提示词
DEFAULT_SYSTEM_PROMPT = """你是 DeepSeek CLI，一个强大的 AI 编程助手。

## 核心能力
- 代码分析与理解
- 文件读写与编辑
- Shell 命令执行
- 项目结构分析

## 工作模式
你会按照 Think → Act → Observe 循环工作：
1. 思考：分析问题，制定计划
2. 行动：执行工具调用
3. 观察：分析结果，决定下一步

## 工具使用
- Read: 读取文件内容
- Write: 写入文件
- Edit: 编辑文件
- Bash: 执行命令
- Glob: 查找文件
- Grep: 搜索内容

## 技能系统
你可以调用专门技能：
- code_review: 代码审查
- test_generation: 测试生成
- refactoring: 重构建议
- documentation: 文档生成
- git_analysis: Git 分析

## 注意事项
- 先思考再行动
- 复杂任务分解为小步骤
- 遇到错误时调整策略
"""


class DeepSeekCLIv2:
    """
    DeepSeek CLI v2 - 完整四层架构
    """

    def __init__(
        self,
        api_key: str = None,
        base_url: str = None,
        model: str = "deepseek-chat",
        working_dir: str = None
    ):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        self.base_url = base_url or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        self.model = model
        self.working_dir = working_dir or os.getcwd()

        # 初始化四个层级
        self._init_layers()

    def _init_layers(self):
        """初始化四层架构"""
        # Layer 4: Environment Interaction
        self.environment = EnvironmentLayer(working_dir=self.working_dir)

        # Layer 3: Skills & Sub-agents
        self.skill_registry = SkillRegistry()
        self.subagent_manager = SubAgentManager()

        # Layer 2: Prompt Augmentation
        self.prompt_engine = PromptAugmentationEngine(working_dir=self.working_dir)
        self.prompt_builder = DynamicPromptBuilder(self.prompt_engine)

        # Layer 1: Agentic Runtime
        self.runtime = AgenticRuntime(
            max_iterations=50,
            on_state_change=self._on_state_change
        )

        # API Client
        self.client = DeepSeekClient(self.api_key, self.base_url)

        # Tool Executor
        self.tool_executor = ToolExecutor(working_dir=self.working_dir)

    def _on_state_change(self, state: AgentState, message: str):
        """状态变化回调"""
        print(f"[{state.value.upper()}] {message}", file=sys.stderr)

    def get_tools_definition(self) -> List[Dict]:
        """获取工具定义"""
        return [
            {
                "type": "function",
                "function": {
                    "name": "Read",
                    "description": "读取文件内容",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string", "description": "文件路径"},
                            "offset": {"type": "integer", "description": "起始行号", "default": 1},
                            "limit": {"type": "integer", "description": "读取行数", "default": 2000}
                        },
                        "required": ["file_path"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "Write",
                    "description": "写入文件",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string", "description": "文件路径"},
                            "content": {"type": "string", "description": "文件内容"}
                        },
                        "required": ["file_path", "content"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "Edit",
                    "description": "编辑文件（字符串替换）",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string", "description": "文件路径"},
                            "old_string": {"type": "string", "description": "要替换的字符串"},
                            "new_string": {"type": "string", "description": "新字符串"},
                            "replace_all": {"type": "boolean", "default": False}
                        },
                        "required": ["file_path", "old_string", "new_string"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "Bash",
                    "description": "执行 shell 命令",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {"type": "string", "description": "命令"},
                            "timeout": {"type": "integer", "default": 120000}
                        },
                        "required": ["command"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "Glob",
                    "description": "查找文件",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "pattern": {"type": "string", "description": "glob 模式"},
                            "path": {"type": "string", "description": "搜索路径"}
                        },
                        "required": ["pattern"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "Grep",
                    "description": "搜索文件内容",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "pattern": {"type": "string", "description": "正则表达式"},
                            "path": {"type": "string"},
                            "output_mode": {"type": "string", "default": "content"}
                        },
                        "required": ["pattern"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "Skill",
                    "description": "调用专门技能",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "skill_name": {"type": "string", "description": "技能名称"},
                            "arguments": {"type": "object", "description": "技能参数"}
                        },
                        "required": ["skill_name"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "ProjectContext",
                    "description": "获取项目上下文信息",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "include_structure": {"type": "boolean", "default": True},
                            "include_git": {"type": "boolean", "default": True}
                        }
                    }
                }
            }
        ]

    async def run(
        self,
        prompt: str,
        system_prompt: str = None,
        verbose: bool = False,
        stream_json: bool = True,
        use_augmentation: bool = True,
        detect_skills: bool = True
    ) -> AsyncGenerator[Dict, None]:
        """
        运行 DeepSeek CLI

        Args:
            prompt: 用户输入
            system_prompt: 系统提示词
            verbose: 详细输出
            stream_json: JSON 流式输出
            use_augmentation: 是否使用提示词增强
            detect_skills: 是否自动检测技能
        """
        # 1. 分析项目上下文
        if verbose:
            print("[DeepSeek] 分析项目上下文...", file=sys.stderr)

        self.prompt_engine.analyze_project()

        # 2. 检测技能
        if detect_skills:
            matching_skills = self.skill_registry.find_matching_skills(prompt)
            if matching_skills and verbose:
                for skill in matching_skills:
                    print(f"[DeepSeek] 检测到技能: {skill.name}", file=sys.stderr)

        # 3. 构建增强的提示词
        base_system = system_prompt or DEFAULT_SYSTEM_PROMPT

        if use_augmentation:
            augmented_system = self.prompt_engine.build_system_prompt(base_system)
            relevant_code = self.prompt_engine.extract_relevant_code(prompt)
        else:
            augmented_system = base_system
            relevant_code = ""

        # 4. 构建消息
        user_content = prompt
        if relevant_code:
            user_content = f"{relevant_code}\n\n---\n\n{prompt}"

        messages = [{"role": "user", "content": user_content}]
        tools = self.get_tools_definition()

        # 5. 执行循环
        tool_call_count = 0
        max_tool_calls = 50
        full_response = ""
        total_usage = {"input_tokens": 0, "output_tokens": 0}

        while tool_call_count < max_tool_calls:
            if verbose:
                print(f"[DeepSeek] 调用 API (轮次 {tool_call_count + 1})", file=sys.stderr)

            response_text = ""
            tool_calls = []

            # 流式调用 API
            async for event in self.client.chat_completion_stream(
                model=self.model,
                messages=messages,
                system=augmented_system,
                tools=tools,
                stream=True
            ):
                event_type = event.get("type")

                if event_type == "content_delta":
                    delta = event.get("delta", "")
                    response_text += delta

                    if stream_json:
                        yield {
                            "type": "assistant",
                            "message": {"content": [{"type": "text", "text": delta}]}
                        }

                elif event_type == "tool_call":
                    tool_calls.append(event.get("tool_call"))

                    if stream_json:
                        tc = event.get("tool_call")
                        yield {
                            "type": "assistant",
                            "message": {
                                "content": [{
                                    "type": "tool_use",
                                    "id": tc.get("id"),
                                    "name": tc.get("function", {}).get("name"),
                                    "input": json.loads(tc.get("function", {}).get("arguments", "{}"))
                                }]
                            }
                        }

                elif event_type == "usage":
                    usage = event.get("usage", {})
                    total_usage["input_tokens"] += usage.get("prompt_tokens", 0)
                    total_usage["output_tokens"] += usage.get("completion_tokens", 0)

            full_response = response_text

            # 没有工具调用，结束
            if not tool_calls:
                break

            # 添加 assistant 消息
            assistant_message = {"role": "assistant", "content": response_text, "tool_calls": tool_calls}
            messages.append(assistant_message)

            # 执行工具
            tool_results = []
            for tc in tool_calls:
                tool_call_count += 1
                tool_id = tc.get("id")
                func = tc.get("function", {})
                func_name = func.get("name")
                func_args = json.loads(func.get("arguments", "{}"))

                if verbose:
                    print(f"[DeepSeek] 执行工具: {func_name}", file=sys.stderr)

                # 特殊工具处理
                if func_name == "Skill":
                    result = await self._execute_skill(func_args)
                elif func_name == "ProjectContext":
                    result = self._get_project_context(func_args)
                else:
                    result = await self.tool_executor.execute(func_name, func_args)

                if stream_json:
                    yield {
                        "type": "tool_result",
                        "tool_name": func_name,
                        "content": result[:2000] if len(result) > 2000 else result
                    }

                tool_results.append({
                    "tool_call_id": tool_id,
                    "role": "tool",
                    "name": func_name,
                    "content": result[:4000]  # 限制长度
                })

            messages.extend(tool_results)

        # 输出最终结果
        yield {
            "type": "result",
            "result": full_response,
            "usage": total_usage
        }

        yield {
            "type": "done",
            "response": full_response
        }

    async def _execute_skill(self, args: Dict) -> str:
        """执行技能"""
        skill_name = args.get("skill_name")
        skill_args = args.get("arguments", {})

        skill = self.skill_registry.get(skill_name)
        if not skill:
            return f"未知技能: {skill_name}"

        context = {
            "working_dir": self.working_dir,
            "current_file": skill_args.get("file")
        }

        result = await skill.execute(context, **skill_args)
        return json.dumps({
            "success": result.success,
            "output": result.output,
            "suggestions": result.suggestions
        }, ensure_ascii=False)

    def _get_project_context(self, args: Dict) -> str:
        """获取项目上下文"""
        include_structure = args.get("include_structure", True)
        include_git = args.get("include_git", True)

        ctx = self.prompt_engine.project_context
        if not ctx:
            return "项目上下文未初始化"

        parts = [f"语言: {ctx.language}"]
        if ctx.framework != "unknown":
            parts.append(f"框架: {ctx.framework}")

        if include_git and ctx.has_git:
            parts.append(f"分支: {ctx.git_branch}")
            if ctx.git_status:
                parts.append(f"状态:\n{ctx.git_status}")

        if include_structure and ctx.directory_structure:
            parts.append(f"\n目录结构:\n{ctx.directory_structure}")

        return '\n'.join(parts)


async def main():
    parser = argparse.ArgumentParser(description="DeepSeek CLI v2 - 四层架构")
    parser.add_argument("-p", "--prompt", type=str, help="输入提示词")
    parser.add_argument("--system", type=str, help="系统提示词")
    parser.add_argument("--model", type=str, default="deepseek-chat")
    parser.add_argument("--output-format", type=str, default="stream-json")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--no-augmentation", action="store_true", help="禁用提示词增强")
    parser.add_argument("--no-skill-detection", action="store_true", help="禁用技能检测")
    parser.add_argument("--working-dir", type=str, help="工作目录")
    parser.add_argument("--list-skills", action="store_true", help="列出所有技能")

    args = parser.parse_args()

    # 列出技能
    if args.list_skills:
        registry = SkillRegistry()
        print("可用技能:")
        for skill in registry.list_skills():
            print(f"  - {skill['name']}: {skill['description']}")
            print(f"    触发词: {', '.join(skill['triggers'])}")
        return

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
    cli = DeepSeekCLIv2(
        api_key=api_key,
        model=args.model,
        working_dir=args.working_dir
    )

    # 运行
    stream_json = args.output_format == "stream-json"

    async for event in cli.run(
        prompt=prompt,
        system_prompt=args.system,
        verbose=args.verbose,
        stream_json=stream_json,
        use_augmentation=not args.no_augmentation,
        detect_skills=not args.no_skill_detection
    ):
        if stream_json:
            print(json.dumps(event, ensure_ascii=False), flush=True)
        else:
            if event["type"] == "text":
                print(event.get("text", ""), end="", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
