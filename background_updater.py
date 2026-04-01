from typing import Optional
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
                config_path = os.path.join(BASE_DIR, "config", "initial_configs.csv")
            self.analyzer = MarketTrendAnalyzer(config_path)
        else:
            self.analyzer = None
        
        self.db_dir = os.path.join(BASE_DIR, "data")
        os.makedirs(self.db_dir, exist_ok=True)

        self.output_dir = os.path.join(BASE_DIR, "output")
        self.trend_judgment_dir = os.path.join(self.output_dir, "趋势判断")
        self.trend_history_dir = os.path.join(self.output_dir, "趋势历史")
        os.makedirs(self.trend_judgment_dir, exist_ok=True)
        os.makedirs(self.trend_history_dir, exist_ok=True)
    
    def _fetch_and_analyze(self, symbol: str) -> Optional[dict]:
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
        
        # ========== 修复1: 动态计算需要获取的天数 ==========
        # 获取配置点时间
        config_time = None
        config_date = None
        if self.analyzer is not None:
            config = self.analyzer.get_stock_config(symbol)
            if config is not None:
                config_time_str = config.get("最新时间", "")
                if config_time_str:
                    try:
                        config_date = pd.to_datetime(config_time_str)
                        today = datetime.now()
                        # 计算需要的天数：配置点到今天 + 多获取2天缓冲
                        days_needed = (today - config_date).days + 3
                        # 最少获取7天，最多30天
                        days_needed = max(7, min(days_needed, 30))
                        print(f"  [后台更新] 配置点: {config_time_str}, 需获取 {days_needed} 天数据")
                    except Exception as e:
                        print(f"  [后台更新] 配置时间解析失败: {e}, 使用默认7天")
                        days_needed = 7
                else:
                    days_needed = 7
            else:
                days_needed = 7
        else:
            days_needed = 7
        
        # 获取分钟数据
        print(f"  [后台更新] 获取 {name} ({code_ifind}) 数据...")
        df = self.fetcher.get_minute_data(code_ifind, days=int(days_needed))
        
        if df is None or df.empty:
            print(f"  [后台更新] {name} 数据获取失败")
            return None
        
        # ========== 修复2: 以配置点为基准截取数据 ==========
        if config_date is not None:
            # 确保时间列是datetime类型
            df["day"] = pd.to_datetime(df["day"])
            # 只保留配置点及之后的数据
            original_len = len(df)
            df = df[df["day"] >= config_date].copy()
            if len(df) < original_len:
                print(f"  [后台更新] 丢弃配置点前数据: {original_len - len(df)} 条")
            
            if df.empty:
                print(f"  [后台更新] {name} 没有配置点之后的数据")
                return None
        
        # 保存到CSV（覆盖模式，从配置点开始的数据）
        db_file = os.path.join(self.db_dir, f"{symbol}_{code_raw}_min1.csv")
        # 使用覆盖模式：只保存从配置点开始的数据
        df.to_csv(db_file, index=False, encoding="utf-8")
        
        # 趋势分析
        if self.analyzer is not None:
            # 构建完整趋势历史：遍历所有分钟数据逐条更新状态
            # 状态初始化必须在配置点
            state = self.analyzer._init_state_from_config(symbol)
            if state is None:
                print(f"  [后台更新] {name} 无法初始化配置状态")
                return None
            
            records = []
            for _, row in df.iterrows():
                high = float(row["high"])
                low = float(row["low"])
                state = update_trend(state, high, low)
                records.append({
                    "时间": row["day"],
                    "day": row["day"],
                    "high": row["high"],
                    "low": row["low"],
                    "close": row["close"],
                    "trend": state["trend"],
                    "trend_name": TREND_NAMES.get(state["trend"], state["trend"]),
                    "key_high": state["key_high"],
                    "key_low": state["key_low"],
                    "n_low": state["n_low"],
                    "n_high": state["n_high"],
                    "rally_high": state["rally_high"],
                    "rally_low": state["rally_low"],
                    "secondary_low": state["secondary_low"],
                    "secondary_high": state["secondary_high"],
                    "break_low": state["break_low"],
                    "break_high": state["break_high"],
                })

            if not records:
                print(f"  [后台更新] {name} 没有有效记录")
                return None

            # 取最后一条记录的状态作为当前趋势
            current_state = records[-1]
            original_state = self.analyzer._init_state_from_config(symbol)
            changed = state["trend"] != original_state["trend"]

            result = {
                "stock_code": symbol,
                "current_price": float(df.iloc[-1]["close"]),
                "trend": state["trend"],
                "trend_name": TREND_NAMES.get(state["trend"], state["trend"]),
                "changed": changed,
                "key_high": state["key_high"],
                "key_low": state["key_low"],
                "n_low": state["n_low"],
                "n_high": state["n_high"],
                "rally_high": state["rally_high"],
                "rally_low": state["rally_low"],
                "secondary_low": state["secondary_low"],
                "secondary_high": state["secondary_high"],
            }

            # 保存趋势判断（当前最新状态）和趋势历史（完整分钟记录）
            self._save_trend_judgment(symbol, name, code_raw, market,
                                     float(df.iloc[-1]["close"]), result, records)
            self._save_trend_history(symbol, records)

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

    def _save_trend_judgment(self, symbol: str, name: str, code_raw: str, market: str,
                             price: float, result: dict, records: list):
        """保存趋势判断文件（当前最新状态）"""
        if not records:
            return

        last = records[-1]
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        signal_text, signal_color = self._get_signal_info(result.get("trend", ""))

        trend_judgment_data = {
            "时间": last["时间"],
            "代码": code_raw,
            "名称": name,
            "市场": market,
            "当前价格": price,
            "趋势代码": result.get("trend", ""),
            "趋势名称": result.get("trend_name", ""),
            "信号文字": signal_text,
            "信号颜色": signal_color,
            "变化标记": "是" if result.get("changed") else "否",
            "更新时间": now_str,
            "key_high": result.get("key_high"),
            "key_low": result.get("key_low"),
            "n_low": result.get("n_low"),
            "n_high": result.get("n_high"),
            "rally_high": result.get("rally_high"),
            "rally_low": result.get("rally_low"),
            "secondary_low": result.get("secondary_low"),
            "secondary_high": result.get("secondary_high"),
            "break_low": result.get("break_low"),
            "break_high": result.get("break_high"),
        }

        df = pd.DataFrame([trend_judgment_data])
        output_file = os.path.join(self.trend_judgment_dir, f"{symbol}_趋势判断.csv")
        df.to_csv(output_file, index=False, encoding="utf-8")

    def _save_trend_history(self, symbol: str, records: list):
        """保存趋势历史文件（覆盖模式，以配置点为起点）"""
        if not records:
            return

        new_df = pd.DataFrame(records)
        output_file = os.path.join(self.trend_history_dir, f"{symbol}_趋势历史.csv")

        # 使用覆盖模式：每次都重新保存从配置点开始的完整历史
        new_df = new_df.sort_values("时间").reset_index(drop=True)
        new_df.to_csv(output_file, index=False, encoding="utf-8")

    def _get_signal_info(self, trend_code: str) -> tuple:
        """根据趋势代码获取信号文字和颜色"""
        signal_map = {
            "up": ("买入", "🔴"),
            "up_natural": ("卖出", "🟡"),
            "up_rally": ("买入", "🟢"),
            "up_secondary": ("卖出", "🟡"),
            "up_break": ("卖出", "🔵"),
            "down": ("观望", "⚪"),
            "down_natural": ("观望", "⚪"),
            "down_rally": ("买入", "🟢"),
            "down_secondary": ("观望", "⚪"),
            "down_break": ("买入", "🔵"),
        }
        return signal_map.get(trend_code, ("未知", "⚪"))
    
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
