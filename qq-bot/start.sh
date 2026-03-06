#!/bin/bash
# 启动QQ机器人（同时启动Webhook服务器和测试连接）

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🐱 启动猫咪咖啡馆 QQ 机器人${NC}"
echo "=========================================="

# 检查Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Python3 未安装${NC}"
    exit 1
fi

# 检查依赖
echo -e "${YELLOW}📦 检查依赖...${NC}"

cd "$SCRIPT_DIR"
if ! python3 -c "import httpx" 2>/dev/null; then
    echo "安装 httpx..."
    pip3 install httpx
fi

if ! python3 -c "import flask" 2>/dev/null; then
    echo "安装 flask..."
    pip3 install flask
fi

# 测试连接
echo ""
echo -e "${YELLOW}🔗 测试 NapCat 连接...${NC}"
python3 cat_cafe_bot.py
echo ""

# 检查是否成功
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ NapCat 连接成功！${NC}"
    echo ""
    echo -e "${YELLOW}🚀 启动 Webhook 服务器...${NC}"
    echo "按 Ctrl+C 停止"
    echo ""
    python3 webhook_server.py
else
    echo -e "${RED}❌ 连接失败，请检查 NapCat 是否正在运行${NC}"
    exit 1
fi
