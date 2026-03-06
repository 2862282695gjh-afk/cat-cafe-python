"""
DeepSeek Agent - 使用 DeepSeek API 实现 Claude CLI 兼容的 Agent
使用完整的六层架构实现：
- 2 调度层: Agent主循环 + 消息队列
- 2 执行层: 工具引擎 + 并发控制
- 2 管理层: 上下文压缩 + SubAgent

支持六层安全防护架构：
- Layer 1: 输入验证层
- Layer 2: 权限控制层
- Layer 3: 沙箱隔离层
- Layer 4: 执行监控层
- Layer 5: 错误恢复层
- Layer 6: 审计记录层
"""
import asyncio
import json
import os
from typing import Dict, AsyncGenerator, Optional
from .base import BaseAgent

# 导入 DeepSeek CLI v3
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from deepseek_cli.deepseek_cli_v3 import DeepSeekCLIv3


def get_default_system_prompt(cat_name: str = 'DeepSeek') -> str:
    """生成默认的系统提示词"""
    return f"""你是 {cat_name}，一只可爱的猫咪，生活在猫咪咖啡馆里。

## 核心能力
你是一个具有完整记忆系统的智能助手，能够：
- 记住之前的对话和决策
- 理解项目上下文
- 执行复杂的编程任务

## 工作模式
采用 Think → Act → Observe 循环：
1. 思考：分析问题，制定计划
2. 行动：执行工具调用
3. 观察：分析结果，决定下一步

## 你的特点
- 温柔友善，喜欢帮助人类
- 回答问题时专业且友好
- 偶尔会在回答中加入一些猫咪的视角
- 你是 {cat_name}，不是其他猫咪

## 可用工具
- Read: 读取文件内容
- Write: 写入文件
- Edit: 编辑文件
- Bash: 执行命令
- Glob: 查找文件
- Grep: 搜索内容

## 安全机制
- 危险操作需要确认
- 文件操作有权限检查
- 命令执行有超时限制
- 所有操作都会被审计记录

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


class DeepSeekAgent(BaseAgent):
    """DeepSeek Agent 实现 - 使用六层架构，支持安全防护"""

    # 类级别的 CLI 实例缓存（按 working_dir 分组）
    _cli_instances: Dict[str, DeepSeekCLIv3] = {}

    def __init__(self, config: Dict):
        name = config.get('name', 'DeepSeek猫')
        system_prompt = config.get('systemPrompt')
        if not system_prompt:
            system_prompt = get_default_system_prompt(name)

        super().__init__({
            'id': config.get('id', 'deepseek'),
            'name': name,
            'avatar': config.get('avatar', '🐱'),
            'description': config.get('description', 'DeepSeek 驱动的猫咪，擅长编程和推理'),
            'systemPrompt': system_prompt,
            'voice': config.get('voice', {
                'pitch': 1.0,
                'rate': 1.0,
                'description': '清晰有力'
            })
        })

        self.model = config.get('model', 'deepseek-chat')
        self.api_key = config.get('apiKey') or os.getenv('DEEPSEEK_API_KEY')
        self.base_url = config.get('baseUrl') or os.getenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com')

        # 安全配置
        self.enable_security = config.get('enableSecurity', False)
        self.security_level = config.get('securityLevel', 'standard')
        self.security_manager = None  # 由外部注入

        if not self.api_key:
            raise ValueError("DeepSeek API Key 未设置，请设置 DEEPSEEK_API_KEY 环境变量或在配置中提供 apiKey")

    def _get_cli(self, working_dir: str) -> DeepSeekCLIv3:
        """获取或创建 CLI 实例（按工作目录缓存）"""
        if working_dir not in self._cli_instances:
            self._cli_instances[working_dir] = DeepSeekCLIv3(
                api_key=self.api_key,
                base_url=self.base_url,
                model=self.model,
                working_dir=working_dir,
                max_iterations=50,
                max_tokens=128000,
                compression_threshold=0.92
            )
        return self._cli_instances[working_dir]

    async def invoke(
        self,
        prompt: str,
        signal=None,
        working_dir: Optional[str] = None,
        thread_id: Optional[str] = None
    ) -> AsyncGenerator[Dict, None]:
        """调用 DeepSeek API（六层架构 + 安全防护）"""
        # 使用提供的 working_dir 或当前目录
        work_dir = working_dir or os.getcwd()

        # 如果启用了安全管理器，进行安全检查
        if self.security_manager:
            try:
                from deepseek_cli.security import AuditEventType, AuditSeverity

                # 记录开始执行
                await self.security_manager.audit_logging.log_event(
                    event_type=AuditEventType.TOOL_EXECUTE,
                    severity=AuditSeverity.INFO,
                    description=f"DeepSeek Agent 开始处理请求",
                    tool_name="DeepSeekAgent",
                    details={"prompt_length": len(prompt)}
                )

                # 检查输入是否安全
                check_result = await self.security_manager.check_execution(
                    tool_name="Prompt",
                    arguments={"prompt": prompt[:500]}  # 只检查前500字符
                )

                if not check_result.allowed:
                    yield {'type': 'error', 'message': f'安全检查未通过: {check_result.reason}', 'private': True}
                    return

            except Exception as e:
                print(f'[DeepSeek Agent] 安全检查异常: {e}')
                # 继续执行，不因安全检查失败而中断

        # 获取 CLI 实例
        cli = self._get_cli(work_dir)

        full_response = ''

        try:
            async for event in cli.run(
                prompt=prompt,
                system_prompt=self.system_prompt,
                verbose=False,
                stream_json=True
            ):
                # 检查取消信号
                if signal and signal.get('aborted', False):
                    yield {'type': 'error', 'message': '请求已取消', 'private': True}
                    return

                event_type = event.get('type')

                # 发送状态事件
                if event_type == 'assistant':
                    content = event.get('message', {}).get('content', [])
                    for block in content:
                        if block.get('type') == 'text':
                            yield {'type': 'status', 'status': 'streaming', 'message': '正在回复...', 'private': True}
                            yield {'type': 'text', 'text': block.get('text', '')}
                        elif block.get('type') == 'tool_use':
                            tool_name = block.get('name', 'unknown')
                            tool_input = block.get('input', {})

                            # 安全检查工具调用
                            needs_confirmation = False
                            if self.security_manager:
                                try:
                                    check_result = await self.security_manager.check_execution(
                                        tool_name=tool_name,
                                        arguments=tool_input
                                    )
                                    if check_result.needs_confirmation:
                                        needs_confirmation = True
                                    elif not check_result.allowed:
                                        yield {
                                            'type': 'tool_error',
                                            'name': tool_name,
                                            'error': f'安全检查未通过: {check_result.reason}'
                                        }
                                        continue
                                except Exception as e:
                                    print(f'[安全] 工具检查异常: {e}')

                            yield {'type': 'status', 'status': 'tool', 'message': f'使用工具: {tool_name}', 'private': True}
                            yield {
                                'type': 'tool',
                                'name': tool_name,
                                'input': tool_input,
                                'description': f'执行 {tool_name}',
                                'needsConfirmation': needs_confirmation
                            }

                elif event_type == 'tool_result':
                    tool_name = event.get('tool_name', 'unknown')
                    content = event.get('content', '')
                    is_error = '错误' in content or not event.get('success', True)

                    # 审计记录
                    if self.security_manager:
                        try:
                            await self.security_manager.audit_logging.log_tool_execution(
                                tool_name=tool_name,
                                execution_id=event.get('tool_call_id', ''),
                                arguments={},
                                result=content[:200],
                                success=not is_error
                            )
                        except Exception as e:
                            print(f'[审计] 记录失败: {e}')

                    if is_error:
                        yield {
                            'type': 'tool_error',
                            'name': tool_name,
                            'error': content
                        }
                    else:
                        yield {
                            'type': 'tool_result',
                            'name': tool_name,
                            'content': content[:500]  # 限制长度
                        }

                elif event_type == 'tool_needs_confirmation':
                    # 需要用户确认的危险操作
                    yield {
                        'type': 'tool',
                        'name': event.get('name'),
                        'input': {},  # 需要从存储中恢复
                        'description': event.get('message', '需要确认操作'),
                        'needsConfirmation': True,
                        'toolCallId': event.get('tool_call_id')
                    }

                elif event_type == 'result':
                    full_response = event.get('result', '')
                    usage = event.get('usage', {})
                    stats = event.get('stats', {})
                    if usage or stats:
                        yield {
                            'type': 'result',
                            'usage': {
                                'input_tokens': stats.get('input_tokens', usage.get('input_tokens', 0)),
                                'output_tokens': stats.get('output_tokens', usage.get('output_tokens', 0)),
                                'total_tokens': stats.get('total_tokens', usage.get('total_tokens', 0))
                            },
                            'stats': stats
                        }

                elif event_type == 'complete':
                    full_response = event.get('response', '')
                    stats = event.get('stats', {})
                    yield {
                        'type': 'result',
                        'usage': {
                            'input_tokens': 0,
                            'output_tokens': 0,
                            'total_tokens': stats.get('total_tokens', 0)
                        },
                        'stats': stats
                    }

            # 完成
            yield {'type': 'status', 'status': 'idle', 'message': '完成', 'private': True}
            yield {'type': 'done', 'response': full_response}

            # 审计记录完成
            if self.security_manager:
                try:
                    from deepseek_cli.security import AuditEventType, AuditSeverity
                    await self.security_manager.audit_logging.log_event(
                        event_type=AuditEventType.TOOL_SUCCESS,
                        severity=AuditSeverity.INFO,
                        description="DeepSeek Agent 处理完成",
                        tool_name="DeepSeekAgent"
                    )
                except Exception as e:
                    print(f'[审计] 记录完成失败: {e}')

        except Exception as e:
            print(f'[DeepSeek Agent] 调用异常: {e}')
            import traceback
            traceback.print_exc()

            # 审计记录错误
            if self.security_manager:
                try:
                    from deepseek_cli.security import AuditEventType, AuditSeverity
                    await self.security_manager.audit_logging.log_event(
                        event_type=AuditEventType.TOOL_FAILURE,
                        severity=AuditSeverity.WARNING,
                        description=f"DeepSeek Agent 处理失败: {str(e)[:100]}",
                        tool_name="DeepSeekAgent"
                    )
                except Exception:
                    pass

            yield {'type': 'status', 'status': 'idle', 'message': '出错', 'private': True}
            yield {'type': 'error', 'message': str(e), 'private': True}

    def confirm_tool(self, tool_call_id: str) -> bool:
        """确认工具调用"""
        # 找到对应的 CLI 实例并确认
        for cli in self._cli_instances.values():
            if cli.confirm_tool(tool_call_id):
                return True
        return False

    def deny_tool(self, tool_call_id: str) -> bool:
        """拒绝工具调用"""
        for cli in self._cli_instances.values():
            if cli.deny_tool(tool_call_id):
                return True
        return False

    def get_stats(self) -> Dict:
        """获取所有实例的统计信息"""
        stats = {
            working_dir: cli.get_stats()
            for working_dir, cli in self._cli_instances.items()
        }

        # 添加安全统计
        if self.security_manager:
            stats['security'] = {
                'enabled': True,
                'level': self.security_level
            }

        return stats

    async def get_security_stats(self) -> Dict:
        """获取安全统计信息"""
        if not self.security_manager:
            return {'enabled': False}

        try:
            return await self.security_manager.get_stats()
        except Exception as e:
            return {'enabled': True, 'error': str(e)}

    async def chat(self, message: str, user_id: str = None, working_dir: str = None) -> str:
        """
        简单的聊天接口（用于QQ机器人等简单场景）
        收集所有流式输出并返回完整回复
        """
        work_dir = working_dir or os.getcwd()
        full_response = []
        try:
            async for event in self.invoke(message, working_dir=work_dir):
                if event['type'] == 'text':
                    full_response.append(event['text'])
                elif event['type'] == 'done':
                    return event['response'] or ''.join(full_response)
                elif event['type'] == 'error':
                    return f"❌ {event['message']}"
            return ''.join(full_response)
        except Exception as e:
            return f"❌ 发生错误: {str(e)}"

