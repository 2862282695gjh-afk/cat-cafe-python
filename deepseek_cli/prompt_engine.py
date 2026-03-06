"""
Prompt Augmentation Engine - 提示词增强引擎
负责动态构建和优化 prompt，注入上下文
"""
import os
import json
import subprocess
from typing import Dict, List, Optional, Any
from pathlib import Path
from dataclasses import dataclass


@dataclass
class ProjectContext:
    """项目上下文"""
    root_path: str
    language: str = "unknown"
    framework: str = "unknown"
    has_git: bool = False
    git_branch: str = ""
    git_status: str = ""
    dependencies: Dict[str, str] = None
    directory_structure: str = ""
    relevant_files: List[str] = None


class PromptAugmentationEngine:
    """
    提示词增强引擎

    功能：
    1. 项目上下文收集 (目录结构、依赖、git 状态)
    2. 相关代码片段提取
    3. 动态系统提示词构建
    4. 历史对话压缩
    """

    def __init__(self, working_dir: str = None, max_context_tokens: int = 8000):
        self.working_dir = working_dir or os.getcwd()
        self.max_context_tokens = max_context_tokens
        self.project_context: Optional[ProjectContext] = None
        self.file_cache: Dict[str, str] = {}

    def analyze_project(self) -> ProjectContext:
        """分析项目结构"""
        context = ProjectContext(root_path=self.working_dir)

        # 检测语言和框架
        context = self._detect_language_and_framework(context)

        # 获取 git 信息
        context = self._get_git_info(context)

        # 获取目录结构
        context.directory_structure = self._get_directory_structure()

        # 获取依赖
        context.dependencies = self._get_dependencies(context.language)

        self.project_context = context
        return context

    def _detect_language_and_framework(self, context: ProjectContext) -> ProjectContext:
        """检测项目语言和框架"""
        # 检测 Python
        if os.path.exists(os.path.join(self.working_dir, "requirements.txt")):
            context.language = "python"
            if os.path.exists(os.path.join(self.working_dir, "flask")):
                context.framework = "flask"
            elif os.path.exists(os.path.join(self.working_dir, "django")):
                context.framework = "django"
            elif os.path.exists(os.path.join(self.working_dir, "fastapi")):
                context.framework = "fastapi"

        # 检测 JavaScript/TypeScript
        elif os.path.exists(os.path.join(self.working_dir, "package.json")):
            try:
                with open(os.path.join(self.working_dir, "package.json")) as f:
                    pkg = json.load(f)
                    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}

                    if "typescript" in deps:
                        context.language = "typescript"
                    else:
                        context.language = "javascript"

                    if "react" in deps:
                        context.framework = "react"
                    elif "vue" in deps:
                        context.framework = "vue"
                    elif "next" in deps:
                        context.framework = "nextjs"
                    elif "express" in deps:
                        context.framework = "express"
            except:
                context.language = "javascript"

        # 检测 Go
        elif os.path.exists(os.path.join(self.working_dir, "go.mod")):
            context.language = "go"

        # 检测 Rust
        elif os.path.exists(os.path.join(self.working_dir, "Cargo.toml")):
            context.language = "rust"

        # 检测 Java
        elif os.path.exists(os.path.join(self.working_dir, "pom.xml")):
            context.language = "java"
            context.framework = "maven"
        elif os.path.exists(os.path.join(self.working_dir, "build.gradle")):
            context.language = "java"
            context.framework = "gradle"

        return context

    def _get_git_info(self, context: ProjectContext) -> ProjectContext:
        """获取 Git 信息"""
        git_dir = os.path.join(self.working_dir, ".git")
        if not os.path.exists(git_dir):
            return context

        context.has_git = True

        try:
            # 获取当前分支
            result = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=self.working_dir,
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                context.git_branch = result.stdout.strip()

            # 获取状态
            result = subprocess.run(
                ["git", "status", "--short"],
                cwd=self.working_dir,
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                context.git_status = result.stdout.strip()

        except Exception:
            pass

        return context

    def _get_directory_structure(self, max_depth: int = 3) -> str:
        """获取目录结构"""
        structure = []
        ignore_dirs = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', 'dist', 'build', '.idea', '.vscode'}

        for root, dirs, files in os.walk(self.working_dir):
            # 过滤忽略的目录
            dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith('.')]

            # 计算深度
            rel_path = os.path.relpath(root, self.working_dir)
            depth = 0 if rel_path == '.' else rel_path.count(os.sep) + 1

            if depth > max_depth:
                continue

            # 添加目录/文件
            indent = "  " * depth
            if rel_path != '.':
                structure.append(f"{indent}📁 {os.path.basename(root)}/")

            for file in files[:20]:  # 每个目录最多显示 20 个文件
                if not file.startswith('.'):
                    # 根据扩展名选择图标
                    ext = os.path.splitext(file)[1]
                    icon = self._get_file_icon(ext)
                    structure.append(f"{indent}  {icon} {file}")

        return '\n'.join(structure[:100])  # 最多 100 行

    def _get_file_icon(self, ext: str) -> str:
        """根据文件扩展名返回图标"""
        icons = {
            '.py': '🐍',
            '.js': '📜',
            '.ts': '📘',
            '.jsx': '⚛️',
            '.tsx': '⚛️',
            '.go': '🔵',
            '.rs': '🦀',
            '.java': '☕',
            '.html': '🌐',
            '.css': '🎨',
            '.json': '📋',
            '.md': '📝',
            '.yaml': '⚙️',
            '.yml': '⚙️',
            '.sh': '🖥️',
            '.sql': '🗃️',
        }
        return icons.get(ext, '📄')

    def _get_dependencies(self, language: str) -> Dict[str, str]:
        """获取项目依赖"""
        deps = {}

        if language == "python":
            req_file = os.path.join(self.working_dir, "requirements.txt")
            if os.path.exists(req_file):
                try:
                    with open(req_file) as f:
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith('#'):
                                if '==' in line:
                                    name, version = line.split('==', 1)
                                    deps[name] = version
                                elif '>=' in line:
                                    name, version = line.split('>=', 1)
                                    deps[name] = f">={version}"
                                else:
                                    deps[line] = "latest"
                except:
                    pass

        elif language in ["javascript", "typescript"]:
            pkg_file = os.path.join(self.working_dir, "package.json")
            if os.path.exists(pkg_file):
                try:
                    with open(pkg_file) as f:
                        pkg = json.load(f)
                        deps.update(pkg.get("dependencies", {}))
                except:
                    pass

        return deps

    def build_system_prompt(
        self,
        base_prompt: str,
        include_project_context: bool = True,
        include_git_info: bool = True,
        include_directory_structure: bool = True
    ) -> str:
        """
        构建增强的系统提示词
        """
        if not self.project_context:
            self.analyze_project()

        ctx = self.project_context
        sections = [base_prompt]

        # 添加项目上下文
        if include_project_context:
            sections.append("\n## 项目上下文")
            sections.append(f"- 工作目录: {ctx.root_path}")
            sections.append(f"- 项目语言: {ctx.language}")
            if ctx.framework != "unknown":
                sections.append(f"- 框架: {ctx.framework}")

        # 添加 Git 信息
        if include_git_info and ctx.has_git:
            sections.append("\n## Git 状态")
            sections.append(f"- 当前分支: {ctx.git_branch}")
            if ctx.git_status:
                sections.append(f"- 变更状态:\n```\n{ctx.git_status}\n```")

        # 添加目录结构
        if include_directory_structure and ctx.directory_structure:
            sections.append("\n## 项目结构")
            sections.append(f"```\n{ctx.directory_structure}\n```")

        # 添加依赖信息
        if ctx.dependencies:
            sections.append("\n## 主要依赖")
            for name, version in list(ctx.dependencies.items())[:10]:
                sections.append(f"- {name}: {version}")

        return '\n'.join(sections)

    def extract_relevant_code(
        self,
        query: str,
        max_files: int = 5,
        max_lines_per_file: int = 100
    ) -> str:
        """
        根据查询提取相关代码片段

        简单实现：根据关键词搜索文件
        """
        if not self.project_context:
            self.analyze_project()

        keywords = self._extract_keywords(query)
        relevant_files = []

        # 遍历代码文件
        code_extensions = {'.py', '.js', '.ts', '.jsx', '.tsx', '.go', '.java', '.rs'}

        for root, dirs, files in os.walk(self.working_dir):
            dirs[:] = [d for d in dirs if d not in {'.git', 'node_modules', '__pycache__', '.venv', 'venv'}]

            for file in files:
                ext = os.path.splitext(file)[1]
                if ext not in code_extensions:
                    continue

                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()

                    # 检查关键词匹配
                    score = sum(1 for kw in keywords if kw.lower() in content.lower())
                    if score > 0:
                        relevant_files.append((file_path, score, content))

                except Exception:
                    continue

        # 按匹配度排序，取前 N 个
        relevant_files.sort(key=lambda x: x[1], reverse=True)
        top_files = relevant_files[:max_files]

        if not top_files:
            return ""

        # 构建代码片段
        sections = ["## 相关代码片段"]
        for file_path, score, content in top_files:
            rel_path = os.path.relpath(file_path, self.working_dir)
            lines = content.split('\n')[:max_lines_per_file]
            sections.append(f"\n### {rel_path} (相关度: {score})")
            sections.append(f"```\n{chr(10).join(lines)}\n```")

        return '\n'.join(sections)

    def _extract_keywords(self, query: str) -> List[str]:
        """从查询中提取关键词"""
        # 简单的关键词提取
        import re

        # 移除常见停用词
        stop_words = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
                      'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
                      'would', 'could', 'should', 'may', 'might', 'must', 'shall',
                      '的', '是', '在', '有', '和', '了', '不', '这', '我', '你'}

        # 提取单词
        words = re.findall(r'\b\w+\b', query.lower())

        # 过滤并返回
        return [w for w in words if w not in stop_words and len(w) > 2]

    def compress_history(
        self,
        messages: List[Dict],
        max_messages: int = 10,
        keep_recent: int = 3
    ) -> List[Dict]:
        """
        压缩历史对话

        保留策略：
        1. 保留最近 N 条消息
        2. 对早期消息进行摘要
        """
        if len(messages) <= max_messages:
            return messages

        # 保留最近的消息
        recent = messages[-keep_recent:]
        older = messages[:-keep_recent]

        # 对早期消息生成摘要
        summary_parts = []
        for msg in older:
            role = msg.get('role', 'unknown')
            content = msg.get('content', '')
            if isinstance(content, str):
                summary_parts.append(f"[{role}]: {content[:200]}...")

        summary = "\n".join(summary_parts)

        # 返回摘要 + 最近消息
        return [
            {"role": "system", "content": f"之前的对话摘要:\n{summary}"}
        ] + recent


class DynamicPromptBuilder:
    """动态提示词构建器"""

    def __init__(self, engine: PromptAugmentationEngine):
        self.engine = engine

    def build(
        self,
        user_message: str,
        conversation_history: List[Dict] = None,
        include_relevant_code: bool = True,
        include_project_context: bool = True
    ) -> str:
        """构建完整的提示词"""
        sections = []

        # 1. 相关代码（如果有）
        if include_relevant_code:
            relevant_code = self.engine.extract_relevant_code(user_message)
            if relevant_code:
                sections.append(relevant_code)

        # 2. 对话历史
        if conversation_history:
            history_text = self._format_history(conversation_history)
            sections.append(f"## 对话历史\n{history_text}")

        # 3. 用户消息
        sections.append(f"## 当前请求\n{user_message}")

        return '\n\n'.join(sections)

    def _format_history(self, messages: List[Dict], max_turns: int = 5) -> str:
        """格式化对话历史"""
        formatted = []
        for msg in messages[-max_turns * 2:]:  # 保留最近 N 轮
            role = msg.get('role', 'unknown')
            content = msg.get('content', '')
            if isinstance(content, str):
                role_name = "用户" if role == "user" else "助手"
                formatted.append(f"**{role_name}**: {content[:500]}")
        return '\n\n'.join(formatted)
