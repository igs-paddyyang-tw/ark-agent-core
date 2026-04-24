"""LLM Analyze Skill：AI 數據洞察分析。"""

from pydantic import Field

from ark_agent_core.llm.ollama import LLMAdapter
from ark_agent_core.skills.base import BaseSkill, SkillParam, SkillResult, SkillType


class LLMAnalyzeInput(SkillParam):
    """LLM Analyze 輸入參數。"""
    data: str = Field(description="要分析的數據（文字或 JSON）")
    context: str = Field(default="", description="額外上下文")


ANALYZE_SYSTEM_PROMPT = """你是一位資深營運數據分析師。根據提供的數據，產出以下分析：
1. 關鍵發現（2-3 點）
2. 異常指標說明
3. 趨勢判斷
4. 行動建議（1-2 點）

使用繁體中文回答，語氣專業但易懂。"""


class LLMAnalyzeSkill(BaseSkill):
    skill_id = "llm_analyze"
    skill_type = SkillType.LLM
    description = "AI 數據洞察：KPI 異常解讀 + 趨勢分析 + 行動建議"
    input_schema = LLMAnalyzeInput

    def __init__(self, llm: LLMAdapter | None = None) -> None:
        self._llm = llm or LLMAdapter(timeout=5.0)

    def validate_params(self, params: dict) -> bool:
        return "data" in params

    async def execute(self, params: dict) -> SkillResult:
        data = params["data"]
        context = params.get("context", "")
        prompt = f"請分析以下數據：\n{data}"
        progress_cb = params.get("_progress_callback")

        try:
            if progress_cb:
                # 串流模式：逐 token 回報進度
                from ark_agent_core.conversation.progress import EventType, ProgressEvent

                async def on_token(token: str) -> None:
                    await progress_cb(ProgressEvent(
                        event_type=EventType.LLM_TOKEN, data=token,
                    ))

                result = await self._llm.generate_stream(
                    prompt=prompt, system=ANALYZE_SYSTEM_PROMPT,
                    tier="BALANCE", on_token=on_token,
                )
                await progress_cb(ProgressEvent(event_type=EventType.LLM_COMPLETE))
            else:
                # 非串流模式（向後相容）
                result = await self._llm.generate(
                    prompt=prompt, system=ANALYZE_SYSTEM_PROMPT,
                    tier="BALANCE", context=context,
                )
            return SkillResult(
                success=True,
                data={"analysis": result["text"]},
                metadata={"model": result["model"], "tokens": result["tokens"]},
            )
        except Exception as e:
            return SkillResult(success=False, error=f"LLM analyze failed: {e}")
