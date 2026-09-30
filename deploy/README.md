# 獨立部署與切換

> 獨立部署請先看 [2026-09-30 依賴盤點與搬機清單](STANDALONE.md)。

> 2026-09-22 已切換正式網站至 PostgreSQL；本頁較早的 MySQL 部署敘述為歷史記錄。請先看 [切換紀錄](../POSTGRESQL_MIGRATION_BASELINE.md) 與 [回復草案](../POSTGRESQL_CUTOVER_RUNBOOK.md)。

新版只需要本專案、目前 MySQL、公司 SSO，以及自己的持久資料目錄。不需要舊 Python 專案或舊檔案服務。MySQL 仍使用既有結構，不執行 schema migration。backend/legacy_* 的命名代表資料格式相容，不代表匯入舊專案程式。

## 1. 準備程式與設定

在新主機取得本專案後（Python 3.12、Node.js 20 或更新的相容版本）：

```bash
cd /opt/polimax_next
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
npm ci
npm run build
cp .env.example .env
mkdir -p .data
chmod 700 .data
chmod 600 .env
```

填入目前 MySQL 及公司 SSO 設定，不要直接以範本覆蓋已有的 .env。讀取優先順序為程序環境變數 > .env > env。預設 MySQL／SSO；正式部署不開啟測試登入。PUBLIC_WEB_URL 和 SSO_REDIRECT_URI 必須符合公司登錄值；若網址更動，需要公司 SSO 設定配合。

## 2. 一次性搬入既有資料

應先安排舊入口停止表單寫入，再進行最終複製。以下工具只讀來源及 SQL，不刪除來源或修改 SQL：

```bash
.venv/bin/python scripts/migrate_storage.py \
  --source /path/to/old-project \
  --scan-database \
  --download --file-url https://old-file-service.example
```

工具複製全部回應檔案、權限快照，掃描表單及 SQL 附件欄位，下載附件 bytes 並保留 UUID、檔名、MIME。已存在且相同的表單會略過；不同則停止，避免覆蓋新版變更。首次預先搬移與正式切換之間如舊系統有修改，應在獨立空目錄重新搬移，再於停寫期間核對及切換，不能直接覆蓋已有新版寫入的資料。

.data/migration-report.json 的 complete 必須為 true，否則工具以狀態碼 2 結束，missing 列出未完成附件。無法下載的附件需由管理者取得原檔，補入 .data/files/{uuid} 及對應 {uuid}.json 索引；不可把 HTML 錯誤頁當附件。來源不是本地目錄時，先將舊回應與權限快照匯出到可讀目錄。

持久內容如下：

```text
.data/
  permissions/latest-AMS.json  # 指向同目錄的權限快照
  permissions/<snapshot>.json  # 原有帳號、角色、欄位及擁有者規則
  responses/                   # A/D/E 表單與 B/C 出回程、備份
  files/<uuid>                 # 附件 bytes
  files/<uuid>.json            # 檔名、MIME、大小等索引
  sso/                         # 後端 session/token
  migration-report.json
```

如 .data 搬到另一個主機，可排除 sso/ 讓使用者重新登入。其餘業務資料要完整保留。資料與帳密不在 Git 中，新主機單純 git clone 不會取得它們。

## 3. 啟動與驗收

```bash
npm start
```

此命令在 5173 提供前端及 /api。服務管理可使用 polimax-next.service.example，按實際帳號、路徑與資料目錄調整；範本使用 5174，由既有反向代理轉接。設定外部 AMS_DATA_DIR 時亦須調整 ReadWritePaths。不要同時啟動佔用相同連接埠的服務。

切換前確認 /api/health 可連 MySQL、公司 SSO 可登入、角色權限正確、既有表單可讀、附件可預覽下載。新主機應在沒有舊目錄且無舊檔案服務連線的情況驗收。寫入驗證先在隔離 MySQL 完成，再由使用者確認正式業務流程。

## 4. 權限管理與備份

權限快照已獨立；舊 AMS 再改權限不會自動同步到新版。要更新新版的快照與 manifest，或明確設定 AMS_POLICY_FILE。不要替未授權帳號自動配管理員。管理頁的重新載入只讀新版政策檔，不向外部抓快照。

備份 MySQL 與 .data/responses、.data/files、.data/permissions；兩種儲存需在停寫期間一致備份。不可讓新舊入口同時寫入同一 MySQL 卻各自保存不同 JSON。回復舊程式前也必須一起處理切換後新增的表單與附件，不能僅切回入口。

## 定位與通知

新版讀取目前 MySQL 的定位／通知結果，不依賴舊專案執行檔。但它尚未實作 GPS 裝置接收、Beacon 上游取數或通知排程；這些外部資料生產程序需另外運行或另行移植。部署新版不會自動產生定位資料，也不會補齊空的定位表。

## 本機本次切換紀錄

已在使用者明確接受 15 個歷史附件缺失後切換，保留 UUID，未將缺失標記為已搬移。切換前停寫並核對 280 個表單檔案，5173／5174 與 Nginx 網站及 MySQL health 均成功，SSO 授權跳轉成功。完整結果記錄於 .data/migration-report.json。實際帳號登入仍由使用者確認。

一般切換應完成所有附件；若使用者明確接受列出的缺漏，可保留 complete=false，另記錄接受的 UUID 與切換狀態。不要以 complete=true 隱藏缺失，也不要在切換後重新將舊資料覆蓋新版已更新的表單。


## 本機開機自動啟動（2026-09-15）

本機 `/home/c113118138/polimax_next` 由使用者 systemd 管理：
- `polimax-next@5173.service`：原有直接入口。
- `polimax-next@5174.service`：Nginx 80 埠代理的入口。

服務範本為 `deploy/polimax-next@.service`，已安裝到
`~/.config/systemd/user/polimax-next@.service` 並 enable 兩個實例。
帳號 `c113118138` 的 `Linger=yes`，開機無須登入即可啟動。
服務設定 Restart=always、RestartSec=5；MySQL 與 Nginx 已啟用開機啟動。
環境設定沿用專案 env/.env，前端仍由 dist 提供。

```bash
systemctl --user status polimax-next@5173 polimax-next@5174
systemctl --user restart polimax-next@5173 polimax-next@5174
journalctl --user -u polimax-next@5174 -n 100 --no-pager
```

服務管理期間不要再用 npm start 佔用 5173；預設 Vite dev 也會與 5174 衝突。
修改前端後先 npm run build；後端修改後使用上面的 restart。
已驗證兩個服務 enabled/active，5173、5174 及 Nginx 的網頁和 MySQL health
均回應 HTTP 200。本次沒有實際重開機。

### SSO session 清理

SSO 模式由後端生命週期啟動清理工作，每天 Asia/Taipei 時間 00:00 刪除 `expires` 已到期的 `session-*.json`。保留未到期資料與共用鎖檔；兩個服務使用相同 session 鎖，避免與登入驗證或登出競爭。服務需保持運行；停機期間不執行，重啟後等待下一個午夜。目前登入有效期維持 12 小時，到期後 API 會拒絕使用，與午夜檔案清理時間分開。
