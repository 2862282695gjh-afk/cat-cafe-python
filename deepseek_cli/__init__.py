"""
DeepSeek CLI - 完整六层架构实现

架构:
- 2 调度层: Agent主循环 + 消息队列
- 2 执行层: 工具引擎 + 并发控制
- 2 管理层: 上下文压缩 + SubAgent

15类工具:
- 文件操作: Read, Write, Edit, MultiEdit, LS
- 搜索: Glob, Grep
- 任务管理: TodoRead, TodoWrite, Task
- 命令执行: Bash
- 网络: WebFetch, WebSearch
- Notebook: NotebookRead, NotebookEdit

SubAgent 架构:
- 准备阶段: 任务解析、环境准备、工具配置
- 实例化: 独立Agent、隔离权限、专用工具
- Schema验证: description(3-5词)、prompt(详细指令)
- 独立执行: 专用消息队列、独立错误处理
- 结果返回: 单一消息、无状态通信、摘要生成
"""
# v1 - 基础版本
from .deepseek_cli import DeepSeekCLI, get_tools_definition, DEFAULT_SYSTEM_PROMPT
from .api_client import DeepSeekClient
from .tools import ToolExecutor

# v2 - 四层架构版本
from .runtime import AgenticRuntime, AgentState, Task, ExecutionStep
from .prompt_engine import PromptAugmentationEngine, DynamicPromptBuilder, ProjectContext
from .skills import SkillRegistry, SubAgentManager as SubAgentManagerV1, BaseSkill, SkillResult
from .environment import EnvironmentLayer, FileInfo as EnvFileInfo, ExecutionResult as EnvExecutionResult

# v3 - 六层架构版本（完整）
from .memory import MemoryManager, ShortTermMemory, MidTermMemory, LongTermMemory
from .memory import AU2Compressor, CompressionResult, Message
from .tool_engine import (
    ToolEngine, ToolCall, ToolStatus, ToolPhase,
    ExecutionResult, ToolExecutionPipeline, PermissionGate, ConcurrencyController,
    # 阶段组件
    ToolRegistry, ToolDefinition, SchemaValidator,
    CancellationController, ToolExecutor as ToolExecutorV3,
    ResultFormatter,
    # 数据类
    ValidationResult, AuthorizationResult, ToolResultBlock,
    AbortSignal, HookType, HookContext,
    PermissionAction, DangerLevel,
    # 异常
    ToolError, ToolCancelledError, ToolTimeoutError, ValidationError
)
from .orchestrator import Orchestrator, LoopState, LoopContext
from .context_injector import ContextInjector, FileInfo as InjectorFileInfo, InjectionResult

# SubAgent 架构 (v3 - 完整实现)
from .subagent import (
    SubAgentType, SubAgentStatus, SubAgentInstance,
    TaskContext, CN5Schema, SubAgentResult,
    TaskPreparer, SubAgentFactory, SchemaGenerator,
    SubAgentExecutor, ResultAggregator,
    TaskTool, SubAgentManager,
    SUBAGENT_SYSTEM_PROMPTS
)

# Todo 工具对象层 + 存储持久化层
from .todo import (
    # 枚举
    TodoStatus, TodoPriority, StorageType,
    # 数据类
    Todo,
    # YJ1 排序算法
    YJ1SortEngine,
    # 存储层
    TodoStorageBase, MemoryTodoStorage, FileTodoStorage, BrowserCacheStorage,
    # 工具
    TodoWriteTool, TodoReadTool,
    # 管理器
    TodoManager,
)

# System-Reminder 动态注入机制
from .system_reminder import (
    # 枚举
    TriggerType, InjectionPoint, RelevanceLevel,
    # 数据类
    TriggerState, ReminderContext, SystemReminder,
    # 组件
    StateDetector, ConditionMatcher, ContentGenerator, InjectionController,
    # 注入器
    SystemReminderInjector, AgentLoopReminderManager,
    # 便捷函数
    create_reminder, format_as_xml, format_as_markdown,
)

__all__ = [
    # v1
    'DeepSeekCLI',
    'DeepSeekClient',
    'ToolExecutor',
    'get_tools_definition',
    'DEFAULT_SYSTEM_PROMPT',

    # v2 - 四层架构
    'AgenticRuntime',
    'AgentState',
    'Task',
    'ExecutionStep',
    'PromptAugmentationEngine',
    'DynamicPromptBuilder',
    'ProjectContext',
    'SkillRegistry',
    'SubAgentManagerV1',
    'BaseSkill',
    'SkillResult',
    'EnvironmentLayer',
    'EnvFileInfo',
    'EnvExecutionResult',

    # v3 - 六层架构
    'MemoryManager',
    'ShortTermMemory',
    'MidTermMemory',
    'LongTermMemory',
    'AU2Compressor',
    'CompressionResult',
    'Message',

    # 工具引擎
    'ToolEngine',
    'ToolCall',
    'ToolStatus',
    'ToolPhase',
    'ExecutionResult',
    'ToolExecutionPipeline',
    'PermissionGate',
    'ConcurrencyController',

    # 阶段组件
    'ToolRegistry',
    'ToolDefinition',
    'SchemaValidator',
    'CancellationController',
    'ToolExecutorV3',
    'ResultFormatter',

    # 数据类
    'ValidationResult',
    'AuthorizationResult',
    'ToolResultBlock',
    'AbortSignal',
    'HookType',
    'HookContext',
    'PermissionAction',
    'DangerLevel',

    # 异常
    'ToolError',
    'ToolCancelledError',
    'ToolTimeoutError',
    'ValidationError',

    # Orchestrator
    'Orchestrator',
    'LoopState',
    'LoopContext',

    # Context Injector
    'ContextInjector',
    'InjectorFileInfo',
    'InjectionResult',

    # SubAgent 架构
    'SubAgentType',
    'SubAgentStatus',
    'SubAgentInstance',
    'TaskContext',
    'CN5Schema',
    'SubAgentResult',
    'TaskPreparer',
    'SubAgentFactory',
    'SchemaGenerator',
    'SubAgentExecutor',
    'ResultAggregator',
    'TaskTool',
    'SubAgentManager',
    'SUBAGENT_SYSTEM_PROMPTS',

    # Todo 工具对象层
    'TodoStatus',
    'TodoPriority',
    'StorageType',
    'Todo',
    'YJ1SortEngine',
    'TodoStorageBase',
    'MemoryTodoStorage',
    'FileTodoStorage',
    'BrowserCacheStorage',
    'TodoWriteTool',
    'TodoReadTool',
    'TodoManager',

    # System-Reminder 动态注入
    'TriggerType',
    'InjectionPoint',
    'RelevanceLevel',
    'TriggerState',
    'ReminderContext',
    'SystemReminder',
    'StateDetector',
    'ConditionMatcher',
    'ContentGenerator',
    'InjectionController',
    'SystemReminderInjector',
    'AgentLoopReminderManager',
    'create_reminder',
    'format_as_xml',
    'format_as_markdown',
]
