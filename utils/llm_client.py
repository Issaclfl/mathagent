import os
from pathlib import Path

import requests
from dotenv import load_dotenv

# 显式加载项目根目录的 .env（不依赖当前工作目录）
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_PATH)

DEFAULT_TIMEOUT = 60


def _get_timeout() -> int:
    """优先从环境变量读取超时时间（秒），回退到默认值。"""
    try:
        return int(os.getenv("LLM_TIMEOUT", str(DEFAULT_TIMEOUT)))
    except ValueError:
        return DEFAULT_TIMEOUT


def _get_model() -> str:
    """优先从环境变量读取模型名，回退到默认值。"""
    return os.getenv("LLM_MODEL", "mimo-v2.5")


def _get_max_tokens() -> int | None:
    """读取单次输出上限；未显式配置时返回 None（不发送该参数）。

    实测：deepseek-v4-flash 的 max_tokens 上限低于 8192，长代码生成会被提前截断
    （finish_reason=length）；不发送时服务端可完整输出 9479+ 字符。因此
    仅在用户显式设置 LLM_MAX_TOKENS 时才发送，其余情况交给服务端决定。
    """
    raw = os.getenv("LLM_MAX_TOKENS", "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def call_llm(prompt: str, system_prompt: str = "", temperature: float = 0.7) -> str:
    api_key = os.getenv("LLM_API_KEY", "")
    api_url = os.getenv("LLM_BASE_URL", "")

    if not api_key:
        print("错误：未找到 LLM_API_KEY，请在 .env 文件中配置")
        return ""

    if not api_url:
        print("错误：未找到 LLM_BASE_URL，请在 .env 文件中配置")
        return ""

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": _get_model(),
        "messages": messages,
        "temperature": temperature,
    }
    max_tokens = _get_max_tokens()
    if max_tokens:
        payload["max_tokens"] = max_tokens

    try:
        url = api_url.rstrip("/") + "/chat/completions"
        resp = requests.post(url, json=payload, headers=headers, timeout=_get_timeout())
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        # 截断检测：finish_reason 非 stop 说明输出被 max_tokens 切断，
        # 视为失败返回空（上层会重试），避免半截代码/半截论文被静默采用
        finish_reason = data["choices"][0].get("finish_reason", "")
        if finish_reason not in ("stop", "", None):
            print(f"LLM 输出被截断 (finish_reason={finish_reason})，本次调用视为失败")
            return ""
        if not content:
            # 空响应诊断：HTTP 200 但无内容（服务端限流/波动），打印状态与响应体便于定位
            print(f"LLM 返回空内容 (HTTP {resp.status_code})，响应体: "
                  f"{str(data)[:200]}")
            return ""
        return content
    except Exception as e:
        print(f"LLM调用失败：{e}")
        return ""


if __name__ == "__main__":
    os.environ["LLM_API_KEY"] = "test-key"
    os.environ["LLM_BASE_URL"] = "https://example.com/test"
    result = call_llm("你好")
    print("测试通过")
