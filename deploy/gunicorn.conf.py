"""
finnbot · Gunicorn 生产配置（配合 Nginx 反代）
使用：gunicorn -c deploy/gunicorn.conf.py main:app
"""
import os

# 工作目录与后端入口
wsgi_app = "main:app"
chdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 监听：仅本机回环，由 Nginx 对外（HTTPS 终止）
bind = "127.0.0.1:8000"

# 工人：CPU 核心数 * 2 + 1，也可固定值；财税场景并发不高，2~4 即可
workers = int(os.getenv("GUNICORN_WORKERS", "2"))
worker_class = "uvicorn.workers.UvicornWorker"  # 必须：FastAPI 异步
worker_connections = 1000
threads = 2

# 超时：企业微信异步处理，给足时间避免被动回复链路被打断
timeout = 60
keepalive = 5
graceful_timeout = 30

# 进程管理
preload_app = True
max_requests = 1000          # 防止内存缓慢泄漏
max_requests_jitter = 50
reload = False

# 日志
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("GUNICORN_LOGLEVEL", "info")
