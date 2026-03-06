"""
Todo 工具对象层 + 存储持久化层

Todo工具对象层:
- TodoWrite (Y对象): 任务创建、状态更新、优先级设置
- TodoRead (N对象): 任务查询、状态显示、进度跟踪

数据管理层:
- YJ1排序算法引擎: 猉pending(0)→in_progress(1)→completed(2)↓, 重要性排序
- 存储持久化层:
  - React状态管理: useState, useEffect, 组件更新
  - 会话状态存储: 本地存储、会话恢复、离线支持
  - 浏览器缓存: localStorage, sessionStorage
"""
import os
import json
import time
import hashlib
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field, asdict
from enum import Enum
from datetime import datetime
from pathlib import Path


# ============================================================================
# 枚举定义
# ============================================================================

class TodoStatus(Enum):
    """
    Todo 状态
    YJ1 排序: pending(0) -> in_progress(1) -> completed(2)
    """
    PENDING = 0
    IN_PROGRESS = 1
    COMPLETED = 2

    # 额外状态
    BLOCKED = 3      # 被阻塞
    CANCELLED = 4    # 已取消


class TodoPriority(Enum):
    """Todo 优先级"""
    LOW = 0
    MEDIUM = 1
    HIGH = 2
    CRITICAL = 3


class StorageType(Enum):
    """存储类型"""
    MEMORY = "memory"           # 内存存储
    LOCAL_STORAGE = "localStorage"  # 浏览器 localStorage
    SESSION_STORAGE = "sessionStorage"  # 浏览器 sessionStorage
    FILE = "file"               # 文件存储
    REDIS = "redis"              # Redis 存储


# ============================================================================
# Todo 数据类
# ============================================================================

@dataclass
class Todo:
    """
    Todo 任务对象
    """
    id: str
    content: str
    status: TodoStatus = TodoStatus.PENDING
    priority: TodoPriority = TodoPriority.MEDIUM

    # 元数据
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None

    # 关联信息
    thread_id: Optional[str] = None
    agent_id: Optional[str] = None
    parent_id: Optional[str] = None  # 父任务 ID（用于子任务）
    dependencies: List[str] = field(default_factory=list)  # 依赖的任务 ID

    # 进度追踪
    progress: float = 0.0  # 0.0 - 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.id:
            self.id = self._generate_id()

    def _generate_id(self) -> str:
        """生成唯一 ID"""
        data = f"{self.content}:{time.time()}"
        return f"todo-{hashlib.md5(data.encode()).hexdigest()[:8]}"

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "id": self.id,
            "content": self.content,
            "status": self.status.value,
            "statusText": self.status.name.lower(),
            "priority": self.priority.value,
            "priorityText": self.priority.name.lower(),
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "completedAt": self.completed_at,
            "threadId": self.thread_id,
            "agentId": self.agent_id,
            "parentId": self.parent_id,
            "dependencies": self.dependencies,
            "progress": self.progress,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "Todo":
        """从字典创建"""
        return cls(
            id=data.get("id", ""),
            content=data.get("content", ""),
            status=TodoStatus(data.get("status", 0)),
            priority=TodoPriority(data.get("priority", 1)),
            created_at=data.get("createdAt", time.time()),
            updated_at=data.get("updatedAt", time.time()),
            completed_at=data.get("completedAt"),
            thread_id=data.get("threadId"),
            agent_id=data.get("agentId"),
            parent_id=data.get("parentId"),
            dependencies=data.get("dependencies", []),
            progress=data.get("progress", 0.0),
            metadata=data.get("metadata", {}),
        )


# ============================================================================
# YJ1 排序算法引擎
# ============================================================================

class YJ1SortEngine:
    """
    YJ1 排序算法引擎

    排序规则:
    1. 状态优先级: pending(0) -> in_progress(1) -> completed(2)
    2. 重要性排序: critical > high > medium > low
    3. 时间排序: 创建时间（新优先）
    """

    @staticmethod
    def calculate_score(todo: Todo) -> float:
        """
        计算排序分数（越低越优先）

        评分规则:
        - 状态权重: pending=0, in_progress=100, completed=1000
        - 优先级权重: critical=-100, high=-10, medium=0, low=10
        - 时间权重: 创建时间越新分数越低
        """
        # 状态权重
        status_weights = {
            TodoStatus.PENDING: 0,
            TodoStatus.IN_PROGRESS: 100,
            TodoStatus.BLOCKED: 200,
            TodoStatus.COMPLETED: 1000,
            TodoStatus.CANCELLED: 1000,
        }
        status_score = status_weights.get(todo.status, 500)

        # 优先级权重（负数表示更高优先）
        priority_weights = {
            TodoPriority.CRITICAL: -100,
            TodoPriority.HIGH: -10,
            TodoPriority.MEDIUM: 0,
            TodoPriority.LOW: 10,
        }
        priority_score = priority_weights.get(todo.priority, 0)

        # 时间权重（创建时间越新分数越低）
        time_score = 0
        if todo.created_at:
            # 归一化时间（1小时内为0，超过24小时为100）
            age_hours = (time.time() - todo.created_at) / 3600
            time_score = min(100, max(0, (age_hours - 1) * 5))

        return status_score + priority_score + time_score

    @classmethod
    def sort(cls, todos: List[Todo]) -> List[Todo]:
        """排序任务列表"""
        return sorted(todos, key=cls.calculate_score)

    @classmethod
    def get_next_pending(cls, todos: List[Todo]) -> Optional[Todo]:
        """获取下一个待处理的任务"""
        pending = [t for t in todos if t.status == TodoStatus.PENDING]
        if not pending:
            return None
        sorted_pending = cls.sort(pending)
        return sorted_pending[0] if sorted_pending else None

    @classmethod
    def get_by_status(cls, todos: List[Todo]) -> Dict[str, List[Todo]]:
        """按状态分组"""
        result = {
            "pending": [],
            "in_progress": [],
            "completed": [],
            "blocked": [],
            "cancelled": [],
        }
        for todo in todos:
            status_key = todo.status.name.lower()
            if status_key in result:
                result[status_key].append(todo)
        return result

    @classmethod
    def get_by_priority(cls, todos: List[Todo]) -> Dict[str, List[Todo]]:
        """按优先级分组"""
        result = {
            "critical": [],
            "high": [],
            "medium": [],
            "low": [],
        }
        for todo in todos:
            priority_key = todo.priority.name.lower()
            if priority_key in result:
                result[priority_key].append(todo)
        return result


# ============================================================================
# 存储持久化层 - 基类
# ============================================================================

class TodoStorageBase:
    """
    Todo 存储基类
    """

    def save(self, todos: List[Todo]) -> bool:
        raise NotImplementedError

    def load(self) -> List[Todo]:
        raise NotImplementedError

    def add(self, todo: Todo) -> bool:
        raise NotImplementedError

    def update(self, todo: Todo) -> bool:
        raise NotImplementedError

    def delete(self, todo_id: str) -> bool:
        raise NotImplementedError

    def get(self, todo_id: str) -> Optional[Todo]:
        raise NotImplementedError

    def clear(self) -> bool:
        raise NotImplementedError


# ============================================================================
# 存储持久化层 - 内存存储
# ============================================================================

class MemoryTodoStorage(TodoStorageBase):
    """
    内存存储实现
    React useState 风格
    """

    def __init__(self):
        self._todos: Dict[str, Todo] = {}
        self._listeners: List[Callable] = []  # 状态监听器

    def subscribe(self, listener: Callable):
        """订阅状态变化"""
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def _notify(self):
        """通知所有监听器"""
        for listener in self._listeners:
                try:
                    listener(self.get_all())
                except Exception as e:
                    print(f"[TodoStorage] Listener error: {e}")

    def save(self, todos: List[Todo]) -> bool:
        self._todos = {t.id: t for t in todos}
        self._notify()
        return True

    def load(self) -> List[Todo]:
        return list(self._todos.values())

    def add(self, todo: Todo) -> bool:
        self._todos[todo.id] = todo
        self._notify()
        return True

    def update(self, todo: Todo) -> bool:
        if todo.id not in self._todos:
            return False
        todo.updated_at = time.time()
        self._todos[todo.id] = todo
        self._notify()
        return True

    def delete(self, todo_id: str) -> bool:
        if todo_id in self._todos:
            del self._todos[todo_id]
            self._notify()
            return True
        return False

    def get(self, todo_id: str) -> Optional[Todo]:
        return self._todos.get(todo_id)

    def get_all(self) -> List[Todo]:
        return list(self._todos.values())

    def clear(self) -> bool:
        self._todos.clear()
        self._notify()
        return True


# ============================================================================
# 存储持久化层 - 文件存储
# ============================================================================

class FileTodoStorage(TodoStorageBase):
    """
    文件存储实现
    支持会话恢复和离线支持
    """

    def __init__(self, storage_path: str = None, thread_id: str = None):
        self.storage_path = Path(storage_path or os.path.join(os.getcwd(), ".deepseek", "todos"))
        self.thread_id = thread_id
        self._ensure_dir()

    def _ensure_dir(self):
        """确保目录存在"""
        self.storage_path.mkdir(parents=True, exist_ok=True)

    def _get_file_path(self) -> Path:
        """获取存储文件路径"""
        if self.thread_id:
            return self.storage_path / f"thread-{self.thread_id}.json"
        return self.storage_path / "todos.json"

    def save(self, todos: List[Todo]) -> bool:
        try:
            data = [t.to_dict() for t in todos]
            with open(self._get_file_path(), 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"[FileTodoStorage] Save error: {e}")
            return False

    def load(self) -> List[Todo]:
        try:
            file_path = self._get_file_path()
            if not file_path.exists():
                return []
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return [Todo.from_dict(t) for t in data]
        except Exception as e:
            print(f"[FileTodoStorage] Load error: {e}")
            return []

    def add(self, todo: Todo) -> bool:
        todos = self.load()
        todos.append(todo)
        return self.save(todos)

    def update(self, todo: Todo) -> bool:
        todos = self.load()
        for i, t in enumerate(todos):
            if t.id == todo.id:
                todo.updated_at = time.time()
                todos[i] = todo
                return self.save(todos)
        return False

    def delete(self, todo_id: str) -> bool:
        todos = self.load()
        todos = [t for t in todos if t.id != todo_id]
        return self.save(todos)

    def get(self, todo_id: str) -> Optional[Todo]:
        todos = self.load()
        for t in todos:
            if t.id == todo_id:
                return t
        return None

    def clear(self) -> bool:
        try:
            file_path = self._get_file_path()
            if file_path.exists():
                file_path.unlink()
            return True
        except Exception as e:
            print(f"[FileTodoStorage] Clear error: {e}")
            return False


# ============================================================================
# 存储持久化层 - 浏览器缓存模拟
# ============================================================================

class BrowserCacheStorage(TodoStorageBase):
    """
    浏览器缓存存储模拟
    localStorage / sessionStorage 模式
    """

    def __init__(self, storage_type: StorageType = StorageType.LOCAL_STORAGE, session_id: str = None):
        self.storage_type = storage_type
        self.session_id = session_id or "default"
        self._cache: Dict[str, Any] = {}  # 内存模拟
        self._memory_storage = MemoryTodoStorage()

    def _get_cache_key(self) -> str:
        """获取缓存键"""
        prefix = "todo" if self.storage_type == StorageType.LOCAL_STORAGE else "session"
        return f"{prefix}_{self.session_id}"

    def _simulate_browser_cache(self) -> Dict:
        """
        模拟浏览器缓存行为

        localStorage: 持久化，跨会话
        sessionStorage: 会话级别，关闭浏览器后清除
        """
        cache_key = self._get_cache_key()

        if self.storage_type == StorageType.LOCAL_STORAGE:
            # localStorage: 从持久化存储加载
            file_storage = FileTodoStorage()
            cached = {}
            for todo in file_storage.load():
                cached[todo.id] = todo.to_dict()
            return cached
        else:
            # sessionStorage: 仅内存中保存
            return self._cache.get(cache_key, {})

    def save(self, todos: List[Todo]) -> bool:
        cache_key = self._get_cache_key()
        data = {t.id: t.to_dict() for t in todos}

        if self.storage_type == StorageType.LOCAL_STORAGE:
            # 同时保存到文件
            file_storage = FileTodoStorage()
            file_storage.save(todos)

        self._cache[cache_key] = data
        return True

    def load(self) -> List[Todo]:
        data = self._simulate_browser_cache()
        return [Todo.from_dict(t) for t in data.values()]

    def add(self, todo: Todo) -> bool:
        todos = self.load()
        todos.append(todo)
        return self.save(todos)

    def update(self, todo: Todo) -> bool:
        todos = self.load()
        for i, t in enumerate(todos):
            if t.id == todo.id:
                todo.updated_at = time.time()
                todos[i] = todo
                return self.save(todos)
        return False

    def delete(self, todo_id: str) -> bool:
        todos = self.load()
        todos = [t for t in todos if t.id != todo_id]
        return self.save(todos)

    def get(self, todo_id: str) -> Optional[Todo]:
        data = self._simulate_browser_cache()
        if todo_id in data:
            return Todo.from_dict(data[todo_id])
        return None

    def clear(self) -> bool:
        cache_key = self._get_cache_key()
        if cache_key in self._cache:
            del self._cache[cache_key]
        return True


# ============================================================================
# TodoWrite 工具 (Y对象) - 任务创建、状态更新、优先级设置
# ============================================================================

class TodoWriteTool:
    """
    TodoWrite 工具 (Y对象)

    功能:
    - 任务创建
    - 状态更新
    - 优先级设置
    """

    def __init__(self, storage: TodoStorageBase = None):
        self.storage = storage or MemoryTodoStorage()

    async def execute(self, args: Dict) -> str:
        """
        执行 TodoWrite

        Args:
            todos: List[Dict] - 任务列表

        Returns:
            操作结果
        """
        todos_data = args.get("todos", [])

        if not todos_data:
            return "Error: No todos provided"

        results = []

        for todo_data in todos_data:
            # 解析任务数据
            todo_id = todo_data.get("id")
            content = todo_data.get("content")
            status = todo_data.get("status")
            priority = todo_data.get("priority")

            if todo_id:
                # 更新现有任务
                existing = self.storage.get(todo_id)
                if existing:
                    if status:
                        existing.status = TodoStatus[status.upper()] if isinstance(status, str) else TodoStatus(status)
                    if priority:
                        existing.priority = TodoPriority[priority.upper()] if isinstance(priority, str) else TodoPriority(priority)
                    if content:
                        existing.content = content

                    # 如果完成，设置完成时间
                    if existing.status == TodoStatus.COMPLETED:
                        existing.completed_at = time.time()
                        existing.progress = 1.0

                    self.storage.update(existing)
                    results.append(f"Updated: {todo_id}")
                else:
                    results.append(f"Error: Todo not found: {todo_id}")
            else:
                # 创建新任务
                if not content:
                    results.append("Error: Content required for new todo")
                    continue

                new_todo = Todo(
                    id="",  # 自动生成
                    content=content,
                    status=TodoStatus[status.upper()] if status and isinstance(status, str) else TodoStatus(status or TodoStatus.PENDING),
                    priority=TodoPriority[priority.upper()] if priority and isinstance(priority, str) else TodoPriority(priority or TodoPriority.MEDIUM),
                )

                self.storage.add(new_todo)
                results.append(f"Created: {new_todo.id}")

        return "\n".join(results)


# ============================================================================
# TodoRead 工具 (N对象) - 任务查询、状态显示、进度跟踪
# ============================================================================

class TodoReadTool:
    """
    TodoRead 工具 (N对象)

    功能:
    - 任务查询
    - 状态显示
    - 进度跟踪
    """

    def __init__(self, storage: TodoStorageBase = None):
        self.storage = storage or MemoryTodoStorage()

    async def execute(self, args: Dict) -> str:
        """
        执行 TodoRead

        Args:
            status: Optional[str] - 按状态过滤
            priority: Optional[str] - 按优先级过滤
            sort: Optional[str] - 排序方式

        Returns:
            任务列表和统计信息
        """
        todos = self.storage.load()

        # 过滤
        status_filter = args.get("status")
        priority_filter = args.get("priority")

        if status_filter:
            status_enum = TodoStatus[status_filter.upper()] if isinstance(status_filter, str) else status_filter
            todos = [t for t in todos if t.status == status_enum]

        if priority_filter:
            priority_enum = TodoPriority[priority_filter.upper()] if isinstance(priority_filter, str) else priority_filter
            todos = [t for t in todos if t.priority == priority_enum]

        # 排序 (默认使用 YJ1 排序)
        sort_method = args.get("sort", "yj1")
        if sort_method == "yj1":
            todos = YJ1SortEngine.sort(todos)

        # 生成输出
        output_lines = ["# Todo List\n"]

        if not todos:
            output_lines.append("No todos found.\n")
        else:
            # 按状态分组显示
            grouped = YJ1SortEngine.get_by_status(todos)

            for status_name, status_todos in grouped.items():
                if status_todos:
                    status_icons = {
                        "pending": "⏳",
                        "in_progress": "🔄",
                        "completed": "✅",
                        "blocked": "🚫",
                        "cancelled": "❌",
                    }
                    icon = status_icons.get(status_name, "📝")
                    output_lines.append(f"\n## {icon} {status_name.upper()} ({len(status_todos)})\n")

                    for todo in status_todos:
                        priority_icons = {
                            TodoPriority.LOW: "🟢",
                            TodoPriority.MEDIUM: "🟡",
                            TodoPriority.HIGH: "🟠",
                            TodoPriority.CRITICAL: "🔴",
                        }
                        priority_icon = priority_icons.get(todo.priority, "⚪")

                        progress_bar = self._render_progress_bar(todo.progress)

                        output_lines.append(
                            f"- [{priority_icon}] {todo.content[:50]}{'...' if len(todo.content) > 50 else ''} {progress_bar}"
                        )

        # 统计信息
        output_lines.append(f"\n---\n**Total:** {len(todos)} todos")
        output_lines.append(f"**Progress:** {self._calculate_overall_progress(todos):.1%}")

        return "\n".join(output_lines)

    def _render_progress_bar(self, progress: float, width: int = 10) -> str:
        """渲染进度条"""
        filled = int(progress * width)
        bar = "█" * filled + "░" * (width - filled)
        return f"`{bar}` {progress*100:.0}%"

    def _calculate_overall_progress(self, todos: List[Todo]) -> float:
        """计算整体进度"""
        if not todos:
            return 0.0
        return sum(t.progress for t in todos) / len(todos)


# ============================================================================
# Todo 管理器 - 统一接口
# ============================================================================

class TodoManager:
    """
    Todo 管理器
    统一管理 TodoWrite 和 TodoRead 工具
    """

    def __init__(
        self,
        storage_type: StorageType = StorageType.MEMORY,
        storage_path: str = None,
        thread_id: str = None
    ):
        # 根据类型创建存储
        if storage_type == StorageType.FILE:
            self.storage = FileTodoStorage(storage_path, thread_id)
        elif storage_type in [StorageType.LOCAL_STORAGE, StorageType.SESSION_STORAGE]:
            self.storage = BrowserCacheStorage(storage_type, thread_id)
        else:
            self.storage = MemoryTodoStorage()

        # 创建工具
        self.write_tool = TodoWriteTool(self.storage)
        self.read_tool = TodoReadTool(self.storage)

    # ==================== 便捷方法 ====================

    def add_todo(
        self,
        content: str,
        priority: TodoPriority = TodoPriority.MEDIUM,
        thread_id: str = None,
        agent_id: str = None
    ) -> Todo:
        """添加任务"""
        todo = Todo(
            id="",
            content=content,
            priority=priority,
            thread_id=thread_id,
            agent_id=agent_id,
        )
        self.storage.add(todo)
        return todo

    def start_todo(self, todo_id: str) -> bool:
        """开始任务"""
        todo = self.storage.get(todo_id)
        if todo and todo.status == TodoStatus.PENDING:
            todo.status = TodoStatus.IN_PROGRESS
            todo.updated_at = time.time()
            return self.storage.update(todo)
        return False

    def complete_todo(self, todo_id: str) -> bool:
        """完成任务"""
        todo = self.storage.get(todo_id)
        if todo:
            todo.status = TodoStatus.COMPLETED
            todo.completed_at = time.time()
            todo.updated_at = time.time()
            todo.progress = 1.0
            return self.storage.update(todo)
        return False

    def block_todo(self, todo_id: str, reason: str = None) -> bool:
        """阻塞任务"""
        todo = self.storage.get(todo_id)
        if todo:
            todo.status = TodoStatus.BLOCKED
            todo.updated_at = time.time()
            if reason:
                todo.metadata["block_reason"] = reason
            return self.storage.update(todo)
        return False

    def update_progress(self, todo_id: str, progress: float) -> bool:
        """更新进度"""
        todo = self.storage.get(todo_id)
        if todo:
            todo.progress = min(1.0, max(0.0, progress))
            todo.updated_at = time.time()
            return self.storage.update(todo)
        return False

    def set_priority(self, todo_id: str, priority: TodoPriority) -> bool:
        """设置优先级"""
        todo = self.storage.get(todo_id)
        if todo:
            todo.priority = priority
            todo.updated_at = time.time()
            return self.storage.update(todo)
        return False

    def get_all(self) -> List[Todo]:
        """获取所有任务"""
        return self.storage.load()

    def get_sorted(self) -> List[Todo]:
        """获取排序后的任务"""
        return YJ1SortEngine.sort(self.get_all())

    def get_next_pending(self) -> Optional[Todo]:
        """获取下一个待处理任务"""
        return YJ1SortEngine.get_next_pending(self.get_all())

    def get_stats(self) -> Dict:
        """获取统计信息"""
        todos = self.get_all()
        grouped = YJ1SortEngine.get_by_status(todos)

        return {
            "total": len(todos),
            "pending": len(grouped["pending"]),
            "in_progress": len(grouped["in_progress"]),
            "completed": len(grouped["completed"]),
            "blocked": len(grouped["blocked"]),
            "progress": sum(t.progress for t in todos) / len(todos) if todos else 0,
        }

    def clear_completed(self) -> int:
        """清除已完成的任务"""
        todos = self.get_all()
        count = 0
        for todo in todos:
            if todo.status == TodoStatus.COMPLETED:
                self.storage.delete(todo.id)
                count += 1
        return count

    # ==================== 工具执行接口 ====================

    async def write(self, todos: List[Dict]) -> str:
        """执行 TodoWrite"""
        return await self.write_tool.execute({"todos": todos})

    async def read(self, status: str = None, priority: str = None) -> str:
        """执行 TodoRead"""
        args = {}
        if status:
            args["status"] = status
        if priority:
            args["priority"] = priority
        return await self.read_tool.execute(args)
