# FindMy 獨立部署

程式位於 `integrations/findmy/`，從本專案 `.env`／`env` 讀取 PostgreSQL 設定，不需要舊專案。匯入器只允許目標 PostgreSQL 資料庫名稱 `polimax_PostgreSQL`，並將裝置回報寫入 `FindMy` 與 `new_reports`。

在專案根目錄執行：

```sh
python3 -m venv .venv-findmy
.venv-findmy/bin/python -m pip install -r integrations/findmy/requirements.txt
.venv-findmy/bin/python integrations/findmy/create_findmy_session.py
```

Apple 密碼及 2FA 由互動方式輸入。登入資料存於 `AMS_DATA_DIR/findmy/account.json`，Anisette 快取存於同目錄的 `ani_libs.bin`；預設 `AMS_DATA_DIR=.data`。兩者為私密資料，不進 Git，搬機時需妥善複製，或重新登入。首次使用可能需要從 Apple 下載支援套件。

`deploy/polimax-findmy-import.service` 與 `.timer` 提供每小時匯入。範本假設專案在 `%h/polimax_next` 且使用 `.data`；若位置或資料目錄改變，需修改服務路徑及 `ConditionPathExists`。安裝至 `~/.config/systemd/user/` 後執行：

```sh
systemctl --user daemon-reload
systemctl --user enable --now polimax-findmy-import.timer
systemctl --user start polimax-findmy-import.service
```

排程要求已有 Apple session，不會詢問帳密。手動單次執行：

```sh
.venv-findmy/bin/python integrations/findmy/findmyupdate.py
```

FindMy 環境包含後端 requirements，避免匯入資料庫設定時缺少 GeoAlchemy2。資料寫入具去重處理。
