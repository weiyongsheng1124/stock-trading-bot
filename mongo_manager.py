"""
MongoDB 資料庫管理模組
"""
from pymongo import MongoClient
from datetime import datetime, timedelta
from bson import ObjectId
import config


class MongoManager:
    """MongoDB 管理類"""
    
    def __init__(self, uri=None, db_name=None):
        """
        初始化 MongoDB 連線
        Args:
            uri: MongoDB URI
            db_name: 資料庫名稱
        """
        self.uri = uri or config.MONGODB_URI
        self.db_name = db_name or config.MONGODB_DB
        
        self.client = MongoClient(self.uri)
        self.db = self.client[self.db_name]
        
        # 建立索引
        self._ensure_indexes()
    
    def _ensure_indexes(self):
        """建立必要的索引"""
        # 持倉記錄索引
        self.db.positions.create_index([("symbol", 1), ("status", 1)])
        self.db.positions.create_index("updated_at")
        
        # 交易紀錄索引
        self.db.trades.create_index("created_at")
        self.db.trades.create_index([("symbol", 1), ("created_at", -1)])
        
        # 訊號紀錄索引
        self.db.signals.create_index("created_at")
        self.db.signals.create_index([("symbol", 1), ("signal_type", 1)])
        
        # 系統日誌索引
        self.db.logs.create_index("timestamp")
        self.db.logs.create_index([("level", 1), ("timestamp", -1)])
    
    # ============ 持倉管理 ============
    
    def get_position(self, symbol):
        """
        取得特定股票的持倉
        Args:
            symbol: 股票代碼
        Returns:
            dict or None
        """
        return self.db.positions.find_one({
            "symbol": symbol,
            "status": {"$in": [config.TradingState.SIGNAL_BUY_SENT, config.TradingState.HOLDING]}
        })
    
    def get_all_positions(self, status=None):
        """
        取得所有持倉
        Args:
            status: 特定狀態，如果不指定則返回所有非結案持倉
        Returns:
            list of dict
        """
        query = {}
        if status:
            query["status"] = status
        else:
            query["status"] = {"$in": [
                config.TradingState.SIGNAL_BUY_SENT,
                config.TradingState.HOLDING,
                config.TradingState.SIGNAL_SELL_SENT
            ]}
        
        return list(self.db.positions.find(query).sort("updated_at", -1))
    
    def create_position(self, symbol, signal_data, indicators):
        """
        建立新持倉記錄
        Args:
            symbol: 股票代碼
            signal_data: 訊號資料
            indicators: 技術指標資料
        Returns:
            position_id
        """
        position = {
            "symbol": symbol,
            "status": config.TradingState.SIGNAL_BUY_SENT,
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
            "created_at": datetime.now(),
            "updated_at": datetime.now()
        }
        
        result = self.db.positions.insert_one(position)
        return str(result.inserted_id)
    
    def update_position_status(self, symbol, status, additional_data=None):
        """
        更新持倉狀態
        Args:
            symbol: 股票代碼
            status: 新狀態
            additional_data: 額外資料
        """
        update = {
            "$set": {
                "status": status,
                "updated_at": datetime.now()
            }
        }
        
        if additional_data:
            update["$set"].update(additional_data)
        
        self.db.positions.update_one(
            {"symbol": symbol, "status": {"$ne": "CLOSED"}},
            update
        )
    
    def add_holding_info(self, symbol, entry_price, entry_time, stop_loss, quantity=0):
        """
        新增持倉資訊（使用者確認買入後）
        """
        self.db.positions.update_one(
            {"symbol": symbol, "status": config.TradingState.SIGNAL_BUY_SENT},
            {
                "$set": {
                    "status": config.TradingState.HOLDING,
                    "holding_info": {
                        "entry_price": entry_price,
                        "entry_time": entry_time,
                        "stop_loss": stop_loss,
                        "quantity": quantity,
                        "atr": None  # 進場時的 ATR
                    },
                    "updated_at": datetime.now()
                }
            }
        )
    
    def close_position(self, symbol, exit_price, exit_time, pnl_pct, trade_type="manual"):
        """
        關閉持倉
        """
        self.db.positions.update_one(
            {"symbol": symbol},
            {
                "$set": {
                    "status": config.TradingState.COOLDOWN,
                    "close_info": {
                        "exit_price": exit_price,
                        "exit_time": exit_time,
                        "pnl_pct": pnl_pct,
                        "trade_type": trade_type  # "manual" or "stop_loss"
                    },
                    "updated_at": datetime.now(),
                    "closed_at": datetime.now()
                }
            }
        )
    
    def delete_position(self, symbol):
        """
        刪除持倉記錄
        """
        self.db.positions.delete_one({"symbol": symbol})
    
    def set_cooldown(self, symbol, cooldown_until):
        """
        設定冷卻時間
        """
        self.db.positions.update_one(
            {"symbol": symbol},
            {
                "$set": {
                    "status": config.TradingState.COOLDOWN,
                    "cooldown_until": cooldown_until,
                    "updated_at": datetime.now()
                }
            }
        )
    
    def get_cooldown_symbols(self):
        """
        取得仍在冷卻中的股票
        """
        now = datetime.now()
        return list(self.db.positions.find({
            "status": config.TradingState.COOLDOWN,
            "cooldown_until": {"$gt": now}
        }))
    
    def clear_expired_cooldowns(self):
        """
        清除已過期的冷卻
        """
        now = datetime.now()
        expired = list(self.db.positions.find({
            "status": config.TradingState.COOLDOWN,
            "cooldown_until": {"$lte": now}
        }))
        
        for pos in expired:
            # 移動到歷史
            self.db.position_history.insert_one(pos)
            self.db.positions.delete_one({"_id": pos["_id"]})
        
        return len(expired)
    
    # ============ 交易紀錄 ============
    
    def add_trade(self, symbol, trade_type, entry_price, exit_price, quantity, pnl_pct, reason=""):
        """
        新增交易紀錄
        """
        trade = {
            "symbol": symbol,
            "trade_type": trade_type,  # "buy" or "sell"
            "entry_price": entry_price,
            "exit_price": exit_price,
            "quantity": quantity,
            "pnl_pct": pnl_pct,
            "reason": reason,
            "created_at": datetime.now()
        }
        
        self.db.trades.insert_one(trade)
        return trade
    
    def get_trades(self, symbol=None, limit=50):
        """
        取得交易紀錄
        """
        query = {}
        if symbol:
            query["symbol"] = symbol
        
        return list(self.db.trades.find(query).sort("created_at", -1).limit(limit))
    
    def get_trade_stats(self, symbol=None):
        """
        取得交易統計
        """
        pipeline = [
            {"$match": query if symbol else {}},
            {
                "$group": {
                    "_id": None,
                    "total_trades": {"$sum": 1},
                    "winning_trades": {"$sum": {"$cond": [{"$gt": ["$pnl_pct", 0]}, 1, 0]}},
                    "losing_trades": {"$sum": {"$cond": [{"$lt": ["$pnl_pct", 0]}, 1, 0]}},
                    "avg_pnl": {"$avg": "$pnl_pct"},
                    "max_pnl": {"$max": "$pnl_pct"},
                    "min_pnl": {"$min": "$pnl_pct"}
                }
            }
        ]
        
        if symbol:
            pipeline[0]["$match"] = {"symbol": symbol}
        
        result = list(self.db.trades.aggregate(pipeline))
        
        if result:
            stats = result[0]
            stats["win_rate"] = stats["winning_trades"] / stats["total_trades"] * 100 if stats["total_trades"] > 0 else 0
            return stats
        
        return {
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": 0,
            "avg_pnl": 0,
            "max_pnl": 0,
            "min_pnl": 0
        }
    
    # ============ 訊號紀錄 ============
    
    def log_signal(self, symbol, signal_type, data):
        """
        記錄訊號
        """
        signal = {
            "symbol": symbol,
            "signal_type": signal_type,  # "buy" or "sell"
            "data": data,
            "created_at": datetime.now()
        }
        
        self.db.signals.insert_one(signal)
        return signal
    
    def get_signals(self, symbol=None, signal_type=None, limit=100):
        """
        取得訊號紀錄
        """
        query = {}
        if symbol:
            query["symbol"] = symbol
        if signal_type:
            query["signal_type"] = signal_type
        
        return list(self.db.signals.find(query).sort("created_at", -1).limit(limit))
    
    # ============ 系統日誌 ============
    
    def log(self, level, message, module="general"):
        """
        記錄系統日誌
        """
        log_entry = {
            "level": level,  # "INFO", "WARNING", "ERROR"
            "message": message,
            "module": module,
            "timestamp": datetime.now()
        }
        
        self.db.logs.insert_one(log_entry)
    
    def get_logs(self, level=None, limit=100):
        """
        取得系統日誌
        """
        query = {}
        if level:
            query["level"] = level
        
        return list(self.db.logs.find(query).sort("timestamp", -1).limit(limit))
    
    # ============ 策略配置 ============
    
    def save_strategy_params(self, params):
        """
        儲存策略參數
        """
        self.db.strategy_config.update_one(
            {"_id": "current"},
            {
                "$set": {
                    "params": params,
                    "updated_at": datetime.now()
                }
            },
            upsert=True
        )
    
    def get_strategy_params(self):
        """
        取得策略參數
        """
        config = self.db.strategy_config.find_one({"_id": "current"})
        return config.get("params") if config else None
    
    # ============ 工具方法 ============
    
    def close(self):
        """關閉連線"""
        if self.client:
            self.client.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# 取得 MongoDB 實例
def get_mongo_manager():
    return MongoManager()
