"""Skill 統一介面：BaseSkill + SkillParam + SkillResult + SkillType。

OpenClaw 借鑑升級：嚴格 Schema Typed Interface、自動 tool definition 生成、語意版本號。
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class SkillType(Enum):
    """Skill 類型列舉。"""

    PYTHON = "python"
    LLM = "llm"
    MCP = "mcp"


class SkillResult(BaseModel):
    """Skill 執行結果。"""

    success: bool
    data: Any = None
    error: str | None = None
    metadata: dict = Field(default_factory=dict)


class SkillParam(BaseModel):
    """Skill 參數基底（所有 input schema 繼承此類別）。"""

    model_config = ConfigDict(extra="forbid")


class BaseSkill(ABC):
    """所有 Skill 的抽象基底類別。

    借鑑 OpenClaw Tool Interface 標準化設計，支援：
    - 嚴格 Pydantic Schema（input_schema / output_schema）
    - 自動 validate_params（無 schema 時向後相容）
    - 自動產生 Gemini Function Calling tool definition
    - 語意版本號追蹤
    """

    skill_id: str
    skill_type: SkillType
    description: str = ""
    version: str = "1.0.0"

    # 嚴格 Schema（OpenClaw Tool Interface 標準化）
    input_schema: type[SkillParam] | None = None
    output_schema: type[BaseModel] | None = None

    @abstractmethod
    async def execute(self, params: dict) -> SkillResult:
        """執行 Skill，回傳 SkillResult。子類別必須實作。"""

    def validate_params(self, params: dict) -> bool:
        """自動以 input_schema 驗證，無 schema 則回傳 True（向後相容）。"""
        if self.input_schema is None:
            return True
        try:
            self.input_schema(**params)
            return True
        except ValidationError:
            return False

    def to_tool_definition(self) -> dict:
        """自動從 input_schema 產生 Gemini Function Calling tool definition。"""
        if self.input_schema is None:
            return {
                "name": self.skill_id,
                "description": self.description,
                "parameters": {},
            }
        schema = self.input_schema.model_json_schema()
        return {
            "name": self.skill_id,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": schema.get("properties", {}),
                "required": schema.get("required", []),
            },
        }

    def to_dict(self) -> dict:
        """序列化為字典，供 API 回傳。"""
        return {
            "skill_id": self.skill_id,
            "skill_type": self.skill_type.value,
            "description": self.description,
            "version": self.version,
            "has_schema": self.input_schema is not None,
        }
