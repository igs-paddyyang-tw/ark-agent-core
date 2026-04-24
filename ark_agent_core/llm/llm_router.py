"""LLMRouter：統一 LLM 路由，支援 Kiro/Gemini/Ollama 三後端 + fallback chain。

根據 LLM_BACKEND 環境變數決定優先順序，自動建構 fallback chain。
Kiro 作為獨立 Agent 後端，僅在 LLM_BACKEND=kiro 時參與一般對話。
"""

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


class LLMRouter:
    """統一 LLM 路由器。

    Fallback chain 建構邏輯：
    - LLM_BACKEND=gemini（預設）：Gemini → Ollama → 靜態
    - LLM_BACKEND=kiro：Kiro → Gemini → Ollama → 靜態
    - LLM_BACKEND=ollama：Ollama → Gemini → 靜態
    """

    def __init__(
        self,
        kiro: Any | None = None,
        gemini: Any | None = None,
        ollama: Any | None = None,
        backend: str | None = None,
    ) -> None:
        self.kiro = kiro
        self.gemini = gemini
        self.ollama = ollama
        self.backend = (backend or os.getenv("LLM_BACKEND", "gemini")).lower()

    def _build_chain(self) -> list[tuple[str, Any]]:
        """根據 backend 設定建構 fallback chain。"""
        all_backends: dict[str, Any] = {
            "kiro": self.kiro,
            "gemini": self.gemini,
            "ollama": self.ollama,
        }
        chain: list[tuple[str, Any]] = []
        if self.backend in all_backends and all_backends[self.backend]:
            chain.append((self.backend, all_backends[self.backend]))
        default_order = ["gemini", "ollama", "kiro"]
        for name in default_order:
            if name != self.backend and all_backends.get(name):
                chain.append((name, all_backends[name]))
        return chain

    async def generate(
        self, prompt: str, system: str = "", tier: str = "FAST",
        temperature: float = 0.7, **kwargs: Any,
    ) -> dict[str, Any]:
        """統一文字生成介面，自動 fallback。"""
        chain = self._build_chain()
        for i, (name, adapter) in enumerate(chain):
            try:
                if name == "kiro":
                    result = await adapter.generate(prompt=prompt, system=system)
                else:
                    result = await adapter.generate(
                        prompt=prompt, system=system, tier=tier, temperature=temperature,
                    )
                result["fallback"] = i > 0
                result["backend"] = name
                return result
            except Exception as e:
                logger.warning("LLMRouter: %s 失敗，嘗試下一個: %s", name, e)
                continue
        return {
            "text": "抱歉，目前無法處理您的請求。所有 LLM 後端暫時不可用。",
            "model": "static_fallback", "tokens": 0, "fallback": True, "backend": "static",
        }

    async def function_call(
        self, user_message: str, tools: list[dict], tier: str = "BALANCE",
    ) -> dict[str, Any]:
        """Function Calling（僅 Gemini 支援）。"""
        if self.gemini:
            try:
                return await self.gemini.function_call(
                    user_message=user_message, tools=tools, tier=tier,
                )
            except Exception as e:
                logger.warning("LLMRouter FC 失敗: %s", e)
        return {"action": "reply", "text": "抱歉，Function Calling 目前不可用（需要 Gemini API Key）。"}
