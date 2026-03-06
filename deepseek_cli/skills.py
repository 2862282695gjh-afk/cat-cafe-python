"""
Skills & Sub-agents - 技能与子代理系统
专门化的能力模块，支持任务委派
"""
import os
import json
import asyncio
from typing import Dict, List, Optional, Any, AsyncGenerator, Callable
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod


class SkillPriority(Enum):
    """技能优先级"""
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class SkillResult:
    """技能执行结果"""
    skill_name: str
    success: bool
    output: str
    artifacts: Dict[str, Any] = field(default_factory=dict)
    suggestions: List[str] = field(default_factory=list)


class BaseSkill(ABC):
    """技能基类"""

    name: str = "base_skill"
    description: str = "基础技能"
    priority: SkillPriority = SkillPriority.MEDIUM
    triggers: List[str] = []  # 触发关键词

    @abstractmethod
    async def execute(self, context: Dict[str, Any], **kwargs) -> SkillResult:
        """执行技能"""
        pass

    def should_trigger(self, query: str) -> bool:
        """检查是否应该触发此技能"""
        query_lower = query.lower()
        return any(trigger.lower() in query_lower for trigger in self.triggers)

    def get_info(self) -> Dict:
        """获取技能信息"""
        return {
            "name": self.name,
            "description": self.description,
            "priority": self.priority.value,
            "triggers": self.triggers
        }


# ==================== 具体技能实现 ====================

class CodeReviewSkill(BaseSkill):
    """代码审查技能"""

    name = "code_review"
    description = "审查代码质量、发现潜在问题"
    priority = SkillPriority.HIGH
    triggers = ["review", "审查", "检查代码", "code review", "有问题吗"]

    async def execute(self, context: Dict[str, Any], **kwargs) -> SkillResult:
        """执行代码审查"""
        target_file = kwargs.get('file') or context.get('current_file')

        if not target_file:
            return SkillResult(
                skill_name=self.name,
                success=False,
                output="未指定要审查的文件"
            )

        try:
            with open(target_file, 'r', encoding='utf-8') as f:
                code = f.read()
        except Exception as e:
            return SkillResult(
                skill_name=self.name,
                success=False,
                output=f"读取文件失败: {e}"
            )

        # 构建审查提示
        review_prompt = f"""
请审查以下代码，关注：
1. 代码质量和可读性
2. 潜在的 bug 或安全问题
3. 性能问题
4. 最佳实践建议

文件: {target_file}
```{self._get_language(target_file)}
{code}
```
"""
        return SkillResult(
            skill_name=self.name,
            success=True,
            output="代码审查请求已准备",
            artifacts={"review_prompt": review_prompt, "target_file": target_file},
            suggestions=["检查错误处理", "验证边界条件", "考虑性能优化"]
        )

    def _get_language(self, filename: str) -> str:
        ext = os.path.splitext(filename)[1]
        lang_map = {'.py': 'python', '.js': 'javascript', '.ts': 'typescript', '.go': 'go'}
        return lang_map.get(ext, '')


class TestGenerationSkill(BaseSkill):
    """测试生成技能"""

    name = "test_generation"
    description = "为代码生成单元测试"
    priority = SkillPriority.MEDIUM
    triggers = ["测试", "test", "单元测试", "unit test", "写测试"]

    async def execute(self, context: Dict[str, Any], **kwargs) -> SkillResult:
        """生成测试代码"""
        target_file = kwargs.get('file') or context.get('current_file')
        test_framework = kwargs.get('framework', 'pytest')

        if not target_file:
            return SkillResult(
                skill_name=self.name,
                success=False,
                output="未指定要测试的文件"
            )

        try:
            with open(target_file, 'r', encoding='utf-8') as f:
                code = f.read()
        except Exception as e:
            return SkillResult(
                skill_name=self.name,
                success=False,
                output=f"读取文件失败: {e}"
            )

        test_prompt = f"""
请为以下代码生成 {test_framework} 单元测试：

文件: {target_file}
```python
{code}
```

要求：
1. 覆盖主要功能路径
2. 包含边界条件测试
3. 包含错误情况测试
"""
        return SkillResult(
            skill_name=self.name,
            success=True,
            output="测试生成请求已准备",
            artifacts={"test_prompt": test_prompt, "target_file": target_file},
            suggestions=["使用 mock 隔离外部依赖", "测试异常情况"]
        )


class RefactoringSkill(BaseSkill):
    """重构技能"""

    name = "refactoring"
    description = "识别重构机会并提供重构建议"
    priority = SkillPriority.MEDIUM
    triggers = ["重构", "refactor", "优化代码", "改进", "clean code"]

    async def execute(self, context: Dict[str, Any], **kwargs) -> SkillResult:
        """执行重构分析"""
        target_file = kwargs.get('file') or context.get('current_file')
        focus = kwargs.get('focus', 'all')  # all, performance, readability, maintainability

        if not target_file:
            return SkillResult(
                skill_name=self.name,
                success=False,
                output="未指定要重构的文件"
            )

        focus_prompts = {
            'performance': "关注性能优化",
            'readability': "关注代码可读性",
            'maintainability': "关注可维护性",
            'all': "全面分析"
        }

        refactor_prompt = f"""
请分析以下代码并提供重构建议（{focus_prompts.get(focus, '全面分析')}）：

文件: {target_file}

要求：
1. 识别代码坏味道 (code smells)
2. 应用设计模式
3. 提供具体的重构步骤
4. 展示重构后的代码示例
"""
        return SkillResult(
            skill_name=self.name,
            success=True,
            output="重构分析请求已准备",
            artifacts={"refactor_prompt": refactor_prompt},
            suggestions=["提取重复代码为函数", "简化复杂条件", "使用更清晰的命名"]
        )


class DocumentationSkill(BaseSkill):
    """文档生成技能"""

    name = "documentation"
    description = "为代码生成文档和注释"
    priority = SkillPriority.LOW
    triggers = ["文档", "document", "注释", "comment", "docstring", "readme"]

    async def execute(self, context: Dict[str, Any], **kwargs) -> SkillResult:
        """生成文档"""
        target_file = kwargs.get('file') or context.get('current_file')
        doc_type = kwargs.get('type', 'inline')  # inline, readme, api

        if doc_type == 'readme':
            prompt = """
请为当前项目生成 README.md 文档，包括：
1. 项目简介
2. 安装说明
3. 使用方法
4. API 文档（如适用）
5. 贡献指南
"""
        else:
            if not target_file:
                return SkillResult(
                    skill_name=self.name,
                    success=False,
                    output="未指定要添加文档的文件"
                )

            prompt = f"""
请为以下代码添加文档字符串和注释：

文件: {target_file}

要求：
1. 为所有公开函数添加 docstring
2. 解释复杂逻辑
3. 包含参数和返回值说明
4. 包含使用示例
"""

        return SkillResult(
            skill_name=self.name,
            success=True,
            output="文档生成请求已准备",
            artifacts={"doc_prompt": prompt, "doc_type": doc_type}
        )


class GitAnalysisSkill(BaseSkill):
    """Git 分析技能"""

    name = "git_analysis"
    description = "分析 Git 历史和变更"
    priority = SkillPriority.MEDIUM
    triggers = ["git", "commit", "分支", "branch", "diff", "变更历史"]

    async def execute(self, context: Dict[str, Any], **kwargs) -> SkillResult:
        """分析 Git 仓库"""
        import subprocess

        working_dir = context.get('working_dir', os.getcwd())
        analysis_type = kwargs.get('type', 'status')  # status, log, diff

        results = {}

        try:
            if analysis_type in ['status', 'all']:
                result = subprocess.run(
                    ['git', 'status', '--short'],
                    cwd=working_dir, capture_output=True, text=True, timeout=10
                )
                results['status'] = result.stdout

            if analysis_type in ['log', 'all']:
                result = subprocess.run(
                    ['git', 'log', '--oneline', '-10'],
                    cwd=working_dir, capture_output=True, text=True, timeout=10
                )
                results['recent_commits'] = result.stdout

            if analysis_type in ['diff', 'all']:
                result = subprocess.run(
                    ['git', 'diff', '--stat'],
                    cwd=working_dir, capture_output=True, text=True, timeout=10
                )
                results['diff_stat'] = result.stdout

        except Exception as e:
            return SkillResult(
                skill_name=self.name,
                success=False,
                output=f"Git 分析失败: {e}"
            )

        analysis_prompt = f"""
分析 Git 仓库状态：

当前状态:
```
{results.get('status', '无变更')}
```

最近提交:
```
{results.get('recent_commits', '无历史')}
```

变更统计:
```
{results.get('diff_stat', '无变更')}
```
"""
        return SkillResult(
            skill_name=self.name,
            success=True,
            output="Git 分析完成",
            artifacts={"git_prompt": analysis_prompt, "git_data": results}
        )


# ==================== 技能注册表 ====================

class SkillRegistry:
    """技能注册表"""

    def __init__(self):
        self.skills: Dict[str, BaseSkill] = {}
        self._register_default_skills()

    def _register_default_skills(self):
        """注册默认技能"""
        default_skills = [
            CodeReviewSkill(),
            TestGenerationSkill(),
            RefactoringSkill(),
            DocumentationSkill(),
            GitAnalysisSkill(),
        ]
        for skill in default_skills:
            self.register(skill)

    def register(self, skill: BaseSkill):
        """注册技能"""
        self.skills[skill.name] = skill

    def get(self, name: str) -> Optional[BaseSkill]:
        """获取技能"""
        return self.skills.get(name)

    def find_matching_skills(self, query: str) -> List[BaseSkill]:
        """查找匹配的技能"""
        matching = []
        for skill in self.skills.values():
            if skill.should_trigger(query):
                matching.append(skill)
        return sorted(matching, key=lambda s: s.priority.value, reverse=True)

    def list_skills(self) -> List[Dict]:
        """列出所有技能"""
        return [skill.get_info() for skill in self.skills.values()]


# ==================== 子代理系统 ====================

@dataclass
class SubAgentConfig:
    """子代理配置"""
    id: str
    name: str
    specialty: str  # 专长领域
    system_prompt: str
    tools: List[str] = field(default_factory=list)


class SubAgentManager:
    """子代理管理器"""

    def __init__(self):
        self.sub_agents: Dict[str, SubAgentConfig] = {}
        self._register_default_subagents()

    def _register_default_subagents(self):
        """注册默认子代理"""
        default_agents = [
            SubAgentConfig(
                id="code_reviewer",
                name="代码审查员",
                specialty="代码质量审查",
                system_prompt="你是一个专业的代码审查员，擅长发现代码中的问题和改进机会。",
                tools=["Read", "Grep"]
            ),
            SubAgentConfig(
                id="test_writer",
                name="测试工程师",
                specialty="编写测试用例",
                system_prompt="你是一个测试工程师，擅长编写全面的单元测试和集成测试。",
                tools=["Read", "Write", "Bash"]
            ),
            SubAgentConfig(
                id="doc_writer",
                name="文档工程师",
                specialty="编写技术文档",
                system_prompt="你是一个技术文档工程师，擅长编写清晰、完整的技术文档。",
                tools=["Read", "Write", "Glob"]
            ),
            SubAgentConfig(
                id="security_auditor",
                name="安全审计员",
                specialty="安全漏洞检测",
                system_prompt="你是一个安全审计员，擅长发现代码中的安全漏洞和风险。",
                tools=["Read", "Grep", "Bash"]
            ),
        ]
        for agent in default_agents:
            self.register(agent)

    def register(self, agent: SubAgentConfig):
        """注册子代理"""
        self.sub_agents[agent.id] = agent

    def get(self, agent_id: str) -> Optional[SubAgentConfig]:
        """获取子代理"""
        return self.sub_agents.get(agent_id)

    def find_by_specialty(self, query: str) -> List[SubAgentConfig]:
        """根据专长查找子代理"""
        matching = []
        query_lower = query.lower()
        for agent in self.sub_agents.values():
            if agent.specialty.lower() in query_lower:
                matching.append(agent)
        return matching

    def list_subagents(self) -> List[Dict]:
        """列出所有子代理"""
        return [
            {
                "id": agent.id,
                "name": agent.name,
                "specialty": agent.specialty,
                "tools": agent.tools
            }
            for agent in self.sub_agents.values()
        ]

    async def delegate_task(
        self,
        agent_id: str,
        task: str,
        context: Dict[str, Any]
    ) -> AsyncGenerator[Dict, None]:
        """委派任务给子代理"""
        agent = self.get(agent_id)
        if not agent:
            yield {"type": "error", "message": f"未找到子代理: {agent_id}"}
            return

        yield {
            "type": "subagent_start",
            "agent_id": agent_id,
            "agent_name": agent.name,
            "task": task
        }

        # 构建子代理的 prompt
        subagent_prompt = f"""
[系统] 你现在是 {agent.name}，专长领域: {agent.specialty}

{agent.system_prompt}

## 可用工具
你可以使用以下工具: {', '.join(agent.tools)}

## 任务
{task}

## 上下文
{json.dumps(context, ensure_ascii=False, indent=2)}
"""

        yield {
            "type": "subagent_prompt",
            "agent_id": agent_id,
            "prompt": subagent_prompt
        }
