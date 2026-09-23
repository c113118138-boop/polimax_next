# GPS 保存與查詢

正式 PostgreSQL GPS 軌跡僅查最近 90 天（以 created_at 接收時間為準），單次跨度最多 90 天。
地圖預設最近 30 天，提供 30/60/90 天與自訂日期。資料庫端先排除無效座標，再按時間排序抽樣；預設最多回傳 1000 點，保留起终點。長期間折線是摘要，縮小時間範圍可看細節。

清理保留最近 90 天，另保留每個 client_id 按 record_time/id 排序的最後一筆，不論多舊，以維持最新位置查詢。這些例外不會出現在 90 天歷史軌跡內。created_at 為 NULL 的舊資料不自動刪除，需另行檢查。

現行使用 PostgreSQL；舊 MySQL 8+ 模式仍保留。請在專案根目錄使用現有後端環境設定：

```bash
# 唯讀預覽首批候選數（最多 1000 筆，不是全部候選總數）
.venv/bin/python scripts/gps_maintenance.py
# 部署時建立缺少的查詢複合索引；這一步會修改 schema，但不刪資料
.venv/bin/python scripts/gps_maintenance.py --ensure-indexes
# 手動清理，每批 1000 筆，單次最多 100 批
.venv/bin/python scripts/gps_maintenance.py --apply
```

每日清理使用隨附的 systemd user service/timer，部署前核對絕對路徑及設定來源。
若 API 由 service Environment 注入資料庫設定，清理 service 必須套用相同設定。

```bash
mkdir -p ~/.config/systemd/user
cp deploy/polimax-gps-cleanup.service deploy/polimax-gps-cleanup.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now polimax-gps-cleanup.timer
systemctl --user list-timers polimax-gps-cleanup.timer
journalctl --user -u polimax-gps-cleanup.service
```

排程每日台北時間 03:30 執行；Persistent 會補跑錯過的排程。主機無登入也要執行時，管理員需確保使用者服務可持續運作（linger）。
不會自動 OPTIMIZE TABLE，刪除空間可供 InnoDB 重用，不保證立即縮小磁碟檔案。
程式碼與排程範本加入並不代表排程已安裝啟用。原始定位匯入仍由既有上游程序負責。

測試：

```bash
.venv/bin/python tests/test_gps_history.py
GPS_TEST_MYSQL=1 .venv/bin/python tests/test_gps_history.py
```

MySQL 測試只使用 localhost:13316 隔離測試服務及隨機資料庫，不使用專案連線設定。

## Beacon 與儀器定位保存（已加入同一排程）

除了 gps_readings，同一支腳本也處理以下歷史表；不修改 BeaconList、EquipmentList 或借用表單：

| 表 | 90 天依據 | 保留例外 |
| --- | --- | --- |
| new_reports | timestamp | 每個 sheet_id 最新 timestamp/id 的一筆 |
| Outdoor_Beacon_readings | created_at | 每個 client_id/major/minor 最新接收與最新記錄時間的資料 |
| FindMy | created_at | 每個 major 最新 timestamp 與最新 created_at 的資料 |

最新接收和最新記錄若不同，會保留兩筆，避免延遲匯入造成最後位置遺失。
儀器設備沒有獨立歷史軌跡表，相關 Beacon 定位依以上來源清理。
時間或設備識別為 NULL 的資料保留，需人工釐清；缺少的歷史表會記錄並跳過。
每張表每批最多 1000 筆，每次最多 100 批，日誌分表列出結果。
FindMy 舊匯入器用 UTC 寫入 DATETIME，使用 UTC 截止時間。
new_reports 尚無上游時區資訊，使用 UTC 截止時間；若實際寫入台北時間，會保守多留最多 8 小時。
Outdoor TIMESTAMP 以 MySQL session +08:00 讀取比較。
使用既有 polimax-gps-cleanup.timer，每日台灣時間 03:30，無須再建立第二個排程。
