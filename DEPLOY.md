# 🚀 ModAgent 公网部署指南（云服务器 + Docker）

## 架构

```
[浏览器] → :80/:443 Nginx ─┬─ /api/* → backend (FastAPI :8000)
                            └─ /*     → frontend (Next.js :3000)
```

- **鉴权**：登录页密码 → HMAC token（7 天有效），所有 /api 请求必须携带
  （`AUTH_PASSWORD` 未配置时后端自动进入无鉴权本地模式，公网必须配置）
- **持久化**：`data/` 目录挂载 volume（任务结果、经验库不随容器销毁）

## 一、准备（一次性）

1. **购买云服务器**：腾讯云/阿里云轻量应用服务器，2C2G 起（约 100 元/年）。
   - 系统：Ubuntu 22.04 或 Debian 12
   - 安全组放行：**80**（HTTP）、**443**（HTTPS，可选）、**22**（SSH）

2. **安装 Docker**（服务器上执行）：
   ```bash
   curl -fsSL https://get.docker.com | sh
   sudo systemctl enable --now docker
   ```

## 二、部署

```bash
# 1. 上传项目（本地执行）
scp -r C:\Users\Lawson\Desktop\2026数学建模国赛\mathagent 用户名@服务器IP:~/mathagent

# 2. 配置环境变量（服务器上执行）
cd ~/mathagent
cp deploy/.env.example .env
nano .env
#   必填：AUTH_PASSWORD（访问密码）、AUTH_SECRET（openssl rand -hex 32）、LLM_API_KEY

# 3. 启动
docker compose up -d --build

# 4. 验证
curl http://服务器IP/api/health        # {"status":"ok"}
# 浏览器打开 http://服务器IP → 登录页 → 输入 AUTH_PASSWORD
```

常用运维命令：

```bash
docker compose logs -f backend      # 查看后端日志
docker compose ps                   # 服务状态
docker compose up -d --build        # 更新代码后重新构建
docker compose down && up -d        # 完全重启
```

## 三、HTTPS（可选但推荐）

```bash
# 1. 先确保域名 A 记录指向服务器 IP
# 2. 安装 certbot 并签发证书（nginx 插件自动改配置）
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

certbot 会自动改写 nginx 配置。若用 docker 版 nginx，改为：

```bash
# 生成证书到 deploy/certs/
sudo certbot certonly --standalone -d your-domain.com \
  --cert-path deploy/certs/fullchain.pem --key-path deploy/certs/privkey.pem
# 取消 docker-compose.yml 中 443 端口与证书挂载注释，并启用 deploy/nginx-https.conf
```

## 四、本地开发（不受影响）

```bash
python api.py               # 后端 :8000（未配 AUTH_PASSWORD 时无鉴权，照常使用）
cd frontend && npm run dev  # 前端 :3000（rewrites 代理 /api → :8000）
```

## 五、安全注意

| 事项 | 说明 |
|------|------|
| `AUTH_PASSWORD` 强密码 | 公网任何人可访问登录页，弱密码会被爆破 |
| `AUTH_SECRET` 随机化 | 泄露后 token 可被伪造（openssl rand -hex 32） |
| LLM API Key 不外泄 | 只存在于服务器 .env，前端永远拿不到 |
| 定期备份 `data/` | 经验库（experience.json）和论文产物 |
| 更新代码 | git pull 后 `docker compose up -d --build` |
