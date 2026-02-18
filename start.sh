#!/bin/bash
# Railway 啟動腳本

echo "安裝依賴..."
pip install -q -r requirements.txt

echo "啟動 Web Dashboard..."
python dashboard/app.py &
DASHBOARD_PID=$!

echo "啟動交易機器人..."
python bot.py &
BOT_PID=$!

# 等待所有程序
wait $DASHBOARD_PID $BOT_PID
