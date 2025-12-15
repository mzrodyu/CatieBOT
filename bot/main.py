import os
import re
import discord
import httpx
import json
import asyncio

TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
BACKEND_URL = os.getenv("BACKEND_URL", "http://74.48.84.234:8001")
BOT_ID = os.getenv("BOT_ID", "default")  # Fishy

# 用户消息计数器（用于定期总结）
user_message_counts = {}

async def append_user_context(user_id: str, user_name: str, user_msg: str, bot_reply: str):
    """追加对话上下文到记忆（用于后续总结）"""
    try:
        # 只保存有意义的对话片段
        if len(user_msg) < 3:
            return
        context = f"[{user_name}说]{user_msg[:100]} → [回复]{bot_reply[:100]}"
        async with httpx.AsyncClient(timeout=5) as http:
            await http.post(
                f"{BACKEND_URL.rstrip('/')}/api/memories/{BOT_ID}/{user_id}/append",
                json={"user_name": user_name, "content": context}
            )
    except:
        pass

async def summarize_user_memory(user_id: str, user_name: str):
    """定期总结用户记忆，将对话记录转换为用户特征"""
    try:
        async with httpx.AsyncClient(timeout=60) as http:
            # 获取当前记忆
            resp = await http.get(f"{BACKEND_URL.rstrip('/')}/api/memories/{BOT_ID}/{user_id}")
            if resp.status_code != 200:
                return
            data = resp.json()
            current_memory = data.get('memory', '')
            
            if len(current_memory) < 200:
                return
            
            # 调用后端 AI 总结
            summary_resp = await http.post(
                f"{BACKEND_URL.rstrip('/')}/api/ask",
                json={
                    "question": f"请根据以下聊天记录，提取关于这个用户的关键信息，用简短要点列出（如：名字、爱好、性格特点、重要事件等）。只输出要点，不要废话：\n\n{current_memory[-1500:]}",
                    "bot_id": BOT_ID,
                }
            )
            if summary_resp.status_code == 200:
                summary = summary_resp.json().get('answer', '')
                if summary and len(summary) > 10:
                    # 更新为总结后的特征
                    await http.put(
                        f"{BACKEND_URL.rstrip('/')}/api/memories/{BOT_ID}/{user_id}",
                        json={"memory": summary[:800], "user_name": user_name}
                    )
                    print(f'🧠 [记忆已总结] {user_name}', flush=True)
    except Exception as e:
        print(f'🧠 [记忆总结失败] {e}', flush=True)

# 后端配置缓存
_backend_config_cache = {"config": None, "last_fetch": 0}

async def fetch_backend_config():
    """从后端获取配置"""
    import time
    now = time.time()
    if _backend_config_cache["config"] and now - _backend_config_cache["last_fetch"] < 60:
        return _backend_config_cache["config"]
    
    try:
        async with httpx.AsyncClient(timeout=5) as http:
            resp = await http.get(f"{BACKEND_URL.rstrip('/')}/api/bot_config/{BOT_ID}")
            if resp.status_code == 200:
                _backend_config_cache["config"] = resp.json()
                _backend_config_cache["last_fetch"] = now
                return _backend_config_cache["config"]
    except:
        pass
    return _backend_config_cache.get("config") or {}

def get_context_limit():
    """从后端配置获取上下文长度"""
    if _backend_config_cache["config"]:
        limit = _backend_config_cache["config"].get("context_limit", 100)
        return max(10, min(500, int(limit)))
    return 100

intents = discord.Intents.default()
intents.message_content = True


class MeowClient(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)

    async def on_ready(self):
        print(f"Logged in as {self.user} (ID: {self.user.id})")

    async def on_message(self, message: discord.Message):
        # 忽略自己的消息
        if message.author.id == self.user.id:
            return

        # 检测是否应该响应：被@了 或者 回复了机器人的消息
        is_mentioned = self.user in message.mentions
        is_reply_to_bot = False
        if message.reference and message.reference.message_id:
            try:
                replied_msg = await message.channel.fetch_message(message.reference.message_id)
                if replied_msg.author.id == self.user.id:
                    is_reply_to_bot = True
            except:
                pass
        
        if not is_mentioned and not is_reply_to_bot:
            return
        
        # Bot对Bot：添加冷却防止无限循环（同频道5秒内不重复回复同一个Bot）
        if message.author.bot:
            cooldown_key = f"{message.channel.id}_{message.author.id}"
            now = __import__('time').time()
            if not hasattr(self, '_bot_cooldowns'):
                self._bot_cooldowns = {}
            if cooldown_key in self._bot_cooldowns and now - self._bot_cooldowns[cooldown_key] < 5:
                return
            self._bot_cooldowns[cooldown_key] = now
        
        # 获取后端配置（刷新缓存）
        await fetch_backend_config()

        content = message.content.strip()
        # 提取问题（用正则去掉所有@mention）
        question = re.sub(r'<@!?\d+>', '', content).strip()
        
        # 如果当前消息是回复其他消息，添加回复上下文
        if message.reference:
            try:
                replied_msg = message.reference.resolved
                if not replied_msg:
                    replied_msg = await message.channel.fetch_message(message.reference.message_id)
                replied_author = replied_msg.author.display_name or replied_msg.author.name
                # 获取被回复消息的内容，转换Discord格式为可读文本
                replied_content = replied_msg.content or ""
                # 将@mention转换成@用户名
                for mention in replied_msg.mentions:
                    replied_content = replied_content.replace(f'<@{mention.id}>', f'@{mention.display_name}')
                    replied_content = replied_content.replace(f'<@!{mention.id}>', f'@{mention.display_name}')
                replied_content = re.sub(r'<a?:\w+:\d+>', '', replied_content)  # 去掉自定义emoji
                replied_content = replied_content.strip()[:50]
                if replied_content:
                    question = f"(回复{replied_author}「{replied_content}」) {question}"
                else:
                    question = f"(回复{replied_author}) {question}"
            except:
                pass

        # 没有问题时，设置默认问题
        if not question:
            question = "你好"

        # 检查是否有图片附件
        image_urls = []
        for att in message.attachments:
            if att.content_type and att.content_type.startswith("image/"):
                image_urls.append(att.url)

        # 获取服务器表情包列表
        emojis_info = ""
        if message.guild:
            emoji_list = []
            for emoji in message.guild.emojis[:50]:
                if emoji.animated:
                    emoji_list.append(f"<a:{emoji.name}:{emoji.id}>")
                else:
                    emoji_list.append(f"<:{emoji.name}:{emoji.id}>")
            if emoji_list:
                emojis_info = "可用的服务器表情：" + " ".join(emoji_list)

        # 获取频道最近的聊天记录作为上下文
        chat_history = []
        limit = get_context_limit()
        if limit:
            try:
                async for msg in message.channel.history(limit=limit + 1):
                    if msg.id == message.id:
                        continue
                    # 获取消息内容，保留@标记
                    msg_content = msg.content[:200] if msg.content else ""
                    # 处理附件说明（图片/表情包）
                    if msg.attachments:
                        attachment_types = []
                        for att in msg.attachments:
                            if att.content_type and att.content_type.startswith("image/"):
                                attachment_types.append("[图片]")
                            else:
                                attachment_types.append("[附件]")
                        if attachment_types:
                            msg_content = (msg_content + " " + "".join(attachment_types)).strip()
                    # 处理sticker表情贴纸
                    if msg.stickers:
                        sticker_names = [f"[贴纸:{s.name}]" for s in msg.stickers]
                        msg_content = (msg_content + " " + "".join(sticker_names)).strip()
                    if not msg_content:
                        continue
                    # 标识发送者（只有自己才用"你"，其他Bot用名字区分）
                    if msg.author.id == self.user.id:
                        author_name = f"你({self.user.display_name})"
                    elif msg.author.bot:
                        # 其他Bot的消息，用名字标识，避免混淆
                        author_name = f"[其他Bot]{msg.author.display_name}"
                    else:
                        author_name = msg.author.display_name
                    
                    # 检查是否是回复消息，添加回复上下文
                    reply_context = ""
                    if msg.reference and msg.reference.resolved:
                        replied_msg = msg.reference.resolved
                        replied_author = replied_msg.author.display_name or replied_msg.author.name
                        replied_content = (replied_msg.content or "")[:50]
                        reply_context = f"(回复{replied_author}「{replied_content}」) "
                    
                    chat_history.append(f"{author_name}: {reply_context}{msg_content}")
                chat_history.reverse()
            except Exception as e:
                print(f"[上下文读取错误] {e}")

        # 获取频道成员列表（让AI能用名字艾特人）
        members_info = ""
        if message.guild and hasattr(message.channel, 'members'):
            member_list = []
            for member in list(message.channel.members)[:30]:
                if not member.bot:
                    display_name = member.display_name or member.name
                    member_list.append(f"{display_name}: <@{member.id}>")
            if member_list:
                members_info = "【频道成员】如果要艾特某人，使用对应的格式：\n" + "\n".join(member_list)
        
        # 获取频道标注消息（答疑用，读取所有标注）
        pinned_info = ""
        try:
            pin_list = []
            count = 0
            async for pin in message.channel.pins():
                if count >= 50:  # 最多50条标注
                    break
                pin_author = pin.author.display_name or pin.author.name
                pin_content = (pin.content or "")[:200]  # 每条内容限200字
                if pin_content:
                    pin_list.append(f"- [{pin_author}]: {pin_content}")
                count += 1
            if pin_list:
                pinned_info = "【频道标注消息/重要信息】以下是频道的标注消息，可作为答疑参考：\n" + "\n".join(pin_list)
        except:
            pass

        try:
            # 先发送一条占位消息
            reply_msg = await message.reply("💭 思考中...")
            
            # 使用流式API
            answer_chunks = []
            last_update = 0
            import time as time_mod
            start_time = time_mod.time()
            
            async with httpx.AsyncClient(timeout=120) as http:
                async with http.stream(
                    "POST",
                    f"{BACKEND_URL.rstrip('/')}/api/ask_stream",
                    json={
                        "question": question, 
                        "image_urls": image_urls,
                        "emojis_info": emojis_info + ("\n\n" + pinned_info if pinned_info else ""),
                        "chat_history": chat_history,
                        "user_name": message.author.display_name,
                        "user_id": str(message.author.id),
                        "bot_id": BOT_ID,
                        "members_info": members_info,
                    },
                ) as resp:
                    if resp.status_code != 200:
                        print(f"❌ 后端错误：{resp.status_code}", flush=True)
                        await reply_msg.edit(content="❌ 抱歉，我暂时无法回复，请稍后再试。")
                        return
                    
                    input_tokens = 0
                    output_tokens = 0
                    async for line in resp.aiter_lines():
                        if line.startswith("data: "):
                            data_str = line[6:]
                            try:
                                data = json.loads(data_str)
                                if "error" in data:
                                    await reply_msg.edit(content=f"❌ 错误：{data['error']}")
                                    return
                                if "done" in data:
                                    input_tokens = data.get("input_tokens", 0)
                                    output_tokens = data.get("output_tokens", 0)
                                    break
                                if "content" in data:
                                    answer_chunks.append(data["content"])
                                    # 每0.8秒更新一次消息，避免频繁编辑
                                    now = time_mod.time()
                                    if now - last_update > 0.8:
                                        current_answer = "".join(answer_chunks)
                                        if len(current_answer) > 1900:
                                            current_answer = current_answer[:1900] + "..."
                                        try:
                                            await reply_msg.edit(content=current_answer + " ▌")
                                        except:
                                            pass
                                        last_update = now
                            except:
                                pass
            
            # 最终更新
            answer = "".join(answer_chunks).strip()
            # 过滤掉AI回复开头可能带的回复上下文（对用户隐藏）
            answer = re.sub(r'^[\(（]回复.*?[\)）]\s*', '', answer)
            if not answer:
                await reply_msg.edit(content="❌ 抱歉，我暂时无法回复，请稍后再试。")
                return
            
            elapsed = time_mod.time() - start_time
            stats = f"\n`Time: {elapsed:.1f}s | Input: {input_tokens}t | Output: {output_tokens}t`"
            
            # 确保消息长度不超过Discord限制(2000字符)，预留统计信息空间
            max_answer_len = 1950 - len(stats)
            if len(answer) > max_answer_len:
                answer = answer[:max_answer_len] + "..."
            
            try:
                await reply_msg.edit(content=answer + stats)
            except Exception as edit_err:
                print(f"[编辑消息失败] {edit_err}", flush=True)
                # 尝试重新编辑，进一步截断
                try:
                    await reply_msg.edit(content=answer[:1800] + "..." + stats)
                except:
                    pass
            
            # 保存对话上下文 + 定期总结
            user_id = str(message.author.id)
            user_name = message.author.display_name
            asyncio.create_task(append_user_context(user_id, user_name, question, answer[:200]))
            
            user_message_counts[user_id] = user_message_counts.get(user_id, 0) + 1
            if user_message_counts[user_id] >= 20:
                user_message_counts[user_id] = 0
                asyncio.create_task(summarize_user_memory(user_id, user_name))
        except Exception as e:
            print(f"❌ 请求后端失败：{e}", flush=True)
            try:
                await message.reply("❌ 抱歉，我暂时无法回复，请稍后再试。")
            except:
                pass


client = MeowClient()


def main():
    if not TOKEN:
        raise RuntimeError("DISCORD_BOT_TOKEN 未配置，请在运行环境变量中设置。")
    client.run(TOKEN)


if __name__ == "__main__":
    main()
