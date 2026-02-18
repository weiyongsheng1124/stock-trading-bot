"""
JSON 文件管理模組 - 取代 MongoDB
"""
import json
import os
import shutil
from datetime import datetime
from config import (
    POSITIONS_FILE, TRADES_FILE, SIGNALS_FILE, 
    LOGS_FILE, CONFIG_FILE, DATA_DIR, TradingState
)


class JsonManager:
    """JSON 文件管理類"""
    
    def __init__(self):
        """初始化"""
        self.data_dir = DATA_DIR
        os.makedirs(self.data_dir, exist_ok=True)
        
        # 確保文件存在
        for file_path in [POSITIONS_FILE, TRADES_FILE, SIGNALS_FILE, LOGS_FILE]:
            if not os.path.exists(file_path):
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump([], f)
        
        # 確保監控股票文件存在
        if not os.path.exists(SYMBOLS_FILE):
            with open(SYMBOLS_FILE, 'w', encoding='utf-8') as f:
                json.dump({"symbols": DEFAULT_SYMBOLS}, f, ensure_ascii=False)
        
        # 讀取策略配置
        if not os.path.exists(CONFIG_FILE):
            from config import STRATEGY_PARAMS
            self.save_strategy_params(STRATEGY_PARAMS)
    
    # ============ 文件讀寫 ============
    
    def _read_json(self, file_path):
        """讀取 JSON 文件"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return []
    
    def _write_json(self, file_path, data):
        """寫入 JSON 文件"""
        # 確保目錄存在
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    
    # ============ 持倉管理 ============
    
    def get_position(self, symbol):
        """取得特定股票的持倉"""
        positions = self._read_json(POSITIONS_FILE)
        for pos in positions:
            if pos.get("symbol") == symbol and pos.get("status") in [
                TradingState.SIGNAL_BUY_SENT, TradingState.HOLDING
            ]:
                return pos
        return None
    
    def get_all_positions(self, status=None):
        """取得所有持倉"""
        positions = self._read_json(POSITIONS_FILE)
        if status:
            return [p for p in positions if p.get("status") == status]
        return [p for p in positions if p.get("status") in [
            TradingState.SIGNAL_BUY_SENT, TradingState.HOLDING, TradingState.SIGNAL_SELL_SENT
        ]]
    
    def create_position(self, symbol, signal_data, indicators):
        """建立新持倉"""
        positions = self._read_json(POSITIONS_FILE)
        
        # 刪除舊的同名持倉
        positions = [p for p in positions if p.get("symbol") != symbol]
        
        position = {
            "id": f"{symbol}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "symbol": symbol,
            "status": TradingState.SIGNAL_BUY_SENT,
            "signal_data": {
                "type": signal_data.get("type"),
                "price": signal_data.get("price"),
                "time": signal_data.get("time"),
                "bar_index": signal_data.get("bar_index"),
                "confirmed": signal_data.get("confirmed", False)
            },
            "indicators": {
                "macd_dif": indicators.get("MACD_DIF"),
                "macd_dea": indicators.get("MACD_DEA"),
                "rsi": indicators.get("RSI"),
                "adx": indicators.get("ADX"),
                "atr": indicators.get("ATR")
            },
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
        
        positions.append(position)
        self._write_json(POSITIONS_FILE, positions)
        return position
    
    def update_position_status(self, symbol, status, additional_data=None):
        """更新持倉狀態"""
        positions = self._read_json(POSITIONS_FILE)
        for pos in positions:
            if pos.get("symbol") == symbol and pos.get("status") != "CLOSED":
                pos["status"] = status
                pos["updated_at"] = datetime.now().isoformat()
                if additional_data:
                    pos.update(additional_data)
                break
        self._write_json(POSITIONS_FILE, positions)
    
    def add_holding_info(self, symbol, entry_price, entry_time, stop_loss, quantity=0):
        """新增持倉資訊"""
        positions = self._read_json(POSITIONS_FILE)
        for pos in positions:
            if pos.get("symbol") == symbol:
                pos["status"] = TradingState.HOLDING
                pos["holding_info"] = {
                    "entry_price": entry_price,
                    "entry_time": entry_time,
                    "stop_loss": stop_loss,
                    "quantity": quantity
                }
                pos["updated_at"] = datetime.now().isoformat()
                break
        self._write_json(POSITIONS_FILE, positions)
    
    def close_position(self, symbol, exit_price, exit_time, pnl_pct, trade_type="manual"):
        """關閉持倉"""
        positions = self._read_json(POSITIONS_FILE)
        for pos in positions:
            if pos.get("symbol") == symbol:
                pos["status"] = TradingState.COOLDOWN
                pos["close_info"] = {
                    "exit_price": exit_price,
                    "exit_time": exit_time,
                    "pnl_pct": pnl_pct,
                    "trade_type": trade_type
                }
                pos["updated_at"] = datetime.now().isoformat()
                pos["closed_at"] = datetime.now().isoformat()
                break
        self._write_json(POSITIONS_FILE, positions)
    
    def delete_position(self, symbol):
        """刪除持倉"""
        positions = self._read_json(POSITIONS_FILE)
        positions = [p for p in positions if p.get("symbol") != symbol]
        self._write_json(POSITIONS_FILE, positions)
    
    def set_cooldown(self, symbol, cooldown_until):
        """設定冷卻"""
        positions = self._read_json(POSITIONS_FILE)
        for pos in positions:
            if pos.get("symbol") == symbol:
                pos["status"] = TradingState.COOLDOWN
                pos["cooldown_until"] = cooldown_until
                pos["updated_at"] = datetime.now().isoformat()
                break
        self._write_json(POSITIONS_FILE, positions)
    
    def get_cooldown_symbols(self):
        """取得冷卻中的股票"""
        positions = self._read_json(POSITIONS_FILE)
        now = datetime.now()
        return [p for p in positions if p.get("status") == TradingState.COOLDOWN 
                and datetime.fromisoformat(p.get("cooldown_until", "2000-01-01")) > now]
    
    def clear_expired_cooldowns(self):
        """清除過期冷卻"""
        positions = self._read_json(POSITIONS_FILE)
        now = datetime.now()
        updated = False
        
        for pos in positions:
            if pos.get("status") == TradingState.COOLDOWN:
                cooldown_until = datetime.fromisoformat(pos.get("cooldown_until", "2000-01-01"))
                if cooldown_until <= now:
                    # 刪除過期的持倉
                    positions.remove(pos)
                    updated = True
        
        if updated:
            self._write_json(POSITIONS_FILE, positions)
        
        return len(positions)
    
    # ============ 交易紀錄 ============
    
    def add_trade(self, symbol, trade_type, entry_price, exit_price, quantity, pnl_pct, reason=""):
        """新增交易"""
        trades = self._read_json(TRADES_FILE)
        trade = {
            "id": f"{symbol}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "symbol": symbol,
            "trade_type": trade_type,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "quantity": quantity,
            "pnl_pct": pnl_pct,
            "reason": reason,
            "created_at": datetime.now().isoformat()
        }
        trades.append(trade)
        self._write_json(TRADES_FILE, trades)
        return trade
    
    def get_trades(self, symbol=None, limit=50):
        """取得交易紀錄"""
        trades = self._read_json(TRADES_FILE)
        if symbol:
            trades = [t for t in trades if t.get("symbol") == symbol]
        return sorted(trades, key=lambda x: x.get("created_at", ""), reverse=True)[:limit]
    
    def get_trade_stats(self, symbol=None):
        """取得交易統計"""
        trades = self.get_trades(symbol=symbol, limit=1000)
        
        if not trades:
            return {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0,
                "avg_pnl": 0,
                "max_pnl": 0,
                "min_pnl": 0
            }
        
        winning = [t for t in trades if t.get("pnl_pct", 0) > 0]
        losing = [t for t in trades if t.get("pnl_pct", 0) <= 0]
        
        pnls = [t.get("pnl_pct", 0) for t in trades]
        
        return {
            "total_trades": len(trades),
            "winning_trades": len(winning),
            "losing_trades": len(losing),
            "win_rate": len(winning) / len(trades) * 100 if trades else 0,
            "avg_pnl": sum(pnls) / len(pnls) if pnls else 0,
            "max_pnl": max(pnls) if pnls else 0,
            "min_pnl": min(pnls) if pnls else 0
        }
    
    # ============ 訊號紀錄 ============
    
    def log_signal(self, symbol, signal_type, data):
        """記錄訊號"""
        signals = self._read_json(SIGNALS_FILE)
        signal = {
            "symbol": symbol,
            "signal_type": signal_type,
            "data": data,
            "created_at": datetime.now().isoformat()
        }
        signals.append(signal)
        self._write_json(SIGNALS_FILE, signals)
        return signal
    
    def get_signals(self, symbol=None, signal_type=None, limit=100):
        """取得訊號"""
        signals = self._read_json(SIGNALS_FILE)
        if symbol:
            signals = [s for s in signals if s.get("symbol") == symbol]
        if signal_type:
            signals = [s for s in signals if s.get("signal_type") == signal_type]
        return sorted(signals, key=lambda x: x.get("created_at", ""), reverse=True)[:limit]
    
    # ============ 系統日誌 ============
    
    def log(self, level, message, module="general"):
        """記錄日誌"""
        logs = self._read_json(LOGS_FILE)
        log_entry = {
            "level": level,
            "message": message,
            "module": module,
            "timestamp": datetime.now().isoformat()
        }
        logs.append(log_entry)
        
        # 只保留最近 500 筆
        if len(logs) > 500:
            logs = logs[-500:]
        
        self._write_json(LOGS_FILE, logs)
    
    def get_logs(self, level=None, limit=100):
        """取得日誌"""
        logs = self._read_json(LOGS_FILE)
        if level:
            logs = [l for l in logs if l.get("level") == level]
        return sorted(logs, key=lambda x: x.get("timestamp", ""), reverse=True)[:limit]
    
    # ============ 策略配置 ============
    
    def save_strategy_params(self, params):
        """儲存策略參數"""
        config = {
            "params": params,
            "updated_at": datetime.now().isoformat()
        }
        self._write_json(CONFIG_FILE, config)
    
    def get_strategy_params(self):
        """取得策略參數"""
        try:
            config = self._read_json(CONFIG_FILE)
            return config.get("params")
        except:
            return None
    
    # ============ 監控股票管理 ============
    
    def get_monitor_symbols(self):
        """取得監控股票清單"""
        try:
            data = self._read_json(SYMBOLS_FILE)
            return data.get("symbols", ["2330.TW", "8110.TW", "2337.TW"])
        except:
            return ["2330.TW", "8110.TW", "2337.TW"]
    
    def add_monitor_symbol(self, symbol):
        """新增監控股票"""
        symbols = self.get_monitor_symbols()
        symbol = symbol.upper().strip()
        if symbol and symbol not in symbols:
            symbols.append(symbol)
            self._write_json(SYMBOLS_FILE, {"symbols": symbols, "updated_at": datetime.now().isoformat()})
            return True
        return False
    
    def remove_monitor_symbol(self, symbol):
        """移除監控股票"""
        symbols = self.get_monitor_symbols()
        symbol = symbol.upper().strip()
        if symbol in symbols:
            symbols.remove(symbol)
            self._write_json(SYMBOLS_FILE, {"symbols": symbols, "updated_at": datetime.now().isoformat()})
            return True
        return False
    
    def set_monitor_symbols(self, symbols_list):
        """設定監控股票清單"""
        symbols = [s.upper().strip() for s in symbols_list if s.strip()]
        self._write_json(SYMBOLS_FILE, {"symbols": symbols, "updated_at": datetime.now().isoformat()})
        return symbols


# 取得實例
json_manager = JsonManager()
