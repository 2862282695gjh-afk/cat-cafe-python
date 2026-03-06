"""
主循环协调器 (Orchestrator)
整合六层架构：
- 2 调度层: Agent主循环, 消息队列
- 2 执行层: 工具引擎, 并发控制
- 2 管理层: 上下文压缩, SubAgent
"""
import os
import sys
import json
import asyncio
import time
from typing import Dict, List, Optional, Any, AsyncGenerator, Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

from .memory import MemoryManager
from .tool_engine import ToolEngine, ToolCall, ToolStatus, ExecutionResult


class LoopState(Enum):
    """主循环状态"""
    IDLE = "idle"
    PREPROCESSING = "preprocessing"
    COMPRESSION_CHECK = "compression_check"
    PROMPT_GENERATION = "prompt_generation"
    LLM_CALL = "llm_call"
    TOOL_PROCESSING = "tool_processing"
    RESULT_AGGREGATION = "result_aggregation"
    TERMINATION_CHECK = "termination_check"


@dataclass
class LoopContext:
    """主循环上下文"""
    iteration: int = 0
    max_iterations: int = 50
    total_tokens: int = 0
    tool_calls_count: int = 0
    start_time: float = 0
    state: LoopState = LoopState.IDLE
    last_response: str = ""
    pending_tools: List[ToolCall] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class MessagePreprocessor:
    """消息预处理器"""

    def __init__(self, max_message_length: int = 100000):
        self.max_message_length = max_message_length

    def preprocess(self, message: str) -> Dict:
        """
        消息预处理
        1. 消息验证和清理
        2. Token 使用量评估
        3. 压缩阈值检测
        """
        result = {
            "original": message,
            "cleaned": message,
            "tokens": 0,
            "is_valid": True,
            "warnings": []
        }

        # 1. 验证消息
        if not message or not message.strip():
            result["is_valid"] = False
            result["warnings"].append("Empty message")
            return result

        # 2. 清理消息
        cleaned = message.strip()
        # 移除多余空白
        import re
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)

        if len(cleaned) > self.max_message_length:
            result["warnings"].append(f"Message truncated from {len(cleaned)} to {self.max_message_length}")
            cleaned = cleaned[:self.max_message_length] + "..."

        result["cleaned"] = cleaned

        # 3. 估算 tokens
        chinese_chars = sum(1 for c in cleaned if '\u4e00' <= c <= '\u9fff')
        other_chars = len(cleaned) - chinese_chars
        result["tokens"] = int(chinese_chars / 1.5 + other_chars / 4) + 10

        return result


class ModelFallbackManager:
    """模型降级管理器"""

    def __init__(self, models: List[str] = None):
        self.models = models or ["deepseek-chat", "deepseek-coder"]
        self.current_index = 0
        self.failure_counts: Dict[str, int] = {}
        self.max_failures = 3

    def get_current_model(self) -> str:
        """获取当前模型"""
        return self.models[self.current_index]

    def report_failure(self, model: str, error: str):
        """报告模型失败"""
        self.failure_counts[model] = self.failure_counts.get(model, 0) + 1

        if self.failure_counts[model] >= self.max_failures:
            self._fallback()

    def _fallback(self):
        """降级到下一个模型"""
        if self.current_index < len(self.models) - 1:
            self.current_index += 1
            print(f"[ModelFallback] 降级到模型: {self.models[self.current_index]}")
        else:
            print("[ModelFallback] 已是最后一个模型，无法降级")


class Orchestrator:
    """
    主循环协调器

    执行流程:
    1. 消息预处理和上下文检查
    2. 压缩判断
    3. 系统提示生成
    4. 对话生成
    5. 对话管道处理
    6. 工具调用检测和解析
    7. 工具发现、验证、权限、调度、执行
    8. 结果聚合和状态更新
    9. 循环判断
    """

    def __init__(
        self,
        llm_client: Any,
        tools: Dict[str, Callable],
        working_dir: str = None,
        max_iterations: int = 50,
        max_tokens: int = 128000,
        compression_threshold: float = 0.92,
        on_state_change: Callable[[LoopState, str], None] = None
    ):
        self.llm_client = llm_client
        self.working_dir = working_dir or os.getcwd()

        # 初始化各层组件
        self.memory = MemoryManager(
            max_tokens=max_tokens,
            compression_threshold=compression_threshold,
            project_path=self.working_dir
        )
        self.tool_engine = ToolEngine(tools)
        self.preprocessor = MessagePreprocessor()
        self.model_fallback = ModelFallbackManager()

        # 循环状态
        self.ctx = LoopContext(max_iterations=max_iterations)
        self.on_state_change = on_state_change

        # 工具定义（用于 LLM）
        self.tool_definitions = self._build_tool_definitions()

    def _build_tool_definitions(self) -> List[Dict]:
        """构建工具定义"""
        return [
            {
                "type": "function",
                "function": {
                    "name": "Read",
                    "description": "读取文件内容",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string"},
                            "offset": {"type": "integer", "default": 1},
                            "limit": {"type": "integer", "default": 2000}
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
                            "file_path": {"type": "string"},
                            "content": {"type": "string"}
                        },
                        "required": ["file_path", "content"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "Edit",
                    "description": "编辑文件",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string"},
                            "old_string": {"type": "string"},
                            "new_string": {"type": "string"},
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
                    "description": "执行命令",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {"type": "string"},
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
                            "pattern": {"type": "string"},
                            "path": {"type": "string"}
                        },
                        "required": ["pattern"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "Grep",
                    "description": "搜索内容",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "pattern": {"type": "string"},
                            "path": {"type": "string"},
                            "output_mode": {"type": "string", "default": "content"}
                        },
                        "required": ["pattern"]
                    }
                }
            }
        ]

    def _set_state(self, state: LoopState, message: str = ""):
        """更新状态"""
        self.ctx.state = state
        if self.on_state_change:
            self.on_state_change(state, message)
        print(f"[Orchestrator] {state.value}: {message}")

    async def run(self, user_input: str, system_prompt: str = None) -> AsyncGenerator[Dict, None]:
        """
        执行主循环
        """
        self.ctx = LoopContext(
            max_iterations=self.ctx.max_iterations,
            start_time=time.time()
        )

        # ========== Phase 1: 预处理 ==========
        self._set_state(LoopState.PREPROCESSING, "消息预处理")

        preprocessed = self.preprocessor.preprocess(user_input)
        if not preprocessed["is_valid"]:
            yield {"type": "error", "message": "Invalid input"}
            return

        # 添加到记忆
        self.memory.add_message("user", preprocessed["cleaned"])

        yield {"type": "preprocessing", "tokens": preprocessed["tokens"]}

        # ========== Phase 2: 压缩检查 ==========
        self._set_state(LoopState.COMPRESSION_CHECK, "检查上下文")

        if self.memory.short_term.should_compress():
            yield {"type": "compression_triggered", "usage": self.memory.short_term.get_token_usage()}

        # ========== 主循环 ==========
        while self.ctx.iteration < self.ctx.max_iterations:
            self.ctx.iteration += 1

            yield {"type": "iteration_start", "iteration": self.ctx.iteration}

            # ========== Phase 3: 系统提示生成 ==========
            self._set_state(LoopState.PROMPT_GENERATION, f"迭代 {self.ctx.iteration}")

            context = self.memory.get_context_for_prompt()
            enhanced_system = self._build_system_prompt(system_prompt, context)

            # ========== Phase 4: LLM 调用 ==========
            self._set_state(LoopState.LLM_CALL, "调用 LLM")

            messages = self.memory.get_messages_for_api()
            response_text = ""
            tool_calls = []

            try:
                async for event in self._call_llm(enhanced_system, messages):
                    if event["type"] == "text":
                        response_text += event["text"]
                        yield {"type": "text", "text": event["text"]}

                    elif event["type"] == "tool_call":
                        tool_calls.append(event["tool_call"])
                        yield {"type": "tool_call_detected", "tool": event["tool_call"]}

                    elif event["type"] == "usage":
                        self.ctx.total_tokens += event.get("total_tokens", 0)

            except Exception as e:
                self.ctx.errors.append(str(e))
                self.model_fallback.report_failure(self.model_fallback.get_current_model(), str(e))
                yield {"type": "error", "message": str(e)}

                # 尝试降级
                if self.model_fallback.current_index < len(self.model_fallback.models) - 1:
                    continue
                else:
                    break

            self.ctx.last_response = response_text

            # ========== Phase 5: 工具处理 ==========
            if not tool_calls:
                # 没有工具调用，结束循环
                self._set_state(LoopState.TERMINATION_CHECK, "无工具调用，结束")

                # 保存助手消息
                self.memory.add_message("assistant", response_text)

                yield {"type": "response_complete", "response": response_text}
                break

            self._set_state(LoopState.TOOL_PROCESSING, f"处理 {len(tool_calls)} 个工具调用")

            # 保存助手消息
            self.memory.add_message("assistant", response_text, {"tool_calls": tool_calls})

            # ========== Phase 6: 工具执行 ==========
            tool_results = []
            for tc in tool_calls:
                tool_call = ToolCall(
                    id=tc.get("id", f"tc-{int(time.time() * 1000)}"),
                    name=tc.get("function", {}).get("name"),
                    arguments=json.loads(tc.get("function", {}).get("arguments", "{}"))
                )

                yield {"type": "tool_start", "name": tool_call.name, "arguments": tool_call.arguments}

                try:
                    result = await self.tool_engine.execute(tool_call)

                    if result.needs_confirmation:
                        yield {
                            "type": "tool_needs_confirmation",
                            "tool_call_id": tool_call.id,
                            "name": tool_call.name,
                            "message": result.output
                        }
                        # 等待用户确认（在外部处理）
                        break

                    tool_results.append(result)
                    self.ctx.tool_calls_count += 1

                    yield {
                        "type": "tool_result",
                        "tool_call_id": tool_call.id,
                        "name": tool_call.name,
                        "result": result.output,
                        "success": result.success
                    }

                    # 添加到记忆
                    self.memory.add_message("tool", result.output, {
                        "tool_call_id": tool_call.id,
                        "tool_name": tool_call.name
                    })

                except Exception as e:
                    yield {"type": "tool_error", "name": tool_call.name, "error": str(e)}
                    self.memory.add_message("tool", f"Error: {str(e)}", {
                        "tool_call_id": tool_call.id,
                        "tool_name": tool_call.name,
                        "error": True
                    })

            # ========== Phase 7: 结果聚合 ==========
            self._set_state(LoopState.RESULT_AGGREGATION, "聚合结果")

            # 检查是否需要继续
            yield {"type": "iteration_end", "iteration": self.ctx.iteration}

        # ========== 循环结束 ==========
        self._set_state(LoopState.TERMINATION_CHECK, "主循环结束")

        # 保存会话
        self.memory.save_session()

        duration_ms = int((time.time() - self.ctx.start_time) * 1000)

        yield {
            "type": "complete",
            "response": self.ctx.last_response,
            "stats": {
                "iterations": self.ctx.iteration,
                "tool_calls": self.ctx.tool_calls_count,
                "total_tokens": self.ctx.total_tokens,
                "duration_ms": duration_ms,
                "errors": len(self.ctx.errors)
            }
        }

    async def _call_llm(self, system: str, messages: List[Dict]) -> AsyncGenerator[Dict, None]:
        """调用 LLM"""
        model = self.model_fallback.get_current_model()

        async for event in self.llm_client.chat_completion_stream(
            model=model,
            messages=messages,
            system=system,
            tools=self.tool_definitions,
            stream=True
        ):
            yield event

    def _build_system_prompt(self, base_prompt: str, context: str) -> str:
        """构建系统提示"""
        parts = []

        if base_prompt:
            parts.append(base_prompt)

        if context:
            parts.append(f"\n## 上下文\n{context}")

        parts.append(f"\n## 当前时间\n{datetime.now().isoformat()}")

        return '\n'.join(parts)

    def confirm_tool(self, tool_call_id: str) -> bool:
        """确认工具调用"""
        # 找到对应的 tool call
        for tc in self.ctx.pending_tools:
            if tc.id == tool_call_id:
                self.tool_engine.approve_tool(tc)
                return True
        return False

    def deny_tool(self, tool_call_id: str) -> bool:
        """拒绝工具调用"""
        for tc in self.ctx.pending_tools:
            if tc.id == tool_call_id:
                self.tool_engine.deny_tool(tc)
                return True
        return False

    def get_stats(self) -> Dict:
        """获取统计"""
        return {
            "loop": {
                "iteration": self.ctx.iteration,
                "state": self.ctx.state.value,
                "tool_calls": self.ctx.tool_calls_count,
                "total_tokens": self.ctx.total_tokens
            },
            "memory": self.memory.get_stats(),
            "tools": self.tool_engine.get_stats()
        }
