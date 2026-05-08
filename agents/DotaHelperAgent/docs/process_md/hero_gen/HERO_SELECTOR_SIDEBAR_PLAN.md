# 英雄选择器侧边栏功能方案

> 创建时间：2026-05-08  
> 状态：待评审

---

## 一、需求概述

### 1.1 功能描述

在现有前端页面新增一个侧边栏，提供英雄选择器功能：
- 用户只需点击一个按钮，即可生成一段格式化的查询文字
- 文字格式：`我方英雄有xx,xx,xx,xx，敌方英雄有xx,xx,xx,xx,xx，推荐我选什么英雄，并简要给出理由`
- 我方英雄数量：0-4个（随机生成）
- 敌方英雄数量：0-5个（随机生成）
- 英雄由后端随机选择，保证唯一性（不重复）
- 生成的文字支持一键复制
- 历史记录保留，方便查看和重用

### 1.2 核心约束

| 约束项 | 说明 |
|--------|------|
| 我方英雄数量 | 0-4 个（后端随机） |
| 敌方英雄数量 | 0-5 个（后端随机） |
| 英雄唯一性 | 同一英雄不能同时出现在我方和敌方 |
| 英雄数据来源 | 后端从本地数据文件获取，保证与游戏数据一致 |

---

## 二、前端修改方案

### 2.1 页面布局调整

**当前布局**：
```
┌──────────────────────────────────────────────────────────┐
│                    聊天区域 (flex: 1)                      │
├──────────────────────────────────────────────────────────┤
│                  日志侧边栏 (450px)                        │
└──────────────────────────────────────────────────────────┘
```

**新布局**：
```
┌──────────────────────────────────────────────────────────┐
│                    聊天区域 (flex: 1)                      │
├──────────────────────────────────────────────────────────┤
│              英雄选择器侧边栏 (350px)                       │
├──────────────────────────────────────────────────────────┤
│                  日志侧边栏 (450px)                        │
└──────────────────────────────────────────────────────────┘
```

### 2.2 侧边栏 UI 结构

```html
<!-- 英雄选择器侧边栏 -->
<div class="hero-sidebar" id="heroSidebar">
    <div class="hero-sidebar-header">
        <h3>🎮 英雄选择器</h3>
        <button onclick="toggleHeroSidebar()" class="close-btn">✕</button>
    </div>

    <!-- 生成按钮 -->
    <div class="generate-section">
        <button onclick="generateHeroQuery()" class="generate-btn" id="generateBtn">
            ✨ 一键生成英雄推荐查询
        </button>
        <p class="hint-text">随机生成我方和敌方英雄，自动生成查询文本</p>
    </div>

    <!-- 生成结果区 -->
    <div class="result-section" id="resultSection" style="display: none;">
        <div class="result-header">
            <span>生成结果</span>
            <button onclick="copyResult()" class="copy-btn" id="copyBtn">📋 复制</button>
        </div>
        <div class="result-content" id="resultContent"></div>
    </div>

    <!-- 历史记录区 -->
    <div class="history-section">
        <div class="section-header">
            <span>历史记录</span>
            <button onclick="clearHistory()" class="clear-btn">🗑️ 清空</button>
        </div>
        <div class="history-list" id="historyList"></div>
    </div>
</div>
```

### 2.3 CSS 样式设计

```css
/* 英雄选择器侧边栏 */
.hero-sidebar {
    width: 350px;
    background: rgba(0, 0, 0, 0.3);
    border-left: 1px solid rgba(255, 255, 255, 0.1);
    display: flex;
    flex-direction: column;
    overflow-y: auto;
}

.hero-sidebar-header {
    padding: 12px 16px;
    background: rgba(0, 0, 0, 0.2);
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.hero-sidebar-header h3 {
    margin: 0;
    font-size: 14px;
    color: #fff;
}

.close-btn {
    background: none;
    border: none;
    color: #fff;
    cursor: pointer;
    font-size: 16px;
}

.generate-section {
    padding: 20px 16px;
    text-align: center;
}

.generate-btn {
    width: 100%;
    padding: 16px;
    background: linear-gradient(135deg, #e94560 0%, #ff6b6b 100%);
    border: none;
    border-radius: 8px;
    color: #fff;
    font-size: 16px;
    font-weight: bold;
    cursor: pointer;
    transition: all 0.2s;
}

.generate-btn:hover {
    transform: scale(1.02);
    box-shadow: 0 4px 12px rgba(233, 69, 96, 0.4);
}

.generate-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
    transform: none;
}

.hint-text {
    font-size: 12px;
    color: #888;
    margin-top: 8px;
    margin-bottom: 0;
}

.result-section {
    padding: 12px 16px;
    border-top: 1px solid rgba(255, 255, 255, 0.1);
}

.result-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
}

.result-header span {
    font-size: 13px;
    color: #fff;
}

.copy-btn {
    background: rgba(255, 255, 255, 0.1);
    border: 1px solid rgba(255, 255, 255, 0.2);
    padding: 4px 12px;
    border-radius: 4px;
    color: #fff;
    font-size: 12px;
    cursor: pointer;
}

.copy-btn:hover {
    background: rgba(255, 255, 255, 0.2);
}

.result-content {
    background: rgba(0, 0, 0, 0.3);
    padding: 12px;
    border-radius: 8px;
    font-size: 13px;
    line-height: 1.6;
    color: #fff;
    word-break: break-all;
    min-height: 60px;
}

.history-section {
    padding: 12px 16px;
    flex: 1;
    overflow-y: auto;
}

.section-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
}

.section-header span {
    font-size: 13px;
    color: #fff;
}

.clear-btn {
    background: none;
    border: none;
    color: #888;
    cursor: pointer;
    font-size: 12px;
}

.clear-btn:hover {
    color: #fff;
}

.history-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
}

.history-item {
    background: rgba(255, 255, 255, 0.05);
    padding: 10px;
    border-radius: 8px;
    cursor: pointer;
    transition: background 0.2s;
}

.history-item:hover {
    background: rgba(255, 255, 255, 0.1);
}

.history-item .time {
    font-size: 10px;
    color: #888;
    margin-bottom: 4px;
}

.history-item .content {
    font-size: 12px;
    color: #ccc;
    line-height: 1.4;
}

/* 切换按钮 */
.hero-sidebar-toggle {
    position: fixed;
    right: 20px;
    bottom: 150px;
    padding: 10px 16px;
    background: linear-gradient(135deg, #00b894 0%, #00cec9 100%);
    border: none;
    border-radius: 24px;
    color: white;
    cursor: pointer;
    box-shadow: 0 4px 12px rgba(0, 184, 148, 0.4);
    z-index: 100;
}
```

### 2.4 JavaScript 功能实现

```javascript
// 全局状态
let history = [];
let heroSidebarVisible = false;

// 生成英雄查询文本
async function generateHeroQuery() {
    const btn = document.getElementById('generateBtn');
    const resultSection = document.getElementById('resultSection');
    const resultContent = document.getElementById('resultContent');
    
    // 禁用按钮，显示加载状态
    btn.disabled = true;
    btn.textContent = '⏳ 生成中...';
    
    try {
        const response = await fetch('/api/generate_hero_query', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        
        const data = await response.json();
        
        if (data.success) {
            // 显示结果
            resultContent.textContent = data.query;
            resultSection.style.display = 'block';
            
            // 保存到历史记录
            saveToHistory(data.query);
        } else {
            alert('生成失败：' + (data.error || '未知错误'));
        }
    } catch (error) {
        console.error('Failed to generate query:', error);
        alert('生成失败：' + error.message);
    } finally {
        // 恢复按钮状态
        btn.disabled = false;
        btn.textContent = '✨ 一键生成英雄推荐查询';
    }
}

// 复制结果
function copyResult() {
    const content = document.getElementById('resultContent').textContent;
    navigator.clipboard.writeText(content).then(() => {
        const btn = document.getElementById('copyBtn');
        btn.textContent = '✅ 已复制';
        setTimeout(() => {
            btn.textContent = '📋 复制';
        }, 2000);
    }).catch(err => {
        console.error('复制失败:', err);
        alert('复制失败');
    });
}

// 保存到历史记录
function saveToHistory(query) {
    const record = {
        id: Date.now(),
        time: new Date().toLocaleString(),
        query: query
    };
    
    history.unshift(record);
    
    // 最多保留50条
    if (history.length > 50) {
        history = history.slice(0, 50);
    }
    
    // 保存到 localStorage
    localStorage.setItem('heroGenHistory', JSON.stringify(history));
    
    renderHistory();
}

// 加载历史记录
function loadHistory() {
    const saved = localStorage.getItem('heroGenHistory');
    if (saved) {
        try {
            history = JSON.parse(saved);
            renderHistory();
        } catch (e) {
            history = [];
        }
    }
}

// 渲染历史记录
function renderHistory() {
    const container = document.getElementById('historyList');
    if (history.length === 0) {
        container.innerHTML = '<p style="color: #888; text-align: center; font-size: 12px;">暂无历史记录</p>';
        return;
    }
    
    container.innerHTML = history.map(item => `
        <div class="history-item" onclick="loadHistoryItem(${item.id})">
            <div class="time">${item.time}</div>
            <div class="content">${item.query}</div>
        </div>
    `).join('');
}

// 加载历史记录项
function loadHistoryItem(id) {
    const item = history.find(h => h.id === id);
    if (!item) return;
    
    document.getElementById('resultContent').textContent = item.query;
    document.getElementById('resultSection').style.display = 'block';
}

// 清空历史记录
function clearHistory() {
    if (confirm('确定要清空所有历史记录吗？')) {
        history = [];
        localStorage.removeItem('heroGenHistory');
        renderHistory();
    }
}

// 切换侧边栏
function toggleHeroSidebar() {
    const sidebar = document.getElementById('heroSidebar');
    const toggle = document.getElementById('heroSidebarToggle');
    heroSidebarVisible = !heroSidebarVisible;
    
    if (heroSidebarVisible) {
        sidebar.style.display = 'flex';
        toggle.style.display = 'none';
    } else {
        sidebar.style.display = 'none';
        toggle.style.display = 'block';
    }
}

// 页面加载时初始化
document.addEventListener('DOMContentLoaded', () => {
    loadHistory();
});
```

### 2.5 前端修改文件清单

| 文件 | 修改类型 | 说明 |
|------|---------|------|
| `web/index.html` | 修改 | 新增侧边栏HTML结构、CSS样式、JavaScript功能 |

---

## 三、后端修改方案

### 3.1 新增 API 接口

#### 3.1.1 生成英雄查询文本接口

**路由**: `POST /api/generate_hero_query`

**功能**: 随机选择我方和敌方英雄，生成格式化的查询文本

**请求参数**: 无

**响应格式**:
```json
{
    "success": true,
    "query": "我方英雄有主宰,影魔，敌方英雄有帕吉,斧王,宙斯，推荐我选什么英雄，并简要给出理由",
    "our_heroes": ["主宰", "影魔"],
    "enemy_heroes": ["帕吉", "斧王", "宙斯"]
}
```

**实现代码**:
```python
import random
import json
from pathlib import Path

@app.route('/api/generate_hero_query', methods=['POST'])
def generate_hero_query():
    """随机生成英雄查询文本"""
    try:
        # 读取英雄数据
        heroes_file = Path(__file__).parent.parent / 'data' / 'heroes_cn.json'
        
        if not heroes_file.exists():
            return jsonify({
                "success": False,
                "error": "英雄数据文件不存在"
            }), 404
        
        with open(heroes_file, 'r', encoding='utf-8') as f:
            heroes_data = json.load(f)
        
        # 提取所有英雄中文名
        all_heroes = [info.get('cn', '') for info in heroes_data.values() if info.get('cn')]
        
        if len(all_heroes) < 9:  # 至少需要9个英雄
            return jsonify({
                "success": False,
                "error": "英雄数据不足"
            }), 500
        
        # 随机选择我方英雄数量（0-4个）
        our_count = random.randint(0, 4)
        
        # 随机选择敌方英雄数量（0-5个）
        enemy_count = random.randint(0, 5)
        
        # 确保总数不超过英雄总数
        total_needed = our_count + enemy_count
        if total_needed > len(all_heroes):
            total_needed = len(all_heroes)
            # 重新分配
            our_count = random.randint(0, min(4, total_needed))
            enemy_count = total_needed - our_count
        
        # 随机选择英雄（保证不重复）
        selected_heroes = random.sample(all_heroes, total_needed)
        
        # 分配我方和敌方
        our_heroes = selected_heroes[:our_count]
        enemy_heroes = selected_heroes[our_count:]
        
        # 生成查询文本
        parts = []
        if our_heroes:
            parts.append(f"我方英雄有{','.join(our_heroes)}")
        if enemy_heroes:
            parts.append(f"敌方英雄有{','.join(enemy_heroes)}")
        
        query = '，'.join(parts) + '，推荐我选什么英雄，并简要给出理由'
        
        return jsonify({
            "success": True,
            "query": query,
            "our_heroes": our_heroes,
            "enemy_heroes": enemy_heroes
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500
```

### 3.2 后端修改文件清单

| 文件 | 修改类型 | 说明 |
|------|---------|------|
| `web/app.py` | 修改 | 新增 `/api/generate_hero_query` 路由 |

---

## 四、数据流设计

### 4.1 查询文本生成流程

```
┌─────────────────────────────┐
│  用户点击生成按钮            │
└──────┬──────────────────────┘
       │
       ▼
┌─────────────────────────────┐
│  前端 POST /api/generate_hero_query │
└──────┬──────────────────────┘
       │
       ▼
┌─────────────────────────────┐
│  后端读取 heroes_cn.json     │
│  随机选择我方英雄（0-4个）    │
│  随机选择敌方英雄（0-5个）    │
│  保证英雄不重复               │
│  生成格式化查询文本           │
└──────┬──────────────────────┘
       │
       ▼
┌─────────────────────────────┐
│  返回查询文本                │
└──────┬──────────────────────┘
       │
       ▼
┌─────────────────────────────┐
│  前端显示结果                │
│  保存到 localStorage         │
│  渲染历史记录                │
└─────────────────────────────┘
```

---

## 五、技术细节

### 5.1 英雄唯一性保证

**后端保证**：
- 使用 `random.sample()` 从英雄池中随机抽取，保证不重复
- 先抽取总数量，再分配给我方和敌方

### 5.2 历史记录存储

**存储位置**: `localStorage`

**存储键**: `heroGenHistory`

**数据结构**:
```json
[
    {
        "id": 1234567890,
        "time": "2026-05-08 20:30:00",
        "query": "我方英雄有主宰,影魔，敌方英雄有帕吉,斧王,宙斯，推荐我选什么英雄，并简要给出理由"
    }
]
```

**容量限制**: 最多保留 50 条记录

### 5.3 英雄数据来源

**数据文件**: `data/heroes_cn.json`

**数据格式**:
```json
{
    "1": {
        "cn": "主宰",
        "en": "Juggernaut"
    },
    "2": {
        "cn": "帕吉",
        "en": "Pudge"
    }
}
```

**优势**:
- 数据本地化，无需调用外部 API
- 保证英雄名称与游戏一致
- 支持中英文对照

---

## 六、测试方案

### 6.1 前端测试

| 测试项 | 测试方法 | 预期结果 |
|--------|---------|---------|
| 生成按钮 | 点击生成按钮 | 显示加载状态，然后显示结果 |
| 复制功能 | 点击复制按钮 | 文本复制到剪贴板，按钮显示"已复制" |
| 历史记录 | 生成后刷新页面 | 历史记录保留 |
| 加载历史 | 点击历史记录 | 显示对应的查询文本 |
| 清空历史 | 点击清空按钮 | 确认清空后，历史记录消失 |

### 6.2 后端测试

| 测试项 | 测试方法 | 预期结果 |
|--------|---------|---------|
| 生成接口 | POST /api/generate_hero_query | 返回格式正确的查询文本 |
| 英雄唯一性 | 多次调用接口 | 每次返回的英雄都不重复 |
| 数量限制 | 检查返回的英雄数量 | 我方0-4个，敌方0-5个 |
| 错误处理 | 删除 heroes_cn.json 后调用接口 | 返回错误信息 |

---

## 七、实施步骤

### 7.1 第一阶段：后端 API 开发

1. 在 `web/app.py` 中新增 `/api/generate_hero_query` 路由
2. 实现英雄随机选择和文本生成逻辑
3. 测试接口返回数据格式

### 7.2 第二阶段：前端 UI 开发

1. 在 `web/index.html` 中新增侧边栏 HTML 结构
2. 添加 CSS 样式
3. 实现生成按钮和结果显示

### 7.3 第三阶段：前端功能开发

1. 实现调用后端接口
2. 实现复制功能
3. 实现历史记录管理

### 7.4 第四阶段：集成测试

1. 测试完整流程
2. 修复发现的问题
3. 优化用户体验

---

## 八、风险评估

### 8.1 技术风险

| 风险项 | 影响 | 应对措施 |
|--------|------|---------|
| 英雄数据文件缺失 | 无法生成查询文本 | 添加错误提示和降级方案 |
| localStorage 容量限制 | 历史记录丢失 | 限制记录数量，定期清理 |
| 浏览器兼容性 | 部分功能不可用 | 使用标准 API，添加降级方案 |

### 8.2 用户体验风险

| 风险项 | 影响 | 应对措施 |
|--------|------|---------|
| 侧边栏过多 | 页面拥挤 | 支持折叠/展开 |
| 生成速度慢 | 用户体验差 | 后端优化，添加加载状态 |

---

## 九、后续优化方向

### 9.1 短期优化

- [ ] 添加生成动画效果
- [ ] 支持一键发送到聊天框

### 9.2 中期优化

- [ ] 支持自定义英雄数量范围
- [ ] 支持导入/导出历史记录
- [ ] 添加英雄角色标签显示（力量、敏捷、智力）

### 9.3 长期优化

- [ ] 与聊天功能集成，一键发送查询
- [ ] 支持从聊天记录自动提取英雄
- [ ] 添加英雄克制关系可视化

---

## 十、总结

本方案通过新增英雄选择器侧边栏，为用户提供一键生成英雄推荐查询文本的功能。方案特点：

1. **后端控制逻辑**：英雄选择和文本生成由后端负责，前端只需调用接口
2. **数据本地化**：英雄数据从本地文件读取，保证准确性
3. **状态持久化**：历史记录使用 localStorage 存储
4. **用户体验**：支持一键复制、历史记录重用、加载状态提示

整体实现难度较低，预计可在短时间内完成开发和测试。
