"""Template Render Skill：使用 Jinja2 渲染模板字串。"""

from jinja2 import Template
from pydantic import Field

from ark_agent_core.skills.base import BaseSkill, SkillParam, SkillResult, SkillType


class TemplateRenderInput(SkillParam):
    """Template Render 輸入參數。"""
    template: str = Field(description="Jinja2 模板字串")
    context: dict = Field(default_factory=dict, description="模板變數")


class TemplateRenderSkill(BaseSkill):
    skill_id = "template_render"
    skill_type = SkillType.PYTHON
    description = "使用 Jinja2 渲染模板字串"
    input_schema = TemplateRenderInput

    def validate_params(self, params: dict) -> bool:
        return "template" in params

    async def execute(self, params: dict) -> SkillResult:
        template_str = params["template"]
        context = params.get("context", {})
        try:
            rendered = Template(template_str).render(**context)
            return SkillResult(success=True, data={"rendered": rendered})
        except Exception as e:
            return SkillResult(success=False, error=f"Template render failed: {e}")
