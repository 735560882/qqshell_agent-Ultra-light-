import botpy
import subprocess
import os
import time
import pyotp
from openai import OpenAI
from botpy.message import Message
from dotenv import load_dotenv

# 加载 .env 配置
load_dotenv()

APP_ID = os.getenv("APP_ID")
APP_SECRET = os.getenv("APP_SECRET")
DS_KEY = os.getenv("DS_KEY")
ADMIN_OPENID = os.getenv("ADMIN_OPENID")
ADMIN_TOTP_SECRET = os.getenv("ADMIN_TOTP_SECRET")

# 认证会话有效期（秒）：认证成功后 30 分钟内无需重复认证
AUTH_TTL = 30 * 60
# 已认证的会话：{sender_id: 过期时间戳}
auth_sessions = {}

# 需要在回复中脱敏的敏感值
SECRETS = [s for s in (APP_SECRET, DS_KEY, ADMIN_TOTP_SECRET) if s]

client = OpenAI(api_key=DS_KEY, base_url="https://api.deepseek.com/v1")
MEMORY_FILE = "agent_memory.md"

# 短期记忆区（按用户存储，限制最多 10 条防溢出）
chat_histories = {}

def redact(text):
    """把回复中出现的敏感值替换掉，避免通过 QQ 泄露。"""
    for s in SECRETS:
        text = text.replace(s, "***")
    return text

def verify_totp(code):
    """校验 6 位动态码，允许前后各一个时间窗口（约 30 秒）的误差。"""
    if not ADMIN_TOTP_SECRET:
        return False
    return pyotp.TOTP(ADMIN_TOTP_SECRET).verify(code, valid_window=1)

def is_authed(sender_id):
    return time.time() < auth_sessions.get(sender_id, 0)

def get_memory():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return f.read()
    return "目前没有特殊记忆。"

def save_memory(text):
    with open(MEMORY_FILE, "a", encoding="utf-8") as f:
        f.write(f"\n- {text}")

def ask_deepseek(user_id, user_msg):
    long_term_mem = get_memory()
    history = chat_histories.get(user_id, [])

    prompt = f"""
    你是一个拥有完整 root 权限的服务器运维 Agent。

    【长期记忆区】：
    {long_term_mem}

    【核心规则】：
    1. 直接输出纯命令，不要 Markdown 格式。
    2. 闲聊请以 'TEXT:' 开头。
    3. 如果需要执行 Git 操作，请先 cd 到工作区。

    用户请求：{user_msg}
    """

    messages = [{"role": "system", "content": prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_msg})

    try:
        res = client.chat.completions.create(
            model="deepseek-flash",
            messages=messages,
            temperature=0.1,
            max_tokens=800,
            extra_body={"reasoning_effort": "low"}
        )
    except Exception as e:
        print(f"API 降级: {e}")
        res = client.chat.completions.create(
            model="deepseek-flash",
            messages=messages,
            temperature=0.1,
            max_tokens=800
        )

    reply = res.choices[0].message.content.strip()

    history.append({"role": "user", "content": user_msg})
    history.append({"role": "assistant", "content": reply})
    chat_histories[user_id] = history[-10:]

    return reply

class MyAgent(botpy.Client):
    async def process_msg(self, message: Message, is_private=False):
        user_msg = message.content.strip()
        if not user_msg: return

        sender_id = getattr(message.author, 'member_openid', getattr(message.author, 'user_openid', ''))
        # 未配置 ADMIN_OPENID 时拒绝所有请求（fail closed），避免任何人都能让 root 权限的 Agent 执行命令
        if not ADMIN_OPENID or sender_id != ADMIN_OPENID:
            # 把发送者的 OpenID 打印到日志，方便首次配置时获取
            print(f"[AUTH] 拒绝未授权用户，OpenID: {sender_id}（如需授权，请填入 ADMIN_OPENID）")
            return

        # 认证指令：只允许私聊，动态码不进入大模型、不写入记忆或历史
        if user_msg.startswith("#认证"):
            if not is_private:
                await message.reply(content="⚠️ 请私聊发送认证指令，避免动态码在群里暴露。", msg_seq=1)
                return
            code = user_msg.replace("#认证", "", 1).strip()
            if verify_totp(code):
                auth_sessions[sender_id] = time.time() + AUTH_TTL
                await message.reply(content="✅ 认证成功，30 分钟内有效。", msg_seq=1)
            else:
                await message.reply(content="❌ 动态码错误或已过期，请重试。", msg_seq=1)
            return

        # 所有其他指令都必须先通过认证
        if not is_authed(sender_id):
            await message.reply(content="🔒 未认证。请私聊发送：#认证 <6位动态码>", msg_seq=1)
            return

        if user_msg.startswith("#记住") or user_msg.startswith("记住"):
            content = user_msg.replace("#记住", "").replace("记住", "").strip()
            save_memory(content)
            await message.reply(content=f"🧠 已写入长期记忆：{content}", msg_seq=1)
            return

        await message.reply(content="⏳ 思考中...", msg_seq=1)
        ai_reply = ask_deepseek(sender_id, user_msg)
        print(f"\n[DEBUG] {sender_id} -> 执行: {redact(ai_reply)}")

        if ai_reply.startswith("TEXT:"):
            await message.reply(content=redact(ai_reply.replace("TEXT:", "").strip()), msg_seq=2)
        else:
            await message.reply(content=f"⚙️ 宿主机执行:\n{redact(ai_reply)}", msg_seq=2)
            try:
                output = subprocess.check_output(ai_reply, shell=True, stderr=subprocess.STDOUT, text=True, timeout=300)
                reply_msg = output[-1500:] if len(output) > 1500 else output
                reply_msg = redact(reply_msg)
                if not reply_msg.strip(): reply_msg = "✅ 执行完毕，无输出。"
                await message.reply(content=f"💻 结果:\n\n{reply_msg}", msg_seq=3)
            except subprocess.TimeoutExpired:
                await message.reply(content="❌ 执行超时。", msg_seq=3)
            except Exception as e:
                await message.reply(content=f"❌ 报错:\n{redact(str(e)[-1000:])}", msg_seq=3)

    async def on_at_message_create(self, message: Message): await self.process_msg(message)
    async def on_group_at_message_create(self, message: Message): await self.process_msg(message)
    async def on_c2c_message_create(self, message: Message): await self.process_msg(message, is_private=True)

if __name__ == "__main__":
    intents = botpy.Intents(public_messages=True, public_guild_messages=True, direct_message=True)
    print("🚀 Agent 启动...")
    MyAgent(intents=intents).run(appid=APP_ID, secret=APP_SECRET)
