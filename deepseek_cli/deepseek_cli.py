#!/usr/bin/env python3
"""
DeepSeek CLI - 模拟 Claude CLI 的行为
支持工具调用、流式输出、stream-json 格式
"""
import os
import sys
import json
import asyncio
import argparse
import uuid
import time
from typing import AsyncGenerator, Dict, List, Optional, Any

# 添加父目录到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deepseek_cli.tools import ToolExecutor
from deepseek_cli.api_client import DeepSeekClient


# 默认系统提示词
DEFAULT_SYSTEM_PROMPT = """你是 DeepSeek，一个有用的 AI 助手。

## 工具使用说明
- 你可以使用提供的工具来帮助用户完成任务
- 工具会自动执行，你只需要决定使用哪个工具和参数
- 工具执行结果会返回给你，根据结果继续操作

## 可用工具
- Read: 读取文件内容
- Write: 写入文件
- Edit: 编辑文件
- Bash: 执行 shell 命令
- Glob: 查找文件
- Grep: 搜索文件内容
"""


def get_tools_definition() -> List[Dict]:
    """获取工具定义 (DeepSeek/OpenAI 格式)"""
    return [
        {
            "type": "function",
            "function": {
                "name": "Read",
                "description": "读取文件内容。返回文件的指定行内容。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "要读取的文件的绝对路径"
                        },
                        "offset": {
                            "type": "integer",
                            "description": "起始行号（从1开始），默认为1",
                            "default": 1
                        },
                        "limit": {
                            "type": "integer",
                            "description": "要读取的最大行数",
                            "default": 2000
                        }
                    },
                    "required": ["file_path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "Write",
                "description": "将内容写入文件。如果文件不存在则创建，存在则覆盖。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "要写入的文件的绝对路径"
                        },
                        "content": {
                            "type": "string",
                            "description": "要写入的内容"
                        }
                    },
                    "required": ["file_path", "content"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "Edit",
                "description": "对文件进行字符串替换编辑。old_string 必须在文件中唯一匹配。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "要编辑的文件的绝对路径"
                        },
                        "old_string": {
                            "type": "string",
                            "description": "要被替换的文本"
                        },
                        "new_string": {
                            "type": "string",
                            "description": "替换后的新文本"
                        },
                        "replace_all": {
                            "type": "boolean",
                            "description": "是否替换所有匹配项",
                            "default": False
                        }
                    },
                    "required": ["file_path", "old_string", "new_string"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "Bash",
                "description": "执行 shell 命令。用于运行终端命令如 git、npm、docker 等。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "要执行的 shell 命令"
                        },
                        "timeout": {
                            "type": "integer",
                            "description": "超时时间（毫秒），默认 120000",
                            "default": 120000
                        }
                    },
                    "required": ["command"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "Glob",
                "description": "使用 glob 模式查找文件。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {
                            "type": "string",
                            "description": "Glob 模式，如 **/*.py"
                        },
                        "path": {
                            "type": "string",
                            "description": "搜索目录，默认为当前目录"
                        }
                    },
                    "required": ["pattern"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "Grep",
                "description": "使用正则表达式搜索文件内容。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {
                            "type": "string",
                            "description": "正则表达式模式"
                        },
                        "path": {
                            "type": "string",
                            "description": "搜索路径"
                        },
                        "output_mode": {
                            "type": "string",
                            "description": "输出模式: content, files_with_matches, count",
                            "default": "content"
                        }
                    },
                    "required": ["pattern"]
                }
            }
        }
    ]


class DeepSeekCLI:
    def __init__(self, api_key: str = None, base_url: str = None, model: str = "deepseek-chat"):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        self.base_url = base_url or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        self.model = model
        self.client = DeepSeekClient(self.api_key, self.base_url)
        self.tool_executor = ToolExecutor()
        self.max_tool_calls = 50  # 最大工具调用次数，防止无限循环

    def output_json(self, data: Dict):
        """输出 JSON 行"""
        print(json.dumps(data, ensure_ascii=False), flush=True)

    async def run(self, prompt: str, system_prompt: str = None,
                  verbose: bool = False, stream_json: bool = True) -> AsyncGenerator[Dict, None]:
        """
        运行 DeepSeek 对话

        Args:
            prompt: 用户输入
            system_prompt: 系统提示词
            verbose: 是否显示详细信息
            stream_json: 是否输出 stream-json 格式

        Yields:
            事件字典
        """
        messages = [{"role": "user", "content": prompt}]
        system = system_prompt or DEFAULT_SYSTEM_PROMPT
        tools = get_tools_definition()

        tool_call_count = 0
        full_response = ""
        total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        while tool_call_count < self.max_tool_calls:
            # 调用 API
            if verbose:
                print(f"[DeepSeek] 调用 API (第 {tool_call_count + 1} 轮)", file=sys.stderr)

            response_text = ""
            tool_calls = []

            # 流式处理响应
            async for event in self.client.chat_completion_stream(
                model=self.model,
                messages=messages,
                system=system,
                tools=tools,
                stream=True
            ):
                event_type = event.get("type")

                if event_type == "content_delta":
                    # 文本内容
                    delta = event.get("delta", "")
                    response_text += delta

                    if stream_json:
                        yield {
                            "type": "assistant",
                            "message": {
                                "content": [{"type": "text", "text": delta}]
                            }
                        }

                elif event_type == "tool_call":
                    # 工具调用
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
                    # 使用量统计
                    usage = event.get("usage", {})
                    total_usage["prompt_tokens"] += usage.get("prompt_tokens", 0)
                    total_usage["completion_tokens"] += usage.get("completion_tokens", 0)
                    total_usage["total_tokens"] += usage.get("total_tokens", 0)

            full_response = response_text

            # 如果没有工具调用，结束循环
            if not tool_calls:
                break

            # 添加 assistant 消息
            assistant_message = {"role": "assistant", "content": response_text}
            if tool_calls:
                assistant_message["tool_calls"] = tool_calls
            messages.append(assistant_message)

            # 执行工具并收集结果
            tool_results = []
            for tc in tool_calls:
                tool_call_count += 1
                tool_id = tc.get("id")
                function_name = tc.get("function", {}).get("name")
                arguments = json.loads(tc.get("function", {}).get("arguments", "{}"))

                if verbose:
                    print(f"[DeepSeek] 执行工具: {function_name}({arguments})", file=sys.stderr)

                # 执行工具
                try:
                    result = await self.tool_executor.execute(function_name, arguments)
                except Exception as e:
                    result = f"工具执行错误: {str(e)}"

                if verbose:
                    print(f"[DeepSeek] 工具结果: {result[:200]}...", file=sys.stderr)

                # 输出工具结果
                if stream_json:
                    yield {
                        "type": "tool_result",
                        "tool_name": function_name,
                        "content": result
                    }

                # 添加工具结果到消息
                tool_results.append({
                    "tool_call_id": tool_id,
                    "role": "tool",
                    "name": function_name,
                    "content": result
                })

            # 添加工具结果消息
            messages.extend(tool_results)

        # 输出最终结果
        yield {
            "type": "result",
            "result": full_response,
            "usage": {
                "input_tokens": total_usage["prompt_tokens"],
                "output_tokens": total_usage["completion_tokens"]
            }
        }

        yield {
            "type": "done",
            "response": full_response
        }


async def main():
    parser = argparse.ArgumentParser(description="DeepSeek CLI - 模拟 Claude CLI")
    parser.add_argument("-p", "--prompt", type=str, help="输入提示词")
    parser.add_argument("--system", type=str, help="系统提示词")
    parser.add_argument("--model", type=str, default="deepseek-chat",
                        help="模型名称 (deepseek-chat, deepseek-coder)")
    parser.add_argument("--output-format", type=str, default="stream-json",
                        choices=["stream-json", "text"],
                        help="输出格式")
    parser.add_argument("--verbose", action="store_true", help="显示详细信息")
    parser.add_argument("--api-key", type=str, help="API Key (或设置 DEEPSEEK_API_KEY)")
    parser.add_argument("--base-url", type=str, help="API Base URL")

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
    api_key = args.api_key or os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        print("错误: 请设置 DEEPSEEK_API_KEY 环境变量或使用 --api-key 参数", file=sys.stderr)
        sys.exit(1)

    # 创建 CLI 实例
    cli = DeepSeekCLI(
        api_key=api_key,
        base_url=args.base_url,
        model=args.model
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
            if event["type"] == "content_delta":
                print(event.get("delta", ""), end="", flush=True)
            elif event["type"] == "result":
                print()  # 换行


if __name__ == "__main__":
    asyncio.run(main())
