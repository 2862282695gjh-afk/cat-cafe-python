"""
Skill 管理器
支持预定义模板、自定义 HTTP 工具、Python 脚本工具
"""
import asyncio
import time
import uuid
import json
import aiohttp
from typing import Dict, List, Optional, Any


# 预定义技能模板
SKILL_TEMPLATES = [
    # ===== Code Review 工作流 Skills =====
    {
        'id': 'hand_off',
        'name': '交接五件套 (Hand-off)',
        'description': '代码/任务交接时必须包含五件套：What/Why/Tradeoff/OpenQuestions/NextAction',
        'type': 'prompt',
        'category': 'code_review',
        'triggers': ['交给狸花猫', 'handoff', '交接', '移交'],
        'config': {
            'prompt': '''
## 交接五件套规范

当进行任务或代码交接时，必须包含以下五个要素：

### 1. What（做了什么）
- 明确描述完成的工作内容
- 列出修改的文件和关键变更
- 说明新增/修改/删除的功能

### 2. Why（为什么这样做）
- 解释设计决策的原因
- 说明技术选型的依据
- 阐述为什么选择这个方案而不是其他方案

### 3. Tradeoff（权衡取舍）
- 当前方案的优点
- 当前方案的缺点/局限性
- 已知的技术债务
- 性能/可维护性/扩展性方面的取舍

### 4. Open Questions（开放问题）
- 待解决的疑问
- 需要后续讨论的点
- 不确定的设计决策
- 需要其他人输入的问题

### 5. Next Action（下一步行动）
- 明确的后续任务
- 建议的优化方向
- 需要跟进的事项
- 责任人和时间线（如适用）

---
⚠️ **强制要求**：每次交接必须完整包含以上五项，缺一不可。
'''
        },
        'parameters': [
            {'name': 'context', 'type': 'string', 'required': True, 'description': '交接的上下文内容'}
        ]
    },
    {
        'id': 'receiving_review',
        'name': '接收 Review 反馈',
        'description': '正确接收和处理 Code Review 反馈的工作流',
        'type': 'prompt',
        'category': 'code_review',
        'triggers': ['reviewer说', 'fix these', 'review反馈', '需要修改'],
        'config': {
            'prompt': '''
## 接收 Review 反馈规范

### 🚫 禁止的响应方式
以下响应属于**表演性同意**，绝对禁止：
- "You're absolutely right"
- "Great points"
- "Excellent feedback"
- "Thanks for catching that"
- "让我现在就改"（没有理解问题就动手）
- "好的我改一下"（没有复述问题）

### ✅ 正确的响应流程

#### Step 1: 复述技术问题
在动手修改前，先用你自己的话复述问题：
```
问题确认：你指的是 [文件名]:[行号] 处的 [具体代码]，
存在 [问题描述]，可能导致 [潜在影响]，对吗？
```

#### Step 2: 提澄清问题
如果不确定问题的具体含义或边界：
```
关于这个问题，我想确认：
1. [具体疑问1]
2. [具体疑问2]
```

#### Step 3: 技术论证（如需要）
如果认为 reviewer 的建议有误，可以 push back：
```
我对此有不同看法：
- Reviewer 认为：[reviewer的观点]
- 我的理解：[我的观点]
- 技术依据：[具体的技术理由/文档/代码证据]
- 建议：[替代方案或讨论]
```

#### Step 4: 执行修复
确认理解后，执行修复：
- 修改代码
- 编写/更新测试
- 本地验证通过

#### Step 5: 请求确认
修复完成后：
```
已完成修复：
- 问题：[原问题描述]
- 修改：[具体改动]
- 验证：[本地测试结果]
请 @reviewer 确认
```

### 🔴 Red-Green 验证规则
修复后必须：
1. **Red**: 确认问题确实存在过（复现/理解问题）
2. **Green**: 确认修复后问题已解决（测试通过/验证）
3. 不能跳过验证直接说"改好了"
'''
        },
        'parameters': [
            {'name': 'feedback', 'type': 'string', 'required': True, 'description': '收到的 review 反馈'}
        ]
    },
    {
        'id': 'requesting_review',
        'name': '发起 Review 请求',
        'description': '发起 Code Review 请求时的规范流程',
        'type': 'prompt',
        'category': 'code_review',
        'triggers': ['请review', '帮我看看', 'review一下', 'code review'],
        'config': {
            'prompt': '''
## 发起 Review 请求规范

### 📋 请求前自检清单
在发起 review 请求前，必须先完成以下自检：

#### 代码质量自检
- [ ] 代码能正常编译/运行
- [ ] 已添加必要的注释
- [ ] 变量/函数命名清晰
- [ ] 没有调试代码残留（console.log等）
- [ ] 没有注释掉的代码块

#### 测试自检
- [ ] 新功能有对应的测试
- [ ] 所有测试通过
- [ ] 边界条件已覆盖
- [ ] 错误处理已测试

#### 安全自检
- [ ] 没有硬编码的敏感信息
- [ ] 用户输入有验证/清理
- [ ] 权限检查到位
- [ ] 没有SQL注入/XSS等风险

---

## Review 执行规范

### 🚫 Reviewer 禁止的响应
- "Looks good" / "看起来不错"
- "代码很清晰"
- "没什么问题"
- 只有表情符号（👍/✅）

### ✅ Reviewer 必须执行

#### 1. 逐行审查
- 审阅每一行变更
- 标注具体行号
- 引用具体代码片段

#### 2. 问题分级

| 级别 | 名称 | 标准 | 处理方式 |
|------|------|------|----------|
| **P1** | 阻断级 | 功能错误、安全问题、数据丢失风险 | 必须立即修复，阻断合并 |
| **P2** | 重要级 | 代码质量、测试覆盖不足、潜在bug | 必须修复后才能放行 |
| **P3** | 建议 | 风格、命名、可优化但不影响功能 | 可登记到 backlog |

#### 3. 具体输出格式
```
## Review 结果

### P1（阻断级）- 必须修复
1. [文件]:[行号] - [问题描述]
   - 问题：[具体问题]
   - 影响：[潜在影响]
   - 建议：[修复建议]

### P2（重要级）- 必须修复
1. ...

### P3（建议）- 可记录
1. ...

### ✅ 好的地方
- [值得肯定的代码实践]
```

---

## ❓ 不确定时的处理

如果遇到以下不确定的情况，**立即 STOP**，主动提问：

### 需要问主人（产品/需求方）
- 需求边界不清晰
- 优先级不确定
- 产品意图模糊
- 业务规则不明确

### 需要问开发者
- 代码意图不清楚
- 技术选型有疑问
- 测试边界不确定
- 安全风险评估

**不要猜测，直接问！**
'''
        },
        'parameters': [
            {'name': 'code_changes', 'type': 'string', 'required': True, 'description': '需要 review 的代码变更描述'}
        ]
    },
    {
        'id': 'merge_approval_gate',
        'name': '合入审批门禁',
        'description': '代码合入 main 分支前的审批流程',
        'type': 'prompt',
        'category': 'code_review',
        'triggers': ['合入main', 'ready to merge', '可以合并', 'merge to main'],
        'config': {
            'prompt': '''
## 合入 Main 分支门禁规范

### 🚫 错误的合入流程
```
修复 → 自己判断改对了 → 合入 main
```
**这是错误的！** 不能自己判断、自己合并。

### ✅ 正确的合入流程
```
修复 → 请求 reviewer 确认 → reviewer 放行 → 合入 main
```

---

## 放行信号判断

### ✅ 有效的放行信号
只有以下明确的、无条件的语句才是有效放行：
- "可以放行了"
- "LGTM" (Looks Good To Me)
- "通过"
- "Approved ✅"
- "没有问题，可以合入"

### ❌ 无效的放行信号（不能合入）
以下都是**条件放行**或**部分放行**，不能合入：

| 语句 | 问题 |
|------|------|
| "整体ok，但xxx需要修改" | 有条件放行，还有待修改项 |
| "只剩小问题" | 还有问题未解决 |
| "基本可以" | 不是明确放行 |
| 只有点赞没有文字 | 意图不明 |
| "看起来差不多" | 模糊信号 |
| 没有任何放行语句 | 未获得放行 |

---

## 合入前检查清单

### 必须满足的条件
- [ ] 至少一位 reviewer 明确放行（有效放行信号）
- [ ] 所有 P1 问题已修复并确认
- [ ] 所有 P2 问题已修复并确认
- [ ] CI/CD 测试通过
- [ ] 没有合并冲突

### 合入命令
确认以上条件全部满足后：
```bash
# 确保在正确的分支
git checkout main
git pull origin main

# 合并功能分支
git merge --no-ff feature/xxx

# 推送到远程
git push origin main
```

---

## ⚠️ 紧急修复流程（Hotfix）

如果需要紧急合入，仍需：
1. 创建 hotfix 分支
2. 最小化变更
3. 获得至少一位 reviewer 口头/消息确认
4. 事后补充完整 review 记录
'''
        },
        'parameters': [
            {'name': 'merge_request', 'type': 'string', 'required': True, 'description': '合入请求描述'}
        ]
    },
    {
        'id': 'branch_workflow',
        'name': '分支开发工作流',
        'description': '基于个人分支和 Merge Request 的开发流程',
        'type': 'prompt',
        'category': 'code_review',
        'triggers': ['创建分支', '新建分支', '开发流程', 'git flow'],
        'config': {
            'prompt': '''
## 分支开发工作流规范

### 分支命名规范
```
feature/[功能名]      - 新功能开发
bugfix/[bug描述]      - Bug 修复
hotfix/[紧急修复]     - 紧急修复
refactor/[重构内容]   - 代码重构
test/[测试内容]       - 测试相关
```

### 完整开发流程

#### 1. 开始新任务
```bash
# 从最新的 main 创建功能分支
git checkout main
git pull origin main
git checkout -b feature/my-feature
```

#### 2. 开发过程中
```bash
# 频繁提交，每个 commit 做一件事
git add [files]
git commit -m "type: description"

# 定期同步 main 的更新
git fetch origin main
git rebase origin/main  # 或 merge
```

#### 3. 提交前准备
```bash
# 确保测试通过
npm test  # 或 make test, pytest 等

# 代码格式化
npm run lint --fix  # 或对应命令

# 提交全部更改
git add .
git commit -m "feat: complete feature X"
```

#### 4. 创建 Merge Request
```bash
# 推送到远程
git push origin feature/my-feature

# 然后在 GitLab/GitHub 上创建 MR/PR
```

#### 5. MR/PR 描述模板
```markdown
## 变更说明
<!-- 简要描述这个 MR 做了什么 -->

## 关联 Issue
Closes #xxx

## 变更类型
- [ ] 新功能
- [ ] Bug 修复
- [ ] 重构
- [ ] 文档更新
- [ ] 测试

## 测试情况
- [ ] 已添加单元测试
- [ ] 已添加集成测试
- [ ] 手动测试通过

## Review 请求
@reviewer1 @reviewer2 请帮忙 review

## Checklist
- [ ] 代码符合团队规范
- [ ] 没有引入新的警告
- [ ] 文档已更新（如适用）
```

#### 6. Review 通过后合入
- 确认获得有效放行信号
- Squash commits（如需要）
- 合并到 main
- 删除功能分支

---

## Commit Message 规范
```
<type>(<scope>): <subject>

<body>

<footer>
```

### Type 类型
- `feat`: 新功能
- `fix`: Bug 修复
- `docs`: 文档
- `style`: 格式（不影响代码运行）
- `refactor`: 重构
- `test`: 测试
- `chore`: 构建/工具变动

### 示例
```
feat(auth): add OAuth2 login support

- Implement OAuth2 authentication flow
- Add login/logout endpoints
- Update user model for OAuth tokens

Closes #123
```
'''
        },
        'parameters': [
            {'name': 'task_description', 'type': 'string', 'required': True, 'description': '任务描述'}
        ]
    },
    # ===== 原有的通用 Skills =====
    {
        'id': 'web_search',
        'name': '网络搜索',
        'description': '使用搜索引擎搜索网络信息',
        'type': 'http',
        'category': 'search',
        'config': {
            'method': 'GET',
            'urlTemplate': 'https://api.duckduckgo.com/?q={query}&format=json',
            'headers': {},
            'bodyTemplate': None,
            'responseParser': 'json'
        },
        'parameters': [
            {'name': 'query', 'type': 'string', 'required': True, 'description': '搜索关键词'}
        ]
    },
    {
        'id': 'http_request',
        'name': 'HTTP 请求',
        'description': '发送自定义 HTTP 请求',
        'type': 'http',
        'category': 'network',
        'config': {
            'method': 'GET',
            'urlTemplate': '{url}',
            'headers': {},
            'bodyTemplate': None,
            'responseParser': 'auto'
        },
        'parameters': [
            {'name': 'url', 'type': 'string', 'required': True, 'description': '请求 URL'},
            {'name': 'method', 'type': 'string', 'required': False, 'description': 'HTTP 方法'},
            {'name': 'body', 'type': 'object', 'required': False, 'description': '请求体'}
        ]
    },
    {
        'id': 'json_transform',
        'name': 'JSON 转换',
        'description': '使用 Python 脚本转换 JSON 数据',
        'type': 'python',
        'category': 'data',
        'config': {
            'script': '''
def transform(data):
    """转换输入数据"""
    result = data
    return result

result = transform(input_data)
'''
        },
        'parameters': [
            {'name': 'input_data', 'type': 'object', 'required': True, 'description': '输入数据'}
        ]
    },
    {
        'id': 'text_analysis',
        'name': '文本分析',
        'description': '使用 Python 进行文本分析',
        'type': 'python',
        'category': 'analysis',
        'config': {
            'script': '''
def analyze(text):
    """分析文本"""
    words = text.split()
    return {
        "word_count": len(words),
        "char_count": len(text),
        "preview": text[:200]
    }

result = analyze(text)
'''
        },
        'parameters': [
            {'name': 'text', 'type': 'string', 'required': True, 'description': '要分析的文本'}
        ]
    },
    {
        'id': 'calculator',
        'name': '计算器',
        'description': '执行数学计算',
        'type': 'python',
        'category': 'utility',
        'config': {
            'script': '''
import math

def calculate(expression):
    """安全地计算数学表达式"""
    allowed_names = {
        'abs': abs, 'round': round, 'min': min, 'max': max,
        'sum': sum, 'pow': pow, 'len': len,
        'math': math
    }
    try:
        # 只允许安全的数学运算
        result = eval(expression, {"__builtins__": {}}, allowed_names)
        return {"success": True, "result": result}
    except Exception as e:
        return {"success": False, "error": str(e)}

result = calculate(expression)
'''
        },
        'parameters': [
            {'name': 'expression', 'type': 'string', 'required': True, 'description': '数学表达式'}
        ]
    },
    {
        'id': 'translate',
        'name': '翻译',
        'description': '调用翻译 API 进行文本翻译',
        'type': 'http',
        'category': 'language',
        'config': {
            'method': 'POST',
            'urlTemplate': 'https://api.example.com/translate',
            'headers': {'Content-Type': 'application/json'},
            'bodyTemplate': '{"text": "{text}", "target": "{target_lang}"}',
            'responseParser': 'json'
        },
        'parameters': [
            {'name': 'text', 'type': 'string', 'required': True, 'description': '要翻译的文本'},
            {'name': 'target_lang', 'type': 'string', 'required': True, 'description': '目标语言'}
        ]
    }
]


class SkillManager:
    """管理 Skill 工具"""

    def __init__(self, storage=None):
        self.storage = storage
        self.skills: Dict[str, Dict] = {}
        self._load_skills()
        self._load_templates_as_skills()  # 自动加载预定义模板

    def _load_skills(self):
        """从存储加载技能配置"""
        if not self.storage:
            return
        try:
            skill_configs = self.storage.get_all_skills()
            for config in skill_configs:
                self.skills[config.get('id')] = config
        except Exception as e:
            print(f'[Skill] 加载技能配置失败: {e}')

    def _load_templates_as_skills(self):
        """将预定义模板加载为技能（如果尚未存在）"""
        for template in SKILL_TEMPLATES:
            template_id = template.get('id')
            # 使用固定 ID 以便模板技能可以被引用
            skill_id = f"template-{template_id}"

            if skill_id not in self.skills:
                self.skills[skill_id] = {
                    'id': skill_id,
                    'name': template.get('name'),
                    'description': template.get('description'),
                    'type': template.get('type'),
                    'category': template.get('category', 'custom'),
                    'config': template.get('config', {}),
                    'parameters': template.get('parameters', []),
                    'triggers': template.get('triggers', []),
                    'templateId': template_id,
                    'isTemplate': True,
                    'createdAt': int(time.time() * 1000),
                    'updatedAt': int(time.time() * 1000)
                }

    def get_templates(self) -> List[Dict]:
        """获取预定义模板列表"""
        return SKILL_TEMPLATES

    def get_template(self, template_id: str) -> Optional[Dict]:
        """获取特定模板"""
        for template in SKILL_TEMPLATES:
            if template['id'] == template_id:
                return template
        return None

    def create_skill_from_template(self, template_id: str, custom_config: Dict = None) -> Dict:
        """从模板创建技能"""
        template = self.get_template(template_id)
        if not template:
            raise ValueError(f'Template not found: {template_id}')

        skill_id = f"skill-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"
        skill = {
            'id': skill_id,
            'name': custom_config.get('name', template['name']) if custom_config else template['name'],
            'description': custom_config.get('description', template['description']) if custom_config else template['description'],
            'type': template['type'],
            'category': template.get('category', 'custom'),
            'config': {**template['config'], **(custom_config.get('config', {}) if custom_config else {})},
            'parameters': template.get('parameters', []),
            'triggers': template.get('triggers', []),
            'templateId': template_id,
            'createdAt': int(time.time() * 1000),
            'updatedAt': int(time.time() * 1000)
        }

        self.skills[skill_id] = skill

        if self.storage:
            self.storage.save_skill(skill_id, skill)

        return skill

    def create_skill(self, config: Dict) -> Dict:
        """创建自定义技能"""
        skill_id = config.get('id') or f"skill-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"

        skill = {
            'id': skill_id,
            'name': config.get('name', 'Unnamed Skill'),
            'description': config.get('description', ''),
            'type': config.get('type', 'http'),
            'category': config.get('category', 'custom'),
            'config': config.get('config', {}),
            'parameters': config.get('parameters', []),
            'triggers': config.get('triggers', []),
            'createdAt': int(time.time() * 1000),
            'updatedAt': int(time.time() * 1000)
        }

        self.skills[skill_id] = skill

        if self.storage:
            self.storage.save_skill(skill_id, skill)

        return skill

    def update_skill(self, skill_id: str, config: Dict) -> Optional[Dict]:
        """更新技能配置"""
        if skill_id not in self.skills:
            return None

        skill = self.skills[skill_id]
        skill.update({
            'name': config.get('name', skill['name']),
            'description': config.get('description', skill['description']),
            'config': config.get('config', skill['config']),
            'parameters': config.get('parameters', skill['parameters']),
            'triggers': config.get('triggers', skill.get('triggers', [])),
            'updatedAt': int(time.time() * 1000)
        })

        if self.storage:
            self.storage.save_skill(skill_id, skill)

        return skill

    def delete_skill(self, skill_id: str) -> bool:
        """删除技能"""
        if skill_id not in self.skills:
            return False

        del self.skills[skill_id]

        if self.storage:
            self.storage.delete_skill(skill_id)

        return True

    def get_skill(self, skill_id: str) -> Optional[Dict]:
        """获取技能配置"""
        return self.skills.get(skill_id)

    def list_skills(self) -> List[Dict]:
        """列出所有技能"""
        return list(self.skills.values())

    async def execute_skill(self, skill_id: str, params: Dict) -> Any:
        """执行技能"""
        skill = self.skills.get(skill_id)
        if not skill:
            raise ValueError(f'Skill not found: {skill_id}')

        skill_type = skill.get('type', 'http')

        if skill_type == 'http':
            return await self._execute_http_skill(skill, params)
        elif skill_type == 'python':
            return await self._execute_python_skill(skill, params)
        elif skill_type == 'prompt':
            return await self._execute_prompt_skill(skill, params)
        else:
            raise ValueError(f'Unknown skill type: {skill_type}')

    async def _execute_prompt_skill(self, skill: Dict, params: Dict) -> Any:
        """执行 Prompt 模板类型的技能（用于工作流指导）"""
        config = skill.get('config', {})
        prompt_template = config.get('prompt', '')

        # 将参数填充到模板中（如果有占位符）
        result = prompt_template
        for key, value in params.items():
            result = result.replace(f'{{{key}}}', str(value))

        return {
            'success': True,
            'type': 'prompt',
            'name': skill.get('name'),
            'triggers': skill.get('triggers', []),
            'prompt': result,
            'instruction': f'请按照以下规范执行 {skill.get("name")} 流程：\n\n{result}'
        }

    def get_skill_by_trigger(self, trigger_text: str) -> Optional[Dict]:
        """根据触发文本查找匹配的技能"""
        trigger_lower = trigger_text.lower()
        for skill in self.skills.values():
            triggers = skill.get('triggers', [])
            for trigger in triggers:
                if trigger.lower() in trigger_lower:
                    return skill
        return None

    def get_skills_by_category(self, category: str) -> List[Dict]:
        """获取指定分类的所有技能"""
        return [s for s in self.skills.values() if s.get('category') == category]

    def get_all_triggers(self) -> Dict[str, str]:
        """获取所有触发词和对应的技能ID"""
        trigger_map = {}
        for skill in self.skills.values():
            for trigger in skill.get('triggers', []):
                trigger_map[trigger.lower()] = skill.get('id')
        return trigger_map

    async def _execute_http_skill(self, skill: Dict, params: Dict) -> Any:
        """执行 HTTP 类型的技能"""
        config = skill.get('config', {})

        # 构建 URL
        url = config.get('urlTemplate', '')
        for key, value in params.items():
            url = url.replace(f'{{{key}}}', str(value))

        method = config.get('method', 'GET').upper()
        headers = config.get('headers', {})

        # 构建请求体
        body = None
        body_template = config.get('bodyTemplate')
        if body_template:
            body = body_template
            for key, value in params.items():
                if isinstance(value, (dict, list)):
                    body = body.replace(f'{{{key}}}', json.dumps(value))
                else:
                    body = body.replace(f'{{{key}}}', str(value))

        # 如果有 body 参数，直接使用
        if 'body' in params and method in ['POST', 'PUT', 'PATCH']:
            body = json.dumps(params['body'])
            headers['Content-Type'] = 'application/json'

        try:
            async with aiohttp.ClientSession() as session:
                async with session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    data=body if body else None,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    response_text = await response.text()

                    # 解析响应
                    parser = config.get('responseParser', 'auto')
                    if parser == 'json' or (parser == 'auto' and 'application/json' in response.content_type):
                        try:
                            return {
                                'success': True,
                                'status': response.status,
                                'data': json.loads(response_text)
                            }
                        except json.JSONDecodeError:
                            return {
                                'success': True,
                                'status': response.status,
                                'data': response_text
                            }
                    else:
                        return {
                            'success': True,
                            'status': response.status,
                            'data': response_text
                        }

        except aiohttp.ClientError as e:
            return {
                'success': False,
                'error': str(e)
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    async def _execute_python_skill(self, skill: Dict, params: Dict) -> Any:
        """执行 Python 脚本类型的技能"""
        config = skill.get('config', {})
        script = config.get('script', '')

        if not script:
            return {'success': False, 'error': 'No script provided'}

        # 安全执行环境
        safe_globals = {
            '__builtins__': {
                'abs': abs, 'all': all, 'any': any, 'bool': bool,
                'dict': dict, 'enumerate': enumerate, 'filter': filter,
                'float': float, 'frozenset': frozenset, 'int': int,
                'isinstance': isinstance, 'len': len, 'list': list,
                'map': map, 'max': max, 'min': min, 'range': range,
                'reversed': reversed, 'round': round, 'set': set,
                'sorted': sorted, 'str': str, 'sum': sum, 'tuple': tuple,
                'type': type, 'zip': zip, 'json': json,
                'True': True, 'False': False, 'None': None
            },
            'json': json
        }

        # 导入常用模块
        try:
            import math
            safe_globals['math'] = math
        except ImportError:
            pass

        try:
            import re
            safe_globals['re'] = re
        except ImportError:
            pass

        try:
            import datetime
            safe_globals['datetime'] = datetime
        except ImportError:
            pass

        # 执行脚本
        local_vars = dict(params)

        try:
            # 在异步上下文中执行同步代码
            loop = asyncio.get_event_loop()
            exec(script, safe_globals, local_vars)

            # 获取结果
            result = local_vars.get('result')

            return {
                'success': True,
                'data': result
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'errorType': type(e).__name__
            }

    def to_tool_definition(self, skill: Dict) -> Dict:
        """将技能转换为工具定义格式"""
        parameters = skill.get('parameters', [])

        properties = {}
        required = []

        for param in parameters:
            param_name = param.get('name')
            properties[param_name] = {
                'type': param.get('type', 'string'),
                'description': param.get('description', '')
            }
            if param.get('required', False):
                required.append(param_name)

        return {
            'name': f"skill_{skill['id']}",
            'description': skill.get('description', skill.get('name')),
            'inputSchema': {
                'type': 'object',
                'properties': properties,
                'required': required
            }
        }
