# 设计文档 08 — CORS 全开 + 无认证

> 对应 `implementation_plan.md` 第 11 节问题 8（P2）

## 1. 问题现状

- `web_app.py:172-177` `allow_origins=["*"]`，任何站点可跨域调用本地分析服务。
- Web 与 MCP 端点无任何认证，`/api/analyze`、`/api/cancel` 等可被任意调用。

## 2. 目标设计

1. **CORS 收紧**：仅允许配置的受信来源。
2. **认证**：为 Web 与 MCP 端点增加鉴权（API Token）。
3. 配置化（结合设计文档 05 的 `security` 配置）。

## 3. 模块/接口设计

### 3.1 CORS 收紧（`web_app.py`）

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=cfg.security.cors_origins,  # 默认 ["http://localhost:8000"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### 3.2 API Token 认证（`web_app.py` + `mcp_server/`）

- 新增 `security.auth_token` 配置（从环境变量 `COMPETITOR_AUTH_TOKEN` 读取，不明文落码）。
- Web：`/api/*` 端点要求 `Authorization: Bearer <token>` 或 `?token=`。
- MCP：握手/请求时校验 token。

```python
def require_auth(request: Request):
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    if token != cfg.security.auth_token:
        raise HTTPException(401, "Unauthorized")
```

### 3.3 配置化

- `security.cors_origins`、`security.auth_token` 纳入 `AppConfig`（见设计文档 05）。
- 未配置 token 时：默认仅允许 localhost 访问（本地开发），生产必须配置。

## 4. 接入方式

```
启动 → load_config() → security 配置
  → CORS 中间件用 cfg.security.cors_origins
  → /api/* 端点 require_auth 校验 token
```

## 5. 验证方式

- **单元测试**：无 token 请求返回 401；错误 token 返回 401；正确 token 通过。
- **集成测试**：跨域请求被 CORS 拒绝；受信来源通过。

## 6. 实现优先级与工作量

- 优先级：**中**（P2，安全）。
- 工作量：约 0.5-1 天。
- 建议与设计文档 05（配置加载）一并实现，token 走环境变量。
