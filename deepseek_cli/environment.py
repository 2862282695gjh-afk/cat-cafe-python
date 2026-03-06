"""
Environment Interaction Layer - 环境交互层增强
与文件系统、终端、Git、网络等交互
"""
import os
import re
import json
import asyncio
import subprocess
import shutil
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime


@dataclass
class FileInfo:
    """文件信息"""
    path: str
    name: str
    size: int
    modified_time: datetime
    is_dir: bool
    extension: str
    language: str


@dataclass
class ExecutionResult:
    """命令执行结果"""
    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    success: bool


class EnvironmentLayer:
    """
    环境交互层 - 统一的文件系统、Shell、Git、网络操作接口
    """

    def __init__(
        self,
        working_dir: str = None,
        sandbox_mode: bool = False,
        allowed_paths: List[str] = None,
        blocked_commands: List[str] = None
    ):
        self.working_dir = working_dir or os.getcwd()
        self.sandbox_mode = sandbox_mode
        self.allowed_paths = allowed_paths or [self.working_dir]
        self.blocked_commands = blocked_commands or [
            'rm -rf /', 'mkfs', 'dd if=', 'format',
            'del /s', 'rd /s', 'shutdown', 'reboot'
        ]

        # 文件变更追踪
        self.file_changes: List[Dict] = []
        self.command_history: List[ExecutionResult] = []

    # ==================== 文件系统操作 ====================

    def resolve_path(self, path: str) -> str:
        """解析路径（支持相对路径）"""
        if not os.path.isabs(path):
            path = os.path.join(self.working_dir, path)
        return os.path.normpath(path)

    def is_path_allowed(self, path: str) -> bool:
        """检查路径是否被允许访问"""
        if not self.sandbox_mode:
            return True

        resolved = self.resolve_path(path)
        return any(
            resolved.startswith(allowed)
            for allowed in self.allowed_paths
        )

    def read_file(
        self,
        file_path: str,
        offset: int = 0,
        limit: int = 2000,
        encoding: str = 'utf-8'
    ) -> Tuple[str, bool]:
        """
        读取文件内容

        Returns:
            (content, success)
        """
        path = self.resolve_path(file_path)

        if not self.is_path_allowed(path):
            return f"访问被拒绝: {path}", False

        if not os.path.exists(path):
            return f"文件不存在: {path}", False

        if os.path.isdir(path):
            return f"是目录而非文件: {path}", False

        try:
            with open(path, 'r', encoding=encoding, errors='replace') as f:
                lines = f.readlines()

            start = max(0, offset)
            end = start + limit
            selected = lines[start:end]

            # 添加行号
            result = []
            for i, line in enumerate(selected, start=start + 1):
                result.append(f"{i:6}→{line.rstrip()}")

            return '\n'.join(result), True

        except Exception as e:
            return f"读取失败: {e}", False

    def write_file(
        self,
        file_path: str,
        content: str,
        mode: str = 'write',  # write, append
        encoding: str = 'utf-8',
        create_dirs: bool = True
    ) -> Tuple[str, bool]:
        """写入文件"""
        path = self.resolve_path(file_path)

        if not self.is_path_allowed(path):
            return f"访问被拒绝: {path}", False

        try:
            if create_dirs:
                os.makedirs(os.path.dirname(path), exist_ok=True)

            write_mode = 'a' if mode == 'append' else 'w'
            with open(path, write_mode, encoding=encoding) as f:
                f.write(content)

            # 记录变更
            self.file_changes.append({
                'type': 'write',
                'path': path,
                'size': len(content),
                'timestamp': datetime.now().isoformat()
            })

            return f"写入成功: {path} ({len(content)} 字符)", True

        except Exception as e:
            return f"写入失败: {e}", False

    def edit_file(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False
    ) -> Tuple[str, bool, int]:
        """
        编辑文件（字符串替换）

        Returns:
            (message, success, replacements)
        """
        path = self.resolve_path(file_path)

        if not self.is_path_allowed(path):
            return f"访问被拒绝: {path}", False, 0

        if not os.path.exists(path):
            return f"文件不存在: {path}", False, 0

        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()

            # 查找匹配
            matches = list(re.finditer(re.escape(old_string), content))
            if not matches:
                return f"未找到匹配: {old_string[:50]}...", False, 0

            if not replace_all and len(matches) > 1:
                return f"找到 {len(matches)} 处匹配，请使用更精确的字符串或 replace_all=true", False, 0

            # 执行替换
            if replace_all:
                new_content = content.replace(old_string, new_string)
                count = len(matches)
            else:
                new_content = content.replace(old_string, new_string, 1)
                count = 1

            with open(path, 'w', encoding='utf-8') as f:
                f.write(new_content)

            # 记录变更
            self.file_changes.append({
                'type': 'edit',
                'path': path,
                'replacements': count,
                'timestamp': datetime.now().isoformat()
            })

            return f"编辑成功: {path} (替换 {count} 处)", True, count

        except Exception as e:
            return f"编辑失败: {e}", False, 0

    def delete_file(self, file_path: str) -> Tuple[str, bool]:
        """删除文件"""
        path = self.resolve_path(file_path)

        if not self.is_path_allowed(path):
            return f"访问被拒绝: {path}", False

        if not os.path.exists(path):
            return f"文件不存在: {path}", False

        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)

            self.file_changes.append({
                'type': 'delete',
                'path': path,
                'timestamp': datetime.now().isoformat()
            })

            return f"删除成功: {path}", True

        except Exception as e:
            return f"删除失败: {e}", False

    def list_directory(
        self,
        dir_path: str = '.',
        recursive: bool = False,
        include_hidden: bool = False,
        pattern: str = None
    ) -> List[FileInfo]:
        """列出目录内容"""
        path = self.resolve_path(dir_path)

        if not os.path.exists(path):
            return []

        results = []
        lang_map = {
            '.py': 'Python', '.js': 'JavaScript', '.ts': 'TypeScript',
            '.go': 'Go', '.rs': 'Rust', '.java': 'Java',
            '.html': 'HTML', '.css': 'CSS', '.json': 'JSON',
            '.md': 'Markdown', '.yaml': 'YAML', '.yml': 'YAML',
        }

        if recursive:
            for root, dirs, files in os.walk(path):
                if not include_hidden:
                    dirs[:] = [d for d in dirs if not d.startswith('.')]

                for name in files + dirs:
                    if not include_hidden and name.startswith('.'):
                        continue

                    if pattern and not re.search(pattern, name):
                        continue

                    full_path = os.path.join(root, name)
                    info = self._get_file_info(full_path)
                    if info:
                        results.append(info)
        else:
            for name in os.listdir(path):
                if not include_hidden and name.startswith('.'):
                    continue

                if pattern and not re.search(pattern, name):
                    continue

                full_path = os.path.join(path, name)
                info = self._get_file_info(full_path)
                if info:
                    results.append(info)

        return results

    def _get_file_info(self, path: str) -> Optional[FileInfo]:
        """获取文件信息"""
        try:
            stat = os.stat(path)
            ext = os.path.splitext(path)[1]
            lang_map = {
                '.py': 'Python', '.js': 'JavaScript', '.ts': 'TypeScript',
                '.go': 'Go', '.rs': 'Rust', '.java': 'Java',
            }
            return FileInfo(
                path=path,
                name=os.path.basename(path),
                size=stat.st_size,
                modified_time=datetime.fromtimestamp(stat.st_mtime),
                is_dir=os.path.isdir(path),
                extension=ext,
                language=lang_map.get(ext, 'Unknown')
            )
        except:
            return None

    # ==================== Shell 命令执行 ====================

    def is_command_safe(self, command: str) -> bool:
        """检查命令是否安全"""
        command_lower = command.lower()
        for blocked in self.blocked_commands:
            if blocked.lower() in command_lower:
                return False
        return True

    async def execute_command(
        self,
        command: str,
        timeout: int = 120000,
        env: Dict[str, str] = None,
        cwd: str = None
    ) -> ExecutionResult:
        """
        执行 Shell 命令
        """
        if not self.is_command_safe(command):
            return ExecutionResult(
                command=command,
                exit_code=-1,
                stdout="",
                stderr="命令被阻止：包含危险操作",
                duration_ms=0,
                success=False
            )

        start_time = datetime.now()
        work_dir = cwd or self.working_dir

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=work_dir,
                env={**os.environ, **(env or {})}
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout / 1000
                )
            except asyncio.TimeoutError:
                process.kill()
                return ExecutionResult(
                    command=command,
                    exit_code=-1,
                    stdout="",
                    stderr=f"命令超时 ({timeout}ms)",
                    duration_ms=timeout,
                    success=False
                )

            duration = (datetime.now() - start_time).total_seconds() * 1000
            result = ExecutionResult(
                command=command,
                exit_code=process.returncode,
                stdout=stdout.decode('utf-8', errors='replace'),
                stderr=stderr.decode('utf-8', errors='replace'),
                duration_ms=int(duration),
                success=process.returncode == 0
            )

            self.command_history.append(result)
            return result

        except Exception as e:
            return ExecutionResult(
                command=command,
                exit_code=-1,
                stdout="",
                stderr=str(e),
                duration_ms=0,
                success=False
            )

    # ==================== Git 操作 ====================

    async def git_status(self) -> Dict[str, Any]:
        """获取 Git 状态"""
        result = await self.execute_command('git status --porcelain')
        if not result.success:
            return {"error": result.stderr, "has_changes": False}

        changes = []
        for line in result.stdout.strip().split('\n'):
            if line:
                status = line[:2]
                file_path = line[3:]
                changes.append({"status": status, "file": file_path})

        return {
            "has_changes": len(changes) > 0,
            "changes": changes,
            "branch": await self._get_current_branch()
        }

    async def _get_current_branch(self) -> str:
        """获取当前分支"""
        result = await self.execute_command('git branch --show-current')
        return result.stdout.strip() if result.success else "unknown"

    async def git_diff(self, file_path: str = None) -> str:
        """获取差异"""
        cmd = 'git diff'
        if file_path:
            cmd += f' {file_path}'
        result = await self.execute_command(cmd)
        return result.stdout if result.success else result.stderr

    async def git_log(self, count: int = 10) -> List[Dict]:
        """获取提交历史"""
        cmd = f'git log --oneline -{count} --format="%H|%s|%an|%ar"'
        result = await self.execute_command(cmd)

        if not result.success:
            return []

        commits = []
        for line in result.stdout.strip().split('\n'):
            if '|' in line:
                parts = line.split('|', 3)
                if len(parts) >= 4:
                    commits.append({
                        "hash": parts[0],
                        "message": parts[1],
                        "author": parts[2],
                        "time": parts[3]
                    })
        return commits

    # ==================== 搜索功能 ====================

    def search_files(
        self,
        pattern: str,
        path: str = '.',
        file_pattern: str = '*'
    ) -> List[str]:
        """搜索文件名"""
        import fnmatch

        search_path = self.resolve_path(path)
        results = []

        for root, dirs, files in os.walk(search_path):
            dirs[:] = [d for d in dirs if not d.startswith('.')]

            for name in files:
                if fnmatch.fnmatch(name, file_pattern):
                    if pattern.lower() in name.lower():
                        results.append(os.path.join(root, name))

        return results

    def search_content(
        self,
        pattern: str,
        path: str = '.',
        file_extensions: List[str] = None,
        ignore_case: bool = True,
        max_results: int = 100
    ) -> List[Dict]:
        """搜索文件内容"""
        search_path = self.resolve_path(path)
        results = []
        flags = re.IGNORECASE if ignore_case else 0

        try:
            regex = re.compile(pattern, flags)
        except re.error:
            return [{"error": f"无效的正则表达式: {pattern}"}]

        extensions = set(file_extensions or ['.py', '.js', '.ts', '.go', '.java', '.md', '.txt'])

        for root, dirs, files in os.walk(search_path):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d != 'node_modules']

            for name in files:
                ext = os.path.splitext(name)[1]
                if ext not in extensions:
                    continue

                file_path = os.path.join(root, name)
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        for line_num, line in enumerate(f, 1):
                            if regex.search(line):
                                results.append({
                                    "file": file_path,
                                    "line": line_num,
                                    "content": line.strip()[:200]
                                })
                                if len(results) >= max_results:
                                    return results
                except:
                    continue

        return results

    # ==================== 状态和清理 ====================

    def get_file_changes(self) -> List[Dict]:
        """获取文件变更记录"""
        return self.file_changes.copy()

    def get_command_history(self) -> List[ExecutionResult]:
        """获取命令执行历史"""
        return self.command_history.copy()

    def clear_history(self):
        """清除历史记录"""
        self.file_changes.clear()
        self.command_history.clear()

    def get_environment_summary(self) -> Dict:
        """获取环境摘要"""
        return {
            "working_dir": self.working_dir,
            "sandbox_mode": self.sandbox_mode,
            "file_changes_count": len(self.file_changes),
            "commands_executed": len(self.command_history),
            "last_file_change": self.file_changes[-1] if self.file_changes else None,
            "last_command": {
                "command": self.command_history[-1].command,
                "success": self.command_history[-1].success
            } if self.command_history else None
        }
