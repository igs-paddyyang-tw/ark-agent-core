"""Wiki RAG Bridge Skill：Wiki 頁面 → 文字 chunks，供向量化使用。

此 Skill 將 Wiki 頁面拆分為 chunks 並產出結構化資料，
可供 ChromaDB 或其他向量 DB 索引。不直接依賴 ChromaDB。
"""

from pathlib import Path

from ark_agent_core.skills.base import BaseSkill, SkillResult, SkillType


class WikiRagBridgeSkill(BaseSkill):
    skill_id = "wiki_rag_bridge"
    skill_type = SkillType.PYTHON
    description = "Wiki ↔ RAG 橋接：將 Wiki 頁面拆分為 chunks 供向量化索引"

    def __init__(self, wiki_dir: str = "./knowledge") -> None:
        self.wiki_dir = Path(wiki_dir)

    async def execute(self, params: dict) -> SkillResult:
        action = params.get("action", "extract")
        chunk_size = params.get("chunk_size", 500)
        overlap = params.get("overlap", 50)

        if action == "extract":
            return self._extract_chunks(chunk_size, overlap)
        elif action == "stats":
            return self._stats()
        else:
            return SkillResult(success=False, error=f"Unknown action: {action}")

    def _extract_chunks(self, chunk_size: int, overlap: int) -> SkillResult:
        """從所有 Wiki 頁面提取 text chunks。"""
        all_chunks = []

        for md_file in self._wiki_files():
            try:
                content = md_file.read_text(encoding="utf-8")
            except Exception:
                continue

            # 移除 frontmatter
            if content.startswith("---"):
                end = content.find("---", 3)
                if end > 0:
                    content = content[end + 3:].strip()

            rel_path = md_file.relative_to(self.wiki_dir).as_posix()
            title = md_file.stem

            # 按段落拆分，再合併到 chunk_size
            paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
            current_chunk = ""

            for para in paragraphs:
                if len(current_chunk) + len(para) > chunk_size and current_chunk:
                    all_chunks.append({
                        "text": current_chunk.strip(),
                        "source": rel_path,
                        "title": title,
                    })
                    # overlap：保留尾部
                    current_chunk = current_chunk[-overlap:] + "\n\n" + para if overlap else para
                else:
                    current_chunk = current_chunk + "\n\n" + para if current_chunk else para

            if current_chunk.strip():
                all_chunks.append({
                    "text": current_chunk.strip(),
                    "source": rel_path,
                    "title": title,
                })

        return SkillResult(success=True, data={
            "chunks": all_chunks,
            "chunk_count": len(all_chunks),
        })

    def _stats(self) -> SkillResult:
        """Wiki 頁面統計。"""
        files = list(self._wiki_files())
        total_chars = 0
        for f in files:
            try:
                total_chars += len(f.read_text(encoding="utf-8"))
            except Exception:
                pass

        return SkillResult(success=True, data={
            "page_count": len(files),
            "total_chars": total_chars,
        })

    def _wiki_files(self):
        """列出所有 Wiki 頁面（排除 meta 檔案和 raw/）。"""
        if not self.wiki_dir.is_dir():
            return
        for md_file in self.wiki_dir.rglob("*.md"):
            if md_file.name.startswith("."):
                continue
            if md_file.name in ("schema.md", "index.md", "log.md"):
                continue
            if "raw" in md_file.parts:
                continue
            yield md_file
