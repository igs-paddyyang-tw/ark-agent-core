"""HTML Chart Skill：產生 Chart.js 互動式圖表 HTML。"""

import json

from pydantic import Field

from ark_agent_core.skills.base import BaseSkill, SkillParam, SkillResult, SkillType


class HtmlChartInput(SkillParam):
    """HTML Chart 輸入參數。"""
    chart_type: str = Field(default="bar", description="圖表類型：bar/line/pie/doughnut/radar")
    title: str = Field(default="Chart", description="圖表標題")
    labels: list[str] = Field(description="X 軸標籤")
    datasets: list[dict] = Field(description="資料集（Chart.js 格式）")
    output_path: str = Field(default="", description="輸出檔案路徑（選填）")

CHART_TEMPLATE = """<!DOCTYPE html>
<html><head>
<meta charset="UTF-8">
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>body{{font-family:sans-serif;max-width:800px;margin:40px auto;}}canvas{{max-height:400px;}}</style>
</head><body>
<h2>{title}</h2>
<canvas id="chart"></canvas>
<script>
new Chart(document.getElementById('chart'), {{
  type: '{chart_type}',
  data: {{
    labels: {labels},
    datasets: {datasets}
  }},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ position: 'top' }}, title: {{ display: true, text: '{title}' }} }}
  }}
}});
</script>
</body></html>"""


class HtmlChartSkill(BaseSkill):
    skill_id = "html_chart"
    skill_type = SkillType.PYTHON
    description = "產生 Chart.js 互動式圖表 HTML（折線/柱狀/圓餅/雷達）"
    input_schema = HtmlChartInput

    def validate_params(self, params: dict) -> bool:
        return "chart_type" in params or "labels" in params or "datasets" in params

    async def execute(self, params: dict) -> SkillResult:
        chart_type = params.get("chart_type", "bar")
        title = params.get("title", "Chart")
        labels = params.get("labels", ["A", "B", "C"])
        datasets = params.get("datasets", [{"label": "Data", "data": [1, 2, 3]}])
        output_path = params.get("output_path", "")

        valid_types = {"bar", "line", "pie", "doughnut", "radar", "polarArea"}
        if chart_type not in valid_types:
            return SkillResult(success=False, error=f"Unsupported chart type: {chart_type}")

        try:
            html = CHART_TEMPLATE.format(
                title=title,
                chart_type=chart_type,
                labels=json.dumps(labels, ensure_ascii=False),
                datasets=json.dumps(datasets, ensure_ascii=False),
            )

            result_data = {"html": html, "chart_type": chart_type}

            if output_path:
                from pathlib import Path
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                Path(output_path).write_text(html, encoding="utf-8")
                result_data["output_path"] = output_path

            return SkillResult(success=True, data=result_data)
        except Exception as e:
            return SkillResult(success=False, error=f"Chart generation failed: {e}")
