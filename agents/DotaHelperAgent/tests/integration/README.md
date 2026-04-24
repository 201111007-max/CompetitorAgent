# Integration Tests

集成测试，测试多个组件之间的交互。

## 测试文件

（当前为空，后续添加）

## 运行测试

```bash
# 运行所有集成测试
pytest integration/ -v
```

## 计划添加的测试

### API + Core 集成测试
- 测试 API 层与 Agent Core 的交互
- 测试 Tool Registry 与具体 Tools 的协作
- 测试 Memory 与 Agent 的数据持久化

### Cache + API Client 集成测试
- 测试缓存与 API 客户端的协同工作
- 测试缓存预热机制
- 测试缓存失效场景

### LLM + Parser 集成测试
- 测试 LLM 与英雄解析器的集成
- 测试 LLM 与物品解析器的集成
- 测试回退机制（LLM 不可用时）

## 依赖

- 多个相关模块
- pytest fixtures
- Mock 对象（按需使用）

## 与 E2E 测试的区别

- **集成测试**: 关注多个组件之间的接口和交互
- **E2E 测试**: 关注完整的用户场景和业务流程
