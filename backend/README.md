# Bilibili Comment Monitor Backend

这是一个用于监控 B 站视频评论并通知到钉钉的后端服务。

## 部署步骤 (轻量云服务器)

### 1. 环境准备
确保服务器已安装 Python 3.8+。

### 2. 安装依赖
```bash
pip install fastapi uvicorn requests apscheduler pydantic
```

### 3. 运行服务
```bash
python app.py
```
服务默认运行在 `8000` 端口。

## API 说明

### 配置
- `POST /config`: 更新 Cookie、钉钉 Webhook 或检查间隔。

### 视频管理
- `GET /videos`: 获取监控视频列表。
- `POST /videos`: 添加新的监控视频 (传入 `bv_id`)。
- `DELETE /videos/{oid}`: 移除监控视频。

### 任务控制
- `POST /jobs/start`: 启动监控任务。
- `POST /jobs/stop`: 停止监控任务。
- `GET /status`: 查看任务运行状态。
