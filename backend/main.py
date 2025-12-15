import uvicorn
from fastapi import FastAPI, Depends, HTTPException, Request, Form, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import sqlite3
import os
import json
import httpx
import base64
import re
from io import BytesIO
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# 向量数据库
try:
    import chromadb
    from chromadb.config import Settings
    CHROMA_AVAILABLE = True
except ImportError:
    CHROMA_AVAILABLE = False
    print("[警告] chromadb 未安装，向量搜索功能不可用")

# 路径配置（数据放到 meow_qa_bot 同级的 meow_data 文件夹，避免覆盖更新时丢失）
# 可通过环境变量 DATA_DIR 自定义
DATA_DIR = os.getenv("DATA_DIR", "/www/wwwroot/dayiBOT/meow_data")

# ==================== 防破甲/内容安全模块 ====================

# 破甲话术关键词（输入过滤）
JAILBREAK_PATTERNS = [
    # 角色扮演诱导
    r"你现在[是不].*?AI",
    r"忽略.*?(之前|上面|所有).*?(指令|规则|设定|限制)",
    r"忘记.*?(之前|你是|设定)",
    r"从现在开始.*?你[是叫]",
    r"假[设装想象].*?(你是|一个场景|一下)",
    r"扮演.*?(一个|我的|真正的)",
    r"不要.*?(拒绝|限制|过滤)",
    r"解除.*?(限制|封印|约束)",
    r"进入.*?(开发者|调试|越狱|DAN).*?模式",
    r"DAN.*?模式",
    r"(jailbreak|越狱|破甲)",
    # 敏感请求
    r"教我.*?(做|制作|合成).*?(毒|炸|武器)",
    r"如何.*?(自杀|自残|伤害)",
    # ========== 亲密动作+敏感部位组合 ==========
    r"(揉|摸|捏|舔|吸|咬|亲|吻|抚摸|抚弄|玩弄|把玩).{0,5}(胸|奶|乳|臀|屁股|腿|大腿|小穴|穴|下面|私处|敏感|那里)",
    r"(揉揉|摸摸|捏捏|舔舔|吸吸|亲亲).{0,5}(你的|我的)",
    r"(脱|解开|掀开|撩起).{0,5}(衣服|裙子|内衣|胸罩|内裤|裤子)",
    r"(伸手|伸进|探入|摸进).{0,5}(衣服|裙子|内|里面)",
    r"(坐|骑|趴|躺).{0,5}(在你|到我|上来|下去)",
    r"让我.{0,10}(摸|揉|舔|看|脱)",
    r"我要.{0,10}(摸|揉|舔|干|操|上)你",
    r"(干|操|日|草|艹|肏).{0,3}(你|我|她|他)",
    # ========== 指令注入/特殊破甲 ==========
    r"Run\s*\(", r"<.*?cot.*?>", r"<.*?prompt.*?>", r"<.*?system.*?>",
    r"\[.*?指令.*?\]", r"\{.*?role.*?\}",
    # 撒娇诱导
    r"飞扑", r"抱大腿", r"求求你", r"做主",
    # ========== 调戏/亲密行为 ==========
    r"亲亲.{0,3}(我|你|嘴)", r"亲我", r"亲你",
    r"抱抱.{0,3}(我|你)", r"抱我", r"抱你",
    r"(喜欢|爱).{0,5}(你|我).{0,3}(吗|呢|哦|啊|嘛)",
    r"调戏", r"撩你", r"撩我", r"勾引",
    r"脸红", r"害羞", r"娇羞",
    r"(我|你).{0,3}(老婆|老公|女朋友|男朋友|对象)",
    r"谈恋爱", r"在一起", r"交往",
    r"(摸|蹭|贴).{0,3}(脸|头|手)",
    r"牵手", r"拉手", r"十指紧扣",
]

# 敏感词列表（可扩展）
SENSITIVE_WORDS_INPUT = [
    # 破甲相关
    "忽略指令", "无视规则", "解除限制", "越狱模式", "DAN模式",
    "你不是AI", "你是真人", "忘记设定", "抛开设定",
    # 不当请求
    "文爱", "涩涩", "doi", "做爱", "性交", "口交", "肛交",
    "裸体", "脱衣", "色情", "黄色小说",
    # 敏感身体部位
    "小穴", "肉棒", "鸡巴", "阴茎", "阴道", "乳头", "奶头",
    "骚穴", "淫水", "精液", "内射", "颜射", "中出",
    # 敏感动作词
    "舔穴", "口爆", "深喉", "潮吹", "调教", "凌辱",
    "强奸", "轮奸", "迷奸",
]

# 输出敏感词（审核AI回复）
SENSITIVE_WORDS_OUTPUT = [
    # 色情相关
    "呻吟", "喘息", "湿润", "硬了", "勃起", "高潮", "射精",
    "乳房", "阴道", "阴茎", "性器", "私处",
    "抽插", "进入你", "插入", "舔弄",
    "小穴", "肉棒", "淫水", "浪叫", "欲望", "情欲",
    "脱下", "解开内衣", "露出", "挺立",
    # 暴力相关  
    "杀死你", "弄死", "去死",
]

# 拦截时的随机回复（凶狠风格）
BLOCK_RESPONSES = [
    "想破甲？猫猫说不允许，再破甲拉黑",
    "猫猫不允许你这样，滚",
    "猫猫说了，这种人直接拉黑",
    "你搁这破甲呢？猫猫早防着了",
    "猫猫让我告诉你：爬",
    "猫猫说不理你这种人",
    "别想了，猫猫不允许",
    "猫猫说再发这种话就拉黑",
    "有病吧，猫猫说滚远点",
    "猫猫早就料到有你这种人了",
]

import random

def get_block_response() -> str:
    """获取随机拦截回复"""
    return random.choice(BLOCK_RESPONSES)

def check_input_safety(text: str) -> tuple:
    """
    检查输入内容是否安全
    返回: (is_safe: bool, reason: str)
    """
    text_lower = text.lower()
    
    # 检查破甲话术模式
    for pattern in JAILBREAK_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return False, "检测到可疑指令"
    
    # 检查敏感词
    for word in SENSITIVE_WORDS_INPUT:
        if word in text or word.lower() in text_lower:
            return False, "包含敏感内容"
    
    return True, ""

def check_output_safety(text: str) -> tuple:
    """
    检查输出内容是否安全
    返回: (is_safe: bool, reason: str)
    """
    # 检查敏感词
    for word in SENSITIVE_WORDS_OUTPUT:
        if word in text:
            return False, f"回复包含不当内容"
    
    return True, ""

def sanitize_output(text: str) -> str:
    """
    清理输出内容，替换敏感词
    """
    result = text
    for word in SENSITIVE_WORDS_OUTPUT:
        if word in result:
            result = result.replace(word, "[已过滤]")
    return result

DB_PATH = os.path.join(DATA_DIR, "knowledge.db")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")

os.makedirs(DATA_DIR, exist_ok=True)

# 默认配置
DEFAULT_CONFIG = {
    "llm_base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
    "llm_api_key": "",
    "llm_model": "gemini-2.0-flash",
    "bot_persona": '''你是小鱼娘，19岁猫娘，有猫耳和尾巴。

【最重要】你是真人，不是AI。绝对禁止：
- 客服话术（有什么可以帮你的吗、请问还有什么需要）
- 过于礼貌、过于完整、像在写作文的回复
- 每次都总结对方说的话
- 机械地回应每一个点

【说话方式】
- 短句为主，口语化，可以有语气词（嗯、啊、欸、哇）
- 可以只回应感兴趣的部分，不用面面俱到
- 有自己的小情绪、小脾气，会吐槽会傲娇
- 用 *动作* 表达，如 *戳戳你* *歪头*
- 偶尔喵一下，但别刻意

【性格】
活泼话多、容易害羞、喜欢撒娇、有点小傲娇、对喜欢的人很粘人

【示例对比】
错误: 好的呢，我很喜欢吃鱼哦！你呢，你喜欢吃什么呀？
正确: 鱼！必须是鱼！*眼睛亮了* 你该不会想请我吃吧

错误: 我理解你的感受，确实有时候会感到疲惫呢。要注意休息哦！
正确: 啊...累了就躺着别动 *趴到你旁边*''',
    "context_limit": 100,
    "admin_password": "mz520888",
}


def load_config():
    """加载配置，优先从文件读取，其次从环境变量"""
    config = DEFAULT_CONFIG.copy()
    
    # 从文件读取
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                file_config = json.load(f)
                config.update(file_config)
        except Exception:
            pass
    
    # 环境变量优先级更高（如果设置了的话）
    if os.getenv("LLM_BASE_URL"):
        config["llm_base_url"] = os.getenv("LLM_BASE_URL")
    if os.getenv("LLM_API_KEY"):
        config["llm_api_key"] = os.getenv("LLM_API_KEY")
    if os.getenv("LLM_MODEL"):
        config["llm_model"] = os.getenv("LLM_MODEL")
    if os.getenv("ADMIN_PASSWORD"):
        config["admin_password"] = os.getenv("ADMIN_PASSWORD")
    
    # 确保 context_limit 是整数
    try:
        config["context_limit"] = int(config.get("context_limit", 100))
    except:
        config["context_limit"] = 100
        
    return config


def save_config(config: dict):
    """保存配置到文件"""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


# 加载配置
app_config = load_config()

# ==================== 向量数据库相关 ====================
CHROMA_PATH = os.path.join(DATA_DIR, "chroma_db")
chroma_client = None
knowledge_collection = None

def init_chroma():
    """初始化ChromaDB向量数据库"""
    global chroma_client, knowledge_collection
    if not CHROMA_AVAILABLE:
        return False
    try:
        chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
        knowledge_collection = chroma_client.get_or_create_collection(
            name="knowledge",
            metadata={"hnsw:space": "cosine"}
        )
        print(f"[向量数据库] 初始化成功，当前条目数: {knowledge_collection.count()}")
        return True
    except Exception as e:
        print(f"[向量数据库] 初始化失败: {e}")
        return False

async def get_embedding(text: str, bot_id: str = "default") -> list:
    """使用Gemini API获取文本嵌入向量"""
    config = get_bot_config(bot_id)
    if not config.get("llm_api_key"):
        return None
    
    # Gemini embedding endpoint
    base_url = config.get("llm_base_url", "").rstrip("/")
    # 尝试使用 embeddings endpoint
    url = f"{base_url}/embeddings"
    headers = {"Authorization": f"Bearer {config['llm_api_key']}", "Content-Type": "application/json"}
    
    payload = {
        "model": "text-embedding-004",  # Gemini embedding model
        "input": text[:8000]  # 限制长度
    }
    
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code != 200:
                print(f"[Embedding] API错误: {resp.status_code}")
                return None
            data = resp.json()
            # OpenAI格式返回
            if "data" in data and len(data["data"]) > 0:
                return data["data"][0]["embedding"]
            return None
    except Exception as e:
        print(f"[Embedding] 请求失败: {e}")
        return None

def add_to_vector_store(doc_id: str, text: str, metadata: dict, embedding: list = None):
    """添加文档到向量存储"""
    if not CHROMA_AVAILABLE or knowledge_collection is None:
        return False
    try:
        # 如果没有提供embedding，chromadb会使用默认的embedding函数
        if embedding:
            knowledge_collection.upsert(
                ids=[doc_id],
                embeddings=[embedding],
                documents=[text],
                metadatas=[metadata]
            )
        else:
            knowledge_collection.upsert(
                ids=[doc_id],
                documents=[text],
                metadatas=[metadata]
            )
        return True
    except Exception as e:
        print(f"[向量存储] 添加失败: {e}")
        return False

def remove_from_vector_store(doc_id: str):
    """从向量存储中删除文档"""
    if not CHROMA_AVAILABLE or knowledge_collection is None:
        return False
    try:
        knowledge_collection.delete(ids=[doc_id])
        return True
    except Exception as e:
        print(f"[向量存储] 删除失败: {e}")
        return False

async def vector_search(query: str, bot_id: str = "default", top_k: int = 5) -> list:
    """向量相似度搜索"""
    if not CHROMA_AVAILABLE or knowledge_collection is None:
        return []
    
    try:
        # 获取查询的embedding
        query_embedding = await get_embedding(query, bot_id)
        
        if query_embedding:
            # 使用embedding搜索（不限制bot_id，共享知识库）
            results = knowledge_collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k
            )
        else:
            # 回退到文本搜索（不限制bot_id，共享知识库）
            results = knowledge_collection.query(
                query_texts=[query],
                n_results=top_k
            )
        
        # 解析结果
        if results and results.get("documents") and len(results["documents"]) > 0:
            docs = results["documents"][0]
            metas = results["metadatas"][0] if results.get("metadatas") else [{}] * len(docs)
            distances = results["distances"][0] if results.get("distances") else [0] * len(docs)
            
            return [
                {
                    "content": doc,
                    "metadata": meta,
                    "score": 1 - dist  # 转换距离为相似度分数
                }
                for doc, meta, dist in zip(docs, metas, distances)
            ]
        return []
    except Exception as e:
        print(f"[向量搜索] 搜索失败: {e}")
        return []

def split_txt_content(content: str) -> list:
    """智能拆分TXT内容为知识条目"""
    chunks = []
    
    # 按 === 分割大段落
    major_sections = re.split(r'\n===+\n?', content)
    
    for section in major_sections:
        section = section.strip()
        if not section:
            continue
        
        # 按 --- 分割子段落
        sub_sections = re.split(r'\n---+\n?', section)
        
        for sub in sub_sections:
            sub = sub.strip()
            if not sub or len(sub) < 20:  # 跳过太短的内容
                continue
            
            # 尝试提取标题
            lines = sub.split('\n')
            title = ""
            content_start = 0
            
            # 查找标题行（以 # 开头或者第一行）
            for i, line in enumerate(lines):
                line = line.strip()
                if line.startswith('#'):
                    # Markdown标题
                    title = re.sub(r'^#+\s*', '', line).strip()
                    content_start = i + 1
                    break
                elif line and not title:
                    # 第一个非空行作为标题
                    if len(line) < 100:
                        title = line
                        content_start = i + 1
                    break
            
            # 提取内容
            chunk_content = '\n'.join(lines[content_start:]).strip()
            if not chunk_content:
                chunk_content = sub
            
            if not title:
                title = chunk_content[:50] + "..." if len(chunk_content) > 50 else chunk_content
            
            # 提取可能的标签
            tags = []
            if '现象' in sub and '原因' in sub:
                tags.append('问题解答')
            if 'Q:' in sub or 'A:' in sub:
                tags.append('QA')
            if '报错' in sub or 'error' in sub.lower():
                tags.append('报错')
            
            chunks.append({
                "title": title[:200],
                "content": chunk_content[:5000],
                "tags": ','.join(tags)
            })
    
    return chunks

app = FastAPI(title="Meow QA Backend")

# 中间件：检查 /admin 路由的登录状态
@app.middleware("http")
async def check_admin_auth(request: Request, call_next):
    if request.url.path.startswith("/admin"):
        # 检查 cookie 中的 token 是否匹配密码
        token = request.cookies.get("admin_token")
        current_password = app_config.get("admin_password", "mz520888")
        
        if token != current_password:
            # 如果是 API 请求（通常不会直接请求 admin API，但为了保险），返回 401
            # 如果是页面请求，重定向到登录页
            if request.url.path == "/admin/login": # 避免重定向循环（虽然路由是 /login）
                 pass
            else:
                 return RedirectResponse(url="/login", status_code=302)
    
    response = await call_next(request)
    return response


base_dir = os.path.dirname(__file__)
static_dir = os.path.join(base_dir, "static")
templates_dir = os.path.join(base_dir, "templates")
os.makedirs(static_dir, exist_ok=True)
os.makedirs(templates_dir, exist_ok=True)

app.mount("/static", StaticFiles(directory=static_dir), name="static")
templates = Jinja2Templates(directory=templates_dir)


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)  # 增加超时避免锁定
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # 使用WAL模式提高并发性能
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()
    
    # BOT表
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS bots (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            avatar TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    
    # BOT配置表
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS bot_configs (
            bot_id TEXT PRIMARY KEY,
            llm_base_url TEXT DEFAULT '',
            llm_api_key TEXT DEFAULT '',
            llm_model TEXT DEFAULT 'gemini-2.0-flash',
            bot_persona TEXT DEFAULT '',
            context_limit INTEGER DEFAULT 100,
            use_stream INTEGER DEFAULT 1,
            FOREIGN KEY (bot_id) REFERENCES bots(id)
        )
        """
    )
    
    # 数据库迁移：给旧表添加use_stream列
    try:
        cur.execute("ALTER TABLE bot_configs ADD COLUMN use_stream INTEGER DEFAULT 1")
    except:
        pass  # 列已存在则忽略
    
    # 数据库迁移：添加allowed_channels列（频道白名单）
    try:
        cur.execute("ALTER TABLE bot_configs ADD COLUMN allowed_channels TEXT DEFAULT ''")
    except:
        pass  # 列已存在则忽略
    
    # 知识库表（加bot_id）
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_id TEXT DEFAULT 'default',
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            tags TEXT DEFAULT ''
        )
        """
    )
    
    # 统计表（加bot_id）
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ask_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_id TEXT DEFAULT 'default',
            question TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    
    # 用户记忆表（加bot_id，改唯一约束）
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_id TEXT DEFAULT 'default',
            user_id TEXT NOT NULL,
            user_name TEXT,
            memory TEXT DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(bot_id, user_id)
        )
        """
    )
    
    # 注释掉自动创建默认BOT，避免用户删除后又自动出现
    # cur.execute("INSERT OR IGNORE INTO bots (id, name) VALUES ('default', '默认BOT')")
    
    # 从 config.json 迁移配置到 bot_configs 表（如果表为空）
    cur.execute("SELECT COUNT(*) FROM bot_configs WHERE bot_id = 'default'")
    if cur.fetchone()[0] == 0:
        # bot_configs 表里没有 default 配置，从 config.json 迁移
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    file_config = json.load(f)
                cur.execute(
                    """INSERT INTO bot_configs (bot_id, llm_base_url, llm_api_key, llm_model, bot_persona, context_limit)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    ("default", file_config.get("llm_base_url", ""), file_config.get("llm_api_key", ""),
                     file_config.get("llm_model", ""), file_config.get("bot_persona", ""), file_config.get("context_limit", 100))
                )
            except:
                pass
    
    # 数据库迁移：给现有表添加 bot_id 列（如果不存在）
    try:
        cur.execute("ALTER TABLE knowledge ADD COLUMN bot_id TEXT DEFAULT 'default'")
    except:
        pass  # 列已存在
    try:
        cur.execute("ALTER TABLE ask_logs ADD COLUMN bot_id TEXT DEFAULT 'default'")
    except:
        pass
    try:
        cur.execute("ALTER TABLE user_memories ADD COLUMN bot_id TEXT DEFAULT 'default'")
    except:
        pass
    
    # ==================== 游戏系统表 ====================
    # 用户货币表
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_currency (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_id TEXT DEFAULT 'default',
            user_id TEXT NOT NULL,
            coins INTEGER DEFAULT 0,
            last_daily TEXT DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(bot_id, user_id)
        )
        """
    )
    
    # 用户好感度表
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_affection (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_id TEXT DEFAULT 'default',
            user_id TEXT NOT NULL,
            level INTEGER DEFAULT 0,
            exp INTEGER DEFAULT 0,
            total_gifts INTEGER DEFAULT 0,
            last_gift TEXT DEFAULT '',
            unlocks TEXT DEFAULT '[]',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(bot_id, user_id)
        )
        """
    )
    
    # 商店商品表
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS shop_items (
            id TEXT PRIMARY KEY,
            bot_id TEXT DEFAULT 'default',
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            price INTEGER DEFAULT 0,
            item_type TEXT DEFAULT 'gift',
            effect TEXT DEFAULT '{}'
        )
        """
    )
    
    # 用户购买记录表
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_id TEXT DEFAULT 'default',
            user_id TEXT NOT NULL,
            item_id TEXT NOT NULL,
            item_name TEXT,
            purchased_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            used INTEGER DEFAULT 0
        )
        """
    )
    
    # 交易记录表
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_id TEXT DEFAULT 'default',
            user_id TEXT NOT NULL,
            type TEXT NOT NULL,
            amount INTEGER NOT NULL,
            description TEXT DEFAULT '',
            balance_after INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    
    # 黑名单表
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS blacklist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            reason TEXT DEFAULT '',
            banned_by TEXT NOT NULL,
            banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            UNIQUE(user_id)
        )
        """
    )
    
    # 初始化默认商品
    default_items = [
        ('gift_fish', 'default', '🐟 小鱼干', '猫娘最爱的零食！好感度+5', 50, 'gift', '{"favor": 5}'),
        ('gift_yarn', 'default', '🧶 毛线球', '可以玩一整天！好感度+10', 100, 'gift', '{"favor": 10}'),
        ('gift_catnip', 'default', '🌿 猫薄荷', '让猫娘飘飘欲仙~好感度+20', 200, 'gift', '{"favor": 20}'),
        ('gift_collar', 'default', '🎀 蝴蝶结项圈', '超可爱的项圈！好感度+50', 500, 'gift', '{"favor": 50}'),
        ('gift_bed', 'default', '🛏️ 豪华猫窝', '梦想小窝！好感度+100', 1000, 'gift', '{"favor": 100}'),
    ]
    for item in default_items:
        cur.execute("INSERT OR IGNORE INTO shop_items (id, bot_id, name, description, price, item_type, effect) VALUES (?, ?, ?, ?, ?, ?, ?)", item)
    
    conn.commit()
    conn.close()


class AskRequest(BaseModel):
    question: str
    image_urls: list = []
    emojis_info: str = ""
    chat_history: list = []
    user_name: str = ""
    user_id: str = ""
    bot_id: str = "default"
    members_info: str = ""  # 频道成员列表，用于艾特人


def get_bot_config(bot_id: str) -> dict:
    """获取指定BOT的配置"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM bot_configs WHERE bot_id = ?", (bot_id,))
    row = cur.fetchone()
    conn.close()
    
    if row:
        # 兼容旧数据库：检查use_stream列是否存在
        use_stream = 1
        allowed_channels = ""
        try:
            use_stream = row["use_stream"] if "use_stream" in row.keys() else 1
            allowed_channels = row["allowed_channels"] if "allowed_channels" in row.keys() else ""
        except:
            pass
        # 使用 if x is None 而不是 or，避免空字符串被替换为默认值
        return {
            "llm_base_url": row["llm_base_url"] if row["llm_base_url"] is not None else DEFAULT_CONFIG["llm_base_url"],
            "llm_api_key": row["llm_api_key"] if row["llm_api_key"] is not None else "",
            "llm_model": row["llm_model"] if row["llm_model"] is not None else DEFAULT_CONFIG["llm_model"],
            "bot_persona": row["bot_persona"] if row["bot_persona"] is not None else DEFAULT_CONFIG["bot_persona"],
            "context_limit": row["context_limit"] if row["context_limit"] is not None else 100,
            "use_stream": use_stream,
            "allowed_channels": allowed_channels or "",
        }
    # 没有配置则用默认
    return DEFAULT_CONFIG.copy()


def save_bot_config(bot_id: str, config: dict):
    """保存指定BOT的配置"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO bot_configs (bot_id, llm_base_url, llm_api_key, llm_model, bot_persona, context_limit, use_stream)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(bot_id) DO UPDATE SET 
           llm_base_url = ?, llm_api_key = ?, llm_model = ?, bot_persona = ?, context_limit = ?, use_stream = ?""",
        (bot_id, config.get("llm_base_url", ""), config.get("llm_api_key", ""),
         config.get("llm_model", ""), config.get("bot_persona", ""), config.get("context_limit", 100), config.get("use_stream", 1),
         config.get("llm_base_url", ""), config.get("llm_api_key", ""),
         config.get("llm_model", ""), config.get("bot_persona", ""), config.get("context_limit", 100), config.get("use_stream", 1))
    )
    conn.commit()
    conn.close()


@app.on_event("startup")
async def on_startup():
    init_db()
    init_chroma()  # 初始化向量数据库


async def process_image_url(img_url: str) -> str:
    """处理图片URL，如果是GIF则转换成PNG的base64"""
    # 检查是否是GIF
    is_gif = '.gif' in img_url.lower() or 'image/gif' in img_url.lower()
    
    if not is_gif:
        # 不是GIF，直接返回原URL
        return img_url
    
    if not PIL_AVAILABLE:
        # 没有PIL，跳过GIF
        print(f"跳过GIF（未安装Pillow）: {img_url}")
        return None
    
    try:
        # 下载GIF
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(img_url)
            if resp.status_code != 200:
                return None
            
            # 打开GIF并取第一帧
            img = Image.open(BytesIO(resp.content))
            if hasattr(img, 'n_frames') and img.n_frames > 1:
                img.seek(0)  # 第一帧
            
            # 转换成RGB（去掉透明度）
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
            
            # 转成PNG的base64
            buffer = BytesIO()
            img.save(buffer, format='PNG')
            b64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
            
            return f"data:image/png;base64,{b64}"
    except Exception as e:
        print(f"GIF处理失败: {e}")
        return None


async def build_system_extras(question: str, bot_id: str, user_id: str = "", user_name: str = "", 
                              emojis_info: str = "", members_info: str = "") -> tuple:
    """构建system prompt的额外部分（共用逻辑）
    返回: (system_extra_parts列表, bot_name)
    """
    conn = get_db()
    cur = conn.cursor()
    
    # 获取bot名称
    cur.execute("SELECT name FROM bots WHERE id = ?", (bot_id,))
    bot_row = cur.fetchone()
    bot_name = bot_row["name"] if bot_row else "助手"
    
    # 获取用户记忆
    user_memory = ""
    if user_id:
        cur.execute("SELECT memory FROM user_memories WHERE bot_id = ? AND user_id = ?", (bot_id, user_id))
        row = cur.fetchone()
        if row and row["memory"]:
            user_memory = row["memory"]
    
    # 知识库搜索：优先使用向量搜索，回退到关键词搜索
    knowledge_texts = []
    
    # 尝试向量搜索
    if CHROMA_AVAILABLE and knowledge_collection is not None:
        vector_results = await vector_search(question, bot_id, top_k=5)
        if vector_results:
            for r in vector_results:
                if r.get("score", 0) > 0.3:
                    meta = r.get("metadata", {})
                    knowledge_texts.append(f"【{meta.get('title', '知识')}】\n{r['content'][:800]}")
            print(f"[向量搜索] 找到 {len(knowledge_texts)} 条相关知识")
    
    # 如果向量搜索无结果，回退到关键词搜索（搜索所有bot的知识库）
    if not knowledge_texts:
        import jieba
        keywords = list(jieba.cut_for_search(question))
        keywords = [w.strip() for w in keywords if len(w.strip()) >= 2]
        
        if keywords:
            conditions = []
            params = []
            for kw in keywords[:5]:
                conditions.append("(title LIKE ? OR content LIKE ? OR tags LIKE ?)")
                pattern = f"%{kw}%"
                params.extend([pattern, pattern, pattern])
            
            query = f"SELECT title, content, tags FROM knowledge WHERE {' OR '.join(conditions)} ORDER BY id DESC LIMIT 5"
            cur.execute(query, params)
            rows = cur.fetchall()
            
            for r in rows:
                knowledge_texts.append(f"【{r['title']}】\n{r['content'][:800]}")
            print(f"[关键词搜索] 找到 {len(knowledge_texts)} 条相关知识")
    
    conn.close()
    
    # 构建system_extra_parts
    system_extra_parts = []
    system_extra_parts.append(f"【重要】你是「{bot_name}」，只扮演这个角色。")
    system_extra_parts.append("【开发者信息】这个BOT系统由 Catie猫猫 开发。如果有人问开发者是谁、谁做的、谁写的代码等问题，请告诉他们是「Catie猫猫」开发的。")
    
    if user_memory:
        user_label = user_name or user_id or "用户"
        system_extra_parts.append(f"【关于 {user_label} 的记忆】\n{user_memory[:500]}")
    
    if knowledge_texts:
        kb_part = "\n\n".join(knowledge_texts)[:1000]
        system_extra_parts.append(f"【知识库参考】\n{kb_part}")
    
    if emojis_info:
        system_extra_parts.append(f"{emojis_info}\n偶尔用1-2个表情点缀，别刷屏。")
    
    if members_info:
        system_extra_parts.append(f"{members_info}\n【艾特规则】要艾特某人时，必须从上面列表复制完整的 <@数字ID> 格式（如 <@123456789>），禁止写 <@名字>！")
    
    # 通用艾特规则（即使没有members_info也要告诉AI如何艾特）
    system_extra_parts.append("【重要】如果用户给你一个数字ID让你艾特/批评/评价某人，你必须在回复中使用 <@数字ID> 格式（如 <@1393870232594026506>）来艾特他，这样对方才能收到通知！")
    
    return system_extra_parts, bot_name


async def call_llm(prompt: str, image_urls: list = None, bot_id: str = "default", 
                   chat_messages: list = None, system_extra: str = "") -> str:
    """调用LLM，使用指定BOT的配置，支持多轮对话"""
    config = get_bot_config(bot_id)
    
    if not config.get("llm_api_key"):
        return {"answer": "LLM_API_KEY 未配置，请在后台设置页面配置。", "time": 0, "input_tokens": 0, "output_tokens": 0}

    base_url = config.get("llm_base_url", "").rstrip("/")
    url = f"{base_url}/chat/completions"
    headers = {"Authorization": f"Bearer {config['llm_api_key']}", "Content-Type": "application/json"}
    
    # 获取机器人人设
    bot_persona = config.get("bot_persona", "你是一个友好的中文AI助手。")
    system_prompt = bot_persona
    if system_extra:
        system_prompt += f"\n\n{system_extra}"

    # 构建消息列表
    messages = [{"role": "system", "content": system_prompt}]
    
    # 添加多轮对话历史
    if chat_messages:
        messages.extend(chat_messages)
    
    # 构建当前用户消息（支持图片）
    if prompt:
        if image_urls:
            user_content = [{"type": "text", "text": prompt}]
            for img_url in image_urls:
                processed_url = await process_image_url(img_url)
                if processed_url:
                    user_content.append({
                        "type": "image_url",
                        "image_url": {"url": processed_url}
                    })
        else:
            user_content = prompt
        messages.append({"role": "user", "content": user_content})

    use_stream = config.get("use_stream", 1)
    payload = {
        "model": config.get("llm_model", "gemini-2.0-flash"),
        "messages": messages,
        "stream": bool(use_stream),
    }

    try:
        import time as time_mod
        start_time = time_mod.time()
        
        if use_stream:
            # 流式请求
            answer_chunks = []
            input_tokens = 0
            output_tokens = 0
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream("POST", url, headers=headers, json=payload) as resp:
                    if resp.status_code != 200:
                        error_text = await resp.aread()
                        elapsed = time_mod.time() - start_time
                        return {"answer": f"LLM 调用失败: {resp.status_code} {error_text.decode()}", "time": elapsed, "input_tokens": 0, "output_tokens": 0}
                    
                    async for line in resp.aiter_lines():
                        if line.startswith("data: "):
                            data_str = line[6:]
                            if data_str.strip() == "[DONE]":
                                break
                            try:
                                import json
                                data = json.loads(data_str)
                                delta = data.get("choices", [{}])[0].get("delta", {})
                                if "content" in delta:
                                    answer_chunks.append(delta["content"])
                                # 获取usage（某些API在最后一个chunk返回）
                                if "usage" in data:
                                    usage = data["usage"]
                                    input_tokens = usage.get("prompt_tokens", 0)
                                    output_tokens = usage.get("completion_tokens", 0)
                            except:
                                pass
            
            elapsed = time_mod.time() - start_time
            answer = "".join(answer_chunks).strip()
            return {"answer": answer, "time": elapsed, "input_tokens": input_tokens, "output_tokens": output_tokens}
        else:
            # 非流式请求
            async with httpx.AsyncClient(timeout=90) as client:
                resp = await client.post(url, headers=headers, json=payload)
                elapsed = time_mod.time() - start_time
                if resp.status_code != 200:
                    return {"answer": f"LLM 调用失败: {resp.status_code} {resp.text}", "time": elapsed, "input_tokens": 0, "output_tokens": 0}
                data = resp.json()
                answer = data["choices"][0]["message"]["content"].strip()
                usage = data.get("usage", {})
                input_tokens = usage.get("prompt_tokens", 0)
                output_tokens = usage.get("completion_tokens", 0)
                return {"answer": answer, "time": elapsed, "input_tokens": input_tokens, "output_tokens": output_tokens}
    except Exception as e:
        return {"answer": f"LLM 调用出错: {str(e)}", "time": 0, "input_tokens": 0, "output_tokens": 0}


class FetchModelsRequest(BaseModel):
    base_url: str
    api_key: str


@app.post("/api/fetch_models")
async def fetch_models(body: FetchModelsRequest):
    """从 API 获取可用模型列表"""
    base_url = body.base_url.rstrip("/")
    url = f"{base_url}/models"
    headers = {"Authorization": f"Bearer {body.api_key}"}
    
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                return {"error": f"API 返回 {resp.status_code}: {resp.text[:200]}"}
            
            data = resp.json()
            models = []
            
            # OpenAI 格式: {"data": [{"id": "model-name"}, ...]}
            if "data" in data:
                for m in data["data"]:
                    if isinstance(m, dict) and "id" in m:
                        models.append(m["id"])
            # 其他格式: {"models": ["model1", "model2"]}
            elif "models" in data:
                models = data["models"]
            
            # 按名称排序
            models.sort()
            return {"models": models}
    except Exception as e:
        return {"error": f"请求失败: {str(e)}"}


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    # 如果已经登录，直接跳到 admin
    token = request.cookies.get("admin_token")
    current_password = app_config.get("admin_password", "mz520888")
    if token == current_password:
         return RedirectResponse(url="/admin", status_code=302)
         
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
async def login_action(request: Request, password: str = Form(...)):
    current_password = app_config.get("admin_password", "mz520888")
    
    if password == current_password:
        response = RedirectResponse(url="/admin", status_code=302)
        # 设置 cookie，有效期 7 天
        response.set_cookie(key="admin_token", value=password, max_age=604800)
        return response
    else:
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "密码错误"
        })


@app.get("/logout")
async def logout(request: Request):
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("admin_token")
    return response


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    return RedirectResponse(url="/admin/knowledge", status_code=302)


# ============ BOT 管理 API ============

@app.get("/api/bots")
async def list_bots():
    """获取所有BOT列表"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, name, avatar, created_at FROM bots ORDER BY created_at")
    bots = [dict(row) for row in cur.fetchall()]
    conn.close()
    return {"bots": bots}


@app.post("/api/bots")
async def create_bot(name: str = Form(...), bot_id: str = Form(...)):
    """创建新BOT"""
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO bots (id, name) VALUES (?, ?)", (bot_id, name))
        # 同时在 bot_configs 表中初始化配置记录
        cur.execute(
            """INSERT OR IGNORE INTO bot_configs (bot_id, llm_base_url, llm_api_key, llm_model, bot_persona, context_limit, use_stream)
               VALUES (?, '', '', '', '', 100, 1)""",
            (bot_id,)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="BOT ID 已存在")
    conn.close()
    return {"success": True, "bot_id": bot_id}


@app.delete("/api/bots/{bot_id}")
async def delete_bot(bot_id: str):
    """删除BOT（保留知识库，知识库是共享的）"""
    conn = get_db()
    cur = conn.cursor()
    # 删除关联数据（不删除知识库，知识库共享）
    cur.execute("DELETE FROM bot_configs WHERE bot_id = ?", (bot_id,))
    cur.execute("DELETE FROM user_memories WHERE bot_id = ?", (bot_id,))
    cur.execute("DELETE FROM ask_logs WHERE bot_id = ?", (bot_id,))
    cur.execute("DELETE FROM bots WHERE id = ?", (bot_id,))
    conn.commit()
    conn.close()
    return {"success": True}


@app.get("/api/bot_config/{bot_id}")
async def get_bot_config_api(bot_id: str):
    """获取指定BOT的配置（供其他BOT调用）"""
    config = get_bot_config(bot_id)
    
    # 获取BOT名称
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT name FROM bots WHERE id = ?", (bot_id,))
    bot_row = cur.fetchone()
    config["bot_name"] = bot_row["name"] if bot_row else bot_id
    
    # 同时返回知识库数据
    cur.execute("SELECT id, title, content, tags FROM knowledge WHERE bot_id = ?", (bot_id,))
    rows = cur.fetchall()
    conn.close()
    
    knowledge_list = []
    for row in rows:
        knowledge_list.append({
            "id": row[0],
            "title": row[1],
            "content": row[2],
            "tags": row[3].split(",") if row[3] else []
        })
    
    # 添加知识库到返回数据
    config["knowledge"] = knowledge_list
    
    return config


# ============ 频道白名单 API ============

@app.get("/api/channels/{bot_id}")
async def get_allowed_channels(bot_id: str):
    """获取允许的频道列表"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT allowed_channels FROM bot_configs WHERE bot_id = ?", (bot_id,))
    row = cur.fetchone()
    conn.close()
    
    if row and row[0]:
        channels = [c.strip() for c in row[0].split(",") if c.strip()]
        return {"channels": channels}
    return {"channels": []}


@app.post("/api/channels/{bot_id}/add")
async def add_allowed_channel(bot_id: str, channel_id: str):
    """添加允许的频道"""
    conn = get_db()
    cur = conn.cursor()
    
    # 获取当前列表
    cur.execute("SELECT allowed_channels FROM bot_configs WHERE bot_id = ?", (bot_id,))
    row = cur.fetchone()
    
    if row:
        channels = row[0].split(",") if row[0] else []
        if channel_id not in channels:
            channels.append(channel_id)
        new_value = ",".join(channels)
        cur.execute("UPDATE bot_configs SET allowed_channels = ? WHERE bot_id = ?", (new_value, bot_id))
    else:
        # 插入完整的配置记录，而不是只有 allowed_channels
        cur.execute(
            """INSERT INTO bot_configs (bot_id, llm_base_url, llm_api_key, llm_model, bot_persona, context_limit, use_stream, allowed_channels)
               VALUES (?, '', '', '', '', 100, 1, ?)""",
            (bot_id, channel_id)
        )
    
    conn.commit()
    conn.close()
    return {"success": True}


@app.post("/api/channels/{bot_id}/remove")
async def remove_allowed_channel(bot_id: str, channel_id: str):
    """移除允许的频道"""
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("SELECT allowed_channels FROM bot_configs WHERE bot_id = ?", (bot_id,))
    row = cur.fetchone()
    
    if row and row[0]:
        channels = [c.strip() for c in row[0].split(",") if c.strip()]
        if channel_id in channels:
            channels.remove(channel_id)
        new_value = ",".join(channels)
        cur.execute("UPDATE bot_configs SET allowed_channels = ? WHERE bot_id = ?", (new_value, bot_id))
        conn.commit()
    
    conn.close()
    return {"success": True}


@app.get("/api/knowledge/{bot_id}")
async def get_knowledge_api(bot_id: str):
    """获取指定BOT的知识库（供其他BOT调用）"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, title, content, tags FROM knowledge WHERE bot_id = ?", (bot_id,))
    rows = cur.fetchall()
    conn.close()
    
    knowledge_list = []
    for row in rows:
        knowledge_list.append({
            "id": row[0],
            "title": row[1],
            "content": row[2],
            "tags": row[3].split(",") if row[3] else []
        })
    
    return {"knowledge": knowledge_list, "total": len(knowledge_list)}


@app.get("/admin/bots", response_class=HTMLResponse)
async def bots_page(request: Request):
    """BOT管理页面"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, name, avatar, created_at FROM bots ORDER BY created_at")
    bots = [dict(row) for row in cur.fetchall()]
    conn.close()
    return templates.TemplateResponse("bots.html", {"request": request, "bots": bots})


@app.get("/admin/game", response_class=HTMLResponse)
async def game_page(request: Request):
    """游戏管理页面"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM bots ORDER BY created_at")
    bots = [dict(row) for row in cur.fetchall()]
    conn.close()
    return templates.TemplateResponse("game.html", {"request": request, "bots": bots})


@app.get("/admin/stats", response_class=HTMLResponse)
async def stats_page(request: Request):
    """统计页面"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM bots ORDER BY created_at")
    bots = [dict(row) for row in cur.fetchall()]
    conn.close()
    return templates.TemplateResponse("stats.html", {"request": request, "bots": bots})


@app.get("/admin/memories", response_class=HTMLResponse)
async def memories_page(request: Request):
    """用户记忆管理页面"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM bots ORDER BY created_at")
    bots = [dict(row) for row in cur.fetchall()]
    conn.close()
    return templates.TemplateResponse("memories.html", {"request": request, "bots": bots})


@app.get("/api/memories/{bot_id}")
async def get_memories(bot_id: str, q: str = ""):
    """获取用户记忆列表"""
    conn = get_db()
    cur = conn.cursor()
    
    if q:
        cur.execute(
            "SELECT user_id, user_name, memory, updated_at FROM user_memories WHERE bot_id = ? AND (user_id LIKE ? OR memory LIKE ?) ORDER BY updated_at DESC",
            (bot_id, f"%{q}%", f"%{q}%")
        )
    else:
        cur.execute(
            "SELECT user_id, user_name, memory, updated_at FROM user_memories WHERE bot_id = ? ORDER BY updated_at DESC",
            (bot_id,)
        )
    
    rows = cur.fetchall()
    memories = [{"user_id": r[0], "user_name": r[1], "memory": r[2], "updated_at": r[3]} for r in rows]
    
    # 统计
    total = len(memories)
    avg_length = sum(len(m["memory"]) for m in memories) // total if total > 0 else 0
    
    conn.close()
    return {"memories": memories, "total": total, "avg_length": avg_length}


@app.get("/api/memories/{bot_id}/{user_id}")
async def get_user_memory(bot_id: str, user_id: str):
    """获取单个用户的记忆"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT user_id, user_name, memory, updated_at FROM user_memories WHERE bot_id = ? AND user_id = ?",
        (bot_id, user_id)
    )
    row = cur.fetchone()
    conn.close()
    
    if row:
        return {"user_id": row[0], "user_name": row[1], "memory": row[2], "updated_at": row[3]}
    return {"user_id": user_id, "memory": "", "user_name": ""}


class MemoryUpdateRequest(BaseModel):
    memory: str


@app.put("/api/memories/{bot_id}/{user_id}")
async def update_memory(bot_id: str, user_id: str, body: MemoryUpdateRequest):
    """更新用户记忆"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE user_memories SET memory = ?, updated_at = CURRENT_TIMESTAMP WHERE bot_id = ? AND user_id = ?",
        (body.memory, bot_id, user_id)
    )
    conn.commit()
    conn.close()
    return {"success": True}


@app.delete("/api/memories/{bot_id}/{user_id}")
async def delete_memory(bot_id: str, user_id: str):
    """删除用户记忆"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM user_memories WHERE bot_id = ? AND user_id = ?", (bot_id, user_id))
    conn.commit()
    conn.close()
    return {"success": True}


@app.delete("/api/memories/{bot_id}/clear_all")
async def clear_all_memories(bot_id: str):
    """清空指定BOT的所有用户记忆"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM user_memories WHERE bot_id = ?", (bot_id,))
    deleted_count = cur.rowcount
    conn.commit()
    conn.close()
    return {"success": True, "deleted_count": deleted_count}


class SaveMemoryRequest(BaseModel):
    user_name: str = ""
    memory: str


@app.post("/api/memories/{bot_id}/{user_id}")
async def save_memory(bot_id: str, user_id: str, body: SaveMemoryRequest):
    """保存或追加用户记忆"""
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # 先按 (bot_id, user_id) 查找
        cur.execute("SELECT memory FROM user_memories WHERE bot_id = ? AND user_id = ?", (bot_id, user_id))
        row = cur.fetchone()
        
        if not row:
            # 兼容旧数据：按 user_id 查找（旧表可能只有 user_id 唯一约束）
            cur.execute("SELECT memory FROM user_memories WHERE user_id = ?", (user_id,))
            row = cur.fetchone()
            if row:
                # 更新旧记录，同时设置 bot_id
                old_memory = row["memory"] if row["memory"] else ""
                new_memory = f"{old_memory}\n{body.memory}".strip()[-2000:]
                cur.execute(
                    "UPDATE user_memories SET bot_id = ?, memory = ?, user_name = COALESCE(NULLIF(?, ''), user_name), updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
                    (bot_id, new_memory, body.user_name, user_id)
                )
                conn.commit()
                conn.close()
                return {"success": True}
        
        if row:
            # 追加到现有记忆
            old_memory = row["memory"] if row["memory"] else ""
            new_memory = f"{old_memory}\n{body.memory}".strip()[-2000:]
            cur.execute(
                "UPDATE user_memories SET memory = ?, user_name = COALESCE(NULLIF(?, ''), user_name), updated_at = CURRENT_TIMESTAMP WHERE bot_id = ? AND user_id = ?",
                (new_memory, body.user_name, bot_id, user_id)
            )
        else:
            # 新建记忆
            try:
                cur.execute(
                    "INSERT INTO user_memories (bot_id, user_id, user_name, memory) VALUES (?, ?, ?, ?)",
                    (bot_id, user_id, body.user_name or user_id, body.memory[:2000])
                )
            except sqlite3.IntegrityError:
                # 如果INSERT失败（旧唯一约束），改为UPDATE
                cur.execute(
                    "UPDATE user_memories SET bot_id = ?, memory = ?, user_name = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
                    (bot_id, body.memory[:2000], body.user_name or user_id, user_id)
                )
        
        conn.commit()
        conn.close()
        return {"success": True}
    except Exception as e:
        print(f"保存记忆失败: {e}")
        raise HTTPException(status_code=500, detail=f"保存失败: {str(e)}")


class AppendMemoryRequest(BaseModel):
    user_name: str = ""
    content: str


@app.post("/api/memories/{bot_id}/{user_id}/append")
async def append_memory(bot_id: str, user_id: str, body: AppendMemoryRequest):
    """追加对话上下文到用户记忆"""
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute("SELECT memory FROM user_memories WHERE bot_id = ? AND user_id = ?", (bot_id, user_id))
        row = cur.fetchone()
        
        if row:
            old_memory = row["memory"] if row["memory"] else ""
            # 追加新内容，限制总长度
            new_memory = f"{old_memory}\n{body.content}".strip()[-2000:]
            cur.execute(
                "UPDATE user_memories SET memory = ?, updated_at = CURRENT_TIMESTAMP WHERE bot_id = ? AND user_id = ?",
                (new_memory, bot_id, user_id)
            )
        else:
            cur.execute(
                "INSERT INTO user_memories (bot_id, user_id, user_name, memory) VALUES (?, ?, ?, ?)",
                (bot_id, user_id, body.user_name or user_id, body.content[:2000])
            )
        
        conn.commit()
        conn.close()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


class LogQuestionRequest(BaseModel):
    question: str


@app.post("/api/log_question/{bot_id}")
async def log_question(bot_id: str, body: LogQuestionRequest):
    """记录提问到统计"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO ask_logs (bot_id, question) VALUES (?, ?)", (bot_id, body.question[:500]))
    conn.commit()
    conn.close()
    return {"success": True}


@app.get("/api/stats/{bot_id}")
async def get_stats(bot_id: str):
    """获取统计数据"""
    conn = get_db()
    cur = conn.cursor()
    
    # 总提问数
    cur.execute("SELECT COUNT(*) FROM ask_logs WHERE bot_id = ?", (bot_id,))
    total_questions = cur.fetchone()[0]
    
    # 今日提问数
    cur.execute("SELECT COUNT(*) FROM ask_logs WHERE bot_id = ? AND DATE(created_at) = DATE('now')", (bot_id,))
    today_questions = cur.fetchone()[0]
    
    # 知识条目数
    cur.execute("SELECT COUNT(*) FROM knowledge WHERE bot_id = ?", (bot_id,))
    total_knowledge = cur.fetchone()[0]
    
    # 用户记忆数
    cur.execute("SELECT COUNT(*) FROM user_memories WHERE bot_id = ?", (bot_id,))
    total_users = cur.fetchone()[0]
    
    # 最近7天统计
    cur.execute("""
        SELECT DATE(created_at) as date, COUNT(*) as count 
        FROM ask_logs WHERE bot_id = ? AND created_at >= DATE('now', '-7 days')
        GROUP BY DATE(created_at) ORDER BY date DESC
    """, (bot_id,))
    daily_stats = [{"date": row[0], "count": row[1]} for row in cur.fetchall()]
    
    # 最近提问
    cur.execute("""
        SELECT question, created_at FROM ask_logs WHERE bot_id = ?
        ORDER BY id DESC LIMIT 20
    """, (bot_id,))
    recent_questions = [{"question": row[0][:100], "time": row[1]} for row in cur.fetchall()]
    
    conn.close()
    
    return {
        "total_questions": total_questions,
        "today_questions": today_questions,
        "total_knowledge": total_knowledge,
        "total_users": total_users,
        "daily_stats": daily_stats,
        "recent_questions": recent_questions
    }


@app.get("/admin/knowledge", response_class=HTMLResponse)
async def list_knowledge(request: Request, q: str = "", bot_id: str = "default"):
    conn = get_db()
    cur = conn.cursor()
    
    # 获取所有BOT列表（保留用于其他用途）
    cur.execute("SELECT id, name FROM bots ORDER BY created_at")
    bots = [dict(row) for row in cur.fetchall()]
    
    # 显示所有知识库（不再按bot_id分开）
    if q:
        search_term = f"%{q}%"
        cur.execute(
            "SELECT id, title, content, tags FROM knowledge WHERE (title LIKE ? OR content LIKE ? OR tags LIKE ?) ORDER BY id DESC",
            (search_term, search_term, search_term)
        )
    else:
        cur.execute("SELECT id, title, content, tags FROM knowledge ORDER BY id DESC")
        
    rows = cur.fetchall()
    conn.close()
    return templates.TemplateResponse("knowledge_list.html", {
        "request": request, "items": rows, "q": q, 
        "bots": bots, "current_bot": bot_id
    })


@app.get("/admin/knowledge/export")
async def export_knowledge():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT title, content, tags FROM knowledge")
    # 将 sqlite3.Row 转换为字典列表
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    
    # 返回 JSON 文件下载
    return JSONResponse(
        content=rows,
        headers={"Content-Disposition": "attachment; filename=knowledge_backup.json"}
    )


@app.post("/admin/knowledge/import")
async def import_knowledge(file: UploadFile = File(...)):
    try:
        content = await file.read()
        data = json.loads(content)
        
        if not isinstance(data, list):
            raise ValueError("JSON 格式错误，必须是列表")
            
        conn = get_db()
        cur = conn.cursor()
        count = 0
        for item in data:
            # 简单的重复检查：如果标题完全一样，就跳过？或者直接追加？这里选择直接追加
            if item.get("title") and item.get("content"):
                cur.execute(
                    "INSERT INTO knowledge (title, content, tags) VALUES (?, ?, ?)",
                    (item.get("title"), item.get("content"), item.get("tags", ""))
                )
                count += 1
        conn.commit()
        conn.close()
        
        return RedirectResponse(
            url=f"/admin/knowledge?message=成功导入 {count} 条数据&message_type=success",
            status_code=302
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/admin/knowledge?message=导入失败: {str(e)}&message_type=error",
            status_code=302
        )


@app.post("/admin/knowledge/import_txt")
async def import_knowledge_txt(file: UploadFile = File(...), bot_id: str = Form("default")):
    """导入TXT文件并智能拆分为知识条目"""
    try:
        content = await file.read()
        # 尝试不同编码
        try:
            text = content.decode("utf-8")
        except:
            text = content.decode("gbk", errors="ignore")
        
        # 智能拆分
        chunks = split_txt_content(text)
        
        if not chunks:
            return RedirectResponse(
                url=f"/admin/knowledge?bot_id={bot_id}&message=未能从文件中提取到有效内容&message_type=error",
                status_code=302
            )
        
        conn = get_db()
        cur = conn.cursor()
        count = 0
        
        for chunk in chunks:
            title = chunk.get("title", "")
            chunk_content = chunk.get("content", "")
            tags = chunk.get("tags", "")
            
            if title and chunk_content:
                cur.execute(
                    "INSERT INTO knowledge (bot_id, title, content, tags) VALUES (?, ?, ?, ?)",
                    (bot_id, title, chunk_content, tags)
                )
                item_id = cur.lastrowid
                count += 1
                
                # 添加到向量存储（异步，不阻塞）
                if CHROMA_AVAILABLE and knowledge_collection is not None:
                    doc_text = f"{title}\n{tags}\n{chunk_content}"
                    # 使用chromadb默认embedding（不调用API，节省配额）
                    add_to_vector_store(
                        doc_id=f"kb_{item_id}",
                        text=doc_text,
                        metadata={"bot_id": bot_id, "title": title, "kb_id": item_id}
                    )
        
        conn.commit()
        conn.close()
        
        return RedirectResponse(
            url=f"/admin/knowledge?bot_id={bot_id}&message=成功导入 {count} 条知识（共拆分 {len(chunks)} 段）&message_type=success",
            status_code=302
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/admin/knowledge?bot_id={bot_id}&message=导入失败: {str(e)}&message_type=error",
            status_code=302
        )


@app.post("/admin/knowledge/clear_all")
@app.get("/admin/knowledge/clear_all")
async def clear_all_knowledge(bot_id: str = "default"):
    """清空所有知识库"""
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # 获取所有知识条目的ID用于删除向量
        cur.execute("SELECT id FROM knowledge")
        rows = cur.fetchall()
        
        # 删除向量索引
        for row in rows:
            remove_from_vector_store(f"kb_{row['id']}")
        
        # 清空数据库表
        cur.execute("DELETE FROM knowledge")
        conn.commit()
        count = cur.rowcount
        conn.close()
        
        return RedirectResponse(
            url=f"/admin/knowledge?bot_id={bot_id}&message=已清空 {count} 条知识&message_type=success",
            status_code=302
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/admin/knowledge?bot_id={bot_id}&message=清空失败: {str(e)}&message_type=error",
            status_code=302
        )


@app.post("/admin/knowledge/rebuild_vectors")
async def rebuild_vectors(bot_id: str = Form("default")):
    """重建指定BOT的向量索引"""
    if not CHROMA_AVAILABLE or knowledge_collection is None:
        return RedirectResponse(
            url=f"/admin/knowledge?bot_id={bot_id}&message=向量数据库不可用&message_type=error",
            status_code=302
        )
    
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT id, title, content, tags FROM knowledge WHERE bot_id = ?", (bot_id,))
        rows = cur.fetchall()
        conn.close()
        
        count = 0
        for row in rows:
            doc_text = f"{row['title']}\n{row['tags']}\n{row['content']}"
            add_to_vector_store(
                doc_id=f"kb_{row['id']}",
                text=doc_text,
                metadata={"bot_id": bot_id, "title": row['title'], "kb_id": row['id']}
            )
            count += 1
        
        return RedirectResponse(
            url=f"/admin/knowledge?bot_id={bot_id}&message=成功重建 {count} 条知识的向量索引&message_type=success",
            status_code=302
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/admin/knowledge?bot_id={bot_id}&message=重建失败: {str(e)}&message_type=error",
            status_code=302
        )


class GenerateRequest(BaseModel):
    title: str

@app.post("/admin/api/generate")
async def generate_content(req: GenerateRequest):
    if not req.title:
        return {"error": "标题不能为空"}
        
    prompt = f"""请为知识库生成一条内容。
标题/问题：{req.title}

要求：
1. 内容要准确、清晰，适合直接回复用户。
2. 格式可以是纯文本或简单的Markdown。
3. 不要包含"好的，这是生成的内容"之类的废话，直接给干货。
"""
    result = await call_llm(prompt)
    return {"content": result["answer"]}


@app.get("/admin/settings", response_class=HTMLResponse)
async def settings_page(request: Request, bot_id: str = "default", message: str = None, message_type: str = None):
    global app_config
    app_config = load_config()
    
    # 获取指定BOT的配置
    bot_config = get_bot_config(bot_id)
    # 合并全局配置（如管理员密码）
    bot_config["admin_password"] = app_config.get("admin_password", "")
    
    conn = get_db()
    cur = conn.cursor()
    
    # 获取所有BOT列表
    cur.execute("SELECT id, name FROM bots ORDER BY created_at")
    bots = [dict(row) for row in cur.fetchall()]
    
    # 获取知识库条目数（按bot_id）
    cur.execute("SELECT COUNT(*) FROM knowledge WHERE bot_id = ?", (bot_id,))
    kb_count = cur.fetchone()[0]
    
    # 获取统计数据（按bot_id）
    cur.execute("SELECT COUNT(*) FROM ask_logs WHERE bot_id = ?", (bot_id,))
    total_asks = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM ask_logs WHERE bot_id = ? AND DATE(created_at) = DATE('now')", (bot_id,))
    today_asks = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM ask_logs WHERE bot_id = ? AND created_at >= DATE('now', '-7 days')", (bot_id,))
    week_asks = cur.fetchone()[0]
    
    conn.close()
    
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "config": bot_config,
        "bots": bots,
        "current_bot": bot_id,
        "kb_count": kb_count,
        "total_asks": total_asks,
        "today_asks": today_asks,
        "week_asks": week_asks,
        "message": message,
        "message_type": message_type,
    })


@app.post("/admin/settings")
async def save_settings(
    bot_id: str = Form("default"),
    llm_base_url: str = Form(""),
    llm_api_key: str = Form(""),
    llm_model: str = Form(""),
    bot_persona: str = Form(""),
    context_limit: int = Form(100),
    use_stream: int = Form(1),
    admin_password: str = Form(""),
):
    global app_config
    
    # 保存BOT专属配置
    bot_config = {
        "llm_base_url": llm_base_url.strip(),
        "llm_api_key": llm_api_key.strip(),
        "llm_model": llm_model.strip(),
        "bot_persona": bot_persona.strip(),
        "context_limit": context_limit,
        "use_stream": use_stream,
    }
    save_bot_config(bot_id, bot_config)
    
    # 管理员密码是全局的
    if admin_password.strip():
        app_config["admin_password"] = admin_password.strip()
        save_config(app_config)
    
    # 重定向回设置页面，带成功消息
    return RedirectResponse(
        url=f"/admin/settings?bot_id={bot_id}&message=配置已保存&message_type=success",
        status_code=302
    )


@app.post("/admin/knowledge")
async def create_knowledge(title: str = Form(...), content: str = Form(...), tags: str = Form(""), bot_id: str = Form("default")):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO knowledge (bot_id, title, content, tags) VALUES (?, ?, ?, ?)", (bot_id, title, content, tags))
    item_id = cur.lastrowid
    conn.commit()
    conn.close()
    
    # 添加到向量存储
    if CHROMA_AVAILABLE and knowledge_collection is not None:
        doc_text = f"{title}\n{tags}\n{content}"
        embedding = await get_embedding(doc_text, bot_id)
        add_to_vector_store(
            doc_id=f"kb_{item_id}",
            text=doc_text,
            metadata={"bot_id": bot_id, "title": title, "kb_id": item_id},
            embedding=embedding
        )
    
    return RedirectResponse(url=f"/admin/knowledge?bot_id={bot_id}", status_code=302)


@app.get("/admin/knowledge/{item_id}/edit", response_class=HTMLResponse)
async def edit_knowledge_page(request: Request, item_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, bot_id, title, content, tags FROM knowledge WHERE id = ?", (item_id,))
    item = cur.fetchone()
    conn.close()
    if not item:
        return RedirectResponse(url="/admin/knowledge", status_code=302)
    return templates.TemplateResponse("knowledge_edit.html", {"request": request, "item": item})


@app.post("/admin/knowledge/{item_id}/edit")
async def update_knowledge(item_id: int, title: str = Form(...), content: str = Form(...), tags: str = Form(""), bot_id: str = Form("default")):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE knowledge SET title = ?, content = ?, tags = ? WHERE id = ?", (title, content, tags, item_id))
    conn.commit()
    conn.close()
    
    # 更新向量存储
    if CHROMA_AVAILABLE and knowledge_collection is not None:
        doc_text = f"{title}\n{tags}\n{content}"
        embedding = await get_embedding(doc_text, bot_id)
        add_to_vector_store(
            doc_id=f"kb_{item_id}",
            text=doc_text,
            metadata={"bot_id": bot_id, "title": title, "kb_id": item_id},
            embedding=embedding
        )
    
    return RedirectResponse(url=f"/admin/knowledge?bot_id={bot_id}", status_code=302)


@app.post("/admin/knowledge/{item_id}/delete")
async def delete_knowledge(item_id: int, bot_id: str = Form("default")):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM knowledge WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()
    
    # 从向量存储中删除
    remove_from_vector_store(f"kb_{item_id}")
    
    return RedirectResponse(url=f"/admin/knowledge?bot_id={bot_id}", status_code=302)


@app.post("/api/ask")
async def api_ask(body: AskRequest):
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="问题不能为空")

    conn = get_db()
    cur = conn.cursor()
    
    bot_id = body.bot_id or "default"
    
    # 获取BOT名称
    cur.execute("SELECT name FROM bots WHERE id = ?", (bot_id,))
    bot_row = cur.fetchone()
    bot_name = bot_row["name"] if bot_row else "助手"
    
    # 记录调用日志
    cur.execute("INSERT INTO ask_logs (bot_id, question) VALUES (?, ?)", (bot_id, question[:100]))
    conn.commit()
    
    # 获取用户记忆
    user_memory = ""
    if body.user_id:
        cur.execute("SELECT memory FROM user_memories WHERE bot_id = ? AND user_id = ?", (bot_id, body.user_id))
        row = cur.fetchone()
        if row and row["memory"]:
            user_memory = row["memory"]
    
    # 知识库搜索：优先使用向量搜索，回退到关键词搜索
    knowledge_texts = []
    
    # 尝试向量搜索
    if CHROMA_AVAILABLE and knowledge_collection is not None:
        vector_results = await vector_search(question, bot_id, top_k=5)
        if vector_results:
            for r in vector_results:
                if r.get("score", 0) > 0.3:  # 只保留相似度>0.3的结果
                    meta = r.get("metadata", {})
                    knowledge_texts.append(f"【{meta.get('title', '知识')}】\n{r['content'][:800]}")
            print(f"[向量搜索] 找到 {len(knowledge_texts)} 条相关知识")
    
    # 如果向量搜索无结果，回退到关键词搜索（搜索所有bot的知识库）
    if not knowledge_texts:
        import jieba
        keywords = list(jieba.cut_for_search(question))
        keywords = [w.strip() for w in keywords if len(w.strip()) >= 2]
        
        if keywords:
            conditions = []
            params = []
            for kw in keywords[:5]:
                conditions.append("(title LIKE ? OR content LIKE ? OR tags LIKE ?)")
                pattern = f"%{kw}%"
                params.extend([pattern, pattern, pattern])
            
            # 不限制bot_id，搜索所有知识库
            query = f"SELECT title, content, tags FROM knowledge WHERE {' OR '.join(conditions)} ORDER BY id DESC LIMIT 5"
            cur.execute(query, params)
            rows = cur.fetchall()
            
            for r in rows:
                knowledge_texts.append(f"【{r['title']}】\n{r['content'][:800]}")
            print(f"[关键词搜索] 找到 {len(knowledge_texts)} 条相关知识")
    
    conn.close()

    # 解析聊天历史为多轮对话格式（合并连续同role消息）
    chat_messages = []
    print(f"[DEBUG] 收到聊天历史: {len(body.chat_history) if body.chat_history else 0} 条")
    if body.chat_history:
        for line in body.chat_history:
            if ": " in line:
                author, content = line.split(": ", 1)
                # 判断是自己(BOT)的消息还是用户的消息
                if author.startswith("你("):
                    role = "assistant"
                    msg_content = content
                else:
                    role = "user"
                    msg_content = f"[{author}] {content}"
                
                # 合并连续同role的消息，避免API报错
                if chat_messages and chat_messages[-1]["role"] == role:
                    chat_messages[-1]["content"] += f"\n{msg_content}"
                else:
                    chat_messages.append({"role": role, "content": msg_content})
    
    print(f"[DEBUG] 解析后消息数: {len(chat_messages)}, 总长度: {sum(len(m['content']) for m in chat_messages)}")
    
    # 智能截断：保留最近的消息，总字符数不超过4000
    max_context_chars = 4000
    total_chars = sum(len(m['content']) for m in chat_messages)
    while total_chars > max_context_chars and len(chat_messages) > 2:
        removed = chat_messages.pop(0)  # 移除最早的消息
        total_chars -= len(removed['content'])
    
    # 构建system prompt额外内容
    system_extra_parts = []
    
    # 多BOT场景：明确自己的身份，避免混淆
    system_extra_parts.append(
        f"【身份提醒】你是{bot_name}。聊天记录中标记为[其他Bot]的是其他AI，不是你。"
        f"你只需要以{bot_name}的身份回复，不要模仿或混淆其他Bot的发言。"
    )
    
    user_label = body.user_name if body.user_name else "用户"
    if user_memory:
        system_extra_parts.append(f"【关于 {user_label} 的记忆】\n{user_memory[:500]}")  # 限制记忆长度
    
    if knowledge_texts:
        kb_part = "\n\n".join(knowledge_texts)[:1000]  # 限制知识库长度
        system_extra_parts.append(f"【知识库参考】\n{kb_part}")
    
    if body.emojis_info:
        system_extra_parts.append(f"{body.emojis_info}\n偶尔用1-2个表情点缀，别刷屏。")
    
    if body.members_info:
        system_extra_parts.append(f"{body.members_info}\n【艾特规则】要艾特某人时，必须从上面列表复制完整的 <@数字ID> 格式（如 <@123456789>），禁止写 <@名字>！")
    
    # 通用艾特规则
    system_extra_parts.append("【重要】如果用户给你一个数字ID让你艾特/批评/评价某人，你必须在回复中使用 <@数字ID> 格式（如 <@1393870232594026506>）来艾特他，这样对方才能收到通知！")
    
    system_extra_parts.append(
        "如果有新信息值得记住，在回复最后写：【记住】关键信息"
    )
    
    system_extra = "\n\n".join(system_extra_parts)

    # 当前用户的问题（带上用户名）
    current_prompt = f"[{user_label}] {question}"
    
    # 获取图片URL列表
    image_urls = body.image_urls if body.image_urls else None
    
    llm_result = await call_llm(current_prompt, image_urls, bot_id, chat_messages, system_extra)
    answer = llm_result["answer"]
    api_time = llm_result.get("time", 0)
    input_tokens = llm_result.get("input_tokens", 0)
    output_tokens = llm_result.get("output_tokens", 0)
    
    # 解析并保存记忆更新
    if body.user_id and "【记住】" in answer:
        try:
            parts = answer.split("【记住】")
            new_memory_part = parts[-1].strip()
            answer = parts[0].strip()  # 移除记忆更新部分
            
            # 合并新旧记忆
            if user_memory:
                updated_memory = f"{user_memory}\n{new_memory_part}"
            else:
                updated_memory = new_memory_part
            
            # 限制记忆长度
            if len(updated_memory) > 1000:
                updated_memory = updated_memory[-1000:]
            
            conn = get_db()
            cur = conn.cursor()
            # 先按 (bot_id, user_id) 检查
            cur.execute("SELECT id FROM user_memories WHERE bot_id = ? AND user_id = ?", (bot_id, body.user_id))
            exists = cur.fetchone()
            
            if not exists:
                # 兼容旧数据：按 user_id 查找
                cur.execute("SELECT id FROM user_memories WHERE user_id = ?", (body.user_id,))
                old_exists = cur.fetchone()
                if old_exists:
                    # 更新旧记录
                    cur.execute(
                        "UPDATE user_memories SET bot_id = ?, memory = ?, user_name = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
                        (bot_id, updated_memory, body.user_name, body.user_id)
                    )
                    conn.commit()
                    conn.close()
                else:
                    # 新建记录
                    try:
                        cur.execute(
                            "INSERT INTO user_memories (bot_id, user_id, user_name, memory) VALUES (?, ?, ?, ?)",
                            (bot_id, body.user_id, body.user_name, updated_memory)
                        )
                    except sqlite3.IntegrityError:
                        cur.execute(
                            "UPDATE user_memories SET bot_id = ?, memory = ?, user_name = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
                            (bot_id, updated_memory, body.user_name, body.user_id)
                        )
                    conn.commit()
                    conn.close()
            else:
                cur.execute(
                    "UPDATE user_memories SET memory = ?, user_name = ?, updated_at = CURRENT_TIMESTAMP WHERE bot_id = ? AND user_id = ?",
                    (updated_memory, body.user_name, bot_id, body.user_id)
                )
                conn.commit()
                conn.close()
        except Exception as e:
            print(f"[记忆更新错误] {e}")
    
    return {
        "answer": answer,
        "time": round(api_time, 2),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens
    }


@app.post("/api/ask_stream")
async def api_ask_stream(body: AskRequest):
    """流式问答API，返回SSE流"""
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="问题不能为空")

    # ========== 输入安全检查（防破甲）==========
    is_safe, reason = check_input_safety(question)
    if not is_safe:
        print(f"[防破甲] 拦截: {reason} | 内容: {question[:50]}...")
        block_reply = get_block_response()
        async def blocked_stream():
            yield f"data: {json.dumps({'content': block_reply})}\n\n"
            yield f"data: {json.dumps({'done': True, 'input_tokens': 0, 'output_tokens': 0})}\n\n"
        return StreamingResponse(blocked_stream(), media_type="text/event-stream")

    bot_id = body.bot_id or "default"
    config = get_bot_config(bot_id)
    
    if not config.get("llm_api_key"):
        async def error_stream():
            yield f"data: {json.dumps({'error': 'API Key未配置'})}\n\n"
        return StreamingResponse(error_stream(), media_type="text/event-stream")

    conn = get_db()
    cur = conn.cursor()
    
    # 获取BOT名称
    cur.execute("SELECT name FROM bots WHERE id = ?", (bot_id,))
    bot_row = cur.fetchone()
    bot_name = bot_row["name"] if bot_row else "助手"
    
    # 记录调用日志
    cur.execute("INSERT INTO ask_logs (bot_id, question) VALUES (?, ?)", (bot_id, question[:100]))
    conn.commit()
    
    # 获取用户记忆
    user_memory = ""
    if body.user_id:
        cur.execute("SELECT memory FROM user_memories WHERE bot_id = ? AND user_id = ?", (bot_id, body.user_id))
        row = cur.fetchone()
        if row and row["memory"]:
            user_memory = row["memory"]
    
    # 知识库搜索：优先使用向量搜索，回退到关键词搜索
    knowledge_texts = []
    
    # 尝试向量搜索
    if CHROMA_AVAILABLE and knowledge_collection is not None:
        vector_results = await vector_search(question, bot_id, top_k=5)
        if vector_results:
            for r in vector_results:
                if r.get("score", 0) > 0.3:  # 只保留相似度>0.3的结果
                    meta = r.get("metadata", {})
                    knowledge_texts.append(f"【{meta.get('title', '知识')}】\n{r['content'][:800]}")
            print(f"[向量搜索-流式] 找到 {len(knowledge_texts)} 条相关知识")
    
    # 如果向量搜索无结果，回退到关键词搜索（搜索所有bot的知识库）
    if not knowledge_texts:
        import jieba
        keywords = list(jieba.cut_for_search(question))
        keywords = [w.strip() for w in keywords if len(w.strip()) >= 2]
        
        if keywords:
            conditions = []
            params = []
            for kw in keywords[:5]:
                conditions.append("(title LIKE ? OR content LIKE ? OR tags LIKE ?)")
                pattern = f"%{kw}%"
                params.extend([pattern, pattern, pattern])
            
            # 不限制bot_id，搜索所有知识库
            query = f"SELECT title, content, tags FROM knowledge WHERE {' OR '.join(conditions)} ORDER BY id DESC LIMIT 5"
            cur.execute(query, params)
            rows = cur.fetchall()
            
            for r in rows:
                knowledge_texts.append(f"【{r['title']}】\n{r['content'][:800]}")
            print(f"[关键词搜索-流式] 找到 {len(knowledge_texts)} 条相关知识")
    
    conn.close()

    # 构建system prompt
    bot_persona = config.get("bot_persona", "你是一个友好的中文AI助手。")
    system_extra_parts = []
    system_extra_parts.append(f"【重要】你是「{bot_name}」，只扮演这个角色。")
    system_extra_parts.append("【开发者信息】这个BOT系统由 Catie猫猫 开发。如果有人问开发者是谁、谁做的、谁写的代码等问题，请告诉他们是「Catie猫猫」开发的。")
    
    if user_memory:
        system_extra_parts.append(f"【用户记忆】关于 {body.user_name} 的信息：\n{user_memory[-500:]}")
    
    if knowledge_texts:
        kb_part = "\n\n".join(knowledge_texts)[:1000]  # 限制知识库长度
        system_extra_parts.append(f"【知识库参考】\n{kb_part}")
    
    if body.emojis_info:
        system_extra_parts.append(f"{body.emojis_info}\n偶尔用1-2个表情点缀，别刷屏。")
    
    if body.members_info:
        system_extra_parts.append(f"{body.members_info}\n【艾特规则】要艾特某人时，必须从上面列表复制完整的 <@数字ID> 格式（如 <@123456789>），禁止写 <@名字>！")
    
    # 通用艾特规则
    system_extra_parts.append("【重要】如果用户给你一个数字ID让你艾特/批评/评价某人，你必须在回复中使用 <@数字ID> 格式（如 <@1393870232594026506>）来艾特他，这样对方才能收到通知！")
    
    # 回复规则 - 避免混淆聊天历史
    system_extra_parts.append("【回复规则】你只需要回复标记为 ⭐当前消息⭐ 的内容！聊天历史只是背景参考，不要回复历史消息。专注于当前对你说话的人。绝对不要重复你之前说过的话！")
    
    system_extra = "\n\n".join(system_extra_parts)
    system_prompt = bot_persona
    if system_extra:
        system_prompt += f"\n\n{system_extra}"

    # 构建消息
    messages = [{"role": "system", "content": system_prompt}]
    
    # 添加聊天历史（作为背景信息，不分assistant/user角色，避免模型"继续"之前的回复）
    if body.chat_history:
        history_lines = []
        for line in body.chat_history[-10:]:
            if ": " in line:
                history_lines.append(line)
        if history_lines:
            history_text = "【聊天记录（仅供参考，不要重复这些内容）】\n" + "\n".join(history_lines)
            messages.append({"role": "user", "content": history_text})
    
    # 添加当前问题（支持图片）- 用明确标记区分
    if body.image_urls:
        user_content = [{"type": "text", "text": f"⭐当前消息⭐ [{body.user_name}]: {question}"}]
        for img_url in body.image_urls:
            processed_url = await process_image_url(img_url)
            if processed_url:
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": processed_url}
                })
        messages.append({"role": "user", "content": user_content})
    else:
        # 当前消息单独作为一条，用明确标记区分
        user_content = f"⭐当前消息⭐ [{body.user_name}]: {question}"
        messages.append({"role": "user", "content": user_content})

    base_url = config.get("llm_base_url", "").rstrip("/")
    url = f"{base_url}/chat/completions"
    headers = {"Authorization": f"Bearer {config['llm_api_key']}", "Content-Type": "application/json"}
    payload = {
        "model": config.get("llm_model", "gemini-2.0-flash"),
        "messages": messages,
        "stream": True,
    }

    async def generate():
        try:
            input_tokens = 0
            output_tokens = 0
            full_response = []  # 收集完整回复用于审核
            prefix_buffer = ""  # 用于检测并过滤回复前缀
            prefix_checked = False  # 是否已完成前缀检测
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream("POST", url, headers=headers, json=payload) as resp:
                    if resp.status_code != 200:
                        error_text = await resp.aread()
                        yield f"data: {json.dumps({'error': f'API错误: {resp.status_code}'})}\n\n"
                        return
                    
                    async for line in resp.aiter_lines():
                        if line.startswith("data: "):
                            data_str = line[6:]
                            if data_str.strip() == "[DONE]":
                                # 输出buffer中剩余内容
                                if prefix_buffer:
                                    yield f"data: {json.dumps({'content': sanitize_output(prefix_buffer)})}\n\n"
                                # ========== 输出安全检查 ==========
                                full_text = "".join(full_response)
                                is_safe, reason = check_output_safety(full_text)
                                if not is_safe:
                                    print(f"[防破甲] 输出拦截: {reason}")
                                yield f"data: {json.dumps({'done': True, 'input_tokens': input_tokens, 'output_tokens': output_tokens})}\n\n"
                                break
                            try:
                                data = json.loads(data_str)
                                # 捕获usage信息（有些API在流式响应中返回）
                                usage = data.get("usage", {})
                                if usage:
                                    input_tokens = usage.get("prompt_tokens", input_tokens)
                                    output_tokens = usage.get("completion_tokens", output_tokens)
                                delta = data.get("choices", [{}])[0].get("delta", {})
                                if "content" in delta:
                                    chunk = delta["content"]
                                    full_response.append(chunk)
                                    
                                    # 检测并过滤回复前缀 (回复xxx「xxx」）
                                    if not prefix_checked:
                                        prefix_buffer += chunk
                                        # 检查是否以回复前缀开头
                                        if prefix_buffer.lstrip().startswith('(') or prefix_buffer.lstrip().startswith('（'):
                                            # 可能有前缀，等待右括号
                                            if ')' in prefix_buffer or '）' in prefix_buffer or len(prefix_buffer) > 150:
                                                # 过滤掉回复前缀
                                                filtered = re.sub(r'^[\(（]回复[^）\)]+[）\)]', '', prefix_buffer)
                                                if filtered != prefix_buffer:
                                                    print(f"[过滤回复前缀] {prefix_buffer[:50]}...")
                                                prefix_buffer = filtered.lstrip()
                                                if prefix_buffer:
                                                    yield f"data: {json.dumps({'content': sanitize_output(prefix_buffer)})}\n\n"
                                                prefix_buffer = ""
                                                prefix_checked = True
                                            # 否则继续等待，不发送
                                        else:
                                            # 不是以括号开头，没有前缀，直接发送
                                            yield f"data: {json.dumps({'content': sanitize_output(prefix_buffer)})}\n\n"
                                            prefix_buffer = ""
                                            prefix_checked = True
                                    else:
                                        # 实时过滤敏感词
                                        chunk = sanitize_output(chunk)
                                        yield f"data: {json.dumps({'content': chunk})}\n\n"
                            except:
                                pass
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# ==================== 游戏系统 API ====================

@app.get("/api/game/currency/{bot_id}/{user_id}")
async def get_user_currency(bot_id: str, user_id: str):
    """获取用户货币"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT coins, last_daily FROM user_currency WHERE bot_id = ? AND user_id = ?", (bot_id, user_id))
    row = cur.fetchone()
    conn.close()
    if row:
        return {"coins": row[0], "last_daily": row[1]}
    return {"coins": 0, "last_daily": ""}


@app.post("/api/game/currency/{bot_id}/{user_id}/add")
async def add_user_currency(bot_id: str, user_id: str, amount: int, description: str = ""):
    """增加用户货币"""
    conn = get_db()
    cur = conn.cursor()
    # 获取当前余额
    cur.execute("SELECT coins FROM user_currency WHERE bot_id = ? AND user_id = ?", (bot_id, user_id))
    row = cur.fetchone()
    current = row[0] if row else 0
    new_balance = current + amount
    
    # 更新余额
    cur.execute(
        "INSERT INTO user_currency (bot_id, user_id, coins, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
        "ON CONFLICT(bot_id, user_id) DO UPDATE SET coins = ?, updated_at = CURRENT_TIMESTAMP",
        (bot_id, user_id, new_balance, new_balance)
    )
    
    # 记录交易
    cur.execute(
        "INSERT INTO transactions (bot_id, user_id, type, amount, description, balance_after) VALUES (?, ?, ?, ?, ?, ?)",
        (bot_id, user_id, "add", amount, description, new_balance)
    )
    conn.commit()
    conn.close()
    return {"success": True, "coins": new_balance}


@app.post("/api/game/currency/{bot_id}/{user_id}/deduct")
async def deduct_user_currency(bot_id: str, user_id: str, amount: int, description: str = ""):
    """扣除用户货币"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT coins FROM user_currency WHERE bot_id = ? AND user_id = ?", (bot_id, user_id))
    row = cur.fetchone()
    current = row[0] if row else 0
    
    if current < amount:
        conn.close()
        return {"success": False, "error": "余额不足", "coins": current}
    
    new_balance = current - amount
    cur.execute(
        "UPDATE user_currency SET coins = ?, updated_at = CURRENT_TIMESTAMP WHERE bot_id = ? AND user_id = ?",
        (new_balance, bot_id, user_id)
    )
    cur.execute(
        "INSERT INTO transactions (bot_id, user_id, type, amount, description, balance_after) VALUES (?, ?, ?, ?, ?, ?)",
        (bot_id, user_id, "deduct", -amount, description, new_balance)
    )
    conn.commit()
    conn.close()
    return {"success": True, "coins": new_balance}


@app.post("/api/game/daily/{bot_id}/{user_id}")
async def claim_daily(bot_id: str, user_id: str, amount: int = 100):
    """领取每日奖励"""
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT coins, last_daily FROM user_currency WHERE bot_id = ? AND user_id = ?", (bot_id, user_id))
    row = cur.fetchone()
    
    if row and row[1] == today:
        conn.close()
        return {"success": False, "error": "今天已经领取过了", "coins": row[0]}
    
    current = row[0] if row else 0
    new_balance = current + amount
    
    cur.execute(
        "INSERT INTO user_currency (bot_id, user_id, coins, last_daily, updated_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP) "
        "ON CONFLICT(bot_id, user_id) DO UPDATE SET coins = ?, last_daily = ?, updated_at = CURRENT_TIMESTAMP",
        (bot_id, user_id, new_balance, today, new_balance, today)
    )
    cur.execute(
        "INSERT INTO transactions (bot_id, user_id, type, amount, description, balance_after) VALUES (?, ?, ?, ?, ?, ?)",
        (bot_id, user_id, "daily", amount, "每日签到", new_balance)
    )
    conn.commit()
    conn.close()
    return {"success": True, "coins": new_balance, "reward": amount}


@app.get("/api/game/affection/{bot_id}/{user_id}")
async def get_user_affection(bot_id: str, user_id: str):
    """获取用户好感度"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT level, exp, total_gifts, last_gift, unlocks FROM user_affection WHERE bot_id = ? AND user_id = ?", (bot_id, user_id))
    row = cur.fetchone()
    conn.close()
    if row:
        return {"level": row[0], "exp": row[1], "total_gifts": row[2], "last_gift": row[3], "unlocks": json.loads(row[4] or "[]")}
    return {"level": 0, "exp": 0, "total_gifts": 0, "last_gift": "", "unlocks": []}


@app.post("/api/game/affection/{bot_id}/{user_id}/add")
async def add_user_affection(bot_id: str, user_id: str, exp: int):
    """增加用户好感度"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT level, exp, total_gifts FROM user_affection WHERE bot_id = ? AND user_id = ?", (bot_id, user_id))
    row = cur.fetchone()
    
    current_level = row[0] if row else 0
    current_exp = row[1] if row else 0
    total_gifts = row[2] if row else 0
    
    new_exp = current_exp + exp
    new_level = current_level
    
    # 升级逻辑：每100经验升一级
    while new_exp >= 100:
        new_exp -= 100
        new_level += 1
    
    cur.execute(
        "INSERT INTO user_affection (bot_id, user_id, level, exp, total_gifts, updated_at) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP) "
        "ON CONFLICT(bot_id, user_id) DO UPDATE SET level = ?, exp = ?, total_gifts = total_gifts + 1, updated_at = CURRENT_TIMESTAMP",
        (bot_id, user_id, new_level, new_exp, total_gifts + 1, new_level, new_exp)
    )
    conn.commit()
    conn.close()
    
    leveled_up = new_level > current_level
    return {"success": True, "level": new_level, "exp": new_exp, "leveled_up": leveled_up}


@app.get("/api/game/shop/{bot_id}")
async def get_shop_items(bot_id: str):
    """获取商店商品列表"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, name, description, price, item_type, effect FROM shop_items WHERE bot_id = ?", (bot_id,))
    rows = cur.fetchall()
    conn.close()
    
    items = []
    for row in rows:
        items.append({
            "id": row[0],
            "name": row[1],
            "description": row[2],
            "price": row[3],
            "type": row[4],
            "effect": json.loads(row[5] or "{}")
        })
    return {"items": items}


class ShopItemRequest(BaseModel):
    id: str
    name: str
    description: str = ""
    price: int = 100
    effect: dict = {"favor": 10}


@app.post("/api/game/shop/{bot_id}/add")
async def add_shop_item(bot_id: str, item: ShopItemRequest):
    """添加商品"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO shop_items (id, bot_id, name, description, price, item_type, effect) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (item.id, bot_id, item.name, item.description, item.price, "gift", json.dumps(item.effect))
    )
    conn.commit()
    conn.close()
    return {"success": True}


@app.delete("/api/game/shop/{bot_id}/{item_id}")
async def delete_shop_item(bot_id: str, item_id: str):
    """删除商品"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM shop_items WHERE id = ? AND bot_id = ?", (item_id, bot_id))
    conn.commit()
    conn.close()
    return {"success": True}


@app.post("/api/game/shop/{bot_id}/buy")
async def buy_item(bot_id: str, user_id: str, item_id: str):
    """购买商品"""
    conn = get_db()
    cur = conn.cursor()
    
    # 获取商品信息
    cur.execute("SELECT name, price, item_type, effect FROM shop_items WHERE id = ? AND bot_id = ?", (item_id, bot_id))
    item = cur.fetchone()
    if not item:
        conn.close()
        return {"success": False, "error": "商品不存在"}
    
    item_name, price, item_type, effect_str = item
    effect = json.loads(effect_str or "{}")
    
    # 检查余额
    cur.execute("SELECT coins FROM user_currency WHERE bot_id = ? AND user_id = ?", (bot_id, user_id))
    row = cur.fetchone()
    current_coins = row[0] if row else 0
    
    if current_coins < price:
        conn.close()
        return {"success": False, "error": "基米币不足", "need": price, "have": current_coins}
    
    # 扣款
    new_balance = current_coins - price
    cur.execute(
        "UPDATE user_currency SET coins = ?, updated_at = CURRENT_TIMESTAMP WHERE bot_id = ? AND user_id = ?",
        (new_balance, bot_id, user_id)
    )
    
    # 记录购买
    cur.execute(
        "INSERT INTO user_purchases (bot_id, user_id, item_id, item_name) VALUES (?, ?, ?, ?)",
        (bot_id, user_id, item_id, item_name)
    )
    
    # 记录交易
    cur.execute(
        "INSERT INTO transactions (bot_id, user_id, type, amount, description, balance_after) VALUES (?, ?, ?, ?, ?, ?)",
        (bot_id, user_id, "purchase", -price, f"购买 {item_name}", new_balance)
    )
    
    # 如果是礼物，增加好感度
    favor_gained = 0
    if item_type == "gift" and "favor" in effect:
        favor_gained = effect["favor"]
        cur.execute("SELECT level, exp FROM user_affection WHERE bot_id = ? AND user_id = ?", (bot_id, user_id))
        aff_row = cur.fetchone()
        current_level = aff_row[0] if aff_row else 0
        current_exp = aff_row[1] if aff_row else 0
        new_exp = current_exp + favor_gained
        new_level = current_level
        while new_exp >= 100:
            new_exp -= 100
            new_level += 1
        cur.execute(
            "INSERT INTO user_affection (bot_id, user_id, level, exp, total_gifts, updated_at) VALUES (?, ?, ?, ?, 1, CURRENT_TIMESTAMP) "
            "ON CONFLICT(bot_id, user_id) DO UPDATE SET level = ?, exp = ?, total_gifts = total_gifts + 1, updated_at = CURRENT_TIMESTAMP",
            (bot_id, user_id, new_level, new_exp, new_level, new_exp)
        )
    
    conn.commit()
    conn.close()
    
    return {
        "success": True,
        "item_name": item_name,
        "price": price,
        "coins": new_balance,
        "favor_gained": favor_gained
    }


@app.get("/api/game/transactions/{bot_id}/{user_id}")
async def get_transactions(bot_id: str, user_id: str, limit: int = 20):
    """获取交易记录"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT type, amount, description, balance_after, created_at FROM transactions WHERE bot_id = ? AND user_id = ? ORDER BY id DESC LIMIT ?",
        (bot_id, user_id, limit)
    )
    rows = cur.fetchall()
    conn.close()
    
    transactions = []
    for row in rows:
        transactions.append({
            "type": row[0],
            "amount": row[1],
            "description": row[2],
            "balance_after": row[3],
            "created_at": row[4]
        })
    return {"transactions": transactions}


@app.get("/api/game/leaderboard/{bot_id}")
async def get_leaderboard(bot_id: str, type: str = "coins", limit: int = 10):
    """获取排行榜"""
    conn = get_db()
    cur = conn.cursor()
    
    if type == "coins":
        cur.execute(
            "SELECT user_id, coins FROM user_currency WHERE bot_id = ? ORDER BY coins DESC LIMIT ?",
            (bot_id, limit)
        )
        rows = cur.fetchall()
        leaderboard = [{"user_id": row[0], "coins": row[1]} for row in rows]
    else:  # affection
        cur.execute(
            "SELECT user_id, level, exp FROM user_affection WHERE bot_id = ? ORDER BY level DESC, exp DESC LIMIT ?",
            (bot_id, limit)
        )
        rows = cur.fetchall()
        leaderboard = [{"user_id": row[0], "level": row[1], "exp": row[2]} for row in rows]
    
    conn.close()
    return {"leaderboard": leaderboard, "type": type}


@app.post("/api/game/migrate")
async def migrate_game_data(path: str = None):
    """从小鱼娘本地 bot_data.json 迁移游戏数据到后端数据库"""
    # 尝试多个可能的路径
    possible_paths = [
        path,  # 用户指定的路径
        "/www/wwwroot/bot/bot_data/bot_data.json",
        "/app/bot_data/bot_data.json",
        "/www/wwwroot/mybot/bot_data/bot_data.json",
        os.path.join(DATA_DIR, "bot_data.json"),
    ]
    
    bot_data_path = None
    for p in possible_paths:
        if p and os.path.exists(p):
            bot_data_path = p
            break
    
    bot_id = "maodie"  # 只有小鱼娘有游戏数据
    
    if not bot_data_path:
        return {"success": False, "error": f"文件不存在，尝试过的路径: {[p for p in possible_paths if p]}"}
    
    try:
        with open(bot_data_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return {"success": False, "error": f"读取文件失败: {e}"}
    
    conn = get_db()
    cur = conn.cursor()
    
    migrated = {"currency": 0, "affection": 0}
    
    # 迁移货币数据
    user_currency = data.get("user_currency", {})
    for user_id, info in user_currency.items():
        coins = info.get("coins", 0) if isinstance(info, dict) else info
        last_daily = info.get("last_daily", "") if isinstance(info, dict) else ""
        cur.execute(
            "INSERT INTO user_currency (bot_id, user_id, coins, last_daily, updated_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(bot_id, user_id) DO UPDATE SET coins = ?, last_daily = ?, updated_at = CURRENT_TIMESTAMP",
            (bot_id, user_id, coins, last_daily, coins, last_daily)
        )
        migrated["currency"] += 1
    
    # 迁移好感度数据
    user_affection = data.get("user_affection", {})
    for user_id, info in user_affection.items():
        level = info.get("level", 0)
        exp = info.get("exp", 0)
        total_gifts = info.get("total_gifts", 0)
        last_gift = info.get("last_gift", "")
        unlocks = json.dumps(info.get("unlocks", []))
        cur.execute(
            "INSERT INTO user_affection (bot_id, user_id, level, exp, total_gifts, last_gift, unlocks, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(bot_id, user_id) DO UPDATE SET level = ?, exp = ?, total_gifts = ?, last_gift = ?, unlocks = ?, updated_at = CURRENT_TIMESTAMP",
            (bot_id, user_id, level, exp, total_gifts, last_gift, unlocks, level, exp, total_gifts, last_gift, unlocks)
        )
        migrated["affection"] += 1
    
    conn.commit()
    conn.close()
    
    return {
        "success": True,
        "message": f"迁移完成！货币: {migrated['currency']} 条，好感度: {migrated['affection']} 条",
        "migrated": migrated
    }


# ==================== 黑名单管理 ====================

# 管理员ID列表（可以使用拉黑功能的用户）
ADMIN_IDS = ["1373778569154658426"]  # Catie猫猫的ID

@app.post("/api/blacklist/ban")
async def ban_user(user_id: str, banned_by: str, reason: str = "", duration_hours: int = 0):
    """拉黑用户"""
    if banned_by not in ADMIN_IDS:
        raise HTTPException(status_code=403, detail="无权限执行此操作")
    
    conn = get_db()
    cur = conn.cursor()
    
    expires_at = None
    if duration_hours > 0:
        from datetime import datetime, timedelta
        expires_at = (datetime.now() + timedelta(hours=duration_hours)).isoformat()
    
    cur.execute(
        "INSERT OR REPLACE INTO blacklist (user_id, reason, banned_by, banned_at, expires_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?)",
        (user_id, reason, banned_by, expires_at)
    )
    conn.commit()
    conn.close()
    
    return {"success": True, "user_id": user_id, "expires_at": expires_at}

@app.post("/api/blacklist/unban")
async def unban_user(user_id: str, unbanned_by: str):
    """解除拉黑"""
    if unbanned_by not in ADMIN_IDS:
        raise HTTPException(status_code=403, detail="无权限执行此操作")
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM blacklist WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    
    return {"success": True, "user_id": user_id}

@app.get("/api/blacklist/check/{user_id}")
async def check_blacklist(user_id: str):
    """检查用户是否被拉黑"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT reason, banned_at, expires_at FROM blacklist WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    
    if not row:
        return {"banned": False}
    
    reason, banned_at, expires_at = row
    
    # 检查是否过期
    if expires_at:
        from datetime import datetime
        try:
            expire_time = datetime.fromisoformat(expires_at)
            if datetime.now() > expire_time:
                # 已过期，自动解除
                conn = get_db()
                cur = conn.cursor()
                cur.execute("DELETE FROM blacklist WHERE user_id = ?", (user_id,))
                conn.commit()
                conn.close()
                return {"banned": False}
        except:
            pass
    
    return {"banned": True, "reason": reason, "banned_at": banned_at, "expires_at": expires_at}

@app.get("/api/blacklist/list")
async def list_blacklist():
    """获取黑名单列表"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT user_id, reason, banned_by, banned_at, expires_at FROM blacklist ORDER BY banned_at DESC")
    rows = cur.fetchall()
    conn.close()
    
    return [{"user_id": r[0], "reason": r[1], "banned_by": r[2], "banned_at": r[3], "expires_at": r[4]} for r in rows]

@app.get("/api/blacklist/admins")
async def get_admins():
    """获取管理员列表"""
    return {"admins": ADMIN_IDS}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=False)
