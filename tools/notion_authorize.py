"""Notion OAuth 授权：本地回调服务 + PKCE。

流程：
  1. 动态客户端注册（DCR）拿 client_id（需浏览器 UA，否则 Cloudflare 1010）
  2. 生成 PKCE code_verifier / challenge
  3. 起本地 HTTP 服务监听 http://127.0.0.1:8765/callback
  4. 打印授权链接 -> 用户在浏览器点「允许」
  5. 收到 code -> 换 access_token / refresh_token
  6. 保存到 .notion_oauth.json（已被 .gitignore 排除）

用法：
    python tools/notion_authorize.py
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import secrets
import socketserver
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

MCP = "https://mcp.notion.com"
REDIRECT_PORT = 8765
REDIRECT_URI = f"http://127.0.0.1:{REDIRECT_PORT}/callback"
SCOPE = "default"

ROOT = Path(__file__).resolve().parent.parent
TOKEN_FILE = ROOT / ".notion_oauth.json"

# Cloudflare 按 UA 拦截 Python 默认 UA，必须伪装成浏览器
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

_result: dict = {}


def _post(url: str, payload: dict, *, form: bool = False) -> dict:
    if form:
        data = urllib.parse.urlencode(payload).encode()
        ctype = "application/x-www-form-urlencoded"
    else:
        data = json.dumps(payload).encode()
        ctype = "application/json"
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": ctype, "Accept": "application/json",
                 "User-Agent": UA},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        qs = urllib.parse.parse_qs(parsed.query)
        _result.update({k: v[0] for k, v in qs.items()})

        ok = "code" in _result
        body = (
            "<html><head><meta charset='utf-8'><title>授权结果</title></head>"
            "<body style='font-family:sans-serif;padding:40px'>"
            f"<h2>{'✅ 授权成功' if ok else '❌ 授权失败'}</h2>"
            "<p>可以关闭本页面，回到 DSH 继续。</p>"
            f"<pre style='color:#666'>{json.dumps(_result, ensure_ascii=False)[:400]}</pre>"
            "</body></html>"
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, *args):  # 静音
        pass


def main() -> int:
    print("=== 1. 动态客户端注册 ===")
    try:
        reg = _post(f"{MCP}/register", {
            "client_name": "Course Notes Assistant (local)",
            "redirect_uris": [REDIRECT_URI],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "scope": SCOPE,
        })
    except urllib.error.HTTPError as e:
        print(f"  [FAIL] HTTP {e.code}: {e.read().decode()[:300]}")
        return 1
    client_id = reg.get("client_id")
    if not client_id:
        print(f"  [FAIL] 没拿到 client_id: {reg}")
        return 1
    print(f"  [OK] client_id = {client_id}")

    print("=== 2. 生成 PKCE ===")
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")
    state = secrets.token_urlsafe(16)
    print("  [OK]")

    print("=== 3. 启动本地回调服务 ===")
    try:
        httpd = socketserver.TCPServer(("127.0.0.1", REDIRECT_PORT), Handler)
    except OSError as e:
        print(f"  [FAIL] 端口 {REDIRECT_PORT} 被占用: {e}")
        return 1
    httpd.timeout = 1
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    print(f"  [OK] 监听 {REDIRECT_URI}")

    print("=== 4. 授权链接（请在浏览器打开） ===")
    auth_url = f"{MCP}/authorize?" + urllib.parse.urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    print()
    print(auth_url)
    print()
    print("=== 5. 等待你在浏览器完成授权（最多 10 分钟） ===")
    deadline = time.time() + 600
    while time.time() < deadline and "code" not in _result and "error" not in _result:
        time.sleep(1)
    httpd.shutdown()

    if "error" in _result:
        print(f"  [FAIL] 授权被拒绝: {_result}")
        return 1
    if "code" not in _result:
        print("  [FAIL] 超时未收到授权码")
        return 1
    if _result.get("state") != state:
        print(f"  [FAIL] state 不匹配（可能是 CSRF）: {_result.get('state')!r} != {state!r}")
        return 1
    print("  [OK] 收到授权码")

    print("=== 6. 用授权码换 token ===")
    try:
        tok = _post(f"{MCP}/token", {
            "grant_type": "authorization_code",
            "code": _result["code"],
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        }, form=True)
    except urllib.error.HTTPError as e:
        print(f"  [FAIL] HTTP {e.code}: {e.read().decode()[:400]}")
        return 1

    access = tok.get("access_token")
    if not access:
        print(f"  [FAIL] 没拿到 access_token: {list(tok.keys())}")
        return 1
    print(f"  [OK] access_token 长度 = {len(access)}")
    print(f"  refresh_token: {'有' if tok.get('refresh_token') else '无'}")
    print(f"  expires_in: {tok.get('expires_in')}")

    TOKEN_FILE.write_text(json.dumps({
        "client_id": client_id,
        "access_token": access,
        "refresh_token": tok.get("refresh_token"),
        "expires_in": tok.get("expires_in"),
        "obtained_at": int(time.time()),
        "token_endpoint": f"{MCP}/token",
        "mcp_url": f"{MCP}/mcp",
    }, indent=2), encoding="utf-8")
    print(f"  [OK] 已保存到 {TOKEN_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
