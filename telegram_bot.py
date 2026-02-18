"""
Telegram 機器人模組
"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
import asyncio
from datetime import datetime
from mongo_manager import MongoManager
from config import TRADING_CONFIG, TradingState
import logging

logger = logging.getLogger(__name__)


class TradingBot:
    """交易機器人類"""
    
    def __init__(self, token, chat_id, mongo_manager: MongoManager):
        """
        初始化
        Args:
            token: Telegram Bot Token
            chat_id: 接收通知的 Chat ID
            mongo_manager: MongoDB 管理實例
        """
        self.token = token
        self.chat_id = chat_id
        self.mongo = mongo_manager
        
        # 創建 Application
        self.application = Application.builder().token(token).build()
        
        # 註冊處理器
        self._register_handlers()
    
    def _register_handlers(self):
        """註冊命令處理器"""
        # /start
        self.application.add_handler(CommandHandler("start", self.start))
        
        # /buy
        self.application.add_handler(CommandHandler("buy", self.buy))
        
        # /sell
        self.application.add_handler(CommandHandler("sell", self.sell))
        
        # /status
        self.application.add_handler(CommandHandler("status", self.status))
        
        # /positions
        self.application.add_handler(CommandHandler("positions", self.positions))
        
        # /trades
        self.application.add_handler(CommandHandler("trades", self.trades))
        
        # /help
        self.application.add_handler(CommandHandler("help", self.help))
        
        # 未預期的訊息
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.unknown))
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/start 命令"""
        await update.message.reply_text(
            "🤖 股票交易機器人已啟動！\n\n"
            "可用指令：\n"
            "/buy - 確認買入訊號\n"
            "/sell - 確認賣出訊號\n"
            "/status - 查看目前狀態\n"
            "/positions - 查看持倉\n"
            "/trades - 查看交易紀錄\n"
            "/help - 說明"
        )
    
    async def buy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /buy 命令 - 確認買入
        處理邏輯：
        1. 檢查是否有待確認的買入訊號
        2. 檢查是否已持倉（防呆）
        3. 記錄買入資訊
        4. 發送確認通知
        """
        user_id = update.message.from_user.id
        args = context.args
        
        # 取得訊息中的股票代碼（如果有的話）
        if args:
            symbol = args[0].upper()
        else:
            # 找尋有待確認買入的股票
            positions = self.mongo.get_all_positions(status=TradingState.SIGNAL_BUY_SENT)
            if len(positions) == 0:
                await update.message.reply_text("❌ 目前沒有待確認的買入訊號")
                return
            elif len(positions) == 1:
                symbol = positions[0]["symbol"]
            else:
                # 多個訊號時，提示使用者選擇
                symbols = [p["symbol"] for p in positions]
                await update.message.reply_text(
                    f"📋 待確認買入的股票：\n" +
                    "\n".join([f"- {s}" for s in symbols]) +
                    "\n\n請輸入：/buy <股票代碼>"
                )
                return
        
        # 取得持倉記錄
        position = self.mongo.get_position(symbol)
        
        if not position:
            await update.message.reply_text(f"❌ 沒有 {symbol} 的買入訊號")
            return
        
        # 防呆：檢查是否已持倉
        if position["status"] == TradingState.HOLDING:
            await update.message.reply_text(
                f"⚠️ {symbol} 已經在持倉中，請勿重複買入"
            )
            return
        
        # 取得買入價格和時間
        signal_data = position.get("signal_data", {})
        entry_price = signal_data.get("price")
        entry_time = signal_data.get("time")
        indicators = position.get("indicators", {})
        atr = indicators.get("atr")
        
        # 計算停損價
        stop_loss = entry_price - (atr * 2) if atr else entry_price * 0.95
        
        # 更新持倉狀態
        self.mongo.add_holding_info(
            symbol=symbol,
            entry_price=entry_price,
            entry_time=entry_time,
            stop_loss=round(stop_loss, 2),
            quantity=0  # 數量由使用者自行記錄
        )
        
        # 記錄交易
        self.mongo.add_trade(
            symbol=symbol,
            trade_type="buy",
            entry_price=entry_price,
            exit_price=0,
            quantity=0,
            pnl_pct=0,
            reason="使用者確認買入"
        )
        
        # 發送確認訊息
        keyboard = [
            [
                InlineKeyboardButton("📊 查看持倉", callback_data=f"position_{symbol}"),
                InlineKeyboardButton("📈 查看圖表", callback_data=f"chart_{symbol}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"✅ 買入確認成功！\n\n"
            f"📈 股票：{symbol}\n"
            f"💰 買入價格：{entry_price}\n"
            f"⏰ 買入時間：{entry_time}\n"
            f"🛡️ 停損價：{stop_loss:.2f}\n\n"
            f"機器人將持續監控，適時發出賣出訊號",
            reply_markup=reply_markup
        )
        
        # 記錄日誌
        self.mongo.log("INFO", f"使用者確認買入 {symbol} @ {entry_price}", "telegram_bot")
    
    async def sell(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /sell 命令 - 確認賣出
        處理邏輯：
        1. 檢查是否有持倉
        2. 檢查是否已無持倉（防呆）
        3. 計算損益
        4. 刪除持倉記錄
        """
        user_id = update.message.from_user.id
        args = context.args
        
        # 取得訊息中的股票代碼
        if args:
            symbol = args[0].upper()
        else:
            # 找尋持倉中的股票
            positions = self.mongo.get_all_positions(status=TradingState.HOLDING)
            if len(positions) == 0:
                await update.message.reply_text("❌ 目前沒有持倉中的股票")
                return
            elif len(positions) == 1:
                symbol = positions[0]["symbol"]
            else:
                symbols = [p["symbol"] for p in positions]
                await update.message.reply_text(
                    f"📋 持倉中的股票：\n" +
                    "\n".join([f"- {s}" for s in symbols]) +
                    "\n\n請輸入：/sell <股票代碼>"
                )
                return
        
        # 取得持倉記錄
        position = self.mongo.get_position(symbol)
        
        if not position:
            await update.message.reply_text(f"❌ 沒有 {symbol} 的持倉記錄")
            return
        
        # 防呆：檢查是否已無持倉
        if position["status"] not in [TradingState.HOLDING, TradingState.SIGNAL_SELL_SENT]:
            await update.message.reply_text(
                f"⚠️ {symbol} 目前沒有持倉，請確認狀態"
            )
            return
        
        # 取得持倉資訊
        holding = position.get("holding_info", {})
        entry_price = holding.get("entry_price")
        entry_time = holding.get("entry_time")
        quantity = holding.get("quantity", 0)
        
        # 取得目前價格（從持倉記錄中取得賣出價格）
        args = context.args
        current_price = float(args[1]) if len(args) > 1 else float(args[0]) if args else entry_price
        
        # 計算損益
        if entry_price and entry_price > 0:
            pnl_pct = (current_price - entry_price) / entry_price * 100
            pnl_symbol = "+" if pnl_pct >= 0 else ""
        else:
            pnl_pct = 0
        
        # 更新持倉狀態
        exit_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.mongo.close_position(
            symbol=symbol,
            exit_price=current_price,
            exit_time=exit_time,
            pnl_pct=pnl_pct,
            trade_type="manual"
        )
        
        # 設定冷卻時間（隔日才能再買）
        cooldown_until = datetime.now()
        self.mongo.set_cooldown(symbol, cooldown_until)
        
        # 記錄交易
        self.mongo.add_trade(
            symbol=symbol,
            trade_type="sell",
            entry_price=entry_price,
            exit_price=current_price,
            quantity=quantity,
            pnl_pct=pnl_pct,
            reason="使用者確認賣出"
        )
        
        # 刪除持倉記錄（移到歷史）
        self.mongo.delete_position(symbol)
        
        # 發送確認訊息
        pnl_emoji = "🟢" if pnl_pct >= 0 else "🔴"
        
        await update.message.reply_text(
            f"✅ 賣出確認成功！\n\n"
            f"📉 股票：{symbol}\n"
            f"💰 賣出價格：{current_price}\n"
            f"⏰ 買入時間：{entry_time}\n"
            f"⏰ 賣出時間：{exit_time}\n\n"
            f"{pnl_emoji} 損益：{pnl_symbol}{pnl_pct:.2f}%\n\n"
            f"📊 持倉已結清，冷卻中..."
        )
        
        # 記錄日誌
        self.mongo.log("INFO", f"使用者確認賣出 {symbol} @ {current_price} (P&L: {pnl_pct:.2f}%)", "telegram_bot")
    
    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/status 命令 - 查看目前狀態"""
        positions = self.mongo.get_all_positions()
        cooldown = self.mongo.get_cooldown_symbols()
        
        status_text = "📊 目前狀態\n\n"
        
        # 持倉
        if positions:
            status_text += "📈 持倉中：\n"
            for p in positions:
                holding = p.get("holding_info", {})
                status = p["status"]
                status_name = {
                    TradingState.SIGNAL_BUY_SENT: "待買入確認",
                    TradingState.HOLDING: "持有中",
                    TradingState.SIGNAL_SELL_SENT: "待賣出確認"
                }.get(status, status)
                
                entry_price = holding.get("entry_price", "N/A")
                stop_loss = holding.get("stop_loss", "N/A")
                
                status_text += f"- {p['symbol']}: {status_name}\n"
                if entry_price != "N/A":
                    status_text += f"  買入價: {entry_price}, 停損: {stop_loss}\n"
        else:
            status_text += "📭 無持倉\n"
        
        # 冷卻
        if cooldown:
            status_text += "\n⏳ 冷卻中：\n"
            for c in cooldown:
                status_text += f"- {c['symbol']}\n"
        else:
            status_text += "\n✅ 無冷卻股票"
        
        await update.message.reply_text(status_text)
    
    async def positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/positions 命令 - 查看持倉"""
        positions = self.mongo.get_all_positions()
        
        if not positions:
            await update.message.reply_text("📭 目前沒有持倉")
            return
        
        text = "📈 目前持倉：\n\n"
        for p in positions:
            holding = p.get("holding_info", {})
            entry_price = holding.get("entry_price", 0)
            stop_loss = holding.get("stop_loss", 0)
            quantity = holding.get("quantity", 0)
            
            text += f"📊 {p['symbol']}\n"
            text += f"  狀態: {p['status']}\n"
            if entry_price:
                text += f"  買入價: {entry_price}\n"
            if stop_loss:
                text += f"  停損價: {stop_loss}\n"
            if quantity:
                text += f"  數量: {quantity}\n"
            text += "\n"
        
        await update.message.reply_text(text)
    
    async def trades(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/trades 命令 - 查看交易紀錄"""
        trades = self.mongo.get_trades(limit=20)
        
        if not trades:
            await update.message.reply_text("📭 尚無交易紀錄")
            return
        
        text = "📜 交易紀錄：\n\n"
        for t in trades:
            pnl_pct = t.get("pnl_pct", 0)
            pnl_symbol = "+" if pnl_pct >= 0 else ""
            pnl_emoji = "🟢" if pnl_pct >= 0 else "🔴"
            
            text += f"{pnl_emoji} {t['symbol']} - {t['trade_type'].upper()}\n"
            text += f"  買入: {t.get('entry_price', 'N/A')}"
            if t.get('exit_price'):
                text += f" → 賣出: {t['exit_price']}\n"
            else:
                text += "\n"
            text += f"  損益: {pnl_symbol}{pnl_pct:.2f}%\n"
            text += f"  時間: {t.get('created_at', 'N/A').strftime('%Y-%m-%d %H:%M')}\n\n"
        
        await update.message.reply_text(text)
    
    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/help 命令 - 說明"""
        help_text = """
🤖 股票交易機器人說明

📌 指令列表：
/buy [股票代碼] - 確認買入訊號
/sell [股票代碼] - 確認賣出訊號
/status - 查看目前狀態
/positions - 查看持倉
/trades - 查看交易紀錄
/help - 說明

📋 買賣流程：
1. 機器人偵測到買入訊號 → 發送通知
2. 您回覆 /buy → 機器人記錄買入資訊
3. 機器人持續監控
4. 機器人偵測到賣出訊號 → 發送通知
5. 您回覆 /sell → 機器人計算損益並結清

⚠️ 注意事項：
- 請確認您在交易時間內操作
- 機器人會自動發送訊號，但最終決策由您確認
- 請務必設定止損止盈
        """
        await update.message.reply_text(help_text)
    
    async def unknown(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """未知指令處理"""
        await update.message.reply_text(
            "❓ 未知指令，請輸入 /help 查看說明"
        )
    
    # ============ 發送訊息方法 ============
    
    async def send_buy_signal(self, symbol, price, indicators):
        """
        發送買入訊號通知
        """
        atr = indicators.get("atr", 0)
        rsi = indicators.get("rsi", 0)
        adx = indicators.get("adx", 0)
        stop_loss = price - (atr * 2) if atr else price * 0.95
        
        message = (
            f"🟢 【買入訊號】{symbol}\n\n"
            f"💰 價格：{price}\n"
            f"🛡️ 停損：{stop_loss:.2f}\n"
            f"📊 ATR：{atr:.2f}\n"
            f"📉 RSI：{rsi:.2f}\n"
            f"📈 ADX：{adx:.2f}\n\n"
            f"請回覆 /buy {symbol} 確認買入"
        )
        
        await self.application.bot.send_message(
            chat_id=self.chat_id,
            text=message
        )
    
    async def send_sell_signal(self, symbol, price, reason, pnl_pct=None):
        """
        發送賣出訊號通知
        """
        pnl_text = f"\n📊 目前損益：{pnl_pct:+.2f}%" if pnl_pct is not None else ""
        
        message = (
            f"🔴 【賣出訊號】{symbol}\n\n"
            f"💰 價格：{price}\n"
            f"📋 原因：{reason}{pnl_text}\n\n"
            f"請回覆 /sell {symbol} 確認賣出"
        )
        
        await self.application.bot.send_message(
            chat_id=self.chat_id,
            text=message
        )
    
    async def send_force_sell_notification(self, symbol, price, reason):
        """
        發送強制賣出通知（ATR 停損觸發）
        """
        message = (
            f"🚨 【強制賣出通知】{symbol}\n\n"
            f"💰 價格：{price}\n"
            f"📋 原因：{reason}\n\n"
            f"已自動發送賣出訊號，請回覆 /sell {symbol} 確認"
        )
        
        await self.application.bot.send_message(
            chat_id=self.chat_id,
            text=message
        )
    
    async def send_error(self, error_message):
        """
        發送錯誤通知
        """
        await self.application.bot.send_message(
            chat_id=self.chat_id,
            text=f"❌ 錯誤：{error_message}"
        )
    
    def run(self):
        """啟動機器人"""
        self.application.run_polling()
    
    async def run_async(self):
        """非同步啟動"""
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()
        
        # 保持運行
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            await self.application.updater.stop()
            await self.application.stop()
