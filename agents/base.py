from __future__ import annotations

import logging
import time
import threading
from typing import Any

from utils.llm_client import call_llm

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 1.0

# 全局 stop_event 引用（由 api.py 设置，供 BaseAgent 检查）
_global_stop_event: threading.Event | None = None


def set_stop_event(event: threading.Event | None) -> None:
    """设置全局 stop_event，供 BaseAgent 在 LLM 调用间隙检查。"""
    global _global_stop_event
    _global_stop_event = event


def get_stop_event() -> threading.Event | None:
    """获取当前全局 stop_event。"""
    return _global_stop_event


class BaseAgent:
    """所有智能体的基类。

    提供统一的角色定义、状态管理、LLM 调用接口。
    子类只需实现自己的领域逻辑。
    """

    def __init__(self, role: str) -> None:
        self.role = role
        self._state: dict[str, Any] = {}
        self.logger = logging.getLogger(self.__class__.__name__)
        logger.info(f"[{self.__class__.__name__}] 角色已初始化：{role}")

    def _check_stop(self) -> bool:
        """检查是否应该停止（调用 stop_event.is_set()）。"""
        ev = _global_stop_event
        if ev and ev.is_set():
            self.logger.info("收到停止信号，中断执行")
            return True
        return False

    # ── LLM 调用 ──────────────────────────────────────────────

    def think(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.7,
        max_retries: int = MAX_RETRIES,
    ) -> str:
        """调用 LLM，带重试机制 + 停止检查 + 超时保护。"""
        if self._check_stop():
            raise InterruptedError("用户取消任务")
        if not system_prompt:
            system_prompt = f"你是{self.role}。"

        last_error = None
        for attempt in range(max_retries):
            # 每次重试前检查停止信号
            if self._check_stop():
                raise InterruptedError("用户取消任务")
            try:
                result = call_llm(prompt, system_prompt=system_prompt, temperature=temperature)
                if result:
                    return result
                last_error = "LLM返回空结果"
            except InterruptedError:
                raise  # 透传停止信号
            except Exception as e:
                last_error = str(e)

            if attempt < max_retries - 1:
                delay = RETRY_DELAY * (2 ** attempt)
                self.logger.warning(
                    f"LLM调用失败(第{attempt+1}次)，{delay}秒后重试: {last_error}"
                )
                time.sleep(delay)

        self.logger.error(f"LLM调用失败，已重试{max_retries}次: {last_error}")
        return ""

    # ── 状态管理 ──────────────────────────────────────────────

    def update_state(self, key: str, value: Any) -> None:
        self._state[key] = value
        self.logger.info(f"state['{key}'] 已更新")

    def get_state(self, key: str | None = None) -> Any:
        if key is None:
            return dict(self._state)
        return self._state.get(key)

    def clear_state(self) -> None:
        self._state.clear()
        self.logger.info("状态已清空")

    # ── 生命周期钩子 ──────────────────────────────────────────

    def on_start(self) -> None:
        """任务开始前的回调，子类可覆盖。"""

    def on_finish(self) -> None:
        """任务结束后的回调，子类可覆盖。"""

    # ── 模板方法 ──────────────────────────────────────────────

    def execute(self, *args, **kwargs) -> Any:
        """模板方法：统一调用流程，自动触发生命周期钩子。"""
        self.on_start()
        try:
            result = self.run(*args, **kwargs)
            return result
        finally:
            self.on_finish()

    def run(self, *args, **kwargs) -> Any:
        """子类必须实现此方法。"""
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} role={self.role!r}>"
