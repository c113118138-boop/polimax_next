# PostgreSQL 正式切換草案

狀態：**2026-09-22 已依本草案完成正式切換。下文保留當時操作順序供回復與下次搬移參考；執行結果見 [遷移紀錄](POSTGRESQL_MIGRATION_BASELINE.md)。**

## 切換前必須確認

- 安排停寫窗口；通知使用者期間網站與三個定位接收器暫停。確認有權執行 `sudo`、`polimax_admin` 密碼可在終端機輸入。
- 再核實是否有其他主機、容器或排程寫 `mqtt_data`。本機常駐寫入者為 `polimax-next@5173/5174` 與三個 `pmx-tracking@...`；`polimax-gps-cleanup.timer` 每日 03:30 會刪除過期資料。舊 `AMS_API.py`／`backup_*.py` 本機未見常駐，但仍是 MySQL 專用程式。
- 盤點目標 PostgreSQL 備份排程及儲存位置。現有 MySQL 備份 agent 不能當作 PostgreSQL 備份。`pg_dump -Fc`／`pg_restore` 已在隔離叢集演練，正式目標庫與 `.data` 的備份尚未建立。
- 在正式環境先驗證 SSO、權限快照、附件與定位頁面；測試登入無法替代真實帳號驗收。

## 停寫窗口順序

1. 停止兩個網站入口與三個接收器，暫停 `polimax-gps-cleanup.timer`；核對沒有其他寫入程序。若權限同步服務會更新 `.data/permissions`，亦暫停它。此時 MySQL 服務本身保持運行，供備份與最後匯出。
2. 在權限限制為 `0700` 的備份目錄執行 `sudo mysqldump --single-transaction --skip-lock-tables --routines --events --triggers mqtt_data`，保存完整 MySQL SQL；另封存當時的 `polimax_next/.data` 與資料庫設定檔。`--skip-lock-tables` 是因 MySQL view 的舊 definer 已不存在，普通 `mysqldump` 曾報 1449。備份含帳密、session 與業務資料，不得加入 Git。
3. 驗證 SQL dump 包含 23 張表、3 個 view，封存檔可讀且有雜湊值。做過還原演練後，才把這份備份視為回復依據。
4. 用 `scripts/export_postgresql.py` 從停寫後的 MySQL 產生**新的** PostgreSQL 匯出；不得沿用 `/tmp/polimax_pg_test_export_20260921b`。在 `polimax_PostgreSQL` 清除舊測試快照後，載入新 `load.psql`，再執行 `scripts/postgresql_views.sql`。
5. 重新核對每張表筆數、主鍵最大值、三個 view，以及 `.data/responses`、`.data/files`、`.data/permissions` 的檔案數與關聯。`scripts/verify_postgresql.sql` 可作目標庫初步檢查，但不能代替逐表及業務驗收。
6. **通過核對後**才將 `polimax_next` 的 `AMS_DATABASE_MODE` 設為 `postgresql` 並填入 `POSTGRES_*`，重新啟動網站與三個接收器。確認 `/api/health` 回報 PostgreSQL，SSO 登入、資產、預約、附件、GPS／Beacon 實際接收、GPS 清理唯讀預覽皆正常。
7. 設定並驗證 PostgreSQL 與 `.data` 的定期一致備份，再恢復清理排程。保留 MySQL 與切換點封存，直到回復期限結束。

## 回復原則

切換後若已有新表單、附件或定位資料寫入 PostgreSQL，不能只把網站連線改回 MySQL。必須先停寫，決定如何處理切換後新增資料，再一起回復資料庫與 `.data` 到相容狀態。若切換前的備份或核對失敗，維持 MySQL 模式並重新啟動原服務。
