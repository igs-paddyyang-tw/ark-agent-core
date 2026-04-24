"""LLM QA Skill：知識問答（Wiki + RAG 增強）。"""

from pydantic import Field

from ark_agent_core.llm.ollama import LLMAdapter
from ark_agent_core.skills.base import BaseSkill, SkillParam, SkillResult, SkillType


class LLMQAInput(SkillParam):
    """LLM QA 輸入參數。"""
    question: str = Field(description="使用者問題")
    context: str = Field(default="", description="額外上下文")


QA_SYSTEM_PROMPT = """你是一位營運智能助理。根據提供的 Context 回答使用者問題。
規則：
1. 優先使用 Context 中的資訊回答
2. 如果 Context 不足，說明你不確定並提供最佳推測
3. 附帶引用來源（如果有）
4. 使用繁體中文回答"""


class LLMQASkill(BaseSkill):
    skill_id = "llm_qa"
    skill_type = SkillType.LLM
    description = "知識問答：Wiki + RAG 增強的 Q&A"
    input_schema = LLMQAInput

    def __init__(self, llm: LLMAdapter | None = None) -> None:
        self._llm = llm or LLMAdapter(timeout=5.0)

    def validate_params(self, params: dict) -> bool:
        return "question" in params

    async def execute(self, params: dict) -> SkillResult:
        question = params["question"]
        context = params.get("context", "")
        sources = params.get("sources", [])
        progress_cb = params.get("_progress_callback")

        prompt = f"問題：{question}"
        if sources:
            source_text = "\n".join(f"- {s}" for s in sources)
            context = f"{context}\n\n來源：\n{source_text}" if context else f"來源：\n{source_text}"

        try:
            if progress_cb:
                from ark_agent_core.conversation.progress import EventType, ProgressEvent

                async def on_token(token: str) -> None:
                    await progress_cb(ProgressEvent(
                        event_type=EventType.LLM_TOKEN, data=token,
                    ))

                result = await self._llm.generate_stream(
                    prompt=prompt, system=QA_SYSTEM_PROMPT,
                    tier="BALANCE", on_token=on_token,
                )
                await progress_cb(ProgressEvent(event_type=EventType.LLM_COMPLETE))
            else:
                result = await self._llm.generate(
                    prompt=prompt, system=QA_SYSTEM_PROMPT,
                    tier="BALANCE", context=context,
                )
            return SkillResult(
                success=True,
                data={"answer": result["text"], "sources": sources},
                metadata={"model": result["model"], "tokens": result["tokens"]},
            )
        except Exception as e:
            return SkillResult(success=False, error=f"LLM QA failed: {e}")
