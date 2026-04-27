"""ark CLI 入口：ark init / ark run / ark skills。"""

import argparse
import shutil
import sys
from pathlib import Path


def cmd_init(args) -> int:
    """ark init <project_name> — 產出專案骨架。"""
    project_name = args.name
    target = Path.cwd() / project_name

    if target.exists():
        print(f"❌ 目錄已存在：{target}")
        return 1

    # 從 templates/ 複製骨架
    template_dir = Path(__file__).resolve().parent.parent / "templates" / "project_skeleton"
    if not template_dir.exists():
        print(f"❌ 找不到範本：{template_dir}")
        return 1

    shutil.copytree(template_dir, target)
    print(f"✅ 專案骨架已建立：{target}")
    print(f"\n下一步：")
    print(f"  cd {project_name}")
    print(f"  cp .env.example .env")
    print(f"  # 編輯 .env 填入 GEMINI_API_KEY（選用）")
    print(f"  ark run")
    return 0


def cmd_run(args) -> int:
    """ark run — 啟動 uvicorn server。"""
    import uvicorn
    import os

    port = int(os.getenv("PORT", args.port or 8000))
    host = os.getenv("HOST", "0.0.0.0")
    print(f"🚀 啟動 server：http://localhost:{port}")
    uvicorn.run("src.server.main:app", host=host, port=port, reload=True)
    return 0


def cmd_skills(args) -> int:
    """ark skills — 列出已註冊的 Skills。"""
    from ark_agent_core.skills.registry import SkillRegistry
    r = SkillRegistry()
    r.auto_discover("ark_agent_core.skills.builtin")
    r.auto_discover("ark_agent_core.skills.builtin.wiki")
    r.auto_discover("ark_agent_core.skills.builtin.llm")
    skills = r.list_skills()
    print(f"已註冊 Skills（{len(skills)} 個）：\n")
    for s in skills:
        print(f"  • {s['skill_id']} ({s['skill_type']}) — {s['description'][:50]}")
    return 0


def cmd_version(args) -> int:
    """ark version — 顯示版本。"""
    from ark_agent_core import __version__
    print(f"ark-agent-core v{__version__}")
    return 0


def main() -> int:
    """CLI 主入口。"""
    parser = argparse.ArgumentParser(
        prog="ark",
        description="Ark Agent Core — 智能助理框架 CLI",
    )
    sub = parser.add_subparsers(dest="cmd")

    p_init = sub.add_parser("init", help="建立新專案")
    p_init.add_argument("name", help="專案名稱")
    p_init.set_defaults(func=cmd_init)

    p_run = sub.add_parser("run", help="啟動 server")
    p_run.add_argument("--port", type=int, help="埠號（預設 8000）")
    p_run.set_defaults(func=cmd_run)

    p_skills = sub.add_parser("skills", help="列出已註冊 Skills")
    p_skills.set_defaults(func=cmd_skills)

    p_version = sub.add_parser("version", help="顯示版本")
    p_version.set_defaults(func=cmd_version)

    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
