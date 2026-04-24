"""GeminiAdapter：Gemini API 整合（generate + function_call）。"""

import json
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

MODEL_TIERS = {
    "FAST": "gemini-2.5-flash",
    "BALANCE": "gemini-2.5-flash",
    "HEAVY": "gemini-2.5-pro",
}

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiAdapter:
    """Gemini API 整合，支援文字生成與 Function Calling。"""

    def __init__(
        self,
        api_key: str | None = None,
        default_model: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        self.default_model = default_model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self.timeout = timeout

    def select_model(self, tier: str = "BALANCE") -> str:
        """根據 tier 選擇模型。"""
        return MODEL_TIERS.get(tier.upper(), self.default_model)

    async def generate(
        self,
        prompt: str,
        system: str = "",
        tier: str = "BALANCE",
        temperature: float = 0.7,
    ) -> dict[str, Any]:
        """一般文字生成。"""
        model = self.select_model(tier)
        contents = []
        if system:
            contents.append({"role": "user", "parts": [{"text": f"[System] {system}"}]})
            contents.append({"role": "model", "parts": [{"text": "understood"}]})
        contents.append({"role": "user", "parts": [{"text": prompt}]})

        try:
            url = f"{GEMINI_API_BASE}/models/{model}:generateContent?key={self.api_key}"
            payload = {
                "contents": contents,
                "generationConfig": {"temperature": temperature},
            }
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()

            text = data["candidates"][0]["content"]["parts"][0]["text"]
            tokens = data.get("usageMetadata", {}).get("totalTokenCount", 0)
            return {"text": text, "model": model, "tokens": tokens}
        except Exception as e:
            logger.warning("Gemini generate 失敗: %s", e)
            return {"text": "抱歉，目前無法處理您的請求。", "model": "fallback", "tokens": 0}

    async def function_call(
        self,
        user_message: str,
        tools: list[dict],
        tier: str = "BALANCE",
    ) -> dict[str, Any]:
        """Function Calling：回傳 skill_id + params 或純文字回覆。"""
        model = self.select_model(tier)
        contents = [{"role": "user", "parts": [{"text": user_message}]}]

        # 轉換 tools 為 Gemini 格式
        gemini_tools = [{"function_declarations": tools}] if tools else []

        try:
            url = f"{GEMINI_API_BASE}/models/{model}:generateContent?key={self.api_key}"
            payload = {"contents": contents, "tools": gemini_tools}
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()

            candidate = data["candidates"][0]["content"]["parts"][0]

            if "functionCall" in candidate:
                fc = candidate["functionCall"]
                return {
                    "action": "call",
                    "skill_id": fc["name"],
                    "params": dict(fc.get("args", {})),
                }
            else:
                return {
                    "action": "reply",
                    "text": candidate.get("text", ""),
                }
        except Exception as e:
            logger.warning("Gemini function_call 失敗: %s", e)
            return {"action": "reply", "text": "抱歉，目前無法處理您的請求。"}

    def skills_to_tools(self, registry) -> list[dict]:
        """從 SkillRegistry 自動產生 tool definitions（清理 Gemini 不支援的 schema）。"""
        tools = []
        for skill in registry._skills.values():
            if skill.input_schema is None:
                continue
            td = skill.to_tool_definition()
            # 清理 Gemini 不支援的 schema 欄位
            td["parameters"] = self._clean_schema(td.get("parameters", {}))
            tools.append(td)
        return tools

    def _clean_schema(self, schema: dict) -> dict:
        """移除 Gemini API 不支援的 JSON Schema 欄位。"""
        cleaned = {}
        for k, v in schema.items():
            if k in ("title", "additionalProperties", "default", "$defs"):
                continue
            if k == "properties" and isinstance(v, dict):
                cleaned[k] = {
                    pk: self._clean_property(pv) for pk, pv in v.items()
                }
            elif isinstance(v, dict):
                cleaned[k] = self._clean_schema(v)
            else:
                cleaned[k] = v
        return cleaned

    def _clean_property(self, prop: dict) -> dict:
        """清理單一 property 的 schema。"""
        # anyOf [str, null] → 簡化為 str
        if "anyOf" in prop:
            for item in prop["anyOf"]:
                if isinstance(item, dict) and item.get("type") != "null":
                    return {"type": item["type"], "description": prop.get("description", "")}
            return {"type": "string"}
        cleaned = {}
        for k, v in prop.items():
            if k in ("title", "default", "additionalProperties"):
                continue
            if isinstance(v, dict):
                cleaned[k] = self._clean_property(v)
            else:
                cleaned[k] = v
        return cleaned
