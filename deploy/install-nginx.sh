#!/usr/bin/env bash
set -euo pipefail
if [[ $EUID -ne 0 ]]; then
    echo '請使用 sudo bash 執行此安裝指令。' >&2
    exit 1
fi
config_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
target=/etc/nginx/conf.d/polimax-next.conf
backup=''
if [[ -e "$target" ]]; then
    backup="${target}.backup.$(date +%Y%m%d%H%M%S)"
    cp -p -- "$target" "$backup"
fi
restore_config() {
    if [[ -n "$backup" ]]; then cp -p -- "$backup" "$target"; else rm -f -- "$target"; fi
}
install -m 0644 -- "$config_dir/polimax-next.conf" "$target"
if ! nginx -t; then
    restore_config
    echo '設定檢查失敗，已還原；未重新載入 Nginx。' >&2
    exit 1
fi
if ! systemctl reload nginx; then
    restore_config
    echo '重新載入失敗，已還原設定，請查看 Nginx 狀態。' >&2
    exit 1
fi
# A successful reload signal can return before the new workers accept requests.
verified=0
for attempt in {1..20}; do
    if health=$(curl --fail --silent --show-error --max-time 2 -H 'Host: 163.18.26.228' http://127.0.0.1/api/health 2>/dev/null); then
        if [[ "$health" == *'"ok":true'* ]]; then
            printf '%s\n' "$health"
            verified=1
            break
        fi
    fi
    sleep 0.25
done
if [[ "$verified" -ne 1 ]]; then
    echo 'Nginx 已重新載入，但健康檢查尚未通過；請檢查 5174 服務與代理日誌。' >&2
    exit 1
fi
printf 'POLIMAX 入口：http://163.18.26.228/\n'
