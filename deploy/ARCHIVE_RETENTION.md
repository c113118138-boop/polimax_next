# PostgreSQL 歷史封存與清理

正式庫：`polimax_PostgreSQL`。封存庫：`polimax_PostgreSQL_Expired`。
兩者位於 163.18.26.228 的同一個 PostgreSQL instance，沿用本機
`127.0.0.1` 連線及既有帳號，不增加對外開放的連接埠。

## 保留規則

| 資料表 | 規則 |
| --- | --- |
| gps_readings、new_reports、Outdoor_Beacon_readings、FindMy | 沿用 90 天與每設備最新定位例外；Outdoor/FindMy 保留最新接收與最新記錄 |
| sensor_readings | 90 天；每個 client_id/major 保留最新接收與最新記錄 |
| alert_logs、notification | 接收／建立超過 90 天 |
| vehicle_status | update_at 超過 90 天；保留每個 client_id/license_plate 最新狀態 |
| device_alert、vehicle_alerts2 | 登記處理完成超過 90 天；車輛告警另需 notification_sent=是 |
| cost | 人工登記核對完成超過 90 天 |
| insurance_records | 到期與人工確認無待辦理賠均超過 90 天 |
| vehicle_records | 紀錄日期與人工確認維修完成均超過 90 天 |
| garage_files | 人工確認失效／被取代超過 90 天 |
| formio_responses、form_flows | 整份表單使用時段結束超過 90 天；A 表需 returned/RETURN_ARRIVED 超過 90 天，且主表、出回程 JSON 最近 90 天未修改；D/E 表需人工確認完成／歸還超過 90 天 |

CarList、EquipmentList、BeaconList、basic_information、findmy_id、rfid_tags、
vehicle_managers 不清理。Views 不另行搬移；新增的表不會自動列入刪除。
時間或設備識別缺失、日期格式無法判讀、仍有效或未完成的資料均保留。
FindMy/new_reports 維持舊程式的 UTC 截止時間，其餘使用台北時間。
建立／更新時間仍在 90 天內的業務資料也保留。

沒有可靠完成欄位的資料不會以建立時間猜測完成狀態。管理員在
「歷史封存 → 正式資料與完成登記」登記實際時間與依據，也可取消登記。
SQL、流程、JSON 或附件內容變動後，原登記指紋不符即不再符合封存資格。
A 表以實際歸還狀態判斷，人工登記不能跳過未歸還狀態。

## 安全流程

1. 取得與網站、完整備份相同的 advisory lock，並鎖定本批來源資料。
2. 固定本次 90 天截止時間；篩選確切 ID，保留所有例外。
3. 同名資料表保存原 ID 與完整欄位。整份表單同批保存 SQL、流程及 B/C JSON。
4. 附件與 JSON 以 4 MiB 區塊存入封存庫，以 SHA-256 去重。缺檔保留原紀錄並回報。
5. 提交封存交易，再用新交易讀取每筆完整內容與所有檔案區塊核對。
6. 再次核對來源內容，刪除完全相同的原始資料，提交來源交易。

跨資料庫不是單一交易；封存後當機可能留下兩邊都有資料。
重跑接受內容相同的既有 ID，內容不同就停止，不覆蓋也不刪來源。
`polimax_archive_batches` 保存來源庫、截止時間、原始資料、檔案索引、
完成登記與驗證時間。驗證成功不等於來源刪除已提交；查詢只顯示已驗證批次。
原始 JSON 與本機附件保留，避免共用附件誤刪與跨 SQL／檔案交易問題；此次
主要縮減正式 SQL 資料庫，沒有自動回收本機檔案或封存庫資料。

定位／事件每表每批最多 500 筆，每次最多 100 批；業務每批為一筆紀錄或
一整份表單，每表每次最多處理 100 筆候選。業務作業用正式庫續跑游標，
未完成或缺檔資料不會永遠擋住後續資料。預覽是有限批次筆數，不代表全庫總數。
表結構不一致需先處理 schema 遷移，不得忽略不認識的欄位。

## 部署

在專案目錄執行，最後才啟用清理：

```bash
# 唯一需要本機 PostgreSQL 管理員權限的步驟，可重複執行
sudo -u postgres psql -X -v ON_ERROR_STOP=1 < deploy/create_archive_database.sql
# 建立來源完成登記表及封存表，不搬移／刪除資料
.venv/bin/python scripts/archive_maintenance.py --initialize
# 唯讀預覽
.venv/bin/python scripts/archive_maintenance.py
```

在現有 `.env` 新增，不能覆蓋既有帳密：

```dotenv
AMS_ARCHIVE_DATABASE=polimax_PostgreSQL_Expired
AMS_ARCHIVE_ENABLED=1
```

啟用後完整備份同時輸出 `postgresql.dump`、`expired.dump`、`persistent.tar`
及 SHA-256 manifest；封存庫備份失敗不會回報完整備份成功。
未啟用時仍維持原正式庫與檔案備份，清理則拒絕刪除。

```bash
.venv/bin/python scripts/backup_postgresql.py
.venv/bin/python scripts/archive_maintenance.py --apply
cp deploy/polimax-gps-cleanup.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user restart polimax-next@5173 polimax-next@5174
systemctl --user enable --now polimax-gps-cleanup.timer polimax-pg-backup.timer
```

沿用每天 03:30 清理、04:00 完整備份。舊 `gps_maintenance.py` 已轉接新流程，
不會退回直接刪除；舊 `--ensure-indexes` 選項不再使用。
暫停封存只需停用 `polimax-gps-cleanup.timer`，保留完整備份排程與
`AMS_ARCHIVE_ENABLED=1`，確保已有封存資料繼續備份。

也可用 CLI 登記完成；一般資料 KEY 為主鍵，表單為 form_id：

```bash
.venv/bin/python scripts/archive_maintenance.py --complete cost 123 \
  --completed-at '2026-05-01T17:00:00' --note '費用已核對完成' --actor 'operator-id'
```

## 查詢、備份與還原

「歷史封存」提供分頁查閱及原檔下載，需要 Administration 及對應業務完整
讀取權限；有欄位、擁有者或範圍限制的帳號不能透過原始資料查詢繞過限制。
歷史資料按需查詢，不自動合併到平常預約列表。

隔離還原時，分別用 `pg_restore --no-owner --no-acl -d ...` 還原兩份 dump，
依 manifest 驗證 tar 與兩份 dump 的 SHA-256。封存表不帶來源 identity default、
外鍵或 trigger，以保留原 ID，避免歷史紀錄依賴仍在變動的主檔。
回搬正式庫前須處理 ID 衝突、還原 JSON／附件及流水號，不能直接整庫覆蓋。
同主機封存不減少主機總容量，也不能取代離機備份。

## 測試

```bash
.venv/bin/python tests/test_retention.py
npm run build
```

測試建立並移除 `/tmp` 下 Unix socket PostgreSQL 叢集，完全不讀正式帳密。

## 2026-09-24 正式啟用紀錄

- 使用者以 PostgreSQL 管理員建立 `polimax_PostgreSQL_Expired`，完成初始化與 `.env` 啟用設定。
- 20 項封存隔離測試通過，包含續跑游標、當機重跑、內容衝突、主檔保留、權限、分塊附件、雙庫備份與還原；前端建置通過。
- 既有 `test_standalone.py` 有 1 項因舊 SSO 預設權限快照路徑失敗，該段程式未修改。
- 首次正式雙庫及持久檔案備份位於 `migration_backups/scheduled/20260923-230326`；SHA-256、兩份 dump 目錄及 295 個 tar 成員核對完成。
- 網站 5173／5174 重啟後 health 正常，封存 API 已載入且未登入請求回應 401。
- 首輪正式清理成功，搬移與刪除均為 0 筆。39 份舊表單因缺少 JSON 或附件而保留，其餘資料未符合完整封存條件。
- 每日清理與雙庫備份排程已啟用：台北時間 03:30 及 04:00。續跑游標已初始化並於正式庫驗證。
