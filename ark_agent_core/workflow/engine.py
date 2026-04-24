"""WorkflowEngine：YAML 工作流引擎，支援四種控制流程 + 進度回報。"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Template

from ark_agent_core.conversation.progress import EventType, ProgressEvent
from ark_agent_core.skills.registry import SkillRegistry
from ark_agent_core.workflow.context import RunContext

# 進度回報 callback 型別
ProgressCallback = Callable[[ProgressEvent], Awaitable[None]]


class WorkflowEngine:
    """載入並執行 YAML 定義的工作流。"""

    def __init__(self, registry: SkillRegistry, workflows_dir: str = "./workflows") -> None:
        self.registry = registry
        self.workflows_dir = Path(workflows_dir)
        self._definitions: dict[str, dict] = {}

    def load_all(self) -> int:
        """載入 workflows_dir 下所有 .yaml 檔案。回傳載入數量。"""
        count = 0
        if not self.workflows_dir.is_dir():
            return 0
        for f in sorted(self.workflows_dir.glob("*.yaml")):
            try:
                with open(f, encoding="utf-8") as fh:
                    definition = yaml.safe_load(fh)
                if definition and "id" in definition:
                    self._definitions[definition["id"]] = definition
                    count += 1
            except Exception:
                pass
        return count

    def list_workflows(self) -> list[dict]:
        """列出所有已載入的工作流。"""
        return [
            {
                "id": d["id"],
                "name": d.get("name", d["id"]),
                "description": d.get("description", ""),
                "steps": len(d.get("steps", [])),
            }
            for d in self._definitions.values()
        ]

    def get_definition(self, workflow_id: str) -> dict | None:
        return self._definitions.get(workflow_id)

    async def run(
        self,
        workflow_id: str,
        params: dict | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> RunContext:
        """執行指定工作流，可選擇性傳入進度回報 callback。"""
        definition = self._definitions.get(workflow_id)
        if definition is None:
            ctx = RunContext(workflow_id, params)
            ctx.fail(f"Workflow not found: {workflow_id}")
            return ctx

        ctx = RunContext(workflow_id, params)
        ctx.progress_callback = progress_callback
        steps = definition.get("steps", [])
        ctx.start(len(steps))

        # 通知：工作流開始
        await self._emit(ctx, ProgressEvent(
            event_type=EventType.WORKFLOW_START,
            total_steps=len(steps),
            message=f"🚀 開始執行 {workflow_id}（{len(steps)} 步）",
        ))

        try:
            await self._execute_steps(steps, ctx)
            if ctx.error is None:
                ctx.complete()
                # 通知：工作流完成
                elapsed_ms = int((time.time() - ctx.started_at.timestamp()) * 1000) if ctx.started_at else 0
                await self._emit(ctx, ProgressEvent(
                    event_type=EventType.COMPLETE,
                    message=f"✅ 全部完成（{elapsed_ms}ms）",
                ))
        except Exception as e:
            ctx.fail(str(e))
            await self._emit(ctx, ProgressEvent(
                event_type=EventType.ERROR,
                message=str(e),
            ))

        return ctx

    async def _emit(self, ctx: RunContext, event: ProgressEvent) -> None:
        """發射進度事件（若有 callback）。"""
        cb = getattr(ctx, "progress_callback", None)
        if cb is not None:
            try:
                await cb(event)
            except Exception:
                pass  # 進度回報失敗不影響工作流執行

    async def _execute_steps(self, steps: list[dict], ctx: RunContext) -> None:
        """依序執行步驟列表，支援四種控制流程。"""
        for step in steps:
            if ctx.error:
                break

            step_type = step.get("type", "skill")
            ctx.current_step += 1

            if step_type == "skill":
                await self._execute_skill_step(step, ctx)
            elif step_type == "condition":
                await self._execute_condition_step(step, ctx)
            elif step_type == "loop":
                await self._execute_loop_step(step, ctx)
            elif step_type == "parallel":
                await self._execute_parallel_step(step, ctx)
            else:
                ctx.fail(f"Unknown step type: {step_type}")
                break

    async def _execute_skill_step(self, step: dict, ctx: RunContext) -> None:
        """執行單一 Skill 步驟，發射進度事件。"""
        step_id = step.get("id", f"step_{ctx.current_step}")
        skill_id = step.get("skill")
        raw_params = step.get("params", {})

        # 通知：步驟開始
        await self._emit(ctx, ProgressEvent(
            event_type=EventType.STEP_START,
            step_id=step_id,
            step_index=ctx.current_step,
            total_steps=ctx.total_steps,
            message=f"⏳ [{ctx.current_step}/{ctx.total_steps}] {step_id}...",
        ))

        start_time = time.time()

        # Jinja2 模板解析參數
        resolved_params = self._resolve_params(raw_params, ctx)

        # 將 progress_callback 傳入 Skill 參數（供 LLM Skill 串流使用）
        cb = getattr(ctx, "progress_callback", None)
        if cb is not None:
            resolved_params["_progress_callback"] = cb

        result = await self.registry.invoke(skill_id, resolved_params)

        elapsed_ms = int((time.time() - start_time) * 1000)

        if result.success:
            output_key = step.get("output", step_id)
            ctx.set_step_output(output_key, result.data)
            # 通知：步驟完成
            await self._emit(ctx, ProgressEvent(
                event_type=EventType.STEP_DONE,
                step_id=step_id,
                step_index=ctx.current_step,
                total_steps=ctx.total_steps,
                data=elapsed_ms,
                message=f"✅ [{ctx.current_step}/{ctx.total_steps}] {step_id} ({elapsed_ms}ms)",
            ))
        else:
            on_error = step.get("on_error", "fail")
            # 通知：步驟失敗
            await self._emit(ctx, ProgressEvent(
                event_type=EventType.STEP_FAILED,
                step_id=step_id,
                step_index=ctx.current_step,
                total_steps=ctx.total_steps,
                message=f"❌ [{ctx.current_step}/{ctx.total_steps}] {step_id}: {result.error}",
            ))
            if on_error == "fail":
                ctx.fail(f"Step {step_id} failed: {result.error}")
            # on_error == "continue" → 繼續下一步

    async def _execute_condition_step(self, step: dict, ctx: RunContext) -> None:
        """條件分支：根據 expression 結果選擇 if_true 或 if_false。"""
        expression = step.get("expression", "False")
        resolved = self._resolve_template(expression, ctx)

        try:
            result = bool(eval(resolved, {"__builtins__": {}}, {}))  # noqa: S307
        except Exception:
            result = False

        branch = step.get("if_true", []) if result else step.get("if_false", [])
        if branch:
            await self._execute_steps(branch, ctx)

    async def _execute_loop_step(self, step: dict, ctx: RunContext) -> None:
        """迴圈：遍歷 items，每次將 item 放入 context。"""
        items_expr = step.get("items", "[]")
        resolved = self._resolve_template(items_expr, ctx)

        try:
            items = eval(resolved, {"__builtins__": {}}, {})  # noqa: S307
        except Exception:
            items = []

        item_var = step.get("item_var", "item")
        body = step.get("steps", [])

        for item in items:
            ctx.set_step_output(item_var, item)
            await self._execute_steps(body, ctx)
            if ctx.error:
                break

    async def _execute_parallel_step(self, step: dict, ctx: RunContext) -> None:
        """平行執行：同時執行多個子步驟。"""
        sub_steps = step.get("steps", [])
        tasks = [self._execute_skill_step(s, ctx) for s in sub_steps]
        await asyncio.gather(*tasks)

    def _resolve_params(self, params: dict, ctx: RunContext) -> dict:
        """解析參數中的 Jinja2 模板。"""
        resolved = {}
        for key, value in params.items():
            if isinstance(value, str) and "{{" in value:
                resolved[key] = self._resolve_template(value, ctx)
            else:
                resolved[key] = value
        return resolved

    def _resolve_template(self, template_str: str, ctx: RunContext) -> str:
        """使用 Jinja2 解析模板字串。"""
        try:
            tmpl = Template(template_str)
            return tmpl.render(
                params=ctx.params,
                outputs=ctx.outputs,
                run_id=ctx.run_id,
            )
        except Exception:
            return template_str
