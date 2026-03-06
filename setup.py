#!/usr/bin/env python3
"""
Cat Café Python Setup
"""
from setuptools import setup, find_packages

setup(
    name="cat-cafe-python",
    version="1.0.0",
    description="猫咪咖啡馆 - 多 Agent AI 聊天系统",
    author="Cat Café Team",
    packages=find_packages(),
    python_requires=">=3.8",
    install_requires=[
        "flask>=2.0.0",
        "flask-socketio>=5.0.0",
        "flask-cors>=3.0.0",
        "python-dotenv>=0.19.0",
        "redis>=4.0.0",
        "httpx>=0.23.0",
        "aiohttp>=3.8.0",
    ],
    extras_require={
        "security": [
            "psutil>=5.8.0",
        ]
    },
    entry_points={
        "console_scripts": [
            "cat-cafe=run:main",
            "deepseek-cli=deepseek_cli.cli:cli_entry",
        ]
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
)
