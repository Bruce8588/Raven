#!/usr/bin/env python3
"""
趋势判断模块
功能：根据利弗莫尔规则，对数据库中的数据生成趋势判断
"""
import os
import sys
import pandas as pd
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "core"))

from core.config.rules import *


def init_state(stock_info):
    """根据必要信息初始化状态"""
    trend = stock_info.get("trend", "up")
    state = {
        "trend": trend,
        "key_high": stock_info.get("key_high"),
        "key_low": stock_info.get("key_low"),
        "n_low": stock_info.get("n_low"),
        "n_high": stock_info.get("n_high"),
        "rally_high": stock_info.get("rally_high"),
        "rally_low": stock_info.get("rally_low"),
        "secondary_low": stock_info.get("secondary_low"),
        "secondary_high": stock_info.get("secondary_high"),
        "break_low": stock_info.get("break_low"),
        "break_high": stock_info.get("break_high"),
        "rally_triggered": False,  # 是否已触发过回升
    }
    return state


def update_trend(state, high, low):
    """根据利弗莫尔规则更新趋势状态"""
    trend = state["trend"]
    key_high = state["key_high"]
    key_low = state["key_low"]
    n_low = state["n_low"]
    n_high = state["n_high"]
    rally_high = state["rally_high"]
    rally_low = state["rally_low"]
    secondary_low = state["secondary_low"]
    secondary_high = state["secondary_high"]
    break_low = state["break_low"]
    break_high = state["break_high"]
    rally_triggered = state.get("rally_triggered", False)

    new_trend = trend

    # ========== 上升趋势体系 ==========
    if trend == "up":
        if key_high is not None and high is not None and high > key_high:
            key_high = high
        if key_high is not None and low is not None and low < key_high * PULLBACK_THRESHOLD:
            n_low = low
            new_trend = "up_natural"

    elif trend == "up_natural":
        if n_low is not None and low is not None and low < n_low:
            n_low = low
        if n_low is not None and high is not None and high > n_low * RALLY_THRESHOLD:
            rally_high = high
            rally_triggered = True
            new_trend = "up_rally"

    elif trend == "up_rally":
        if rally_high is not None and high is not None and high > rally_high:
            rally_high = high
        # 特殊规则：跌破 n_low
        if rally_triggered and n_low is not None and low is not None and low < n_low:
            secondary_low = n_low
            new_trend = "up_secondary"
        # 标准规则：跌破 rally_high × 0.94
        elif rally_high is not None and n_low is not None and low is not None and low < rally_high * PULLBACK_THRESHOLD and low >= n_low:
            secondary_low = low
            new_trend = "up_secondary"
        elif rally_high is not None and high is not None and high > rally_high and (key_high is None or high < key_high):
            rally_high = high
        elif key_high is not None and high is not None and high > key_high:
            key_high = high
            new_trend = "up"

    elif trend == "up_secondary":
        if secondary_low is not None and low is not None and low < secondary_low and (n_low is None or low > n_low):
            secondary_low = low
        elif secondary_low is not None and rally_high is not None and high is not None and high > secondary_low and high < rally_high:
            pass
        elif secondary_low is not None and rally_high is not None and high is not None and high > secondary_low and high > rally_high:
            rally_high = high
            new_trend = "up_rally"
        elif secondary_low is not None and n_low is not None and low is not None and low < secondary_low and low < n_low:
            break_low = n_low
            new_trend = "up_break"

    elif trend == "up_break":
        if break_low is not None and low is not None and low < break_low and (n_low is None or low > n_low * 0.97):
            break_low = low
        elif break_low is not None and n_low is not None and low is not None and low < break_low and low < n_low * 0.97:
            key_low = low
            new_trend = "down"
        elif break_low is not None and high is not None and high > break_low * 1.06:
            rally_high = high
            n_low = break_low
            new_trend = "up_rally"

    # ========== 下跌趋势体系 ==========
    elif trend == "down":
        if key_low is not None and low is not None and low < key_low:
            key_low = low
        if key_low is not None and high is not None and high > key_low * RALLY_THRESHOLD:
            n_high = high
            new_trend = "down_natural"

    elif trend == "down_natural":
        if high is not None and (n_high is None or high > n_high):
            n_high = high
        # 正确规则：价格从n_high下跌6%才触发down_rally
        if n_high is not None and low is not None and low < n_high * PULLBACK_THRESHOLD:
            rally_low = low
            secondary_high = low
            new_trend = "down_rally"

    elif trend == "down_rally":
        if rally_low is not None and high is not None and high > rally_low * RALLY_THRESHOLD:
            secondary_high = high
            new_trend = "down_secondary"
        elif rally_low is not None and low is not None and low < rally_low and (key_low is None or low >= key_low):
            rally_low = low
        elif key_low is not None and low is not None and low < key_low:
            new_trend = "down"

    elif trend == "down_secondary":
        if secondary_high is not None and high is not None and high > secondary_high and (n_high is None or high < n_high):
            secondary_high = high
        elif secondary_high is not None and n_high is not None and high is not None and high > secondary_high and high > n_high:
            break_high = high
            new_trend = "down_break"
        elif secondary_high is not None and rally_low is not None and low is not None and low < secondary_high and low > rally_low:
            pass
        elif secondary_high is not None and rally_low is not None and low is not None and low < secondary_high and low < rally_low:
            new_trend = "down_rally"

    elif trend == "down_break":
        if break_high is not None and high is not None and high > break_high and (n_high is None or high < n_high * 1.03):
            break_high = high
        elif break_high is not None and n_high is not None and high is not None and high > break_high and high > n_high * 1.03:
            key_high = high
            n_low = None  # 重置：进入新的上升周期
            rally_high = None  # 重置：进入新的上升周期
            secondary_low = None  # 重置：进入新的上升周期
            rally_triggered = False  # 重置：进入新的上升周期
            new_trend = "up"
        elif break_high is not None and low is not None and low < break_high * 0.94:
            rally_low = low
            new_trend = "down_rally"

    # 更新状态
    state["trend"] = new_trend
    state["key_high"] = key_high
    state["key_low"] = key_low
    state["n_low"] = n_low
    state["n_high"] = n_high
    state["rally_high"] = rally_high
    state["rally_low"] = rally_low
    state["secondary_low"] = secondary_low
    state["secondary_high"] = secondary_high
    state["break_low"] = break_low
    state["break_high"] = break_high
    state["rally_triggered"] = rally_triggered

    return state


class TrendAnalyzer:
    """趋势分析器"""
    
    def __init__(self, db_dir=None, output_dir=None):
        self.db_dir = db_dir or os.path.join(BASE_DIR, "data")
        self.output_dir = output_dir or os.path.join(BASE_DIR, "output")
        self.trend_dir = os.path.join(self.output_dir, "趋势判断")
        os.makedirs(self.trend_dir, exist_ok=True)
    
    def analyze_stock(self, symbol, info):
        """分析单只股票"""
        code = info["code"]
        db_file = os.path.join(self.db_dir, f"{symbol}_{code}_min1.csv")
        
        if not os.path.exists(db_file):
            print(f"  {symbol}: 数据库文件不存在")
            return None
        
        # 读取数据
        df = pd.read_csv(db_file)
        
        # 处理中文列名
        if '时间' in df.columns:
            df.rename(columns={'时间': 'day', '开盘': 'open', '收盘': 'close', 
                            '最高': 'high', '最低': 'low', '成交量': 'volume', 
                            '成交额': 'amount', '均价': 'avg_price'}, inplace=True)
        
        df["day"] = pd.to_datetime(df["day"])
        df = df.sort_values("day").reset_index(drop=True)
        
        # 初始化状态
        state = init_state(info)
        
        # 分析每条数据
        records = []
        for _, row in df.iterrows():
            high = float(row["high"])
            low = float(row["low"])
            
            state = update_trend(state, high, low)
            
            records.append({
                "时间": row["day"],
                "当前价格": row["close"],
                "趋势代码": state["trend"],
                "趋势名称": TREND_NAMES.get(state["trend"], state["trend"]),
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
        
        # 保存结果
        result_df = pd.DataFrame(records)
        output_file = os.path.join(self.trend_dir, f"{symbol}_趋势判断.csv")
        result_df.to_csv(output_file, index=False, encoding="utf-8")
        
        print(f"  {symbol}: 已分析 {len(records)} 条数据")
        return result_df
    
    def analyze_all(self, stocks):
        """分析所有股票"""
        results = {}
        for symbol, info in stocks.items():
            result = self.analyze_stock(symbol, info)
            results[symbol] = result
        return results


if __name__ == "__main__":
    from config.stocks import POOL_A, WATCHLIST
    
    analyzer = TrendAnalyzer()
    
    print("=== 分析股票池A ===")
    analyzer.analyze_all(POOL_A)
    
    print("\n=== 分析自选股 ===")
    analyzer.analyze_all(WATCHLIST)
    
    print("\n趋势分析完成!")
