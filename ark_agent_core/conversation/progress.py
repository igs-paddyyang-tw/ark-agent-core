"""Progress Reporter：工作流執行進度事件。"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class EventType(Enum):
    """工作流執行事件類型。"""
    WORKFLOW_START = "workflow_start"   # 工作流開始執行
    STEP_START = "step_start"          # 步驟開始
    STEP_DONE = "step_done"            # 步驟完成
    STEP_FAILED = "step_failed"        # 步驟執行失敗
    LLM_TOKEN = "llm_token"            # LLM 串流 token
    LLM_COMPLETE = "llm_complete"      # LLM 串流完成
    PROGRESS = "progress"              # 一般進度更新
    ERROR = "error"                    # 錯誤
    COMPLETE = "complete"              # 工作流全部完成


@dataclass
class ProgressEvent:
    """單一進度事件。"""
    event_type: EventType
    step_id: str = ""
    step_index: int = 0
    total_steps: int = 0
    message: str = ""
    data: Any = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type.value,
            "step_id": self.step_id,
            "step_index": self.step_index,
            "total_steps": self.total_steps,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
        }


class ProgressReporter:
    """收集並分發進度事件。"""

    def __init__(self) -> None:
        self._events: list[ProgressEvent] = []
        self._listeners: list[Callable[[ProgressEvent], None]] = []

    def add_listener(self, callback: Callable[[ProgressEvent], None]) -> None:
        self._listeners.append(callback)

    def emit(self, event: ProgressEvent) -> None:
        self._events.append(event)
        for listener in self._listeners:
            try:
                listener(event)
            except Exception:
                pass

    def step_start(self, step_id: str, index: int, total: int) -> None:
        self.emit(ProgressEvent(
            event_type=EventType.STEP_START,
            step_id=step_id,
            step_index=index,
            total_steps=total,
            message=f"⏳ [{index}/{total}] {step_id}...",
        ))

    def step_done(self, step_id: str, index: int, total: int, duration_ms: int = 0) -> None:
        self.emit(ProgressEvent(
            event_type=EventType.STEP_DONE,
            step_id=step_id,
            step_index=index,
            total_steps=total,
            message=f"✅ [{index}/{total}] {step_id} ({duration_ms}ms)",
        ))

    def error(self, step_id: str, message: str) -> None:
        self.emit(ProgressEvent(
            event_type=EventType.ERROR,
            step_id=step_id,
            message=f"❌ {step_id}: {message}",
        ))

    def complete(self, total_duration_ms: int = 0) -> None:
        self.emit(ProgressEvent(
            event_type=EventType.COMPLETE,
            message=f"✅ 全部完成（{total_duration_ms}ms）",
        ))

    def get_events(self) -> list[dict]:
        return [e.to_dict() for e in self._events]

    def clear(self) -> None:
        self._events.clear()


class TelegramProgressReporter:
    """接收工作流進度事件，透過 Telegram edit_message_text 即時更新。"""

    def __init__(self, bot, chat_id: int, message_id: int) -> None:
        self.bot = bot
        self.chat_id = chat_id
        self.message_id = message_id
        self._steps: dict[str, str] = {}  # step_id → 已格式化的狀態字串
        self._stream_buffer: str = ""
        self._last_update: float = 0
        self._min_interval: float = 0.5  # 500ms 節流
        self._start_time: float = 0  # 工作流開始時間

    async def handle_event(self, event: ProgressEvent) -> None:
        """處理進度事件，依據事件類型更新 Telegram 訊息。"""
        if event.event_type == EventType.WORKFLOW_START:
            # 記錄開始時間，渲染初始訊息
            self._start_time = time.time()
            self._steps.clear()
            self._stream_buffer = ""
            await self._update_message("⏳ 工作流開始執行...")

        elif event.event_type == EventType.STEP_START:
            # 更新步驟狀態為進行中
            self._steps[event.step_id] = (
                f"⏳ [{event.step_index}/{event.total_steps}] {event.step_id}..."
            )
            await self._update_message(self._render_progress())

        elif event.event_type == EventType.STEP_DONE:
            # 更新步驟狀態為完成，顯示耗時
            duration = event.data if isinstance(event.data, (int, float)) else 0
            self._steps[event.step_id] = (
                f"✅ [{event.step_index}/{event.total_steps}] {event.step_id} ({duration}ms)"
            )
            await self._update_message(self._render_progress())

        elif event.event_type == EventType.STEP_FAILED:
            # 更新步驟狀態為失敗，顯示錯誤摘要
            error_msg = event.message or "未知錯誤"
            self._steps[event.step_id] = (
                f"❌ [{event.step_index}/{event.total_steps}] {event.step_id}: {error_msg}"
            )
            await self._update_message(self._render_progress())

        elif event.event_type == EventType.LLM_TOKEN:
            # 累積串流 token，節流更新
            self._stream_buffer += event.data if isinstance(event.data, str) else ""
            now = time.time()
            if now - self._last_update >= self._min_interval:
                self._last_update = now
                await self._update_message(self._render_progress())

        elif event.event_type == EventType.LLM_COMPLETE:
            # 串流完成，清空緩衝區
            self._stream_buffer = ""
            await self._update_message(self._render_progress())

        elif event.event_type == EventType.COMPLETE:
            # 工作流全部完成，顯示總耗時
            elapsed = int((time.time() - self._start_time) * 1000) if self._start_time else 0
            await self._update_message(
                self._render_progress() + f"\n\n✅ 全部完成（{elapsed}ms）"
            )

        elif event.event_type == EventType.ERROR:
            # 錯誤事件
            error_msg = event.message or "未知錯誤"
            await self._update_message(
                self._render_progress() + f"\n\n❌ 錯誤：{error_msg}"
            )

    def _render_progress(self) -> str:
        """渲染進度文字（純文字，不用 Markdown 避免格式錯誤）。"""
        lines = list(self._steps.values())

        # 若有串流緩衝區，附加截斷預覽（最多 200 字元）
        if self._stream_buffer:
            # 將換行替換為空格，避免破壞渲染格式
            sanitized = self._stream_buffer.replace("\n", " ").replace("\r", " ")
            preview = sanitized[:200]
            if len(sanitized) > 200:
                preview += "..."
            lines.append(f"💬 {preview}")

        return "\n".join(lines)

    async def _update_message(self, text: str) -> None:
        """透過 edit_message_text 更新訊息，捕獲內容相同與速率限制錯誤。"""
        try:
            from telegram.error import BadRequest, RetryAfter
        except ImportError:
            # telegram 套件未安裝時靜默跳過
            return

        try:
            await self.bot.edit_message_text(
                text=text,
                chat_id=self.chat_id,
                message_id=self.message_id,
            )
        except BadRequest:
            # 內容相同，靜默忽略
            pass
        except RetryAfter as e:
            # 速率限制，增加節流間隔
            self._min_interval = max(self._min_interval, 1.0)
            logger.warning("Telegram 速率限制，節流間隔調整為 %.1fs（retry_after=%s）",
                           self._min_interval, e.retry_after)
        except Exception:
            # 其他錯誤靜默忽略，避免影響工作流執行
            logger.exception("更新 Telegram 進度訊息失敗")
