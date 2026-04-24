"""Wiki Template Skill：頁面模板管理。"""

from datetime import datetime, timezone

from ark_agent_core.skills.base import BaseSkill, SkillResult, SkillType

TEMPLATES = {
    "entity": """---
tags: [entity]
sources: [{source}]
created: {date}
updated: {date}
---

# {title}

{title} 的概述（2-3 句話）。

## 基本資訊

_待補充_

## 相關連結

- [[相關頁面]]

## 來源

- 來自 `raw/{source}`
""",
    "concept": """---
tags: [concept]
sources: [{source}]
created: {date}
updated: {date}
---

# {title}

{title} 的定義與說明。

## 定義

_待補充_

## 規則

_待補充_

## 相關連結

- [[相關頁面]]

## 來源

- 來自 `raw/{source}`
""",
    "source": """---
tags: [source-summary]
sources: [{source}]
created: {date}
updated: {date}
---

# {title}

原始文件 `{source}` 的結構化摘要。

## 關鍵要點

_待補充_

## 詳細內容

_待補充_

## 相關連結

- [[相關頁面]]

## 來源

- 來自 `raw/{source}`
""",
}


class WikiTemplateSkill(BaseSkill):
    skill_id = "wiki_template"
    skill_type = SkillType.PYTHON
    description = "Wiki 頁面模板管理：entity / concept / source 三種模板"

    async def execute(self, params: dict) -> SkillResult:
        action = params.get("action", "list")

        if action == "list":
            return SkillResult(success=True, data={"templates": list(TEMPLATES.keys())})

        elif action == "render":
            template_type = params.get("type", "entity")
            title = params.get("title", "Untitled")
            source = params.get("source", "unknown")

            template = TEMPLATES.get(template_type)
            if not template:
                return SkillResult(success=False, error=f"Unknown template: {template_type}")

            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            rendered = template.format(title=title, source=source, date=date)
            return SkillResult(success=True, data={"rendered": rendered, "type": template_type})

        else:
            return SkillResult(success=False, error=f"Unknown action: {action}")
