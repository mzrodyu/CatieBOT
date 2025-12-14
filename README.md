# 🐱 CatieBOT

一个基于 Discord 的智能问答机器人系统，支持多BOT管理、知识库、用户记忆等功能。

## ✨ 功能特性

- 🤖 **多BOT管理** - 支持创建和管理多个独立的BOT角色
- 📚 **知识库系统** - 自定义知识库，支持向量搜索和关键词搜索
- 🧠 **用户记忆** - 记住与用户的对话内容，提供个性化回复
- 📌 **标注消息读取** - 自动读取频道标注消息作为答疑参考
- 🎨 **表情包支持** - 识别并使用服务器自定义表情
- 📊 **统计面板** - 查看使用统计和对话记录
- 🌐 **Web后台** - 现代化的管理界面

## 🚀 快速开始

### 环境要求

- Python 3.9+
- SQLite3
- Discord Bot Token
- OpenAI API Key（或兼容的API）

### 安装

```bash
# 克隆仓库
git clone https://github.com/mzrodyu/CatieBOT.git
cd CatieBOT

# 安装依赖
pip install -r requirements.txt
```

### 配置

1. 复制环境变量模板：
```bash
cp .env.example .env
```

2. 编辑 `.env` 文件，填入你的配置：
```env
DISCORD_BOT_TOKEN=你的Discord Bot Token
OPENAI_API_KEY=你的OpenAI API Key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini
```

### 运行

```bash
# 启动后端
cd backend
python main.py

# 启动Bot（新终端）
cd bot
python main.py
```

后台管理面板: `http://localhost:6001/admin/bots`

## 📁 项目结构

```
CatieBOT/
├── backend/           # 后端API服务
│   ├── main.py       # 主程序
│   ├── templates/    # HTML模板
│   └── static/       # 静态资源
├── bot/              # Discord Bot
│   └── main.py       # Bot主程序
├── requirements.txt  # Python依赖
└── README.md
```

## 🛠️ 技术栈

- **后端**: FastAPI, SQLite, Jinja2
- **Bot**: discord.py
- **AI**: OpenAI API (兼容其他API)
- **向量搜索**: ChromaDB (可选)

## 📝 使用说明

### 后台管理

1. 访问 `http://your-server:6001/admin/bots`
2. 创建新的BOT角色，设置名称和系统提示
3. 在知识库中添加常见问题和答案
4. 查看用户记忆和统计数据

### Discord使用

- 直接 @机器人 或回复机器人消息即可对话
- 机器人会自动读取频道标注消息作为参考
- 支持发送图片进行识图

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 开源协议

MIT License - 详见 [LICENSE](LICENSE)

## 👤 开发者

**Catie猫猫** - [@mzrodyu](https://github.com/mzrodyu)

---

⭐ 如果这个项目对你有帮助，请给个 Star！
