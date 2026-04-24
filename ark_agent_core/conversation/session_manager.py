"""SessionManager：管理所有使用者 Session 的生命週期，含 SQLite 持久化。"""

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from ark_agent_core.conversation.session import Session, SessionState

logger = logging.getLogger(__name__)

# SQLite 建表語句
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id   TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    chat_id      TEXT,
    status       TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    completed_at TEXT,
    turn_count   INTEGER DEFAULT 0,
    intent       TEXT,
    workflow     TEXT,
    params       TEXT DEFAULT '{}',
    turns_json   TEXT DEFAULT '[]'
);
"""

_CREATE_INDEX_USER_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);"
)
_CREATE_INDEX_STATUS_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);"
)


class SessionManager:
    """per-user Session 管理：建立、取得、清理、SQLite 持久化。"""

    def __init__(self, db_path: str = "./data/sessions.db", memory_store=None) -> None:
        self._sessions: dict[str, Session] = {}
        self._user_sessions: dict[str, str] = {}  # user_id -> session_id
        self.db_path = Path(db_path)
        self._memory_store = memory_store  # MemoryStore 實例（用於使用頻率統計）

    # ── SQLite 持久化方法 ────────────────────────────────────

    async def init_db(self) -> None:
        """應用程式啟動時建立 sessions 表與索引。自動建立父目錄。"""
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            async with aiosqlite.connect(str(self.db_path)) as db:
                await db.execute(_CREATE_TABLE_SQL)
                await db.execute(_CREATE_INDEX_USER_SQL)
                await db.execute(_CREATE_INDEX_STATUS_SQL)
                await db.commit()
            logger.info("SQLite sessions 表初始化完成：%s", self.db_path)
        except Exception:
            logger.critical(
                "SQLite 建表失敗，持久化功能降級為僅記憶體模式：%s",
                self.db_path,
                exc_info=True,
            )

    async def persist_session(self, session: Session) -> None:
        """將 Session 非同步寫入 SQLite。失敗時記錄日誌，不拋出例外。"""
        try:
            # 序列化最近 20 輪對話
            recent_turns = session.turns[-20:]
            turns_data = [
                {
                    "role": t.role,
                    "content": t.content,
                    "timestamp": t.timestamp.isoformat(),
                }
                for t in recent_turns
            ]
            turns_json = json.dumps(turns_data, ensure_ascii=False)

            # 從 session context 取得相關欄位
            params_json = json.dumps(
                session.context.get("params", {}), ensure_ascii=False
            )
            completed_at = (
                datetime.now(timezone.utc).isoformat()
                if session.state in (SessionState.COMPLETED, SessionState.EXPIRED)
                else None
            )

            async with aiosqlite.connect(str(self.db_path)) as db:
                await db.execute(
                    """
                    INSERT OR REPLACE INTO sessions
                        (session_id, user_id, chat_id, status, created_at,
                         completed_at, turn_count, intent, workflow, params, turns_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session.session_id,
                        session.user_id,
                        session.context.get("chat_id"),
                        session.state.value,
                        session.created_at.isoformat(),
                        completed_at,
                        len(session.turns),
                        session.context.get("intent"),
                        session.context.get("workflow_id"),
                        params_json,
                        turns_json,
                    ),
                )
                await db.commit()
        except Exception:
            logger.error(
                "SQLite 寫入失敗（session_id=%s）",
                session.session_id,
                exc_info=True,
            )

    async def complete_session(self, user_id: str) -> None:
        """標記 Session 為 COMPLETED，持久化後從記憶體移除。同時更新使用頻率統計。"""
        session_id = self._user_sessions.get(user_id)
        if not session_id or session_id not in self._sessions:
            return

        session = self._sessions[session_id]
        session.state = SessionState.COMPLETED

        # 更新使用頻率統計
        if self._memory_store is not None:
            workflow_id = session.context.get("workflow_id", "")
            if workflow_id:
                try:
                    self._memory_store.increment_usage(user_id, workflow_id)
                except Exception:
                    logger.warning("使用頻率統計更新失敗", exc_info=True)

        await self.persist_session(session)
        self._remove_session(session_id)

    async def expire_session(self, session_id: str) -> None:
        """標記 Session 為 EXPIRED，持久化後從記憶體移除。"""
        if session_id not in self._sessions:
            return

        session = self._sessions[session_id]
        session.state = SessionState.EXPIRED
        await self.persist_session(session)
        self._remove_session(session_id)

    # ── 既有同步方法（保持不變）─────────────────────────────

    def get_or_create(self, user_id: str) -> Session:
        """取得使用者的 Session，如果不存在或已過期則建立新的。"""
        session_id = self._user_sessions.get(user_id)

        if session_id and session_id in self._sessions:
            session = self._sessions[session_id]
            if not session.is_expired():
                return session
            # 過期 → 清理後建立新的
            self._remove_session(session_id)

        return self._create_session(user_id)

    def get_session(self, session_id: str) -> Session | None:
        session = self._sessions.get(session_id)
        if session and session.is_expired():
            session.state = SessionState.EXPIRED
        return session

    def reset_session(self, user_id: str) -> Session:
        """重置使用者 Session。"""
        session_id = self._user_sessions.get(user_id)
        if session_id:
            self._remove_session(session_id)
        return self._create_session(user_id)

    def cleanup_expired(self) -> int:
        """清理所有過期 Session，回傳清理數量。"""
        expired_ids = [
            sid for sid, s in self._sessions.items() if s.is_expired()
        ]
        for sid in expired_ids:
            self._remove_session(sid)
        return len(expired_ids)

    def list_active(self) -> list[dict]:
        """列出所有活躍 Session。"""
        return [
            s.to_dict()
            for s in self._sessions.values()
            if not s.is_expired()
        ]

    @property
    def active_count(self) -> int:
        return sum(1 for s in self._sessions.values() if not s.is_expired())

    def _create_session(self, user_id: str) -> Session:
        session_id = uuid.uuid4().hex[:12]
        session = Session(session_id=session_id, user_id=user_id)
        self._sessions[session_id] = session
        self._user_sessions[user_id] = session_id
        return session

    def _remove_session(self, session_id: str) -> None:
        session = self._sessions.pop(session_id, None)
        if session:
            self._user_sessions.pop(session.user_id, None)
