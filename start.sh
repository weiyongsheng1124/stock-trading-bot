#!/bin/bash
# Railway 啟動腳本

echo "安裝依賴..."
pip install -q -r requirements.txt

echo "啟動 Web Dashboard..."
python dashboard/app.py
