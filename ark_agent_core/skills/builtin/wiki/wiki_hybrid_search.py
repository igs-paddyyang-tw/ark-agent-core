"""Wiki Hybrid Search Skill：三路搜尋 + RRF 融合。

路線 1：Wiki index.md 定位 → 頁面內容搜尋（wiki_query）
路線 2：BM25 關鍵字搜尋（rank_bm25，如果可用）
路線 3：預留 ChromaDB 向量搜尋介面

三路結果透過 Reciprocal Rank Fusion (RRF) 融合排序。
"""

import math
from pathlib import Path

from ark_agent_core.skills.base import BaseSkill, SkillResult, SkillType
from ark_agent_core.skills.builtin.wiki.wiki_query import WikiQuerySkill


class WikiHybridSearchSkill(BaseSkill):
    skill_id = "wiki_hybrid_search"
    skill_type = SkillType.PYTHON
    description = "三路混合搜尋：Wiki 全文 + BM25 關鍵字 + RRF 融合"

    def __init__(self, wiki_dir: str = "./knowledge") -> None:
        self.wiki_dir = Path(wiki_dir)
        self._wiki_query = WikiQuerySkill(wiki_dir=wiki_dir)

    def validate_params(self, params: dict) -> bool:
        return "query" in params

    async def execute(self, params: dict) -> SkillResult:
        query = params["query"]
        top_k = params.get("top_k", 5)
        rrf_k = params.get("rrf_k", 60)

        try:
            # 路線 1：Wiki 全文搜尋
            wiki_result = await self._wiki_query.execute({"query": query, "max_results": top_k * 2})
            wiki_hits = wiki_result.data.get("results", []) if wiki_result.success else []

            # 路線 2：BM25 關鍵字搜尋
            bm25_hits = self._bm25_search(query, top_k * 2)

            # RRF 融合
            fused = self._rrf_fuse([wiki_hits, bm25_hits], rrf_k)

            # 取 top_k
            results = fused[:top_k]

            return SkillResult(
                success=True,
                data={
                    "results": results,
                    "count": len(results),
                    "query": query,
                    "sources": {
                        "wiki_hits": len(wiki_hits),
                        "bm25_hits": len(bm25_hits),
                    },
                },
            )
        except Exception as e:
            return SkillResult(success=False, error=f"Hybrid search failed: {e}")

    def _bm25_search(self, query: str, max_results: int) -> list[dict]:
        """簡易 BM25 搜尋（不依賴 rank_bm25 套件，用 TF-IDF 近似）。"""
        if not self.wiki_dir.is_dir():
            return []

        query_terms = set(query.lower().split())
        if not query_terms:
            return []

        results = []
        for md_file in self.wiki_dir.rglob("*.md"):
            if md_file.name.startswith(".") or md_file.name in ("schema.md", "index.md", "log.md"):
                continue
            if "raw" in md_file.parts:
                continue

            try:
                content = md_file.read_text(encoding="utf-8").lower()
            except Exception:
                continue

            # 簡易 BM25 評分：term frequency * inverse document frequency 近似
            words = content.split()
            doc_len = len(words)
            if doc_len == 0:
                continue

            score = 0.0
            for term in query_terms:
                tf = content.count(term)
                if tf > 0:
                    # BM25 公式簡化：tf / (tf + 1.2 * (1 - 0.75 + 0.75 * doc_len / 500))
                    k1 = 1.2
                    b = 0.75
                    avg_dl = 500
                    norm_tf = tf / (tf + k1 * (1 - b + b * doc_len / avg_dl))
                    score += norm_tf

            if score > 0:
                title = ""
                for line in content.split("\n"):
                    if line.startswith("# "):
                        title = line[2:].strip()
                        break

                rel_path = md_file.relative_to(self.wiki_dir).as_posix()
                results.append({
                    "path": rel_path,
                    "title": title or md_file.stem,
                    "score": round(score, 4),
                    "summary": content[:200].replace("\n", " ").strip(),
                })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:max_results]

    def _rrf_fuse(self, result_lists: list[list[dict]], k: int = 60) -> list[dict]:
        """Reciprocal Rank Fusion：多路結果融合排序。"""
        scores: dict[str, float] = {}
        items: dict[str, dict] = {}

        for result_list in result_lists:
            for rank, item in enumerate(result_list):
                path = item.get("path", "")
                if not path:
                    continue
                rrf_score = 1.0 / (k + rank + 1)
                scores[path] = scores.get(path, 0) + rrf_score
                if path not in items:
                    items[path] = item

        # 按 RRF 分數排序
        sorted_paths = sorted(scores.keys(), key=lambda p: scores[p], reverse=True)
        fused = []
        for path in sorted_paths:
            item = items[path].copy()
            item["rrf_score"] = round(scores[path], 6)
            fused.append(item)

        return fused
