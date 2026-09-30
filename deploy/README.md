# finnbot · 生产部署指南（Nginx + HTTPS）

企业微信自建应用的回调 URL **强制要求 HTTPS + 已备案域名**，因此生产环境必须有反向代理做 HTTPS 终止。本目录提供 Nginx 配置示例与完整步骤。

---

## 一、前置条件

- 一台具备**公网 IP** 的服务器（国内需完成 ICP 备案）。
- 一个**已备案**的域名，解析到该服务器（如 `bot.your-domain.com`）。
- 服务器已开放 **80 / 443** 入站（80 用于证书签发，443 用于回调）。
- 后端已按主 README 装好依赖并 `cp .env.example .env` 填好配置。

## 二、安装 Nginx 与证书工具

```bash
# Ubuntu / Debian
sudo apt update && sudo apt install -y nginx certbot python3-certbot-nginx

# CentOS / RHEL
sudo yum install -y nginx certbot
sudo systemctl enable --now nginx
```

## 三、申请免费 HTTPS 证书（Let's Encrypt）

方式 A（推荐，certbot 自动改 Nginx）：先把 `deploy/nginx.conf.example` 里的 80 段和 `server_name` 配好并启用，再执行：
```bash
sudo certbot --nginx -d bot.your-domain.com
```
方式 B（webroot，不改配置）：
```bash
sudo certbot certonly --webroot -w /var/www/certbot -d bot.your-domain.com
```
证书默认落在 `/etc/letsencrypt/live/bot.your-domain.com/`。certbot 会自动续期，无需人工干预。

> 如使用阿里云/腾讯云等国内 CA，可在其控制台申请免费 DV 证书，下载 Nginx 版后改 `ssl_certificate` / `ssl_certificate_key` 路径即可。

## 四、部署 Nginx 配置

```bash
# 1. 复制示例配置
sudo cp deploy/nginx.conf.example /etc/nginx/conf.d/finnbot.conf
#    Ubuntu 也可放 /etc/nginx/sites-available/ 并软链到 sites-enabled

# 2. 把里面的 bot.your-domain.com 改成你的真实域名（两处 server_name）

# 3. 校验语法并生效
sudo nginx -t
sudo nginx -s reload
```

## 五、以守护进程运行后端（systemd）

把 `finnbot` 部署到 `/opt/finnbot`（已含 venv 与 `.env`），使用仓库内置的单元文件：

```bash
# 1. 按实际部署修改 User / 路径（如需）
sudo cp deploy/finnbot.service /etc/systemd/system/finnbot.service
sudo nano /etc/systemd/system/finnbot.service   # 改 WorkingDirectory / EnvironmentFile / ExecStart 路径

# 2. 启动并设置开机自启
sudo systemctl daemon-reload
sudo systemctl enable --now finnbot

# 3. 健康检查
curl http://127.0.0.1:8000/health   # 期望返回 {"status":"ok"}
sudo journalctl -u finnbot -f       # 看后端日志
```

> 后端 `ExecStart` 使用 `deploy/gunicorn.conf.py`（uvicorn worker、本机 8000、超时 60s、自动重启），
> 详见该配置文件注释。

## 六、企业微信后台配置

1. 应用详情 → 接收消息 → 设置 API 接收：
   - URL：`https://bot.your-domain.com/wecom/callback`
   - Token / EncodingAESKey：与 `.env` 中 `WECOM_CALLBACK_TOKEN` / `WECOM_ENCODING_AES` 一致。
2. 应用详情 → 开发者接口 → **可信 IP**：填服务器公网出口 IP（多个用逗号）。
3. 保存时企业微信会发 GET 校验，Nginx→后端 `/health` 正常即可通过。

## 七、验证

- 浏览器/命令行访问 `https://bot.your-domain.com/health` 应返回 ok。
- 在企业微信给应用发"小微企业增值税有什么优惠？"应收到带出处的政策答复。
- 发送"查验 011002300311 12345678 2024-05-12 560.00 123456"应进入发票查验与风险校验流程（未配查验服务商会引导补全）。

## 八、运维提示

- 后端监听 `127.0.0.1:8000`（仅本机），由 Nginx 对外，避免直接暴露。
- 证书到期前 certbot 自动续期；可在 cron 加 `certbot renew --quiet` 兜底。
- 日志：`sudo journalctl -u finnbot -f` 看后端；`/var/log/nginx/access.log` 看回调。
