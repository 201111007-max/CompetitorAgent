# Vue 前端框架迁移测试指南

## 测试框架变更

### 旧测试框架
- **测试类型**: HTML 静态测试页面
- **测试文件**: `tests/frontend/test_frontend_optimization.html`
- **测试方式**: 浏览器直接打开 HTML 文件
- **测试内容**: 
  - 验证 `sendMessage()` 函数已删除
  - 验证 `sendMessageStream()` 函数存在
  - 验证按钮没有 `onclick` 属性
  - 验证事件监听器绑定

### 新测试框架
- **测试框架**: Vitest + @vue/test-utils
- **测试类型**: 单元测试 + 组件测试
- **测试文件位置**: `frontend/src/**/__tests__/*.test.ts`
- **测试方式**: `npm run test`

## 测试用例变更

### 新增测试用例

#### 1. 组件测试 (`ChatInput.test.ts`)
```typescript
- renders properly
- has input field
- has send button
```

#### 2. Store 测试 (`chat.test.ts`)
```typescript
- initializes with empty messages
- adds message correctly
- sets streaming status
- clears messages
```

### 测试覆盖率

运行 `npm run test:coverage` 可以生成测试覆盖率报告。

## 测试命令

```bash
# 运行测试
npm run test

# 运行测试 UI
npm run test:ui

# 生成覆盖率报告
npm run test:coverage
```

## 测试配置文件

- `vitest.config.ts` - Vitest 配置
- `package.json` - 测试脚本配置

## 迁移影响

### 已移除的测试
- ❌ `test_frontend_optimization.html` (HTML 静态测试)

### 新增的测试
- ✅ 组件单元测试
- ✅ Store 单元测试
- ✅ 测试覆盖率报告

### 测试优势
1. **自动化**: 测试可自动运行，无需手动打开浏览器
2. **CI/CD 友好**: 可集成到持续集成流程
3. **覆盖率**: 可生成详细的测试覆盖率报告
4. **类型安全**: TypeScript 类型检查
5. **组件隔离**: 每个组件独立测试

## 后续测试计划

### 待添加的测试
- [ ] `MessageList.test.ts` - 消息列表组件测试
- [ ] `ThinkingSteps.test.ts` - 思考步骤组件测试
- [ ] `useSSE.test.ts` - SSE 流式处理测试
- [ ] `useChat.test.ts` - 聊天逻辑测试
- [ ] E2E 测试 (Playwright/Cypress)

### 测试最佳实践
1. 每个组件都应有对应的测试文件
2. 测试文件放在 `__tests__` 目录下
3. 测试文件命名: `<ComponentName>.test.ts`
4. 使用 `describe` 组织测试套件
5. 使用 `it` 定义单个测试用例
6. 使用 `expect` 进行断言

## 测试示例

### 组件测试示例
```typescript
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import MyComponent from '@/components/MyComponent.vue'

describe('MyComponent', () => {
  it('renders properly', () => {
    const wrapper = mount(MyComponent)
    expect(wrapper.exists()).toBe(true)
  })
})
```

### Store 测试示例
```typescript
import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useMyStore } from '@/stores/myStore'

describe('My Store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('initializes correctly', () => {
    const store = useMyStore()
    expect(store.items).toEqual([])
  })
})
```

## 总结

前端框架迁移后，测试方式从手动 HTML 测试转变为自动化单元测试。新的测试框架提供了更好的测试体验和更全面的测试覆盖，为项目的持续维护提供了保障。
