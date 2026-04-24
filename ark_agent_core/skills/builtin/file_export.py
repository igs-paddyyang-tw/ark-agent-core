"""File Export Skill：將資料匯出為 Markdown / CSV / JSON 檔案。"""

import csv
import io
import json
from pathlib import Path

from ark_agent_core.skills.base import BaseSkill, SkillResult, SkillType


class FileExportSkill(BaseSkill):
    skill_id = "file_export"
    skill_type = SkillType.PYTHON
    description = "將資料匯出為 Markdown / CSV / JSON 檔案"

    def validate_params(self, params: dict) -> bool:
        return "format" in params and "content" in params

    async def execute(self, params: dict) -> SkillResult:
        fmt = params["format"]
        content = params["content"]
        output_path = params.get("output_path", "")

        try:
            if fmt == "markdown":
                text = self._to_markdown(content)
            elif fmt == "csv":
                text = self._to_csv(content)
            elif fmt == "json":
                text = json.dumps(content, ensure_ascii=False, indent=2)
            else:
                return SkillResult(success=False, error=f"Unsupported format: {fmt}")

            result_data = {"text": text, "format": fmt}

            if output_path:
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                Path(output_path).write_text(text, encoding="utf-8")
                result_data["output_path"] = output_path

            return SkillResult(success=True, data=result_data)
        except Exception as e:
            return SkillResult(success=False, error=f"Export failed: {e}")

    def _to_markdown(self, content: dict | list | str) -> str:
        """將資料轉為 Markdown 表格或文字。"""
        if isinstance(content, str):
            return content

        if isinstance(content, dict):
            title = content.get("title", "Report")
            rows = content.get("rows", [])
        elif isinstance(content, list):
            title = "Report"
            rows = content
        else:
            return str(content)

        lines = [f"# {title}", ""]

        if rows and isinstance(rows[0], dict):
            headers = list(rows[0].keys())
            lines.append("| " + " | ".join(headers) + " |")
            lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
            for row in rows:
                vals = [str(row.get(h, "")) for h in headers]
                lines.append("| " + " | ".join(vals) + " |")

        return "\n".join(lines)

    def _to_csv(self, content: dict | list) -> str:
        """將資料轉為 CSV 字串。"""
        if isinstance(content, dict):
            rows = content.get("rows", [])
        elif isinstance(content, list):
            rows = content
        else:
            return ""

        if not rows:
            return ""

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
        return output.getvalue()
