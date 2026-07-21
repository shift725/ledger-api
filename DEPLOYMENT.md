# 部署 Runbook — 從零重建整站（裸 VPS → HTTPS 上線）

> 「主機是 cattle」的證明文件：機器全毀，照這條線走一遍就回來。**唯一不可重建的只有 `.env`（密鑰）與 db volume**，其餘全是可拋的。
> 現行實例值（換域名／主機時只改這幾個）：域名 `shift725-ledger-api.duckdns.org`、部署金鑰 `ledger_deploy`、部署目錄 `/srv/ledger-api`、雲商 AWS Lightsail（東京、Ubuntu 24.04 LTS、2 vCPU／2 GB）。

## 部署拓撲（先看懂形狀）

- **八個容器**：`db`（Postgres）／`redis`（快取＋Celery broker）／`web`（gunicorn）／`worker`＋`beat`（Celery）／`frontend`（nginx 服 SPA＋同源反代 `/api`）／`nginx`（edge，TLS 終止）／`certbot`。
- **入口**：`:443` edge nginx（唯一對外埠）→ 反代 `frontend:80` →（`/api` `/admin` `/static` 再轉）`web:8000`；其餘路徑落 SPA。`:80`→301→`:443`。
- **image 從 GHCR pull**（`ghcr.io/shift725/ledger-api/web`＋`/frontend`，public），主機**不 build**——部署的是 CI 驗過的同一顆 artifact。
- **密鑰唯一正本＝GitHub Secrets**；部署時 render `.env` 上主機。`web`／`redis` 不對外，`:8000`／`:5433` 不 publish（docker publish 走 iptables DNAT 會繞過 ufw，唯一正解是不 publish）。

---

## 前提（先確認這些存在，否則從對應步驟補）

- [ ] GitHub repo 在、`main` 綠、Deploy 管線把 **web＋frontend 兩顆 image 發到 GHCR**（public）。驗：`docker manifest inspect ghcr.io/shift725/ledger-api/web:latest` exit 0。
- [ ] 手上有：一個雲商帳號（本例 AWS Lightsail）、一個可簽 Let's Encrypt 的域名（本例 DuckDNS）、prod 密鑰的值（GitHub Secrets 有存＝可直接取；否則本 runbook Phase 5 現生）。

> 若連 repo／image 都沒了＝全毀重建：先把 repo push 回 GitHub、merge 一次 `main` 讓 Deploy 發 image，再從 Phase 1 起。

---

## Phase 1 — 開 VPS（雲商 console，手動）

1. 開 instance：**東京區、Ubuntu 24.04 LTS、2 vCPU／2 GB**。
2. **Attach 靜態 IP**（不 attach 重開機就換 IP，DNS 會指空）。記下 IP＝`<主機IP>`。
3. **雲商 console 防火牆開 443**（Lightsail 預設只開 22／80；這是 ufw 之外的**第二道牆**，兩道都要開）。
4. 下載雲商預設 SSH 金鑰（第一次以管理帳號 `ubuntu` 登入用）。

## Phase 2 — DNS（DuckDNS，手動）

1. duckdns.org 登入 → 子網域 `current ip` 填 `<主機IP>` → update。
2. 驗：`nslookup <域名>` 要回 `<主機IP>`（沒生效等 1–2 分鐘）。

## Phase 3 — 本機產部署金鑰

```powershell
ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\ledger_deploy" -C "ledger-deploy"   # passphrase 留空（CI 非互動用）
```

產出 `ledger_deploy`（私鑰，之後進 GitHub Secret `DEPLOY_SSH_KEY`）＋`ledger_deploy.pub`（公鑰，下一步放主機）。

---

## Phase 4 — 主機初始化（SSH 進去，以 `ubuntu`）

**全程保持這個 session 開著**（鎖門前先確認鑰匙）。

```bash
ssh -i <雲商金鑰>.pem ubuntu@<主機IP>

# 1 系統更新
sudo apt update && sudo apt full-upgrade -y
# 2 自動安全更新
sudo apt install -y unattended-upgrades
printf 'APT::Periodic::Update-Package-Lists "1";\nAPT::Periodic::Unattended-Upgrade "1";\n' | sudo tee /etc/apt/apt.conf.d/20auto-upgrades
# 3 建 deploy＋放公鑰（貼上 ledger_deploy.pub 的內容）
sudo adduser --disabled-password --gecos "" deploy
sudo install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
echo '<你的 ledger_deploy.pub 內容>' | sudo tee /home/deploy/.ssh/authorized_keys
sudo chmod 600 /home/deploy/.ssh/authorized_keys && sudo chown deploy:deploy /home/deploy/.ssh/authorized_keys
# 4 Docker 官方源（發行版內建版太舊，撐不起 compose 的 !reset 語法）
sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update && sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
# 5 docker group（deploy 免 sudo 跑 docker；注意：docker group ≈ root 等價權限）
sudo usermod -aG docker deploy
# 6 swap 1G（2 GB 機保險）
sudo fallocate -l 1G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
# 7 docker log 輪替（json-file 預設無上限，會撐爆磁碟）
printf '{\n  "log-driver": "json-file",\n  "log-opts": { "max-size": "10m", "max-file": "3" }\n}\n' | sudo tee /etc/docker/daemon.json
sudo systemctl restart docker
# 8 ufw
sudo ufw allow 22/tcp && sudo ufw allow 80/tcp && sudo ufw allow 443/tcp && sudo ufw enable   # 輸入 y
```

### ⚠️ Phase 4b — 驗證關卡（鎖門前先確認鑰匙）

**另開新視窗**，別關 ubuntu session：

```powershell
ssh -i "$env:USERPROFILE\.ssh\ledger_deploy" deploy@<主機IP>     # 要能登入
```

```bash
docker run --rm hello-world     # deploy 免 sudo 要能跑
```

兩項都過，才做 4c。

### Phase 4c — SSH 加固（過 4b 才做）

```bash
# 用 00- 檔名搶在 cloud-init 的 50- 前面（SSH 設定 first-match-wins）
printf 'PasswordAuthentication no\nPermitRootLogin no\n' | sudo tee /etc/ssh/sshd_config.d/00-hardening.conf
sudo sshd -t && sudo sshd -T | grep -iE 'passwordauthentication|permitrootlogin'   # 確認真的是 no
sudo systemctl restart ssh
```

**再開新視窗**驗 deploy 金鑰仍可登入、密碼登入被拒——確認後才可關掉所有 session。

---

## Phase 5 — 上檔案＋建 prod `.env`（以 `deploy`）

主機建目錄（以 ubuntu，sudo）：

```bash
sudo mkdir -p /srv/ledger-api/docker/nginx && sudo chown -R deploy:deploy /srv/ledger-api
```

本機 scp（在 repo 目錄、`main`）：

```powershell
$k="$env:USERPROFILE\.ssh\ledger_deploy"
scp -i $k docker-compose.yml docker-compose.prod.yml deploy@<主機IP>:/srv/ledger-api/
scp -i $k docker/nginx/default.conf.template docker/nginx/ssl-params.conf.template deploy@<主機IP>:/srv/ledger-api/docker/nginx/
```

建 `.env`（以 deploy，`/srv/ledger-api`；真密鑰主機生成）：

```bash
cd /srv/ledger-api
EMAIL='你的@email.com'
SECRET_KEY=$(openssl rand -hex 32); PG_PW=$(openssl rand -hex 24); SU_PW=$(openssl rand -hex 16)
cat > .env <<EOF
SECRET_KEY=$SECRET_KEY
DEBUG=False
ALLOWED_HOSTS=<域名>,localhost,127.0.0.1
POSTGRES_USER=ledger
POSTGRES_PASSWORD=$PG_PW
POSTGRES_DB=ledger
DB_HOST=db
DB_PORT=5432
DJANGO_SUPERUSER_USERNAME=admin
DJANGO_SUPERUSER_EMAIL=$EMAIL
DJANGO_SUPERUSER_PASSWORD=$SU_PW
TLS_BEHIND_PROXY=True
CSRF_TRUSTED_ORIGINS=https://<域名>
DOMAIN_NAME=<域名>
CERTBOT_EMAIL=$EMAIL
COMPOSE_PROFILES=tls
EOF
chmod 600 .env
echo "admin 登入密碼（存好，登 /admin/ 用 email + 這組）: $SU_PW"
docker compose -f docker-compose.yml -f docker-compose.prod.yml config -q && echo "compose OK"
```

> `ALLOWED_HOSTS` **必含 localhost**（web healthcheck 內部打 `http://localhost:8000/healthz`，漏了→400 DisallowedHost→永不 healthy→整棧卡）。密鑰用 `openssl rand -hex`（不含 `@:/`，不拆壞 DATABASE_URL 組合）。

---

## Phase 6 — 憑證首簽＋起站（以 `deploy`）

```bash
cd /srv/ledger-api
dc() { docker compose -f docker-compose.yml -f docker-compose.prod.yml "$@"; }
DOMAIN=<域名>; EMAIL=$(grep '^CERTBOT_EMAIL=' .env | cut -d= -f2)

# 1 dummy 憑證（讓 nginx 443 起得來——先有雞才有蛋的解法）
dc run --rm --entrypoint sh certbot -c "mkdir -p /etc/letsencrypt/live/$DOMAIN && openssl req -x509 -nodes -newkey rsa:2048 -days 1 -keyout /etc/letsencrypt/live/$DOMAIN/privkey.pem -out /etc/letsencrypt/live/$DOMAIN/fullchain.pem -subj '/CN=localhost'"
# 2 起全棧
dc pull && dc up -d --wait --wait-timeout 300 && dc ps
# 3 外部連通檢查（本機跑）：curl -I http://<域名> 要 301
# 4 staging 試簽（先驗流程、不燒正式 rate limit）
dc run --rm --entrypoint sh certbot -c "rm -rf /etc/letsencrypt/live/$DOMAIN /etc/letsencrypt/archive/$DOMAIN /etc/letsencrypt/renewal/$DOMAIN.conf"
dc run --rm --entrypoint certbot certbot certonly --webroot -w /var/www/certbot --staging -d $DOMAIN --email $EMAIL --agree-tos --no-eff-email --non-interactive
#    "Successfully received certificate"（issuer 帶 STAGING）= 通。失敗別往下。
# 5 正式簽
dc run --rm --entrypoint sh certbot -c "rm -rf /etc/letsencrypt/live/$DOMAIN /etc/letsencrypt/archive/$DOMAIN /etc/letsencrypt/renewal/$DOMAIN.conf"
dc run --rm --entrypoint certbot certbot certonly --webroot -w /var/www/certbot -d $DOMAIN --email $EMAIL --agree-tos --no-eff-email --non-interactive
# 6 reload 吃真憑證
dc exec nginx nginx -s reload
# 7 驗續簽路徑（webroot 首簽＝續簽同路徑，故此步必過）
dc run --rm --entrypoint certbot certbot renew --dry-run
```

> 用 **webroot** 不用 standalone：standalone 會把 renewal config 寫成 standalone、日後續簽撞 edge 佔 `:80`。webroot 讓首簽路徑＝續簽路徑。

---

## Phase 7 — 上線驗收

```bash
# 本機（外部）
curl -I https://<域名>          # 200、憑證無錯（issuer=Let's Encrypt 非 STAGING）
curl -I http://<域名>           # 301
```

- [ ] `dc ps` 八個 service healthy／running。
- [ ] 瀏覽器 `https://<域名>` 綠鎖＋登入頁；`/admin/` 是 Django（email＋SU_PW 登入）。
- [ ] 手機裝 PWA→離線記一筆→回線同步（PWA 只在 secure context／HTTPS 運作）。
- [ ] SSL Labs 掃 `<域名>` ≥ A。
- [ ] 外掃 `:8000`／`:5433` closed。

---

## GitHub Secrets（啟用自動部署與 rollback 所需）

站手動上線後，設好這 **5 筆 repo Secrets**，此後 push `main` 即自動部署（Deploy workflow：build→push GHCR→SSH pull＋起棧→部署後 smoke）。

| Secret | 內容 | 來源 |
|---|---|---|
| `DEPLOY_HOST` | 主機公開 IP | Phase 1 的 `<主機IP>` |
| `DEPLOY_USER` | `deploy` | Phase 4 建的部署使用者 |
| `DEPLOY_SSH_KEY` | `ledger_deploy` **私鑰全文**（`-----BEGIN…END-----`） | Phase 3 |
| `DEPLOY_KNOWN_HOSTS` | 主機 SSH 指紋（釘死防 MITM，**絕不** `StrictHostKeyChecking=no`） | 本機 `ssh-keyscan <主機IP>` 的輸出貼上 |
| `DEPLOY_ENV_FILE` | Phase 5 的 `.env` **全文** | Phase 5 |

> 密鑰唯一正本自此在 GitHub Secrets；部署時 render `.env` 上機（本 run 另追加 `IMAGE_TAG`）。主機上的 `.env` 是可覆蓋的 cattle（部署會先留一份 `.env.bak` 當救生索）。**任何密鑰都不烤進 image、不進 repo、不進 log。**

---

## 監測（uptime）

站掉線要第一時間知道。用免費 HTTP uptime 監測（UptimeRobot 級）打健康端點：

- **監測 URL**：`https://<域名>/healthz` → 回 200 JSON `{"status":"ok","checks":{"db":"ok","cache":"ok"}}`；db 或 cache 掛→**503**，監測即告警。
- **為何打 `/healthz` 而非 `/`**：`/healthz` 實查 db＋cache（後端真健康）；`/` 只是靜態 SPA（前端活著、後端掛也回 200＝假綠）。
- `/healthz` 免認證免限流（服務級探針），5 分鐘一發不吃 API 額度。

設定步驟（需一個免費帳號，手動）：

1. 註冊 UptimeRobot（或 healthchecks.io 等）免費帳號。
2. New Monitor → 型別 HTTP(s) → URL 填 `https://<域名>/healthz` → 間隔 5 分鐘 → 預期 200。
3. Alert Contact 設 email（站掛即收信）。

---

## 日常維運

**更新到最新**：push `main` 即自動部署。手動一行（斷網等最後手段）：

```bash
cd /srv/ledger-api && docker compose -f docker-compose.yml -f docker-compose.prod.yml pull \
  && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

**Rollback 到某版**（image `sha-<commit>` tag 不可變）：主要走 **GitHub Actions → Deploy → Run workflow → 填 `image_tag=sha-<舊commit>`**（跳過 build、直部該版＋自動 smoke，全程 Actions log 可見）。主機手動一行是斷網等最後手段：

```bash
IMAGE_TAG=sha-<舊commit> docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

**換域名**：改 `.env` 的 `DOMAIN_NAME`／`ALLOWED_HOSTS`／`CSRF_TRUSTED_ORIGINS`（同步更新 GitHub Secret `DEPLOY_ENV_FILE`）＋DNS 指過來＋重跑 Phase 6 簽一張新證。零程式碼返工。

**DB 備份／還原**（手動一次性）：

```bash
docker compose exec -T db pg_dump -U ledger ledger > backup-$(date +%F).sql   # 備份
docker compose exec -T db psql   -U ledger ledger < backup.sql                # 還原
```

---

## 一頁速記（順序）

1 VPS（東京／Ubuntu／2 GB／靜態 IP／**console 開 443**）→ 2 DNS → 3 本機產金鑰 → 4 主機 init（含 docker 官方源、**驗證關卡、cloud-init 加固陷阱**）→ 5 scp＋`.env`（**ALLOWED_HOSTS 含 localhost**）→ 6 憑證（**dummy→staging→正式→reload**）→ 7 驗收 → 設 GitHub Secrets（自動部署上線）→ 監測。

唯一不可重建的：`.env`（密鑰）＋db volume。其餘全是 cattle。
