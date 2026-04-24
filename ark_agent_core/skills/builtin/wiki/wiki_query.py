"""Wiki Query Skill：查詢 Wiki 知識庫。"""

from pathlib import Path

from ark_agent_core.skills.base import BaseSkill, SkillResult, SkillType


class WikiQuerySkill(BaseSkill):
    skill_id = "wiki_query"
    skill_type = SkillType.PYTHON
    description = "查詢 LLM Wiki 知識庫：讀取 index.md 定位 → 頁面內容搜尋 → 回傳結果"

    def __init__(self, wiki_dir: str = "./knowledge") -> None:
        self.wiki_dir = Path(wiki_dir)

    def validate_params(self, params: dict) -> bool:
        return "query" in params

    async def execute(self, params: dict) -> SkillResult:
        query = params["query"].lower()
        max_results = params.get("max_results", 5)

        try:
            results = self._search(query, max_results)
            return SkillResult(
                success=True,
                data={
                    "results": results,
                    "count": len(results),
                    "query": params["query"],
                },
            )
        except Exception as e:
            return SkillResult(success=False, error=f"Wiki query failed: {e}")

    def _search(self, query: str, max_results: int) -> list[dict]:
        """搜尋 Wiki 頁面，回傳匹配結果。"""
        results = []
        if not self.wiki_dir.is_dir():
            return results

        for md_file in self.wiki_dir.rglob("*.md"):
            if md_file.name.startswith("."):
                continue

            try:
                content = md_file.read_text(encoding="utf-8")
            except Exception:
                continue

            # 標題匹配（權重高）
            title = ""
            for line in content.split("\n"):
                if line.startswith("# "):
                    title = line[2:].strip()
                    break

            score = 0
            query_terms = query.split()

            # 標題匹配
            title_lower = title.lower()
            for term in query_terms:
                if term in title_lower:
                    score += 10

            # 檔名匹配
            name_lower = md_file.stem.lower()
            for term in query_terms:
                if term in name_lower:
                    score += 5

            # 內容匹配
            content_lower = content.lower()
            for term in query_terms:
                count = content_lower.count(term)
                score += min(count, 5)  # cap per term

            if score > 0:
                rel_path = md_file.relative_to(self.wiki_dir).as_posix()
                # 取摘要（前 200 字）
                summary = content[:200].replace("\n", " ").strip()
                results.append({
                    "path": rel_path,
                    "title": title or md_file.stem,
                    "score": score,
                    "summary": summary,
                })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:max_results]
