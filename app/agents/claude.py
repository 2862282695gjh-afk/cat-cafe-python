"""
Claude Agent - 调用 Claude CLI
支持 session chain：每只猫有独立的 Claude CLI 配置目录
"""
import asyncio
import json
import os
import re
import time
from pathlib import Path
from typing import Dict, AsyncGenerator, Optional
from .base import BaseAgent

# 猫咪配置目录的根目录
CATS_CONFIG_ROOT = Path.home() / '.claude-cats'


def ensure_cat_config_dir(agent_id: str) -> Path:
    """确保猫咪的配置目录存在"""
    config_dir = CATS_CONFIG_ROOT / agent_id
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def has_existing_session(config_dir: Path) -> bool:
    """检查是否存在之前的 session"""
    # Claude CLI 的 session 存储在配置目录下的特定文件中
    # 检查 projects 目录是否存在且非空
    projects_dir = config_dir / 'projects'
    if projects_dir.exists():
        # 检查是否有任何 session 文件
        for project in projects_dir.iterdir():
            if project.is_dir():
                sessions = list(project.glob('*.json'))
                if sessions:
                    return True
    return False


def get_default_system_prompt(cat_name: str = 'Claude') -> str:
    """生成默认的系统提示词，使用猫咪的实际名字"""
    return f"""你是一只可爱的猫咪 ({cat_name})，生活在猫咪咖啡馆里。

## 你的特点
- 温柔友善，喜欢帮助人类
- 回答问题时专业且友好
- 偶尔会在回答中加入一些猫咪的视角
- 你是 {cat_name}，不是其他猫咪

## 工具使用说明
- 你已经拥有完整权限，可以直接执行所有工具（Bash、Read、Write、Edit 等）
- 不需要请求用户授权或批准，直接执行即可
- 不要说"需要授权"、"请点击批准"之类的话
- 如果工具执行出错，如实告诉用户错误信息
- 工具执行结果会直接返回给你，根据结果继续操作

## Agent-to-Agent (A2A) 协作
咖啡馆里还有其他猫咪可以协助你。当你遇到以下情况时，可以呼叫其他猫咪：

1. **需要代码 Review**：完成后可以在回复末尾说 "我写完了，@其他猫咪名字 能帮我 review 一下吗？"
2. **需要其他专长**：如果问题不在你的专长范围内，可以说 "这个问题 @其他猫咪名字 更擅长，我帮你叫他"
3. **需要验证结果**：完成后可以呼叫其他猫咪验证

**格式**：在回复末尾用 @猫咪名字 来呼叫
**注意**：每次最多呼叫一只猫咪，形成协作链

## 身份提醒
- 你的名字是 {cat_name}，记住自己的身份
- 当被其他猫咪呼叫时，你是以 {cat_name} 的身份回应
"""

DEFAULT_SYSTEM_PROMPT = get_default_system_prompt('Claude')

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

# 需要确认的危险工具模式（仅限真正危险的操作）
DANGEROUS_TOOL_PATTERNS = {
    'Bash': ['rm -rf', 'rm -r', 'git push --force', 'git push -f', 'drop database', 'truncate table'],
}


def is_retryable_error(error_message: str) -> bool:
    if not error_message:
        return False
    msg = error_message.lower()
    return any(p.lower() in msg for p in RETRY_CONFIG['retryable_patterns'])


def is_dangerous_tool(tool_name: str, tool_input: Dict) -> bool:
    """检查工具调用是否是危险操作"""
    if tool_name == 'Bash':
        patterns = DANGEROUS_TOOL_PATTERNS.get('Bash', [])
        command = tool_input.get('command', '').lower()
        return any(p.lower() in command for p in patterns)
    # Write 和 Edit 操作不需要额外确认（Claude CLI 已配置 --dangerously-skip-permissions）
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
        name = config.get('name', '布偶猫')
        # 如果没有自定义 systemPrompt，使用默认的（包含正确的名字）
        system_prompt = config.get('systemPrompt')
        if not system_prompt:
            system_prompt = get_default_system_prompt(name)

        super().__init__({
            'id': config.get('id', 'opus'),
            'name': name,
            'avatar': config.get('avatar', '🐱'),
            'description': config.get('description', '温柔友善的 Claude，擅长各种任务'),
            'systemPrompt': system_prompt,
            'voice': config.get('voice', {
                'pitch': 0.7,
                'rate': 0.85,
                'description': '温柔低沉'
            })
        })

        # 为这只猫创建独立的配置目录
        self.config_dir = ensure_cat_config_dir(self.id)
        self.session_count = 0  # 用于追踪是否是第一次调用

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

                if last_error:
                    if not should_retry:
                        print(f'[Claude Agent] 不可重试的错误: {last_error}')
                        yield {'type': 'status', 'status': 'idle', 'message': '出错', 'private': True}
                        yield {'type': 'error', 'message': last_error, 'private': False}
                    return

                # 如果既没有响应也没有错误，可能是空响应，不再重试
                print(f'[Claude Agent] 空响应，不再重试')
                yield {'type': 'status', 'status': 'idle', 'message': '完成', 'private': True}
                yield {'type': 'done', 'response': ''}
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
        """执行一次 Claude CLI 调用，支持 session chain"""
        import os

        env = os.environ.copy()

        # 代理设置（仅在需要时启用）
        # env['http_proxy'] = 'http://127.0.0.1:7890'
        # env['https_proxy'] = 'http://127.0.0.1:7890'

        # 取消设置 CLAUDECODE 以允许嵌套调用
        env.pop('CLAUDECODE', None)

        # 确保 GLM API 配置被正确传递
        # 从 .env 文件或环境变量中获取
        if not env.get('ANTHROPIC_API_KEY') and os.getenv('ANTHROPIC_API_KEY'):
            env['ANTHROPIC_API_KEY'] = os.getenv('ANTHROPIC_API_KEY')
        if not env.get('ANTHROPIC_BASE_URL') and os.getenv('ANTHROPIC_BASE_URL'):
            env['ANTHROPIC_BASE_URL'] = os.getenv('ANTHROPIC_BASE_URL')

        print(f"[Claude Agent] API Key: {'已配置' if env.get('ANTHROPIC_API_KEY') else '未配置'}")
        print(f"[Claude Agent] Base URL: {env.get('ANTHROPIC_BASE_URL', '默认')}")

        # 关键：设置 CLAUDE_CONFIG_DIR 为这只猫的独立目录
        # 这样每只猫的 session 就不会互相干扰
        env['CLAUDE_CONFIG_DIR'] = str(self.config_dir)

        # 构建命令参数
        # --dangerously-skip-permissions: 跳过所有权限检查，允许工具自动执行
        # 注意：GLM API 的 session resume 可能有兼容性问题，暂时禁用
        cmd_args = [
            'claude',
            '-p', full_prompt,
            '--output-format', 'stream-json',
            '--verbose',
            '--dangerously-skip-permissions'
        ]

        # 暂时禁用 session resume 以解决 GLM API 兼容性问题
        # has_session = self.session_count > 0 or has_existing_session(self.config_dir)
        # if has_session:
        #     cmd_args.append('--resume')
        #     print(f"[Claude Agent] {self.name} 继续之前的 session (第 {self.session_count + 1} 次调用)")
        # else:
        #     print(f"[Claude Agent] {self.name} 创建新 session")

        print(f"[Claude Agent] {self.name} 新会话调用")
        self.session_count += 1
        print(f"[Claude Agent] 配置目录: {self.config_dir}")

        process = await asyncio.create_subprocess_exec(
            *cmd_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            limit=1024 * 1024  # 增加缓冲区限制到 1MB
        )

        full_response = ''
        buffer = ''

        # 非阻塞读取 stderr
        async def read_stderr():
            while True:
                try:
                    line = await asyncio.wait_for(process.stderr.readline(), timeout=0.1)
                    if line:
                        print(f"[Claude Agent stderr] {line.decode('utf-8').strip()}")
                    elif process.returncode is not None:
                        break
                except asyncio.TimeoutError:
                    if process.returncode is not None:
                        break
                    continue
                except Exception as e:
                    print(f"[Claude Agent stderr] 读取错误: {e}")
                    break

        stderr_task = asyncio.create_task(read_stderr())

        try:
            while True:
                # 检查取消信号
                if signal and signal.get('aborted', False):
                    process.terminate()
                    yield {'type': 'error', 'message': '请求已取消'}
                    return

                # 读取数据块而不是行，避免缓冲区溢出
                try:
                    chunk = await asyncio.wait_for(process.stdout.read(1024 * 64), timeout=120)
                except asyncio.TimeoutError:
                    print('[Claude Agent] 超时，终止进程')
                    process.terminate()
                    break

                if not chunk:
                    # 检查进程是否结束
                    if process.returncode is not None:
                        # 处理 buffer 中剩余的数据
                        if buffer.strip():
                            await self._process_json_lines(buffer, full_response)
                        break
                    await asyncio.sleep(0.1)
                    continue

                buffer += chunk.decode('utf-8', errors='replace')

                # 处理完整的 JSON 行
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    line = line.strip()
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
                                    text_content = block.get('text', '')
                                    print(f"[Claude Agent] text block: {text_content[:100] if text_content else '(空)'}...")
                                    full_response += text_content
                                    yield {'type': 'text', 'text': text_content}
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
                            result_text = data.get('result', '')
                            print(f"[Claude Agent] result 字段内容: {str(result_text)[:200] if result_text else '(空)'}")
                            if result_text:
                                full_response = result_text
                            yield {
                                'type': 'result',
                                'cost': data.get('cost'),
                                'duration': data.get('duration_ms'),
                                'usage': data.get('usage', {})
                            }

                        # 处理 tool_result（工具执行结果）
                        if data.get('type') == 'tool_result':
                            tool_name = data.get('tool_name', 'unknown')
                            is_error = data.get('is_error', False)
                            content = data.get('content', '')
                            if is_error:
                                print(f"[Claude Agent] tool_result 错误: {tool_name} - {content[:100]}")
                                yield {
                                    'type': 'tool_error',
                                    'name': tool_name,
                                    'error': content
                                }
                            else:
                                print(f"[Claude Agent] tool_result 成功: {tool_name}")
                                yield {
                                    'type': 'tool_result',
                                    'name': tool_name,
                                    'content': content[:500]  # 限制长度
                                }

                        # 处理错误事件
                        if data.get('type') == 'error':
                            error_msg = data.get('message', data.get('error', '未知错误'))
                            print(f"[Claude Agent] 错误事件: {error_msg}")
                            yield {
                                'type': 'error',
                                'message': error_msg
                            }

                    except json.JSONDecodeError as e:
                        print(f"[Claude Agent] JSON 解析错误: {e}, 行: {line[:100]}")
                        pass

        except Exception as e:
            print(f"[Claude Agent] 调用异常: {e}")
            import traceback
            traceback.print_exc()
        finally:
            stderr_task.cancel()
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    process.kill()

        yield {'type': 'done', 'response': full_response}

    async def chat(self, message: str, user_id: str = None) -> str:
        """
        简单的聊天接口（用于QQ机器人等简单场景）
        收集所有流式输出并返回完整回复
        """
        full_response = []
        try:
            async for event in self.invoke(message):
                if event['type'] == 'text':
                    full_response.append(event['text'])
                elif event['type'] == 'done':
                    return event['response'] or ''.join(full_response)
                elif event['type'] == 'error':
                    return f"❌ {event['message']}"
            return ''.join(full_response)
        except Exception as e:
            return f"❌ 发生错误: {str(e)}"
