# 如何開發自訂 Skill

## 基本結構

Skill 繼承 `BaseSkill`，放入 `src/skills/internal/` 即會自動註冊。

```python
# src/skills/internal/my_skill.py

from pydantic import Field
from ark_agent_core.skills.base import BaseSkill, SkillParam, SkillResult, SkillType


class MySkillInput(SkillParam):
    """輸入參數定義。"""
    name: str = Field(description="使用者名稱")
    greeting: str = Field(default="Hello", description="問候語")


class MySkill(BaseSkill):
    skill_id = "my_skill"
    skill_type = SkillType.PYTHON
    description = "客製化問候 Skill"
    input_schema = MySkillInput

    async def execute(self, params: dict) -> SkillResult:
        try:
            name = params.get("name", "World")
            greeting = params.get("greeting", "Hello")
            return SkillResult(
                success=True,
                data={"message": f"{greeting}, {name}!"},
            )
        except Exception as e:
            return SkillResult(success=False, error=str(e))
```

## 三個關鍵設計

### 1. `input_schema` 必要

有 `input_schema` 才能被 Gemini Function Calling 自動觸發。

### 2. 錯誤捕獲

```python
try:
    # ...
    return SkillResult(success=True, data={...})
except Exception as e:
    return SkillResult(success=False, error=str(e))
```

不要讓例外往上拋，Skill 負責自己處理。

### 3. `description` 要清楚

Gemini 會看 description 判斷要不要呼叫這個 Skill，描述越清楚觸發越準確。

好的 description：
> 「查詢玩家資料庫。預設查詢 VIP>=5 大客的消費狀況（按 LTV 排序 Top 10）。不需要額外參數即可直接呼叫。」

不好的 description：
> 「查詢資料庫」

## 三種 Skill 類型

```python
skill_type = SkillType.PYTHON   # 純 Python 邏輯
skill_type = SkillType.LLM      # 呼叫 LLM（摘要、分析、問答）
skill_type = SkillType.MCP      # 外部 MCP Server
```

## 測試

```python
# tests/test_my_skill.py

import pytest
from src.skills.internal.my_skill import MySkill


@pytest.mark.asyncio
async def test_my_skill_basic():
    skill = MySkill()
    result = await skill.execute({"name": "Paddy"})
    assert result.success
    assert "Paddy" in result.data["message"]
```

## 觸發方式

1. **指令模式**：`/my_skill name=Paddy greeting=Hi`
2. **自然語言（Gemini FC）**：「幫我問候 Paddy」
3. **Workflow**：

   ```yaml
   - id: greet
     type: skill
     skill: my_skill
     params:
       name: "Paddy"
     output: result
   ```

4. **程式碼**：

   ```python
   result = await registry.invoke("my_skill", {"name": "Paddy"})
   ```

## 下一步

- [Workflow 建立指引](./workflow-guide.md)
- [Wiki 知識庫整合](./wiki-integration.md)
