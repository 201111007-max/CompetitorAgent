# Bug: OpenDota API 速率限制导致工具返回空数据

**日期**: 2026-05-27
**状态**: 已解决
**优先级**: 高
**最后更新**: 2026-05-31

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

3. **数据过期机制（TTL）**
   - 文件: `managers/matchup_data_manager.py`
   - 功能: 数据有效期设置为 7 天
   - 实现: `_is_data_expired()` 检查数据是否过期
   - 实现: `_delete_expired_data()` 删除过期数据
   - 实现: `_wrap_data_with_metadata()` 为数据添加时间戳和 TTL 信息

4. **数据完整性校验**
   - 文件: `managers/matchup_data_manager.py`
   - 功能: 验证数据格式和必要字段
   - 实现: `_validate_data_integrity()` 校验数据完整性
   - 实现: `_delete_invalid_data()` 删除无效数据
   - 检查: 必要字段（hero_id, wins, games_played）和比赛场次（≥10）

5. **动态速率调整**
   - 文件: `utils/background_loader.py`
   - 功能: SmartBackgroundLoader 根据成功率动态调整请求频率
   - 实现: `_adjust_rate_limit()` 动态调整速率
   - 实现: `_handle_429_error()` 处理 429 错误
   - 策略: 连续成功 5 次 → 提高频率 10%，连续失败 2 次 → 降低频率 20%
   - 范围: 最小 0.1 次/秒，最大 2.0 次/秒

6. **单元测试**
   - 文件: `tests/unit/test_matchup_data_manager.py`
   - 功能: 19 个测试用例覆盖所有新增功能
   - 覆盖: 过期检查、完整性校验、数据包装、状态统计等

### 待办事项

#### 高优先级

- [ ] **注册 OpenDota API Key**
  - 访问: https://www.opendota.com/
  - 配置: 在 `config.yaml` 中添加 `api_key`
  - 效果: 提高请求限制

- [x] **实现全量缓存预热**
  - 调用 `/api/cache/warmup` with `{"full_warmup": true}`
  - 缓存所有 124 个英雄的 matchup 数据
  - 减少实时 API 调用

- [ ] **集成 STRATZ API**
  - 文件: 参考 `docs/process_md/STRATZ_API_GUIDE.md`
  - 使用 `heroStats.winWeek` 批量获取英雄胜率
  - 一次请求获取所有英雄数据

#### 中优先级

- [x] **优化缓存策略**
  - 增加 matchup 数据缓存 TTL（已实现 7 天过期机制）
  - 实现本地 JSON 文件缓存作为备用数据源
  - 添加缓存预热定时任务

- [x] **数据过期机制（TTL）**
  - 实现: 数据有效期设置为 7 天
  - 功能: 自动检查和删除过期数据
  - 测试: 已通过单元测试验证

- [x] **数据完整性校验**
  - 实现: 验证数据格式和必要字段
  - 功能: 自动检查和删除无效数据
  - 测试: 已通过单元测试验证

- [x] **动态速率调整**
  - 实现: SmartBackgroundLoader 根据成功率动态调整
  - 功能: 429 错误自动降速并暂停
  - 测试: 已集成到后台加载流程

- [ ] **前端 Trace 复制功能**
  - 检查 `ChatBox.vue` 复制按钮实现
  - 确保 trace ID 可复制到剪贴板
  - 添加复制成功/失败提示

#### 低优先级

- [x] **API 请求队列**
  - 实现: BackgroundLoader 优先级队列
  - 功能: 自动控制请求频率
  - 效果: 避免触发 429

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
| `managers/matchup_data_manager.py` | 数据过期机制、完整性校验、metadata 包装 |
| `utils/background_loader.py` | SmartBackgroundLoader 动态速率调整 |
| `tests/unit/test_matchup_data_manager.py` | 单元测试（19 个测试用例） |
| `docs/process_md/STRATZ_API_GUIDE.md` | STRATZ API 批量接口文档 |

---

## 参考资料

- [OpenDota API 文档](https://docs.opendota.com/)
- [STRATZ API 使用指南](../process_md/STRATZ_API_GUIDE.md)
- [Langfuse 监控集成](../process_md/langfuse_p0_integration/)