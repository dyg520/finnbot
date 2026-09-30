#!/usr/bin/env bash
# finnbot 一键部署脚本（在目标 Linux 服务器上以 root 或具 sudo 权限用户执行）
# 用法：
#   ./deploy.sh /opt/finnbot https://github.com/dyg520/finnbot.git
# 第一个参数为部署目录（默认 /opt/finnbot），第二个为仓库地址（默认下方常量）
set -euo pipefail

DEPLOY_DIR="${1:-/opt/finnbot}"
REPO_URL="${2:-https://github.com/dyg520/finnbot.git}"
SERVICE_USER="${3:-www-data}"
PY_VERSION="${4:-3.11}"

echo "===== [1/6] 安装系统依赖 ====="
if command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update -y
  sudo apt-get install -y python3 python3-venv python3-pip git nginx certbot python3-certbot-nginx
elif command -v yum >/dev/null 2>&1; then
  sudo yum install -y python3 python3-pip git nginx certbot
fi

echo "===== [2/6] 拉取代码 ====="
if [ -d "$DEPLOY_DIR/.git" ]; then
  sudo git -C "$DEPLOY_DIR" pull --ff-only
else
  sudo git clone "$REPO_URL" "$DEPLOY_DIR"
fi

echo "===== [3/6] 建虚拟环境并装依赖 ====="
sudo python3 -m venv "$DEPLOY_DIR/.venv"
sudo "$DEPLOY_DIR/.venv/bin/pip" install --upgrade pip
sudo "$DEPLOY_DIR/.venv/bin/pip" install -r "$DEPLOY_DIR/requirements.txt"

echo "===== [4/6] 准备 .env（若不存在则复制模板，请随后手动填值） ====="
if [ ! -f "$DEPLOY_DIR/.env" ]; then
  sudo cp "$DEPLOY_DIR/.env.example" "$DEPLOY_DIR/.env"
  echo "⚠️  已生成 $DEPLOY_DIR/.env，请编辑填入企业微信 CorpID/AgentId/Secret/Token/AESKey 与 LLM_API_KEY"
fi

echo "===== [5/6] 安装 systemd 守护单元 ====="
sudo cp "$DEPLOY_DIR/deploy/finnbot.service" /etc/systemd/system/finnbot.service
sudo sed -i "s#/opt/finnbot#$DEPLOY_DIR#g; s#www-data#$SERVICE_USER#g" /etc/systemd/system/finnbot.service
sudo systemctl daemon-reload
sudo systemctl enable --now finnbot
sleep 2
echo "服务状态："
sudo systemctl is-active finnbot || echo "（服务未 active，请 journalctl -u finnbot 排查）"

echo "===== [6/6] 配置 Nginx + HTTPS ====="
echo "请将下方 Nginx 配置写入 /etc/nginx/sites-available/finnbot 并启用，然后："
echo "  sudo certbot --nginx -d 你的域名"
echo "详细见 deploy/README.md 与 deploy/nginx.conf.example"
echo ""
echo "===== 部署脚本完成 ====="
echo "下一步：1) 填 .env  2) 配 Nginx+HTTPS  3) 企业微信后台填回调 URL  4) 发消息验收"
