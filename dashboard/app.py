"""
Web Dashboard - Flask 伺服器
"""
from flask import Flask, render_template, request, jsonify, redirect, url_for
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from json_manager import JsonManager
from config import STRATEGY_PARAMS, TRADING_CONFIG

app = Flask(__name__)

# 初始化 JSON 管理器
db = JsonManager()


# ============ 即時監控頁 ============

@app.route('/')
@app.route('/monitor')
def monitor():
    positions = db.get_all_positions()
    cooldown = db.get_cooldown_symbols()
    stats = db.get_trade_stats()
    
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
    return jsonify(db.get_all_positions())


@app.route('/api/trades')
def api_trades():
    symbol = request.args.get('symbol')
    limit = int(request.args.get('limit', 20))
    return jsonify(db.get_trades(symbol=symbol, limit=limit))


@app.route('/api/stats')
def api_stats():
    symbol = request.args.get('symbol')
    return jsonify(db.get_trade_stats(symbol=symbol))


@app.route('/api/logs')
def api_logs():
    level = request.args.get('level')
    limit = int(request.args.get('limit', 50))
    return jsonify(db.get_logs(level=level, limit=limit))


# ============ 策略配置頁 ============

@app.route('/config', methods=['GET', 'POST'])
def config():
    if request.method == 'POST':
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
        
        db.save_strategy_params(params)
        return render_template('config.html', params=params, success=True)
    
    current_params = db.get_strategy_params()
    if current_params is None:
        current_params = STRATEGY_PARAMS
    
    return render_template('config.html', params=current_params)


# ============ 回測頁 ============

@app.route('/backtest', methods=['GET', 'POST'])
def backtest():
    if request.method == 'POST':
        symbol = request.form.get('symbol', '').upper().strip()
        period = request.form.get('period', '6mo')
        interval = request.form.get('interval', '1d')
        return redirect(url_for('backtest_result', symbol=symbol, period=period, interval=interval))
    
    return render_template('backtest.html', symbols=TRADING_CONFIG["symbols"])


@app.route('/backtest/result')
def backtest_result():
    symbol = request.args.get('symbol')
    period = request.args.get('period', '6mo')
    interval = request.args.get('interval', '1d')
    
    if not symbol:
        return redirect(url_for('backtest'))
    
    result = run_backtest(symbol, period, interval)
    return render_template('backtest_result.html', symbol=symbol, period=period, interval=interval, result=result)


def run_backtest(symbol, period, interval):
    import yfinance as yf
    from ta.momentum import RSIIndicator
    from ta.trend import MACD, ADXIndicator
    from ta.volatility import AverageTrueRange
    
    params = db.get_strategy_params()
    if params is None:
        params = STRATEGY_PARAMS
    
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
    
    # 黃金交叉確認 - 簡化版本
    confirm_bars = params.get("confirm_bars", 3)
    
    # 黃金交叉訊號
    df['GC'] = (df['MACD'] > df['MACD_Signal']) & (df['MACD'].shift(1) <= df['MACD_Signal'].shift(1))
    df['DC'] = (df['MACD'] < df['MACD_Signal']) & (df['MACD'].shift(1) >= df['MACD_Signal'].shift(1))
    
    # 建立黃金交叉確認欄位
    gc_confirm = [False] * len(df)
    
    for i in range(confirm_bars + 1, len(df)):
        # 檢查第 0 根是否黃金交叉
        if df['GC'].iloc[i - confirm_bars]:
            # 檢查接下來 confirm_bars 根 DIF 是否都在 DEA 上方
            all_above = True
            for j in range(i - confirm_bars + 1, i + 1):
                if df['MACD'].iloc[j] <= df['MACD_Signal'].iloc[j]:
                    all_above = False
                    break
            gc_confirm[i] = all_above
    
    df['GC_Confirm'] = gc_confirm
    
    # 回測
    capital = 100000
    shares = 0
    position = 0
    trades = []
    
    for i in range(30, len(df)):
        if df.iloc[i]['GC_Confirm'] and position == 0:
            shares = capital // df.iloc[i]['Close']
            entry_price = df.iloc[i]['Close']
            entry_date = df.index[i]
            position = 1
            
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
        "trades": trades[-20:]
    }


# ============ 錯誤處理 ============

@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', error="404 - 頁面不存在"), 404


@app.errorhandler(500)
def server_error(e):
    return render_template('error.html', error="500 - 伺服器錯誤"), 500


if __name__ == '__main__':
    # Railway 環境變數
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
