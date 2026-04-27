# schema.md — My Project Wiki Schema

> 繼承 ark-agent-core Wiki v3.0 規範

## 目錄結構

```
knowledge/my-project/
├── raw/         # 唯讀原始資料
├── wiki/        # 結構化知識頁面
├── schema.md    # 本文件
├── index.md     # 索引
└── log.md       # 操作日誌
```

## 頁面 Frontmatter

```yaml
---
title: "頁面標題"
type: concept | entity | source | synthesis
tags: [tag1, tag2]
sources: [raw/來源檔案]
related: [相關頁面]
created: YYYY-MM-DD
updated: YYYY-MM-DD
status: seedling | developing | mature
---
```
