"""KiroAdapter：封裝 kiro-cli 呼叫，作為獨立 Agent 後端。

不參與一般 LLM fallback chain（延遲太高），
作為獨立路徑供使用者明確要求時使用。
當 LLM_BACKEND=kiro 時，一般對話也會走此路徑。
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Kiro Skill → Runtime Skill 目標目錄對應表
KIRO_SKILL_MAP: dict[str, dict[str, str]] = {
    "ark-db-query": {"target": "python_skills", "type": "PYTHON"},
    "ark-etl-pipeline": {"target": "python_skills", "type": "PYTHON"},
    "ark-chart-generator": {"target": "python_skills", "type": "PYTHON"},
    "ark-file-export": {"target": "python_skills", "type": "PYTHON"},
    "ark-web-scraper": {"target": "python_skills", "type": "PYTHON"},
    "ark-cost-tracker": {"target": "python_skills", "type": "PYTHON"},
    "ark-report-template": {"target": "python_skills", "type": "PYTHON"},
    "ark-telegram-notify": {"target": "python_skills", "type": "PYTHON"},
    "ark-security-audit": {"target": "python_skills", "type": "PYTHON"},
    "ark-test-runner": {"target": "python_skills", "type": "PYTHON"},
    "ark-llm-tools": {"target": "llm_skills", "type": "LLM"},
    "ark-translator": {"target": "llm_skills", "type": "LLM"},
    "ark-code-review": {"target": "llm_skills", "type": "LLM"},
    "ark-wiki-engine": {"target": "wiki_skills", "type": "PYTHON"},
}


class KiroAdapter:
    """封裝 kiro-cli 所有操作，透過 subprocess 非同步執行。

    提供對話、檔案操作、系統資訊、Skill CodeGen 等功能。
    """

    def __init__(
        self,
        kiro_cmd: str | None = None,
        workspace: str | None = None,
        chat_timeout: int | None = None,
        file_timeout: int | None = None,
    ) -> None:
        self.kiro_cmd = kiro_cmd or os.getenv("KIRO_CLI_CMD", "kiro-cli")
        self.workspace = workspace or os.getenv(
            "KIRO_WORKSPACE", str(Path.home() / "kiro-workspace"),
        )
        self.chat_timeout = chat_timeout or int(
            os.getenv("KIRO_CHAT_TIMEOUT", "120"),
        )
        self.file_timeout = file_timeout or int(
            os.getenv("KIRO_FILE_TIMEOUT", "30"),
        )
        self._available: bool | None = None

    async def is_available(self) -> bool:
        """檢查 kiro-cli 是否可用（已安裝且可執行）。結果快取。"""
        if self._available is not None:
            return self._available
        try:
            proc = await asyncio.create_subprocess_exec(
                self.kiro_cmd, "version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            self._available = proc.returncode == 0
            if self._available:
                version = stdout.decode("utf-8", errors="replace").strip()
                logger.info("Kiro CLI 可用：%s", version)
            else:
                logger.warning("Kiro CLI 不可用（exit %d）", proc.returncode)
        except (FileNotFoundError, asyncio.TimeoutError, Exception) as e:
            logger.warning("Kiro CLI 不可用：%s", e)
            self._available = False
        return self._available

    async def _run(
        self,
        cmd: list[str],
        cwd: str | None = None,
        timeout: int | None = None,
        stdin_data: str | None = None,
    ) -> dict[str, Any]:
        """執行 shell 命令並回傳結果。"""
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.PIPE if stdin_data else None,
                cwd=cwd or self.workspace,
            )
            stdin_bytes = stdin_data.encode() if stdin_data else None
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=stdin_bytes),
                timeout=timeout or self.chat_timeout,
            )
            return {
                "success": proc.returncode == 0,
                "returncode": proc.returncode,
                "stdout": stdout.decode("utf-8", errors="replace").strip(),
                "stderr": stderr.decode("utf-8", errors="replace").strip(),
            }
        except asyncio.TimeoutError:
            return {
                "success": False, "returncode": -1, "stdout": "",
                "stderr": f"執行超時（{timeout or self.chat_timeout}s）",
            }
        except FileNotFoundError:
            return {
                "success": False, "returncode": -1, "stdout": "",
                "stderr": f"找不到命令：{cmd[0]}，請確認 kiro-cli 已安裝",
            }
        except Exception as e:
            return {"success": False, "returncode": -1, "stdout": "", "stderr": str(e)}

    def _fmt(self, result: dict[str, Any], label: str = "") -> str:
        """格式化命令執行結果為可讀文字。"""
        parts: list[str] = []
        if label:
            parts.append(f"【{label}】")
        if result["stdout"]:
            parts.append(result["stdout"])
        if result["stderr"] and not result["success"]:
            parts.append(f"⚠️ {result['stderr']}")
        if not result["success"] and not result["stdout"] and not result["stderr"]:
            parts.append(f"執行失敗（exit {result['returncode']}）")
        return "\n".join(parts) if parts else "（無輸出）"

    async def ask(self, question: str, agent: str = "", trust_all_tools: bool = True) -> dict[str, Any]:
        """向 Kiro CLI 發送問題（非互動模式）。"""
        cmd = [self.kiro_cmd, "chat", "--no-interactive"]
        if trust_all_tools:
            cmd.append("--trust-all-tools")
        if agent:
            cmd += ["--agent", agent]
        cmd.append(question)
        result = await self._run(cmd, timeout=self.chat_timeout)
        return {"text": self._fmt(result, "Kiro"), "model": "kiro-cli", "success": result["success"], "tokens": 0}

    async def resume_chat(self, question: str, session_id: str = "", trust_all_tools: bool = True) -> dict[str, Any]:
        """繼續 Kiro CLI 對話（resume 模式）。"""
        cmd = [self.kiro_cmd, "chat", "--no-interactive"]
        if trust_all_tools:
            cmd.append("--trust-all-tools")
        if session_id:
            cmd += ["--resume-id", session_id]
        else:
            cmd.append("--resume")
        cmd.append(question)
        result = await self._run(cmd, timeout=self.chat_timeout)
        return {"text": self._fmt(result, "Kiro 繼續對話"), "model": "kiro-cli", "success": result["success"], "tokens": 0}

    async def list_sessions(self) -> str:
        """列出所有 Kiro CLI 對話 Session。"""
        result = await self._run([self.kiro_cmd, "chat", "--list-sessions"], timeout=self.file_timeout)
        return self._fmt(result, "Sessions")

    async def file_read(self, path: str) -> str:
        """讀取檔案內容。"""
        try:
            file_path = Path(path) if Path(path).is_absolute() else Path(self.workspace) / path
            if not file_path.exists():
                return f"❌ 檔案不存在：{file_path}"
            if not file_path.is_file():
                return f"❌ 不是檔案：{file_path}"
            content = file_path.read_text(encoding="utf-8", errors="replace")
            size = file_path.stat().st_size
            lines = content.count("\n") + 1
            return f"📄 {file_path}\n（{size} bytes，{lines} 行）\n\n{content}"
        except Exception as e:
            return f"❌ 讀取失敗：{e}"

    async def file_write(self, path: str, content: str, append: bool = False) -> str:
        """寫入檔案內容（自動建立目錄）。"""
        try:
            file_path = Path(path) if Path(path).is_absolute() else Path(self.workspace) / path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            mode = "a" if append else "w"
            with open(file_path, mode, encoding="utf-8") as f:
                f.write(content)
            action = "附加" if append else "寫入"
            return f"✅ {action}成功：{file_path}（{file_path.stat().st_size} bytes）"
        except Exception as e:
            return f"❌ 寫入失敗：{e}"

    async def file_list(self, path: str = "", pattern: str = "*") -> str:
        """列出目錄內容。"""
        try:
            dir_path = Path(path) if (path and Path(path).is_absolute()) else Path(self.workspace) / (path or "")
            if not dir_path.exists():
                return f"❌ 路徑不存在：{dir_path}"
            if not dir_path.is_dir():
                return f"❌ 不是目錄：{dir_path}"
            items = sorted(dir_path.glob(pattern))
            lines = [f"📁 {dir_path}\n"]
            for item in items:
                prefix = "📁" if item.is_dir() else "📄"
                size = f"  ({item.stat().st_size}b)" if item.is_file() else ""
                lines.append(f"  {prefix} {item.name}{size}")
            return "\n".join(lines) if len(lines) > 1 else f"📁 {dir_path}\n（空目錄）"
        except Exception as e:
            return f"❌ 列出失敗：{e}"

    async def file_delete(self, path: str) -> str:
        """刪除檔案。"""
        try:
            file_path = Path(path) if Path(path).is_absolute() else Path(self.workspace) / path
            if not file_path.exists():
                return f"❌ 檔案不存在：{file_path}"
            file_path.unlink()
            return f"✅ 已刪除：{file_path}"
        except Exception as e:
            return f"❌ 刪除失敗：{e}"

    async def analyze_file(self, path: str, instruction: str) -> str:
        """讓 Kiro CLI 讀取並分析檔案。"""
        file_path = Path(path) if Path(path).is_absolute() else Path(self.workspace) / path
        if not file_path.exists():
            return f"❌ 檔案不存在：{file_path}"
        prompt = f"請讀取並處理以下檔案：{file_path}\n\n指令：{instruction}"
        cmd = [self.kiro_cmd, "chat", "--no-interactive", "--trust-all-tools", prompt]
        result = await self._run(cmd, cwd=str(file_path.parent), timeout=self.chat_timeout)
        return self._fmt(result, f"分析 {file_path.name}")

    async def version(self) -> str:
        """取得 Kiro CLI 版本。"""
        result = await self._run([self.kiro_cmd, "version"], timeout=10)
        return self._fmt(result, "版本")

    async def doctor(self) -> str:
        """執行 Kiro CLI 診斷。"""
        result = await self._run([self.kiro_cmd, "doctor", "--format", "plain"], timeout=30)
        return self._fmt(result, "診斷報告")

    async def generate_skill(
        self, kiro_skill_name: str, skill_id: str, description: str = "",
        target_dir: str = "src/skills/python_skills", skill_type: str = "PYTHON",
    ) -> dict[str, Any]:
        """讓 Kiro CLI 根據 .kiro/skills/ 定義產出 Runtime Skill。"""
        skill_md_path = f".kiro/skills/{kiro_skill_name}/SKILL.md"
        prompt = (
            f"請根據以下 Kiro Skill 定義，產出一個 Python Runtime Skill。\n\n"
            f"## 規範\n"
            f"1. 讀取 {skill_md_path} 了解產出指引\n"
            f"2. 讀取 src/skills/base.py 了解 BaseSkill / SkillParam / SkillResult 介面\n"
            f"3. 參考 {target_dir}/ 下的現有 Skill 程式碼風格\n"
            f"4. 產出的 Skill 必須：\n"
            f"   - 繼承 BaseSkill\n"
            f'   - 定義 skill_id = "{skill_id}"\n'
            f"   - 定義 skill_type = SkillType.{skill_type}\n"
            f"   - 定義 SkillParam 子類別作為 input_schema（含 Field description）\n"
            f"   - 實作 async execute(self, params: dict) -> SkillResult\n"
            f"   - 所有例外捕獲，回傳 SkillResult(success=False, error=...)\n"
            f"   - Docstring 使用繁體中文\n"
            f"   - 路徑操作使用 pathlib.Path\n"
            f"5. 將產出的檔案寫入 {target_dir}/{skill_id}.py\n"
        )
        if description:
            prompt += f"\n## 使用者需求\n{description}\n"
        return await self.ask(prompt)

    def get_skill_status(self, skill_id: str) -> dict[str, Any]:
        """檢查 Runtime Skill 檔案狀態。"""
        for subdir in ("python_skills", "llm_skills", "wiki_skills", "internal", "builtin"):
            file_path = Path(self.workspace) / "src" / "skills" / subdir / f"{skill_id}.py"
            if file_path.exists():
                return {"exists": True, "path": str(file_path.relative_to(self.workspace)), "size": file_path.stat().st_size, "category": subdir}
        return {"exists": False, "path": "", "size": 0, "category": ""}

    async def generate(self, prompt: str, system: str = "", **kwargs: Any) -> dict[str, Any]:
        """LLM 相容介面：將 generate 呼叫轉為 kiro-cli chat。"""
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        return await self.ask(full_prompt)
