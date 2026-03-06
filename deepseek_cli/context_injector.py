"""
上下文注入和恢复机制
完整的文件引用检测、安全检测、智能推荐、容量控制系统
"""
import os
import re
import json
import time
import hashlib
import ast
from typing import Dict, List, Optional, Tuple, Set, Any
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from collections import defaultdict


class TriggerType(Enum):
    """触发类型"""
    EXPLICIT_MENTION = "explicit_mention"      # 用户显式提及
    AUTO_DETECTION = "auto_detection"          # 系统自动检测
    DEPENDENCY_TRACE = "dependency_trace"      # 依赖追踪
    HISTORY_CONTEXT = "history_context"        # 历史上下文


class FilePriority(Enum):
    """文件优先级"""
    CRITICAL = 1     # 核心文件（主入口、配置）
    HIGH = 2         # 直接相关文件
    MEDIUM = 3       # 依赖文件
    LOW = 4          # 参考文件


@dataclass
class FileInfo:
    """文件信息"""
    path: str
    absolute_path: str
    exists: bool
    is_readable: bool
    size: int
    extension: str
    language: str
    priority: FilePriority
    relevance_score: float
    tokens: int = 0
    content: str = ""
    formatted_content: str = ""
    trigger_type: TriggerType = TriggerType.AUTO_DETECTION
    error: str = ""


@dataclass
class InjectionResult:
    """注入结果"""
    success: bool
    files: List[FileInfo]
    total_tokens: int
    total_files: int
    rejected_files: List[Dict]
    warnings: List[str]
    injection_id: str


class FileReferenceDetector:
    """
    文件引用检测器
    检测用户输入中的文件引用
    """

    # 文件引用模式
    PATTERNS = {
        # 显式文件路径
        "explicit_path": [
            r'(?:^|\s|["\'])([a-zA-Z0-9_\-./]+\.[a-zA-Z]{1,10})(?:\s|["\']|$)',
            r'(?:^|\s)([a-zA-Z0-9_\-/]+/)+[a-zA-Z0-9_\-]+\.[a-zA-Z]{1,10}',
        ],
        # 代码引用
        "code_reference": [
            r'`([^`]+\.[a-zA-Z]{1,10})`',
            r'```\w*\n?([^\n]+\.[a-zA-Z]{1,10})',
        ],
        # 特殊关键词
        "keywords": [
            r'(?:file|文件|path|路径)[:\s]+["\']?([^"\':\s]+\.[a-zA-Z]{1,10})',
            r'(?:open|read|write|edit|打开|读取|写入|编辑)[:\s]+["\']?([^"\':\s]+\.[a-zA-Z]{1,10})',
            r'(?:in|在)[:\s]+["\']?([^"\':\s]+\.[a-zA-Z]{1,10})',
        ],
        # 引号包裹
        "quoted": [
            r'"([^"]+\.[a-zA-Z]{1,10})"',
            r"'([^']+\.[a-zA-Z]{1,10})'",
        ],
    }

    # 常见文件扩展名
    KNOWN_EXTENSIONS = {
        '.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.go', '.rs', '.cpp', '.c', '.h',
        '.html', '.css', '.scss', '.less', '.json', '.yaml', '.yml', '.xml', '.toml',
        '.md', '.txt', '.rst', '.sh', '.bash', '.zsh', '.fish',
        '.sql', '.prisma', '.graphql',
        '.vue', '.svelte', '.astro',
        '.dockerfile', '.makefile', '.cmake',
        '.env', '.gitignore', '.dockerignore',
    }

    def __init__(self, working_dir: str):
        self.working_dir = working_dir

    def detect(self, text: str) -> List[Tuple[str, TriggerType]]:
        """
        检测文件引用

        Returns:
            List of (file_path, trigger_type)
        """
        detected = []
        seen = set()

        for pattern_type, patterns in self.PATTERNS.items():
            for pattern in patterns:
                for match in re.finditer(pattern, text, re.IGNORECASE):
                    file_path = match.group(1).strip()

                    # 清理路径
                    file_path = self._clean_path(file_path)

                    if not file_path or file_path in seen:
                        continue

                    # 验证是否是有效文件路径
                    if self._is_valid_file_reference(file_path):
                        trigger = TriggerType.EXPLICIT_MENTION if pattern_type in [
                            "explicit_path", "quoted"
                        ] else TriggerType.AUTO_DETECTION

                        detected.append((file_path, trigger))
                        seen.add(file_path)

        return detected

    def _clean_path(self, path: str) -> str:
        """清理路径"""
        # 移除多余的点和斜杠
        path = path.strip('./')
        # 移除末尾标点
        path = re.sub(r'[,;.!?)]+$', '', path)
        return path

    def _is_valid_file_reference(self, path: str) -> bool:
        """验证是否是有效的文件引用"""
        # 检查扩展名
        _, ext = os.path.splitext(path)
        if ext.lower() not in self.KNOWN_EXTENSIONS:
            return False

        # 检查路径格式
        if not re.match(r'^[a-zA-Z0-9_\-./]+$', path):
            return False

        # 检查长度
        if len(path) > 500 or len(path) < 3:
            return False

        return True


class SecurityValidator:
    """
    安全验证器
    路径验证、权限检测、文件存在检查
    """

    # 敏感文件模式
    SENSITIVE_PATTERNS = [
        r'\.env',
        r'\.pem$',
        r'\.key$',
        r'\.p12$',
        r'\.pfx$',
        r'id_rsa',
        r'id_ed25519',
        r'\.git/config',
        r'\.ssh/',
        r'credentials',
        r'secrets?',
        r'password',
        r'token',
    ]

    # 禁止访问的目录
    BLOCKED_DIRS = [
        '/etc/passwd',
        '/etc/shadow',
        '/etc/ssh/',
        '~/.ssh/',
        '/root/',
    ]

    def __init__(self, working_dir: str, allowed_paths: List[str] = None):
        self.working_dir = os.path.abspath(working_dir)
        self.allowed_paths = allowed_paths or [self.working_dir]

    def validate(self, file_path: str) -> Dict[str, Any]:
        """
        验证文件路径

        Returns:
            {
                "valid": bool,
                "absolute_path": str,
                "exists": bool,
                "is_readable": bool,
                "is_sensitive": bool,
                "error": str
            }
        """
        result = {
            "valid": False,
            "absolute_path": "",
            "exists": False,
            "is_readable": False,
            "is_sensitive": False,
            "error": ""
        }

        try:
            # 解析绝对路径
            if os.path.isabs(file_path):
                abs_path = os.path.normpath(file_path)
            else:
                abs_path = os.path.normpath(os.path.join(self.working_dir, file_path))

            result["absolute_path"] = abs_path

            # 检查路径遍历攻击
            if not self._is_path_allowed(abs_path):
                result["error"] = "Path not in allowed directories"
                return result

            # 检查禁止目录
            for blocked in self.BLOCKED_DIRS:
                blocked_abs = os.path.expanduser(blocked)
                if abs_path.startswith(blocked_abs):
                    result["error"] = "Access to this directory is blocked"
                    return result

            # 检查敏感文件
            for pattern in self.SENSITIVE_PATTERNS:
                if re.search(pattern, abs_path, re.IGNORECASE):
                    result["is_sensitive"] = True
                    result["error"] = "Sensitive file detected, requires explicit approval"
                    return result

            # 检查文件存在
            if not os.path.exists(abs_path):
                result["error"] = "File does not exist"
                return result

            result["exists"] = True

            # 检查是否是文件
            if not os.path.isfile(abs_path):
                result["error"] = "Path is not a file"
                return result

            # 检查可读性
            if not os.access(abs_path, os.R_OK):
                result["error"] = "File is not readable"
                return result

            result["is_readable"] = True
            result["valid"] = True

        except Exception as e:
            result["error"] = str(e)

        return result

    def _is_path_allowed(self, abs_path: str) -> bool:
        """检查路径是否在允许的目录内"""
        for allowed in self.allowed_paths:
            allowed_abs = os.path.abspath(allowed)
            if abs_path.startswith(allowed_abs):
                return True
        return False


class DependencyAnalyzer:
    """
    依赖分析器
    分析文件依赖关系和关联度
    """

    # 语言对应的导入语句模式
    IMPORT_PATTERNS = {
        'python': [
            r'^\s*import\s+([a-zA-Z0-9_.]+)',
            r'^\s*from\s+([a-zA-Z0-9_.]+)\s+import',
        ],
        'javascript': [
            r'^\s*import\s+.*?from\s+["\']([^"\']+)["\']',
            r'^\s*require\s*\(\s*["\']([^"\']+)["\']\s*\)',
        ],
        'typescript': [
            r'^\s*import\s+.*?from\s+["\']([^"\']+)["\']',
            r'^\s*import\s+["\']([^"\']+)["\']',
        ],
        'go': [
            r'^\s*import\s+["\']([^"\']+)["\']',
            r'^\s*import\s*\(\s*["\']([^"\']+)["\']',
        ],
        'java': [
            r'^\s*import\s+([a-zA-Z0-9_.]+);',
        ],
    }

    def __init__(self, working_dir: str):
        self.working_dir = working_dir
        self.dependency_cache: Dict[str, Set[str]] = {}
        self.reverse_deps: Dict[str, Set[str]] = defaultdict(set)

    def analyze_file(self, file_path: str) -> Dict:
        """
        分析单个文件

        Returns:
            {
                "imports": List[str],
                "exports": List[str],
                "local_deps": List[str],
                "external_deps": List[str],
            }
        """
        abs_path = os.path.join(self.working_dir, file_path) if not os.path.isabs(file_path) else file_path

        result = {
            "imports": [],
            "exports": [],
            "local_deps": [],
            "external_deps": [],
        }

        if not os.path.exists(abs_path):
            return result

        # 确定语言
        ext = os.path.splitext(file_path)[1].lower()
        lang_map = {'.py': 'python', '.js': 'javascript', '.ts': 'typescript', '.go': 'go', '.java': 'java'}
        language = lang_map.get(ext)

        if not language or language not in self.IMPORT_PATTERNS:
            return result

        try:
            with open(abs_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            # 提取导入
            for pattern in self.IMPORT_PATTERNS[language]:
                for match in re.finditer(pattern, content, re.MULTILINE):
                    import_path = match.group(1)
                    result["imports"].append(import_path)

                    # 检查是否是本地依赖
                    local_dep = self._resolve_local_dependency(file_path, import_path, language)
                    if local_dep:
                        result["local_deps"].append(local_dep)
                        self.reverse_deps[local_dep].add(file_path)
                    else:
                        result["external_deps"].append(import_path)

            # 对于 Python，提取导出
            if language == 'python':
                result["exports"] = self._extract_python_exports(content)

        except Exception as e:
            pass

        return result

    def _resolve_local_dependency(self, source_file: str, import_path: str, language: str) -> Optional[str]:
        """解析本地依赖"""
        if language == 'python':
            # 转换 module.path 为 module/path.py
            parts = import_path.split('.')
            possible_paths = [
                os.path.join(*parts) + '.py',
                os.path.join(*parts, '__init__.py'),
            ]

            for path in possible_paths:
                full_path = os.path.join(self.working_dir, path)
                if os.path.exists(full_path):
                    return path

        elif language in ['javascript', 'typescript']:
            # 处理相对路径
            if import_path.startswith('.'):
                source_dir = os.path.dirname(source_file)
                resolved = os.path.normpath(os.path.join(source_dir, import_path))

                for ext in ['', '.js', '.ts', '.jsx', '.tsx', '/index.js', '/index.ts']:
                    full_path = os.path.join(self.working_dir, resolved + ext)
                    if os.path.exists(full_path):
                        return resolved + ext

        return None

    def _extract_python_exports(self, content: str) -> List[str]:
        """提取 Python 导出（__all__ 和顶级定义）"""
        exports = []

        # 提取 __all__
        all_match = re.search(r'__all__\s*=\s*\[(.*?)\]', content, re.DOTALL)
        if all_match:
            items = re.findall(r'["\']([^"\']+)["\']', all_match.group(1))
            exports.extend(items)

        # 提取顶级函数和类
        exports.extend(re.findall(r'^(?:def|class)\s+([a-zA-Z0-9_]+)', content, re.MULTILINE))

        return list(set(exports))

    def get_related_files(self, file_path: str, max_depth: int = 2) -> List[Tuple[str, int]]:
        """
        获取相关文件

        Returns:
            List of (file_path, depth)
        """
        related = []
        visited = set()

        def _trace(path: str, depth: int):
            if depth > max_depth or path in visited:
                return

            visited.add(path)

            # 获取此文件的依赖
            analysis = self.analyze_file(path)

            for dep in analysis.get("local_deps", []):
                related.append((dep, depth))
                _trace(dep, depth + 1)

        _trace(file_path, 1)
        return related


class RelevanceCalculator:
    """
    关联度计算器
    计算文件与用户请求的关联度
    """

    def __init__(self):
        self.keyword_weights = {
            "function_name": 0.3,
            "class_name": 0.25,
            "import_match": 0.2,
            "path_similarity": 0.15,
            "extension_match": 0.1,
        }

    def calculate(
        self,
        file_path: str,
        query: str,
        explicit_mentions: List[str] = None,
        analysis: Dict = None
    ) -> float:
        """
        计算关联度分数 (0-1)

        Args:
            file_path: 文件路径
            query: 用户查询
            explicit_mentions: 显式提及的文件
            analysis: 文件分析结果

        Returns:
            关联度分数
        """
        score = 0.0
        query_lower = query.lower()
        file_lower = file_path.lower()

        # 1. 显式提及检查
        if explicit_mentions:
            for mention in explicit_mentions:
                if mention.lower() in file_lower:
                    score += 0.5
                    break

        # 2. 路径相似度
        query_words = set(re.findall(r'\w+', query_lower))
        path_words = set(re.findall(r'\w+', file_lower))
        if query_words & path_words:
            score += len(query_words & path_words) / len(query_words) * 0.3

        # 3. 内容匹配（如果有分析结果）
        if analysis:
            # 检查导出的函数/类是否在查询中
            exports = analysis.get("exports", [])
            for export in exports:
                if export.lower() in query_lower:
                    score += 0.2
                    break

        # 4. 扩展名匹配
        ext = os.path.splitext(file_path)[1].lower()
        if 'python' in query_lower and ext == '.py':
            score += 0.1
        elif 'javascript' in query_lower and ext in ['.js', '.jsx']:
            score += 0.1
        elif 'typescript' in query_lower and ext in ['.ts', '.tsx']:
            score += 0.1

        return min(1.0, score)


class CapacityController:
    """
    容量控制器
    最大20文件，每个8k token，总计32k限制
    """

    def __init__(
        self,
        max_files: int = 20,
        max_tokens_per_file: int = 8000,
        max_total_tokens: int = 32000
    ):
        self.max_files = max_files
        self.max_tokens_per_file = max_tokens_per_file
        self.max_total_tokens = max_total_tokens

    def estimate_tokens(self, content: str) -> int:
        """估算 token 数量"""
        chinese_chars = sum(1 for c in content if '\u4e00' <= c <= '\u9fff')
        other_chars = len(content) - chinese_chars
        return int(chinese_chars / 1.5 + other_chars / 4) + 10

    def control(
        self,
        files: List[FileInfo],
        preserve_priority: bool = True
    ) -> Tuple[List[FileInfo], List[Dict]]:
        """
        容量控制

        Returns:
            (accepted_files, rejected_files)
        """
        accepted = []
        rejected = []
        total_tokens = 0

        # 按优先级和关联度排序
        if preserve_priority:
            files = sorted(files, key=lambda f: (f.priority.value, -f.relevance_score))

        for file_info in files:
            # 检查文件数量限制
            if len(accepted) >= self.max_files:
                rejected.append({
                    "path": file_info.path,
                    "reason": f"Exceeded max files limit ({self.max_files})"
                })
                continue

            # 检查单个文件 token 限制
            file_tokens = file_info.tokens or self.estimate_tokens(file_info.content)

            if file_tokens > self.max_tokens_per_file:
                # 截断内容
                truncated_content = self._truncate_to_token_limit(
                    file_info.content,
                    self.max_tokens_per_file
                )
                file_info.content = truncated_content
                file_info.tokens = self.max_tokens_per_file
                file_tokens = self.max_tokens_per_file

            # 检查总 token 限制
            if total_tokens + file_tokens > self.max_total_tokens:
                # 尝试部分包含
                remaining = self.max_total_tokens - total_tokens
                if remaining > 1000:  # 至少保留 1000 tokens
                    file_info.content = self._truncate_to_token_limit(
                        file_info.content,
                        remaining
                    )
                    file_info.tokens = remaining
                    accepted.append(file_info)
                    total_tokens += remaining
                else:
                    rejected.append({
                        "path": file_info.path,
                        "reason": f"Exceeded total tokens limit ({self.max_total_tokens})"
                    })
                continue

            accepted.append(file_info)
            total_tokens += file_tokens

        return accepted, rejected

    def _truncate_to_token_limit(self, content: str, max_tokens: int) -> str:
        """截断内容到指定 token 限制"""
        # 估算每个 token 约等于 3 个字符（保守估计）
        max_chars = max_tokens * 3

        if len(content) <= max_chars:
            return content

        # 保留开头和结尾
        head_chars = int(max_chars * 0.7)
        tail_chars = int(max_chars * 0.3)

        truncated = (
            content[:head_chars] +
            f"\n\n... [截断: {len(content) - max_chars} 字符] ...\n\n" +
            content[-tail_chars:]
        )
        return truncated


class ContentFormatter:
    """
    内容格式化器
    格式化处理、语法高亮、行号显示
    """

    # 语言标识
    LANGUAGE_MAP = {
        '.py': 'python',
        '.js': 'javascript',
        '.ts': 'typescript',
        '.jsx': 'jsx',
        '.tsx': 'tsx',
        '.java': 'java',
        '.go': 'go',
        '.rs': 'rust',
        '.cpp': 'cpp',
        '.c': 'c',
        '.h': 'c',
        '.hpp': 'cpp',
        '.html': 'html',
        '.css': 'css',
        '.scss': 'scss',
        '.json': 'json',
        '.yaml': 'yaml',
        '.yml': 'yaml',
        '.xml': 'xml',
        '.md': 'markdown',
        '.sql': 'sql',
        '.sh': 'bash',
        '.vue': 'vue',
    }

    def format(self, file_info: FileInfo, show_line_numbers: bool = True) -> str:
        """
        格式化文件内容
        """
        content = file_info.content

        if not content:
            return ""

        # 获取语言
        language = self.LANGUAGE_MAP.get(file_info.extension, '')

        # 添加行号
        if show_line_numbers:
            lines = content.split('\n')
            max_line_num = len(lines)
            line_num_width = len(str(max_line_num))

            formatted_lines = []
            for i, line in enumerate(lines, 1):
                line_num = str(i).rjust(line_num_width)
                formatted_lines.append(f"{line_num} | {line}")

            content = '\n'.join(formatted_lines)

        # 构建格式化输出
        header = self._build_header(file_info)
        footer = self._build_footer(file_info)

        formatted = f"""{header}
```{language}
{content}
```
{footer}"""
        return formatted

    def _build_header(self, file_info: FileInfo) -> str:
        """构建文件头"""
        parts = [f"### 📄 {file_info.path}"]

        meta = []
        if file_info.size:
            meta.append(f"大小: {self._format_size(file_info.size)}")
        if file_info.tokens:
            meta.append(f"~{file_info.tokens} tokens")
        if file_info.language:
            meta.append(f"语言: {file_info.language}")
        if file_info.trigger_type:
            trigger_names = {
                TriggerType.EXPLICIT_MENTION: "用户提及",
                TriggerType.AUTO_DETECTION: "自动检测",
                TriggerType.DEPENDENCY_TRACE: "依赖追踪",
                TriggerType.HISTORY_CONTEXT: "历史上下文"
            }
            meta.append(f"来源: {trigger_names.get(file_info.trigger_type, '未知')}")

        if meta:
            parts.append(f"> {' | '.join(meta)}")

        return '\n'.join(parts)

    def _build_footer(self, file_info: FileInfo) -> str:
        """构建文件尾"""
        if file_info.error:
            return f"\n⚠️ {file_info.error}"
        return ""

    def _format_size(self, size: int) -> str:
        """格式化文件大小"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f}{unit}"
            size /= 1024
        return f"{size:.1f}TB"


class ContextInjector:
    """
    上下文注入器
    整合所有组件，实现完整的注入流程
    """

    def __init__(
        self,
        working_dir: str,
        max_files: int = 20,
        max_tokens_per_file: int = 8000,
        max_total_tokens: int = 32000,
        allowed_paths: List[str] = None
    ):
        self.working_dir = working_dir

        # 初始化组件
        self.detector = FileReferenceDetector(working_dir)
        self.validator = SecurityValidator(working_dir, allowed_paths)
        self.dependency_analyzer = DependencyAnalyzer(working_dir)
        self.relevance_calculator = RelevanceCalculator()
        self.capacity_controller = CapacityController(
            max_files, max_tokens_per_file, max_total_tokens
        )
        self.formatter = ContentFormatter()

        # 文件信息缓存
        self.file_cache: Dict[str, FileInfo] = {}

    def inject(
        self,
        user_input: str,
        history_files: List[str] = None,
        additional_files: List[str] = None
    ) -> InjectionResult:
        """
        执行上下文注入

        Args:
            user_input: 用户输入
            history_files: 历史相关文件
            additional_files: 额外指定的文件

        Returns:
            InjectionResult
        """
        injection_id = f"inj-{int(time.time() * 1000)}"
        warnings = []
        all_files = []

        # ========== Phase 1: 文件引用检测 ==========
        print("[ContextInjector] Phase 1: 检测文件引用...")

        # 1.1 显式提及
        detected = self.detector.detect(user_input)
        explicit_mentions = [path for path, trigger in detected if trigger == TriggerType.EXPLICIT_MENTION]

        # 1.2 添加检测到的文件
        for path, trigger in detected:
            file_info = self._create_file_info(path, trigger)
            if file_info:
                all_files.append(file_info)

        # 1.3 添加额外指定的文件
        if additional_files:
            for path in additional_files:
                file_info = self._create_file_info(path, TriggerType.AUTO_DETECTION)
                if file_info:
                    all_files.append(file_info)

        # ========== Phase 2: 安全检测 ==========
        print(f"[ContextInjector] Phase 2: 安全检测 ({len(all_files)} 文件)...")

        valid_files = []
        for file_info in all_files:
            if file_info.exists and file_info.is_readable:
                valid_files.append(file_info)
            elif file_info.error:
                warnings.append(f"{file_info.path}: {file_info.error}")

        # ========== Phase 3: 依赖分析和智能推荐 ==========
        print("[ContextInjector] Phase 3: 依赖分析和智能推荐...")

        # 分析每个文件的依赖
        for file_info in valid_files:
            analysis = self.dependency_analyzer.analyze_file(file_info.path)
            file_info.metadata = {"analysis": analysis}

            # 添加依赖文件
            for dep_path in analysis.get("local_deps", []):
                if not any(f.path == dep_path for f in valid_files):
                    dep_info = self._create_file_info(dep_path, TriggerType.DEPENDENCY_TRACE)
                    if dep_info and dep_info.exists:
                        valid_files.append(dep_info)

        # ========== Phase 4: 关联度计算和优先级排序 ==========
        print("[ContextInjector] Phase 4: 关联度计算...")

        for file_info in valid_files:
            analysis = getattr(file_info, 'metadata', {}).get("analysis", {})
            file_info.relevance_score = self.relevance_calculator.calculate(
                file_info.path,
                user_input,
                explicit_mentions,
                analysis
            )

            # 设置优先级
            if file_info.trigger_type == TriggerType.EXPLICIT_MENTION:
                file_info.priority = FilePriority.CRITICAL
            elif file_info.relevance_score > 0.5:
                file_info.priority = FilePriority.HIGH
            elif file_info.trigger_type == TriggerType.DEPENDENCY_TRACE:
                file_info.priority = FilePriority.MEDIUM
            else:
                file_info.priority = FilePriority.LOW

        # ========== Phase 5: 容量控制 ==========
        print("[ContextInjector] Phase 5: 容量控制...")

        accepted, rejected = self.capacity_controller.control(valid_files)

        # ========== Phase 6: 内容注入和格式化 ==========
        print("[ContextInjector] Phase 6: 内容注入和格式化...")

        for file_info in accepted:
            # 读取内容
            if not file_info.content:
                try:
                    with open(file_info.absolute_path, 'r', encoding='utf-8', errors='replace') as f:
                        file_info.content = f.read()
                except Exception as e:
                    file_info.error = str(e)
                    continue

            # 计算 tokens
            file_info.tokens = self.capacity_controller.estimate_tokens(file_info.content)

            # 格式化
            file_info.formatted_content = self.formatter.format(file_info)

        # 计算总 tokens
        total_tokens = sum(f.tokens for f in accepted if f.tokens)

        return InjectionResult(
            success=len(accepted) > 0,
            files=accepted,
            total_tokens=total_tokens,
            total_files=len(accepted),
            rejected_files=rejected,
            warnings=warnings,
            injection_id=injection_id
        )

    def _create_file_info(self, path: str, trigger_type: TriggerType) -> Optional[FileInfo]:
        """创建文件信息"""
        # 检查缓存
        cache_key = f"{path}:{trigger_type.value}"
        if cache_key in self.file_cache:
            return self.file_cache[cache_key]

        # 安全验证
        validation = self.validator.validate(path)

        # 确定语言
        ext = os.path.splitext(path)[1].lower()
        lang_map = {
            '.py': 'Python', '.js': 'JavaScript', '.ts': 'TypeScript',
            '.java': 'Java', '.go': 'Go', '.rs': 'Rust',
            '.html': 'HTML', '.css': 'CSS', '.json': 'JSON',
            '.md': 'Markdown', '.yaml': 'YAML', '.yml': 'YAML',
        }

        file_info = FileInfo(
            path=path,
            absolute_path=validation.get("absolute_path", ""),
            exists=validation.get("exists", False),
            is_readable=validation.get("is_readable", False),
            size=0,
            extension=ext,
            language=lang_map.get(ext, "Unknown"),
            priority=FilePriority.MEDIUM,
            relevance_score=0.0,
            trigger_type=trigger_type,
            error=validation.get("error", "")
        )

        # 获取文件大小
        if validation.get("exists"):
            try:
                file_info.size = os.path.getsize(validation["absolute_path"])
            except:
                pass

        # 缓存
        self.file_cache[cache_key] = file_info
        return file_info

    def build_context_string(self, result: InjectionResult) -> str:
        """构建上下文字符串"""
        if not result.files:
            return ""

        parts = ["## 📂 文件上下文\n"]
        parts.append(f"> 共加载 {result.total_files} 个文件，约 {result.total_tokens} tokens\n")

        for file_info in result.files:
            if file_info.formatted_content:
                parts.append(file_info.formatted_content)
                parts.append("\n---\n")

        if result.warnings:
            parts.append("\n### ⚠️ 警告\n")
            for warning in result.warnings:
                parts.append(f"- {warning}\n")

        if result.rejected_files:
            parts.append("\n### 🚫 被拒绝的文件\n")
            for rejected in result.rejected_files:
                parts.append(f"- {rejected['path']}: {rejected['reason']}\n")

        return '\n'.join(parts)
