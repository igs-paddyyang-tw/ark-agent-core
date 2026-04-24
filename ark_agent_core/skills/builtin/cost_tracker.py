"""Cost Tracker Skill：LLM 成本追蹤。"""

import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import Field

from ark_agent_core.skills.base import BaseSkill, SkillParam, SkillResult, SkillType


class CostTrackerInput(SkillParam):
    """Cost Tracker 輸入參數。"""
    action: str = Field(default="log", description="操作：log（記錄）/ report（報告）")
    model: str = Field(default="", description="LLM 模型名稱")
    input_tokens: int = Field(default=0, description="輸入 Token 數")
    output_tokens: int = Field(default=0, description="輸出 Token 數")


class CostTrackerSkill(BaseSkill):
    skill_id = "cost_tracker"
    skill_type = SkillType.PYTHON
    description = "LLM 成本追蹤：Token 用量 + 費用統計"
    input_schema = CostTrackerInput

    def __init__(self, data_dir: str = "./data") -> None:
        self.cost_path = Path(data_dir) / "cost_logs.jsonl"

    async def execute(self, params: dict) -> SkillResult:
        action = params.get("action", "log")

        if action == "log":
            return await self._log_cost(params)
        elif action == "report":
            return await self._report(params)
        else:
            return SkillResult(success=False, error=f"Unknown action: {action}")

    async def _log_cost(self, params: dict) -> SkillResult:
        entry = {
            "run_id": params.get("run_id", ""),
            "skill_id": params.get("skill_id", ""),
            "model": params.get("model", ""),
            "input_tokens": params.get("input_tokens", 0),
            "output_tokens": params.get("output_tokens", 0),
            "cost_usd": params.get("cost_usd", 0.0),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            self.cost_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cost_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            return SkillResult(success=True, data=entry)
        except Exception as e:
            return SkillResult(success=False, error=f"Cost log failed: {e}")

    async def _report(self, params: dict) -> SkillResult:
        if not self.cost_path.exists():
            return SkillResult(success=True, data={"total_cost": 0, "total_tokens": 0, "entries": 0})

        total_cost = 0.0
        total_input = 0
        total_output = 0
        count = 0
        try:
            with open(self.cost_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    entry = json.loads(line)
                    total_cost += entry.get("cost_usd", 0)
                    total_input += entry.get("input_tokens", 0)
                    total_output += entry.get("output_tokens", 0)
                    count += 1
            return SkillResult(success=True, data={
                "total_cost_usd": round(total_cost, 4),
                "total_input_tokens": total_input,
                "total_output_tokens": total_output,
                "entries": count,
            })
        except Exception as e:
            return SkillResult(success=False, error=f"Cost report failed: {e}")
