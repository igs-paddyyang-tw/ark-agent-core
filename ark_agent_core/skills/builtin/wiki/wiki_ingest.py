"""Wiki Ingest Skill：將原始文件攝入 LLM Wiki 知識庫。

基於 LLM Wiki 模式：Raw Sources → Wiki Pages → 交叉引用 → 持續複利。
"""

from datetime import datetime, timezone
from pathlib import Path

from ark_agent_core.skills.base import BaseSkill, SkillResult, SkillType


class WikiIngestSkill(BaseSkill):
    skill_id = "wiki_ingest"
    skill_type = SkillType.PYTHON
    description = "將原始文件攝入 Wiki：讀取 → 分類 → 建立/更新頁面 → 更新索引與日誌"

    def __init__(self, wiki_dir: str = "./knowledge", raw_dir: str = "./knowledge/raw") -> None:
        self.wiki_dir = Path(wiki_dir)
        self.raw_dir = Path(raw_dir)

    def validate_params(self, params: dict) -> bool:
        return "source_path" in params or "content" in params

    async def execute(self, params: dict) -> SkillResult:
        try:
            # 讀取來源內容
            if "content" in params:
                content = params["content"]
                source_name = params.get("name", "untitled")
            elif "source_path" in params:
                source_path = Path(params["source_path"])
                if not source_path.exists():
                    return SkillResult(success=False, error=f"Source not found: {source_path}")
                content = source_path.read_text(encoding="utf-8")
                source_name = source_path.stem
            else:
                return SkillResult(success=False, error="No content or source_path provided")

            # 決定分類
            category = params.get("category", "sources")
            valid_categories = ["entities", "concepts", "sources", "comparisons", "synthesis"]
            if category not in valid_categories:
                category = "sources"

            # 建立 Wiki 頁面
            page_name = params.get("page_name", source_name)
            tags = params.get("tags", [category])
            page_dir = self.wiki_dir / category
            page_dir.mkdir(parents=True, exist_ok=True)
            page_path = page_dir / f"{page_name}.md"

            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            now_full = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

            if page_path.exists():
                # 合併模式：追加新內容，保留既有知識
                existing = page_path.read_text(encoding="utf-8")
                # 更新 frontmatter 的 updated 日期
                if "updated:" in existing:
                    lines = existing.split("\n")
                    for i, line in enumerate(lines):
                        if line.startswith("updated:"):
                            lines[i] = f"updated: {now_str}"
                            break
                    existing = "\n".join(lines)
                merged = f"{existing}\n\n---\n\n## 更新 ({now_full})\n\n{content}"
                page_path.write_text(merged, encoding="utf-8")
                action = "updated"
            else:
                # 新建頁面（含 YAML frontmatter v3.0）
                tags_str = ", ".join(tags)
                page_type = params.get("type", "source")
                related_list = params.get("related", [])
                related_str = ", ".join(related_list) if related_list else ""
                page_content = (
                    f"---\n"
                    f"title: \"{page_name}\"\n"
                    f"type: {page_type}\n"
                    f"tags: [{tags_str}]\n"
                    f"sources: [{source_name}]\n"
                    f"related: [{related_str}]\n"
                    f"created: {now_str}\n"
                    f"updated: {now_str}\n"
                    f"status: seedling\n"
                    f"---\n\n"
                    f"# {page_name}\n\n"
                    f"{content}\n\n"
                    f"## 來源\n\n"
                    f"- 來自 `raw/{source_name}`\n"
                )
                page_path.write_text(page_content, encoding="utf-8")
                action = "created"

            # 更新 log.md
            self._update_log(action, category, page_name)

            # 更新 index.md
            self._update_index(category, page_name, page_path)

            rel_path = page_path.relative_to(self.wiki_dir).as_posix()
            return SkillResult(
                success=True,
                data={
                    "action": action,
                    "path": rel_path,
                    "category": category,
                    "page_name": page_name,
                },
            )
        except Exception as e:
            return SkillResult(success=False, error=f"Wiki ingest failed: {e}")

    def _update_log(self, action: str, category: str, page_name: str) -> None:
        """追加操作紀錄到 log.md（append-only）。"""
        log_path = self.wiki_dir / "log.md"
        if not log_path.exists():
            return
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        entry = f"\n## [{now}] {action} | {category}/{page_name}\n\n- {action}: `{category}/{page_name}.md`\n"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(entry)

    def _update_index(self, category: str, page_name: str, page_path: Path) -> None:
        """更新 index.md 中的頁面條目。"""
        index_path = self.wiki_dir / "index.md"
        if not index_path.exists():
            return

        content = index_path.read_text(encoding="utf-8")
        try:
            rel_path = page_path.relative_to(Path(".").resolve()).as_posix()
        except ValueError:
            rel_path = f"knowledge/{category}/{page_name}.md"

        entry = f"- [{page_name}]({rel_path})"

        category_map = {
            "entities": "## Entities（實體）",
            "concepts": "## Concepts（概念）",
            "sources": "## Sources（來源摘要）",
            "comparisons": "## Comparisons（比較分析）",
            "synthesis": "## Synthesis（綜合洞察）",
        }

        header = category_map.get(category, "")
        if header and header in content:
            if entry not in content:
                placeholder = "_尚無頁面_"
                if placeholder in content.split(header, 1)[-1].split("##")[0]:
                    content = content.replace(
                        f"{header}\n\n{placeholder}",
                        f"{header}\n\n{entry}",
                    )
                else:
                    parts = content.split(header, 1)
                    after = parts[1]
                    next_section = after.find("\n## ")
                    if next_section > 0:
                        insert_pos = next_section
                        after = after[:insert_pos].rstrip() + f"\n{entry}\n" + after[insert_pos:]
                    else:
                        after = after.rstrip() + f"\n{entry}\n"
                    content = parts[0] + header + after

                index_path.write_text(content, encoding="utf-8")
