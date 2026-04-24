"""Echo Skill：回傳輸入訊息，用於測試 Skill 系統。"""

from ark_agent_core.skills.base import BaseSkill, SkillResult, SkillType


class EchoSkill(BaseSkill):
    skill_id = "echo"
    skill_type = SkillType.PYTHON
    description = "回傳輸入訊息，用於測試 Skill 系統與 Workflow 引擎"

    async def execute(self, params: dict) -> SkillResult:
        message = params.get("message", "")
        return SkillResult(
            success=True,
            data={"message": message},
            metadata={"skill": self.skill_id},
        )
