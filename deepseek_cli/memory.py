"""
三层记忆系统实现
1. 短期记忆 - 当前会话上下文
2. 中期记忆 - AU2算法8段式压缩
3. 长期记忆 - 持久化MD文件
"""
import os
import json
import time
import hashlib
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class Message:
    """消息结构"""
    role: str  # user, assistant, system, tool
    content: str
    tokens: int = 0
    timestamp: int = 0
    metadata: Dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = int(time.time() * 1000)


@dataclass
class CompressionResult:
    """压缩结果"""
    original_tokens: int
    compressed_tokens: int
    compression_ratio: float
    sections: Dict[str, str]
    preserved_context: List[str]


class ShortTermMemory:
    """
    短期记忆层
    - 实时消息存储
    - Token 统计
    - 压缩阈值检测
    """

    def __init__(
        self,
        max_tokens: int = 128000,  # DeepSeek 最大上下文
        compression_threshold: float = 0.92  # 92% 触发压缩
    ):
        self.max_tokens = max_tokens
        self.compression_threshold = compression_threshold
        self.messages: List[Message] = []
        self.total_tokens = 0
        self.token_history: List[int] = []  # 追踪 token 使用历史

    def add_message(self, role: str, content: str, metadata: Dict = None) -> Message:
        """添加消息"""
        tokens = self._estimate_tokens(content)
        msg = Message(
            role=role,
            content=content,
            tokens=tokens,
            metadata=metadata or {}
        )
        self.messages.append(msg)
        self.total_tokens += tokens
        self.token_history.append(self.total_tokens)

        return msg

    def _estimate_tokens(self, text: str) -> int:
        """估算 token 数量（简化版）"""
        # 中文约 1.5 字/token，英文约 4 字符/token
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_chars = len(text) - chinese_chars
        return int(chinese_chars / 1.5 + other_chars / 4) + 10

    def should_compress(self) -> bool:
        """检测是否需要压缩"""
        return self.total_tokens >= self.max_tokens * self.compression_threshold

    def get_token_usage(self) -> Dict:
        """获取 token 使用情况"""
        return {
            "total": self.total_tokens,
            "max": self.max_tokens,
            "percentage": self.total_tokens / self.max_tokens * 100,
            "message_count": len(self.messages),
            "should_compress": self.should_compress()
        }

    def get_messages_for_api(self) -> List[Dict]:
        """获取 API 格式的消息"""
        return [
            {"role": msg.role, "content": msg.content}
            for msg in self.messages
        ]

    def clear(self):
        """清除短期记忆"""
        self.messages.clear()
        self.total_tokens = 0
        self.token_history.clear()


class AU2Compressor:
    """
    AU2 算法 - 8段式结构化压缩
    将对话历史压缩为结构化摘要
    """

    # 8个压缩段
    SECTIONS = [
        "background_context",    # 背景上下文
        "key_decisions",         # 关键决策
        "tool_usage",            # 工具使用
        "user_intent",           # 用户意图
        "execution_results",     # 执行结果
        "error_handling",        # 错误处理
        "unresolved_issues",     # 未解决问题
        "next_steps"             # 后续计划
    ]

    def __init__(self, target_compression_ratio: float = 0.3):
        self.target_ratio = target_compression_ratio  # 目标压缩到 30%

    def compress(self, messages: List[Message], context: str = "") -> CompressionResult:
        """
        执行8段式压缩

        Args:
            messages: 消息列表
            context: 额外上下文

        Returns:
            CompressionResult
        """
        original_tokens = sum(msg.tokens for msg in messages)

        # 1. 分析消息内容
        analysis = self._analyze_messages(messages)

        # 2. 生成8段式摘要
        sections = self._generate_sections(analysis, context)

        # 3. 计算压缩后的 token
        compressed_content = self._sections_to_content(sections)
        compressed_tokens = self._estimate_tokens(compressed_content)

        return CompressionResult(
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            compression_ratio=compressed_tokens / original_tokens if original_tokens > 0 else 0,
            sections=sections,
            preserved_context=analysis.get("key_entities", [])
        )

    def _analyze_messages(self, messages: List[Message]) -> Dict:
        """分析消息内容"""
        analysis = {
            "user_messages": [],
            "assistant_messages": [],
            "tool_calls": [],
            "errors": [],
            "key_entities": [],
            "topics": [],
            "decisions": []
        }

        for msg in messages:
            if msg.role == "user":
                analysis["user_messages"].append(msg.content)
                # 提取关键实体
                analysis["key_entities"].extend(self._extract_entities(msg.content))

            elif msg.role == "assistant":
                analysis["assistant_messages"].append(msg.content)
                # 检测决策
                if self._is_decision(msg.content):
                    analysis["decisions"].append(msg.content[:200])

            elif msg.role == "tool":
                analysis["tool_calls"].append({
                    "content": msg.content[:500],
                    "metadata": msg.metadata
                })
                # 检测错误
                if "error" in msg.content.lower():
                    analysis["errors"].append(msg.content[:200])

        return analysis

    def _generate_sections(self, analysis: Dict, context: str) -> Dict[str, str]:
        """生成8个段落的摘要"""
        sections = {}

        # 1. 背景上下文
        sections["background_context"] = self._summarize_background(
            analysis["user_messages"], context
        )

        # 2. 关键决策
        sections["key_decisions"] = self._summarize_decisions(analysis["decisions"])

        # 3. 工具使用
        sections["tool_usage"] = self._summarize_tools(analysis["tool_calls"])

        # 4. 用户意图
        sections["user_intent"] = self._extract_user_intent(analysis["user_messages"])

        # 5. 执行结果
        sections["execution_results"] = self._summarize_results(analysis["assistant_messages"])

        # 6. 错误处理
        sections["error_handling"] = self._summarize_errors(analysis["errors"])

        # 7. 未解决问题
        sections["unresolved_issues"] = self._identify_unresolved(analysis)

        # 8. 后续计划
        sections["next_steps"] = self._suggest_next_steps(analysis)

        return sections

    def _summarize_background(self, user_messages: List[str], context: str) -> str:
        """总结背景上下文"""
        if not user_messages:
            return "无明确背景"

        # 取第一条用户消息作为背景
        first_msg = user_messages[0] if user_messages else ""
        summary = f"用户请求: {first_msg[:300]}"
        if context:
            summary += f"\n项目上下文: {context[:200]}"

        return summary

    def _summarize_decisions(self, decisions: List[str]) -> str:
        """总结关键决策"""
        if not decisions:
            return "无特殊决策记录"

        return "关键决策:\n" + "\n".join(f"- {d[:100]}" for d in decisions[:5])

    def _summarize_tools(self, tool_calls: List[Dict]) -> str:
        """总结工具使用"""
        if not tool_calls:
            return "未使用工具"

        tool_summary = {}
        for tc in tool_calls:
            tool_name = tc.get("metadata", {}).get("tool_name", "unknown")
            tool_summary[tool_name] = tool_summary.get(tool_name, 0) + 1

        return "工具使用统计:\n" + "\n".join(
            f"- {name}: {count}次" for name, count in tool_summary.items()
        )

    def _extract_user_intent(self, user_messages: List[str]) -> str:
        """提取用户意图"""
        if not user_messages:
            return "意图不明确"

        # 简单的意图提取（实际应该用 LLM）
        last_msg = user_messages[-1] if user_messages else ""
        return f"最近请求: {last_msg[:200]}"

    def _summarize_results(self, assistant_messages: List[str]) -> str:
        """总结执行结果"""
        if not assistant_messages:
            return "暂无执行结果"

        # 取最后一条助手消息
        last_msg = assistant_messages[-1] if assistant_messages else ""
        return f"最终结果: {last_msg[:300]}"

    def _summarize_errors(self, errors: List[str]) -> str:
        """总结错误处理"""
        if not errors:
            return "执行过程顺利，无错误"

        return "遇到的错误:\n" + "\n".join(f"- {e[:100]}" for e in errors[:3])

    def _identify_unresolved(self, analysis: Dict) -> str:
        """识别未解决的问题"""
        # 检查是否有未完成的任务
        last_user = analysis["user_messages"][-1] if analysis["user_messages"] else ""
        last_assistant = analysis["assistant_messages"][-1] if analysis["assistant_messages"] else ""

        if "继续" in last_user or "还有" in last_user:
            return "存在待继续的任务"

        return "暂无明显未解决问题"

    def _suggest_next_steps(self, analysis: Dict) -> str:
        """建议后续步骤"""
        if analysis["errors"]:
            return "建议: 解决上述错误后继续"

        if not analysis["assistant_messages"]:
            return "建议: 等待用户明确需求"

        return "建议: 根据执行结果决定下一步操作"

    def _extract_entities(self, text: str) -> List[str]:
        """提取关键实体"""
        import re
        # 提取文件路径
        files = re.findall(r'[\w/\-\.]+\.\w+', text)
        # 提取函数名
        functions = re.findall(r'\b([a-z_][a-z0-9_]*)\s*\(', text)
        return list(set(files + functions))[:10]

    def _is_decision(self, text: str) -> bool:
        """检测是否是决策"""
        decision_keywords = ["决定", "选择", "采用", "使用", "decision", "choose", "will use"]
        return any(kw in text.lower() for kw in decision_keywords)

    def _sections_to_content(self, sections: Dict[str, str]) -> str:
        """将段落转换为内容"""
        lines = ["# 会话摘要"]
        for section_name, content in sections.items():
            title = section_name.replace("_", " ").title()
            lines.append(f"\n## {title}\n{content}")
        return "\n".join(lines)

    def _estimate_tokens(self, text: str) -> int:
        """估算 token"""
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_chars = len(text) - chinese_chars
        return int(chinese_chars / 1.5 + other_chars / 4) + 10


class MidTermMemory:
    """
    中期记忆层
    - 压缩后的会话摘要
    - 持久化存储
    """

    def __init__(self, storage_path: str = None):
        self.storage_path = storage_path or os.path.join(os.getcwd(), ".deepseek", "memory")
        self.compressions: List[CompressionResult] = []
        self.session_summaries: List[Dict] = []

        os.makedirs(self.storage_path, exist_ok=True)

    def store_compression(self, result: CompressionResult, session_id: str = None):
        """存储压缩结果"""
        if not session_id:
            session_id = f"session-{int(time.time() * 1000)}"

        summary = {
            "session_id": session_id,
            "timestamp": int(time.time() * 1000),
            "original_tokens": result.original_tokens,
            "compressed_tokens": result.compressed_tokens,
            "compression_ratio": result.compression_ratio,
            "sections": result.sections
        }

        self.session_summaries.append(summary)
        self.compressions.append(result)

        # 持久化到文件
        self._persist_summary(summary)

        return summary

    def _persist_summary(self, summary: Dict):
        """持久化摘要到 MD 文件"""
        filename = f"session-{summary['session_id']}.md"
        filepath = os.path.join(self.storage_path, filename)

        content = f"""# 会话摘要 - {summary['session_id']}

> 时间: {datetime.fromtimestamp(summary['timestamp'] / 1000).isoformat()}
> 压缩比: {summary['compression_ratio']:.2%}
> 原始 tokens: {summary['original_tokens']} → 压缩后: {summary['compressed_tokens']}

"""
        for section_name, section_content in summary['sections'].items():
            title = section_name.replace("_", " ").title()
            content += f"## {title}\n\n{section_content}\n\n"

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)

    def get_recent_summaries(self, count: int = 3) -> List[Dict]:
        """获取最近的摘要"""
        return self.session_summaries[-count:]

    def build_context_from_summaries(self) -> str:
        """从摘要构建上下文"""
        if not self.session_summaries:
            return ""

        recent = self.get_recent_summaries(3)
        lines = ["## 历史会话摘要"]

        for summary in recent:
            lines.append(f"\n### 会话 {summary['session_id']}")
            if "user_intent" in summary.get("sections", {}):
                lines.append(summary["sections"]["user_intent"])

        return "\n".join(lines)


class LongTermMemory:
    """
    长期记忆层
    - 项目上下文
    - 用户偏好
    - 工作流程
    - 代码风格
    - 开发环境
    - 安全配置
    """

    MEMORY_FILE = "long_term_memory.md"

    def __init__(self, project_path: str = None):
        self.project_path = project_path or os.getcwd()
        self.memory_path = os.path.join(self.project_path, ".deepseek", self.MEMORY_FILE)
        self.memory: Dict[str, Any] = {
            "project_context": {},
            "user_preferences": {},
            "workflows": [],
            "code_style": {},
            "environment": {},
            "security": {}
        }

        self._load()

    def _load(self):
        """加载长期记忆"""
        if os.path.exists(self.memory_path):
            try:
                with open(self.memory_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                self._parse_markdown(content)
            except Exception as e:
                print(f"[LongTermMemory] 加载失败: {e}")

    def _parse_markdown(self, content: str):
        """解析 MD 文件"""
        import re

        sections = re.split(r'^##\s+', content, flags=re.MULTILINE)
        for section in sections[1:]:  # 跳过第一个空部分
            lines = section.strip().split('\n')
            if not lines:
                continue

            title = lines[0].lower().replace(' ', '_')
            body = '\n'.join(lines[1:]).strip()

            if title in self.memory:
                if isinstance(self.memory[title], list):
                    self.memory[title] = [line[2:] for line in body.split('\n') if line.startswith('- ')]
                elif isinstance(self.memory[title], dict):
                    # 解析键值对
                    for line in body.split('\n'):
                        if ':' in line:
                            key, value = line.split(':', 1)
                            self.memory[title][key.strip()] = value.strip()

    def save(self):
        """保存长期记忆"""
        os.makedirs(os.path.dirname(self.memory_path), exist_ok=True)

        content = """# 长期记忆

## Project Context
"""
        for key, value in self.memory.get("project_context", {}).items():
            content += f"{key}: {value}\n"

        content += "\n## User Preferences\n"
        for key, value in self.memory.get("user_preferences", {}).items():
            content += f"{key}: {value}\n"

        content += "\n## Workflows\n"
        for wf in self.memory.get("workflows", []):
            content += f"- {wf}\n"

        content += "\n## Code Style\n"
        for key, value in self.memory.get("code_style", {}).items():
            content += f"{key}: {value}\n"

        content += "\n## Environment\n"
        for key, value in self.memory.get("environment", {}).items():
            content += f"{key}: {value}\n"

        content += "\n## Security\n"
        for key, value in self.memory.get("security", {}).items():
            content += f"{key}: {value}\n"

        with open(self.memory_path, 'w', encoding='utf-8') as f:
            f.write(content)

    def update(self, category: str, data: Dict):
        """更新记忆"""
        if category in self.memory:
            if isinstance(self.memory[category], dict):
                self.memory[category].update(data)
            elif isinstance(self.memory[category], list):
                self.memory[category].extend(data.get("items", []))

        self.save()

    def get_context_for_prompt(self) -> str:
        """获取用于提示词的上下文"""
        lines = ["## 项目记忆"]

        if self.memory.get("project_context"):
            lines.append("项目信息:")
            for k, v in self.memory["project_context"].items():
                lines.append(f"- {k}: {v}")

        if self.memory.get("user_preferences"):
            lines.append("\n用户偏好:")
            for k, v in self.memory["user_preferences"].items():
                lines.append(f"- {k}: {v}")

        if self.memory.get("code_style"):
            lines.append("\n代码风格:")
            for k, v in self.memory["code_style"].items():
                lines.append(f"- {k}: {v}")

        return '\n'.join(lines)


class MemoryManager:
    """
    三层记忆管理器
    协调短期、中期、长期记忆
    """

    def __init__(
        self,
        max_tokens: int = 128000,
        compression_threshold: float = 0.92,
        project_path: str = None
    ):
        # 三层记忆
        self.short_term = ShortTermMemory(max_tokens, compression_threshold)
        self.compressor = AU2Compressor()
        self.mid_term = MidTermMemory(
            storage_path=os.path.join(project_path or os.getcwd(), ".deepseek", "sessions")
        )
        self.long_term = LongTermMemory(project_path)

    def add_message(self, role: str, content: str, metadata: Dict = None):
        """添加消息到短期记忆"""
        self.short_term.add_message(role, content, metadata)

        # 检查是否需要压缩
        if self.short_term.should_compress():
            self._trigger_compression()

    def _trigger_compression(self):
        """触发压缩"""
        print("[Memory] 触发上下文压缩 (达到92%阈值)")

        # 执行压缩
        result = self.compressor.compress(
            self.short_term.messages,
            self.long_term.get_context_for_prompt()
        )

        # 存储到中期记忆
        self.mid_term.store_compression(result)

        # 清空短期记忆，保留压缩摘要
        compressed_content = self.compressor._sections_to_content(result.sections)
        self.short_term.clear()
        self.short_term.add_message("system", f"[压缩摘要]\n{compressed_content}")

        print(f"[Memory] 压缩完成: {result.original_tokens} → {result.compressed_tokens} tokens "
              f"(压缩比: {result.compression_ratio:.1%})")

    def get_context_for_prompt(self) -> str:
        """获取完整的上下文"""
        parts = []

        # 长期记忆
        long_term_ctx = self.long_term.get_context_for_prompt()
        if long_term_ctx:
            parts.append(long_term_ctx)

        # 中期记忆（历史摘要）
        mid_term_ctx = self.mid_term.build_context_from_summaries()
        if mid_term_ctx:
            parts.append(mid_term_ctx)

        return '\n\n'.join(parts)

    def get_messages_for_api(self) -> List[Dict]:
        """获取 API 格式消息"""
        return self.short_term.get_messages_for_api()

    def get_stats(self) -> Dict:
        """获取记忆统计"""
        return {
            "short_term": self.short_term.get_token_usage(),
            "mid_term": {
                "compression_count": len(self.mid_term.session_summaries),
                "total_compressed_tokens": sum(
                    s["compressed_tokens"] for s in self.mid_term.session_summaries
                )
            },
            "long_term": {
                "categories": list(self.long_term.memory.keys()),
                "file_exists": os.path.exists(self.long_term.memory_path)
            }
        }

    def save_session(self):
        """保存会话"""
        # 更新长期记忆
        if self.short_term.messages:
            # 提取项目信息
            self.long_term.update("project_context", {
                "last_session": datetime.now().isoformat(),
                "total_messages": len(self.short_term.messages)
            })
            self.long_term.save()
