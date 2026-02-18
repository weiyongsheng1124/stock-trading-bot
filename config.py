"""
股票交易機器人配置文件
"""
import os
from datetime import datetime, timedelta

# ============ JSON 文件路徑 ============
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
POSITIONS_FILE = os.path.join(DATA_DIR, "positions.json")
TRADES_FILE = os.path.join(DATA_DIR, "trades.json")
SIGNALS_FILE = os.path.join(DATA_DIR, "signals.json")
LOGS_FILE = os.path.join(DATA_DIR, "logs.json")
CONFIG_FILE = os.path.join(DATA_DIR, "strategy_config.json")
SYMBOLS_FILE = os.path.join(DATA_DIR, "monitor_symbols.json")

# 確保數據目錄存在
os.makedirs(DATA_DIR, exist_ok=True)

# ============ Telegram 配置 ============
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ============ 控制開關 ============
ENABLE_TELEGRAM_BOT = os.getenv("ENABLE_TELEGRAM_BOT", "false").lower() == "true"

# ============ 預設監控股票 ============
DEFAULT_SYMBOLS = ["2330.TW", "8110.TW", "2337.TW"]

# ============ 監控股票清單 ============
TRADING_CONFIG = {
    "symbols": DEFAULT_SYMBOLS,
    "check_interval_seconds": 300,  # 5分鐘
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
        "fast": 8,
        "slow": 20,
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
    "stop_loss_multiplier": 2.0,
    "new_high_period": 252  # 近一年新高
}

# ============ 狀態機 ============
class TradingState:
    NO_POSITION = "NO_POSITION"           # 無持倉
    SIGNAL_BUY_SENT = "SIGNAL_BUY_SENT"   # 已發送買入訊號
    HOLDING = "HOLDING"                   # 持有中
    SIGNAL_SELL_SENT = "SIGNAL_SELL_SENT" # 已發送賣出訊號
    COOLDOWN = "COOLDOWN"                 # 冷卻中

# ============ 冷卻時間 ============
COOLDOWN_HOURS = 24

# ============ 黃金交叉確認 ============
GOLDEN_CROSS_CONFIRM_BARS = 3
