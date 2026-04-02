#!/usr/bin/env python3
"""
Raven 后台趋势追踪器（独立进程）
与 web.py 完全分离，避免 Flask 重启时中断后台更新
用法: python3 run_tracker.py
"""
import sys
import os

# 确保导入路径正确
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from background_updater import BackgroundUpdater, stop_background_updater
import signal
import time

TRACKER_INTERVAL = 300      # 完整趋势分析间隔（秒）
TRACKER_QUICK_INTERVAL = 30  # 快速价格更新间隔（秒）

def signal_handler(sig, frame):
    print("\n[追踪器] 收到停止信号，正在关闭...")
    stop_background_updater()
    sys.exit(0)

def main():
    print("=" * 50)
    print("📈 Raven 后台趋势追踪器（独立模式）")
    print(f"   完整分析间隔: {TRACKER_INTERVAL} 秒")
    print(f"   快速更新间隔: {TRACKER_QUICK_INTERVAL} 秒")
    print("=" * 50)
    
    # 注册信号处理（优雅退出）
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # 创建并启动后台更新器
    updater = BackgroundUpdater(
        interval=TRACKER_INTERVAL,
        quick_interval=TRACKER_QUICK_INTERVAL
    )
    updater.start()
    
    print("[追踪器] 已启动，按 Ctrl+C 停止")
    
    # 保持运行
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        signal_handler(None, None)

if __name__ == '__main__':
    main()
