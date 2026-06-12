# 多模态交互能力升级方案

> **文档版本**: v1.0  
> **创建时间**: 2026-06-12  
> **优先级**: P2  
> **预计工作量**: 1-2 周

---

## 一、当前问题分析

### 1.1 现有交互方式

当前 DotaHelperAgent 仅支持文本输入和输出。

**痛点**：
- ❌ 无法展示复杂的游戏数据（地图、英雄位置等）
- ❌ 缺乏语音提醒能力
- ❌ 缺乏可视化展示

---

## 二、改进目标

### 2.1 核心目标

从"文本交互"升级为"多模态交互"系统，实现：

1. **语音播报**：将推荐内容转换为语音
2. **数据可视化**：将数据转换为图表
3. **多模态输出**：支持文本、语音、图表等多种输出方式

---

## 三、架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                    多模态交互架构                             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ 输入模态     │  │ 输出模态     │  │ 多模态处理器 │      │
│  │              │  │              │  │              │      │
│  │ - 文本       │  │ - 文本       │  │ - 模态识别   │      │
│  │ - 语音       │  │ - 语音       │  │ - 内容转换   │      │
│  │ - 游戏状态   │  │ - 可视化图表 │  │ - 渲染引擎   │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 四、关键组件设计

### 4.1 语音播报

```python
# utils/voice_renderer.py
from typing import str

class VoiceRenderer:
    """语音播报器"""
    
    def __init__(self, engine: str = "azure"):
        self.engine = engine
    
    def render(self, text: str) -> bytes:
        """将文本转换为语音"""
        if self.engine == "azure":
            return self._render_with_azure(text)
        elif self.engine == "google":
            return self._render_with_google(text)
    
    def _render_with_azure(self, text: str) -> bytes:
        """使用 Azure TTS"""
        # 实现 Azure TTS 调用
        pass
    
    def _render_with_google(self, text: str) -> bytes:
        """使用 Google TTS"""
        # 实现 Google TTS 调用
        pass
```

### 4.2 数据可视化

```python
# utils/chart_renderer.py
from typing import Dict, Any
import matplotlib.pyplot as plt

class ChartRenderer:
    """图表渲染器"""
    
    def render(self, data: Dict[str, Any], chart_type: str) -> bytes:
        """将数据转换为图表"""
        if chart_type == "bar":
            return self._render_bar_chart(data)
        elif chart_type == "line":
            return self._render_line_chart(data)
        elif chart_type == "pie":
            return self._render_pie_chart(data)
    
    def _render_bar_chart(self, data: Dict) -> bytes:
        """渲染柱状图"""
        fig, ax = plt.subplots()
        ax.bar(data['labels'], data['values'])
        return self._fig_to_bytes(fig)
    
    def _render_line_chart(self, data: Dict) -> bytes:
        """渲染折线图"""
        fig, ax = plt.subplots()
        ax.plot(data['x'], data['y'])
        return self._fig_to_bytes(fig)
    
    def _fig_to_bytes(self, fig) -> bytes:
        """将图表转换为字节"""
        from io import BytesIO
        buf = BytesIO()
        fig.savefig(buf, format='png')
        buf.seek(0)
        return buf.read()
```

### 4.3 多模态输出工具

```python
# tools/multimodal_tools.py
from tools.base import Tool

class MultimodalOutputTool(Tool):
    """多模态输出工具"""
    
    def __init__(self, voice_renderer, chart_renderer):
        super().__init__(
            name="render_multimodal",
            description="渲染多模态内容",
            parameters={
                "content": dict,
                "modality": str  # "text" | "voice" | "chart"
            },
            func=self._render,
            category="multimodal"
        )
        self.voice_renderer = voice_renderer
        self.chart_renderer = chart_renderer
    
    def _render(self, content: dict, modality: str) -> dict:
        """渲染内容"""
        if modality == "text":
            return {"type": "text", "content": content}
        elif modality == "voice":
            audio = self.voice_renderer.render(content['text'])
            return {"type": "voice", "content": audio}
        elif modality == "chart":
            image = self.chart_renderer.render(content['data'], content['chart_type'])
            return {"type": "chart", "content": image}
```

---

## 五、实施步骤

### 第一阶段：语音播报功能（3-4 天）

**任务**:
1. 集成 Azure TTS 或 Google TTS
2. 实现语音播报器
3. 编写单元测试

**交付物**:
- 语音播报功能
- 单元测试通过

---

### 第二阶段：数据可视化功能（3-4 天）

**任务**:
1. 集成 Matplotlib 或 Plotly
2. 实现图表渲染器
3. 编写单元测试

**交付物**:
- 数据可视化功能
- 单元测试通过

---

### 第三阶段：多模态输出工具（2-3 天）

**任务**:
1. 实现多模态输出工具
2. 集成到 Agent
3. 编写集成测试

**交付物**:
- 多模态输出工具
- 集成测试通过

---

## 六、预期收益

| 指标 | 当前 | 升级后 | 提升 |
|------|------|--------|------|
| **用户满意度** | 80% | 95% | +19% |
| **用户留存率** | 65% | 85% | +31% |

---

> **文档版本**: v1.0  
> **最后更新**: 2026-06-12
