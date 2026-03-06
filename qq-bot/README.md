# QQ 机器人 APK 推送工具

这个工具可以在 APK 编译完成后自动推送到你的 QQ。

## 架构说明

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  编译脚本   │ ──▶ │  push_apk   │ ──▶ │   NapCat    │
│  (gradlew)  │     │  (Python)   │     │  (OneBot)   │
└─────────────┘     └─────────────┘     └─────────────┘
                                               │
                                               ▼
                                        ┌─────────────┐
                                        │   你的 QQ   │
                                        └─────────────┘
```

## 第一步：安装 NapCat

NapCat 是基于 NTQQ 的 OneBot 11 协议实现，支持发送文件。

### macOS 安装方法

1. **下载 NapCat**
   ```bash
   # 创建目录
   mkdir -p ~/napcat && cd ~/napcat

   # 下载最新版本（访问 https://github.com/NapNeko/NapCatQQ/releases 查看最新版本）
   # macOS 使用 napcat.mac.zip
   curl -L -o napcat.zip https://github.com/NapNeko/NapCatQQ/releases/latest/download/napcat.mac.zip
   unzip napcat.zip
   ```

2. **安装 QQ NT**
   - 从 App Store 或腾讯官网安装 QQ NT 版本

3. **启动 NapCat**
   ```bash
   cd ~/napcat
   ./napcat
   ```

4. **登录 QQ**
   - 首次启动会弹出 QQ 登录窗口
   - 扫码或输入账号密码登录
   - 登录成功后，NapCat 会在后台运行

### 配置 NapCat

编辑 `~/napcat/config/onebot11.json`：

```json
{
  "http": {
    "enable": true,
    "host": "0.0.0.0",
    "port": 3000,
    "secret": "",
    "enableHeart": false,
    "enablePost": false
  },
  "ws": {
    "enable": false
  },
  "reverseWs": {
    "enable": false
  },
  "debug": false,
  "heartInterval": 30000,
  "messagePostFormat": "array",
  "enableLocalFile2Url": true,
  "musicSignUrl": "",
  "reportSelfMessage": false,
  "token": ""
}
```

**重要**: 确保 `"enableLocalFile2Url": true`，这样才能发送本地文件！

## 第二步：安装 Python 依赖

```bash
cd qq-bot
pip3 install httpx
```

## 第三步：配置推送脚本

编辑 `push_apk.py`，修改以下配置：

```python
# 你的 QQ 号
TARGET_QQ = "123456789"  # 改成你的 QQ 号

# NapCat API 地址（默认即可）
ONEBOT_API_URL = "http://127.0.0.1:3000"
```

或者使用环境变量：

```bash
export TARGET_QQ=123456789
export ONEBOT_API_URL=http://127.0.0.1:3000
```

## 第四步：测试

### 测试 NapCat 是否正常

```bash
# 检查 NapCat 是否在运行
curl http://127.0.0.1:3000/get_login_info
```

如果返回类似 `{"data":{"user_id":123456789,"nickname":"xxx"}}`，说明正常。

### 测试推送 APK

```bash
cd qq-bot
python3 push_apk.py
```

## 使用方法

### 方式一：先编译再推送

```bash
# 1. 编译 APK
cd android-app/FitTrack
./gradlew assembleDebug

# 2. 推送到 QQ
cd ../../qq-bot
python3 push_apk.py
```

### 方式二：一键编译+推送

```bash
cd qq-bot
./build_and_push.sh 你的QQ号
```

## 常见问题

### Q: NapCat 启动失败
A: 确保已安装 QQ NT 版本，并且 QQ 没有在运行（NapCat 会自动启动 QQ）

### Q: 发送文件失败
A: 检查配置文件中 `"enableLocalFile2Url": true` 是否已设置

### Q: 收不到消息
A:
1. 检查 NapCat 是否登录成功
2. 检查 TARGET_QQ 是否正确
3. 检查 ONEBOT_API_URL 是否正确

### Q: 想发送到群怎么办？
A: 修改 `push_apk.py`，使用 `send_group_file` 函数并传入群号

## 文件说明

| 文件 | 说明 |
|------|------|
| `push_apk.py` | APK 推送脚本 |
| `build_and_push.sh` | 一键编译+推送脚本 |
| `README.md` | 本说明文档 |
