"""Conversation Planner：分析對話狀態，決定下一步動作。"""

import json
import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ark_agent_core.conversation.session import Session, SessionState

logger = logging.getLogger(__name__)


def _load_prompt(category: str) -> str | None:
    """嘗試載入 prompt 模板（延遲匯入，避免硬依賴）。"""
    try:
        from ark_agent_core.llm.prompts import load_prompt
        return load_prompt(category)
    except ImportError:
        return None


class PlanAction(Enum):
    EXECUTE = "execute"      # 參數充足 → 執行
    CLARIFY = "clarify"      # 缺參數 → 詢問
    ANSWER = "answer"        # RAG 問答
    RESET = "reset"          # 取消重來
    REMEMBER = "remember"    # 偵測偏好 → 確認 → 寫 memory


@dataclass
class ExecutionPlan:
    """Planner 產出的執行計畫。"""
    action: PlanAction
    workflow_id: str = ""
    params: dict = None
    clarify_question: str = ""
    clarify_options: list[str] = None
    answer_context: str = ""
    memory_key: str = ""
    memory_value: str = ""

    def __post_init__(self):
        if self.params is None:
            self.params = {}
        if self.clarify_options is None:
            self.clarify_options = []

    def to_dict(self) -> dict:
        return {
            "action": self.action.value,
            "workflow_id": self.workflow_id,
            "params": self.params,
            "clarify_question": self.clarify_question,
            "clarify_options": self.clarify_options,
        }


# 意圖 → 工作流對應
INTENT_WORKFLOW_MAP = {
    "query_kpi": "daily_kpi",
    "query_revenue": "daily_kpi",
    "generate_report": "daily_kpi",
    "vip_analysis": "vip_daily_analysis",
    "weekly_insight": "weekly_insight",
}

# 各工作流所需參數
WORKFLOW_REQUIRED_PARAMS = {
    "daily_kpi": ["date"],
    "weekly_review": ["week"],
    "vip_daily_analysis": ["date"],
    "weekly_insight": ["week"],
    "hello": [],
}


class ConversationPlanner:
    """LLM 驅動的對話規劃器，分析 Session 狀態與意圖，產出 ExecutionPlan。"""

    def __init__(
        self,
        llm_adapter: Any | None = None,
        memory_store: Any | None = None,
    ) -> None:
        """初始化 ConversationPlanner。

        Args:
            llm_adapter: LLMAdapter 實例，None 時降級為關鍵字比對
            memory_store: MemoryStore 實例，None 時不載入使用者記憶
        """
        self.llm = llm_adapter
        self.memory = memory_store

    async def parse_intent(self, session: Session) -> dict:
        """呼叫 LLM 進行意圖解析，帶入最近 5 輪對話歷史與使用者記憶。

        回傳: {"intent": str, "confidence": float, "params": dict, "workflow_id": str}
        降級: LLM 不可用或呼叫失敗時使用關鍵字比對。
        """
        # 無 LLM → 直接降級為關鍵字比對
        if self.llm is None:
            return self._keyword_intent(session)

        try:
            # 載入 prompt 模板
            system_prompt = _load_prompt("intent_parse")
            if not system_prompt:
                logger.warning("intent_parse prompt 模板不存在，降級為關鍵字比對")
                return self._keyword_intent(session)

            # 取最近 5 輪對話歷史
            recent_turns = session.get_recent_turns(5)
            conversation_lines = [
                f"[{t.role}] {t.content}" for t in recent_turns
            ]
            conversation_history = "\n".join(conversation_lines)

            # 取使用者記憶
            memory_context = ""
            if self.memory is not None:
                try:
                    user_memory = self.memory.read(session.user_id)
                    if user_memory:
                        memory_lines = [
                            f"{k}: {v}" for k, v in user_memory.items()
                        ]
                        memory_context = "\n".join(memory_lines)
                except Exception as e:
                    logger.warning("讀取使用者記憶失敗: %s", e)

            # 取最後一則使用者訊息
            user_message = ""
            if session.turns:
                user_message = session.turns[-1].content

            # 格式化 system prompt
            formatted_system = system_prompt.format(
                memory_context=memory_context or "無",
                conversation_history=conversation_history or "無",
                user_message=user_message,
            )

            # 呼叫 LLM
            result = await self.llm.generate(
                prompt=user_message,
                system=formatted_system,
                tier="FAST",
            )

            # 解析 JSON 回應（處理 LLM 可能包裹額外文字的情況）
            response_text = result.get("text", "").strip()
            logger.debug("LLM 意圖解析原始回應: %s", response_text[:200])
            intent_data = self._extract_json(response_text)
            logger.debug("LLM 意圖解析結果: %s", intent_data)

            # 確保回傳結構完整
            return {
                "intent": intent_data.get("intent", "unknown"),
                "confidence": float(intent_data.get("confidence", 0.0)),
                "params": intent_data.get("params", {}),
                "workflow_id": intent_data.get("workflow_id", ""),
            }

        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.warning("LLM 意圖解析 JSON 解析失敗: %s", e)
            return self._keyword_intent(session)
        except Exception as e:
            logger.warning("LLM 意圖解析呼叫失敗: %s (type=%s)", e, type(e).__name__, exc_info=True)
            return self._keyword_intent(session)

    @staticmethod
    def _extract_json(text: str) -> dict:
        """從 LLM 回應文字中提取 JSON 物件（dict）。

        處理以下情況：
        - 純 JSON 字串
        - JSON 前後有額外文字（如 markdown code block）
        - 包含 <think>...</think> 標籤（qwen3 thinking mode）
        - json.loads 回傳非 dict 型別（如字串、陣列）→ 繼續嘗試其他提取方式
        """
        if not text:
            raise ValueError("空回應")

        # 移除 <think>...</think> 標籤（qwen3 thinking mode）
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

    def _keyword_intent(self, session: Session) -> dict:
        """關鍵字比對降級方案：使用靜態 INTENT_WORKFLOW_MAP 進行意圖分類。

        Returns:
            {"intent": str, "confidence": 0.5, "params": {}, "workflow_id": str}
        """
        # 取最後一則使用者訊息
        user_message = ""
        if session.turns:
            user_message = session.turns[-1].content
        msg_lower = user_message.lower()

        # 關鍵字比對
        for intent_key, workflow_id in INTENT_WORKFLOW_MAP.items():
            # 將 intent key 中的底線拆成關鍵字
            keywords = intent_key.replace("_", " ").split()
            if any(kw in msg_lower for kw in keywords):
                return {
                    "intent": intent_key,
                    "confidence": 0.5,
                    "params": {},
                    "workflow_id": workflow_id,
                }

        # 常見中文關鍵字比對
        keyword_patterns: list[tuple[list[str], str, str]] = [
            (["kpi", "營收", "報表", "revenue"], "query_kpi", "daily_kpi"),
            (["報告", "report", "產生"], "generate_report", "daily_kpi"),
            (["vip", "大客", "儲值", "玩家分析"], "vip_analysis", "vip_daily_analysis"),
            (["週報", "weekly", "每週"], "weekly_insight", "weekly_insight"),
            (["wiki", "知識", "查詢"], "wiki_query", ""),
            (["取消", "cancel", "重來", "reset"], "reset", ""),
            (["記憶", "memory", "偏好"], "memory_manage", ""),
            (["狀態", "status", "系統"], "system_status", ""),
        ]

        for keywords, intent_name, workflow_id in keyword_patterns:
            if any(kw in msg_lower for kw in keywords):
                return {
                    "intent": intent_name,
                    "confidence": 0.5,
                    "params": {},
                    "workflow_id": workflow_id,
                }

        # 未匹配 → 當作一般問答
        return {
            "intent": "rag_chat",
            "confidence": 0.3,
            "params": {},
            "workflow_id": "",
        }

    async def extract_params(self, session: Session, missing_params: list[str]) -> dict:
        """呼叫 LLM 從使用者最新回覆中提取指定參數值。

        Args:
            session: 當前 Session
            missing_params: 待提取的參數名稱列表

        Returns:
            成功提取的參數 dict，僅包含 missing_params 中的 key。

        降級: LLM 失敗時使用正則表達式提取。
        """
        if self.llm is None or not missing_params:
            return self._regex_extract_params(session, missing_params)

        try:
            # 載入 prompt 模板
            system_prompt = _load_prompt("param_extract")
            if not system_prompt:
                return self._regex_extract_params(session, missing_params)

            # 取使用者最新回覆
            user_reply = session.turns[-1].content if session.turns else ""

            # 格式化 system prompt
            formatted_system = system_prompt.format(
                missing_params=", ".join(missing_params),
                user_reply=user_reply,
            )

            # 呼叫 LLM
            result = await self.llm.generate(
                prompt=user_reply,
                system=formatted_system,
                tier="FAST",
            )

            # 解析 JSON 回應（處理 LLM 可能包裹額外文字的情況）
            response_text = result.get("text", "").strip()
            extracted = self._extract_json(response_text)

            # 僅回傳 missing_params 中的 key
            return {k: v for k, v in extracted.items() if k in missing_params}

        except Exception as e:
            logger.warning("LLM 參數提取失敗: %s", e)
            return self._regex_extract_params(session, missing_params)

    def _regex_extract_params(self, session: Session, missing_params: list[str]) -> dict:
        """正則表達式降級方案：從使用者回覆中提取常見格式的參數值。

        Args:
            session: 當前 Session
            missing_params: 待提取的參數名稱列表

        Returns:
            成功提取的參數 dict。
        """
        user_reply = session.turns[-1].content if session.turns else ""
        extracted: dict[str, str] = {}

        for param in missing_params:
            if param == "date":
                # 匹配日期格式：YYYY-MM-DD、今天、昨天、本週、上週
                date_patterns: list[tuple[str, str]] = [
                    (r"\d{4}-\d{2}-\d{2}", ""),       # 原始日期字串
                    (r"今天|today", "today"),
                    (r"昨天|yesterday", "yesterday"),
                    (r"本週|this week", "this_week"),
                    (r"上週|last week", "last_week"),
                ]
                for pattern, mapped_value in date_patterns:
                    match = re.search(pattern, user_reply, re.IGNORECASE)
                    if match:
                        # 若 mapped_value 為空，使用匹配到的原始字串
                        extracted["date"] = mapped_value or match.group()
                        break

            elif param == "week":
                # 匹配週次：本週、上週
                if "本週" in user_reply or "this week" in user_reply.lower():
                    extracted["week"] = "current"
                elif "上週" in user_reply or "last week" in user_reply.lower():
                    extracted["week"] = "last"

            elif param == "department":
                # 匹配部門名稱
                dept_map = {"全部": "all", "業務部": "sales", "技術部": "tech"}
                for cn, en in dept_map.items():
                    if cn in user_reply:
                        extracted["department"] = en
                        break

            elif param == "format":
                # 匹配輸出格式
                for fmt in ["markdown", "csv", "pdf"]:
                    if fmt in user_reply.lower():
                        extracted["format"] = fmt
                        break

        return extracted

    async def plan(
        self,
        session: Session,
        intent: dict,
        memory: dict | None = None,
    ) -> ExecutionPlan:
        """根據意圖和 Session 狀態決定下一步（async 以支援 LLM 呼叫）。

        路由邏輯：
        - 取消指令 → RESET
        - RAG / Wiki 問答 → ANSWER
        - 系統狀態 / 記憶管理 → 對應動作
        - 信心度 < 0.7 → 導向 RAG 問答
        - 工作流不存在 → 導向 RAG 問答
        - 信心度 ≥ 0.7 且工作流存在 → 檢查參數完整度 → EXECUTE 或 CLARIFY

        Args:
            session: 當前 Session
            intent: {"intent": str, "confidence": float, "params": dict}
            memory: 使用者記憶 dict
        """
        memory = memory or {}
        intent_name = intent.get("intent", "unknown")
        intent_params = intent.get("params", {})
        confidence = intent.get("confidence", 0.0)

        # 取消指令
        if intent_name == "reset" or any(
            kw in (session.turns[-1].content if session.turns else "")
            for kw in ["取消", "cancel", "重來"]
        ):
            session.state = SessionState.IDLE
            session.clarify_count = 0
            return ExecutionPlan(action=PlanAction.RESET)

        # RAG 問答類（明確的問答意圖，不受信心度門檻影響）
        if intent_name in ("rag_chat", "wiki_query"):
            session.state = SessionState.EXECUTING
            query = intent_params.get("query", "")
            if not query and session.turns:
                query = session.turns[-1].content
            return ExecutionPlan(
                action=PlanAction.ANSWER,
                answer_context=query,
            )

        # 系統狀態
        if intent_name == "system_status":
            return ExecutionPlan(action=PlanAction.EXECUTE, workflow_id="", params={"type": "status"})

        # 記憶管理
        if intent_name == "memory_manage":
            return ExecutionPlan(
                action=PlanAction.REMEMBER,
                memory_key=intent_params.get("key", ""),
                memory_value=intent_params.get("value", ""),
            )

        # 信心度不足 → 導向 RAG 問答
        if confidence < 0.7:
            query = session.turns[-1].content if session.turns else ""
            return ExecutionPlan(action=PlanAction.ANSWER, answer_context=query)

        # 工作流執行類（信心度 ≥ 0.7）
        workflow_id = INTENT_WORKFLOW_MAP.get(intent_name, "")
        if not workflow_id:
            # 工作流不存在 → 當作問答
            query = session.turns[-1].content if session.turns else ""
            return ExecutionPlan(action=PlanAction.ANSWER, answer_context=query)

        # 檢查參數完整度
        required = WORKFLOW_REQUIRED_PARAMS.get(workflow_id, [])
        resolved_params = self._resolve_params(
            required, intent_params, memory, session, workflow_defaults={},
        )
        missing = [p for p in required if p not in resolved_params]

        if missing and session.clarify_count < session.max_clarify:
            # 參數不足 → 釐清
            session.state = SessionState.CLARIFYING
            session.clarify_count += 1
            question, options = self._build_clarify(missing[0])
            return ExecutionPlan(
                action=PlanAction.CLARIFY,
                workflow_id=workflow_id,
                params=resolved_params,
                clarify_question=question,
                clarify_options=options,
            )

        if missing:
            # 超過釐清上限 → 套用強制預設值執行
            for p in missing:
                resolved_params[p] = self._force_default_value(p)

        session.state = SessionState.EXECUTING
        session.clarify_count = 0
        session.context["workflow_id"] = workflow_id
        return ExecutionPlan(
            action=PlanAction.EXECUTE,
            workflow_id=workflow_id,
            params=resolved_params,
        )

    def _resolve_params(
        self,
        required: list[str],
        intent_params: dict,
        memory: dict,
        session: Session,
        workflow_defaults: dict | None = None,
    ) -> dict:
        """五層優先順序解析參數：
        (1) 當前訊息提取 → (2) Session 上下文 → (3) 使用者記憶 →
        (4) YAML 預設值 → (5) 系統預設值
        """
        workflow_defaults = workflow_defaults or {}
        resolved = {}
        for param in required:
            # 1. 當前意圖參數
            if param in intent_params:
                resolved[param] = intent_params[param]
            # 2. Session context
            elif param in session.context:
                resolved[param] = session.context[param]
            # 3. Memory（使用 preferred_ 前綴）
            elif f"preferred_{param}" in memory:
                resolved[param] = memory[f"preferred_{param}"]
            # 4. YAML 工作流預設值
            elif param in workflow_defaults:
                resolved[param] = workflow_defaults[param]
            # 5. 系統預設值
            else:
                default = self._default_value(param)
                if default:
                    resolved[param] = default
        return resolved

    def _build_clarify(self, param: str) -> tuple[str, list[str]]:
        """根據缺少的參數建立釐清問題和選項。"""
        clarify_map = {
            "date": ("想看哪一天的？", ["今天", "昨天", "本週"]),
            "week": ("想看哪一週？", ["本週", "上週"]),
            "department": ("哪個部門？", ["全部", "業務部", "技術部"]),
            "format": ("要什麼格式？", ["Markdown", "CSV", "PDF"]),
        }
        return clarify_map.get(param, (f"請提供 {param}：", []))

    def _default_value(self, param: str) -> str:
        """參數預設值（僅在釐清次數超過上限時使用）。

        注意：date 和 week 不在此處提供預設值，
        讓系統先透過釐清流程詢問使用者。
        """
        defaults = {
            "department": "all",
            "format": "markdown",
        }
        return defaults.get(param, "")

    def _force_default_value(self, param: str) -> str:
        """強制預設值（釐清次數超過上限時使用，包含所有參數）。"""
        defaults = {
            "date": "yesterday",
            "week": "current",
            "department": "all",
            "format": "markdown",
        }
        return defaults.get(param, "")
