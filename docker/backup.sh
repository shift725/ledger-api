#!/usr/bin/env bash
# 每日資料庫備份：匯出 → 驗證 → 加密 → 上傳 → 回報。由 deploy 帳號的 cron 執行。
# 任何一步失敗就中止、不回報。healthchecks.io 收不到回報才告警，
# 所以「跑到一半失敗」和「cron 根本沒跑」走同一條告警路徑。
set -euo pipefail

cd "$(dirname "$0")/.."
# 金鑰獨立成檔不放 .env：env_file 會把 .env 整份注入 web/worker/beat。
# 濾掉 CR：這份檔案常在 Windows 上編輯，行尾的 CR 會被當成值的一部分。
source <(tr -d '\r' < ./.env.backup)

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
dump="$tmp/ledger.dump"
# 檔名帶主機名：本機測試上傳的檔案不會被誤認成正式備份。
name="db/$(hostname)-$(date -u +%Y%m%dT%H%M%SZ).dump.age"

# POSTGRES_* 在容器內展開（compose 已注入），腳本不必解析 .env。
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > "$dump"

# 完整讀過一次才抓得到截斷與損毀；pg_restore --list 只讀目錄，兩者都抓不到。
# 用 grep -c 不用 grep -q：後者找到就提早退出，pg_restore 收到 SIGPIPE，pipefail 會誤判失敗。
docker compose exec -T db pg_restore -f - < "$dump" | grep -c '^COPY public.ledger_transaction ' > /dev/null

# 主機只有公鑰：加密後連主機自己也解不開這份備份。
age -r "$AGE_RECIPIENT" -o "$dump.age" "$dump"

# Content-MD5 讓 B2 驗證收到的內容；寫入專用金鑰讀不回來，這是唯一的傳輸檢查。
# 開了 Object Lock 的 bucket 也必須帶，否則回 400。
curl -fsS -m 300 --retry 3 \
  --aws-sigv4 "aws:amz:$B2_REGION:s3" --user "$B2_KEY_ID:$B2_APP_KEY" \
  -H "Content-MD5: $(openssl dgst -md5 -binary "$dump.age" | base64)" \
  -T "$dump.age" "https://s3.$B2_REGION.backblazeb2.com/$B2_BUCKET/$name" > /dev/null

echo "$(date -u +%FT%TZ) ok $name $(wc -c < "$dump.age") bytes"
curl -fsS -m 10 --retry 3 "$HC_PING_URL" > /dev/null
