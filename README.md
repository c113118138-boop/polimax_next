# POLIMAX Next / AMS 交接手冊

> 獨立部署請先看 [2026-09-30 依賴盤點與搬機清單](deploy/STANDALONE.md)。

> 2026-09-22 已切換正式網站與定位接收器至 PostgreSQL；MySQL 保留作回復。本文部分 MySQL 敘述記錄原系統與歷史部署流程，最新狀態見 [切換紀錄](POSTGRESQL_MIGRATION_BASELINE.md)。

車輛、儀器與工作間的資產／預約管理系統，使用 React + TypeScript + Vite 前端與 FastAPI 後端，已由既有 MySQL 結構遷移至 PostgreSQL，並使用公司 SSO。

本文初版依 2026-09-14 專案程式整理，資料庫現況更新至 2026-09-22。正式執行需要本專案、PostgreSQL、公司 SSO 與本專案持久資料；`backend/legacy_*` 表示相容既有資料格式，不代表執行時需要舊專案。

## 1. 接手先看什麼

1. 先讀本文，確認設定、資料目錄與實際服務埠。
2. 部署、搬機或切換入口，讀 [獨立部署說明](deploy/README.md)。
3. 修改借車流程，讀 [車輛借用時序圖](VEHICLE_BORROWING_SEQUENCE.md)；修改儀器借用，讀 [儀器借用時序圖](EQUIPMENT_BORROWING_SEQUENCE.md)。
4. 新增表單欄位，先看本文第 6 節。

## 2. 功能與架構

主要功能包含公司 SSO 登入、角色權限、資產資料、借用／預約、行事曆、車輛發車／抵達／還車紀錄、附件、定位查詢與管理頁。

```text
瀏覽器（React）
  └─ /api/* → FastAPI
                 ├─ 公司 SSO：登入、session 與 token
                 ├─ PostgreSQL：資產、預約索引、流程狀態、定位等
                 └─ .data：表單 JSON、附件、權限、session
```

正式模式由 `backend/app.py` 載入 `legacy_api.py`；明確指定 `AMS_DATABASE_MODE=demo` 才載入 `demo_app.py`。資料庫連線失敗不會自動切換 SQLite。

正式服務也提供 `dist/` 前端檔案；修改前端後必須重新建置，正式頁面才會更新。

### 表單代碼與車輛流程

| 代碼 | 用途 |
| --- | --- |
| A | 車輛借用主表 |
| B | 發車紀錄，包含去程抵達內容 |
| C | 回程紀錄，包含回程抵達內容 |
| D | 工作間預約 |
| E | 儀器借用 |

車輛狀態依序為 `PENDING → DEPARTURE → DEPARTURE_ARRIVED → RETURN → RETURN_ARRIVED`。B/C 紀錄連結主表，不能只改前端狀態文字；轉換、驗證與保存由後端處理。

## 3. 安裝與啟動

以下命令皆在 `polimax_next/` 根目錄執行。部署基準為 Python 3.12、Node.js 20 或更新的相容版本；需要既有 MySQL schema、SSO 註冊資料及業務檔案。正式程式不會自動建立全新資料庫結構。

### 第一次安裝

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
npm ci
npm run build
```

新環境將 `.env.example` 複製為 `.env` 並填入設定；已有 `env` 或 `.env` 時保留原設定，不要覆蓋。Git 不包含帳密和 `.data`，單純 clone 無法取得完整業務環境。既有檔案搬移流程見 [部署文件](deploy/README.md)。

### 單一服務啟動

```bash
npm start
```

預設在 `0.0.0.0:5173` 提供前端及 API。確認服務健康：

```bash
curl -fsS http://127.0.0.1:5173/api/health
```

正式模式的 health 會實際查詢 MySQL，但成功不代表 SSO、附件與定位資料都完整。

### 前後端開發

終端機一啟動後端：

```bash
.venv/bin/python -m uvicorn app:app --app-dir backend --host 127.0.0.1 --port 8001 --reload
```

終端機二啟動前端：

```bash
npm run dev
```

瀏覽 `http://localhost:5174`。Vite 預設將 `/api` 轉發至 `127.0.0.1:8001`；可用 `AMS_API_TARGET` 調整。SSO 開發登入仍需要符合公司登錄的公開網址與 callback，不能假設 localhost 可直接登入。

| 啟動方式 | 預設埠 | 說明 |
| --- | --- | --- |
| `npm start` | 5173 | FastAPI 同時提供 dist 與 API |
| `npm run dev` | 5174 | Vite；後端需另行啟動 |
| 上述開發後端命令 | 8001 | 對應 Vite 預設代理 |
| systemd 範本 | 5174 | FastAPI，由反向代理轉接；會與預設 Vite 衝突 |

systemd 範本為 [polimax-next.service.example](deploy/polimax-next.service.example)，需依主機調整帳號、路徑、埠和 `ReadWritePaths`。不要把範本的埠當成所有部署的固定值。

## 4. 設定與持久資料

設定優先序：**程序環境變數 > `.env` > `env`**。相對資料路徑以專案根目錄解析。設定集中於 [settings.py](backend/settings.py)、[database.py](backend/database.py) 和 [範例環境檔](.env.example)。

| 設定 | 用途 |
| --- | --- |
| `AMS_DATABASE_MODE` | 現行正式為 `mysql`；可明確指定 `postgresql` 做隔離驗證；`demo` 為 SQLite 示範 |
| `MYSQL_HOST/PORT/DATABASE/USER/PASSWORD/CHARSET` | MySQL 連線 |
| `POSTGRES_HOST/PORT/DATABASE/USER/PASSWORD` | PostgreSQL 連線；使用 `postgresql` 模式時必填 HOST、DATABASE、USER、PASSWORD |
| `AMS_AUTH_MODE` | 正式為 `sso`；`test` 僅供隔離測試 |
| `PREVIEW_LOGIN_ENABLED` | 正式設為 `0` |
| `SSO_SERVER/SSO_CLIENT_ID/SSO_CLIENT_SECRET` | 公司 SSO 設定 |
| `PUBLIC_WEB_URL` | 對外網站網址 |
| `SSO_REDIRECT_URI` | 預設為公開網址加 `/api/callback`，須符合 SSO 註冊 |
| `AMS_DATA_DIR` | 持久資料根目錄，預設 `.data` |
| `AMS_RESPONSES_DIR` | 表單 JSON 目錄，預設 `.data/responses` |
| `AMS_SSO_POLICY_MANIFEST` | 權限快照 manifest，預設 `.data/permissions/latest-AMS.json` |
| `AMS_POLICY_FILE` | 可明確指定另一份帳號與角色政策 |

`PREVIEW_DATA_DIR`、`AMS_LEGACY_RESPONSES_DIR` 保留作相容參數；新部署優先使用 `AMS_*` 設定。MySQL、PostgreSQL 與 SSO 密鑰只放後端設定，不加入前端或 Git。現有服務仍使用 MySQL；PostgreSQL 測試快照與遷移進度見 [遷移盤點](POSTGRESQL_MIGRATION_BASELINE.md)。

```text
.data/
  responses/                   # A/B/C/D/E 表單 JSON 及備份
  files/<uuid>                 # 附件內容
  files/<uuid>.json            # 附件名稱、MIME 等索引
  permissions/latest-AMS.json  # 權限 manifest
  permissions/<snapshot>.json # 權限快照
  sso/                        # session/token
  session.key                 # 本機 session 金鑰
  migration-report.json       # 搬移結果與缺失附件清單
```

PostgreSQL 保存 `CarList`、`EquipmentList`、`formio_responses`、`form_flows` 等遷移後表；完整表單另保存在 JSON，包含 `_polimax_next.content` 新版內容。**只備份 PostgreSQL 無法完整還原系統。**

備份／搬機需一致保存 PostgreSQL、responses、files 與 permissions；每日備份由 `polimax-pg-backup.timer` 執行。搬到新主機可不搬 `sso/`，讓使用者重新登入。不要讓不同入口對同一資料庫寫入卻各自保存不同表單 JSON。

歷史資料採「先封存、讀回驗證、再刪除」流程，封存庫為同主機的 `polimax_PostgreSQL_Expired`。業務完成條件、初始化、管理頁面及雙庫備份見 [歷史封存與清理](deploy/ARCHIVE_RETENTION.md)。未完成初始化與啟用前不執行刪除。

## 5. 程式位置速查

| 檔案 | 責任 |
| --- | --- |
| [src/App.tsx](src/App.tsx) | 登入畫面、主版型、選單與路由 |
| [src/Bookings.tsx](src/Bookings.tsx) | 借用／預約表單、列表及詳情 |
| [src/Stages.tsx](src/Stages.tsx) | 車輛出回程階段表單及紀錄 |
| [src/Assets.tsx](src/Assets.tsx) | 車輛、設備及附屬資料介面 |
| [src/Calendar.tsx](src/Calendar.tsx) | 行事曆 |
| [src/Maps.tsx](src/Maps.tsx) | 最新位置、軌跡、掃描站及 Beacon |
| [src/Admin.tsx](src/Admin.tsx)、[src/Access.tsx](src/Access.tsx) | 管理與前端權限相關介面／邏輯 |
| [src/api.ts](src/api.ts) | API 呼叫、共用型別、React Query、台北時間處理 |
| [src/ui.tsx](src/ui.tsx)、[src/style.css](src/style.css) | 共用 UI 與樣式 |
| [backend/app.py](backend/app.py) | 正式／demo 入口選擇 |
| [backend/legacy_api.py](backend/legacy_api.py) | 正式 API、驗證入口、權限檢查、附件及前端靜態檔 |
| [backend/legacy_store.py](backend/legacy_store.py) | 正式資料讀寫、表單轉換、驗證、狀態推進及 JSON 保存 |
| [backend/legacy_schema.py](backend/legacy_schema.py) | 資產與附屬資料的 SQL 欄位映射 |
| [backend/legacy_form_fields.json](backend/legacy_form_fields.json) | 主表需求分類與舊 JSON 欄位映射 |
| [backend/legacy_integrations.py](backend/legacy_integrations.py) | 正式定位、Beacon、掃描站、通知查詢 |
| [backend/sso.py](backend/sso.py)、[backend/permissions.py](backend/permissions.py) | 登入與權限相關邏輯，需依模式確認呼叫路徑 |
| [scripts/migrate_storage.py](scripts/migrate_storage.py) | 一次性搬移表單、權限與附件 |

`demo_app.py`、`fixtures.py`、`integrations.py`、`stages.py` 屬示範模式相關程式。修改正式功能前先從 `app.py → legacy_api.py` 追蹤，避免只改到 demo。

常用 API：`/api/auth/me`、`/api/resources`、`/api/bookings`、`/api/bookings/{id}/advance`、`/api/stages`、`/api/files`、`/api/positions`、`/api/trajectory/{id}`。完整 HTTP 方法與驗證以 `legacy_api.py` 和 `legacy_integrations.py` 為準。

## 6. 新增表單欄位怎麼改

### 借車、借儀器、工作間預約（A/D/E）

1. 在 `src/Bookings.tsx` 加入輸入介面、初始值、編輯回填及送出的 `content`，並補上詳情顯示。
2. 在 `backend/legacy_store.py` 的 `validate_booking()` 加上必要的型別、長度或必填驗證。舊表單沒有新欄位，需決定合理預設及相容方式。
3. 確認 `encode_booking()` 保存、`legacy_content()` 讀取的內容符合需求。新版專用欄位可隨 `content` 保存在 `_polimax_next.content`，不一定需要新增 SQL 欄位。
4. 若必須與舊 JSON 格式互通，才同步調整 `legacy_form_fields.json` 及實際編解碼；單改映射檔不會自動產生輸入框或驗證。
5. 若欄位需要 SQL 搜尋、報表或索引，再評估資料庫結構及讀寫調整；目前沒有自動 schema migration。

例如新增「專案編號」，要同時確認建立時送出 `content.project_code`、編輯時載入、後端保存、詳情顯示，以及舊資料缺值時仍能正常開啟。

### 發車、抵達、還車（B/C）

修改 `src/Stages.tsx`，再確認 `legacy_store.py` 的 `validate_stage()`、`stage()`、`save_stage_json()`；新版內容分為 `content.start` 與 `content.arrival`。

**正式出回程欄位映射在 `legacy_store.py` 的 `STAGE_FIELDS`、`STAGE_CHECKS`，抵達欄位也有直接編解碼。** `legacy_stage_fields.json` 可供理解舊欄位，但不能只修改它就期待正式行為改變。

### 車輛或設備基本資料

修改 `src/Assets.tsx`、`legacy_schema.py` 對應及後端資產驗證／寫入邏輯。此類資料使用既有 SQL 欄位，與主表 JSON 欄位的保存方式不同。

### 修改後至少確認

- 新建 → 儲存 → 重新整理 → 編輯 → 再儲存，欄位值完整保留。
- 詳情頁可讀；舊表單缺少新欄位時不會出錯。
- 不同角色權限與必填驗證符合需求。
- 相關狀態推進與衝突檢查仍正常。

## 7. 驗證與測試

安裝測試依賴：

```bash
.venv/bin/python -m pip install -r backend/requirements-dev.txt
```

依修改範圍執行：

```bash
npm run check
npm run build
.venv/bin/python tests/test_sso.py
.venv/bin/python tests/test_standalone.py
.venv/bin/python tests/test_manual_people.py
.venv/bin/python tests/test_integration.py
```

| 測試 | 範圍與前提 |
| --- | --- |
| `test_sso.py` | SSO 相關自動測試；不能替代真實公司帳號驗收 |
| `test_standalone.py` | 獨立設定、資料搬移等行為 |
| `test_manual_people.py` | 手動第二借用人與後端姓名驗證 |
| `test_integration.py` / `npm run test:api` | 隔離 SQLite demo；不能代表正式 MySQL 相容性 |
| `test_mysql.py` | 固定連 `127.0.0.1:13316` 的隔離 MySQL，以 root 無密碼連線建立隨機測試庫與測試帳號，需要相應權限；勿改指向正式資料庫 |
| `npm run test:browser` | Playwright 啟動隔離 demo 服務於 18021，需先建置前端及安裝 Chromium |

MySQL 與瀏覽器測試命令：

```bash
.venv/bin/python tests/test_mysql.py
npx playwright install chromium
npm run build
npm run test:browser
```

正式模式修改需補對應 MySQL 行為驗證；demo 測試通過不代表正式資料流程已驗證。

## 8. 常見問題與目前限制

### 最新位置沒有顯示

先在左側選擇資源；沒有選取時頁面不會自動顯示所有定位點。

- 車輛 API 透過 `CarList.client_id` 查 `gps_readings.client_id`。沒有匹配紀錄就回傳空座標。
- 2026-09-14 唯讀查詢本機專案設定連線的 MySQL 時，`gps_readings` 與 `new_reports` 皆為 0 筆；此為當時狀態，日後排查需重新查詢。
- 正式 `/api/positions` 目前只處理車輛，會略過設備，即使前端提供設備選項也無定位結果。
- 後端提供 `latest_report_time`，前端讀取 `updated_at`，因此最新接收時間欄位尚未對齊。
- 頁面仍有「測試報告／虛構測試點位」文案，與正式資料來源不一致，待整理。

「刷新位置」只重讀資料庫。此專案不實作 GPS 接收、Beacon 上游取數或通知排程；需要另外維運資料生產程序。部署新版不會自動補入定位資料。

### 修改前端後沒變

`npm start` 讀取 `dist`，先執行 `npm run build`；開發時使用 Vite。若仍未更新，核對反向代理實際指向的服務、部署目錄及瀏覽器快取。

### API 連不上／前端尚未建置

核對啟動命令、埠及 `AMS_API_TARGET`，確認沒有 Vite 與 systemd 互搶 5174。回應「前端尚未建置」時先建立 `dist`；health 失敗則檢查 MySQL 連線與 schema。

### 登入失敗或沒有權限

確認公開網址、SSO callback、client 設定、帳號啟用與權限快照。舊 AMS 的權限異動不會自動同步到新版；管理頁重新載入只讀新版政策檔，不會向外部取得新快照。

### 附件 404

檢查 `.data/files` 的內容與索引，以及 `migration-report.json` 的缺失清單。新版不再轉向舊附件服務。部署紀錄記載切換時接受 15 個歷史附件缺失，實際未完成項目以搬移報告為準，不能假設所有歷史附件齊全。

### 表單寫入／修改衝突

正式儲存使用 MySQL 命名鎖、SQL 交易、JSON 暫存／備份／替換及失敗回滾處理；修改也包含 revision 檢查。不要為避開衝突而直接移除版本或狀態驗證。SQL 與檔案仍是兩種儲存媒介，需要一致備份。

## 9. 發版與交接清單

- 記錄部署版本、實際服務帳號、啟動方式、埠、網域與反向代理目標。
- 確認 MySQL、SSO、資料路徑及權限來源；帳密透過既有安全管道交接。
- 在隔離環境完成相關驗證，建置 `dist`，依實際服務管理方式更新／重啟。
- 驗收 health、真實 SSO 登入、角色權限、既有表單及附件下載。
- 交接 MySQL 與持久檔案備份位置、還原方法，以及定位／通知外部程序的負責人與執行位置。
- 保留缺失附件與未完成功能清單；切回舊版前需處理切換後新增的表單及附件，不能只切換網址。

## 10. 其他文件

- [獨立部署與搬移](deploy/README.md)：部署、搬移、備份及本次切換紀錄。
- [車輛借用時序圖](VEHICLE_BORROWING_SEQUENCE.md)：目前獨立版借車與出回程流程。
- [儀器借用時序圖](EQUIPMENT_BORROWING_SEQUENCE.md)：目前獨立版儀器借用流程。
- [使用者歷史流程](USER_JOURNEY_SEQUENCE.md)、[其他時序圖](SEQUENCE_DIAGRAMS.md)：閱讀時核對是否包含獨立改造前的舊目錄／附件轉接描述，以目前程式與部署文件為準。
- [初期驗收紀錄](ACCEPTANCE.md)：demo 階段背景，不作為目前正式功能全部完成的依據。
