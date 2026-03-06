"""
工具执行器
实现 Read, Write, Edit, Bash, Glob, Grep 等工具
"""
import os
import re
import subprocess
import glob as glob_module
import asyncio
from typing import Dict, Any, Optional, List
from pathlib import Path


class ToolExecutor:
    """工具执行器"""

    def __init__(self, working_dir: str = None, dangerous_skip_permissions: bool = True):
        self.working_dir = working_dir or os.getcwd()
        self.dangerous_skip_permissions = dangerous_skip_permissions

        # 危险命令模式
        self.dangerous_patterns = [
            r"rm\s+-rf\s+/",
            r"rm\s+-rf\s+~",
            r"rm\s+-rf\s+\*",
            r">\s*/dev/sd",
            r"mkfs",
            r"dd\s+if=",
            r":()\s*{\s*:\|:&\s*}",  # fork bomb
        ]

    async def execute(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """执行工具"""
        tool_map = {
            "Read": self.read,
            "Write": self.write,
            "Edit": self.edit,
            "Bash": self.bash,
            "Glob": self.glob_tool,
            "Grep": self.grep_tool,
        }

        handler = tool_map.get(tool_name)
        if not handler:
            return f"未知工具: {tool_name}"

        try:
            result = await handler(**arguments)
            return result
        except Exception as e:
            return f"工具执行错误: {str(e)}"

    async def read(self, file_path: str, offset: int = 1, limit: int = 2000) -> str:
        """
        读取文件内容

        Args:
            file_path: 文件路径
            offset: 起始行号（从1开始）
            limit: 最大行数
        """
        # 处理路径
        if not os.path.isabs(file_path):
            file_path = os.path.join(self.working_dir, file_path)

        if not os.path.exists(file_path):
            return f"错误: 文件不存在: {file_path}"

        if os.path.isdir(file_path):
            return f"错误: {file_path} 是一个目录，不是文件"

        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            # 应用偏移和限制
            start = max(0, offset - 1)
            end = start + limit
            selected_lines = lines[start:end]

            # 格式化输出
            result_lines = []
            for i, line in enumerate(selected_lines, start=offset):
                # 去掉行末换行符，添加行号
                result_lines.append(f"{i:6}→{line.rstrip()}")

            content = '\n'.join(result_lines)

            # 添加文件信息
            total_lines = len(lines)
            shown_lines = len(selected_lines)

            header = f"文件: {file_path}\n"
            header += f"总行数: {total_lines}\n"
            if shown_lines < total_lines:
                header += f"显示: 第 {offset}-{offset + shown_lines - 1} 行\n"
            header += "-" * 40 + "\n"

            return header + content

        except Exception as e:
            return f"读取文件错误: {str(e)}"

    async def write(self, file_path: str, content: str) -> str:
        """
        写入文件

        Args:
            file_path: 文件路径
            content: 文件内容
        """
        # 处理路径
        if not os.path.isabs(file_path):
            file_path = os.path.join(self.working_dir, file_path)

        # 检查危险操作
        if not self.dangerous_skip_permissions:
            # 检查是否覆盖重要文件
            important_files = ['.env', 'id_rsa', 'credentials', '.git/config']
            if os.path.exists(file_path) and any(
                important in file_path for important in important_files
            ):
                return f"警告: 需要确认才能覆盖重要文件: {file_path}"

        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(file_path), exist_ok=True)

            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)

            return f"成功写入文件: {file_path} ({len(content)} 字符)"

        except Exception as e:
            return f"写入文件错误: {str(e)}"

    async def edit(self, file_path: str, old_string: str, new_string: str,
                   replace_all: bool = False) -> str:
        """
        编辑文件（字符串替换）

        Args:
            file_path: 文件路径
            old_string: 要替换的字符串
            new_string: 新字符串
            replace_all: 是否替换所有匹配
        """
        # 处理路径
        if not os.path.isabs(file_path):
            file_path = os.path.join(self.working_dir, file_path)

        if not os.path.exists(file_path):
            return f"错误: 文件不存在: {file_path}"

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # 检查匹配
            matches = list(re.finditer(re.escape(old_string), content))
            if not matches:
                return f"错误: 未找到匹配的字符串: {old_string[:50]}..."

            if not replace_all and len(matches) > 1:
                return f"错误: 找到 {len(matches)} 处匹配，请使用更精确的字符串或设置 replace_all=true"

            # 执行替换
            if replace_all:
                new_content = content.replace(old_string, new_string)
                count = len(matches)
            else:
                new_content = content.replace(old_string, new_string, 1)
                count = 1

            # 写入文件
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(new_content)

            return f"成功编辑文件: {file_path} (替换了 {count} 处)"

        except Exception as e:
            return f"编辑文件错误: {str(e)}"

    async def bash(self, command: str, timeout: int = 120000) -> str:
        """
        执行 shell 命令

        Args:
            command: shell 命令
            timeout: 超时时间（毫秒）
        """
        # 检查危险命令
        for pattern in self.dangerous_patterns:
            if re.search(pattern, command, re.IGNORECASE):
                if not self.dangerous_skip_permissions:
                    return f"警告: 危险命令需要确认: {command}"
                # 如果跳过权限检查，继续执行

        try:
            # 转换超时时间
            timeout_seconds = timeout / 1000

            # 执行命令
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.working_dir
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout_seconds
                )
            except asyncio.TimeoutError:
                process.kill()
                return f"命令超时 ({timeout}ms): {command}"

            # 解码输出
            stdout_text = stdout.decode('utf-8', errors='replace')
            stderr_text = stderr.decode('utf-8', errors='replace')

            # 构建结果
            result = ""
            if stdout_text:
                result += stdout_text
            if stderr_text:
                result += f"\n[stderr]\n{stderr_text}"
            if process.returncode != 0:
                result += f"\n[退出码: {process.returncode}]"

            return result.strip() or "(无输出)"

        except Exception as e:
            return f"执行命令错误: {str(e)}"

    async def glob_tool(self, pattern: str, path: str = None) -> str:
        """
        查找文件

        Args:
            pattern: glob 模式
            path: 搜索路径
        """
        search_path = path or self.working_dir

        if not os.path.isabs(search_path):
            search_path = os.path.join(self.working_dir, search_path)

        try:
            # 使用 glob 搜索
            matches = glob_module.glob(
                os.path.join(search_path, pattern),
                recursive=True
            )

            if not matches:
                return f"未找到匹配的文件: {pattern}"

            # 格式化输出
            results = []
            for match in sorted(matches):
                rel_path = os.path.relpath(match, search_path)
                if os.path.isdir(match):
                    results.append(f"📁 {rel_path}/")
                else:
                    size = os.path.getsize(match)
                    results.append(f"📄 {rel_path} ({size} bytes)")

            return f"找到 {len(results)} 个匹配:\n" + "\n".join(results[:100])

        except Exception as e:
            return f"搜索文件错误: {str(e)}"

    async def grep_tool(self, pattern: str, path: str = None,
                        output_mode: str = "content") -> str:
        """
        搜索文件内容

        Args:
            pattern: 正则表达式模式
            path: 搜索路径
            output_mode: 输出模式 (content/files_with_matches/count)
        """
        search_path = path or self.working_dir

        if not os.path.isabs(search_path):
            search_path = os.path.join(self.working_dir, search_path)

        try:
            regex = re.compile(pattern, re.MULTILINE | re.IGNORECASE)
            results = []
            match_count = 0

            # 遍历文件
            for root, dirs, files in os.walk(search_path):
                # 跳过隐藏目录和 node_modules 等
                dirs[:] = [d for d in dirs if not d.startswith('.') and d != 'node_modules']

                for file in files:
                    if file.startswith('.'):
                        continue

                    file_path = os.path.join(root, file)

                    try:
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()

                        matches = list(regex.finditer(content))

                        if matches:
                            match_count += len(matches)
                            rel_path = os.path.relpath(file_path, search_path)

                            if output_mode == "files_with_matches":
                                results.append(rel_path)
                            elif output_mode == "count":
                                results.append(f"{rel_path}: {len(matches)} 匹配")
                            else:  # content
                                for match in matches[:10]:  # 每个文件最多显示10个匹配
                                    line_num = content[:match.start()].count('\n') + 1
                                    line_content = match.group(0)
                                    results.append(f"{rel_path}:{line_num}: {line_content[:100]}")

                    except Exception:
                        continue

            if not results:
                return f"未找到匹配: {pattern}"

            return f"找到 {match_count} 个匹配:\n" + "\n".join(results[:200])

        except Exception as e:
            return f"搜索内容错误: {str(e)}"
