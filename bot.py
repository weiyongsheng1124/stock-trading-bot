"""
股票自動交易機器人 - 主程式
=============================
功能：
1. 抓取報價（每5分鐘）
2. 計算技術指標
3. 判斷買賣條件
4. 風控檢查
5. Telegram 通知
6. MongoDB 儲存

Author: WayneBot
Date: 2026-02-18
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import schedule
import time
import logging
import threading
import asyncio
from pathlib import Path

from config import (
    TRADING_CONFIG, STRATEGY_PARAMS, TradingState,
    GOLDEN_CROSS_CONFIRM_BARS, COOLDOWN_HOURS
)
from indicators import TechnicalIndicators
from mongo_manager import MongoManager
from telegram_bot import TradingBot

# 設定日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class StockTradingBot:
    """股票交易機器人"""
    
    def __init__(self):
        """初始化"""
        self.indicators = TechnicalIndicators(STRATEGY_PARAMS)
        self.mongo = MongoManager()
        self.is_running = False
        self.check_interval = TRADING_CONFIG["interval_seconds"]  # 5分鐘
        
        # 初始化 Telegram Bot（如果 token 已設定）
        self.bot = None
        if TRADING_CONFIG.get("telegram_token") and TRADING_CONFIG.get("telegram_chat_id"):
            self.bot = TradingBot(
                TRADING_CONFIG["telegram_token"],
                TRADING_CONFIG["telegram_chat_id"],
                self.mongo
            )
    
    def is_trading_hours(self):
        """檢查是否在交易時間"""
        now = datetime.now()
        current_time = now.time()
        current_weekday = now.weekday()
        
        # 檢查是否為平日
        if current_weekday not in TRADING_CONFIG["trading_days"]:
            return False
        
        # 檢查交易時間
        start = datetime.strptime(TRADING_CONFIG["trading_hours"]["start"], "%H:%M").time()
        end = datetime.strptime(TRADING_CONFIG["trading_hours"]["end"], "%H:%M").time()
        
        return start <= current_time <= end
    
    def get_stock_data(self, symbol, period="1mo", interval="5m"):
        """
        取得股票資料
        Args:
            symbol: 股票代碼
            period: 資料期間
            interval: 資料間隔
        Returns:
            pandas DataFrame or None
        """
        try:
            stock = yf.Ticker(symbol)
            df = stock.history(period=period, interval=interval)
            
            if df is None or len(df) < 50:
                logger.warning(f"{symbol}: 資料不足")
                return None
            
            # 移除時區資訊，轉換為台灣時間
            if df.index.tz is not None:
                df.index = df.index.tz_convert('Asia/Taipei')
                df.index = df.index.tz_localize(None)
            
            logger.info(f"{symbol}: 取得 {len(df)} 筆資料")
            return df
            
        except Exception as e:
            logger.error(f"{symbol}: 取得資料失敗 - {e}")
            return None
    
    def check_buy_signal(self, df, symbol):
        """
        檢查買入訊號
        條件：
        1. MACD 黃金交叉
        2. 接下来 3 根 K 棒 DIF 都在 DEA 上方
        3. RSI/ADX 輔助確認
        """
        # 計算技術指標
        df_indicators = self.indicators.calculate(df)
        
        # 取得最近 5 根 K 棒
        recent = df_indicators.tail(GOLDEN_CROSS_CONFIRM_BARS + 2)
        
        # 偵測黃金交叉
        gc_result = self.indicators.detect_golden_cross(recent)
        
        if not gc_result.get("detected"):
            return None
        
        if not gc_result.get("confirmed"):
            # 黃金交叉尚未完全確認
            logger.info(f"{symbol}: 黃金交叉待確認")
            return None
        
        # 取得目前 K 棒資料
        current = df_indicators.iloc[-1]
        current_bar_index = len(df_indicators) - 1
        
        # RSI 檢查
        rsi_check = self.indicators.check_rsi(df_indicators)
        
        # ADX 檢查
        adx_check = self.indicators.check_adx(df_indicators)
        
        # 計算停損
        stop_loss_info = self.indicators.calculate_stop_loss(
            df_indicators,
            current['Close'],
            current_bar_index
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
        """
        檢查賣出訊號
        條件：
        1. 持倉狀態
        2. MACD 死亡交叉
        3. 或 ATR 停損觸發
        """
        # 取得持倉資訊
        holding = position.get("holding_info", {})
        entry_price = holding.get("entry_price", 0)
        stop_loss = holding.get("stop_loss", 0)
        
        # 計算技術指標
        df_indicators = self.indicators.calculate(df)
        current = df_indicators.iloc[-1]
        
        # 檢查 ATR 停損（硬停損）
        if stop_loss and current['Close'] <= stop_loss:
            return {
                "type": "hard_stop_loss",
                "price": current['Close'],
                "reason": f"價格 ${current['Close']:.2f} <= 停損 ${stop_loss:.2f}",
                "pnl_pct": (current['Close'] - entry_price) / entry_price * 100 if entry_price > 0 else 0
            }
        
        # 檢查 MACD 死亡交叉
        dc_result = self.indicators.detect_death_cross(df_indicators)
        
        # 檢查是否為隔日第一根完整 K 棒
        # 這需要記錄買入時的 K 棒索引
        signal_bar_index = position.get("signal_data", {}).get("bar_index", 0)
        current_bar_index = len(df_indicators) - 1
        
        # 檢查是否已過隔日
        signal_time = position.get("signal_data", {}).get("time", "")
        signal_date = signal_time.split()[0] if signal_time else ""
        current_date = datetime.now().strftime("%Y-%m-%d")
        
        # 死亡交叉才需要隔日確認
        if dc_result.get("detected"):
            # 如果買入當天還沒收盤，不允許賣出
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
        """
        處理單一股票
        """
        # 檢查是否在冷卻期
        cooldown_positions = self.mongo.get_cooldown_symbols()
        for pos in cooldown_positions:
            if pos["symbol"] == symbol:
                logger.debug(f"{symbol}: 在冷卻期內，跳過")
                return
        
        # 取得股票資料
        df = self.get_stock_data(symbol)
        if df is None:
            return
        
        # 取得持倉
        position = self.mongo.get_position(symbol)
        
        if position is None:
            # 沒有持倉，檢查買入訊號
            signal = self.check_buy_signal(df, symbol)
            
            if signal:
                # 記錄訊號
                self.mongo.log_signal(symbol, "buy", signal)
                
                # 發送買入通知
                if self.bot:
                    asyncio.run(self.bot.send_buy_signal(
                        symbol,
                        signal["price"],
                        signal
                    ))
                
                # 建立持倉記錄
                self.mongo.create_position(symbol, signal, {
                    "MACD_DIF": signal.get("macd_dif"),
                    "MACD_DEA": signal.get("macd_dea"),
                    "RSI": signal.get("rsi"),
                    "ADX": signal.get("adx"),
                    "ATR": signal.get("atr")
                })
                
                logger.info(f"{symbol}: 買入訊號已發送")
        
        elif position["status"] in [TradingState.SIGNAL_BUY_SENT, TradingState.HOLDING]:
            # 有持倉，檢查賣出訊號
            sell_signal = self.check_sell_signal(df, symbol, position)
            
            if sell_signal:
                # 記錄訊號
                self.mongo.log_signal(symbol, "sell", sell_signal)
                
                # 發送賣出通知
                if self.bot:
                    if sell_signal["type"] == "hard_stop_loss":
                        # 硬停損通知
                        asyncio.run(self.bot.send_force_sell_notification(
                            symbol,
                            sell_signal["price"],
                            sell_signal["reason"]
                        ))
                    else:
                        asyncio.run(self.bot.send_sell_signal(
                            symbol,
                            sell_signal["price"],
                            sell_signal["reason"],
                            sell_signal.get("pnl_pct")
                        ))
                
                # 更新持倉狀態為 SIGNAL_SELL_SENT
                self.mongo.update_position_status(
                    symbol,
                    TradingState.SIGNAL_SELL_SENT,
                    {"sell_signal": sell_signal}
                )
                
                logger.info(f"{symbol}: 賣出訊號已發送 - {sell_signal['reason']}")
    
    def run_market_scan(self):
        """執行市場掃描"""
        if not self.is_trading_hours():
            logger.debug("非交易時間，跳過")
            return
        
        logger.info("開始市場掃描...")
        
        for symbol in TRADING_CONFIG["symbols"]:
            try:
                self.process_symbol(symbol)
            except Exception as e:
                logger.error(f"{symbol}: 處理失敗 - {e}")
                self.mongo.log("ERROR", f"{symbol}: {e}", "market_scan")
        
        logger.info("市場掃描完成")
    
    def run_hard_stop_loss_check(self):
        """執行硬停損檢查"""
        if not self.is_trading_hours():
            return
        
        logger.info("執行硬停損檢查...")
        
        positions = self.mongo.get_all_positions(status=TradingState.HOLDING)
        
        for position in positions:
            symbol = position["symbol"]
            
            try:
                # 取得最新報價
                df = self.get_stock_data(symbol, period="1d", interval="1m")
                if df is None:
                    continue
                
                current_price = df.iloc[-1]['Close']
                stop_loss = position.get("holding_info", {}).get("stop_loss", 0)
                
                # 檢查是否觸發停損
                if stop_loss and current_price <= stop_loss:
                    logger.warning(f"{symbol}: 價格 ${current_price:.2f} <= 停損 ${stop_loss:.2f}")
                    
                    # 發送強制賣出通知
                    if self.bot:
                        asyncio.run(self.bot.send_force_sell_notification(
                            symbol,
                            current_price,
                            f"ATR 停損觸發 (停損: {stop_loss:.2f})"
                        ))
                    
                    # 更新狀態
                    self.mongo.update_position_status(
                        symbol,
                        TradingState.SIGNAL_SELL_SENT,
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
        self.mongo.clear_expired_cooldowns()
        
        # 排程：每5分鐘執行市場掃描
        schedule.every(self.check_interval).seconds.do(self.run_market_scan)
        
        # 排程：每分鐘執行硬停損檢查
        schedule.every(1).minutes.do(self.run_hard_stop_loss_check)
        
        # 排程：每日清除過期冷卻
        schedule.every().day.at("09:00").do(self.mongo.clear_expired_cooldowns)
        
        self.is_running = True
        
        # 啟動 Telegram Bot（如果已設定）
        if self.bot:
            logger.info("啟動 Telegram Bot...")
            self.bot.run()
        
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
        
        # 清理
        self.mongo.close()
        logger.info("機器人已停止")
    
    def stop(self):
        """停止機器人"""
        self.is_running = False


# ============ 主程式 ============

if __name__ == "__main__":
    bot = StockTradingBot()
    bot.start()
