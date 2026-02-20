"""
Web Dashboard - Flask 伺服器（完整版）
"""
from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_cors import CORS
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from json_manager import JsonManager
from config import STRATEGY_PARAMS, TRADING_CONFIG, DEFAULT_SYMBOLS

app = Flask(__name__)
CORS(app)  # 允許跨域請求

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



def safe_round(val, decimals=2):
    """安全四捨五入，處理 NaN"""
    import math
    try:
        if val is None or (isinstance(val, float) and math.isnan(val)):
            return None
        return round(float(val), decimals)
    except (ValueError, TypeError):
        return None
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
        
        # 使用個別股票策略，如果沒有則使用預設參數
        params = db.get_symbol_params(symbol)
        if params is None:
            params = STRATEGY_PARAMS
        
        macd = MACD(df['Close'], 
                     window_slow=params["macd"]["slow"],
                     window_fast=params["macd"]["fast"], 
                     window_sign=params["macd"]["signal"])
        df['MACD'] = macd.macd().fillna(0)
        df['MACD_Signal'] = macd.macd_signal().fillna(0)
        df['MACD_Hist'] = macd.macd_diff().fillna(0)
        
        df['RSI'] = RSIIndicator(df['Close'], window=params["rsi"]["period"]).rsi().fillna(50)
        
        adx = ADXIndicator(df['High'], df['Low'], df['Close'], window=params["adx"]["period"])
        df['ADX'] = adx.adx().fillna(20)
        
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
                "open": safe_round(row['Open'], 2),
                "high": safe_round(row['High'], 2),
                "low": safe_round(row['Low'], 2),
                "close": safe_round(row['Close'], 2),
                "volume": int(row['Volume']),
                "macd": safe_round(row['MACD'], 4),
                "macd_signal": safe_round(row['MACD_Signal'], 4),
                "macd_hist": safe_round(row['MACD_Hist'], 4),
                "rsi": safe_round(row['RSI'], 2),
                "adx": safe_round(row['ADX'], 2),
                "atr": safe_round(row['ATR'], 2)
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

@app.route('/config')
def config():
    """策略配置頁 - 重定向到第一個監控股票"""
    symbols = db.get_monitor_symbols()
    if symbols and len(symbols) > 0:
        return redirect(url_for('config_symbol', symbol=symbols[0]))
    return redirect(url_for('monitor'))


# ============ 個別股票策略配置 ============

@app.route('/config/<symbol>')
def config_symbol(symbol):
    """個別股票策略配置頁"""
    symbol = symbol.upper()
    params = db.get_symbol_params(symbol)
    if params is None:
        params = db.get_strategy_params() or STRATEGY_PARAMS
    
    all_symbols = db.get_monitor_symbols()
    all_params = db.get_all_symbol_params()
    
    return render_template(
        'config_symbol.html', 
        symbol=symbol, 
        params=params,
        all_symbols=all_symbols,
        all_params=all_params
    )


@app.route('/config/<symbol>', methods=['POST'])
def config_symbol_save(symbol):
    """儲存個別股票策略參數"""
    try:
        symbol = symbol.upper()
        
        # 解析表單參數
        def get_int(key, default):
            val = request.form.get(key)
            try:
                return int(val) if val else default
            except:
                return default
        
        def get_float(key, default):
            val = request.form.get(key)
            try:
                return float(val) if val else default
            except:
                return default
        
        params = {
            "macd": {
                "fast": get_int('macd_fast', 12),
                "slow": get_int('macd_slow', 26),
                "signal": get_int('macd_signal', 9)
            },
            "rsi": {
                "period": get_int('rsi_period', 14),
                "oversold": get_int('rsi_oversold', 30),
                "overbought": get_int('rsi_overbought', 70)
            },
            "adx": {
                "period": get_int('adx_period', 14),
                "threshold": get_int('adx_threshold', 20)
            },
            "atr": {
                "period": get_int('atr_period', 14)
            },
            "confirm_bars": get_int('confirm_bars', 3),
            "stop_loss_multiplier": get_float('stop_loss_multiplier', 2.0),
            "new_high_period": get_int('new_high_period', 252)
        }
        
        # 儲存參數
        success = db.save_symbol_params(symbol, params)
        
        return render_template(
            'config_symbol.html',
            symbol=symbol,
            params=params,
            all_symbols=db.get_monitor_symbols(),
            all_params=db.get_all_symbol_params(),
            success=success
        )
    except Exception as e:
        import traceback
        print("儲存參數錯誤:", traceback.format_exc())
        return render_template('error.html', error=f"儲存參數失敗：{str(e)}"), 500


@app.route('/api/symbol_params/<symbol>')
def api_symbol_params(symbol):
    """取得個別股票參數 API"""
    params = db.get_symbol_params(symbol)
    # 只返回自訂參數，None 表示使用預設
    return jsonify({"symbol": symbol.upper(), "params": params})


@app.route('/api/symbol_params/<symbol>', methods=['POST'])
def api_save_symbol_params(symbol):
    """儲存個別股票參數 API"""
    data = request.get_json()
    params = data.get('params')
    
    if params:
        db.save_symbol_params(symbol.upper(), params)
        return jsonify({"success": True, "symbol": symbol.upper()})
    
    return jsonify({"success": False, "error": "無參數資料"})


@app.route('/api/symbol_params/<symbol>', methods=['DELETE'])
def api_delete_symbol_params(symbol):
    """刪除個別股票參數 API"""
    db.delete_symbol_params(symbol.upper())
    return jsonify({"success": True})

@app.route('/api/symbol_params', methods=['GET'])
def api_all_symbol_params():
    """取得所有股票參數 API"""
    all_params = db.get_all_symbol_params()
    return jsonify(all_params)


# ============ 回測頁 ============

@app.route('/backtest', methods=['GET', 'POST'])
def backtest():
    if request.method == 'POST':
        symbol = request.form.get('symbol', '').upper().strip()
        period = request.form.get('period', '6mo')
        interval = request.form.get('interval', '1d')
        initial_capital = int(request.form.get('initial_capital', 100000))
        strategy_type = request.form.get('strategy_type', 'default')
        selected_symbol = request.form.get('selected_symbol', '').upper().strip()
        
        # 解析策略類型
        if strategy_type.startswith('symbol:'):
            # 使用指定股票的個別策略
            target_symbol = selected_symbol or symbol
            symbol_params = db.get_symbol_params(target_symbol)
            if symbol_params:
                params = symbol_params
            else:
                params = STRATEGY_PARAMS
        elif strategy_type == 'custom':
            # 自訂參數，會在下麵覆蓋
            params = STRATEGY_PARAMS
        else:
            # 使用預設策略
            params = STRATEGY_PARAMS
        
        # 如果有override參數，使用表單中的值
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
            
            # 儲存為該股票的個別策略
            db.save_symbol_params(symbol, params)
        
        # 將使用的參數序列化為 URL 參數
        import urllib.parse
        params_json = urllib.parse.quote(json.dumps(params))
        
        return redirect(url_for('backtest_result', 
                              symbol=symbol, 
                              period=period, 
                              interval=interval,
                              capital=initial_capital,
                              params_data=params_json))
    
    symbols = db.get_monitor_symbols()
    all_params = db.get_all_symbol_params()
    default_params = STRATEGY_PARAMS
    return render_template('backtest.html', 
                         symbols=symbols, 
                         params=default_params,
                         all_params=all_params)


@app.route('/backtest/result')
def backtest_result():
    symbol = request.args.get('symbol')
    period = request.args.get('period', '6mo')
    interval = request.args.get('interval', '1d')
    initial_capital = int(request.args.get('capital', 100000))
    params_data = request.args.get('params_data')
    
    if not symbol:
        return redirect(url_for('backtest'))
    
    try:
        # 如果 URL 有傳遞參數，直接使用
        if params_data:
            import urllib.parse
            params = json.loads(urllib.parse.unquote(params_data))
            result = run_backtest(symbol, period, interval, initial_capital, params)
        else:
            # 否則執行回測（使用預設參數）
            result = run_backtest(symbol, period, interval, initial_capital)
    except Exception as e:
        result = {"error": f"回測發生錯誤：{str(e)}"}
    
    if isinstance(result, dict) and "error" in result:
        return render_template('backtest_result.html', 
                           symbol=symbol, period=period, 
                           interval=interval, capital=initial_capital,
                           error=result["error"],
                           symbols=db.get_monitor_symbols())
    
    return render_template('backtest_result.html',
                        symbol=symbol, period=period,
                        interval=interval, capital=initial_capital,
                        result=result,
                        symbols=db.get_monitor_symbols())


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
        
        # 記錄股價資料（用於圖表）- 從 start_idx 開始，與 equityCurve 對齊
        price_data = []
        start_idx = 30
        for i in range(start_idx, len(df)):
            price_data.append({
                "time": str(df.index[i].date()),
                "open": float(round(float(df['Open'].iloc[i]), 2)),
                "high": float(round(float(df['High'].iloc[i]), 2)),
                "low": float(round(float(df['Low'].iloc[i]), 2)),
                "close": float(round(float(df['Close'].iloc[i]), 2))
            })
        
        # 計算 MACD
        macd = MACD(df['Close'], 
                     window_slow=params["macd"]["slow"],
                     window_fast=params["macd"]["fast"], 
                     window_sign=params["macd"]["signal"])
        df['MACD'] = macd.macd().fillna(0)  # NaN 填為 0
        df['MACD_Signal'] = macd.macd_signal().fillna(0)
        df['MACD_Hist'] = macd.macd_diff().fillna(0)
        
        df['RSI'] = RSIIndicator(df['Close'], window=params["rsi"]["period"]).rsi().fillna(50)
        
        # ADX 指標計算
        try:
            adx_indicator = ADXIndicator(df['High'], df['Low'], df['Close'], window=params["adx"]["period"])
            df['ADX'] = adx_indicator.adx().fillna(20)
            df['ADX'] = df['ADX'].clip(lower=0, upper=100)  # ADX 範圍 0-100
        except:
            df['ADX'] = 20
        
        atr = AverageTrueRange(df['High'], df['Low'], df['Close'], window=params["atr"]["period"])
        df['ATR'] = atr.average_true_range().fillna(df['Close'].mean() * 0.02)
        
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
        initial_capital_float = float(initial_capital)
        cash = initial_capital_float  # 現金
        shares = 0  # 股數
        position = 0  # 是否持有部位
        entry_price = 0  # 買入價格
        entry_date = None  # 買入日期
        trades = []
        equity_curve = []  # 資金曲線（總資產 = 現金 + 股票價值）
        buy_signals = []  # 買入點
        sell_signals = []  # 賣出點
        macd_data = []  # MACD 數據
        rsi_data = []  # RSI 數據
        adx_data = []  # ADX 數據
        
        # 固定倉位比例（50%）
        position_size = 1.0
        
        # 從有足夠歷史資料的地方開始
        start_idx = 30  # 避開前面需要計算指標的資料
        
        for i in range(start_idx, len(df)):
            current_price = float(df['Close'].iloc[i])
            current_time = str(df.index[i].date())
            
            # 記錄技術指標
            macd_data.append({
                "time": current_time,
                "macd": round(float(df['MACD'].iloc[i]), 4),
                "signal": round(float(df['MACD_Signal'].iloc[i]), 4),
                "hist": round(float(df['MACD_Hist'].iloc[i]), 4)
            })
            rsi_data.append({
                "time": current_time,
                "rsi": round(float(df['RSI'].iloc[i]), 2)
            })
            adx_data.append({
                "time": current_time,
                "adx": round(float(df['ADX'].iloc[i]), 2)
            })
            
            # 計算總資產（現金 + 股票價值）
            if position:
                current_equity = cash + shares * current_price
            else:
                current_equity = cash
            
            # 記錄為相對於初始資金的比例 (%)
            equity_pct = (current_equity - initial_capital_float) / initial_capital_float * 100
            equity_curve.append({
                "time": current_time,
                "equity": round(current_equity, 2),
                "equity_pct": round(equity_pct, 2)
            })
            
            # 買入訊號
            if df.iloc[i]['GC_Confirm'] and position == 0:
                # 用當時的全部資金買入
                if current_price > 0:
                    shares = int(cash // current_price)
                    cost = shares * current_price
                    cash = cash - cost  # 剩下的是現金
                entry_price = current_price
                entry_date = df.index[i]
                position = 1
                
                # 記錄買入點
                buy_signals.append({
                    "time": current_time,
                    "price": float(round(entry_price, 2)),
                    "index": i - start_idx  # 改為相對於 price_data 的索引
                })
                
            # 賣出訊號
            elif df.iloc[i]['DC'] and position == 1:
                exit_price = current_price
                exit_date = df.index[i]
                
                # 計算此筆交易的報酬率
                pnl_pct = (exit_price - entry_price) / entry_price * 100
                is_win = pnl_pct > 0
                
                trades.append({
                    "id": len(trades) + 1,
                    "entry_date": str(entry_date.date()),
                    "exit_date": current_time,
                    "entry_price": float(round(entry_price, 2)),
                    "exit_price": float(round(exit_price, 2)),
                    "pnl": float(round(pnl_pct, 2)),
                    "win": bool(is_win)
                })
                
                # 記錄賣出點
                sell_signals.append({
                    "time": current_time,
                    "price": float(round(exit_price, 2)),
                    "index": i - start_idx,  # 改為相對於 price_data 的索引
                    "pnl": float(round(pnl_pct, 2))
                })
                
                # 賣出股票，回收全部資金
                cash = cash + shares * exit_price
                shares = 0
                position = 0
        
        # 統計
        total = len(trades)
        winning = [t for t in trades if t.get("win") is True or t.get("win") == "true"]
        win_rate = len(winning) / total * 100 if total > 0 else 0
        
        # 計算總報酬率（基於最後一天的 equity_pct）
        final_equity_pct = 0
        if equity_curve:
            final_equity_pct = equity_curve[-1].get("equity_pct", 0)
        
        # 計算回撤曲線（基於 equity_pct）
        drawdown = []
        if equity_curve and len(equity_curve) > 0:
            peak_pct = 0  # 峰值%（從0開始）
            current_dd = 0  # 當前回撤%
            
            for item in equity_curve:
                equity_pct = item.get("equity_pct", 0)
                
                # 更新峰值
                if equity_pct >= peak_pct:
                    peak_pct = equity_pct
                    current_dd = 0  # 回到高點，回撤歸零
                elif equity_pct < peak_pct:
                    # 計算新回撤
                    current_dd = peak_pct - equity_pct
                
                drawdown.append({
                    "time": item["time"],
                    "drawdown": round(current_dd, 2)
                })
        
        max_dd = 0
        if drawdown:
            max_dd = max([d["drawdown"] for d in drawdown])
        
        return {
            "total_trades": total,
            "wins": len(winning),
            "losses": total - len(winning),
            "win_rate": round(win_rate, 2),
            "total_return": round(final_equity_pct, 2),
            "trades": trades,
            "equity_curve": equity_curve,
            "buy_signals": buy_signals,
            "sell_signals": sell_signals,
            "price_data": price_data,
            "drawdown": drawdown,
            "macd_data": macd_data,
            "rsi_data": rsi_data,
            "adx_data": adx_data,
            "max_drawdown": round(max_dd, 2),
            "final_capital": round(equity_curve[-1]["equity"], 2) if equity_curve else round(initial_capital_float, 2),
            "params": params
        }
        
    except Exception as e:
        import traceback
        return {"error": f"{str(e)}\n{traceback.format_exc()}"}


def run_backtest(symbol, period, interval, initial_capital=100000, params_override=None):
    """執行回測（使用儲存的參數或指定的參數）"""
    import yfinance as yf
    from ta.momentum import RSIIndicator
    from ta.trend import MACD, ADXIndicator
    from ta.volatility import AverageTrueRange
    
    # 如果有指定參數則使用，否則使用預設參數
    if params_override:
        params = params_override
    else:
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
    import traceback
    print("500錯誤:", traceback.format_exc())
    return render_template('error.html', error="500 - 伺服器錯誤\n" + str(e)), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
