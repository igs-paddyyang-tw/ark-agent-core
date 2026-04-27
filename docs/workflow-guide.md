# 如何建立 Workflow

Workflow 用 YAML 定義，由 WorkflowEngine 執行。

## 基本結構

```yaml
id: my_workflow
name: 我的工作流
description: 描述文字
steps:
  - id: step1
    type: skill
    skill: db_query
    params:
      collection: "player_profiles"
    output: data
```

## 四種步驟類型

### 1. skill — 呼叫 Skill

```yaml
- id: query
  type: skill
  skill: db_query
  params:
    collection: "player_profiles"
    limit: 10
  output: result
```

### 2. condition — 條件分支

```yaml
- id: check
  type: condition
  condition: "outputs.result.count > 0"
  then:
    id: has_data
    type: skill
    skill: template_render
    params:
      template: "找到 {{ count }} 筆"
  else:
    id: no_data
    type: skill
    skill: echo
    params:
      message: "無資料"
```

### 3. loop — 迴圈

```yaml
- id: batch
  type: loop
  items: '["A", "B", "C"]'
  item_var: letter
  step:
    id: process
    type: skill
    skill: echo
    params:
      message: "處理: {{ letter }}"
    output: processed
  output: results
```

### 4. parallel — 平行執行

```yaml
- id: fanout
  type: parallel
  steps:
    - id: query_a
      type: skill
      skill: db_query
      params: { db_path: "a.db" }
    - id: query_b
      type: skill
      skill: db_query
      params: { db_path: "b.db" }
  output: merged
```

## 步驟間傳遞資料

```yaml
- id: step1
  skill: db_query
  output: data   # 存到 outputs.data

- id: step2
  skill: data_transform
  params:
    data: "{{ outputs.data.rows }}"  # 引用上一步結果
```

## 環境變數

```yaml
params:
  api_key: "${MONGO_PASS}"  # 從 .env 讀取
```

## 實戰範例：大客日報

```yaml
id: vip_daily_report
name: 大客玩家每日分析
steps:
  - id: query
    type: skill
    skill: db_query
    params:
      db_type: "mongodb"
      collection: "player_profiles"
      filter:
        vip_level: {$gte: 5}
      limit: 20
    output: vip_data

  - id: analyze
    type: skill
    skill: llm_analyze
    params:
      data: "{{ outputs.vip_data.rows }}"
      context: "分析大客消費行為、流失風險"
    output: insight

  - id: save
    type: skill
    skill: wiki_ingest
    params:
      content: "{{ outputs.insight.analysis }}"
      category: "synthesis"
      page_name: "vip-daily-report"
    output: saved
```

## 觸發 Workflow

```python
from ark_agent_core.workflow.engine import WorkflowEngine

engine = WorkflowEngine(registry)
engine.load_all("workflows/")
ctx = await engine.run("vip_daily_report")
print(ctx.outputs["saved"])
```

## 排程執行

建立 `workflows/schedules/daily.yaml`：

```yaml
id: vip_daily_schedule
workflow_id: vip_daily_report
cron: "0 10 * * *"  # 每日 10:00
enabled: true
```
