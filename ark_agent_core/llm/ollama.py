"""LLM Adapter：統一 LLM 呼叫介面。

優先使用 Gemini（雲端，快速穩定），Ollama（本地）作為備援。
支援 Model Router + Fallback Chain + Wiki Context 注入。
"""

import json
import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Gemini model tier 對應表
GEMINI_TIERS = {
    "FAST": "gemini-2.5-flash",
    "BALANCE": "gemini-2.5-flash",
    "HEAVY": "gemini-2.5-pro",
}

# Ollama model tier 對應表（備援，使用 Gemma 4 系列）
OLLAMA_TIERS = {
    "FAST": "gemma4:e4b",
    "BALANCE": "gemma4:e4b",
    "HEAVY": "gemma4:26b",
}

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_OLLAMA_URL = "http://localhost:11434"


class LLMAdapter:
    """統一 LLM 呼叫介面。Gemini 為主、Ollama 備援，支援 Wiki Context 自動注入。"""

    def __init__(
        self,
        gemini_api_key: str | None = None,
        gemini_model: str | None = None,
        ollama_url: str = DEFAULT_OLLAMA_URL,
        ollama_enabled: bool | None = None,
        default_model: str = "gemma4:e4b",
        timeout: float = 120.0,
        wiki_dir: str = "./knowledge",
    ) -> None:
        # Gemini 設定（主要）
        self.gemini_api_key = gemini_api_key if gemini_api_key is not None else os.getenv("GEMINI_API_KEY", "")
        self.gemini_model = gemini_model if gemini_model is not None else os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        # Ollama 設定（備援，預設關閉，透過 .env OLLAMA_ENABLED=true 開啟）
        self.ollama_url = ollama_url.rstrip("/")
        self.ollama_enabled = ollama_enabled if ollama_enabled is not None else os.getenv("OLLAMA_ENABLED", "false").lower() in ("true", "1", "yes")
        self.default_model = default_model
        self.timeout = timeout
        self.wiki_dir = wiki_dir

    def select_model(self, tier: str = "FAST") -> str:
        """根據 tier 選擇模型。有 Gemini Key 時選 Gemini，Ollama 啟用時選 Ollama。"""
        if self.gemini_api_key:
            return GEMINI_TIERS.get(tier.upper(), self.gemini_model)
        if self.ollama_enabled:
            return OLLAMA_TIERS.get(tier.upper(), self.default_model)
        # 兩者都沒有 → 仍回傳 Gemini 模型名稱（會在呼叫時失敗並走 static fallback）
        return GEMINI_TIERS.get(tier.upper(), "gemini-2.5-flash")

    def _is_gemini_model(self, model: str) -> bool:
        """判斷模型名稱是否為 Gemini 模型。"""
        return model.startswith("gemini")

    async def generate(
        self,
        prompt: str,
        system: str = "",
        model: str | None = None,
        tier: str = "FAST",
        context: str = "",
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> dict[str, Any]:
        """呼叫 LLM 產生回應。

        優先順序：Gemini（若有 API Key）→ Ollama fallback chain → 靜態回應。

        Args:
            prompt: 使用者 prompt
            system: system prompt
            model: 指定模型（優先於 tier）
            tier: 模型等級 FAST/BALANCE/HEAVY
            context: 額外 context（Wiki 注入用）
            temperature: 溫度
            max_tokens: 最大 token 數

        Returns:
            {"text": str, "model": str, "tokens": int, "fallback": bool}
        """
        selected_model = model or self.select_model(tier)

        # Wiki Context 自動注入
        if not context:
            context = self._load_wiki_context(prompt)

        # 組合 system prompt + context
        full_system = system
        if context:
            full_system = f"{system}\n\n--- Context ---\n{context}" if system else f"--- Context ---\n{context}"

        # 建立 fallback chain
        chain = self._build_fallback_chain(selected_model)

        for i, try_model in enumerate(chain):
            try:
                if self._is_gemini_model(try_model):
                    result = await self._call_gemini(
                        model=try_model,
                        prompt=prompt,
                        system=full_system,
                        temperature=temperature,
                    )
                else:
                    result = await self._call_ollama(
                        model=try_model,
                        prompt=prompt,
                        system=full_system,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                result["fallback"] = i > 0
                self._log_cost(result)
                return result
            except Exception as e:
                logger.warning("LLM call failed for %s: %s (%s)", try_model, e, type(e).__name__)
                continue

        # 全部失敗 → 靜態回應
        return {
            "text": "抱歉，目前無法處理您的請求。所有 LLM 模型暫時不可用。",
            "model": "static_fallback",
            "tokens": 0,
            "fallback": True,
        }

    async def generate_stream(
        self,
        prompt: str,
        system: str = "",
        model: str | None = None,
        tier: str = "FAST",
        on_token: Callable[[str], Awaitable[None]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> dict[str, Any]:
        """串流模式呼叫 LLM。

        Gemini 不支援串流時降級為非串流模式。
        Ollama 支援 stream=True 逐 token callback。
        當 on_token 為 None 時，降級為非串流模式（向後相容）。
        """
        # 無 callback 時降級為非串流模式
        if on_token is None:
            return await self.generate(
                prompt=prompt, system=system, model=model, tier=tier,
                temperature=temperature, max_tokens=max_tokens,
            )

        selected_model = model or self.select_model(tier)
        chain = self._build_fallback_chain(selected_model)

        for i, try_model in enumerate(chain):
            try:
                if self._is_gemini_model(try_model):
                    # Gemini 不支援逐 token 串流，降級為一次性回傳後觸發 callback
                    result = await self._call_gemini(
                        model=try_model, prompt=prompt,
                        system=system, temperature=temperature,
                    )
                    # 模擬串流：將完整文字拆成 chunks 觸發 callback
                    text = result.get("text", "")
                    chunk_size = 20
                    for j in range(0, len(text), chunk_size):
                        await on_token(text[j:j + chunk_size])
                    result["fallback"] = i > 0
                    return result
                else:
                    result = await self._call_ollama_stream(
                        model=try_model, prompt=prompt, system=system,
                        temperature=temperature, max_tokens=max_tokens,
                        on_token=on_token,
                    )
                    result["fallback"] = i > 0
                    return result
            except Exception as e:
                logger.warning("LLM stream call failed for %s: %s (%s)", try_model, e, type(e).__name__)
                continue

        return {
            "text": "抱歉，目前無法處理您的請求。所有 LLM 模型暫時不可用。",
            "model": "static_fallback",
            "tokens": 0,
            "fallback": True,
        }

    def _build_fallback_chain(self, primary: str) -> list[str]:
        """建立 fallback chain：Gemini → Ollama（若啟用）。"""
        chain = [primary]
        if self._is_gemini_model(primary):
            # 主模型是 Gemini，Ollama 啟用時加入備援
            if self.ollama_enabled:
                fb = self.default_model
                if fb not in chain:
                    chain.append(fb)
        else:
            # 主模型是 Ollama，先嘗試 Gemini
            if self.gemini_api_key:
                gemini_fb = self.gemini_model or "gemini-2.5-flash"
                if gemini_fb not in chain:
                    chain.insert(0, gemini_fb)
            if self.ollama_enabled:
                fb = self.default_model
                if fb not in chain:
                    chain.append(fb)
        return chain

    # ── Gemini API ──────────────────────────────────────────

    async def _call_gemini(
        self,
        model: str,
        prompt: str,
        system: str,
        temperature: float,
    ) -> dict[str, Any]:
        """呼叫 Gemini API。"""
        if not self.gemini_api_key:
            raise ValueError("Gemini API Key 未設定")

        contents: list[dict] = []
        if system:
            contents.append({"role": "user", "parts": [{"text": f"[System] {system}"}]})
            contents.append({"role": "model", "parts": [{"text": "understood"}]})
        contents.append({"role": "user", "parts": [{"text": prompt}]})

        url = f"{GEMINI_API_BASE}/models/{model}:generateContent?key={self.gemini_api_key}"
        payload = {
            "contents": contents,
            "generationConfig": {"temperature": temperature},
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        text = ""
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as e:
            logger.warning("Gemini 回應結構異常: %s, data=%s", e, str(data)[:200])
            # 嘗試其他可能的回應格式
            candidates = data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                for part in parts:
                    if "text" in part:
                        text = part["text"]
                        break
        tokens = data.get("usageMetadata", {}).get("totalTokenCount", 0)
        return {
            "text": text,
            "model": model,
            "tokens": tokens,
            "fallback": False,
        }

    # ── Ollama API ──────────────────────────────────────────

    async def _call_ollama(
        self,
        model: str,
        prompt: str,
        system: str,
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        """呼叫 Ollama API。"""
        url = f"{self.ollama_url}/api/generate"
        payload = {
            "model": model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        return {
            "text": data.get("response", ""),
            "model": model,
            "tokens": data.get("eval_count", 0),
            "fallback": False,
        }

    async def _call_ollama_stream(
        self,
        model: str,
        prompt: str,
        system: str,
        temperature: float,
        max_tokens: int,
        on_token: Callable[[str], Awaitable[None]] | None,
    ) -> dict[str, Any]:
        """Ollama stream=True 實作，逐行讀取 NDJSON。"""
        url = f"{self.ollama_url}/api/generate"
        payload = {
            "model": model,
            "prompt": prompt,
            "system": system,
            "stream": True,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        full_text = ""
        token_count = 0
        partial = False

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                async with client.stream("POST", url, json=payload) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        token_text = data.get("response", "")
                        if token_text:
                            full_text += token_text
                            token_count += 1
                            if on_token is not None:
                                await on_token(token_text)
                        if data.get("done", False):
                            eval_count = data.get("eval_count")
                            if eval_count is not None:
                                token_count = eval_count
                            break
            except Exception as e:
                if full_text:
                    logger.warning("串流中斷，回傳部分文字: %s", e)
                    partial = True
                else:
                    raise

        result: dict[str, Any] = {
            "text": full_text,
            "model": model,
            "tokens": token_count,
        }
        if partial:
            result["partial"] = True
        return result

    # ── 成本追蹤 ─────────────────────────────────────────────

    def _log_cost(self, result: dict[str, Any]) -> None:
        """記錄 LLM 呼叫成本至 cost_logs.jsonl（靜默失敗）。"""
        try:
            import json as _json
            from datetime import datetime, timezone
            from pathlib import Path

            cost_path = Path("./data/cost_logs.jsonl")
            cost_path.parent.mkdir(parents=True, exist_ok=True)

            model = result.get("model", "")
            tokens = result.get("tokens", 0)

            # Gemini 定價估算（gemini-2.5-flash: $0.15/1M input, $0.60/1M output）
            if "gemini" in model:
                cost_usd = tokens * 0.0000004  # 粗估平均
            else:
                cost_usd = 0.0  # Ollama 本地免費

            entry = {
                "model": model,
                "tokens": tokens,
                "cost_usd": round(cost_usd, 6),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            with open(cost_path, "a", encoding="utf-8") as f:
                f.write(_json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass  # 成本追蹤失敗不影響主流程

    # ── Wiki Context ────────────────────────────────────────

    def _load_wiki_context(self, query: str, max_pages: int = 3) -> str:
        """從 Wiki 載入相關 context 注入 LLM prompt。"""
        from pathlib import Path

        wiki_path = Path(self.wiki_dir)
        if not wiki_path.is_dir():
            return ""

        schema_path = wiki_path / "schema.md"
        schema_snippet = ""
        if schema_path.exists():
            try:
                content = schema_path.read_text(encoding="utf-8")
                schema_snippet = content[:500]
            except Exception:
                pass

        query_terms = set(query.lower().split())
        if not query_terms:
            return schema_snippet

        scored_pages: list[tuple[float, str, str]] = []
        for md_file in wiki_path.rglob("*.md"):
            if md_file.name.startswith(".") or md_file.name in ("schema.md", "index.md", "log.md"):
                continue
            if "raw" in md_file.parts:
                continue
            try:
                content = md_file.read_text(encoding="utf-8")
                content_lower = content.lower()
                score = sum(content_lower.count(t) for t in query_terms)
                if score > 0:
                    scored_pages.append((score, md_file.stem, content[:800]))
            except Exception:
                continue

        scored_pages.sort(key=lambda x: x[0], reverse=True)
        top_pages = scored_pages[:max_pages]

        if not top_pages and not schema_snippet:
            return ""

        parts = []
        if schema_snippet:
            parts.append(f"[Schema]\n{schema_snippet}")
        for _score, name, content in top_pages:
            parts.append(f"[Wiki: {name}]\n{content}")

        return "\n\n".join(parts)
