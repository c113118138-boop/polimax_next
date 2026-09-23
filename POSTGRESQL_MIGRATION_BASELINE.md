# PostgreSQL 遷移盤點與切換紀錄

> **目前狀態（2026-09-22）：正式網站與三個定位接收器已切換至 PostgreSQL；下文 2026-09-21 的「尚未切換」敘述為當時歷史狀態。**

本文件是唯讀盤點，不是備份。查詢期間服務仍在運作，以下筆數只是當時快照；正式搬移前需在停寫窗口重新核對。

## 現況

- 同機 MySQL 8.0.46 正在運行，正式資料庫是 `mqtt_data`。2026-09-21 後續已安裝 PostgreSQL 16.15，`16/main` 叢集在線並於 `127.0.0.1:5432` 接受連線；尚未建立專案測試庫或帳號。
- `polimax-next@5173` 與 `polimax-next@5174` 都在運行，使用 `polimax_next/env` 的正式 MySQL 設定。
- 三個 `pmx-tracking@...` 接收服務正在運行。`Outdoor_GPS_Agent.py` 明確寫入 `gps_readings`，`Outdoor_Beacon_Agent.py` 明確寫入 `Outdoor_Beacon_readings`；室內接收器也使用 MySQL。應在切換前確認各服務實際寫入的資料庫及表。
- `polimax-gps-cleanup.timer` 每天 03:30 執行清理。切換窗口須處理此排程。其他外部程序（例如 FindMy 匯入、通知、備份 agent）仍需另行核實是否啟用及其資料庫依賴。
- `.data` 約 2.0 MiB；其中 `responses` 282 檔、`files` 0 檔、`permissions` 2 檔。完整表單和權限快照不只在 SQL。`.data` 另有 SSO 狀態、session key 等執行資料，備份須妥善保護。

## 正式資料庫快照

23 張 InnoDB 實體表、3 個 view、258 個欄位、85 組索引、1 個外鍵；沒有資料庫 trigger、routine 或 event。`information_schema.TABLES.TABLE_ROWS` 是估算值，以下是唯讀交易中的 `COUNT(*)`：

| 表 | 筆數 |
| --- | ---: |
| BeaconList | 87 |
| CarList | 16 |
| EquipmentList | 5 |
| form_flows | 90 |
| formio_responses | 124 |
| gps_readings | 120 |
| 其餘 17 張實體表 | 0 |

三個 view 為 `Findmy_latest`、`car_realtime`、`latest_scanned_devices`。唯一外鍵為 `alert_logs.tag_id → rfid_tags.id`。正式 schema 比 `tests/legacy-schema.sql` 範圍大，不能用測試檔直接建立 PostgreSQL 正式 schema。

需逐欄轉換 `ENUM`、`TINYINT`、`UNSIGNED`、自動流水號、MySQL `TIMESTAMP`/`DATETIME` 及 `ON UPDATE CURRENT_TIMESTAMP`。混合大小寫的表／欄名需要在 PostgreSQL 保持正確引用；view 定義也必須重寫。部分外部接收器使用 MySQL connector 與 MySQL SQL 語法，不能只切換網站後端。

## 一致備份與切換前核對

1. 先確認所有寫入者及其所用的資料庫，包括網站兩個入口、定位接收器、FindMy／通知上游及排程；列出可停寫的服務和切換窗口。
2. 在停寫窗口暫停所有相關寫入與清理排程，確認沒有新寫入，再一起備份 `mqtt_data` 的完整 schema、資料、view，以及 `.data/responses`、`.data/files`、`.data/permissions`。依還原需求處理 `.data` 其他執行檔案，避免將密鑰放入版本控制。
3. 對備份做還原演練；核對各表筆數、主鍵最大值、view、外鍵，以及表單 JSON／附件數量與關聯。正式切換前重新取得此快照，不能沿用本文件數字。
4. 在隔離 PostgreSQL 庫完成 schema 轉換、資料匯入及程式驗證後，才切換服務連線；保留 MySQL 和同一時間點的檔案備份作回復依據。

目前未執行備份、停服務或修改資料庫；PostgreSQL 已由主機使用者安裝，專案尚未連接。

## 2026-09-21 測試匯出進度

- `scripts/export_postgresql.py` 可從正式 MySQL 唯讀產生 PostgreSQL 建表、資料、索引、外鍵、更新時間觸發器及流水號設定。輸出含業務資料，僅放在權限 `0700` 的 `/tmp/polimax_pg_test_export_20260921b`；檔案權限為 `0600`。
- 已在獨立的 `/tmp` PostgreSQL 16 臨時叢集試載入：23 張表、85 組索引建立成功；`formio_responses` 124 筆、`gps_readings` 120 筆，與該次匯出相符。臨時叢集已停止。
- 這是服務持續運作時的測試快照，不是停寫後的一致備份。尚未匯入使用者建立的 `polimax_PostgreSQL`。
- MySQL 帳號 `polimax_api` 缺少 `SHOW VIEW` 權限，無法讀取三個 view 的定義；匯出工具明確列出缺項。正式搬移前需由具 `SHOW VIEW` 權限的帳號取得定義並轉換。
- PostgreSQL `polimax_admin` 密碼只由使用者持有；目標庫匯入需在使用者自己的終端機輸入密碼執行，不能把密碼加入腳本或對話。

## 2026-09-21 view 轉換

- 主機使用者以 `mysqldump --single-transaction --skip-lock-tables --no-data --skip-triggers` 成功匯出完整 schema；檔案位於 `/tmp/polimax_mysql_schema_20260921.sql`，包含三個 view 的定義。
- `scripts/postgresql_views.sql` 已依該定義轉換 `Findmy_latest`、`car_realtime`、`latest_scanned_devices`，並在隔離 PostgreSQL 16 臨時叢集成功建立與查詢。時間篩選明確使用台北時區。
- MySQL 原 view 的 definer 為已不存在的 `sean`@`%`；一般鎖表式 `mysqldump` 因此失敗。這不影響已完成的 PostgreSQL SQL 語法驗證，但原 MySQL view 實際查詢需另行確認。
- 三個 PostgreSQL view 尚未套用到使用者的 `polimax_PostgreSQL` 目標庫。

## 2026-09-21 目標庫驗證

使用者在 `polimax_PostgreSQL` 以 `polimax_admin` 執行 `scripts/verify_postgresql.sql`，回報 23 張表、3 個 view、85 組索引；`BeaconList` 87、`CarList` 16、`EquipmentList` 5、`form_flows` 90、`formio_responses` 124、`gps_readings` 120 筆，均與測試匯出相符。view 筆數為 `car_realtime` 120、`Findmy_latest` 0、`latest_scanned_devices` 0。

這只驗證測試快照的結構與主要筆數，未驗證每筆內容、前後端業務流程或持續寫入。正式網站仍連接 MySQL；後續需修改應用程式及外部接收器的 PostgreSQL 連線與 MySQL 專用邏輯，並在停寫窗口重新製作一致備份與最終匯入。

## 2026-09-22 後端隔離驗證

- 新增明確的 `AMS_DATABASE_MODE=postgresql`，使用 `POSTGRES_HOST/PORT/DATABASE/USER/PASSWORD`；現行服務預設仍為 MySQL。後端安裝 Psycopg 3.3.6，並在 PostgreSQL 寫入時使用 session advisory lock 對應原 MySQL 命名鎖。
- 在 `/tmp` 臨時 PostgreSQL 叢集與複製的 `.data/responses` 上驗證：health 回報 PostgreSQL、登入測試、資產和預約讀取、資產更新讀回、A 表單建立與 JSON 讀回、GPS 軌跡查詢（10/93 筆）及 GPS 清理唯讀預覽。設定單元測試 4 項通過。臨時叢集已停止。
- 尚未用 `polimax_admin` 密碼對使用者的目標庫啟動後端實例；尚未驗證 SSO、附件、所有業務流程與定位接收器。正式服務仍連接 MySQL，沒有執行停寫後一致備份或最終匯入。

## 2026-09-22 定位接收器與下一項驗收

- `PMXAgent-deploy-package/agents` 的三個常駐接收器已加入明確 PostgreSQL 模式，原 MySQL 模式仍為預設。`tracking_connection.py` 統一連線及三種 INSERT；GPS、室內 Beacon、戶外 Beacon 在 `/tmp` 隔離 PostgreSQL 各試寫一筆後回滾，零筆測試資料殘留；原 MySQL 路徑唯讀連線成功。三個正式服務未重啟。
- 主機 PostgreSQL 設定時區為 `Asia/Taipei`；新接收 SQL 以台北時間保存 `created_at`。MySQL 目前 `NOW()` 也為台北時間，與 `UTC_TIMESTAMP()` 相差 8 小時。
- `scripts/verify_postgresql_api.py` 在使用者終端機提示 PostgreSQL 密碼，對目標庫進行只讀 API 驗收，並在暫存目錄複製表單 JSON；不保存密碼或啟動對外服務。
- `AMS_API.py` 與舊 MySQL 備份 agents 仍使用 `tracking_database.database_config()`；正式切換前需釐清它們是否仍在執行，並改用 PostgreSQL 備份／查詢或退役。尚未安排停寫後一致備份與正式切換。

使用者層 systemd timers 僅見 `polimax-gps-cleanup.timer`；`crontab` 中未找到相關 agents。這不排除其他帳號、容器或外部主機的排程，正式切換前仍需核實。只讀 API 驗收腳本已在 `/tmp` 隔離庫實跑成功（25 項資產、34 項預約，含先前隔離測試新增的 1 筆）；目標 `polimax_PostgreSQL` 尚待使用者輸入密碼驗證。

## 2026-09-22 目標庫只讀 API 驗收

使用者在主機終端機執行 `scripts/verify_postgresql_api.py` 並自行輸入 `polimax_admin` 密碼，結果為 PostgreSQL、25 項資產、33 項預約、預約詳情可讀、零筆寫入。切換順序與回復條件另見 `POSTGRESQL_CUTOVER_RUNBOOK.md`。這證明目標庫可供目前後端讀取，尚不等於正式切換完成。

## 2026-09-22 備份格式演練

在 `/tmp` 隔離 PostgreSQL 叢集以 `pg_dump -Fc` 備份、`pg_restore --no-owner --no-acl` 還原到另一個隔離資料庫，核對還原後有 23 張表、3 個 view、125 筆 `formio_responses`（比原測試快照多 1 筆先前隔離 API 測試表單）、120 筆 `gps_readings`。此演練證明 PostgreSQL 自訂格式可還原；尚未備份或還原正式 `polimax_PostgreSQL`，也不能代替 MySQL 與 `.data` 的停寫後一致備份。

## 2026-09-22 正式切換結果

- 21:15 CST 停止兩個網站入口、三個定位接收器、GPS 清理排程與權限同步服務；MySQL 保持運行。
- 在停寫期間保存 23 張表的當前 MySQL 結構與資料、3 個 view 的還原 SQL、`.data` 與設定。於隔離 MySQL 還原並核對 `formio_responses` 124、`gps_readings` 120、3 個 view。備份位於私有的 `migration_backups/pg_final_20260922_2115`。
- 發現 MySQL `CHAR(1)` 空字串與 PostgreSQL `CHAR(1)` 補空白差異後，將轉換型別改為 `VARCHAR(1)` 並重新匯入。最終逐表雜湊比對：**23 張表、442 筆資料全部一致**。最終 PostgreSQL 匯出位於 `migration_backups/pg_final_20260922_2115_v2`。
- 新的 `.env` 權限 `0600`，明確設為 PostgreSQL；未覆蓋原 `env` 的 MySQL 與 SSO 設定。21:26 後兩個網站入口、三個接收器及權限服務恢復；兩個 `/api/health` 都回報 PostgreSQL，SSO 跳轉回應 303，公開 IP 的 Nginx 入口回應 200。
- 三個接收器連上 MQTT broker，未見重啟循環；尚無新的真實定位訊息可驗證完整上游寫入。GPS 清理 PostgreSQL 唯讀預覽成功，排程恢復。
- 正式 PostgreSQL 切換點 dump 已保存；`scripts/backup_postgresql.py` 實際完成一次 PostgreSQL 與持久檔案備份，雜湊、tar 內容、pg_restore 清單與權限核對通過。`polimax-pg-backup.timer` 已啟用，每日 04:00 備份。
- MySQL 服務與停寫備份仍保留供回復。切換後關鍵表在 MySQL 與 PostgreSQL 筆數尚相同；真實 SSO 帳號、附件與實際業務寫入仍需使用者驗收。
