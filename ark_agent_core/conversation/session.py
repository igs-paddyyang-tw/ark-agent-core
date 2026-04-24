"""Session 與 Turn 資料結構。"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class SessionState(Enum):
    IDLE = "idle"
    INTENT_PARSING = "intent_parsing"
    CLARIFYING = "clarifying"
    EXECUTING = "executing"
    STREAMING = "streaming"
    COMPLETED = "completed"
    EXPIRED = "expired"


@dataclass
class Turn:
    """單輪對話。"""
    role: str  # "user" | "assistant" | "system"
    content: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict = field(default_factory=dict)


@dataclass
class Session:
    """使用者對話 Session。"""
    session_id: str
    user_id: str
    state: SessionState = SessionState.IDLE
    turns: list[Turn] = field(default_factory=list)
    context: dict = field(default_factory=dict)
    clarify_count: int = 0
    max_clarify: int = 3
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_active: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ttl_seconds: int = 300  # 5 分鐘逾時

    def add_turn(self, role: str, content: str, **metadata: Any) -> Turn:
        turn = Turn(role=role, content=content, metadata=metadata)
        self.turns.append(turn)
        self.last_active = datetime.now(timezone.utc)
        return turn

    def is_expired(self) -> bool:
        elapsed = (datetime.now(timezone.utc) - self.last_active).total_seconds()
        return elapsed > self.ttl_seconds

    def get_recent_turns(self, n: int = 10) -> list[Turn]:
        return self.turns[-n:]

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "state": self.state.value,
            "turn_count": len(self.turns),
            "clarify_count": self.clarify_count,
            "created_at": self.created_at.isoformat(),
            "last_active": self.last_active.isoformat(),
            "expired": self.is_expired(),
        }
