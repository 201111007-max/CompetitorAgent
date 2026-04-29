# 日志文件说明

## 文件结构

| 文件 | 说明 | 格式 |
|------|------|------|
| app.log | 主应用日志 | 文本 |
| app.json.log | 结构化日志 | JSON |
| error.log | 错误日志 | 文本 |
| agent.log | Agent 组件日志 | 文本 |
| tool.log | 工具调用日志 | 文本 |
| cache.log | 缓存操作日志 | 文本 |
| api.log | API 请求日志 | 文本 |
| web.log | Web 服务日志 | 文本 |

## 日志轮转

- 单个文件最大 10MB
- 保留 5 个备份文件
- 命名格式: {name}.log.1, {name}.log.2, ...

## 日志级别

- DEBUG: 调试信息
- INFO: 一般信息
- WARNING: 警告
- ERROR: 错误
- CRITICAL: 严重错误
