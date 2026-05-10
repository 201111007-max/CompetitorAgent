# End-to-End Tests

端到端全流程测试，模拟真实用户场景，测试从前端到后端的完整流程。

## 测试文件

- `test_e2e_workflow.py` - 完整的 E2E 工作流测试

## 运行测试

```bash
# 运行所有 E2E 测试
pytest e2e/ -v

# 运行特定测试
pytest e2e/test_e2e_workflow.py -v

# 运行特定测试类
pytest e2e/test_e2e_workflow.py::TestEndToEndHeroCounter -v
pytest e2e/test_e2e_workflow.py::TestEndToEndItemRecommendation -v
```

## 测试场景

### 英雄克制推荐流程
1. 用户输入："对面有军团，我们选什么英雄克制？"
2. API 接收请求并解析英雄名称
3. Agent Controller 执行 ReAct 循环
4. 调用 `analyze_counter_picks` 工具
5. 返回推荐结果

### 出装推荐流程
1. 用户输入："敌法应该出什么装备？"
2. API 解析英雄名称
3. Agent 调用 `recommend_items` 工具
4. 返回出装建议

### 技能加点流程
1. 用户输入："斧王技能怎么加？"
2. API 解析英雄名称
3. Agent 调用 `build_skill_order` 工具
4. 返回技能加点顺序

### 多轮对话
- 测试上下文连续性
- 测试 session_id 保持
- 测试基于历史对话的响应

### 错误处理
- LLM 不可用时的回退
- Agent Controller 未初始化
- API 请求错误处理

### 性能测试
- 响应时间测试 (< 2s)
- 并发请求测试
- 缓存效果测试

## 依赖

- 完整的 Agent 系统（Agent Controller + Tool Registry + Memory）
- Flask test client (e2e_client fixture)
- Mock LLM client

## 注意事项

- E2E 测试需要初始化完整的 Agent 环境
- 使用 Mock 对象避免依赖外部服务
- 测试运行时间较长（~15 秒）
