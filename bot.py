"""
股票自動交易機器人 - 主程式
"""
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import schedule
import time
import logging
import asyncio
import os

from config import (
    TRADING_CONFIG, STRATEGY_PARAMS, TradingState,
    GOLDEN_CROSS_CONFIRM_BARS, COOLDOWN_HOURS, 
    TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, ENABLE_TELEGRAM_BOT, DEFAULT_SYMBOLS
)
from indicators import TechnicalIndicators
from json_manager import JsonManager

# 設定日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class StockTradingBot:
    """股票交易機器人"""
    
    def __init__(self):
        self.indicators = TechnicalIndicators(STRATEGY_PARAMS)
        # 從 JSON 取得監控股票清單
        from json_manager import JsonManager
        self.db = JsonManager()
        self.symbols = self.db.get_monitor_symbols()
        
        # 取得檢查間隔
        self.check_interval = TRADING_CONFIG["check_interval_seconds"]
        
        # 初始化 Telegram Bot（如果 ENABLE_TELEGRAM_BOT=true）
        self.bot = None
        if ENABLE_TELEGRAM_BOT and TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
            try:
                from telegram_bot import TradingBot
                self.bot = TradingBot(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, self.db)
                logger.info("Telegram Bot 已初始化")
            except Exception as e:
                logger.warning(f"Telegram Bot 初始化失敗: {e}")
        elif TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
            logger.info("Telegram Bot 未啟動 (ENABLE_TELEGRAM_BOT=false)")
    
    def is_trading_hours(self):
        """檢查是否在交易時間"""
        now = datetime.now()
        current_time = now.time()
        current_weekday = now.weekday()
        
        if current_weekday not in TRADING_CONFIG["trading_days"]:
            return False
        
        start = datetime.strptime(TRADING_CONFIG["trading_hours"]["start"], "%H:%M").time()
        end = datetime.strptime(TRADING_CONFIG["trading_hours"]["end"], "%H:%M").time()
        
        return start <= current_time <= end
    
    def get_stock_data(self, symbol, period="1mo", interval="5m"):
        """取得股票資料"""
        try:
            stock = yf.Ticker(symbol)
            df = stock.history(period=period, interval=interval)
            
            if df is None or len(df) < 50:
                logger.warning(f"{symbol}: 資料不足")
                return None
            
            # 移除時區
            if df.index.tz is not None:
                df.index = df.index.tz_convert('Asia/Taipei')
                df.index = df.index.tz_localize(None)
            
            logger.info(f"{symbol}: 取得 {len(df)} 筆資料")
            return df
            
        except Exception as e:
            logger.error(f"{symbol}: 取得資料失敗 - {e}")
            return None
    
    def check_buy_signal(self, df, symbol):
        """檢查買入訊號"""
        df_indicators = self.indicators.calculate(df)
        recent = df_indicators.tail(GOLDEN_CROSS_CONFIRM_BARS + 2)
        gc_result = self.indicators.detect_golden_cross(recent)
        
        if not gc_result.get("detected") or not gc_result.get("confirmed"):
            return None
        
        current = df_indicators.iloc[-1]
        current_bar_index = len(df_indicators) - 1
        
        stop_loss_info = self.indicators.calculate_stop_loss(
            df_indicators, current['Close'], current_bar_index
        )
        
        signal_data = {
            "type": "golden_cross",
            "price": current['Close'],
            "time": df_indicators.index[-1].strftime("%Y-%m-%d %H:%M:%S"),
            "bar_index": current_bar_index,
            "confirmed": True,
            "strength": gc_result.get("strength", 0),
            "rsi": current['RSI'],
            "adx": current['ADX'],
            "atr": current['ATR'],
            "stop_loss": stop_loss_info["stop_loss"],
            "risk_reward": stop_loss_info.get("risk_reward_ratio", 0)
        }
        
        logger.info(f"{symbol}: 買入訊號 - {signal_data}")
        return signal_data
    
    def check_sell_signal(self, df, symbol, position):
        """檢查賣出訊號"""
        holding = position.get("holding_info", {})
        entry_price = holding.get("entry_price", 0)
        stop_loss = holding.get("stop_loss", 0)
        
        df_indicators = self.indicators.calculate(df)
        current = df_indicators.iloc[-1]
        
        # ATR 硬停損
        if stop_loss and current['Close'] <= stop_loss:
            return {
                "type": "hard_stop_loss",
                "price": current['Close'],
                "reason": f"價格 ${current['Close']:.2f} <= 停損 ${stop_loss:.2f}",
                "pnl_pct": (current['Close'] - entry_price) / entry_price * 100 if entry_price > 0 else 0
            }
        
        # MACD 死亡交叉
        dc_result = self.indicators.detect_death_cross(df_indicators)
        
        # 檢查是否隔日
        signal_time = position.get("signal_data", {}).get("time", "")
        signal_date = signal_time.split()[0] if signal_time else ""
        current_date = datetime.now().strftime("%Y-%m-%d")
        
        if dc_result.get("detected"):
            if signal_date == current_date:
                logger.info(f"{symbol}: 死亡交叉，但仍在買入當日，暫不賣出")
                return None
            
            return {
                "type": "death_cross",
                "price": current['Close'],
                "reason": "MACD 死亡交叉",
                "pnl_pct": (current['Close'] - entry_price) / entry_price * 100 if entry_price > 0 else 0
            }
        
        return None
    
    def process_symbol(self, symbol):
        """處理單一股票"""
        # 檢查冷卻
        cooldown_symbols = self.db.get_cooldown_symbols()
        for pos in cooldown_symbols:
            if pos["symbol"] == symbol:
                logger.debug(f"{symbol}: 在冷卻期內，跳過")
                return
        
        # 取得股票資料
        df = self.get_stock_data(symbol)
        if df is None:
            return
        
        # 取得持倉
        position = self.db.get_position(symbol)
        
        if position is None:
            # 檢查買入訊號
            signal = self.check_buy_signal(df, symbol)
            
            if signal:
                self.db.log_signal(symbol, "buy", signal)
                
                if self.bot:
                    asyncio.run(self.bot.send_buy_signal(symbol, signal["price"], signal))
                
                self.db.create_position(symbol, signal, {
                    "MACD_DIF": signal.get("macd_dif"),
                    "MACD_DEA": signal.get("macd_dea"),
                    "RSI": signal.get("rsi"),
                    "ADX": signal.get("adx"),
                    "ATR": signal.get("atr")
                })
                
                logger.info(f"{symbol}: 買入訊號已發送")
        
        elif position["status"] in [TradingState.SIGNAL_BUY_SENT, TradingState.HOLDING]:
            # 檢查賣出訊號
            sell_signal = self.check_sell_signal(df, symbol, position)
            
            if sell_signal:
                self.db.log_signal(symbol, "sell", sell_signal)
                
                if self.bot:
                    if sell_signal["type"] == "hard_stop_loss":
                        asyncio.run(self.bot.send_force_sell_notification(
                            symbol, sell_signal["price"], sell_signal["reason"]
                        ))
                    else:
                        asyncio.run(self.bot.send_sell_signal(
                            symbol, sell_signal["price"],
                            sell_signal["reason"], sell_signal.get("pnl_pct")
                        ))
                
                self.db.update_position_status(
                    symbol, TradingState.SIGNAL_SELL_SENT,
                    {"sell_signal": sell_signal}
                )
                
                logger.info(f"{symbol}: 賣出訊號已發送 - {sell_signal['reason']}")
    
    def run_market_scan(self):
        """執行市場掃描"""
        if not self.is_trading_hours():
            logger.debug("非交易時間，跳過")
            return
        
        logger.info("開始市場掃描...")
        
        # 重新載入監控股票清單
        self.symbols = self.db.get_monitor_symbols()
        
        for symbol in self.symbols:
            try:
                self.process_symbol(symbol)
            except Exception as e:
                logger.error(f"{symbol}: 處理失敗 - {e}")
                self.db.log("ERROR", f"{symbol}: {e}", "market_scan")
        
        logger.info("市場掃描完成")
    
    def run_hard_stop_loss_check(self):
        """執行硬停損檢查"""
        if not self.is_trading_hours():
            return
        
        logger.info("執行硬停損檢查...")
        
        positions = self.db.get_all_positions(status=TradingState.HOLDING)
        
        for position in positions:
            symbol = position["symbol"]
            
            try:
                df = self.get_stock_data(symbol, period="1d", interval="1m")
                if df is None:
                    continue
                
                current_price = df.iloc[-1]['Close']
                stop_loss = position.get("holding_info", {}).get("stop_loss", 0)
                
                if stop_loss and current_price <= stop_loss:
                    logger.warning(f"{symbol}: 價格 ${current_price:.2f} <= 停損 ${stop_loss:.2f}")
                    
                    if self.bot:
                        asyncio.run(self.bot.send_force_sell_notification(
                            symbol, current_price, f"ATR 停損觸發"
                        ))
                    
                    self.db.update_position_status(
                        symbol, TradingState.SIGNAL_SELL_SENT,
                        {
                            "sell_signal": {
                                "type": "hard_stop_loss",
                                "price": current_price,
                                "reason": "ATR 停損觸發"
                            }
                        }
                    )
            
            except Exception as e:
                logger.error(f"{symbol}: 停損檢查失敗 - {e}")
    
    def start(self):
        """啟動機器人"""
        logger.info("啟動股票交易機器人...")
        
        # 清除過期冷卻
        self.db.clear_expired_cooldowns()
        
        # 排程
        schedule.every(self.check_interval).seconds.do(self.run_market_scan)
        schedule.every(1).minutes.do(self.run_hard_stop_loss_check)
        schedule.every().day.at("09:00").do(self.db.clear_expired_cooldowns)
        
        self.is_running = True
        
        # 啟動 Telegram Bot (僅當 ENABLE_TELEGRAM_BOT=true)
        if self.bot and ENABLE_TELEGRAM_BOT:
            logger.info("啟動 Telegram Bot...")
            self.bot.run()
        else:
            logger.info("Telegram Bot 模式: polling 已禁用 (使用 Webhook 或單一實例)")
        
        # 主迴圈
        while self.is_running:
            try:
                schedule.run_pending()
                time.sleep(1)
            except KeyboardInterrupt:
                logger.info("收到中斷訊號，停止機器人...")
                break
            except Exception as e:
                logger.error(f"執行錯誤: {e}")
                time.sleep(5)
        
        logger.info("機器人已停止")
    
    def stop(self):
        """停止機器人"""
        self.is_running = False


if __name__ == "__main__":
    bot = StockTradingBot()
    bot.start()
