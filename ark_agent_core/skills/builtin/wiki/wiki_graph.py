"""Wiki Graph Skill：從 [[wikilink]] 建立知識圖譜分析。"""

import re
from pathlib import Path

from ark_agent_core.skills.base import BaseSkill, SkillResult, SkillType


class WikiGraphSkill(BaseSkill):
    skill_id = "wiki_graph"
    skill_type = SkillType.PYTHON
    description = "知識圖譜分析：[[wikilink]] → 節點/邊 + hub/orphan 偵測"

    def __init__(self, wiki_dir: str = "./knowledge") -> None:
        self.wiki_dir = Path(wiki_dir)

    async def execute(self, params: dict) -> SkillResult:
        try:
            nodes, edges = self._build_graph()

            # 計算入度/出度
            in_degree: dict[str, int] = {n: 0 for n in nodes}
            out_degree: dict[str, int] = {n: 0 for n in nodes}
            for src, tgt in edges:
                out_degree[src] = out_degree.get(src, 0) + 1
                if tgt in in_degree:
                    in_degree[tgt] = in_degree.get(tgt, 0) + 1

            # Hub 節點（入度最高）
            hubs = sorted(in_degree.items(), key=lambda x: x[1], reverse=True)[:5]

            # 孤立節點（入度 = 0 且出度 = 0，或只有出度）
            orphans = [n for n in nodes if in_degree.get(n, 0) == 0]

            return SkillResult(
                success=True,
                data={
                    "node_count": len(nodes),
                    "edge_count": len(edges),
                    "hubs": [{"page": h[0], "in_degree": h[1]} for h in hubs],
                    "orphans": orphans,
                    "orphan_count": len(orphans),
                    "nodes": list(nodes),
                    "edges": [{"source": s, "target": t} for s, t in edges],
                },
            )
        except Exception as e:
            return SkillResult(success=False, error=f"Wiki graph failed: {e}")

    def _build_graph(self) -> tuple[set[str], list[tuple[str, str]]]:
        """掃描所有 Wiki 頁面，提取 [[wikilink]] 建立圖。"""
        nodes: set[str] = set()
        edges: list[tuple[str, str]] = []

        if not self.wiki_dir.is_dir():
            return nodes, edges

        for md_file in self.wiki_dir.rglob("*.md"):
            if md_file.name.startswith("."):
                continue
            if md_file.name in ("schema.md", "index.md", "log.md"):
                continue
            if "raw" in md_file.parts:
                continue

            page_name = md_file.stem
            nodes.add(page_name)

            try:
                content = md_file.read_text(encoding="utf-8")
            except Exception:
                continue

            # 提取 [[wikilink]]
            links = re.findall(r"\[\[([^\]]+)\]\]", content)
            for link in links:
                target = link.strip()
                if target and target != page_name:
                    edges.append((page_name, target))
                    nodes.add(target)  # 目標可能還沒有頁面

        return nodes, edges
