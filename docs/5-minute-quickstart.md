# 5 分鐘建立你的智能助理

## 第 1 分鐘：安裝

```bash
pip install ark-agent-core
```

## 第 2 分鐘：建立專案

```bash
ark init my-agent
cd my-agent
```

產出的骨架：

```
my-agent/
├── src/server/main.py      # FastAPI app
├── src/skills/internal/    # 你的業務 Skills
├── knowledge/my-project/   # Wiki 知識庫
├── workflows/hello.yaml    # 範例 Workflow
├── .env.example
└── requirements.txt
```

## 第 3 分鐘：設定環境

```bash
cp .env.example .env
pip install -r requirements.txt
```

（如果要用 Gemini，編輯 `.env` 填入 `GEMINI_API_KEY`）

## 第 4 分鐘：啟動

```bash
ark run
```

瀏覽 `http://localhost:8000`：
- `/` — 首頁
- `/api/v1/health` — 健康檢查
- `/api/v1/skills` — 已註冊 Skills（19 個內建）

## 第 5 分鐘：擴充功能

安裝 Kiro Skills：

```bash
git clone https://github.com/igs-paddyyang-tw/ark-kiro-skills.git .kiro/skills
```

在 Kiro IDE 輸入自然語言：
- 「使用 ark-chatbot-generator 加入 Telegram Bot」
- 「使用 ark-wiki-engine 加入 Wiki」
- 「使用 ark-db-query 加入資料庫查詢」

Kiro 會自動產出對應的 Skills 和整合程式碼。

---

## 下一步

- [如何開發自訂 Skill](./custom-skill-guide.md)
- [如何建立 Workflow](./workflow-guide.md)
- [架構總覽](./architecture.md)
