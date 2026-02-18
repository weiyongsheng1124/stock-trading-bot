# 股票自動交易機器人

## 📊 專案簡介

自動化股票交易機器人，支援：
- 📈 MACD 黃金交叉策略
- 🛡️ ATR 停損風控
- 📱 Telegram 通知
- 🌐 Web Dashboard
- 💾 **JSON 檔案儲存**（無需 MongoDB）

---

## 🚀 快速開始

### 1. 安裝依賴

```bash
pip install -r requirements.txt
```

### 2. 設定環境變數

建立 `.env` 檔案：

```env
# Telegram (可選)
TELEGRAM_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

### 3. 啟動服務

```bash
# 啟動交易機器人
python bot.py

# 啟動 Web Dashboard (另一個終端機)
python dashboard/app.py
```

---

## 📁 專案結構

```
stock-trading-bot/
├── bot.py              # 主程式（交易邏輯）
├── config.py           # 設定檔
├── indicators.py        # 技術指標計算
├── json_manager.py      # JSON 檔案管理（取代 MongoDB）
├── telegram_bot.py      # Telegram 機器人
├── requirements.txt     # 依賴套件
├── data/               # JSON 數據儲存目錄（自動建立）
│   ├── positions.json  # 持倉記錄
│   ├── trades.json     # 交易紀錄
│   ├── signals.json    # 訊號紀錄
│   ├── logs.json       # 系統日誌
│   └── strategy_config.json # 策略配置
└── dashboard/
    └── app.py          # Flask 伺服器
    └── templates/      # HTML 範本
```

---

## 🎯 交易策略

### 買入條件
1. MACD 黃金交叉 (DIF 向上穿越 DEA)
2. 接下來 3 根 K 棒 DIF 持續在 DEA 上方
3. RSI/ADX 輔助確認

### 賣出條件
1. MACD 死亡交叉 (DIF 向下穿越 DEA)
2. 隔日第一根完整 K 棒完成後才允許賣出
3. ATR 硬停損觸發

### 風控
- 停損 = 買入價 - 2 × ATR
- 創近一年新高時，停損 = max(原停損, 最高價 - 2 × ATR)

---

## 📱 Telegram 指令

| 指令 | 功能 |
|------|------|
| `/start` | 啟動機器人 |
| `/buy [代碼]` | 確認買入 |
| `/sell [代碼]` | 確認賣出 |
| `/status` | 查看狀態 |
| `/positions` | 查看持倉 |
| `/trades` | 查看交易紀錄 |
| `/help` | 說明 |

---

## 🌐 Web Dashboard

| 頁面 | URL |
|------|-----|
| 即時監控 | `/` 或 `/monitor` |
| 策略配置 | `/config` |
| 回測 | `/backtest` |

---

## 📊 狀態機

```
NO_POSITION (無持倉)
    ↓ 買入訊號
SIGNAL_BUY_SENT (待買入)
    ↓ /buy 確認
HOLDING (持有中)
    ↓ 賣出訊號
SIGNAL_SELL_SENT (待賣出)
    ↓ /sell 確認
COOLDOWN (冷卻中)
    ↓ 隔日
NO_POSITION (無持倉)
```

---

## ⚠️ 風險警告

1. **過去績效不代表未來表現**
2. **請務必設定停損**
3. **建議先用模擬盤測試**
4. **不要投入超過能承受損失的資金**

---

## 📝 更新日誌

### v1.1.0 (2026-02-18)
- **改用 JSON 檔案儲存**（無需 MongoDB）
- 簡化部署流程
- 新增 Railway 部署支援

### v1.0.0 (2026-02-18)
- 初始版本
- MACD 策略
- Telegram 通知
- Web Dashboard

---

**GitHub**: https://github.com/weiyongsheng1124/stock-trading-bot
