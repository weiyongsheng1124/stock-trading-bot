# Railway 分開部署說明

## 檔案結構

```
stock-trading-bot/
├── Procfile           # Dashboard 部署
├── Procfile.dashboard # 等同於 Procfile
├── Procfile.bot      # Bot 部署
├── dashboard/
│   └── app.py        # Web Dashboard
├── bot.py            # 交易機器人
├── data/             # 共用資料夾（兩者都會使用）
├── config.py         # 共用設定
├── json_manager.py   # 共用資料管理
└── requirements.txt   # 共用依賴
```

## 部署步驟

### Railway Service 1 - Dashboard
1. 在 Railway 建立新服務
2. 連接 GitHub 倉庫
3. **Procfile Path**: 留空（使用預設的 `Procfile`）
4. 環境變數：不需要特別設定

### Railway Service 2 - Bot
1. 在 Railway 建立另一個新服務
2. 連接同一個 GitHub 倉庫
3. **Procfile Path**: `Procfile.bot`
4. 環境變數：
   ```
   ENABLE_TRADING=true
   ENABLE_TELEGRAM_BOT=true
   ```

## 共用資料夾

兩個服務會共用 `data/` 目錄下的檔案：
- `monitor_symbols.json` - 監控股票清單
- `symbol_params.json` - 個別股票參數（透過內存存儲）
- `positions.json` - 持倉資料
- `trades.json` - 交易紀錄
- `signals.json` - 訊號紀錄
- `logs.json` - 日誌

## 注意事項

1. **Railway filesystem 是唯讀的**，所以：
   - 監控股票清單可能無法寫入
   - 個別股票參數使用內存存儲（重啟後會重置）
   - 持倉/交易資料可能無法持久化

2. **建議分開部署的話**：
   - 使用 PostgreSQL 等資料庫替代 JSON 檔案
   - 或使用 Railway 的 Volume 來持久化 data/ 目錄
