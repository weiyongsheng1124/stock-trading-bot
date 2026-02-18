"""
Web Dashboard - Flask 伺服器（完整版）
"""
from flask import Flask, render_template, request, jsonify, redirect, url_for
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from json_manager import JsonManager
from config import STRATEGY_PARAMS, TRADING_CONFIG, DEFAULT_SYMBOLS

app = Flask(__name__)

db = JsonManager()


# ============ 即時監控頁 ============

@app.route('/')
@app.route('/monitor')
def monitor():
    positions = db.get_all_positions()
    cooldown = db.get_cooldown_symbols()
    stats = db.get_trade_stats()
    symbols = db.get_monitor_symbols()
    
    return render_template(
        'monitor.html',
        positions=positions,
        cooldown=cooldown,
        stats=stats,
        trading_hours=TRADING_CONFIG["trading_hours"],
        symbols=symbols
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


@app.route('/api/live_chart/<symbol>')
def api_live_chart(symbol):
    import yfinance as yf
    from ta.momentum import RSIIndicator
    from ta.trend import MACD, ADXIndicator
    from ta.volatility import AverageTrueRange
    
    try:
        df = yf.Ticker(symbol).history(period="1d", interval="5m")
        
        if df is None or len(df) < 10:
            return jsonify({"error": "無法取得資料"})
        
        params = db.get_strategy_params() or STRATEGY_PARAMS
        
        macd = MACD(df['Close'], 
                     window_slow=params["macd"]["slow"],
                     window_fast=params["macd"]["fast"], 
                     window_sign=params["macd"]["signal"])
        df['MACD'] = macd.macd()
        df['MACD_Signal'] = macd.macd_signal()
        df['MACD_Hist'] = macd.macd_diff()
        
        df['RSI'] = RSIIndicator(df['Close'], window=params["rsi"]["period"]).rsi()
        
        adx = ADXIndicator(df['High'], df['Low'], df['Close'], window=params["adx"]["period"])
        df['ADX'] = adx.adx()
        
        atr = AverageTrueRange(df['High'], df['Low'], df['Close'], window=params["atr"]["period"])
        df['ATR'] = atr.average_true_range()
        
        position = db.get_position(symbol)
        stop_loss = None
        entry_price = None
        
        if position and position.get("holding_info"):
            entry_price = position["holding_info"].get("entry_price")
            stop_loss = position["holding_info"].get("stop_loss")
        
        candles = []
        for i, row in df.iterrows():
            candle = {
                "time": i.strftime("%Y-%m-%d %H:%M:%S"),
                "open": round(row['Open'], 2),
                "high": round(row['High'], 2),
                "low": round(row['Low'], 2),
                "close": round(row['Close'], 2),
                "volume": int(row['Volume']),
                "macd": round(row['MACD'], 4),
                "macd_signal": round(row['MACD_Signal'], 4),
                "macd_hist": round(row['MACD_Hist'], 4),
                "rsi": round(row['RSI'], 2),
                "adx": round(row['ADX'], 2),
                "atr": round(row['ATR'], 2)
            }
            candles.append(candle)
        
        signals = db.get_signals(symbol=symbol, limit=20)
        
        return jsonify({
            "symbol": symbol,
            "candles": candles,
            "stop_loss": stop_loss,
            "entry_price": entry_price,
            "signals": [s["signal_type"] for s in signals[-5:]],
            "position_status": position["status"] if position else None
        })
        
    except Exception as e:
        return jsonify({"error": str(e)})


# ============ 監控股票管理 ============

@app.route('/api/symbols')
def api_symbols():
    return jsonify(db.get_monitor_symbols())


@app.route('/api/symbols/add', methods=['POST'])
def api_add_symbol():
    data = request.get_json()
    symbol = data.get('symbol', '').strip().upper()
    
    if not symbol:
        return jsonify({"success": False, "error": "請輸入股票代碼"})
    
    try:
        import yfinance as yf
        stock = yf.Ticker(symbol)
        hist = stock.history(period="1mo", interval="1d")
        if hist is None or len(hist) < 5:
            return jsonify({"success": False, "error": f"無法取得 {symbol} 的資料"})
    except Exception as e:
        return jsonify({"success": False, "error": f"驗證失敗：{str(e)}"})
    
    success = db.add_monitor_symbol(symbol)
    if success:
        return jsonify({"success": True, "symbol": symbol})
    return jsonify({"success": False, "error": "股票已存在"})


@app.route('/api/symbols/remove', methods=['POST'])
def api_remove_symbol():
    data = request.get_json()
    symbol = data.get('symbol', '').strip().upper()
    success = db.remove_monitor_symbol(symbol)
    return jsonify({"success": success})


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
        initial_capital = int(request.form.get('initial_capital', 100000))
        
        if 'override' in request.form:
            params = {
                "macd": {
                    "fast": int(request.form.get('macd_fast', 8)),
                    "slow": int(request.form.get('macd_slow', 20)),
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
                "stop_loss_multiplier": float(request.form.get('stop_loss_multiplier', 2.0))
            }
        else:
            params = db.get_strategy_params() or STRATEGY_PARAMS
        
        return redirect(url_for('backtest_result', 
                              symbol=symbol, 
                              period=period, 
                              interval=interval,
                              capital=initial_capital))
    
    symbols = db.get_monitor_symbols()
    return render_template('backtest.html', symbols=symbols, params=STRATEGY_PARAMS)


@app.route('/backtest/result')
def backtest_result():
    symbol = request.args.get('symbol')
    period = request.args.get('period', '6mo')
    interval = request.args.get('interval', '1d')
    initial_capital = int(request.args.get('capital', 100000))
    
    if not symbol:
        return redirect(url_for('backtest'))
    
    try:
        result = run_backtest(symbol, period, interval, initial_capital)
    except Exception as e:
        result = {"error": f"回測發生錯誤：{str(e)}"}
    
    if isinstance(result, dict) and "error" in result:
        return render_template('backtest_result.html', 
                           symbol=symbol, period=period, 
                           interval=interval, capital=initial_capital,
                           error=result["error"])
    
    return render_template('backtest_result.html',
                        symbol=symbol, period=period,
                        interval=interval, capital=initial_capital,
                        result=result)


# ============ 參數優化器 ============

@app.route('/api/optimize', methods=['POST'])
def api_optimize():
    """參數優化器 - 根據目標勝率推薦最佳參數"""
    data = request.get_json()
    symbol = data.get('symbol')
    target_win_rate = float(data.get('target_win_rate', 60))
    period = data.get('period', '1y')
    interval = data.get('interval', '1d')
    initial_capital = int(data.get('initial_capital', 100000))
    
    if not symbol:
        return jsonify({"success": False, "error": "請輸入股票代碼"})
    
    try:
        results = optimize_params(symbol, period, interval, initial_capital, target_win_rate)
        if "error" in results:
            return jsonify({"success": False, "error": results["error"]})
        return jsonify({"success": True, **results})
    except Exception as e:
        return jsonify({"success": False, "error": f"優化過程發生錯誤：{str(e)}"})


def optimize_params(symbol, period, interval, initial_capital, target_win_rate):
    """網格搜索找出符合目標勝率的最佳參數"""
    import yfinance as yf
    from ta.momentum import RSIIndicator
    from ta.trend import MACD, ADXIndicator
    from ta.volatility import AverageTrueRange
    
    # 取得股價資料
    try:
        df = yf.Ticker(symbol).history(period=period, interval=interval)
        if df is None or len(df) < 50:
            return {"error": f"無法取得 {symbol} 的股價資料或資料不足 (取得 {len(df) if df is not None else 0} 筆)"}
    except Exception as e:
        return {"error": f"取得股價資料失敗：{str(e)}"}
    
    # 參數網格
    param_grid = {
        "macd_fast": [8, 12, 16],
        "macd_slow": [20, 26, 32],
        "macd_signal": [6, 9, 12],
        "rsi_period": [7, 14, 21],
        "confirm_bars": [1, 2, 3, 5],
        "stop_loss_multiplier": [1.5, 2.0, 2.5]
    }
    
    best_result = None
    best_score = -999
    total_combinations = 0
    valid_combinations = 0
    
    # 遍歷所有參數組合
    for macd_fast in param_grid["macd_fast"]:
        for macd_slow in param_grid["macd_slow"]:
            if macd_fast >= macd_slow:
                continue
            for signal in param_grid["macd_signal"]:
                for rsi_period in param_grid["rsi_period"]:
                    for confirm in param_grid["confirm_bars"]:
                        for sl_mult in param_grid["stop_loss_multiplier"]:
                            
                            total_combinations += 1
                            
                            params = {
                                "macd": {"fast": macd_fast, "slow": macd_slow, "signal": signal},
                                "rsi": {"period": rsi_period, "oversold": 30, "overbought": 70},
                                "adx": {"period": 14, "threshold": 20},
                                "atr": {"period": 14},
                                "confirm_bars": confirm,
                                "stop_loss_multiplier": sl_mult
                            }
                            
                            try:
                                result = run_backtest_with_params(df, params, initial_capital)
                                
                                if "error" in result:
                                    continue
                                
                                valid_combinations += 1
                                
                                # 計算分數：接近目標勝率且報酬率越高越好
                                win_rate_diff = abs(result["win_rate"] - target_win_rate)
                                score = -win_rate_diff * 100 + result["total_return"] * 0.1
                                
                                if score > best_score:
                                    best_score = score
                                    best_result = result
                                    
                            except Exception as e:
                                continue
    
    if best_result is None:
        return {"error": f"找不到符合條件的參數組合 (已測試 {total_combinations} 組，其中 {valid_combinations} 組有效)"}
    
    return {
        "symbol": symbol,
        "target_win_rate": target_win_rate,
        "recommended_params": best_result["params"],
        "result": best_result
    }


def run_backtest_with_params(df, params, initial_capital=100000):
    """使用指定參數執行回測"""
    from ta.momentum import RSIIndicator
    from ta.trend import MACD, ADXIndicator
    from ta.volatility import AverageTrueRange
    
    try:
        # 複製資料避免修改原始資料
        df = df.copy()
        
        # 記錄股價資料（用於圖表）
        price_data = []
        for i in range(len(df)):
            price_data.append({
                "time": str(df.index[i].date()),
                "open": round(float(df['Open'].iloc[i]), 2),
                "high": round(float(df['High'].iloc[i]), 2),
                "low": round(float(df['Low'].iloc[i]), 2),
                "close": round(float(df['Close'].iloc[i]), 2)
            })
        
        macd = MACD(df['Close'], 
                     window_slow=params["macd"]["slow"],
                     window_fast=params["macd"]["fast"], 
                     window_sign=params["macd"]["signal"])
        df['MACD'] = macd.macd()
        df['MACD_Signal'] = macd.macd_signal()
        df['MACD_Hist'] = macd.macd_diff()
        
        df['RSI'] = RSIIndicator(df['Close'], window=params["rsi"]["period"]).rsi()
        
        atr = AverageTrueRange(df['High'], df['Low'], df['Close'], window=params["atr"]["period"])
        df['ATR'] = atr.average_true_range()
        
        # 買賣訊號
        df['GC'] = (df['MACD'] > df['MACD_Signal']) & (df['MACD'].shift(1) <= df['MACD_Signal'].shift(1))
        df['DC'] = (df['MACD'] < df['MACD_Signal']) & (df['MACD'].shift(1) >= df['MACD_Signal'].shift(1))
        
        confirm_bars = params.get("confirm_bars", 3)
        gc_confirm = [False] * len(df)
        
        for i in range(confirm_bars + 1, len(df)):
            if df['GC'].iloc[i - confirm_bars]:
                all_above = True
                for j in range(i - confirm_bars + 1, i + 1):
                    if df['MACD'].iloc[j] <= df['MACD_Signal'].iloc[j]:
                        all_above = False
                        break
                gc_confirm[i] = all_above
        
        df['GC_Confirm'] = gc_confirm
        
        # 執行回測
        capital = float(initial_capital)
        shares = 0
        position = 0
        trades = []
        equity_curve = []  # 資金曲線
        buy_signals = []  # 買入點
        sell_signals = []  # 賣出點
        
        # 從有足夠歷史資料的地方開始
        start_idx = 30  # 避開前面需要計算指標的資料
        
        for i in range(start_idx, len(df)):
            current_price = float(df['Close'].iloc[i])
            current_time = str(df.index[i].date())
            
            # 記錄資金（每天都記錄）
            if position:
                current_equity = shares * current_price
            else:
                current_equity = capital
            
            equity_curve.append({
                "time": current_time,
                "equity": round(current_equity, 2)
            })
            
            # 買入訊號
            if df.iloc[i]['GC_Confirm'] and position == 0:
                # 計算買入數量
                if current_price > 0:
                    shares = int(capital // current_price)
                entry_price = current_price
                entry_date = df.index[i]
                position = 1
                
                # 記錄買入點
                buy_signals.append({
                    "time": current_time,
                    "price": round(entry_price, 2),
                    "index": i
                })
                
            # 賣出訊號
            elif df.iloc[i]['DC'] and position == 1:
                exit_price = current_price
                exit_date = df.index[i]
                pnl = (exit_price - entry_price) / entry_price * 100
                
                trades.append({
                    "id": len(trades) + 1,
                    "entry_date": str(entry_date.date()),
                    "exit_date": current_time,
                    "entry_price": round(entry_price, 2),
                    "exit_price": round(exit_price, 2),
                    "pnl": round(pnl, 2),
                    "win": pnl > 0
                })
                
                # 記錄賣出點
                sell_signals.append({
                    "time": current_time,
                    "price": round(exit_price, 2),
                    "index": i,
                    "pnl": round(pnl, 2)
                })
                
                # 更新資金
                capital = shares * exit_price
                position = 0
                shares = 0
        
        # 統計
        total = len(trades)
        winning = [t for t in trades if t["win"]]
        win_rate = len(winning) / total * 100 if total > 0 else 0
        
        # 計算回撤曲線
        drawdown = []
        if equity_curve:
            equity_values = [e["equity"] for e in equity_curve]
            peak = equity_values[0]
            
            for eq in equity_values:
                if eq > peak:
                    peak = eq
                dd = (peak - eq) / peak * 100 if peak > 0 else 0
                drawdown.append({
                    "time": equity_curve[len(drawdown)]["time"],
                    "drawdown": round(dd, 2)
                })
        
        return {
            "total_trades": total,
            "wins": len(winning),
            "losses": total - len(winning),
            "win_rate": round(win_rate, 2),
            "total_return": round((capital - initial_capital) / initial_capital * 100, 2),
            "trades": trades,
            "equity_curve": equity_curve,
            "buy_signals": buy_signals,
            "sell_signals": sell_signals,
            "price_data": price_data,
            "drawdown": drawdown,
            "max_drawdown": round(max([d["drawdown"] for d in drawdown]) if drawdown else 0, 2),
            "final_capital": round(capital, 2),
            "params": params
        }
        
    except Exception as e:
        import traceback
        return {"error": f"{str(e)}\n{traceback.format_exc()}"}


def run_backtest(symbol, period, interval, initial_capital=100000):
    """執行回測（使用儲存的參數）"""
    import yfinance as yf
    from ta.momentum import RSIIndicator
    from ta.trend import MACD, ADXIndicator
    from ta.volatility import AverageTrueRange
    
    params = db.get_strategy_params()
    if params is None:
        from config import STRATEGY_PARAMS
        params = STRATEGY_PARAMS
    
    try:
        df = yf.Ticker(symbol).history(period=period, interval=interval)
    except Exception as e:
        return {"error": f"無法取得股價資料：{str(e)}"}
    
    if df is None or len(df) < 50:
        return {"error": "無法取得足夠資料進行回測"}
    
    result = run_backtest_with_params(df, params, initial_capital)
    
    if "error" in result:
        return result
    
    return result


# ============ 錯誤處理 ============

@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', error="404 - 頁面不存在"), 404


@app.errorhandler(500)
def server_error(e):
    return render_template('error.html', error="500 - 伺服器錯誤"), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
