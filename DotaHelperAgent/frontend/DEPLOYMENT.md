# Vue 前端部署指南

## 构建命令

```bash
# 开发环境
npm run dev

# 生产构建
npm run build

# 预览构建结果
npm run preview
```

## 构建产物

构建完成后，会在 `dist` 目录生成以下文件：

```
dist/
├── index.html
├── assets/
│   ├── index-[hash].js
│   ├── index-[hash].css
│   └── ...
└── ...
```

## 部署方式

### 方式一：Nginx 部署

1. 构建前端项目：
```bash
npm run build
```

2. 将 `dist` 目录内容复制到 Nginx 静态目录：
```bash
cp -r dist/* /usr/share/nginx/html/
```

3. Nginx 配置示例：
```nginx
server {
    listen 80;
    server_name your-domain.com;

    root /usr/share/nginx/html;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /api {
        proxy_pass http://localhost:5000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
    }
}
```

### 方式二：Flask 静态文件服务

1. 修改 Flask 后端 `app.py`：

```python
from flask import Flask, send_from_directory
import os

app = Flask(__name__, static_folder='../frontend/dist')

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_frontend(path):
    if path != "" and os.path.exists(app.static_folder + '/' + path):
        return send_from_directory(app.static_folder, path)
    else:
        return send_from_directory(app.static_folder, 'index.html')

@app.route('/api/chat', methods=['POST'])
def chat():
    # ... existing code
    pass
```

2. 构建前端并启动 Flask：
```bash
cd frontend
npm run build
cd ..
python web/app.py
```

### 方式三：Docker 部署

1. 创建 `Dockerfile`：

```dockerfile
# 构建阶段
FROM node:18-alpine as build
WORKDIR /app
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ .
RUN npm run build

# 生产阶段
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

2. 构建并运行：
```bash
docker build -t dota-helper-frontend .
docker run -p 80:80 dota-helper-frontend
```

## 环境变量配置

创建 `.env.production` 文件：

```env
VITE_API_BASE_URL=https://your-api-domain.com
```

## 性能优化

### 构建优化
- ✅ 代码分割 (Code Splitting)
- ✅ Tree Shaking
- ✅ 压缩代码
- ✅ CSS 提取
- ✅ 图片优化

### 运行时优化
- ✅ 懒加载组件
- ✅ 虚拟滚动
- ✅ 缓存策略

## 监控与日志

### 前端监控
- 使用 `console.log` 记录关键操作
- 错误边界捕获组件错误
- 性能监控 API

### 日志收集
- 前端日志发送到后端 API
- 使用 Sentry 等第三方服务

## CI/CD 集成

### GitHub Actions 示例

```yaml
name: Build and Deploy

on:
  push:
    branches: [ main ]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      
      - name: Setup Node.js
        uses: actions/setup-node@v2
        with:
          node-version: '18'
      
      - name: Install dependencies
        run: cd frontend && npm install
      
      - name: Build
        run: cd frontend && npm run build
      
      - name: Deploy
        run: |
          # 部署脚本
```

## 总结

Vue 前端框架迁移完成后，项目具备了现代化的构建和部署能力。通过 Vite 的快速构建和多种部署方式的支持，可以灵活地适应不同的生产环境需求。
