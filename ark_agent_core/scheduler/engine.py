"""ScheduleEngine：APScheduler 排程引擎，支援 YAML 定義排程。"""

import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Coroutine

import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)


class ScheduleEntry:
    """單一排程項目。"""

    def __init__(self, schedule_id: str, definition: dict) -> None:
        self.schedule_id = schedule_id
        self.name: str = definition.get("name", schedule_id)
        self.workflow_id: str = definition.get("workflow_id", "")
        self.cron: str = definition.get("cron", "")
        self.params: dict = definition.get("params", {})
        self.enabled: bool = definition.get("enabled", True)
        self.description: str = definition.get("description", "")

    def to_dict(self) -> dict:
        return {
            "schedule_id": self.schedule_id,
            "name": self.name,
            "workflow_id": self.workflow_id,
            "cron": self.cron,
            "enabled": self.enabled,
            "description": self.description,
        }


class ScheduleEngine:
    """管理排程定義與 APScheduler 生命週期。"""

    def __init__(self, schedules_dir: str = "./workflows/schedules") -> None:
        self.schedules_dir = Path(schedules_dir)
        self._entries: dict[str, ScheduleEntry] = {}
        self._scheduler = AsyncIOScheduler()
        self._trigger_callback: Callable[..., Coroutine] | None = None
        self._logs: list[dict] = []

    def set_trigger_callback(
        self, callback: Callable[..., Coroutine]
    ) -> None:
        """設定排程觸發時的回呼函式，簽名: async def(workflow_id, params)"""
        self._trigger_callback = callback

    def load_definitions(self) -> int:
        """從 YAML 檔案載入排程定義。回傳載入數量。"""
        count = 0
        if not self.schedules_dir.is_dir():
            return 0

        for f in sorted(self.schedules_dir.glob("*.yaml")):
            try:
                with open(f, encoding="utf-8") as fh:
                    data = yaml.safe_load(fh)
                if not data:
                    continue
                # 支援單一定義或列表
                entries = data if isinstance(data, list) else data.get("schedules", [data])
                for entry_def in entries:
                    sid = entry_def.get("id", "")
                    if sid:
                        self._entries[sid] = ScheduleEntry(sid, entry_def)
                        count += 1
            except Exception as e:
                logger.warning("Failed to load schedule %s: %s", f, e)
        return count

    def register_jobs(self) -> int:
        """將已載入的排程定義註冊到 APScheduler。回傳註冊數量。"""
        count = 0
        for entry in self._entries.values():
            if not entry.enabled or not entry.cron:
                continue
            try:
                trigger = CronTrigger.from_crontab(entry.cron)
                self._scheduler.add_job(
                    self._trigger_workflow,
                    trigger=trigger,
                    id=entry.schedule_id,
                    name=entry.name,
                    kwargs={
                        "workflow_id": entry.workflow_id,
                        "params": entry.params,
                        "schedule_id": entry.schedule_id,
                    },
                    replace_existing=True,
                )
                count += 1
            except Exception as e:
                logger.warning("Failed to register job %s: %s", entry.schedule_id, e)
        return count

    async def _trigger_workflow(
        self, workflow_id: str, params: dict, schedule_id: str
    ) -> None:
        """排程觸發時執行的內部方法。"""
        log_entry = {
            "schedule_id": schedule_id,
            "workflow_id": workflow_id,
            "triggered_at": datetime.now(timezone.utc).isoformat(),
            "status": "triggered",
        }
        self._logs.append(log_entry)
        logger.info("Schedule triggered: %s -> %s", schedule_id, workflow_id)

        if self._trigger_callback:
            try:
                await self._trigger_callback(workflow_id, params)
                log_entry["status"] = "completed"
            except Exception as e:
                log_entry["status"] = "failed"
                log_entry["error"] = str(e)
                logger.error("Schedule %s failed: %s", schedule_id, e)

    def start(self) -> None:
        """啟動排程器。"""
        if not self._scheduler.running:
            self._scheduler.start()

    def stop(self) -> None:
        """停止排程器。"""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def list_schedules(self) -> list[dict]:
        """列出所有排程定義。"""
        return [e.to_dict() for e in self._entries.values()]

    def toggle_schedule(self, schedule_id: str, enabled: bool) -> bool:
        """啟用或暫停排程。回傳是否成功。"""
        entry = self._entries.get(schedule_id)
        if entry is None:
            return False

        entry.enabled = enabled
        if enabled:
            try:
                trigger = CronTrigger.from_crontab(entry.cron)
                self._scheduler.add_job(
                    self._trigger_workflow,
                    trigger=trigger,
                    id=entry.schedule_id,
                    name=entry.name,
                    kwargs={
                        "workflow_id": entry.workflow_id,
                        "params": entry.params,
                        "schedule_id": entry.schedule_id,
                    },
                    replace_existing=True,
                )
            except Exception:
                pass
        else:
            try:
                self._scheduler.remove_job(schedule_id)
            except Exception:
                pass
        return True

    def toggle(self, schedule_id: str) -> bool:
        """翻轉排程的 enabled 狀態，回傳切換後的 enabled 值。

        若 schedule_id 不存在，回傳 False。
        """
        entry = self._entries.get(schedule_id)
        if entry is None:
            return False
        new_enabled = not entry.enabled
        self.toggle_schedule(schedule_id, new_enabled)
        return new_enabled

    @staticmethod
    def _resolve_env_vars(params: dict) -> dict:
        """遞迴替換 params 中的 ${ENV_VAR} 引用。"""
        resolved = {}
        for key, value in params.items():
            if isinstance(value, str):
                resolved[key] = re.sub(
                    r"\$\{(\w+)\}",
                    lambda m: os.environ.get(m.group(1), ""),
                    value,
                )
            elif isinstance(value, dict):
                resolved[key] = ScheduleEngine._resolve_env_vars(value)
            else:
                resolved[key] = value
        return resolved

    def get_logs(self, limit: int = 20) -> list[dict]:
        """取得最近的排程執行紀錄。"""
        return self._logs[-limit:]
