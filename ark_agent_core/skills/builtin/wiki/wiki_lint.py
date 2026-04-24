"""Wiki Lint Skill：Wiki 健康檢查。"""

import re
from pathlib import Path

from ark_agent_core.skills.base import BaseSkill, SkillResult, SkillType


class WikiLintSkill(BaseSkill):
    skill_id = "wiki_lint"
    skill_type = SkillType.PYTHON
    description = "Wiki 健康檢查：偵測孤立頁面、缺少標題、斷裂連結"

    VALID_TYPES = {"concept", "entity", "source", "synthesis", "comparison", "overview", "system"}
    VALID_STATUS = {"seedling", "developing", "mature"}
    REQUIRED_FRONTMATTER = {"title", "type", "tags", "created", "updated"}

    def __init__(self, wiki_dir: str = "./knowledge") -> None:
        self.wiki_dir = Path(wiki_dir)

    async def execute(self, params: dict) -> SkillResult:
        try:
            issues = []
            pages = self._scan_pages()

            if not pages:
                return SkillResult(
                    success=True,
                    data={"issues": [], "page_count": 0, "healthy": True},
                )

            # 收集所有頁面名稱（用於連結檢查）
            page_names = {p["name"].lower() for p in pages}

            for page in pages:
                # 檢查：缺少一級標題
                if not page["has_title"]:
                    issues.append({
                        "type": "missing_title",
                        "path": page["path"],
                        "message": f"頁面缺少一級標題 (#): {page['path']}",
                    })

                # 檢查：frontmatter 必要欄位
                for field in self.REQUIRED_FRONTMATTER:
                    if field not in page.get("frontmatter", {}):
                        issues.append({
                            "type": "missing_frontmatter",
                            "path": page["path"],
                            "message": f"缺少 frontmatter 欄位 '{field}': {page['path']}",
                        })

                # 檢查：type 合法值
                fm_type = page.get("frontmatter", {}).get("type", "")
                if fm_type and fm_type not in self.VALID_TYPES:
                    issues.append({
                        "type": "invalid_type",
                        "path": page["path"],
                        "message": f"無效的 type '{fm_type}': {page['path']}",
                    })

                # 檢查：status 合法值
                fm_status = page.get("frontmatter", {}).get("status", "")
                if fm_status and fm_status not in self.VALID_STATUS:
                    issues.append({
                        "type": "invalid_status",
                        "path": page["path"],
                        "message": f"無效的 status '{fm_status}': {page['path']}",
                    })

                # 檢查：斷裂的 [[雙向連結]]
                for link in page["links"]:
                    if link.lower() not in page_names:
                        issues.append({
                            "type": "broken_link",
                            "path": page["path"],
                            "message": f"斷裂連結 [[{link}]] in {page['path']}",
                        })

                # 檢查：內容過短
                if page["char_count"] < 50:
                    issues.append({
                        "type": "too_short",
                        "path": page["path"],
                        "message": f"頁面內容過短 ({page['char_count']} 字): {page['path']}",
                    })

            # 檢查：孤立頁面（沒有被任何其他頁面連結）
            all_links = set()
            for page in pages:
                all_links.update(link.lower() for link in page["links"])

            for page in pages:
                if page["name"].lower() not in all_links and len(pages) > 1:
                    issues.append({
                        "type": "orphan",
                        "path": page["path"],
                        "message": f"孤立頁面（無入站連結）: {page['path']}",
                    })

            return SkillResult(
                success=True,
                data={
                    "issues": issues,
                    "issue_count": len(issues),
                    "page_count": len(pages),
                    "healthy": len(issues) == 0,
                },
            )
        except Exception as e:
            return SkillResult(success=False, error=f"Wiki lint failed: {e}")

    def _scan_pages(self) -> list[dict]:
        """掃描所有 Wiki 頁面，提取元資料與 frontmatter。"""
        pages = []
        if not self.wiki_dir.is_dir():
            return pages

        for md_file in self.wiki_dir.rglob("*.md"):
            if md_file.name.startswith("."):
                continue

            try:
                content = md_file.read_text(encoding="utf-8")
            except Exception:
                continue

            # 提取標題
            has_title = False
            for line in content.split("\n"):
                if line.startswith("# ") and not line.startswith("## "):
                    has_title = True
                    break

            # 提取 [[雙向連結]]
            links = re.findall(r"\[\[([^\]]+)\]\]", content)

            # 提取 frontmatter
            frontmatter = self._parse_frontmatter(content)

            rel_path = md_file.relative_to(self.wiki_dir).as_posix()
            pages.append({
                "path": rel_path,
                "name": md_file.stem,
                "has_title": has_title,
                "links": links,
                "char_count": len(content),
                "frontmatter": frontmatter,
            })

        return pages

    def _parse_frontmatter(self, content: str) -> dict:
        """簡易解析 YAML frontmatter。"""
        if not content.startswith("---"):
            return {}
        parts = content.split("---", 2)
        if len(parts) < 3:
            return {}
        fm = {}
        for line in parts[1].strip().split("\n"):
            if ":" in line:
                key, _, value = line.partition(":")
                fm[key.strip()] = value.strip().strip('"').strip("'")
        return fm
