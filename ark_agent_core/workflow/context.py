"""RunContext：工作流執行上下文，儲存步驟間的資料傳遞。"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any
import uuid


class RunStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class RunContext:
    """工作流單次執行的上下文。"""

    def __init__(self, workflow_id: str, params: dict | None = None) -> None:
        self.run_id: str = uuid.uuid4().hex[:12]
        self.workflow_id: str = workflow_id
        self.params: dict = params or {}
        self.status: RunStatus = RunStatus.PENDING
        self.outputs: dict[str, Any] = {}
        self.current_step: int = 0
        self.total_steps: int = 0
        self.started_at: datetime | None = None
        self.finished_at: datetime | None = None
        self.error: str | None = None

    def start(self, total_steps: int) -> None:
        self.status = RunStatus.RUNNING
        self.total_steps = total_steps
        self.started_at = datetime.now(timezone.utc)

    def set_step_output(self, step_id: str, output: Any) -> None:
        """儲存步驟輸出，供後續步驟引用。"""
        self.outputs[step_id] = output

    def get_output(self, step_id: str) -> Any:
        return self.outputs.get(step_id)

    def complete(self) -> None:
        self.status = RunStatus.COMPLETED
        self.finished_at = datetime.now(timezone.utc)

    def fail(self, error: str) -> None:
        self.status = RunStatus.FAILED
        self.error = error
        self.finished_at = datetime.now(timezone.utc)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "status": self.status.value,
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "error": self.error,
        }
