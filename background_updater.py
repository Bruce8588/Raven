#!/usr/bin/env python3
"""
Raven 后台数据更新模块
功能：后台定期更新已搜索股票的iFind数据
"""
import time
import threading
import sys
import os
import json
from datetime import datetime
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from cache import StockCache
from fetcher.ifind import IFinDFetcher

# 尝试导入analyzer
try:
    from core.analyzer import MarketTrendAnalyzer
    from core.trend import init_state, update_trend
    from core.config.rules import TREND_NAMES
    HAS_ANALYZER = True
except ImportError as e:
    HAS_ANALYZER = False
    print(f"警告: 无法导入趋势分析器 ({e})，后台更新将以简化模式运行")


class BackgroundUpdater:
    """后台定期更新已搜索股票"""
    
    def __init__(self, interval: int = 300, config_path: str = None):
        """
        Args:
            interval: 更新间隔（秒），默认300秒（5分钟）
            config_path: 初始配置CSV路径
        """
        self.cache = StockCache()
        self.fetcher = IFinDFetcher()
        self.interval = interval
        self.running = False
        self._thread = None
        
        # 初始化趋势分析器
        if HAS_ANALYZER:
            if config_path is None:
                config_path = os.path.join(BASE_DIR, "config", "initial", "initial_configs.csv")
            self.analyzer = MarketTrendAnalyzer(config_path)
        else:
            self.analyzer = None
        
        self.db_dir = os.path.join(BASE_DIR, "data")
        os.makedirs(self.db_dir, exist_ok=True)
    
    def _fetch_and_analyze(self, symbol: str) -> dict | None:
        """
        获取单只股票数据并进行趋势分析
        
        Returns:
            分析后的数据字典，如果失败返回None
        """
        # 从watchlist获取股票代码
        watchlist_path = os.path.join(BASE_DIR, "config", "watchlist.json")
        if not os.path.exists(watchlist_path):
            print(f"  [后台更新] watchlist.json 不存在")
            return None
        
        with open(watchlist_path, "r", encoding="utf-8") as f:
            watchlist = json.load(f)
        
        # 兼容不同watchlist格式
        info = None
        code = None
        
        # 格式1: key是symbol如 "sh002129"
        if symbol in watchlist:
            info = watchlist[symbol]
            code = info.get("code", "")
        
        # 格式2: key是纯代码
        if info is None:
            for k, v in watchlist.items():
                if v.get("code") == symbol:
                    info = v
                    code = symbol
                    symbol = k
                    break
        
        if info is None:
            print(f"  [后台更新] 未找到股票 {symbol} 的配置")
            return None
        
        name = info.get("name", symbol)
        code_raw = info.get("code", "")
        market = info.get("market", "")
        
        # 转换代码格式：sz/sh前缀 -> iFinD格式
        code_ifind = self._convert_code(code_raw, market)
        
        # 获取分钟数据
        print(f"  [后台更新] 获取 {name} ({code_ifind}) 数据...")
        df = self.fetcher.get_minute_data(code_ifind, days=7)
        
        if df is None or df.empty:
            print(f"  [后台更新] {name} 数据获取失败")
            return None
        
        # 保存到CSV
        db_file = os.path.join(self.db_dir, f"{symbol}_{code_raw}_min1.csv")
        if os.path.exists(db_file):
            old_df = pd.read_csv(db_file)
            old_df["day"] = pd.to_datetime(old_df["day"])
            df = pd.concat([old_df, df], ignore_index=True)
            df = df.drop_duplicates(subset=["day"], keep="last")
            df = df.sort_values("day").reset_index(drop=True)
        df.to_csv(db_file, index=False, encoding="utf-8")
        
        # 趋势分析
        if self.analyzer is not None:
            result = self.analyzer.update_trend(symbol, float(df.iloc[-1]["close"]))
            if result:
                trend_code = result.get("trend", "")
                return {
                    "name": name,
                    "code": code_raw,
                    "market": market,
                    "price": float(df.iloc[-1]["close"]),
                    "trend_code": trend_code,
                    "trend_name": TREND_NAMES.get(trend_code, trend_code),
                    "key_high": result.get("key_high"),
                    "key_low": result.get("key_low"),
                    "n_high": result.get("n_high"),
                    "n_low": result.get("n_low"),
                    "rally_high": result.get("rally_high"),
                    "rally_low": result.get("rally_low"),
                    "secondary_high": result.get("secondary_high"),
                    "secondary_low": result.get("secondary_low"),
                    "description": f"后台自动更新 @ {datetime.now().strftime('%H:%M:%S')}",
                }
        
        # 简化模式：直接返回最新价格
        return {
            "name": name,
            "code": code_raw,
            "market": market,
            "price": float(df.iloc[-1]["close"]),
            "trend_code": "",
            "trend_name": "待分析",
        }
    
    def _convert_code(self, code: str, market: str) -> str:
        """转换代码格式为iFinD格式，如 000333 + SZ -> 000333.SZ"""
        market = market.upper()
        if market in ("SZ", "SH"):
            return f"{code}.{market}"
        return code
    
    def update_all(self):
        """更新所有已搜索股票的数据"""
        searched = self.cache.get_searched()
        if not searched:
            print(f"[后台更新] 无已搜索股票，跳过更新")
            return
        
        print(f"[后台更新] 开始更新 {len(searched)} 只股票: {searched}")
        success = 0
        for symbol in searched:
            try:
                data = self._fetch_and_analyze(symbol)
                if data:
                    self.cache.set(symbol, data)
                    success += 1
                    print(f"  ✓ {data.get('name', symbol)} 更新成功")
                time.sleep(1)  # 避免请求过快
            except Exception as e:
                print(f"  ✗ {symbol} 更新失败: {e}")
        
        print(f"[后台更新] 完成: {success}/{len(searched)} 只股票")
    
    def start(self):
        """启动后台更新线程"""
        if self.running:
            print("[后台更新] 已经在运行中")
            return
        
        self.running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        print(f"[后台更新] 已启动，间隔 {self.interval} 秒")
    
    def stop(self):
        """停止后台更新线程"""
        self.running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        print("[后台更新] 已停止")
    
    def _run(self):
        """后台更新循环"""
        import pandas as pd  # 用于CSV读写
        while self.running:
            try:
                self.update_all()
            except Exception as e:
                print(f"[后台更新] 更新过程出错: {e}")
            
            # 分段睡眠，支持快速停止
            for _ in range(self.interval):
                if not self.running:
                    break
                time.sleep(1)


# 便捷函数：创建并启动后台更新器
_default_updater = None


def start_background_updater(interval: int = 300):
    """启动默认的后台更新器"""
    global _default_updater
    if _default_updater is None:
        _default_updater = BackgroundUpdater(interval=interval)
    _default_updater.start()
    return _default_updater


def stop_background_updater():
    """停止默认的后台更新器"""
    global _default_updater
    if _default_updater:
        _default_updater.stop()
        _default_updater = None


if __name__ == "__main__":
    # 测试后台更新
    updater = BackgroundUpdater(interval=60)  # 1分钟用于测试
    updater.start()
    print("后台更新器已启动，按 Ctrl+C 停止")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        updater.stop()
