"""Memory System：per-user memory.md 讀寫，存放於 data/memory/。"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _load_prompt(category: str) -> str | None:
    """嘗試載入 prompt 模板（延遲匯入，避免硬依賴）。"""
    try:
        from ark_agent_core.llm.prompts import load_prompt
        return load_prompt(category)
    except ImportError:
        return None


def _extract_json(text: str) -> dict:
    """從 LLM 回應文字中提取 JSON 物件（dict）。

    處理 qwen3 thinking mode（<think>...</think>）、markdown code block 等情況。
    json.loads 回傳非 dict 型別（如字串、陣列）時繼續嘗試其他提取方式。
    """
    if not text:
        raise ValueError("空回應")

    # 移除 <think>...</think> 標籤
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    # 嘗試直接解析
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # 嘗試提取 ```json ... ``` 區塊
    md_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if md_match:
        try:
            parsed = json.loads(md_match.group(1))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    # 嘗試提取第一個 {...} 區塊
    brace_match = re.search(r"\{[^{}]*\}", cleaned)
    if brace_match:
        try:
            parsed = json.loads(brace_match.group())
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    raise ValueError(f"無法從回應中提取 JSON dict: {cleaned[:100]}")

# 允許記憶的欄位白名單
ALLOWED_FIELDS = {
    # 報表偏好
    "preferred_date_range",
    "preferred_department",
    "preferred_format",
    "preferred_language",
    "report_style",
    "chart_type",
    # 排程偏好
    "notification_time",
    "schedule_kpi_time",
    "schedule_weekly_time",
    # 使用習慣
    "frequent_queries",
    "conversation_style",
    # 基本資訊
    "nickname",
    "role",
}


class MemoryStore:
    """管理 per-user memory.md 檔案。"""

    def __init__(self, memory_dir: str = "./data/memory") -> None:
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    def _user_path(self, user_id: str) -> Path:
        return self.memory_dir / f"memory_{user_id}.md"

    def read(self, user_id: str) -> dict[str, str]:
        """讀取使用者記憶，回傳 key-value dict。"""
        path = self._user_path(user_id)
        if not path.exists():
            return {}

        data: dict[str, str] = {}
        content = path.read_text(encoding="utf-8")
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("- ") and ": " in line:
                key, _, value = line[2:].partition(": ")
                key = key.strip()
                value = value.strip()
                if key in ALLOWED_FIELDS:
                    data[key] = value
        return data

    def write(self, user_id: str, key: str, value: str) -> bool:
        """寫入單一記憶欄位。回傳是否成功。"""
        if key not in ALLOWED_FIELDS:
            return False

        data = self.read(user_id)
        data[key] = value
        self._save(user_id, data)
        return True

    def clear(self, user_id: str) -> bool:
        """清除使用者所有記憶。"""
        path = self._user_path(user_id)
        if path.exists():
            path.unlink()
        return True

    def export(self, user_id: str) -> str:
        """匯出使用者記憶為 Markdown 字串。"""
        data = self.read(user_id)
        if not data:
            return f"# Memory: {user_id}\n\n_尚無記憶_\n"

        lines = [f"# Memory: {user_id}", ""]
        for key, value in sorted(data.items()):
            lines.append(f"- {key}: {value}")
        lines.append("")
        return "\n".join(lines)

    def _save(self, user_id: str, data: dict[str, str]) -> None:
        lines = [f"# Memory: {user_id}", ""]
        for key, value in sorted(data.items()):
            lines.append(f"- {key}: {value}")
        lines.append("")
        self._user_path(user_id).write_text("\n".join(lines), encoding="utf-8")

    def increment_usage(self, user_id: str, workflow_id: str) -> None:
        """記錄工作流使用次數，更新 frequent_queries 欄位。

        格式：「workflow_id(次數), workflow_id(次數)」，按次數降序排列。
        """
        if not workflow_id:
            return
        data = self.read(user_id)
        raw = data.get("frequent_queries", "")

        # 解析現有統計：「daily_kpi(5), qa(3)」
        usage: dict[str, int] = {}
        if raw:
            for item in raw.split(", "):
                item = item.strip()
                if "(" in item and item.endswith(")"):
                    name, count_str = item.rsplit("(", 1)
                    try:
                        usage[name.strip()] = int(count_str.rstrip(")"))
                    except ValueError:
                        pass
                elif item:
                    usage[item] = 1

        # 累加
        usage[workflow_id] = usage.get(workflow_id, 0) + 1

        # 排序後寫回
        sorted_items = sorted(usage.items(), key=lambda x: x[1], reverse=True)
        new_value = ", ".join(f"{name}({count})" for name, count in sorted_items[:10])
        self.write(user_id, "frequent_queries", new_value)

class MemoryExtractor:
    """Session 完成時，用 LLM 從對話歷史中提取使用者偏好。"""

    def __init__(self, llm_adapter, memory_store: MemoryStore) -> None:
        self.llm = llm_adapter
        self.memory = memory_store

    async def extract(self, session, user_id: str) -> dict[str, str]:
        """分析 Session 對話歷史，回傳提取到的偏好 dict。

        僅提取 ALLOWED_FIELDS 白名單內的欄位。
        LLM 失敗時回傳空 dict（靜默跳過）。
        """
        if not session.turns:
            return {}

        try:
            system_prompt = _load_prompt("memory_extract")
            if not system_prompt:
                return {}

            # 格式化對話歷史
            conversation_lines = [f"[{t.role}] {t.content}" for t in session.turns]
            conversation_history = "\n".join(conversation_lines)

            formatted_system = system_prompt.format(
                conversation_history=conversation_history,
            )

            result = await self.llm.generate(
                prompt="提取使用者偏好",
                system=formatted_system,
                tier="FAST",
            )

            response_text = result.get("text", "").strip()
            extracted = _extract_json(response_text)

            # 過濾到白名單
            return {k: v for k, v in extracted.items() if k in ALLOWED_FIELDS}

        except Exception as e:
            logger.warning("記憶提取失敗: %s", e)
            return {}


# ---------------------------------------------------------------------------
# Phase 2 記憶系統元件
# ---------------------------------------------------------------------------


@dataclass
class MemoryHit:
    """檢索結果。"""

    content: str
    score: float
    source: str  # "vector" | "bm25" | "hybrid"
    metadata: dict = field(default_factory=dict)


class HierarchicalMemory:
    """階層式摘要：L1 近期 + L2 短期摘要 + L3 長期摘要。"""

    def compress(self, session: Any) -> str:
        """根據對話輪數自動分層壓縮。

        回傳格式：
        - ≤10 輪："{L1 原始對話}"
        - 11-50 輪："{L2 摘要}\n\n{L1 原始對話}"
        - >50 輪："{L3 摘要}\n\n{L2 摘要}\n\n{L1 原始對話}"
        """
        turns = session.turns
        total = len(turns)

        if total <= 10:
            return self._format_l1(turns)

        l1_turns = turns[-10:]
        l1_text = self._format_l1(l1_turns)

        if total <= 50:
            l2_turns = turns[:-10]
            l2_text = self._compress_l2(l2_turns)
            return f"{l2_text}\n\n{l1_text}"

        # > 50 輪：全部三層
        l1_turns = turns[-10:]
        l2_turns = turns[10:-10]
        l3_turns = turns[:10] + turns[10:-10]

        l1_text = self._format_l1(l1_turns)
        l2_text = self._compress_l2(l2_turns)
        l3_text = self._compress_l3(l3_turns)

        return f"{l3_text}\n\n{l2_text}\n\n{l1_text}"

    def _format_l1(self, turns: list[Any]) -> str:
        """格式化 L1 原始對話。"""
        lines: list[str] = []
        for t in turns:
            lines.append(f"[{t.role}] {t.content}")
        return "\n".join(lines)

    def _compress_l2(self, turns: list[Any]) -> str:
        """L2 壓縮：每 10 輪壓縮為 1 段摘要（簡易版：取首句）。"""
        chunks: list[str] = []
        for i in range(0, len(turns), 10):
            chunk = turns[i : i + 10]
            summary_parts = [t.content[:30] for t in chunk]
            chunks.append(f"[L2 摘要] {'; '.join(summary_parts)}")
        return "\n".join(chunks)

    def _compress_l3(self, turns: list[Any]) -> str:
        """L3 壓縮：整體對話壓縮為核心意圖摘要。"""
        topics = set()
        for t in turns:
            if t.content:
                topics.add(t.content[:20])
        return f"[L3 核心意圖] 涵蓋主題: {', '.join(list(topics)[:5])}"


class HybridMemoryRetrieval:
    """向量 + 關鍵字雙路檢索，使用 RRF 合併排序。"""

    def __init__(self, collection_name: str = "conversation_memory") -> None:
        self.collection_name = collection_name

    def rrf_merge(
        self,
        vector_results: list[MemoryHit],
        bm25_results: list[MemoryHit],
        k: int = 60,
    ) -> list[MemoryHit]:
        """Reciprocal Rank Fusion 合併排序。

        公式：RRF_score(d) = Σ 1 / (k + rank_i(d))
        雙路命中 → source="hybrid"，分數為兩路 RRF 分數之和。
        """
        scores: dict[str, float] = {}
        sources: dict[str, str] = {}
        meta: dict[str, dict] = {}

        for rank, hit in enumerate(vector_results):
            key = hit.content
            scores[key] = scores.get(key, 0) + 1 / (k + rank + 1)
            sources[key] = "vector"
            meta[key] = hit.metadata

        for rank, hit in enumerate(bm25_results):
            key = hit.content
            prev = scores.get(key, 0)
            scores[key] = prev + 1 / (k + rank + 1)
            if prev > 0:
                sources[key] = "hybrid"
            else:
                sources[key] = "bm25"
            meta[key] = hit.metadata

        sorted_keys = sorted(scores, key=lambda x: scores[x], reverse=True)
        return [
            MemoryHit(
                content=k, score=scores[k], source=sources[k], metadata=meta[k]
            )
            for k in sorted_keys
        ]
