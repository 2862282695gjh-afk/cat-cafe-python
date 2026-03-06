"""
DeepSeek API 客户端
支持流式输出和工具调用
"""
import json
import httpx
from typing import AsyncGenerator, Dict, List, Optional, Any


class DeepSeekClient:
    """DeepSeek API 客户端 (OpenAI 兼容格式)"""

    def __init__(self, api_key: str, base_url: str = "https://api.deepseek.com"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = 120.0

    async def chat_completion_stream(
        self,
        model: str,
        messages: List[Dict],
        system: str = None,
        tools: List[Dict] = None,
        stream: bool = True,
        temperature: float = 0.7,
        max_tokens: int = 4096
    ) -> AsyncGenerator[Dict, None]:
        """
        流式调用 DeepSeek Chat API

        Args:
            model: 模型名称
            messages: 消息列表
            system: 系统提示词
            tools: 工具定义
            stream: 是否流式输出
            temperature: 温度参数
            max_tokens: 最大 token 数

        Yields:
            事件字典:
            - {"type": "content_delta", "delta": "文本片段"}
            - {"type": "tool_call", "tool_call": {...}}
            - {"type": "usage", "usage": {...}}
        """
        url = f"{self.base_url}/v1/chat/completions"

        # 构建请求体
        request_body = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream
        }

        # 添加系统提示词
        if system:
            request_body["messages"] = [
                {"role": "system", "content": system}
            ] + messages

        # 添加工具定义
        if tools:
            request_body["tools"] = tools

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        tool_calls_buffer = {}  # 缓存工具调用

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST",
                url,
                headers=headers,
                json=request_body
            ) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    raise Exception(f"API 错误 ({response.status_code}): {error_text.decode()}")

                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue

                    data_str = line[6:]  # 去掉 "data: " 前缀

                    if data_str == "[DONE]":
                        break

                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    choices = data.get("choices", [])
                    if not choices:
                        continue

                    choice = choices[0]
                    delta = choice.get("delta", {})
                    finish_reason = choice.get("finish_reason")

                    # 处理文本内容
                    if "content" in delta and delta["content"]:
                        yield {
                            "type": "content_delta",
                            "delta": delta["content"]
                        }

                    # 处理工具调用
                    if "tool_calls" in delta:
                        for tc_delta in delta["tool_calls"]:
                            index = tc_delta.get("index", 0)

                            # 初始化或更新工具调用缓冲区
                            if index not in tool_calls_buffer:
                                tool_calls_buffer[index] = {
                                    "id": "",
                                    "type": "function",
                                    "function": {
                                        "name": "",
                                        "arguments": ""
                                    }
                                }

                            # 更新 ID
                            if tc_delta.get("id"):
                                tool_calls_buffer[index]["id"] = tc_delta["id"]

                            # 更新函数名和参数
                            if "function" in tc_delta:
                                func_delta = tc_delta["function"]
                                if func_delta.get("name"):
                                    tool_calls_buffer[index]["function"]["name"] = func_delta["name"]
                                if func_delta.get("arguments"):
                                    tool_calls_buffer[index]["function"]["arguments"] += func_delta["arguments"]

                    # 工具调用完成
                    if finish_reason == "tool_calls":
                        for tc in tool_calls_buffer.values():
                            yield {
                                "type": "tool_call",
                                "tool_call": tc
                            }
                        tool_calls_buffer = {}

                    # 输出 usage (如果有)
                    if "usage" in data:
                        yield {
                            "type": "usage",
                            "usage": data["usage"]
                        }

    async def chat_completion(
        self,
        model: str,
        messages: List[Dict],
        system: str = None,
        tools: List[Dict] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096
    ) -> Dict:
        """
        非流式调用 DeepSeek Chat API

        Returns:
            完整响应
        """
        url = f"{self.base_url}/v1/chat/completions"

        request_body = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False
        }

        if system:
            request_body["messages"] = [
                {"role": "system", "content": system}
            ] + messages

        if tools:
            request_body["tools"] = tools

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, headers=headers, json=request_body)

            if response.status_code != 200:
                raise Exception(f"API 错误 ({response.status_code}): {response.text}")

            return response.json()
