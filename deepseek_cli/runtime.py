"""
Agentic Runtime - Agent 运行时
负责任务规划、执行循环、状态管理
"""
import asyncio
import json
import time
from typing import Dict, List, Optional, Any, AsyncGenerator, Callable
from dataclasses import dataclass, field
from enum import Enum


class AgentState(Enum):
    """Agent 状态"""
    IDLE = "idle"
    THINKING = "thinking"
    ACTING = "acting"
    OBSERVING = "observing"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class Task:
    """任务定义"""
    id: str
    description: str
    status: str = "pending"
    subtasks: List['Task'] = field(default_factory=list)
    result: Optional[str] = None
    error: Optional[str] = None


@dataclass
class ExecutionStep:
    """执行步骤记录"""
    step_number: int
    thought: str
    action: Dict[str, Any]
    observation: str
    timestamp: int


class AgenticRuntime:
    """
    Agent 运行时 - 实现 ReAct (Reasoning + Acting) 循环

    核心循环: Think → Act → Observe → Repeat
    """

    def __init__(
        self,
        max_iterations: int = 50,
        max_tokens_per_iteration: int = 4096,
        timeout_seconds: int = 300,
        on_state_change: Callable[[AgentState, str], None] = None
    ):
        self.max_iterations = max_iterations
        self.max_tokens_per_iteration = max_tokens_per_iteration
        self.timeout_seconds = timeout_seconds
        self.on_state_change = on_state_change

        # 运行时状态
        self.state = AgentState.IDLE
        self.current_task: Optional[Task] = None
        self.execution_history: List[ExecutionStep] = []
        self.context: Dict[str, Any] = {}
        self.iteration_count = 0
        self.total_tokens_used = 0

    def set_state(self, new_state: AgentState, message: str = ""):
        """更新状态并触发回调"""
        old_state = self.state
        self.state = new_state
        if self.on_state_change:
            self.on_state_change(new_state, message)
        print(f"[Runtime] 状态变化: {old_state.value} → {new_state.value} | {message}")

    async def run(
        self,
        task_description: str,
        llm_client: Any,
        tools: List[Dict],
        context: Dict[str, Any] = None
    ) -> AsyncGenerator[Dict, None]:
        """
        执行主循环

        Args:
            task_description: 任务描述
            llm_client: LLM 客户端 (需要有 chat_completion_stream 方法)
            tools: 可用工具列表
            context: 初始上下文

        Yields:
            执行事件
        """
        self.current_task = Task(
            id=f"task-{int(time.time() * 1000)}",
            description=task_description,
            status="running"
        )
        self.context = context or {}
        self.execution_history = []
        self.iteration_count = 0

        messages = [
            {"role": "user", "content": task_description}
        ]

        self.set_state(AgentState.THINKING, "开始思考任务")

        yield {
            "type": "task_start",
            "task_id": self.current_task.id,
            "description": task_description
        }

        try:
            while self.iteration_count < self.max_iterations:
                self.iteration_count += 1

                # ========== THINK 阶段 ==========
                self.set_state(AgentState.THINKING, f"迭代 {self.iteration_count}")

                yield {
                    "type": "iteration_start",
                    "iteration": self.iteration_count,
                    "max_iterations": self.max_iterations
                }

                # 调用 LLM
                response_text = ""
                tool_calls = []
                step_thought = ""

                async for event in llm_client.chat_completion_stream(
                    model=getattr(llm_client, 'model', 'deepseek-chat'),
                    messages=messages,
                    tools=tools,
                    stream=True
                ):
                    if event.get("type") == "content_delta":
                        delta = event.get("delta", "")
                        response_text += delta
                        yield {"type": "text", "text": delta}

                    elif event.get("type") == "tool_call":
                        tool_calls.append(event.get("tool_call"))

                    elif event.get("type") == "usage":
                        self.total_tokens_used += event.get("usage", {}).get("total_tokens", 0)

                # 提取思考内容
                step_thought = response_text

                # ========== ACT 阶段 ==========
                if not tool_calls:
                    # 没有工具调用，任务完成
                    self.set_state(AgentState.COMPLETED, "任务完成")
                    self.current_task.status = "completed"
                    self.current_task.result = response_text

                    yield {
                        "type": "task_complete",
                        "result": response_text,
                        "iterations": self.iteration_count,
                        "tokens_used": self.total_tokens_used
                    }
                    break

                self.set_state(AgentState.ACTING, f"执行 {len(tool_calls)} 个工具")

                # 执行工具调用
                tool_results = []
                for tc in tool_calls:
                    tool_name = tc.get("function", {}).get("name")
                    tool_args = json.loads(tc.get("function", {}).get("arguments", "{}"))

                    yield {
                        "type": "tool_call",
                        "name": tool_name,
                        "arguments": tool_args
                    }

                    # 这里工具执行由外部处理，我们只记录
                    # 实际执行在 tools.py 中

                # 添加 assistant 消息
                assistant_message = {"role": "assistant", "content": response_text}
                if tool_calls:
                    assistant_message["tool_calls"] = tool_calls
                messages.append(assistant_message)

                # ========== OBSERVE 阶段 ==========
                # 工具结果会被添加到 messages，然后在下一轮迭代中处理

                self.set_state(AgentState.OBSERVING, "观察工具执行结果")

                # 记录执行步骤
                step = ExecutionStep(
                    step_number=self.iteration_count,
                    thought=step_thought,
                    action={"tool_calls": tool_calls},
                    observation="",  # 会在外部填充
                    timestamp=int(time.time() * 1000)
                )
                self.execution_history.append(step)

                yield {
                    "type": "iteration_end",
                    "iteration": self.iteration_count
                }

            else:
                # 达到最大迭代次数
                self.set_state(AgentState.ERROR, "达到最大迭代次数")
                yield {
                    "type": "max_iterations_reached",
                    "iterations": self.iteration_count
                }

        except Exception as e:
            self.set_state(AgentState.ERROR, str(e))
            self.current_task.status = "error"
            self.current_task.error = str(e)
            yield {"type": "error", "message": str(e)}

    def get_execution_summary(self) -> Dict:
        """获取执行摘要"""
        return {
            "task_id": self.current_task.id if self.current_task else None,
            "state": self.state.value,
            "iterations": self.iteration_count,
            "tokens_used": self.total_tokens_used,
            "steps": [
                {
                    "step": s.step_number,
                    "thought": s.thought[:200],
                    "action": s.action,
                    "timestamp": s.timestamp
                }
                for s in self.execution_history
            ]
        }

    def should_continue(self) -> bool:
        """判断是否应该继续执行"""
        return (
            self.iteration_count < self.max_iterations and
            self.state not in [AgentState.COMPLETED, AgentState.ERROR]
        )
