"""
系統配置
"""
import os
from datetime import datetime

# ============ MongoDB 配置 ============
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DB = os.getenv("MONGODB_DB", "stock_trading")

# ============ Telegram 配置 ============
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ============ 交易配置 ============
TRADING_CONFIG = {
    "symbols": ["2330.TW", "8110.TW", "2337.TW"],  # 監控股票清單
    "interval_seconds": 300,  # 5分鐘
    "trading_hours": {
        "start": "09:00",
        "end": "13:30",
        "timezone": "Asia/Taipei"
    },
    "trading_days": [0, 1, 2, 3, 4]  # 週一到週五
}

# ============ 策略參數 ============
STRATEGY_PARAMS = {
    "macd": {
        "fast": 12,
        "slow": 26,
        "signal": 9
    },
    "rsi": {
        "period": 14,
        "oversold": 30,
        "overbought": 70
    },
    "adx": {
        "period": 14,
        "threshold": 20
    },
    "atr": {
        "period": 14
    },
    "confirm_bars": 3,  # DIF > DEA 確認棒數
    "stop_loss_multiplier": 2.0,  # 停損 = 2 * ATR
    "new_high_period": 252  # 近一年新高 (約252交易日)
}

# ============ 狀態機 ============
class TradingState:
    NO_POSITION = "NO_POSITION"           # 無持倉
    SIGNAL_BUY_SENT = "SIGNAL_BUY_SENT"   # 已發送買入訊號
    HOLDING = "HOLDING"                   # 持有中
    SIGNAL_SELL_SENT = "SIGNAL_SELL_SENT" # 已發送賣出訊號
    COOLDOWN = "COOLDOWN"                 # 冷卻中

# ============ 冷卻時間（賣出後隔日才能再買）===========
COOLDOWN_HOURS = 24  # 小時

# ============ 黃金交叉確認 ============
# 第0根：發生交叉
# 第1,2,3根：DIF > DEA
GOLDEN_CROSS_CONFIRM_BARS = 3

# ============ API 配置 ============
STOCK_API_CONFIG = {
    "yfinance": {
        "period": "1mo",
        "interval": "5m"
    }
}
