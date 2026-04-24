"""Wiki Schema Skill：schema.md 讀取與驗證。"""

from pathlib import Path

from ark_agent_core.skills.base import BaseSkill, SkillResult, SkillType

REQUIRED_SECTIONS = ["架構", "頁面", "操作", "品質"]


class WikiSchemaSkill(BaseSkill):
    skill_id = "wiki_schema"
    skill_type = SkillType.PYTHON
    description = "schema.md Schema 讀取、驗證、健康檢查"

    def __init__(self, wiki_dir: str = "./knowledge") -> None:
        self.wiki_dir = Path(wiki_dir)

    async def execute(self, params: dict) -> SkillResult:
        action = params.get("action", "read")
        if action == "read":
            return self._read()
        elif action == "validate":
            return self._validate()
        else:
            return SkillResult(success=False, error=f"Unknown action: {action}")

    def _read(self) -> SkillResult:
        """讀取 schema.md — 先找根目錄，再搜尋子專案。"""
        # 先找根目錄
        schema_path = self.wiki_dir / "schema.md"
        if schema_path.exists():
            content = schema_path.read_text(encoding="utf-8")
            return SkillResult(success=True, data={"content": content, "path": str(schema_path)})

        # 搜尋子專案的 schema.md
        schemas = []
        for sub_dir in sorted(self.wiki_dir.iterdir()):
            if sub_dir.is_dir():
                sub_schema = sub_dir / "schema.md"
                if sub_schema.exists():
                    schemas.append({
                        "project": sub_dir.name,
                        "path": str(sub_schema),
                        "content": sub_schema.read_text(encoding="utf-8"),
                    })

        if schemas:
            return SkillResult(success=True, data={"schemas": schemas, "count": len(schemas)})

        return SkillResult(success=False, error="schema.md not found in any knowledge project")

    def _validate(self) -> SkillResult:
        """驗證 schema.md — 搜尋根目錄和子專案。"""
        # 收集所有 schema.md
        schema_files: list[Path] = []
        root_schema = self.wiki_dir / "schema.md"
        if root_schema.exists():
            schema_files.append(root_schema)
        for sub_dir in sorted(self.wiki_dir.iterdir()):
            if sub_dir.is_dir():
                sub_schema = sub_dir / "schema.md"
                if sub_schema.exists():
                    schema_files.append(sub_schema)

        if not schema_files:
            return SkillResult(success=False, error="schema.md not found in any knowledge project")

        results = []
        for schema_path in schema_files:
            content = schema_path.read_text(encoding="utf-8")
            issues = []
            if not content.startswith("# "):
                issues.append("缺少一級標題")
            for section in REQUIRED_SECTIONS:
                if section not in content:
                    issues.append(f"缺少必要區塊關鍵字：{section}")
            if len(content) < 200:
                issues.append("Schema 內容過短（< 200 字元）")
            results.append({
                "path": str(schema_path),
                "valid": len(issues) == 0,
                "issues": issues,
                "char_count": len(content),
            })

        all_valid = all(r["valid"] for r in results)
        return SkillResult(success=True, data={"valid": all_valid, "results": results})
