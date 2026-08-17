---
name: ecosystem_analysis
description: 生态维度抽取规范（MCP / 插件 / IDE 支持 / 集成 / 仓库活跃度）
---

适用条件：从 GitHub / 插件市场 / 官方文档文本盘点竞品生态能力。

## 抽取规范

- mcp_servers：MCP server 支持情况，每条含 name、vendor（第一方/第三方）、discoverable_via（发现途径）。
- plugins：插件/扩展市场，含 count（数量，无则 0）、rating（评分，无则 0）、top（关键插件名列表）。
- ide_support：支持的 IDE（vscode / jetbrains / terminal 等）。
- integrations：agentic tool-use / 外部工具集成清单。
- repo_activity：仓库活跃度，含 stars、last_release、commits_30d（无数据给 0 或空）。

## 事实边界

- 数据缺失的字段给空/0，不编造；不确定 vendor 归属时不臆测第一方/第三方。

## 披露约束

- 生态信息很少时降低 confidence，summary 注明信息有限。

## 输出结构

```json
{
  "summary": "一句话总结",
  "details": {
    "mcp_servers": [{"name": "server", "vendor": "first-party", "discoverable_via": "docs"}],
    "plugins": {"count": 12, "rating": 4.5, "top": ["vscode-ext"]},
    "ide_support": ["vscode", "terminal"],
    "integrations": ["github"],
    "repo_activity": {"stars": 12000, "last_release": "2026-08-01", "commits_30d": 45}
  },
  "confidence": 0.7
}
```
