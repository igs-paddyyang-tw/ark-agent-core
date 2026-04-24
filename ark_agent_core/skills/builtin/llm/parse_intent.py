"""Intent Parser Skill：使用 LLM 進行意圖分類。"""

import json

from ark_agent_core.llm.ollama import LLMAdapter
from ark_agent_core.skills.base import BaseSkill, SkillResult, SkillType

INTENT_SYSTEM_PROMPT = """你是一個意圖分類器。根據使用者輸入，回傳 JSON 格式的分類結果。

可用意圖：
- query_kpi: 查詢 KPI 數據
- query_revenue: 查詢營收
- query_general: 一般數據查詢
- rag_chat: 知識問答
- wiki_query: Wiki 知識查詢
- run_workflow: 執行工作流
- schedule_manage: 排程管理
- generate_report: 產出報表
- generate_doc: 產出文件
- memory_manage: 記憶管理
- system_status: 系統狀態
- unknown: 無法分類

回傳格式（僅回傳 JSON，不要其他文字）：
{"intent": "意圖名稱", "confidence": 0.0-1.0, "params": {"key": "value"}}
"""


class ParseIntentSkill(BaseSkill):
    skill_id = "llm_parse_intent"
    skill_type = SkillType.LLM
    description = "使用 LLM 進行 12 意圖分類 + 參數抽取"

    def __init__(self, llm: LLMAdapter | None = None) -> None:
        self._llm = llm or LLMAdapter(timeout=5.0)

    def validate_params(self, params: dict) -> bool:
        return "text" in params

    async def execute(self, params: dict) -> SkillResult:
        text = params["text"]

        try:
            result = await self._llm.generate(
                prompt=text,
                system=INTENT_SYSTEM_PROMPT,
                tier="FAST",
                temperature=0.1,
                max_tokens=256,
            )

            # 嘗試解析 JSON
            raw = result["text"].strip()
            # 處理可能被 markdown 包裹的 JSON
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

            parsed = json.loads(raw)
            return SkillResult(
                success=True,
                data={
                    "intent": parsed.get("intent", "unknown"),
                    "confidence": parsed.get("confidence", 0.0),
                    "params": parsed.get("params", {}),
                },
                metadata={"model": result["model"]},
            )
        except json.JSONDecodeError:
            # LLM 回傳非 JSON → 嘗試關鍵字匹配 fallback
            return SkillResult(
                success=True,
                data=self._keyword_fallback(text),
                metadata={"model": "keyword_fallback"},
            )
        except Exception as e:
            # LLM 不可用 → 關鍵字 fallback
            return SkillResult(
                success=True,
                data=self._keyword_fallback(text),
                metadata={"model": "keyword_fallback", "error": str(e)},
            )

    def _keyword_fallback(self, text: str) -> dict:
        """關鍵字匹配 fallback，LLM 不可用時使用。"""
        text_lower = text.lower()
        mappings = [
            (["kpi", "指標", "dau", "mau"], "query_kpi"),
            (["營收", "revenue", "收入"], "query_revenue"),
            (["排程", "schedule", "定時"], "schedule_manage"),
            (["報表", "report", "報告"], "generate_report"),
            (["wiki", "知識", "文件"], "wiki_query"),
            (["狀態", "status", "健康"], "system_status"),
            (["記憶", "memory", "偏好"], "memory_manage"),
            (["工作流", "workflow", "執行"], "run_workflow"),
        ]
        for keywords, intent in mappings:
            if any(kw in text_lower for kw in keywords):
                return {"intent": intent, "confidence": 0.6, "params": {}}

        return {"intent": "rag_chat", "confidence": 0.3, "params": {}}
