"""LLM Summarize Skill：文本摘要。"""

from pydantic import Field

from ark_agent_core.llm.ollama import LLMAdapter
from ark_agent_core.skills.base import BaseSkill, SkillParam, SkillResult, SkillType


class LLMSummarizeInput(SkillParam):
    """LLM Summarize 輸入參數。"""
    content: str = Field(description="要摘要的文本內容")
    max_length: int = Field(default=500, description="摘要最大字數")


SUMMARIZE_SYSTEM_PROMPT = """你是一位專業的文件摘要助手。請將以下內容精簡摘要，保留關鍵資訊。
使用繁體中文，以條列式呈現重點。"""


class LLMSummarizeSkill(BaseSkill):
    skill_id = "llm_summarize"
    skill_type = SkillType.LLM
    description = "文本摘要：長文檔快速摘要"
    input_schema = LLMSummarizeInput

    def __init__(self, llm: LLMAdapter | None = None) -> None:
        self._llm = llm or LLMAdapter(timeout=5.0)

    def validate_params(self, params: dict) -> bool:
        return "content" in params

    async def execute(self, params: dict) -> SkillResult:
        content = params["content"]
        max_length = params.get("max_length", 500)
        progress_cb = params.get("_progress_callback")

        prompt = f"請摘要以下內容（不超過 {max_length} 字）：\n\n{content}"

        try:
            if progress_cb:
                from ark_agent_core.conversation.progress import EventType, ProgressEvent

                async def on_token(token: str) -> None:
                    await progress_cb(ProgressEvent(
                        event_type=EventType.LLM_TOKEN, data=token,
                    ))

                result = await self._llm.generate_stream(
                    prompt=prompt, system=SUMMARIZE_SYSTEM_PROMPT,
                    tier="FAST", on_token=on_token, max_tokens=max_length * 2,
                )
                await progress_cb(ProgressEvent(event_type=EventType.LLM_COMPLETE))
            else:
                result = await self._llm.generate(
                    prompt=prompt, system=SUMMARIZE_SYSTEM_PROMPT,
                    tier="FAST", max_tokens=max_length * 2,
                )
            return SkillResult(
                success=True,
                data={"summary": result["text"]},
                metadata={"model": result["model"], "tokens": result["tokens"]},
            )
        except Exception as e:
            return SkillResult(success=False, error=f"LLM summarize failed: {e}")
