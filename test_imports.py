# 測試程式碼是否有語法錯誤
import sys
sys.path.insert(0, '.')

try:
    from config import STRATEGY_PARAMS, TRADING_CONFIG
    print('✅ config 載入成功')
except Exception as e:
    print(f'❌ config 錯誤: {e}')
    sys.exit(1)

try:
    from indicators import TechnicalIndicators
    print('✅ indicators 載入成功')
except Exception as e:
    print(f'❌ indicators 錯誤: {e}')
    sys.exit(1)

try:
    from json_manager import JsonManager
    print('✅ json_manager 載入成功')
except Exception as e:
    print(f'❌ json_manager 錯誤: {e}')
    sys.exit(1)

try:
    from telegram_bot import TradingBot
    print('✅ telegram_bot 載入成功')
except Exception as e:
    print(f'❌ telegram_bot 錯誤: {e}')
    sys.exit(1)

print('\n✅ 所有模組測試通過！')
print(f'監控股票: {TRADING_CONFIG["symbols"]}')
print(f'MACD 參數: {STRATEGY_PARAMS["macd"]}')
