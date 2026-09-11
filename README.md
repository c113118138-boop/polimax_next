# POLIMAX / AMS

React / TypeScript / Vite 前端與 FastAPI 後端。預設讀取專案 `env` 的 MySQL 帳密，直接沿用既有 POLIMAX 資料表及表單檔案，不需要建立新表，也不使用 SQLite 保存正式資料。

## 啟動

```bash
cd /home/c113118138/polimax_next
.venv/bin/python -m pip install -r backend/requirements.txt
npm run build
npm start
```

開啟 `http://163.18.26.228:5173`。同一服務提供前端與 `/api`；開發用 Vite 代理可透過 `AMS_API_TARGET=http://127.0.0.1:5173 npm run dev` 指向此後端。

`GET /api/health` 會實際查詢 MySQL，回傳 `mode: legacy`、`database: MySQL`、`schema_changes_required: false`。連線失敗會回報錯誤，不會改用示範資料。

## 沿用的資料保存方式

| 資料 | 既有保存位置 |
| --- | --- |
| 車輛 | `CarList` |
| 儀器 | `EquipmentList` |
| A/D/E 預約明細、時間與取消標記 | `formio_responses` |
| 車輛借用流程狀態 | `form_flows` |
| 保險、費用、維護、車庫檔案、管理人 | `insurance_records`、`cost`、`vehicle_records`、`garage_files`、`vehicle_managers` |
| 完整 A 表內容 | 原後端 `回應/主表/*.json`，保留原本 `content` 包裝 |
| B/C 出回程 | 原後端 `回應/發車紀錄表/*.json`、`回應/回程紀錄表/*.json` |
| D 作業區、E 儀器表單完整內容 | `回應/工作間預約表/*.json`、`回應/儀器借用表/*.json` |
| 附件 | 原檔案服務；原 MySQL 欄位保存 UUID 與檔案資訊 |
| Beacon 與定位 | `BeaconList`、`gps_readings`、`new_reports`、`Outdoor_Beacon_readings` |

- 每次查詢直接讀取原表與 JSON；不建立資料鏡像、快取資料庫或 `ams_preview_` 擴充表。
- 保留舊表單編號。A 修改建立新編號並將舊 SQL 明細標記取消；D/E 修改沿用編號；B/C 編號沿用 JSON 目錄的最大流水號。
- JSON 修改保留時間戳 `.bak.json` 備份。新版較完整的欄位保存在同一 JSON 的 `_polimax_next` 區段，同時寫入舊表單對應欄位，保留原檔未修改的內容。
- 使用 MySQL 命名鎖序列化新版的儲存、流水號與衝突判斷；車輛衝突包含時段相接邊界。舊作業區的括號編號格式也納入判斷。
- MySQL 寫入使用交易。JSON 先準備暫存檔，再以原子替換保存；正常錯誤會回滾 SQL 並還原已替換的 JSON。SQL 與檔案系統仍是不同儲存媒介，備份時須一起保存。
- 舊 JSON 中的完整需求、駕駛、里程及異狀會轉換給新版顯示；不產生示範資料補足缺漏。
- 附件沿用舊服務的 `/upload`、`/preview/{uuid}`、`/file/{uuid}`。新版不另建附件資料表。
- 正式入口使用公司 SSO；登入身分由 `/userinfo` 驗證，再套用原 AMS 快照中的啟用使用者、角色與表單權限。access/refresh token 只保存在後端 `.data/sso/`，瀏覽器只持有 HttpOnly 隨機 session cookie，不新增 session 表。
- 登入使用一次性 state（十分鐘期限）防止回呼重放；SSO session 期限十二小時，使用時定期向 IdP 驗證，必要時以 refresh token 更新；登出撤銷本地 session，並呼叫與跳轉原 SSO 登出端點。
- 通知與定位匯入仍由既有系統程序處理；新版讀取既有紀錄，不另行發送通知或建立示範定位。

## 設定

資料庫設定由後端讀取 `env`；`.env` 及程序環境變數可覆寫。不會將帳密送到前端。

| 設定 | 用途 |
| --- | --- |
| `MYSQL_HOST`、`MYSQL_PORT`、`MYSQL_DATABASE`、`MYSQL_USER`、`MYSQL_PASSWORD`、`MYSQL_CHARSET` | 使用現有 MySQL 連線 |
| `AMS_DATABASE_MODE` | 預設 `mysql`；`demo` 才啟用隔離 SQLite 示範版 |
| `AMS_LEGACY_RESPONSES_DIR` | 程序環境變數；預設 `../polimax_carAPI_on/回應` |
| `AMS_LEGACY_FILE_URL` | 程序環境變數；預設舊服務 `https://uclerpnext.54ucl.com:3000` |
| `PREVIEW_DATA_DIR` | 本地金鑰、附件名稱索引及上傳暫存目錄，預設 `.data` |
| `SSO_SERVER`、`SSO_CLIENT_ID`、`SSO_CLIENT_SECRET` | 沿用 env 的 SSO 服務及已註冊 client |
| `PUBLIC_WEB_URL` | SSO 登入後的正式入口，目前 `http://163.18.26.228:5173` |
| `SSO_REDIRECT_URI` | 預設 `PUBLIC_WEB_URL/api/callback`，沿用已註冊回呼 |
| `AMS_SSO_POLICY_MANIFEST` | 預設讀取原 mini-engine 的 `data/snapshots/latest-AMS.json` |
| `AMS_AUTH_MODE`、`PREVIEW_LOGIN_ENABLED` | 僅隔離測試同時設定 `test` 與 `1` 才能使用角色選擇登入；正式預設 SSO |
| `AMS_POLICY_FILE` | 既有政策 JSON 設定來源 |
| `AMS_OPTIONS_FILE` | 可覆寫含 `cities` 的名錄 JSON |
| `AMS_HOLIDAYS_FILE` | 既有假日 JSON；未設定顯示空清單 |

行政區使用舊系統相同的國土測繪中心 `ListTown` 來源，已保存於 `backend/taiwan_cities.json`，避免表單每次載入都等待外部查詢。業務時間仍使用 Asia/Taipei。

## 程式與驗證

- `backend/app.py`：選擇 MySQL 或明確指定的 demo 模式。
- `backend/legacy_api.py`：新版 API、權限及原附件服務轉接。
- `backend/sso.py`：授權碼登入、回呼、伺服器 session、憑證更新、原 AMS 角色與登出。
- `backend/legacy_store.py`：原 MySQL 表與 JSON 的查詢、寫入、出回程與衝突判斷。
- `backend/legacy_schema.py`、`legacy_form_fields.json`、`legacy_stage_fields.json`：原欄位對應。
- `backend/legacy_integrations.py`：原定位與 Beacon 資料查詢。
- `backend/demo_app.py`：隔離示範模式，不用於正式 MySQL 連線。

```bash
.venv/bin/python tests/test_integration.py
.venv/bin/python tests/test_sso.py
.venv/bin/python tests/test_mysql.py
npm run build
```

`test_integration.py` 自動使用暫存 SQLite 示範資料。`test_mysql.py` 固定連到本機 `127.0.0.1:13316` 的隔離測試 MySQL，建立隨機測試資料庫，僅建立 `tests/legacy-schema.sql` 的舊表；以只有 SELECT/INSERT/UPDATE/DELETE 的帳號驗證 API，結束後刪除測試資料庫。不讀取 env 的正式連線目標。

MySQL 測試涵蓋既有 JSON 顯示、資產與五類紀錄、表單版本／取消、出回程、併發搶借、儀器、作業區括號編號、外部資料更新、寫入回滾，以及模擬原附件服務。另已使用真實 MySQL 做唯讀 API 與桌面／手機瀏覽器驗證；沒有新增正式資料表或測試預約。

原重建版本的驗收背景見 [ACCEPTANCE.md](ACCEPTANCE.md)，其中示範來源與 SQLite 內容只適用於 demo 模式。

SSO 合約測試使用模擬 IdP，涵蓋狀態偽造／重放／過期、原角色對應、token 不進入瀏覽器、刷新與登出撤銷。真實 SSO 已驗證授權頁跳轉；個人帳密登入及實際帳號權限需由使用者在正式入口登入確認。從 localhost 進入 SSO 時會先導向已註冊的正式主機，確保回呼 cookie 的網域一致。
