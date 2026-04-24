# ark-agent-core

智能助理框架：Skill 系統 + Workflow 引擎 + LLM 整合。

## 安裝

```bash
pip install ark-agent-core

# 含可選依賴
pip install ark-agent-core[mongodb]    # + pymongo
pip install ark-agent-core[telegram]   # + python-telegram-bot
pip install ark-agent-core[all]        # 全部
```

## 快速開始

```bash
# 建立新專案
ark init my-agent
cd my-agent

# 啟動
ark run
```

## 內建 Skills（19 個）

| 分類 | Skills |
|------|--------|
| 核心 | echo |
| Wiki（8） | wiki_query, wiki_ingest, wiki_lint, wiki_schema, wiki_graph, wiki_hybrid_search, wiki_rag_bridge, wiki_template |
| 資料 | db_query, data_transform |
| 視覺化 | html_chart |
| 追蹤 | cost_tracker |
| 模板 | template_render |
| 匯出 | file_export |
| LLM（4） | llm_analyze, llm_qa, llm_summarize, llm_parse_intent |

## 框架元件

- **Skill 系統**：BaseSkill + SkillRegistry（auto_discover）
- **Workflow 引擎**：YAML 定義工作流（skill/condition/loop/parallel）
- **排程引擎**：APScheduler Cron 定時觸發
- **LLM 整合**：GeminiAdapter（雲端）+ OllamaAdapter（本地）
- **對話管理**：Session + Planner + Memory

## 搭配 Kiro Skills

```bash
git clone https://github.com/igs-paddyyang-tw/ark-kiro-skills.git .kiro/skills
```

32 個 Kiro Skills 食譜，用自然語言觸發產出智能助理功能。

## 授權

MIT
