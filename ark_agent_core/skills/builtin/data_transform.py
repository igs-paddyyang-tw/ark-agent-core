"""Data Transform Skill：資料轉換與計算（ETL Pipeline）。"""

from typing import Any

from pydantic import Field

from ark_agent_core.skills.base import BaseSkill, SkillParam, SkillResult, SkillType


class DataTransformInput(SkillParam):
    """Data Transform 輸入參數。"""
    operation: str = Field(description="操作類型：compare / aggregate / filter")
    data: list[dict] = Field(default_factory=list, description="輸入資料陣列")
    field: str = Field(default="", description="目標欄位名稱")


class DataTransformSkill(BaseSkill):
    skill_id = "data_transform"
    skill_type = SkillType.PYTHON
    description = "資料轉換計算：compare / aggregate / filter"
    input_schema = DataTransformInput

    def validate_params(self, params: dict) -> bool:
        return "operation" in params

    async def execute(self, params: dict) -> SkillResult:
        operation = params["operation"]
        data = params.get("data", [])

        try:
            if operation == "compare":
                result = self._compare(params)
            elif operation == "aggregate":
                result = self._aggregate(data, params)
            elif operation == "filter":
                result = self._filter(data, params)
            else:
                return SkillResult(success=False, error=f"Unknown operation: {operation}")

            return SkillResult(success=True, data=result)
        except Exception as e:
            return SkillResult(success=False, error=f"Transform failed: {e}")

    def _compare(self, params: dict) -> dict:
        """比較 current 與 previous 資料集，計算 delta。"""
        current = params.get("current", {})
        previous = params.get("previous", {})
        deltas = []

        for key in current:
            cur_val = current[key]
            prev_val = previous.get(key, 0)
            if isinstance(cur_val, (int, float)) and isinstance(prev_val, (int, float)):
                change = cur_val - prev_val
                change_pct = (change / prev_val * 100) if prev_val != 0 else 0
                deltas.append({
                    "metric": key,
                    "current": cur_val,
                    "previous": prev_val,
                    "change": round(change, 2),
                    "change_pct": round(change_pct, 2),
                })

        return {"deltas": deltas}

    def _aggregate(self, data: list[dict], params: dict) -> dict:
        """聚合計算：sum / avg / count / min / max。"""
        field = params.get("field", "")
        agg_type = params.get("agg_type", "sum")
        values = [row[field] for row in data if field in row and isinstance(row[field], (int, float))]

        if not values:
            return {"result": 0, "count": 0}

        if agg_type == "sum":
            result = sum(values)
        elif agg_type == "avg":
            result = sum(values) / len(values)
        elif agg_type == "count":
            result = len(values)
        elif agg_type == "min":
            result = min(values)
        elif agg_type == "max":
            result = max(values)
        else:
            result = sum(values)

        return {"result": round(result, 2), "count": len(values), "agg_type": agg_type}

    def _filter(self, data: list[dict], params: dict) -> dict:
        """篩選資料：field op value。"""
        field = params.get("field", "")
        op = params.get("op", "eq")
        value = params.get("value")

        ops = {
            "eq": lambda a, b: a == b,
            "ne": lambda a, b: a != b,
            "gt": lambda a, b: a > b,
            "gte": lambda a, b: a >= b,
            "lt": lambda a, b: a < b,
            "lte": lambda a, b: a <= b,
        }
        op_fn = ops.get(op, ops["eq"])
        filtered = [row for row in data if field in row and op_fn(row[field], value)]
        return {"rows": filtered, "count": len(filtered)}
