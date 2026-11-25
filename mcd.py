"""麦当劳 MCP 客户端（第一阶段：只读查询）。

接入地址与认证方式见麦当劳 MCP 平台文档：
- 接入地址：https://mcp.mcd.cn
- 传输协议：Streamable HTTP
- 认证：请求头 Authorization: Bearer <token>
- 限流：每个 token 每分钟最多 600 次请求，超过返回 429

安全约束：
- 只能调用 MCD_ALLOWED_TOOLS 里列出的工具，默认为空，即不允许调用任何工具。
- 不经过 shell，模型输出也不会直接传入这里。
"""
import json
import math
import threading
import time
from collections import deque

import httpx

MCD_URL = "https://mcp.mcd.cn"
RATE_LIMIT_PER_MIN = 600
PROTOCOL_VERSION = "2025-03-26"  # 待与平台文档核对


class McdError(Exception):
    """对用户可见的错误信息。"""


class RateLimiter:
    """滑动窗口限速。超过上限时直接报错，不阻塞线程。"""

    def __init__(self, limit=RATE_LIMIT_PER_MIN, window=60.0, clock=time.monotonic):
        self.limit = limit
        self.window = window
        self.clock = clock
        self.calls = deque()
        self.lock = threading.Lock()

    def acquire(self):
        with self.lock:
            now = self.clock()
            while self.calls and now - self.calls[0] >= self.window:
                self.calls.popleft()
            if len(self.calls) >= self.limit:
                wait = self.window - (now - self.calls[0])
                raise McdError(f"本地限速：请 {math.ceil(wait)} 秒后再试")
            self.calls.append(now)


def parse_allowed_tools(raw):
    """把环境变量 MCD_ALLOWED_TOOLS（逗号分隔）解析为集合。"""
    if not raw:
        return set()
    return {name.strip() for name in raw.split(",") if name.strip()}


class McdClient:
    def __init__(self, token, allowed_tools=(), transport=None, limiter=None):
        self.token = token
        self.allowed_tools = set(allowed_tools)
        self.session_id = None
        self.limiter = limiter or RateLimiter()
        self.http = httpx.Client(timeout=30, transport=transport)
        self._id = 0

    def _headers(self):
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        return headers

    def _post(self, payload):
        self.limiter.acquire()
        try:
            r = self.http.post(MCD_URL, headers=self._headers(), json=payload)
        except httpx.HTTPError as e:
            raise McdError(f"连接麦当劳平台失败：{type(e).__name__}")
        if r.status_code == 429:
            raise McdError("平台限流（429），请稍后再试")
        if r.status_code in (401, 403):
            raise McdError("认证失败，请检查 MCD_TOKEN 是否正确")
        if r.status_code >= 400:
            raise McdError(f"平台返回 HTTP {r.status_code}")
        sid = r.headers.get("Mcp-Session-Id")
        if sid:
            self.session_id = sid
        return r

    @staticmethod
    def _parse(r):
        if not r.content:
            return None  # 通知类请求通常返回 202 且无内容
        if "text/event-stream" in r.headers.get("content-type", ""):
            events = [line[5:].strip() for line in r.text.splitlines() if line.startswith("data:")]
            body = json.loads(events[-1]) if events else {}
        else:
            body = r.json()
        if "error" in body:
            message = body["error"].get("message", "未知错误")
            raise McdError(f"平台返回错误：{message}")
        return body.get("result")

    def _rpc(self, method, params=None, notify=False):
        payload = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        if not notify:
            self._id += 1
            payload["id"] = self._id
        return self._parse(self._post(payload))

    def initialize(self):
        self._rpc("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "qqshell_agent", "version": "0.1"},
        })
        self._rpc("notifications/initialized", notify=True)

    def list_tools(self):
        if self.session_id is None:
            self.initialize()
        result = self._rpc("tools/list", {}) or {}
        return result.get("tools", [])

    def call_tool(self, name, arguments=None):
        if name not in self.allowed_tools:
            raise McdError(f"工具 {name} 未在 MCD_ALLOWED_TOOLS 中允许，已拒绝调用")
        if self.session_id is None:
            self.initialize()
        result = self._rpc("tools/call", {"name": name, "arguments": arguments or {}}) or {}
        texts = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
        return "\n".join(texts) if texts else json.dumps(result, ensure_ascii=False)
