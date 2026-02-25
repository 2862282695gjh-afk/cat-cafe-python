"""
Base Agent 类
"""
import re
from typing import Dict, Optional, List, Any, AsyncGenerator


class BaseAgent:
    """Agent 基类"""

    # 中文猫名到 ID 的映射
    NAME_TO_ID = {
        '布偶猫': 'opus',
        '缅因猫': 'codex',
        '暹罗猫': 'gemini',
        '英国短毛猫': 'gpt',
        '波斯猫': 'deepseek'
    }

    def __init__(self, config: Dict):
        self.id = config.get('id', 'unknown')           # 'opus' | 'codex' | 'gemini'
        self.name = config.get('name', '猫咪')          # 显示名称
        self.avatar = config.get('avatar', '🐱')
        self.system_prompt = config.get('systemPrompt', '')
        self.description = config.get('description', '')
        # 语音个性配置
        self.voice = config.get('voice', {
            'pitch': 1.0,
            'rate': 1.0,
            'description': '标准声音'
        })

    async def invoke(self, prompt: str, signal=None) -> AsyncGenerator[Dict, None]:
        """
        调用 Agent（子类实现）
        :param prompt: 输入提示
        :param signal: 取消信号
        :yields: 事件字典
        """
        raise NotImplementedError('子类必须实现 invoke 方法')

    def parse_mentions(self, response: str) -> List[str]:
        """
        从回复中解析 @mentions
        :param response: Agent 回复
        :returns: 提到的 Agent ID 列表
        """
        mention_regex = r'@(\S+)'
        mentions = []
        for match in re.finditer(mention_regex, response):
            mention = match.group(1)
            # 转换中文猫名到 ID
            if mention in self.NAME_TO_ID:
                mentions.append(self.NAME_TO_ID[mention])
            else:
                # 直接使用 ID
                mentions.append(mention)
        return list(set(mentions))  # 去重

    def get_info(self) -> Dict:
        """获取 Agent 信息"""
        return {
            'id': self.id,
            'name': self.name,
            'avatar': self.avatar,
            'description': self.description,
            'voice': self.voice
        }
