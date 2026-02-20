"""
Telegram 機器人模組
"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
import asyncio
from datetime import datetime
from json_manager import JsonManager
from config import TradingState
import logging

logger = logging.getLogger(__name__)


class TradingBot:
    """交易機器人類"""
    
    def __init__(self, token, chat_id, db: JsonManager):
        self.token = token
        self.chat_id = chat_id
        self.db = db
        
        self.application = Application.builder().token(token).build()
        self._register_handlers()
    
    def _register_handlers(self):
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("buy", self.buy))
        self.application.add_handler(CommandHandler("sell", self.sell))
        self.application.add_handler(CommandHandler("status", self.status))
        self.application.add_handler(CommandHandler("positions", self.positions))
        self.application.add_handler(CommandHandler("trades", self.trades))
        self.application.add_handler(CommandHandler("ignore", self.ignore))
        self.application.add_handler(CommandHandler("help", self.help))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.unknown))
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🤖 股票交易機器人已啟動！\n\n"
            "可用指令：\n"
            "/buy [股票代碼] - 確認買入（例：/buy 2330.TW）\n"
            "/sell [股票代碼] - 確認賣出（例：/sell 2330.TW）\n"
            "/status - 查看狀態\n"
            "/positions - 查看持倉\n"
            "/trades - 查看交易紀錄\n"
            "/help - 說明"
        )
    
    async def buy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        args = context.args
        
        # 強制要求輸入股票代碼
        if not args:
            await update.message.reply_text(
                "❌ 請輸入股票代碼\n\n"
                "例如：/buy 2330.TW"
            )
            return
        
        symbol = args[0].upper()
        
        position = self.db.get_position(symbol)
        
        if not position:
            await update.message.reply_text(f"❌ 沒有 {symbol} 的買入訊號\n\n請確認股票是否在監控清單中")
            return
        
        if position["status"] == TradingState.HOLDING:
            await update.message.reply_text(f"⚠️ {symbol} 已經在持倉中")
            return
        
        if position["status"] != TradingState.SIGNAL_BUY_SENT:
            await update.message.reply_text(f"⚠️ {symbol} 目前沒有買入訊號")
            return
        
        signal_data = position.get("signal_data", {})
        entry_price = signal_data.get("price")
        entry_time = signal_data.get("time")
        indicators = position.get("indicators", {})
        atr = indicators.get("atr")
        
        stop_loss = entry_price - (atr * 2) if atr else entry_price * 0.95
        
        self.db.add_holding_info(
            symbol=symbol, entry_price=entry_price, entry_time=entry_time,
            stop_loss=round(stop_loss, 2), quantity=0
        )
        
        self.db.add_trade(symbol, "buy", entry_price, 0, 0, 0, "使用者確認買入")
        
        keyboard = [
            [InlineKeyboardButton("📊 查看持倉", callback_data=f"position_{symbol}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"✅ 買入確認成功！\n\n"
            f"📈 股票：{symbol}\n"
            f"💰 買入價格：{entry_price}\n"
            f"⏰ 買入時間：{entry_time}\n"
            f"🛡️ 停損價：{stop_loss:.2f}",
            reply_markup=reply_markup
        )
        
        self.db.log("INFO", f"使用者確認買入 {symbol} @ {entry_price}", "telegram_bot")
    
    async def sell(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        args = context.args
        
        # 強制要求輸入股票代碼
        if not args:
            await update.message.reply_text(
                "❌ 請輸入股票代碼\n\n"
                "例如：/sell 2330.TW"
            )
            return
        
        symbol = args[0].upper()
        
        position = self.db.get_position(symbol)
        
        if not position:
            await update.message.reply_text(f"❌ 沒有 {symbol} 的持倉記錄\n\n請確認股票是否在持倉中")
            return
        
        if position["status"] not in [TradingState.HOLDING, TradingState.SIGNAL_SELL_SENT]:
            await update.message.reply_text(f"⚠️ {symbol} 目前沒有持倉")
            return
        
        holding = position.get("holding_info", {})
        entry_price = holding.get("entry_price")
        entry_time = holding.get("entry_time")
        quantity = holding.get("quantity", 0)
        
        # 取得目前股價
        try:
            import yfinance as yf
            stock = yf.Ticker(symbol)
            current_price = stock.history(period="1d")['Close'].iloc[-1]
        except:
            current_price = entry_price  # 如果取得失敗，使用買入價
        
        pnl_pct = (current_price - entry_price) / entry_price * 100 if entry_price and entry_price > 0 else 0
        pnl_symbol = "+" if pnl_pct >= 0 else ""
        pnl_emoji = "🟢" if pnl_pct >= 0 else "🔴"
        
        exit_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.db.close_position(symbol, current_price, exit_time, pnl_pct, "manual")
        self.db.set_cooldown(symbol, datetime.now().isoformat())
        self.db.add_trade(symbol, "sell", entry_price, current_price, quantity, pnl_pct, "使用者確認賣出")
        self.db.delete_position(symbol)
        
        await update.message.reply_text(
            f"✅ 賣出確認成功！\n\n"
            f"📉 股票：{symbol}\n"
            f"💰 賣出價格：{current_price}\n"
            f"⏰ 買入時間：{entry_time}\n"
            f"⏰ 賣出時間：{exit_time}\n\n"
            f"{pnl_emoji} 損益：{pnl_symbol}{pnl_pct:.2f}%"
        )
        
        self.db.log("INFO", f"使用者確認賣出 {symbol} @ {current_price} (P&L: {pnl_pct:.2f}%)", "telegram_bot")
    
    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        positions = self.db.get_all_positions()
        cooldown = self.db.get_cooldown_symbols()
        
        text = "📊 目前狀態\n\n"
        
        if positions:
            text += "📈 持倉中：\n"
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
                
                text += f"- {p['symbol']}: {status_name}\n"
                if entry_price != "N/A":
                    text += f"  買入價: {entry_price}, 停損: {stop_loss}\n"
        else:
            text += "📭 無持倉\n"
        
        if cooldown:
            text += "\n⏳ 冷卻中：\n"
            for c in cooldown:
                text += f"- {c['symbol']}\n"
        else:
            text += "\n✅ 無冷卻股票"
        
        await update.message.reply_text(text)
    
    async def positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        positions = self.db.get_all_positions()
        
        if not positions:
            await update.message.reply_text("📭 目前沒有持倉")
            return
        
        text = "📈 目前持倉：\n\n"
        for p in positions:
            holding = p.get("holding_info", {})
            text += f"📊 {p['symbol']}\n"
            text += f"  狀態: {p['status']}\n"
            if holding.get("entry_price"):
                text += f"  買入價: {holding['entry_price']}\n"
            if holding.get("stop_loss"):
                text += f"  停損價: {holding['stop_loss']}\n"
            text += "\n"
        
        await update.message.reply_text(text)
    
    async def trades(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        trades = self.db.get_trades(limit=20)
        
        if not trades:
            await update.message.reply_text("📭 尚無交易紀錄")
            return
        
        text = "📜 交易紀錄：\n\n"
        for t in trades:
            pnl_pct = t.get("pnl_pct", 0)
            pnl_emoji = "🟢" if pnl_pct >= 0 else "🔴"
            
            text += f"{pnl_emoji} {t['symbol']} - {t['trade_type'].upper()}\n"
            text += f"  買入: {t.get('entry_price', 'N/A')}"
            if t.get('exit_price'):
                text += f" → 賣出: {t['exit_price']}\n"
            else:
                text += "\n"
            text += f"  損益: {pnl_pct:+.2f}%\n\n"
        
        await update.message.reply_text(text)
    
    async def ignore(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """忽略買入/賣出訊號開關"""
        args = context.args
        
        if args and args[0].lower() in ["on", "yes", "true", "1"]:
            # 開啟忽略
            self.db.set_ignore_signals(True)
            await update.message.reply_text(
                "🔇 **忽略模式已開啟**\n\n"
                "機器人將不會發送買入/賣出訊號通知。\n"
                "使用 /ignore off 可恢復通知。"
            )
        elif args and args[0].lower() in ["off", "no", "false", "0"]:
            # 關閉忽略
            self.db.set_ignore_signals(False)
            await update.message.reply_text(
                "🔔 **忽略模式已關閉**\n\n"
                "機器人將會正常發送買入/賣出訊號通知。"
            )
        else:
            # 顯示目前狀態
            is_ignoring = self.db.get_ignore_signals()
            status = "🔇 **忽略模式：開啟**" if is_ignoring else "🔔 **忽略模式：關閉**"
            await update.message.reply_text(
                f"{status}\n\n"
                "使用指令：\n"
                "/ignore on - 忽略買入/賣出訊號\n"
                "/ignore off - 恢復通知"
            )
    
    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        help_text = """
🤖 股票交易機器人說明

📌 指令列表：
/buy [股票代碼] - 確認買入（例：/buy 2330.TW）
/sell [股票代碼] - 確認賣出（例：/sell 2330.TW）
/status - 查看目前狀態
/positions - 查看持倉
/trades - 查看交易紀錄
/ignore [on/off] - 忽略訊號開關
/help - 說明

📋 買賣流程：
1. 機器人偵測到買入訊號 → 發送通知
2. 您輸入 /buy <股票代碼> → 機器人記錄買入資訊
3. 機器人持續監控
4. 機器人偵測到賣出訊號 → 發送通知
5. 您輸入 /sell <股票代碼> → 機器人計算損益並結清

⚠️ 注意：監控多檔股票時，買入/賣出必須指定股票代碼
        """
        await update.message.reply_text(help_text)
    
    async def unknown(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("❓ 未知指令，請輸入 /help 查看說明")
    
    async def send_buy_signal(self, symbol, price, indicators):
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
        
        await self.application.bot.send_message(chat_id=self.chat_id, text=message)
    
    async def send_sell_signal(self, symbol, price, reason, pnl_pct=None):
        pnl_text = f"\n📊 目前損益：{pnl_pct:+.2f}%" if pnl_pct is not None else ""
        
        message = (
            f"🔴 【賣出訊號】{symbol}\n\n"
            f"💰 價格：{price}\n"
            f"📋 原因：{reason}{pnl_text}\n\n"
            f"請回覆 /sell {symbol} 確認賣出"
        )
        
        await self.application.bot.send_message(chat_id=self.chat_id, text=message)
    
    async def send_force_sell_notification(self, symbol, price, reason):
        message = (
            f"🚨 【強制賣出通知】{symbol}\n\n"
            f"💰 價格：{price}\n"
            f"📋 原因：{reason}\n\n"
            f"已自動發送賣出訊號，請回覆 /sell {symbol} 確認"
        )
        
        await self.application.bot.send_message(chat_id=self.chat_id, text=message)
    
    def run(self):
        try:
            self.application.run_polling()
        except Exception as e:
            if "Conflict" in str(e) or "terminated by other" in str(e):
                logger.warning("⚠️ Telegram Bot 被另一個實例终止 (部署重啟中)")
            else:
                logger.error(f"Telegram Bot 錯誤: {e}")
    
    async def run_async(self):
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()
        
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            await self.application.updater.stop()
            await self.application.stop()
