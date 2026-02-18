"""
Web Dashboard - Flask 伺服器
"""
from flask import Flask, render_template, request, jsonify, redirect, url_for
import json
from datetime import datetime
import sys
import os

# 加入父目錄到路徑
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mongo_manager import MongoManager
from config import STRATEGY_PARAMS, TRADING_CONFIG

app = Flask(__name__)

# 初始化 MongoDB
mongo = MongoManager()


# ============ 即時監控頁 ============

@app.route('/')
@app.route('/monitor')
def monitor():
    """即時監控頁"""
    positions = mongo.get_all_positions()
    cooldown = mongo.get_cooldown_symbols()
    
    # 取得交易統計
    stats = mongo.get_trade_stats()
    
    return render_template(
        'monitor.html',
        positions=positions,
        cooldown=cooldown,
        stats=stats,
        trading_hours=TRADING_CONFIG["trading_hours"],
        symbols=TRADING_CONFIG["symbols"]
    )


@app.route('/api/positions')
def api_positions():
    """API: 取得持倉"""
    positions = mongo.get_all_positions()
    return jsonify(positions)


@app.route('/api/trades')
def api_trades():
    """API: 取得交易"""
    symbol = request.args.get('symbol')
    limit = int(request.args.get('limit', 20))
    trades = mongo.get_trades(symbol=symbol, limit=limit)
    return jsonify(trades)


@app.route('/api/stats')
def api_stats():
    """API: 取得統計"""
    symbol = request.args.get('symbol')
    stats = mongo.get_trade_stats(symbol=symbol)
    return jsonify(stats)


@app.route('/api/logs')
def api_logs():
    """API: 取得日誌"""
    level = request.args.get('level')
    limit = int(request.args.get('limit', 50))
    logs = mongo.get_logs(level=level, limit=limit)
    return jsonify(logs)


# ============ 策略配置頁 ============

@app.route('/config', methods=['GET', 'POST'])
def config():
    """策略配置頁"""
    if request.method == 'POST':
        # 儲存新參數
        params = {
            "macd": {
                "fast": int(request.form.get('macd_fast', 12)),
                "slow": int(request.form.get('macd_slow', 26)),
                "signal": int(request.form.get('macd_signal', 9))
            },
            "rsi": {
                "period": int(request.form.get('rsi_period', 14)),
                "oversold": int(request.form.get('rsi_oversold', 30)),
                "overbought": int(request.form.get('rsi_overbought', 70))
            },
            "adx": {
                "period": int(request.form.get('adx_period', 14)),
                "threshold": int(request.form.get('adx_threshold', 20))
            },
            "atr": {
                "period": int(request.form.get('atr_period', 14))
            },
            "confirm_bars": int(request.form.get('confirm_bars', 3)),
            "stop_loss_multiplier": float(request.form.get('stop_loss_multiplier', 2.0)),
            "new_high_period": int(request.form.get('new_high_period', 252))
        }
        
        mongo.save_strategy_params(params)
        
        return render_template('config.html', params=params, success=True)
    
    # GET: 取得目前參數
    current_params = mongo.get_strategy_params()
    if current_params is None:
        current_params = STRATEGY_PARAMS
    
    return render_template('config.html', params=current_params)


@app.route('/api/symbols', methods=['GET', 'POST'])
def manage_symbols():
    """管理監控股票清單"""
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add':
            symbol = request.form.get('symbol', '').upper().strip()
            if symbol and symbol not in TRADING_CONFIG["symbols"]:
                TRADING_CONFIG["symbols"].append(symbol)
        
        elif action == 'remove':
            symbol = request.form.get('symbol', '').upper().strip()
            if symbol in TRADING_CONFIG["symbols"]:
                TRADING_CONFIG["symbols"].remove(symbol)
        
        return redirect(url_for('config'))
    
    return jsonify({"symbols": TRADING_CONFIG["symbols"]})


# ============ 回測頁 ============

@app.route('/backtest', methods=['GET', 'POST'])
def backtest():
    """回測頁"""
    if request.method == 'POST':
        symbol = request.form.get('symbol', '').upper().strip()
        period = request.form.get('period', '6mo')
        interval = request.form.get('interval', '1d')
        
        # 重新導向到結果頁
        return redirect(url_for('backtest_result', symbol=symbol, period=period, interval=interval))
    
    return render_template('backtest.html', symbols=TRADING_CONFIG["symbols"])


@app.route('/backtest/result')
def backtest_result():
    """回測結果"""
    symbol = request.args.get('symbol')
    period = request.args.get('period', '6mo')
    interval = request.args.get('interval', '1d')
    
    if not symbol:
        return redirect(url_for('backtest'))
    
    # 執行回測
    result = run_backtest(symbol, period, interval)
    
    return render_template(
        'backtest_result.html',
        symbol=symbol,
        period=period,
        interval=interval,
        result=result
    )


def run_backtest(symbol, period, interval):
    """執行回測"""
    import yfinance as yf
    from ta.momentum import RSIIndicator
    from ta.trend import MACD, ADXIndicator
    from ta.volatility import AverageTrueRange
    import numpy as np
    
    # 取得參數
    params = mongo.get_strategy_params()
    if params is None:
        params = STRATEGY_PARAMS
    
    # 取得股票資料
    df = yf.Ticker(symbol).history(period=period, interval=interval)
    
    if df is None or len(df) < 50:
        return {"error": "無法取得足夠資料"}
    
    # 計算指標
    macd = MACD(df['Close'], window_slow=params["macd"]["slow"], 
                 window_fast=params["macd"]["fast"], window_sign=params["macd"]["signal"])
    df['MACD'] = macd.macd()
    df['MACD_Signal'] = macd.macd_signal()
    
    df['RSI'] = RSIIndicator(df['Close'], window=params["rsi"]["period"]).rsi()
    
    adx = ADXIndicator(df['High'], df['Low'], df['Close'], window=params["adx"]["period"])
    df['ADX'] = adx.adx()
    
    atr = AverageTrueRange(df['High'], df['Low'], df['Close'], window=params["atr"]["period"])
    df['ATR'] = atr.average_true_range()
    
    # 偵測黃金交叉
    df['GC'] = (df['MACD'] > df['MACD_Signal']) & (df['MACD'].shift(1) <= df['MACD_Signal'].shift(1))
    df['DC'] = (df['MACD'] < df['MACD_Signal']) & (df['MACD'].shift(1) >= df['MACD_Signal'].shift(1))
    
    # 黃金交叉確認
    df['GC_Confirm'] = df['GC'].rolling(window=3).apply(
        lambda x: all(x[i+1] and df['MACD'].iloc[-1] > df['MACD_Signal'].iloc[-1] for i in range(len(x)-1)) if len(x) >= 2 else False,
        raw=False
    )
    
    # 回測
    capital = 100000
    shares = 0
    position = 0
    trades = []
    
    for i in range(30, len(df)):
        # 買入條件
        if df.iloc[i]['GC_Confirm'] and position == 0:
            shares = capital // df.iloc[i]['Close']
            entry_price = df.iloc[i]['Close']
            entry_date = df.index[i]
            position = 1
            
        # 賣出條件
        elif df.iloc[i]['DC'] and position == 1:
            exit_price = df.iloc[i]['Close']
            pnl = (exit_price - entry_price) / entry_price * 100
            
            trades.append({
                "date": str(entry_date.date()) + " ~ " + str(df.index[i].date()),
                "entry": entry_price,
                "exit": exit_price,
                "pnl": pnl,
                "win": pnl > 0
            })
            
            capital = shares * exit_price
            position = 0
            shares = 0
    
    # 計算統計
    wins = len([t for t in trades if t["win"]])
    total = len(trades)
    win_rate = wins / total * 100 if total > 0 else 0
    
    return {
        "symbol": symbol,
        "period": period,
        "total_trades": total,
        "wins": wins,
        "losses": total - wins,
        "win_rate": win_rate,
        "total_return": (capital - 100000) / 100000 * 100,
        "trades": trades[-20:]  # 最近20筆
    }


# ============ 錯誤處理 ============

@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', error="404 - 頁面不存在"), 404


@app.errorhandler(500)
def server_error(e):
    return render_template('error.html', error="500 - 伺服器錯誤"), 500


# ============ 啟動 ============

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
