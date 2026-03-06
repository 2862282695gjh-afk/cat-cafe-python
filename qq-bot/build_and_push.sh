#!/bin/bash
# 一键编译 APK 并推送到 QQ
# 使用方法: ./build_and_push.sh [TARGET_QQ]

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ANDROID_DIR="$PROJECT_ROOT/android-app/FitTrack"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🐱 FitTrack APK 一键编译推送工具${NC}"
echo "=========================================="

# 检查目标 QQ
if [ -n "$1" ]; then
    export TARGET_QQ="$1"
fi

if [ -z "$TARGET_QQ" ]; then
    echo -e "${RED}❌ 请提供目标 QQ 号${NC}"
    echo "用法: $0 <QQ号>"
    echo "或设置环境变量: export TARGET_QQ=123456789"
    exit 1
fi

echo -e "${GREEN}📱 目标 QQ: $TARGET_QQ${NC}"
echo ""

# 步骤 1: 编译 APK
echo -e "${YELLOW}📦 步骤 1/2: 编译 APK...${NC}"
cd "$ANDROID_DIR"
./gradlew assembleDebug
echo -e "${GREEN}✅ APK 编译完成${NC}"
echo ""

# 步骤 2: 推送到 QQ
echo -e "${YELLOW}📤 步骤 2/2: 推送到 QQ...${NC}"
cd "$SCRIPT_DIR"
python3 push_apk.py

echo ""
echo -e "${GREEN}🎉 全部完成！${NC}"
echo -e "📱 请检查 QQ 是否收到 APK 文件"
