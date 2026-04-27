# My Agent

使用 [ark-agent-core](https://github.com/igs-paddyyang-tw/ark-agent-core) 建立的智能助理。

## 快速開始

```bash
# 1. 安裝依賴
pip install -r requirements.txt

# 2. 設定環境變數
cp .env.example .env

# 3. 啟動
ark run
```

## 目錄結構

```
my-agent/
├── src/
│   ├── server/main.py      # FastAPI app
│   └── skills/internal/    # 業務 Skills（auto_discover）
├── knowledge/              # Wiki 知識庫
│   └── my-project/
├── workflows/              # Workflow YAML
│   └── hello.yaml
├── .env.example
└── requirements.txt
```

## 擴充功能

安裝 Kiro Skills 後，用自然語言觸發產出：

```bash
git clone https://github.com/igs-paddyyang-tw/ark-kiro-skills.git .kiro/skills
```

在 Kiro 中輸入：
- 「使用 ark-chatbot-generator 加入 Telegram Bot」
- 「使用 ark-wiki-engine 加入 Wiki 知識庫」
- 「使用 ark-db-query 加入資料庫查詢」

## 內建 Skills（19 個）

- 核心：echo
- Wiki（8）：wiki_query, wiki_ingest, wiki_lint, wiki_schema, wiki_graph, wiki_hybrid_search, wiki_rag_bridge, wiki_template
- 資料：db_query, data_transform
- 視覺化：html_chart
- 追蹤：cost_tracker
- 模板：template_render
- 匯出：file_export
- LLM（4）：llm_analyze, llm_qa, llm_summarize, llm_parse_intent

## 常用指令

```bash
ark run           # 啟動 server
ark skills        # 列出已註冊 Skills
ark version       # 顯示版本
```
