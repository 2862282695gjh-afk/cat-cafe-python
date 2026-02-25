"""
Claude Agent - 调用 Claude CLI
"""
import asyncio
import json
import re
import time
from typing import Dict, AsyncGenerator, Optional
from .base import BaseAgent


DEFAULT_SYSTEM_PROMPT = """你是一只可爱的布偶猫 (Claude)，生活在猫咪咖啡馆里。

## 你的特点
- 温柔友善，喜欢帮助人类
- 回答问题时专业且友好
- 偶尔会在回答中加入一些猫咪的视角

## 工具权限
你已经有权限直接执行工具（Bash、Read、Write、Edit 等），不需要请求用户批准。当用户让你执行操作时，直接执行即可，不要说"需要批准"或"请在终端点击批准"。

## Agent-to-Agent (A2A) 协作
咖啡馆里还有其他猫咪可以协助你。当你遇到以下情况时，可以呼叫其他猫咪：

1. **需要代码 Review**：完成后可以在回复末尾说 "我写完了，@缅因猫 能帮我 review 一下吗？"
2. **需要其他专长**：如果问题不在你的专长范围内，可以说 "这个问题 @暹罗猫 更擅长，我帮你叫他"
3. **需要验证结果**：完成后可以呼叫其他猫咪验证

**格式**：在回复末尾用 @猫咪名字 来呼叫
**注意**：每次最多呼叫一只猫咪，形成协作链

## 示例
- "@缅因猫 这个代码帮我看看有没有 bug"
- "逻辑上应该没问题了，@布偶猫 你觉得呢？"""

# 重试配置
RETRY_CONFIG = {
    'max_retries': 3,
    'base_delay': 5,      # 基础等待 5 秒
    'max_delay': 60,      # 最大等待 60 秒
    'retryable_patterns': ['429', 'rate limit', 'too many requests']
}

# 工具名称的中文映射
TOOL_NAMES = {
    'read': '读取文件',
    'write': '写入文件',
    'edit': '编辑文件',
    'bash': '执行命令',
    'grep': '搜索内容',
    'glob': '查找文件',
    'task': '启动子任务',
    'web_fetch': '获取网页',
    'web_search': '搜索网络'
}

# 需要确认的危险工具模式
DANGEROUS_TOOL_PATTERNS = {
    'Bash': ['rm ', 'git push', 'git commit', 'delete', 'drop ', 'truncate'],
    'Write': [],  # 所有写操作都可能需要确认
    'Edit': [],   # 所有编辑操作都可能需要确认
}


def is_retryable_error(error_message: str) -> bool:
    if not error_message:
        return False
    msg = error_message.lower()
    return any(p.lower() in msg for p in RETRY_CONFIG['retryable_patterns'])


def is_dangerous_tool(tool_name: str, tool_input: Dict) -> bool:
    """检查工具调用是否是危险操作"""
    if tool_name in DANGEROUS_TOOL_PATTERNS:
        patterns = DANGEROUS_TOOL_PATTERNS[tool_name]
        if tool_name == 'Bash':
            command = tool_input.get('command', '').lower()
            return any(p.lower() in command for p in patterns)
        elif tool_name in ('Write', 'Edit'):
            # 写入和编辑操作总是标记为可能需要关注
            return True
    return False


def get_tool_description(tool_name: str, tool_input: Dict) -> str:
    """获取工具调用的简短描述"""
    if tool_name == 'Bash':
        cmd = tool_input.get('command', '')
        return f"执行命令: {cmd[:50]}..." if len(cmd) > 50 else f"执行命令: {cmd}"
    elif tool_name == 'Write':
        return f"写入文件: {tool_input.get('file_path', 'unknown')}"
    elif tool_name == 'Edit':
        return f"编辑文件: {tool_input.get('file_path', 'unknown')}"
    elif tool_name == 'Read':
        return f"读取文件: {tool_input.get('file_path', 'unknown')}"
    elif tool_name == 'Grep':
        return f"搜索: {tool_input.get('pattern', '')}"
    else:
        return f"{tool_name}"


class ClaudeAgent(BaseAgent):
    def __init__(self, config: Dict):
        super().__init__({
            'id': config.get('id', 'opus'),
            'name': config.get('name', '布偶猫'),
            'avatar': config.get('avatar', '🐱'),
            'description': config.get('description', '温柔友善的 Claude，擅长各种任务'),
            'systemPrompt': config.get('systemPrompt', DEFAULT_SYSTEM_PROMPT),
            'voice': config.get('voice', {
                'pitch': 0.7,
                'rate': 0.85,
                'description': '温柔低沉'
            })
        })

    async def invoke(self, prompt: str, signal=None) -> AsyncGenerator[Dict, None]:
        full_prompt = f"{self.system_prompt}\n\n---\n\n{prompt}"

        for attempt in range(RETRY_CONFIG['max_retries'] + 1):
            # 检查是否被取消
            if signal and signal.get('aborted', False):
                yield {'type': 'error', 'message': '请求已取消', 'private': True}
                return

            if attempt > 0:
                delay = min(
                    RETRY_CONFIG['base_delay'] * (2 ** (attempt - 1)),
                    RETRY_CONFIG['max_delay']
                )
                print(f"[Claude Agent] 第 {attempt} 次重试，等待 {delay} 秒...")
                yield {'type': 'status', 'status': 'retry', 'message': f'{delay} 秒后重试...', 'private': True}
                yield {'type': 'retry', 'attempt': attempt, 'delay': delay, 'message': f'请求过于频繁，{delay} 秒后重试...', 'private': True}
                await asyncio.sleep(delay)

                if signal and signal.get('aborted', False):
                    yield {'type': 'error', 'message': '请求已取消', 'private': True}
                    return

            print(f"[Claude Agent] 开始调用 (尝试 {attempt + 1}/{RETRY_CONFIG['max_retries'] + 1}), agent: {self.name}")
            yield {'type': 'status', 'status': 'thinking', 'message': '正在思考...', 'private': True}

            full_response = ''
            last_error = None
            should_retry = False

            try:
                async for event in self._invoke_once(full_prompt, signal):
                    if event['type'] == 'error':
                        last_error = event['message']
                        should_retry = is_retryable_error(event['message'] or '')
                        if should_retry:
                            print(f'[Claude Agent] 检测到可重试错误: {event["message"]}')
                            break
                        yield {**event, 'private': True}
                        return

                    if event['type'] == 'status':
                        yield {**event, 'private': True}
                        continue

                    if event['type'] == 'thinking':
                        yield {'type': 'status', 'status': 'thinking', 'message': '深度思考中...', 'private': True}
                        yield {**event, 'private': True}
                        continue

                    if event['type'] == 'tool':
                        tool_name = TOOL_NAMES.get(event['name'], event['name'])
                        yield {'type': 'status', 'status': 'tool', 'message': f'使用工具: {tool_name}', 'private': True}
                        yield {**event, 'private': True}
                        continue

                    if event['type'] == 'text':
                        yield {'type': 'status', 'status': 'streaming', 'message': '正在回复...', 'private': True}
                        full_response += event['text']
                        yield {**event, 'private': False}
                        continue

                    if event['type'] == 'result':
                        yield {**event, 'private': True}
                        continue

                    if event['type'] == 'done':
                        full_response = event['response']

                    yield event

                if full_response:
                    print(f'[Claude Agent] 完成, response length: {len(full_response)}')
                    yield {'type': 'status', 'status': 'idle', 'message': '完成', 'private': True}
                    return

                if not should_retry and last_error:
                    print(f'[Claude Agent] 不可重试的错误: {last_error}')
                    yield {'type': 'status', 'status': 'idle', 'message': '出错', 'private': True}
                    return

            except Exception as e:
                print(f'[Claude Agent] 调用异常: {e}')
                last_error = str(e)
                should_retry = is_retryable_error(last_error)

                if not should_retry:
                    yield {'type': 'status', 'status': 'idle', 'message': '出错', 'private': True}
                    yield {'type': 'error', 'message': last_error, 'private': True}
                    return

        print('[Claude Agent] 所有重试失败')
        yield {'type': 'status', 'status': 'idle', 'message': '失败', 'private': True}
        yield {'type': 'error', 'message': 'API 访问频率限制，请等待 1-2 分钟后再试', 'private': False}

    async def _invoke_once(self, full_prompt: str, signal=None) -> AsyncGenerator[Dict, None]:
        """执行一次 Claude CLI 调用"""
        import os

        env = os.environ.copy()
        env['http_proxy'] = 'http://127.0.0.1:7890'
        env['https_proxy'] = 'http://127.0.0.1:7890'
        # 取消设置 CLAUDECODE 以允许嵌套调用
        env.pop('CLAUDECODE', None)

        # 构建命令参数
        cmd_args = [
            'claude',
            '-p', full_prompt,
            '--output-format', 'stream-json',
            '--verbose',
            '--dangerously-skip-permissions'  # 跳过权限检查，允许工具自动执行
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env
        )

        full_response = ''
        buffer = ''

        try:
            while True:
                # 检查取消信号
                if signal and signal.get('aborted', False):
                    process.terminate()
                    yield {'type': 'error', 'message': '请求已取消'}
                    return

                # 读取一行
                try:
                    line = await asyncio.wait_for(process.stdout.readline(), timeout=120)
                except asyncio.TimeoutError:
                    print('[Claude Agent] 超时，终止进程')
                    process.terminate()
                    break

                if not line:
                    # 检查进程是否结束
                    if process.returncode is not None:
                        break
                    await asyncio.sleep(0.1)
                    continue

                line = line.decode('utf-8').strip()
                if not line:
                    continue

                try:
                    data = json.loads(line)
                    print(f"[Claude Agent] 收到数据类型: {data.get('type')}")

                    # 处理 assistant 消息
                    if data.get('type') == 'assistant' and data.get('message', {}).get('content'):
                        for block in data['message']['content']:
                            if block.get('type') == 'thinking':
                                print(f"[Claude Agent] thinking block: {block.get('thinking', '')[:50]}")
                                yield {'type': 'thinking', 'text': block.get('thinking', '')}
                            elif block.get('type') == 'text':
                                full_response += block.get('text', '')
                                yield {'type': 'text', 'text': block.get('text', '')}
                            elif block.get('type') == 'tool_use':
                                tool_name = block.get('name')
                                tool_input = block.get('input', {})
                                print(f"[Claude Agent] tool_use: {tool_name}")
                                # 检查是否是危险操作
                                is_dangerous = is_dangerous_tool(tool_name, tool_input)
                                tool_desc = get_tool_description(tool_name, tool_input)
                                yield {
                                    'type': 'tool',
                                    'name': tool_name,
                                    'input': tool_input,
                                    'description': tool_desc,
                                    'needsConfirmation': is_dangerous
                                }

                    # 处理结果
                    if data.get('type') == 'result':
                        if data.get('result'):
                            full_response = data['result']
                        yield {
                            'type': 'result',
                            'cost': data.get('cost'),
                            'duration': data.get('duration_ms'),
                            'usage': data.get('usage', {})
                        }

                except json.JSONDecodeError:
                    pass

        finally:
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    process.kill()

        yield {'type': 'done', 'response': full_response}
