import asyncio
import botpy
import hmac
import math
import os
import re
import subprocess
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

# 文件路径基于脚本所在目录，避免依赖启动时的工作目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORY_FILE = os.path.join(BASE_DIR, "agent_memory.md")

# 认证相关参数
AUTH_TTL = 30 * 60            # 认证会话有效期（秒）
AUTH_MAX_FAILS = 5            # 连续失败次数上限
AUTH_LOCK_SECONDS = 15 * 60   # 达到上限后锁定时长（秒）

# 高危命令确认参数
CONFIRM_TTL = 120             # 等待确认的有效期（秒）

# 命令执行参数
CMD_TIMEOUT = 300             # 单条命令超时（秒）
OUTPUT_LIMIT = 1500           # 回传到 QQ 的输出最大字符数

# 已认证的会话：{sender_id: 过期时间戳}
auth_sessions = {}
# 认证失败记录：{sender_id: {"count": 连续失败次数, "locked_until": 解锁时间戳}}
auth_fail = {}
# 每个用户最后一次通过验证的时间窗口，用于阻止验证码重放
totp_last_step = {}
# 等待确认的高危命令：{sender_id: (命令, 过期时间戳)}
pending_cmds = {}

# 需要在回复中脱敏的敏感值
SECRETS = [s for s in (APP_SECRET, DS_KEY, ADMIN_TOTP_SECRET) if s]

# 高危命令模式，命中则需要管理员回复 #确认 后才执行
DANGER_PATTERNS = [
    r"\brm\s+-[a-z]*r",          # rm -r / rm -rf 等
    r"\bmkfs",
    r"\bdd\s+if=",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bhalt\b",
    r"\bpoweroff\b",
    r"\buserdel\b",
    r"\bdeluser\b",
    r"\bpasswd\b",
    r"\biptables\s+-F",
    r"\bchmod\s+-R",
    r"\bchown\s+-R",
    r">\s*/dev/sd",
    r":\(\)\s*\{",               # fork bomb
]

client = OpenAI(api_key=DS_KEY, base_url="https://api.deepseek.com/v1")

# 短期记忆区（按用户存储，限制最多 10 条防溢出）
chat_histories = {}

def redact(text):
    """把回复中出现的敏感值替换掉，避免通过 QQ 泄露。"""
    for s in SECRETS:
        text = text.replace(s, "***")
    return text

def clean_command(text):
    """去掉模型可能输出的 Markdown 代码围栏和反引号，只保留命令本身。"""
    t = text.strip()
    t = re.sub(r"^```[a-zA-Z]*\s*\n?", "", t)
    t = re.sub(r"\n?```\s*$", "", t)
    return t.strip().strip("`").strip()

def is_dangerous(cmd):
    return any(re.search(p, cmd, re.IGNORECASE) for p in DANGER_PATTERNS)

def verify_totp(sender_id, code):
    """校验 6 位动态码，允许前后各一个时间窗口的误差；同一窗口只能使用一次。"""
    if not ADMIN_TOTP_SECRET or not re.fullmatch(r"\d{6}", code):
        return False
    totp = pyotp.TOTP(ADMIN_TOTP_SECRET)
    current = int(time.time()) // 30
    for step in (current - 1, current, current + 1):
        if step <= totp_last_step.get(sender_id, -1):
            continue
        if hmac.compare_digest(totp.at(step * 30), code):
            totp_last_step[sender_id] = step
            return True
    return False

def locked_remaining(sender_id):
    """返回认证被锁定的剩余秒数，未锁定返回 0。"""
    rec = auth_fail.get(sender_id)
    if not rec:
        return 0
    return max(0, rec["locked_until"] - time.time())

def record_fail(sender_id):
    rec = auth_fail.setdefault(sender_id, {"count": 0, "locked_until": 0})
    rec["count"] += 1
    if rec["count"] >= AUTH_MAX_FAILS:
        rec["locked_until"] = time.time() + AUTH_LOCK_SECONDS
        rec["count"] = 0

def is_authed(sender_id):
    return time.time() < auth_sessions.get(sender_id, 0)

def run_command(cmd):
    """同步执行 shell 命令，返回 (输出, 错误信息)。在线程中调用，避免阻塞机器人。"""
    try:
        output = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT, text=True, timeout=CMD_TIMEOUT)
        return output, None
    except subprocess.TimeoutExpired:
        return "", "超时"
    except subprocess.CalledProcessError as e:
        return e.output or "", f"退出码 {e.returncode}"
    except Exception as e:
        return "", str(e)

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
    async def execute(self, message: Message, cmd, seq):
        """执行命令并回传结果。seq 为本次回复使用的起始 msg_seq。"""
        await message.reply(content=f"⚙️ 宿主机执行:\n{redact(cmd)}", msg_seq=seq)
        output, err = await asyncio.to_thread(run_command, cmd)
        body = redact(output)[-OUTPUT_LIMIT:]
        if err == "超时":
            await message.reply(content="❌ 执行超时。", msg_seq=seq + 1)
        elif err:
            await message.reply(content=f"❌ 报错（{redact(err)}）:\n{body}", msg_seq=seq + 1)
        else:
            text = body if body.strip() else "✅ 执行完毕，无输出。"
            await message.reply(content=f"💻 结果:\n\n{text}", msg_seq=seq + 1)

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
            remaining = locked_remaining(sender_id)
            if remaining > 0:
                await message.reply(content=f"🔒 认证失败次数过多，请 {math.ceil(remaining / 60)} 分钟后再试。", msg_seq=1)
                return
            code = user_msg.replace("#认证", "", 1).strip()
            if verify_totp(sender_id, code):
                auth_sessions[sender_id] = time.time() + AUTH_TTL
                auth_fail.pop(sender_id, None)
                await message.reply(content="✅ 认证成功，30 分钟内有效。", msg_seq=1)
            else:
                record_fail(sender_id)
                await message.reply(content="❌ 动态码错误或已过期，请重试。", msg_seq=1)
            return

        # 所有其他指令都必须先通过认证
        if not is_authed(sender_id):
            await message.reply(content="🔒 未认证。请私聊发送：#认证 <6位动态码>", msg_seq=1)
            return

        # 高危命令确认 / 取消
        if user_msg == "#确认":
            item = pending_cmds.pop(sender_id, None)
            if not item or time.time() > item[1]:
                await message.reply(content="没有待确认的命令，或已过期。", msg_seq=1)
                return
            await self.execute(message, item[0], seq=1)
            return
        if user_msg == "#取消":
            pending_cmds.pop(sender_id, None)
            await message.reply(content="已取消。", msg_seq=1)
            return

        if user_msg.startswith("#记住") or user_msg.startswith("记住"):
            content = re.sub(r"^(#记住|记住)", "", user_msg, count=1).strip()
            if not content:
                await message.reply(content="用法：#记住 要记住的内容", msg_seq=1)
                return
            save_memory(content)
            await message.reply(content=f"🧠 已写入长期记忆：{content}", msg_seq=1)
            return

        await message.reply(content="⏳ 思考中...", msg_seq=1)
        try:
            raw = await asyncio.to_thread(ask_deepseek, sender_id, user_msg)
        except Exception as e:
            await message.reply(content=f"❌ 调用大模型失败：{redact(str(e))[-300:]}", msg_seq=2)
            return

        result = clean_command(raw)
        print(f"\n[DEBUG] {sender_id} -> {redact(result)}")

        if result.startswith("TEXT:"):
            await message.reply(content=redact(result[5:].strip()), msg_seq=2)
        elif is_dangerous(result):
            pending_cmds[sender_id] = (result, time.time() + CONFIRM_TTL)
            await message.reply(
                content=f"⚠️ 检测到高危命令，已暂停执行：\n{redact(result)}\n\n"
                        f"请在 {CONFIRM_TTL} 秒内回复 #确认 执行，或回复 #取消。",
                msg_seq=2,
            )
        else:
            await self.execute(message, result, seq=2)

    async def on_at_message_create(self, message: Message): await self.process_msg(message)
    async def on_group_at_message_create(self, message: Message): await self.process_msg(message)
    async def on_c2c_message_create(self, message: Message): await self.process_msg(message, is_private=True)

if __name__ == "__main__":
    intents = botpy.Intents(public_messages=True, public_guild_messages=True, direct_message=True)
    print("🚀 Agent 启动...")
    MyAgent(intents=intents).run(appid=APP_ID, secret=APP_SECRET)
