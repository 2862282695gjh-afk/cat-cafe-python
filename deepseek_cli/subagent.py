"""
SubAgent 架构 - 完整的子代理系统

Task 工具执行流程:

1. 准备阶段 (cx="task"):
   - 用户任务描述解析
   - SubAgent 环境准备
   - 工具集合配置

2. SubAgent 实例化:
   - 新的 Agent 实例创建
   - 独立执行环境
   - 隔离权限管理
   - 专用工具子集

3. CN5 Schema 输出验证:
   - 生成 description: 任务简短描述（3-5词）
   - 生成 prompt: 详细任务执行指令

4. SubAgent 独立执行:
   - 独立的 Agent 主循环实例
   - 专用消息队列
   - 隔离的工具权限
   - 独立错误处理

5. 结果返回主 Agent:
   - 单一消息返回机制
   - 无状态通信模式
   - 结果摘要生成
"""
import os
import json
import asyncio
import time
import hashlib
import re
from typing import Dict, List, Optional, Any, AsyncGenerator, Callable, Type
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod
from datetime import datetime
from queue import Queue
from threading import Lock


# ============================================================================
# 枚举和数据类
# ============================================================================

class SubAgentType(Enum):
    """SubAgent 类型"""
    GENERAL_PURPOSE = "general-purpose"   # 通用
    EXPLORE = "Explore"                   # 代码探索
    BASH = "Bash"                         # 命令执行专用
    PLAN = "Plan"                         # 架构规划
    CLAUDE_CODE_GUIDE = "claude-code-guide"  # Claude Code 使用指南


class SubAgentStatus(Enum):
    """SubAgent 状态"""
    IDLE = "idle"
    PREPARING = "preparing"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskContext:
    """任务上下文 (cx="task")"""
    # 用户任务描述
    user_prompt: str
    parsed_intent: str = ""
    task_type: str = ""

    # SubAgent 环境准备
    working_dir: str = ""
    env_vars: Dict[str, str] = field(default_factory=dict)

    # 工具集合配置
    allowed_tools: List[str] = field(default_factory=list)
    tool_permissions: Dict[str, str] = field(default_factory=dict)  # tool -> allow/delay/ask

    # 执行约束
    max_iterations: int = 10
    timeout_ms: int = 120000
    max_tokens: int = 32000


@dataclass
class SubAgentInstance:
    """SubAgent 实例"""
    id: str
    agent_type: SubAgentType
    status: SubAgentStatus = SubAgentStatus.IDLE

    # 独立执行环境
    message_queue: "asyncio.Queue" = field(default_factory=lambda: asyncio.Queue())
    context: Optional[TaskContext] = None

    # 隔离权限管理
    approved_tools: set = field(default_factory=set)
    denied_tools: set = field(default_factory=set)

    # 专用工具子集
    tools: Dict[str, Callable] = field(default_factory=dict)

    # 执行结果
    result: str = ""
    error: Optional[str] = None
    start_time: float = 0
    end_time: float = 0


@dataclass
class CN5Schema:
    """
    CN5 Schema 输出验证
    用于规范化 Task 工具的输出
    """
    # 任务简短描述 (3-5词)
    description: str
    # 详细任务执行指令
    prompt: str
    # 子代理类型
    subagent_type: SubAgentType
    # 模型选择
    model: str = "deepseek-chat"
    # 执行约束
    max_iterations: int = 10


@dataclass
class SubAgentResult:
    """SubAgent 执行结果"""
    # 单一消息返回
    message: str
    # 结果摘要
    summary: str
    # 执行是否成功
    success: bool
    # 执行统计
    iterations: int = 0
    tool_calls: int = 0
    tokens_used: int = 0
    duration_ms: int = 0
    # 附加信息
    artifacts: Dict[str, Any] = field(default_factory=dict)


# ============================================================================
# 阶段1: 准备阶段 - TaskPreparer
# ============================================================================

class TaskPreparer:
    """
    任务准备器
    阶段1: 准备阶段 (cx="task")

    职责:
    - 用户任务描述解析
    - SubAgent 环境准备
    - 工具集合配置
    """

    # SubAgent 类型对应的默认工具集
    DEFAULT_TOOL_SETS = {
        SubAgentType.GENERAL_PURPOSE: [
            "Read", "Write", "Edit", "Glob", "Grep", "Bash", "LS"
        ],
        SubAgentType.EXPLORE: [
            "Read", "Glob", "Grep", "LS"
        ],
        SubAgentType.BASH: [
            "Bash", "Read", "Glob"
        ],
        SubAgentType.PLAN: [
            "Read", "Glob", "Grep", "LS"
        ],
        SubAgentType.CLAUDE_CODE_GUIDE: [
            "Read", "Glob", "Grep"
        ],
    }

    @classmethod
    def prepare(cls, user_prompt: str, **kwargs) -> TaskContext:
        """
        准备任务上下文

        Args:
            user_prompt: 用户任务描述
            **kwargs: 额外参数

        Returns:
            TaskContext: 完整的任务上下文
        """
        # 1. 解析用户任务描述
        parsed_intent = cls._parse_intent(user_prompt)
        task_type = cls._detect_task_type(user_prompt)

        # 2. 准备环境
        working_dir = kwargs.get("working_dir", os.getcwd())
        env_vars = kwargs.get("env_vars", {})

        # 3. 配置工具集合
        subagent_type = cls._determine_subagent_type(user_prompt, task_type)
        allowed_tools = kwargs.get("allowed_tools") or cls.DEFAULT_TOOL_SETS.get(subagent_type, [])

        # 4. 配置工具权限
        tool_permissions = cls._configure_tool_permissions(allowed_tools, subagent_type)

        return TaskContext(
            user_prompt=user_prompt,
            parsed_intent=parsed_intent,
            task_type=task_type,
            working_dir=working_dir,
            env_vars=env_vars,
            allowed_tools=allowed_tools,
            tool_permissions=tool_permissions,
            max_iterations=kwargs.get("max_iterations", 10),
            timeout_ms=kwargs.get("timeout_ms", 120000),
            max_tokens=kwargs.get("max_tokens", 32000),
        )

    @staticmethod
    def _parse_intent(prompt: str) -> str:
        """解析用户意图"""
        # 提取关键动作词
        action_patterns = [
            (r"(查找|搜索|find|search)", "搜索"),
            (r"(修改|编辑|edit|modify|change)", "编辑"),
            (r"(创建|新建|create|new|write)", "创建"),
            (r"(分析|analyze|审查|review)", "分析"),
            (r"(运行|执行|run|execute)", "执行"),
            (r"(解释|explain|说明)", "解释"),
            (r"(规划|设计|plan|design)", "规划"),
        ]

        for pattern, action in action_patterns:
            if re.search(pattern, prompt, re.IGNORECASE):
                return action

        return "综合处理"

    @staticmethod
    def _detect_task_type(prompt: str) -> str:
        """检测任务类型"""
        type_keywords = {
            "code_review": ["review", "审查", "检查代码"],
            "test": ["test", "测试", "单元测试"],
            "refactor": ["refactor", "重构", "优化"],
            "explore": ["explore", "探索", "了解", "分析代码库"],
            "document": ["document", "文档", "注释"],
            "debug": ["debug", "调试", "排查", "错误"],
            "implement": ["implement", "实现", "编写", "开发"],
        }

        prompt_lower = prompt.lower()
        for task_type, keywords in type_keywords.items():
            if any(kw in prompt_lower for kw in keywords):
                return task_type

        return "general"

    @staticmethod
    def _determine_subagent_type(prompt: str, task_type: str) -> SubAgentType:
        """确定 SubAgent 类型"""
        # 根据任务类型映射
        type_mapping = {
            "explore": SubAgentType.EXPLORE,
            "code_review": SubAgentType.EXPLORE,
            "document": SubAgentType.EXPLORE,
            "debug": SubAgentType.BASH,
            "test": SubAgentType.BASH,
        }

        if task_type in type_mapping:
            return type_mapping[task_type]

        # 检查关键词
        prompt_lower = prompt.lower()
        if "explor" in prompt_lower or "了解" in prompt_lower or "分析代码库" in prompt_lower:
            return SubAgentType.EXPLORE
        if "plan" in prompt_lower or "规划" in prompt_lower or "设计" in prompt_lower:
            return SubAgentType.PLAN
        if "claude code" in prompt_lower or "claude-code" in prompt_lower:
            return SubAgentType.CLAUDE_CODE_GUIDE

        return SubAgentType.GENERAL_PURPOSE

    @classmethod
    def _configure_tool_permissions(
        cls,
        tools: List[str],
        subagent_type: SubAgentType
    ) -> Dict[str, str]:
        """配置工具权限"""
        permissions = {}

        # 安全工具自动允许
        safe_tools = {"Read", "Glob", "Grep", "LS", "WebFetch", "WebSearch", "NotebookRead"}

        for tool in tools:
            if tool in safe_tools:
                permissions[tool] = "allow"
            elif tool == "Bash":
                # Bash 命令需要延迟确认
                if subagent_type == SubAgentType.BASH:
                    permissions[tool] = "delay"  # 延迟确认
                else:
                    permissions[tool] = "ask"  # 需要询问
            elif tool in ["Write", "Edit", "MultiEdit"]:
                # 写操作需要确认
                permissions[tool] = "delay"
            else:
                permissions[tool] = "delay"

        return permissions


# ============================================================================
# 阶段2: SubAgent 实例化 - SubAgentFactory
# ============================================================================

class SubAgentFactory:
    """
    SubAgent 工厂
    阶段2: SubAgent 实例化

    职责:
    - 新的 Agent 实例创建
    - 独立执行环境
    - 隔离权限管理
    - 专用工具子集
    """

    @staticmethod
    def create(
        context: TaskContext,
        tool_implementations: Dict[str, Callable],
        agent_type: SubAgentType = None
    ) -> SubAgentInstance:
        """
        创建 SubAgent 实例

        Args:
            context: 任务上下文
            tool_implementations: 可用的工具实现
            agent_type: SubAgent 类型

        Returns:
            SubAgentInstance: 配置好的 SubAgent 实例
        """
        # 确定类型
        if agent_type is None:
            agent_type = SubAgentType.GENERAL_PURPOSE

        # 生成唯一 ID
        instance_id = f"subagent-{int(time.time() * 1000)}-{hashlib.md5(context.user_prompt.encode()).hexdigest()[:8]}"

        # 创建实例
        instance = SubAgentInstance(
            id=instance_id,
            agent_type=agent_type,
            context=context,
        )

        # 配置专用工具子集
        for tool_name in context.allowed_tools:
            if tool_name in tool_implementations:
                instance.tools[tool_name] = tool_implementations[tool_name]

        # 配置隔离权限
        for tool_name, permission in context.tool_permissions.items():
            if permission == "allow":
                instance.approved_tools.add(tool_name)

        return instance


# ============================================================================
# 阶段3: CN5 Schema 输出验证 - SchemaGenerator
# ============================================================================

class SchemaGenerator:
    """
    Schema 生成器
    阶段3: CN5 Schema 输出验证

    职责:
    - 生成 description: 任务简短描述（3-5词）
    - 生成 prompt: 详细任务执行指令
    """

    @staticmethod
    def generate(context: TaskContext, instance: SubAgentInstance) -> CN5Schema:
        """
        生成 CN5 Schema

        Args:
            context: 任务上下文
            instance: SubAgent 实例

        Returns:
            CN5Schema: 验证后的 Schema
        """
        # 生成简短描述 (3-5词)
        description = SchemaGenerator._generate_description(context)

        # 生成详细执行指令
        prompt = SchemaGenerator._generate_prompt(context, instance)

        # 确定模型
        model = SchemaGenerator._select_model(instance.agent_type)

        return CN5Schema(
            description=description,
            prompt=prompt,
            subagent_type=instance.agent_type,
            model=model,
            max_iterations=context.max_iterations,
        )

    @staticmethod
    def _generate_description(context: TaskContext) -> str:
        """生成简短描述 (3-5词)"""
        # 从用户输入中提取关键词
        prompt = context.user_prompt

        # 提取关键名词和动词
        keywords = []

        # 英文关键词
        en_words = re.findall(r'\b[A-Z][a-z]+\b|\b[a-z]{4,}\b', prompt)
        keywords.extend(en_words[:3])

        # 中文关键词
        cn_words = re.findall(r'[\u4e00-\u9fff]{2,}', prompt)
        keywords.extend(cn_words[:2])

        # 组合成描述
        if keywords:
            description = ' '.join(keywords[:5])
        else:
            description = context.parsed_intent

        # 限制长度
        if len(description) > 50:
            description = description[:47] + "..."

        return description

    @staticmethod
    def _generate_prompt(context: TaskContext, instance: SubAgentInstance) -> str:
        """生成详细执行指令"""
        sections = []

        # 1. 任务描述
        sections.append(f"## 任务\n{context.user_prompt}\n")

        # 2. 执行环境
        sections.append(f"## 执行环境")
        sections.append(f"- 工作目录: {context.working_dir}")
        sections.append(f"- 最大迭代次数: {context.max_iterations}")
        sections.append(f"- 超时限制: {context.timeout_ms / 1000}秒")
        sections.append("")

        # 3. 可用工具
        sections.append("## 可用工具")
        for tool in context.allowed_tools:
            permission = context.tool_permissions.get(tool, "ask")
            perm_text = {"allow": "(自动批准)", "delay": "(需确认)", "ask": "(需确认)"}
            sections.append(f"- {tool} {perm_text.get(permission, '')}")
        sections.append("")

        # 4. 执行约束
        sections.append("## 执行约束")
        sections.append("- 独立完成任务，不要请求额外信息")
        sections.append("- 遇到错误时尝试调整策略")
        sections.append("- 完成后提供简洁的结果摘要")
        sections.append("")

        return "\n".join(sections)

    @staticmethod
    def _select_model(agent_type: SubAgentType) -> str:
        """选择模型"""
        model_mapping = {
            SubAgentType.EXPLORE: "deepseek-chat",
            SubAgentType.PLAN: "deepseek-chat",
            SubAgentType.BASH: "deepseek-chat",
            SubAgentType.CLAUDE_CODE_GUIDE: "deepseek-chat",
            SubAgentType.GENERAL_PURPOSE: "deepseek-chat",
        }
        return model_mapping.get(agent_type, "deepseek-chat")


# ============================================================================
# 阶段4: SubAgent 独立执行 - SubAgentExecutor
# ============================================================================

class SubAgentExecutor:
    """
    SubAgent 执行器
    阶段4: SubAgent 独立执行

    职责:
    - 独立的 Agent 主循环实例
    - 专用消息队列
    - 隔离的工具权限
    - 独立错误处理
    """

    def __init__(self, llm_client):
        self.llm_client = llm_client

    async def execute(
        self,
        instance: SubAgentInstance,
        schema: CN5Schema,
        system_prompt: str = None
    ) -> AsyncGenerator[Dict, None]:
        """
        执行 SubAgent

        Args:
            instance: SubAgent 实例
            schema: CN5 Schema
            system_prompt: 系统提示词

        Yields:
            执行事件流
        """
        instance.status = SubAgentStatus.RUNNING
        instance.start_time = time.time()

        # 构建完整的系统提示
        full_system = self._build_system_prompt(instance, schema, system_prompt)

        # 构建消息队列
        messages = [
            {"role": "user", "content": schema.prompt}
        ]

        iterations = 0
        tool_calls_count = 0
        final_response = ""

        try:
            while iterations < instance.context.max_iterations:
                iterations += 1

                yield {
                    "type": "iteration",
                    "iteration": iterations,
                    "max_iterations": instance.context.max_iterations
                }

                # 调用 LLM
                response_text = ""
                tool_calls = []

                async for event in self.llm_client.chat_completion_stream(
                    model=schema.model,
                    messages=messages,
                    system=full_system,
                    stream=True
                ):
                    if event.get("type") == "text":
                        response_text += event.get("text", "")
                        yield {"type": "text", "text": event.get("text", "")}
                    elif event.get("type") == "tool_call":
                        tool_calls.append(event.get("tool_call"))

                if not tool_calls:
                    # 无工具调用，完成
                    final_response = response_text
                    break

                # 处理工具调用
                messages.append({"role": "assistant", "content": response_text})

                for tc in tool_calls:
                    tool_name = tc.get("function", {}).get("name")
                    tool_args = json.loads(tc.get("function", {}).get("arguments", "{}"))

                    # 检查工具是否可用
                    if tool_name not in instance.tools:
                        yield {
                            "type": "tool_error",
                            "tool": tool_name,
                            "error": f"Tool not available: {tool_name}"
                        }
                        messages.append({
                            "role": "tool",
                            "content": f"Error: Tool '{tool_name}' is not available"
                        })
                        continue

                    # 检查权限
                    if tool_name not in instance.approved_tools:
                        # 在 SubAgent 中，我们需要延迟确认或自动处理
                        # 这里简化为自动批准安全操作
                        yield {
                            "type": "tool_permission",
                            "tool": tool_name,
                            "status": "auto_approved"
                        }
                        instance.approved_tools.add(tool_name)

                    # 执行工具
                    tool_calls_count += 1
                    yield {
                        "type": "tool_start",
                        "tool": tool_name,
                        "args": tool_args
                    }

                    try:
                        result = await instance.tools[tool_name](tool_args)
                        yield {
                            "type": "tool_result",
                            "tool": tool_name,
                            "result": str(result)[:2000]
                        }
                        messages.append({
                            "role": "tool",
                            "content": str(result)
                        })
                    except Exception as e:
                        yield {
                            "type": "tool_error",
                            "tool": tool_name,
                            "error": str(e)
                        }
                        messages.append({
                            "role": "tool",
                            "content": f"Error: {str(e)}"
                        })

            # 执行完成
            instance.status = SubAgentStatus.COMPLETED
            instance.result = final_response

        except asyncio.CancelledError:
            instance.status = SubAgentStatus.CANCELLED
            instance.error = "Execution cancelled"
            yield {"type": "cancelled", "reason": "Execution cancelled"}

        except Exception as e:
            instance.status = SubAgentStatus.FAILED
            instance.error = str(e)
            yield {"type": "error", "error": str(e)}

        finally:
            instance.end_time = time.time()

        yield {
            "type": "complete",
            "iterations": iterations,
            "tool_calls": tool_calls_count
        }

    def _build_system_prompt(
        self,
        instance: SubAgentInstance,
        schema: CN5Schema,
        base_system: str = None
    ) -> str:
        """构建系统提示"""
        sections = []

        # 基础系统提示
        if base_system:
            sections.append(base_system)

        # SubAgent 角色定义
        sections.append(f"""
## SubAgent 角色
你是一个 {schema.subagent_type.value} 类型的子代理。
你的任务是独立完成分配给你的任务。

## 任务描述
{schema.description}

## 执行约束
- 最大迭代次数: {schema.max_iterations}
- 工作目录: {instance.context.working_dir}
- 完成后提供简洁的结果摘要
""")

        return "\n".join(sections)


# ============================================================================
# 阶段5: 结果返回 - ResultAggregator
# ============================================================================

class ResultAggregator:
    """
    结果聚合器
    阶段5: 结果返回主 Agent

    职责:
    - 单一消息返回机制
    - 无状态通信模式
    - 结果摘要生成
    """

    @staticmethod
    def aggregate(
        instance: SubAgentInstance,
        execution_events: List[Dict]
    ) -> SubAgentResult:
        """
        聚合执行结果

        Args:
            instance: SubAgent 实例
            execution_events: 执行事件列表

        Returns:
            SubAgentResult: 聚合后的结果
        """
        # 提取关键信息
        iterations = 0
        tool_calls = 0
        text_content = []

        for event in execution_events:
            if event.get("type") == "iteration":
                iterations = event.get("iteration", iterations)
            elif event.get("type") == "tool_start":
                tool_calls += 1
            elif event.get("type") == "text":
                text_content.append(event.get("text", ""))

        # 生成单一消息
        full_message = "".join(text_content)
        if not full_message and instance.result:
            full_message = instance.result

        # 生成摘要
        summary = ResultAggregator._generate_summary(full_message, instance)

        return SubAgentResult(
            message=full_message,
            summary=summary,
            success=instance.status == SubAgentStatus.COMPLETED,
            iterations=iterations,
            tool_calls=tool_calls,
            duration_ms=int((instance.end_time - instance.start_time) * 1000) if instance.end_time else 0,
            artifacts={
                "instance_id": instance.id,
                "agent_type": instance.agent_type.value,
            }
        )

    @staticmethod
    def _generate_summary(message: str, instance: SubAgentInstance) -> str:
        """生成结果摘要"""
        # 提取关键句子
        sentences = re.split(r'[。.!?]', message)
        key_sentences = [s.strip() for s in sentences if len(s.strip()) > 10][:3]

        if key_sentences:
            summary = "。".join(key_sentences)
            if len(summary) > 200:
                summary = summary[:197] + "..."
        else:
            summary = f"任务{'完成' if instance.status == SubAgentStatus.COMPLETED else '失败'}"

        return summary


# ============================================================================
# Task 工具 - 完整流程集成
# ============================================================================

class TaskTool:
    """
    Task 工具
    完整的 SubAgent 调用流程
    """

    def __init__(
        self,
        llm_client,
        tool_implementations: Dict[str, Callable],
        default_system_prompt: str = None
    ):
        self.llm_client = llm_client
        self.tool_implementations = tool_implementations
        self.default_system_prompt = default_system_prompt

        self.preparer = TaskPreparer()
        self.factory = SubAgentFactory()
        self.executor = SubAgentExecutor(llm_client)

    async def execute(
        self,
        prompt: str,
        subagent_type: str = None,
        description: str = None,
        model: str = None,
        **kwargs
    ) -> AsyncGenerator[Dict, None]:
        """
        执行 Task 工具

        Args:
            prompt: 任务描述
            subagent_type: SubAgent 类型
            description: 任务简短描述
            model: 模型选择
            **kwargs: 其他参数

        Yields:
            执行事件流
        """
        # ========== 阶段1: 准备阶段 ==========
        yield {"type": "phase", "phase": "preparing", "message": "准备任务上下文"}

        # 解析 SubAgent 类型
        agent_type = None
        if subagent_type:
            try:
                agent_type = SubAgentType(subagent_type)
            except ValueError:
                agent_type = SubAgentType.GENERAL_PURPOSE

        context = self.preparer.prepare(
            user_prompt=prompt,
            **kwargs
        )

        if agent_type:
            context.tool_permissions = self.preparer._configure_tool_permissions(
                context.allowed_tools, agent_type
            )

        yield {
            "type": "prepared",
            "intent": context.parsed_intent,
            "tools": context.allowed_tools
        }

        # ========== 阶段2: SubAgent 实例化 ==========
        yield {"type": "phase", "phase": "instantiating", "message": "创建 SubAgent 实例"}

        instance = self.factory.create(
            context=context,
            tool_implementations=self.tool_implementations,
            agent_type=agent_type
        )

        yield {
            "type": "instance_created",
            "instance_id": instance.id,
            "agent_type": instance.agent_type.value
        }

        # ========== 阶段3: CN5 Schema 生成 ==========
        yield {"type": "phase", "phase": "schema_generation", "message": "生成执行 Schema"}

        schema = SchemaGenerator.generate(context, instance)

        # 覆盖参数
        if description:
            schema.description = description
        if model:
            schema.model = model

        yield {
            "type": "schema_generated",
            "description": schema.description,
            "model": schema.model,
            "max_iterations": schema.max_iterations
        }

        # ========== 阶段4: SubAgent 独立执行 ==========
        yield {"type": "phase", "phase": "executing", "message": "SubAgent 开始执行"}

        execution_events = []

        async for event in self.executor.execute(
            instance,
            schema,
            self.default_system_prompt
        ):
            execution_events.append(event)
            yield event

        # ========== 阶段5: 结果返回 ==========
        yield {"type": "phase", "phase": "aggregating", "message": "聚合执行结果"}

        result = ResultAggregator.aggregate(instance, execution_events)

        yield {
            "type": "result",
            "message": result.message,
            "summary": result.summary,
            "success": result.success,
            "iterations": result.iterations,
            "tool_calls": result.tool_calls,
            "duration_ms": result.duration_ms
        }


# ============================================================================
# SubAgent 管理器
# ============================================================================

class SubAgentManager:
    """
    SubAgent 管理器
    管理所有 SubAgent 实例和配置
    """

    def __init__(self, llm_client=None, tool_implementations: Dict[str, Callable] = None):
        self.llm_client = llm_client
        self.tool_implementations = tool_implementations or {}
        self.instances: Dict[str, SubAgentInstance] = {}
        self._lock = Lock()

    def create_task_tool(self) -> TaskTool:
        """创建 Task 工具实例"""
        return TaskTool(
            llm_client=self.llm_client,
            tool_implementations=self.tool_implementations
        )

    def register_instance(self, instance: SubAgentInstance):
        """注册实例"""
        with self._lock:
            self.instances[instance.id] = instance

    def get_instance(self, instance_id: str) -> Optional[SubAgentInstance]:
        """获取实例"""
        return self.instances.get(instance_id)

    def cleanup_instance(self, instance_id: str):
        """清理实例"""
        with self._lock:
            self.instances.pop(instance_id, None)

    def get_active_instances(self) -> List[SubAgentInstance]:
        """获取活跃实例"""
        return [
            inst for inst in self.instances.values()
            if inst.status == SubAgentStatus.RUNNING
        ]

    def get_stats(self) -> Dict:
        """获取统计信息"""
        status_counts = {}
        for status in SubAgentStatus:
            status_counts[status.value] = sum(
                1 for inst in self.instances.values()
                if inst.status == status
            )

        return {
            "total_instances": len(self.instances),
            "status_counts": status_counts,
            "active_count": len(self.get_active_instances())
        }


# ============================================================================
# 预定义的 SubAgent 配置
# ============================================================================

# SubAgent 系统提示词模板
SUBAGENT_SYSTEM_PROMPTS = {
    SubAgentType.GENERAL_PURPOSE: """你是一个通用的 AI 助手，能够执行各种编程任务。
你需要独立完成分配给你的任务，使用可用的工具来解决问题。""",

    SubAgentType.EXPLORE: """你是一个代码探索专家。
你的任务是快速理解代码库的结构和功能。
使用 Glob、Grep、Read 等工具来探索代码。
提供清晰、结构化的发现报告。""",

    SubAgentType.BASH: """你是一个命令行执行专家。
你的任务是执行命令行操作来完成特定任务。
注意安全，避免危险操作。
提供清晰的执行结果和状态。""",

    SubAgentType.PLAN: """你是一个软件架构师。
你的任务是分析需求并设计实现方案。
考虑架构权衡、技术选型和实现步骤。
提供详细的计划和建议。""",

    SubAgentType.CLAUDE_CODE_GUIDE: """你是 Claude Code CLI 的专家。
你了解 Claude Code 的所有功能、命令和最佳实践。
帮助用户解决使用问题，提供使用指南。""",
}
