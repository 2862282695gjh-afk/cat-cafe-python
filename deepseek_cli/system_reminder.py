"""
System-Reminder 动态注入机制

在 Agent Loop 执行过程中动态注入系统提醒:

1. 状态检测触发器:
   - Todo 列表变化检测
   - 文件系统状态变化
   - 用户行为模式分析
   - 错误模式识别

2. 条件匹配引擎:
   - 规则表达式匹配
   - 上下文相关性分析
   - 时机适当性判断

3. 内容生成与格式化:
   - 动态内容模版
   - 个性化信息生成
   - 格式化标准化处理

4. 注入时机控制:
   - 小溪流插入点选择
   - 用户体验优化
   - 干扰最小化原则

5. <system-reminder> 标签注入:
   - 在消息流中动态插入
"""
import os
import re
import time
import json
import hashlib
from typing import Dict, List, Optional, Any, Callable, Set
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from pathlib import Path


# ============================================================================
# 枚举定义
# ============================================================================

class TriggerType(Enum):
    """触发器类型"""
    TODO_CHANGE = "todo_change"              # Todo 列表变化
    FILE_SYSTEM = "file_system"              # 文件系统变化
    USER_BEHAVIOR = "user_behavior"          # 用户行为模式
    ERROR_PATTERN = "error_pattern"          # 错误模式
    ITERATION = "iteration"                  # 迭代次数
    TOKEN_USAGE = "token_usage"              # Token 使用量
    TIME_ELAPSED = "time_elapsed"            # 时间流逝
    CUSTOM = "custom"                        # 自定义


class InjectionPoint(Enum):
    """注入点选择"""
    PRE_ITERATION = "pre_iteration"        # 迭代前
    POST_ITERATION = "post_iteration"       # 迭代后
    PRE_TOOL_CALL = "pre_tool_call"        # 工具调用前
    POST_TOOL_CALL = "post_tool_call"      # 工具调用后
    ON_ERROR = "on_error"                  # 错误时
    ON_COMPLETE = "on_complete"            # 完成时
    STREAMING = "streaming"                 # 流式注入


class RelevanceLevel(Enum):
    """相关性级别"""
    CRITICAL = "critical"    # 必须显示
    HIGH = "high"            # 建议显示
    MEDIUM = "medium"        # 可选显示
    LOW = "low"              # 仅在空闲时显示


# ============================================================================
# 数据类
# ============================================================================

@dataclass
class TriggerState:
    """触发器状态"""
    trigger_type: TriggerType
    last_check_time: float = 0
    last_value: Any = None
    change_count: int = 0
    metadata: Dict = field(default_factory=dict)


@dataclass
class ReminderContext:
    """提醒上下文"""
    # Agent 状态
    iteration: int = 0
    max_iterations: int = 50
    tool_calls_count: int = 0
    tokens_used: int = 0
    start_time: float = 0

    # Todo 状态
    pending_todos: int = 0
    in_progress_todos: int = 0
    completed_todos: int = 0

    # 文件系统状态
    files_read: Set[str] = field(default_factory=set)
    files_written: Set[str] = field(default_factory=set)
    files_modified: Set[str] = field(default_factory=set)

    # 用户行为
    user_messages: int = 0
    last_user_message: str = ""

    # 错误状态
    errors: List[str] = field(default_factory=list)
    last_error: str = ""

    # 注入历史
    injected_reminders: List[str] = field(default_factory=list)


@dataclass
class SystemReminder:
    """系统提醒"""
    id: str
    content: str
    relevance: RelevanceLevel
    injection_point: InjectionPoint
    trigger_type: TriggerType
    priority: int = 0  # 越高越优先
    metadata: Dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_xml(self) -> str:
        """转换为 <system-reminder> XML 格式"""
        return f"<system-reminder>\n{self.content}\n</system-reminder>"

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "id": self.id,
            "content": self.content,
            "relevance": self.relevance.value,
            "injection_point": self.injection_point.value,
            "trigger_type": self.trigger_type.value,
            "priority": self.priority,
            "metadata": self.metadata,
        }


# ============================================================================
# 阶段1: 状态检测触发器
# ============================================================================

class StateDetector:
    """
    状态检测触发器

    功能:
    - Todo 列表变化检测
    - 文件系统状态变化
    - 用户行为模式分析
    - 错误模式识别
    """

    def __init__(self):
        self.states: Dict[TriggerType, TriggerState] = {}
        self._file_hashes: Dict[str, str] = {}
        self._init_states()

    def _init_states(self):
        """初始化所有触发器状态"""
        for trigger_type in TriggerType:
            self.states[trigger_type] = TriggerState(
                trigger_type=trigger_type,
                last_check_time=time.time()
            )

    # ==================== Todo 列表变化检测 ====================

    def detect_todo_change(
        self,
        current_todos: List[Dict],
        previous_todos: List[Dict]
    ) -> Optional[Dict]:
        """检测 Todo 列表变化"""
        changes = {
            "added": [],
            "removed": [],
            "status_changed": [],
            "priority_changed": [],
        }

        current_ids = {t.get("id") for t in current_todos}
        previous_ids = {t.get("id") for t in previous_todos}

        # 新增的 Todo
        changes["added"] = list(current_ids - previous_ids)

        # 删除的 Todo
        changes["removed"] = list(previous_ids - current_ids)

        # 状态变化
        prev_status = {t.get("id"): t.get("status") for t in previous_todos}
        for todo in current_todos:
            todo_id = todo.get("id")
            if todo_id in prev_status:
                if todo.get("status") != prev_status[todo_id]:
                    changes["status_changed"].append({
                    "id": todo_id,
                    "from": prev_status[todo_id],
                    "to": todo.get("status")
                    })

        # 更新状态
        self.states[TriggerType.TODO_CHANGE].last_value = current_todos
        self.states[TriggerType.TODO_CHANGE].change_count += len(changes["added"]) + len(changes["removed"])

        if any(changes.values()):
            return changes
        return None

    # ==================== 文件系统状态变化 ====================

    def detect_file_change(
        self,
        file_path: str,
        operation: str  # read, write, modify
    ) -> Optional[Dict]:
        """检测文件系统变化"""
        change_info = {
            "path": file_path,
            "operation": operation,
            "timestamp": time.time(),
        }

        try:
            if os.path.exists(file_path):
                with open(file_path, "rb") as f:
                    content = f.read()
                current_hash = hashlib.md5(content).hexdigest()

                if file_path in self._file_hashes:
                    if self._file_hashes[file_path] != current_hash:
                        change_info["changed"] = True
                        change_info["previous_hash"] = self._file_hashes[file_path]

                self._file_hashes[file_path] = current_hash
                change_info["current_hash"] = current_hash
        except Exception as e:
            change_info["error"] = str(e)

        # 更新状态
        self.states[TriggerType.FILE_SYSTEM].last_value = file_path
        self.states[TriggerType.FILE_SYSTEM].change_count += 1

        return change_info

    # ==================== 用户行为模式分析 ====================

    USER_BEHAVIOR_PATTERNS = {
        "repetitive_question": {
            "pattern": r"(怎么|如何|为什么|what|how|why)",
            "threshold": 3,  # 重复次数
            "description": "重复提问"
        },
        "urgent_request": {
            "pattern": r"(紧急|马上|立刻|快|urgent|asap|immediately)",
            "threshold": 1,
            "description": "紧急请求"
        },
        "confusion": {
            "pattern": r"(不明白|不懂|困惑|confused|don't understand|help)",
            "threshold": 1,
            "description": "用户困惑"
        },
        "frustration": {
            "pattern": r"(不行|错误|失败|不对|wrong|error|fail)",
            "threshold": 2,
            "description": "用户沮丧"
        },
        "completion_request": {
            "pattern": r"(完成|结束|done|finish|complete)",
            "threshold": 1,
            "description": "请求完成"
        },
    }

    def analyze_user_behavior(
        self,
        user_message: str,
        message_history: List[str]
    ) -> Optional[Dict]:
        """分析用户行为模式"""
        detected_patterns = []

        for pattern_name, pattern_config in self.USER_BEHAVIOR_PATTERNS.items():
            pattern = pattern_config["pattern"]
            threshold = pattern_config["threshold"]

            # 检查当前消息
            if re.search(pattern, user_message, re.IGNORECASE):
                # 检查历史消息中的重复
                match_count = sum(
                    1 for msg in message_history
                    if re.search(pattern, msg, re.IGNORECASE)
                )

                if match_count >= threshold - 1:  # -1 因为当前消息也算一次
                    detected_patterns.append({
                        "pattern": pattern_name,
                        "description": pattern_config["description"],
                        "count": match_count + 1,
                    })

        # 更新状态
        self.states[TriggerType.USER_BEHAVIOR].last_value = user_message
        if detected_patterns:
            self.states[TriggerType.USER_BEHAVIOR].change_count += len(detected_patterns)
            return {"patterns": detected_patterns}

        return None

    # ==================== 错误模式识别 ====================

    ERROR_PATTERNS = {
        "permission_denied": {
            "pattern": r"(permission|denied|权限|拒绝)",
            "severity": "high",
            "suggestion": "检查文件权限或使用 sudo"
        },
        "file_not_found": {
            "pattern": r"(no such file|not found|文件不存在)",
            "severity": "medium",
            "suggestion": "检查文件路径是否正确"
        },
        "timeout": {
            "pattern": r"(timeout|超时)",
            "severity": "medium",
            "suggestion": "增加超时时间或简化操作"
        },
        "syntax_error": {
            "pattern": r"(syntax error|语法错误)",
            "severity": "high",
            "suggestion": "检查命令或代码语法"
        },
        "connection_error": {
            "pattern": r"(connection|连接|network|网络)",
            "severity": "medium",
            "suggestion": "检查网络连接"
        },
        "memory_error": {
            "pattern": r"(memory|内存|oom|out of memory)",
            "severity": "critical",
            "suggestion": "减少处理的数据量"
        },
        "repeated_error": {
            "pattern": r"(\berror\b.*\berror\b|错误.*错误)",
            "severity": "high",
            "suggestion": "相同的错误已出现多次，请尝试不同的方法"
        },
    }

    def detect_error_pattern(self, error_message: str) -> Optional[Dict]:
        """识别错误模式"""
        detected_errors = []

        for error_name, error_config in self.ERROR_PATTERNS.items():
            pattern = error_config["pattern"]
            if re.search(pattern, error_message, re.IGNORECASE):
                detected_errors.append({
                    "type": error_name,
                    "severity": error_config["severity"],
                    "suggestion": error_config["suggestion"],
                    "original_message": error_message[:200],
                })

        # 更新状态
        self.states[TriggerType.ERROR_PATTERN].last_value = error_message
        if detected_errors:
            self.states[TriggerType.ERROR_PATTERN].change_count += 1
            return {"errors": detected_errors}

        return None

    # ==================== 迭代次数检测 ====================

    def check_iteration(self, current: int, max_iterations: int) -> Optional[Dict]:
        """检查迭代次数"""
        warning_thresholds = [0.5, 0.75, 0.9, 0.95]  # 50%, 75%, 90%, 95%

        usage_ratio = current / max_iterations if max_iterations > 0 else 0

        for threshold in warning_thresholds:
            threshold_count = int(threshold * max_iterations)
            if current == threshold_count:
                return {
                    "threshold": threshold,
                    "current": current,
                    "max": max_iterations,
                    "usage_ratio": usage_ratio,
                }

        return None

    # ==================== Token 使用量检测 ====================

    def check_token_usage(
        self,
        current_tokens: int,
        max_tokens: int
    ) -> Optional[Dict]:
        """检查 Token 使用量"""
        warning_thresholds = [0.5, 0.75, 0.9, 0.95]

        usage_ratio = current_tokens / max_tokens if max_tokens > 0 else 0

        for threshold in warning_thresholds:
            threshold_tokens = int(threshold * max_tokens)
            if current_tokens >= threshold_tokens:
                prev_value = self.states[TriggerType.TOKEN_USAGE].last_value or 0
                if prev_value < threshold_tokens:
                    return {
                        "threshold": threshold,
                        "current": current_tokens,
                        "max": max_tokens,
                        "usage_ratio": usage_ratio,
                    }

        self.states[TriggerType.TOKEN_USAGE].last_value = current_tokens
        return None

    # ==================== 时间流逝检测 ====================

    def check_time_elapsed(
        self,
        start_time: float,
        warning_intervals: List[int] = None
    ) -> Optional[Dict]:
        """检查时间流逝"""
        if warning_intervals is None:
            warning_intervals = [60, 120, 300, 600]  # 1分钟, 2分钟, 5分钟, 10分钟

        elapsed = time.time() - start_time

        for interval in warning_intervals:
            prev_value = self.states[TriggerType.TIME_ELAPSED].last_value or 0
            if elapsed >= interval and prev_value < interval:
                self.states[TriggerType.TIME_ELAPSED].last_value = elapsed
                return {
                    "elapsed_seconds": elapsed,
                    "elapsed_minutes": elapsed / 60,
                    "warning_interval": interval,
                }

        return None


# ============================================================================
# 阶段2: 条件匹配引擎
# ============================================================================

class ConditionMatcher:
    """
    条件匹配引擎

    功能:
    - 规则表达式匹配
    - 上下文相关性分析
    - 时机适当性判断
    """

    # 匹配规则定义
    MATCHING_RULES = [
        # ==================== 迭代相关 ====================
        {
            "id": "high_iteration_usage",
            "name": "迭代次数过高",
            "trigger_types": [TriggerType.ITERATION],
            "condition": lambda ctx: ctx.get("usage_ratio", 0) >= 0.75,
            "relevance": RelevanceLevel.HIGH,
            "template": "已执行 {current}/{max} 次迭代（{usage_ratio:.0%}）。如果任务复杂，可以考虑分解为子任务。",
        },
        {
            "id": "approaching_limit",
            "name": "接近迭代上限",
            "trigger_types": [TriggerType.ITERATION],
            "condition": lambda ctx: ctx.get("usage_ratio", 0) >= 0.9,
            "relevance": RelevanceLevel.CRITICAL,
            "template": "警告：迭代次数即将达到上限（{current}/{max}）。请考虑简化任务或先完成当前部分。",
        },

        # ==================== Token 使用 ====================
        {
            "id": "high_token_usage",
            "name": "Token 使用过高",
            "trigger_types": [TriggerType.TOKEN_USAGE],
            "condition": lambda ctx: ctx.get("usage_ratio", 0) >= 0.75,
            "relevance": RelevanceLevel.HIGH,
            "template": "已使用约 {usage_ratio:.0%} 的上下文空间。长对话可能触发压缩。",
        },

        # ==================== Todo 相关 ====================
        {
            "id": "many_pending_todos",
            "name": "待办任务过多",
            "trigger_types": [TriggerType.TODO_CHANGE],
            "condition": lambda ctx: ctx.get("pending_count", 0) > 5,
            "relevance": RelevanceLevel.MEDIUM,
            "template": "当前有 {pending_count} 个待办任务。建议优先处理重要任务。",
        },
        {
            "id": "todo_stuck_in_progress",
            "name": "任务卡住",
            "trigger_types": [TriggerType.TODO_CHANGE],
            "condition": lambda ctx: ctx.get("in_progress_duration", 0) > 300,  # 5分钟
            "relevance": RelevanceLevel.HIGH,
            "template": "任务 '{task_content}' 已进行 {in_progress_duration:.0f} 秒。是否需要帮助？",
        },

        # ==================== 错误相关 ====================
        {
            "id": "repeated_errors",
            "name": "重复错误",
            "trigger_types": [TriggerType.ERROR_PATTERN],
            "condition": lambda ctx: ctx.get("error_count", 0) >= 3,
            "relevance": RelevanceLevel.CRITICAL,
            "template": "相同类型的错误已出现 {error_count} 次。建议：{suggestion}",
        },
        {
            "id": "permission_error",
            "name": "权限错误",
            "trigger_types": [TriggerType.ERROR_PATTERN],
            "condition": lambda ctx: "permission" in ctx.get("error_type", "").lower(),
            "relevance": RelevanceLevel.HIGH,
            "template": "权限不足。{suggestion}",
        },

        # ==================== 用户行为 ====================
        {
            "id": "user_confusion",
            "name": "用户困惑",
            "trigger_types": [TriggerType.USER_BEHAVIOR],
            "condition": lambda ctx: "confusion" in ctx.get("patterns", []),
            "relevance": RelevanceLevel.HIGH,
            "template": "看起来您可能有些困惑。需要我解释一下吗？",
        },
        {
            "id": "user_frustration",
            "name": "用户沮丧",
            "trigger_types": [TriggerType.USER_BEHAVIOR],
            "condition": lambda ctx: "frustration" in ctx.get("patterns", []),
            "relevance": RelevanceLevel.CRITICAL,
            "template": "我注意到可能有些不顺利。让我换一种方法试试。",
        },

        # ==================== 时间相关 ====================
        {
            "id": "long_execution",
            "name": "执行时间过长",
            "trigger_types": [TriggerType.TIME_ELAPSED],
            "condition": lambda ctx: ctx.get("elapsed_minutes", 0) >= 5,
            "relevance": RelevanceLevel.MEDIUM,
            "template": "任务已执行 {elapsed_minutes:.1f} 分钟。如果需要暂停，请告诉我。",
        },
    ]

    @classmethod
    def match_rules(
        cls,
        trigger_type: TriggerType,
        context: Dict,
        all_rules: bool = False
    ) -> List[Dict]:
        """
        匹配规则

        Args:
            trigger_type: 触发器类型
            context: 上下文信息
            all_rules: 是否返回所有规则（包括不匹配的）

        Returns:
            匹配的规则列表
        """
        matched = []

        for rule in cls.MATCHING_RULES:
            if trigger_type in rule["trigger_types"]:
                try:
                    if rule["condition"](context):
                        matched.append({
                            "rule": rule,
                            "context": context,
                            "matched": True,
                        })
                    elif all_rules:
                        matched.append({
                            "rule": rule,
                            "context": context,
                            "matched": False,
                        })
                except Exception as e:
                    pass  # 规则条件执行失败，跳过

        return matched

    @classmethod
    def analyze_context_relevance(
        cls,
        reminder: SystemReminder,
        current_context: ReminderContext
    ) -> float:
        """
        分析上下文相关性

        Returns:
            相关性分数 (0.0 - 1.0)
        """
        score = 0.0

        # 检查是否与当前任务相关
        if reminder.trigger_type == TriggerType.TODO_CHANGE:
            if current_context.pending_todos > 0:
                score += 0.3
            if current_context.in_progress_todos > 0:
                score += 0.2

        # 检查是否与错误相关
        elif reminder.trigger_type == TriggerType.ERROR_PATTERN:
            if current_context.errors:
                score += 0.4

        # 检查是否与迭代相关
        elif reminder.trigger_type == TriggerType.ITERATION:
            usage_ratio = current_context.iteration / current_context.max_iterations if current_context.max_iterations > 0 else 0
            if usage_ratio > 0.5:
                score += 0.3

        # 检查是否与 Token 相关
        elif reminder.trigger_type == TriggerType.TOKEN_USAGE:
            score += 0.2  # Token 提醒总是相关的

        return min(1.0, score)

    @classmethod
    def is_appropriate_timing(
        cls,
        reminder: SystemReminder,
        context: ReminderContext,
        recent_injections: List[str]
    ) -> bool:
        """
        判断时机是否适当

        Returns:
            是否应该现在注入
        """
        # 检查是否最近注入过相同类型
        cooldown_seconds = 30  # 冷却时间
        for injected_id in recent_injections[-5:]:  # 检查最近5个
            if injected_id == reminder.id:
                return False

        # 检查注入频率
        max_injections_per_minute = 3
        one_minute_ago = time.time() - 60
        recent_count = sum(
            1 for injected_id in recent_injections
            if injected_id.startswith(reminder.trigger_type.value)
        )
        if recent_count >= max_injections_per_minute:
            return False

        return True


# ============================================================================
# 阶段3: 内容生成与格式化
# ============================================================================

class ContentGenerator:
    """
    内容生成器

    功能:
    - 动态内容模版
    - 个性化信息生成
    - 格式化标准化处理
    """

    # 内容模板库
    TEMPLATES = {
        # 迭代提醒
        "iteration_warning": {
            "template": "已执行 {current}/{max} 次迭代",
            "variables": ["current", "max"],
        },
        "iteration_high": {
            "template": "迭代次数较高（{ratio:.0%}），建议检查任务复杂度",
            "variables": ["ratio"],
        },
        "approaching_limit": {
            "template": "接近迭代上限！当前：{current}/{max}",
            "variables": ["current", "max"],
        },

        # Token 提醒
        "token_usage": {
            "template": "上下文使用：{used}/{max} tokens ({ratio:.0%})",
            "variables": ["used", "max", "ratio"],
        },
        "token_high": {
            "template": "上下文空间紧张，可能很快需要压缩",
            "variables": [],
        },

        # Todo 提醒
        "todo_pending": {
            "template": "待办任务：{count} 个待处理",
            "variables": ["count"],
        },
        "todo_progress": {
            "template": "任务进度：{completed}/{total} 完成 ({ratio:.0%})",
            "variables": ["completed", "total", "ratio"],
        },
        "todo_stuck": {
            "template": "任务 '{name}' 已进行较长时间，可能需要关注",
            "variables": ["name"],
        },

        # 错误提醒
        "error_occurred": {
            "template": "检测到错误：{error}",
            "variables": ["error"],
        },
        "error_repeated": {
            "template": "类似错误已出现 {count} 次",
            "variables": ["count"],
        },
        "error_suggestion": {
            "template": "建议：{suggestion}",
            "variables": ["suggestion"],
        },

        # 用户行为
        "user_confusion": {
            "template": "看起来您可能有疑问，需要我解释一下吗？",
            "variables": [],
        },
        "user_frustration": {
            "template": "我注意到进展可能不如预期，让我换个方法",
            "variables": [],
        },

        # 时间提醒
        "time_elapsed": {
            "template": "任务执行已 {minutes:.1f} 分钟",
            "variables": ["minutes"],
        },
        "time_long": {
            "template": "长时间执行中，如需暂停请告诉我",
            "variables": [],
        },
    }

    @classmethod
    def generate(
        cls,
        template_name: str,
        variables: Dict[str, Any],
        rule_context: Dict = None
    ) -> str:
        """
        生成内容

        Args:
            template_name: 模板名称
            variables: 变量值
            rule_context: 规则上下文（用于个性化）

        Returns:
            生成的内容
        """
        if template_name not in cls.TEMPLATES:
            return f"[Unknown template: {template_name}]"

        template_config = cls.TEMPLATES[template_name]
        template = template_config["template"]

        # 替换变量
        content = template
        for key, value in variables.items():
            placeholder = "{" + key + "}"
            content = content.replace(placeholder, str(value))

        # 个性化处理
        if rule_context:
            content = cls._personalize(content, rule_context)

        return content

    @classmethod
    def generate_from_rule(cls, rule: Dict, context: Dict) -> str:
        """
        从规则生成内容

        Args:
            rule: 匹配的规则
            context: 上下文

        Returns:
            生成的内容
        """
        template = rule.get("template", "")

        # 替换变量
        content = template
        for key, value in context.items():
            placeholder = "{" + key + "}"
            if placeholder in content:
                content = content.replace(placeholder, str(value))

        return content

    @classmethod
    def _personalize(cls, content: str, context: Dict) -> str:
        """个性化处理"""
        # 添加语气调整
        if context.get("formal"):
            content = content.replace("!", "。")
        elif context.get("friendly"):
            content = content + " 😊"

        return content

    @classmethod
    def format_reminder(
        cls,
        content: str,
        relevance: RelevanceLevel,
        format_type: str = "text"
    ) -> str:
        """
        格式化提醒

        Args:
            content: 内容
            relevance: 相关性级别
            format_type: 格式类型 (text, xml, markdown)

        Returns:
            格式化后的内容
        """
        if format_type == "xml":
            return f"<system-reminder>\n{content}\n</system-reminder>"
        elif format_type == "markdown":
            level_icons = {
                RelevanceLevel.CRITICAL: "🚨",
                RelevanceLevel.HIGH: "⚠️",
                RelevanceLevel.MEDIUM: "💡",
                RelevanceLevel.LOW: "ℹ️",
            }
            icon = level_icons.get(relevance, "📌")
            return f"{icon} **{content}**"
        else:
            return content


# ============================================================================
# 阶段4: 注入时机控制器
# ============================================================================

class InjectionController:
    """
    注入时机控制器

    功能:
    - 小溪流插入点选择
    - 用户体验优化
    - 干扰最小化原则
    """

    # 注入点配置
    INJECTION_CONFIG = {
        InjectionPoint.PRE_ITERATION: {
            "max_per_session": 5,
            "priority_boost": 0,
            "requires_user_idle": False,
        },
        InjectionPoint.POST_ITERATION: {
            "max_per_session": 10,
            "priority_boost": 1,
            "requires_user_idle": False,
        },
        InjectionPoint.PRE_TOOL_CALL: {
            "max_per_session": 3,
            "priority_boost": -1,
            "requires_user_idle": False,
        },
        InjectionPoint.POST_TOOL_CALL: {
            "max_per_session": 8,
            "priority_boost": 2,
            "requires_user_idle": False,
        },
        InjectionPoint.ON_ERROR: {
            "max_per_session": 20,
            "priority_boost": 5,
            "requires_user_idle": False,
        },
        InjectionPoint.ON_COMPLETE: {
            "max_per_session": 5,
            "priority_boost": 3,
            "requires_user_idle": False,
        },
        InjectionPoint.STREAMING: {
            "max_per_session": 15,
            "priority_boost": 0,
            "requires_user_idle": True,
        },
    }

    def __init__(self):
        self.injection_history: List[Dict] = []
        self.session_counts: Dict[InjectionPoint, int] = {
            point: 0 for point in InjectionPoint
        }

    def should_inject(
        self,
        reminder: SystemReminder,
        injection_point: InjectionPoint,
        context: ReminderContext
    ) -> bool:
        """
        判断是否应该注入

        Args:
            reminder: 待注入的提醒
            injection_point: 注入点
            context: 上下文

        Returns:
            是否应该注入
        """
        config = self.INJECTION_CONFIG.get(injection_point, {})

        # 检查会话限制
        max_per_session = config.get("max_per_session", 10)
        if self.session_counts[injection_point] >= max_per_session:
            return False

        # 检查用户空闲要求
        if config.get("requires_user_idle", False):
            if context.user_messages > 0:  # 用户最近有活动
                return False

        # 检查相关性
        if reminder.relevance == RelevanceLevel.LOW:
            # 低相关性只在特定情况下注入
            if context.iteration < 5:  # 早期迭代
                return False

        # 检查最近是否注入过
        recent_ids = [h.get("reminder_id") for h in self.injection_history[-10:]]
        if reminder.id in recent_ids:
            return False

        return True

    def select_injection_point(
        self,
        reminder: SystemReminder,
        context: ReminderContext
    ) -> Optional[InjectionPoint]:
        """
        选择最佳注入点

        Args:
            reminder: 待注入的提醒
            context: 上下文

        Returns:
            选中的注入点，或 None 表示不注入
        """
        # 根据相关性级别确定候选注入点
        candidates = []

        if reminder.relevance == RelevanceLevel.CRITICAL:
            # 关键提醒：任何点都可以
            candidates = [
                InjectionPoint.ON_ERROR,
                InjectionPoint.STREAMING,
                InjectionPoint.POST_ITERATION,
            ]
        elif reminder.relevance == RelevanceLevel.HIGH:
            # 高相关性：大部分点可用
            candidates = [
                InjectionPoint.POST_ITERATION,
                InjectionPoint.POST_TOOL_CALL,
                InjectionPoint.STREAMING,
            ]
        elif reminder.relevance == RelevanceLevel.MEDIUM:
            # 中等相关性：选择干扰较小的点
            candidates = [
                InjectionPoint.POST_ITERATION,
                InjectionPoint.ON_COMPLETE,
            ]
        else:
            # 低相关性：只在完成时注入
            candidates = [InjectionPoint.ON_COMPLETE]

        # 选择最佳候选
        for point in candidates:
            if self.should_inject(reminder, point, context):
                return point

        return None

    def record_injection(
        self,
        reminder: SystemReminder,
        injection_point: InjectionPoint
    ):
        """记录注入"""
        self.injection_history.append({
            "reminder_id": reminder.id,
            "injection_point": injection_point.value,
            "timestamp": time.time(),
        })
        self.session_counts[injection_point] += 1

    def get_optimal_delay(
        self,
        injection_point: InjectionPoint,
        context: ReminderContext
    ) -> float:
        """
        获取最优延迟（秒）

        用于用户体验优化，避免在关键时刻打断
        """
        base_delays = {
            InjectionPoint.PRE_ITERATION: 0,
            InjectionPoint.POST_ITERATION: 0.5,
            InjectionPoint.PRE_TOOL_CALL: 0,
            InjectionPoint.POST_TOOL_CALL: 0.3,
            InjectionPoint.ON_ERROR: 0,
            InjectionPoint.ON_COMPLETE: 1.0,
            InjectionPoint.STREAMING: 0.2,
        }

        delay = base_delays.get(injection_point, 0)

        # 根据上下文调整
        if context.errors:  # 有错误时减少延迟
            delay *= 0.5

        return delay


# ============================================================================
# 阶段5: System-Reminder 注入器
# ============================================================================

class SystemReminderInjector:
    """
    System-Reminder 注入器

    在消息流中动态注入 <system-reminder> 标签
    """

    def __init__(self):
        self.detector = StateDetector()
        self.injection_controller = InjectionController()
        self.generated_reminders: List[SystemReminder] = []

    def process_trigger(
        self,
        trigger_type: TriggerType,
        trigger_data: Dict,
        context: ReminderContext
    ) -> List[SystemReminder]:
        """
        处理触发器，生成提醒

        Args:
            trigger_type: 触发器类型
            trigger_data: 触发器数据
            context: 上下文

        Returns:
            生成的提醒列表
        """
        reminders = []

        # 匹配规则
        matched_rules = ConditionMatcher.match_rules(trigger_type, trigger_data)

        for match in matched_rules:
            rule = match["rule"]

            # 生成内容
            content = ContentGenerator.generate_from_rule(rule, trigger_data)

            # 确定相关性
            relevance = rule.get("relevance", RelevanceLevel.MEDIUM)

            # 创建提醒
            reminder = SystemReminder(
                id=f"reminder-{trigger_type.value}-{int(time.time() * 1000)}",
                content=content,
                relevance=relevance,
                injection_point=InjectionPoint.STREAMING,  # 默认流式注入
                trigger_type=trigger_type,
                priority=self._calculate_priority(relevance, trigger_data),
                metadata={
                    "rule_id": rule.get("id"),
                    "trigger_data": trigger_data,
                }
            )

            reminders.append(reminder)
            self.generated_reminders.append(reminder)

        return reminders

    def _calculate_priority(self, relevance: RelevanceLevel, context: Dict) -> int:
        """计算优先级"""
        base_priority = {
            RelevanceLevel.CRITICAL: 100,
            RelevanceLevel.HIGH: 75,
            RelevanceLevel.MEDIUM: 50,
            RelevanceLevel.LOW: 25,
        }

        priority = base_priority.get(relevance, 50)

        # 根据上下文调整
        if context.get("error_count", 0) > 2:
            priority += 20

        return priority

    def inject_into_stream(
        self,
        reminders: List[SystemReminder],
        context: ReminderContext,
        format_type: str = "xml"
    ) -> List[str]:
        """
        将提醒注入到消息流

        Args:
            reminders: 待注入的提醒
            context: 上下文
            format_type: 格式类型

        Returns:
            格式化后的提醒内容列表
        """
        injected = []

        for reminder in reminders:
            # 选择注入点
            injection_point = self.injection_controller.select_injection_point(
                reminder, context
            )

            if injection_point:
                # 获取延迟
                delay = self.injection_controller.get_optimal_delay(
                    injection_point, context
                )

                # 格式化
                formatted = ContentGenerator.format_reminder(
                    reminder.content,
                    reminder.relevance,
                    format_type
                )

                injected.append(formatted)

                # 记录
                self.injection_controller.record_injection(reminder, injection_point)

                # 更新上下文
                context.injected_reminders.append(reminder.id)

        return injected

    def check_and_inject(
        self,
        context: ReminderContext,
        trigger_data: Dict = None
    ) -> List[str]:
        """
        检查所有触发器并注入

        这是主要的入口方法，在 Agent Loop 中调用

        Args:
            context: 当前上下文
            trigger_data: 额外的触发数据

        Returns:
            应该注入的提醒列表
        """
        all_reminders = []

        # 1. 检查迭代次数
        iteration_check = self.detector.check_iteration(
            context.iteration, context.max_iterations
        )
        if iteration_check:
            reminders = self.process_trigger(
                TriggerType.ITERATION, iteration_check, context
            )
            all_reminders.extend(reminders)

        # 2. 检查 Token 使用
        if context.tokens_used > 0:
            token_check = self.detector.check_token_usage(
                context.tokens_used, 128000  # 假设最大 128k
            )
            if token_check:
                reminders = self.process_trigger(
                    TriggerType.TOKEN_USAGE, token_check, context
                )
                all_reminders.extend(reminders)

        # 3. 检查时间流逝
        if context.start_time > 0:
            time_check = self.detector.check_time_elapsed(context.start_time)
            if time_check:
                reminders = self.process_trigger(
                    TriggerType.TIME_ELAPSED, time_check, context
                )
                all_reminders.extend(reminders)

        # 4. 检查错误模式
        if context.last_error:
            error_check = self.detector.detect_error_pattern(context.last_error)
            if error_check:
                reminders = self.process_trigger(
                    TriggerType.ERROR_PATTERN, error_check, context
                )
                all_reminders.extend(reminders)

        # 5. 检查自定义触发
        if trigger_data:
            for trigger_type, data in trigger_data.items():
                try:
                    t_type = TriggerType(trigger_type)
                    reminders = self.process_trigger(t_type, data, context)
                    all_reminders.extend(reminders)
                except ValueError:
                    pass

        # 注入到流
        return self.inject_into_stream(all_reminders, context)


# ============================================================================
# Agent Loop 集成
# ============================================================================

class AgentLoopReminderManager:
    """
    Agent Loop 提醒管理器

    在 Agent 主循环中集成 System-Reminder 机制
    """

    def __init__(self):
        self.injector = SystemReminderInjector()
        self.context = ReminderContext()

    def update_context(
        self,
        iteration: int = None,
        max_iterations: int = None,
        tokens_used: int = None,
        tool_calls_count: int = None,
        todo_stats: Dict = None,
        error: str = None,
        user_message: str = None,
    ):
        """更新上下文"""
        if iteration is not None:
            self.context.iteration = iteration
        if max_iterations is not None:
            self.context.max_iterations = max_iterations
        if tokens_used is not None:
            self.context.tokens_used = tokens_used
        if tool_calls_count is not None:
            self.context.tool_calls_count = tool_calls_count
        if todo_stats is not None:
            self.context.pending_todos = todo_stats.get("pending", 0)
            self.context.in_progress_todos = todo_stats.get("in_progress", 0)
            self.context.completed_todos = todo_stats.get("completed", 0)
        if error is not None:
            self.context.errors.append(error)
            self.context.last_error = error
        if user_message is not None:
            self.context.user_messages += 1
            self.context.last_user_message = user_message

    def check_pre_iteration(self) -> List[str]:
        """迭代前检查"""
        self.context.start_time = self.context.start_time or time.time()
        return self.injector.check_and_inject(self.context)

    def check_post_iteration(self) -> List[str]:
        """迭代后检查"""
        return self.injector.check_and_inject(self.context)

    def check_pre_tool_call(self, tool_name: str, tool_args: Dict) -> List[str]:
        """工具调用前检查"""
        return self.injector.check_and_inject(
            self.context,
            trigger_data={"tool_call": {"name": tool_name, "args": tool_args}}
        )

    def check_post_tool_call(self, tool_name: str, result: str) -> List[str]:
        """工具调用后检查"""
        is_error = "error" in result.lower()
        return self.injector.check_and_inject(
            self.context,
            trigger_data={
                "tool_result": {
                    "name": tool_name,
                    "result": result[:200],
                    "is_error": is_error
                }
            }
        )

    def check_on_error(self, error: str) -> List[str]:
        """错误时检查"""
        self.update_context(error=error)
        return self.injector.check_and_inject(self.context)

    def check_on_complete(self) -> List[str]:
        """完成时检查"""
        return self.injector.check_and_inject(self.context)

    def get_streaming_reminders(self) -> List[str]:
        """获取流式提醒（在生成过程中注入）"""
        return self.injector.check_and_inject(self.context)

    def reset(self):
        """重置上下文"""
        self.context = ReminderContext()
        self.injector = SystemReminderInjector()


# ============================================================================
# 便捷函数
# ============================================================================

def create_reminder(
    content: str,
    relevance: RelevanceLevel = RelevanceLevel.MEDIUM,
    trigger_type: TriggerType = TriggerType.CUSTOM
) -> SystemReminder:
    """创建自定义提醒"""
    return SystemReminder(
        id=f"custom-{int(time.time() * 1000)}",
        content=content,
        relevance=relevance,
        injection_point=InjectionPoint.STREAMING,
        trigger_type=trigger_type,
    )


def format_as_xml(content: str) -> str:
    """格式化为 XML"""
    return f"<system-reminder>\n{content}\n</system-reminder>"


def format_as_markdown(content: str, relevance: RelevanceLevel) -> str:
    """格式化为 Markdown"""
    level_icons = {
        RelevanceLevel.CRITICAL: "🚨",
        RelevanceLevel.HIGH: "⚠️",
        RelevanceLevel.MEDIUM: "💡",
        RelevanceLevel.LOW: "ℹ️",
    }
    icon = level_icons.get(relevance, "📌")
    return f"{icon} {content}"
