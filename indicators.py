"""
技術指標計算模組
"""
import pandas as pd
import numpy as np
from ta.momentum import RSIIndicator
from ta.trend import MACD, ADXIndicator
from ta.volatility import AverageTrueRange
from config import STRATEGY_PARAMS


class TechnicalIndicators:
    """技術指標計算"""
    
    def __init__(self, params=None):
        """
        初始化
        Args:
            params: 策略參數，如果為 None 則使用預設值
        """
        self.params = params or STRATEGY_PARAMS
        self.macd_params = self.params["macd"]
        self.rsi_params = self.params["rsi"]
        self.adx_params = self.params["adx"]
        self.atr_params = self.params["atr"]
    
    def calculate(self, df):
        """
        計算所有技術指標
        Args:
            df: pandas DataFrame (必須包含 Open, High, Low, Close)
        Returns:
            pandas DataFrame 包含所有指標
        """
        result = df.copy()
        
        # MACD
        macd = MACD(
            close=result['Close'],
            window_slow=self.macd_params["slow"],
            window_fast=self.macd_params["fast"],
            window_sign=self.macd_params["signal"]
        )
        result['MACD_DIF'] = macd.macd()      # DIF
        result['MACD_DEA'] = macd.macd_signal()  # DEA
        result['MACD_HIST'] = macd.macd_diff()   # 柱狀圖
        
        # RSI
        rsi = RSIIndicator(
            close=result['Close'],
            window=self.rsi_params["period"]
        )
        result['RSI'] = rsi.rsi()
        
        # ADX
        adx = ADXIndicator(
            high=result['High'],
            low=result['Low'],
            close=result['Close'],
            window=self.adx_params["period"]
        )
        result['ADX'] = adx.adx()
        result['DI_Plus'] = adx.adx_pos()
        result['DI_Minus'] = adx.adx_neg()
        
        # ATR
        atr = AverageTrueRange(
            high=result['High'],
            low=result['Low'],
            close=result['Close'],
            window=self.atr_params["period"]
        )
        result['ATR'] = atr.average_true_range()
        
        # 計算均線（用於判斷近一年新高）
        result['MA20'] = result['Close'].rolling(window=20).mean()
        
        return result
    
    def detect_golden_cross(self, df, lookback=5):
        """
        偵測 MACD 黃金交叉
        Args:
            df: 包含 MACD 指標的 DataFrame
            lookback: 回測棒數
        Returns:
            dict: 包含交叉位置、強度等資訊
        """
        if len(df) < lookback + 1:
            return {"detected": False, "reason": "資料不足"}
        
        # 檢查第 0 根是否發生黃金交叉
        current = df.iloc[-1]
        previous = df.iloc[-2]
        
        # 黃金交叉條件：DIF 向上穿越 DEA
        golden_cross = (
            (current['MACD_DIF'] > current['MACD_DEA']) and
            (previous['MACD_DIF'] <= previous['MACD_DEA'])
        )
        
        if not golden_cross:
            return {"detected": False, "reason": "無黃金交叉"}
        
        # 檢查接下來 3 根 DIF 是否都在 DEA 上方
        confirm_bars = self.params.get("confirm_bars", 3)
        
        if len(df) < confirm_bars + 1:
            return {"detected": False, "reason": "資料不足，無法確認"}
        
        # 檢查第 1, 2, 3 根是否 DIF > DEA
        all_above = True
        for i in range(1, confirm_bars + 1):
            if df.iloc[-i]['MACD_DIF'] <= df.iloc[-i]['MACD_DEA']:
                all_above = False
                break
        
        if not all_above:
            return {
                "detected": True,
                "confirmed": False,
                "reason": "黃金交叉未完全確認"
            }
        
        # 計算黃金交叉強度
        diff = current['MACD_DIF'] - current['MACD_DEA']
        strength = min(abs(diff) / (current['ATR'] + 0.001) * 100, 100)
        
        return {
            "detected": True,
            "confirmed": True,
            "strength": strength,
            "reason": "黃金交叉已確認",
            "diff": diff,
            "histogram": current['MACD_HIST']
        }
    
    def detect_death_cross(self, df, lookback=5):
        """
        偵測 MACD 死亡交叉
        Args:
            df: 包含 MACD 指標的 DataFrame
            lookback: 回測棒數
        Returns:
            dict: 包含交叉位置等資訊
        """
        if len(df) < 2:
            return {"detected": False, "reason": "資料不足"}
        
        current = df.iloc[-1]
        previous = df.iloc[-2]
        
        # 死亡交叉條件：DIF 向下穿越 DEA
        death_cross = (
            (current['MACD_DIF'] < current['MACD_DEA']) and
            (previous['MACD_DIF'] >= previous['MACD_DEA'])
        )
        
        return {
            "detected": death_cross,
            "reason": "死亡交叉" if death_cross else "無死亡交叉"
        }
    
    def check_rsi(self, df):
        """檢查 RSI 狀態"""
        current = df.iloc[-1]
        
        return {
            "value": current['RSI'],
            "oversold": current['RSI'] < self.rsi_params["oversold"],
            "overbought": current['RSI'] > self.rsi_params["overbought"],
            "neutral": not (
                current['RSI'] < self.rsi_params["oversold"] or
                current['RSI'] > self.rsi_params["overbought"]
            )
        }
    
    def check_adx(self, df):
        """檢查 ADX 狀態"""
        current = df.iloc[-1]
        
        return {
            "value": current['ADX'],
            "strong_trend": current['ADX'] > self.adx_params["threshold"],
            "di_plus": current['DI_Plus'],
            "di_minus": current['DI_Minus'],
            "trend_direction": "up" if current['DI_Plus'] > current['DI_Minus'] else "down"
        }
    
    def calculate_stop_loss(self, df, entry_price, entry_bar_index=None):
        """
        計算停損價格
        停損 = 進場價 - 2 * ATR
        若創近一年新高，則使用 max(原停損, 最高價 - 2 * ATR)
        """
        current = df.iloc[-1]
        atr = current['ATR']
        
        # 基本停損
        base_stop_loss = entry_price - (atr * self.params["stop_loss_multiplier"])
        
        # 檢查是否創近一年新高
        lookback = self.params.get("new_high_period", 252)
        
        if len(df) >= lookback and entry_bar_index is not None:
            # 計算近一年最高價
            high_lookback = min(lookback, len(df))
            highs = df['High'].iloc[-high_lookback:]
            
            # 如果進場那根 K 棒是近一年新高
            entry_high = df.iloc[entry_bar_index]['High'] if entry_bar_index else df.iloc[-1]['High']
            one_year_high = highs.max()
            
            if entry_high >= one_year_high * 0.98:  # 接近新高
                # 使用較高的停損價
                new_high_stop = entry_high - (atr * self.params["stop_loss_multiplier"])
                stop_loss = max(base_stop_loss, new_high_stop)
                is_new_high = True
            else:
                stop_loss = base_stop_loss
                is_new_high = False
        else:
            stop_loss = base_stop_loss
            is_new_high = False
        
        return {
            "stop_loss": round(stop_loss, 2),
            "atr": round(atr, 2),
            "base_stop_loss": round(base_stop_loss, 2),
            "is_new_high_stop": is_new_high,
            "risk_reward_ratio": round((current['Close'] - stop_loss) / atr, 2)
        }
    
    def is_market_open(self):
        """檢查是否在交易時間內"""
        from datetime import datetime, time
        import pytz
        
        now = datetime.now(pytz.timezone('Asia/Taipei'))
        current_time = now.time()
        current_weekday = now.weekday()
        
        start_time = time(9, 0)
        end_time = time(13, 30)
        
        # 檢查是否為平日
        if current_weekday not in [0, 1, 2, 3, 4]:
            return False
        
        # 檢查是否在交易時段
        if start_time <= current_time <= end_time:
            return True
        
        return False
    
    def should_buy(self, df):
        """
        綜合判斷是否應該買入
        買入條件：
        1. MACD 黃金交叉已確認（必要條件）
        2. RSI < 50（不能太超買）
        3. ADX > 15（有趨勢）
        """
        current = df.iloc[-1]
        
        # 檢查 MACD 黃金交叉
        gc = self.detect_golden_cross(df)
        
        # RSI 狀態
        rsi_oversold = current['RSI'] < 50  # 偏弱或超賣
        
        # ADX 狀態
        adx_trend = current['ADX'] > 15  # 有趨勢
        
        # 綜合判斷
        buy_score = 0
        reasons = []
        
        if gc["detected"] and gc["confirmed"]:
            buy_score += 2
            reasons.append("MACD黃金交叉已確認")
        elif gc["detected"] and not gc["confirmed"]:
            buy_score += 1
            reasons.append("MACD黃金交叉未確認")
        
        if rsi_oversold:
            buy_score += 1
            reasons.append("RSI偏弱(<50)")
        
        if adx_trend:
            buy_score += 1
            reasons.append("ADX有趨勢(>15)")
        
        # 買入條件：至少 3 分
        should_buy = buy_score >= 3
        
        return {
            "should_buy": should_buy,
            "score": buy_score,
            "max_score": 4,
            "reasons": reasons,
            "macd_confirmed": gc["confirmed"],
            "rsi_oversold": rsi_oversold,
            "adx_trend": adx_trend,
            "rsi_value": round(current['RSI'], 2),
            "adx_value": round(current['ADX'], 2)
        }
    
    def should_sell(self, df):
        """
        綜合判斷是否應該賣出
        賣出條件（滿足其一）：
        1. MACD 死亡交叉
        2. RSI > 70（超買）
        3. ADX < 15（無趨勢）
        """
        current = df.iloc[-1]
        
        # 檢查 MACD 死亡交叉
        dc = self.detect_death_cross(df)
        
        # RSI 狀態
        rsi_overbought = current['RSI'] > 70
        
        # ADX 狀態
        no_trend = current['ADX'] < 15
        
        # 賣出條件
        should_sell = dc["detected"] or rsi_overbought or no_trend
        
        reasons = []
        if dc["detected"]:
            reasons.append("MACD死亡交叉")
        if rsi_overbought:
            reasons.append("RSI超買(>70)")
        if no_trend:
            reasons.append("ADX無趨勢(<15)")
        
        return {
            "should_sell": should_sell,
            "reasons": reasons,
            "death_cross": dc["detected"],
            "rsi_overbought": rsi_overbought,
            "no_trend": no_trend,
            "rsi_value": round(current['RSI'], 2),
            "adx_value": round(current['ADX'], 2)
        }
