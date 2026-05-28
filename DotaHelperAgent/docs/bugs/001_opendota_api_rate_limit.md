# Bug: OpenDota API 速率限制导致工具返回空数据

**日期**: 2026-05-27
**状态**: 待解决
**优先级**: 高

---

## 问题描述

### 1. OpenDota API 429 速率限制

当调用 OpenDota API 获取英雄克制数据时，频繁触发 429 错误（速率限制），导致：

- 工具执行返回空数据 `[]`
- Agent 无法正常推荐英雄
- 用户等待时间过长（重试机制等待 70-90 秒）

**日志示例**:
```
API 速率限制 (429)，等待 70 秒后重试 (第 1/3 次)
API 速率限制 (429)，等待 80 秒后重试 (第 2/3 次)
API 速率限制 (429)，等待 90 秒后重试 (第 3/3 次)
API 速率限制，已达到最大重试次数 3
```

### 2. LLM Fallback 未触发

**问题**: 工具返回空数据时，LLM fallback 机制未正确触发

**原因分析**:
- `thought.observations` 包含空列表 `[]`，但 `if not thought.observations:` 检查不满足
- `_llm_fallback_answer` 方法从 `thought.context.get('query')` 获取查询，但 query 存储在 `thought.query`

**已修复**:
- 修改空数据检查逻辑，检查数据内容是否为空
- 修复 `_llm_fallback_answer` 获取 query 的方式

### 3. Trace 复制失败

**问题**: 前端复制 trace ID 功能未实现或失败

**待确认**: 需要检查前端 `ChatBox.vue` 中的复制功能实现

---

## 根本原因

### OpenDota API 限制

| 项目 | 免费用户 | 注册用户 |
|------|---------|---------|
| 请求限制 | 60 次/分钟 | 更高 |
| `/heroes/{id}/matchups` | 每个英雄单独请求 | 同上 |
| 批量接口 | 不存在 | 不存在 |

**问题**: 每次分析克制关系需要请求 124 个英雄的 matchup 数据，远超 API 限制。

---

## 解决方案

### 已实施

1. **API 重试机制修复**
   - 文件: `utils/api_client.py`
   - 修复: `while retries < max_retries` 而不是 `<=`
   - 添加: 达到最大重试次数时直接返回 `None`

2. **LLM Fallback 机制**
   - 文件: `core/agent_controller.py`, `web/app.py`
   - 添加: `_llm_fallback_answer` 方法
   - 添加: 空数据检查逻辑
   - 功能: 当 API 不可用时，直接用 LLM 知识回答

### 待办事项

#### 高优先级

- [ ] **注册 OpenDota API Key**
  - 访问: https://www.opendota.com/
  - 配置: 在 `config.yaml` 中添加 `api_key`
  - 效果: 提高请求限制

- [ ] **实现全量缓存预热**
  - 调用 `/api/cache/warmup` with `{"full_warmup": true}`
  - 缓存所有 124 个英雄的 matchup 数据
  - 减少实时 API 调用

- [ ] **集成 STRATZ API**
  - 文件: 参考 `docs/process_md/STRATZ_API_GUIDE.md`
  - 使用 `heroStats.winWeek` 批量获取英雄胜率
  - 一次请求获取所有英雄数据

#### 中优先级

- [ ] **优化缓存策略**
  - 增加 matchup 数据缓存 TTL（当前可能过短）
  - 实现本地 JSON 文件缓存作为备用数据源
  - 添加缓存预热定时任务

- [ ] **前端 Trace 复制功能**
  - 检查 `ChatBox.vue` 复制按钮实现
  - 确保 trace ID 可复制到剪贴板
  - 添加复制成功/失败提示

#### 低优先级

- [ ] **API 请求队列**
  - 实现请求队列管理
  - 自动控制请求频率
  - 避免触发 429

- [ ] **多 API 源切换**
  - OpenDota 主用
  - STRATZ 备用
  - 自动切换机制

---

## 测试验证

### 测试步骤

1. 启动前后端服务
2. 输入查询: `我方英雄有米拉娜，敌方英雄有陈、神谕者，推荐我选什么英雄`
3. 检查后端日志:
   - `has_valid_data: False` → 应触发 LLM fallback
   - `LLM fallback 回答成功` → 应显示此日志
4. 前端应显示 LLM 直接回答的英雄推荐

### 验证命令

```bash
# 触发全量缓存预热
curl -X POST http://localhost:5000/api/cache/warmup -H "Content-Type: application/json" -d '{"full_warmup": true}'

# 检查缓存状态
curl http://localhost:5000/api/cache/status
```

---

## 相关文件

| 文件 | 修改内容 |
|------|---------|
| `utils/api_client.py` | API 重试逻辑修复 |
| `core/agent_controller.py` | `_llm_fallback_answer` 方法 |
| `web/app.py` | 空数据检查和 LLM fallback 触发 |
| `docs/process_md/STRATZ_API_GUIDE.md` | STRATZ API 批量接口文档 |

---

## 参考资料

- [OpenDota API 文档](https://docs.opendota.com/)
- [STRATZ API 使用指南](../process_md/STRATZ_API_GUIDE.md)
- [Langfuse 监控集成](../process_md/langfuse_p0_integration/)