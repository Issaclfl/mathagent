"""简单鉴权：HMAC 签名 token + 密码校验（标准库，零依赖）。

公网部署必需——ModAgent 会消耗 LLM API 额度，未鉴权等于任何人可白嫖。
用法：
  AUTH_PASSWORD=xxx  部署密码（必配；未配置时登录接口拒绝一切请求）
  AUTH_SECRET=xxx    可选，token 签名密钥（不配则用默认值，建议生产配置）
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

_TOKEN_TTL = 7 * 24 * 3600  # token 有效期 7 天


def _secret() -> bytes:
    s = os.environ.get("AUTH_SECRET", "") or "mathagent-deploy-secret"
    return s.encode()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_token(ttl: int = _TOKEN_TTL) -> str:
    """签发 token：base64url(payload).hmac-sha256 签名。"""
    payload = _b64(json.dumps({"exp": int(time.time()) + ttl}).encode())
    sig = _b64(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def verify_token(token: str) -> bool:
    """校验 token：验签 + 过期检查。"""
    try:
        payload, sig = token.split(".")
        expect = _b64(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expect):
            return False
        data = json.loads(_unb64(payload))
        return int(data.get("exp", 0)) > time.time()
    except Exception:
        return False


def check_password(password: str) -> bool:
    """校验登录密码。未配置 AUTH_PASSWORD 时拒绝一切（防裸奔）。"""
    expected = os.environ.get("AUTH_PASSWORD", "")
    if not expected:
        return False
    return hmac.compare_digest(password or "", expected)


if __name__ == "__main__":
    t = make_token()
    print("token:", t[:40], "...")
    print("verify:", verify_token(t))
    print("tamper:", verify_token(t[:-1] + ("x" if t[-1] != "x" else "y")))
