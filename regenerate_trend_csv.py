#!/usr/bin/env python3
"""重新生成趋势历史CSV（仅记录变化点，每行一个关键点）"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from core.trend import init_state, update_trend
import importlib
# 动态加载规则模块获取 TREND_NAMES
from core.config import rules
TREND_NAMES = getattr(rules, 'TREND_NAMES', {})

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "output", "趋势历史")
CONFIG_FILE = os.path.join(BASE_DIR, "config", "initial_configs.csv")
os.makedirs(OUTPUT_DIR, exist_ok=True)

TREND_KEYPOINT_MAP = {
    "up": "key_high",
    "up_natural": "n_low",
    "up_rally": "rally_high",
    "up_secondary": "secondary_low",
    "up_break": "key_low",
    "down": "key_low",
    "down_natural": "n_high",
    "down_rally": "rally_low",
    "down_secondary": "secondary_high",
    "down_break": "key_high",
}

def get_stock_config(symbol):
    """从initial_configs.csv获取股票的初始配置"""
    if not os.path.exists(CONFIG_FILE):
        return None
    df = pd.read_csv(CONFIG_FILE)
    # 尝试匹配 symbol (去掉sh/sz前缀)
    clean = symbol.replace('sh', '').replace('sz', '')
    match = df[df['股票代码'].str.contains(clean, na=False)]
    if match.empty:
        return None
    row = match.iloc[0]
    return {
        "trend": row.get('趋势代码', 'up'),
        "key_high": row.get('key_high') if pd.notna(row.get('key_high')) else None,
        "key_low": row.get('key_low') if pd.notna(row.get('key_low')) else None,
        "n_low": row.get('n_low') if pd.notna(row.get('n_low')) else None,
        "n_high": row.get('n_high') if pd.notna(row.get('n_high')) else None,
        "rally_high": row.get('rally_high') if pd.notna(row.get('rally_high')) else None,
        "rally_low": row.get('rally_low') if pd.notna(row.get('rally_low')) else None,
        "secondary_low": row.get('secondary_low') if pd.notna(row.get('secondary_low')) else None,
        "secondary_high": row.get('secondary_high') if pd.notna(row.get('secondary_high')) else None,
        "break_low": row.get('break_low') if pd.notna(row.get('break_low')) else None,
        "break_high": row.get('break_high') if pd.notna(row.get('break_high')) else None,
    }

def regenerate_symbol(symbol):
    """为一个股票重新生成趋势历史CSV"""
    # 找到对应的数据文件
    data_files = [f for f in os.listdir(DATA_DIR) if f.startswith(f"{symbol}_") and f.endswith("_min1.csv")]
    if not data_files:
        print(f"[跳过] {symbol}: 无数据文件")
        return 0
    
    data_file = os.path.join(DATA_DIR, data_files[0])
    df = pd.read_csv(data_file)
    df['day'] = pd.to_datetime(df['day'])
    df = df.sort_values('day').reset_index(drop=True)
    
    stock_config = get_stock_config(symbol)
    if stock_config:
        print(f"[配置] {symbol}: trend={stock_config.get('trend')}, key_high={stock_config.get('key_high')}, key_low={stock_config.get('key_low')}")
    else:
        stock_config = {"trend": "up"}
        print(f"[警告] {symbol}: 无初始配置，使用默认up")
    
    state = init_state(stock_config)
    
    trend_records = []
    prev_trend = None
    prev_keypoint_value = None
    
    for _, row in df.iterrows():
        high = float(row["high"])
        low = float(row["low"])
        state = update_trend(state, high, low)
        
        current_trend = state["trend"]
        kp_name = TREND_KEYPOINT_MAP.get(current_trend, "")
        kp_value = state.get(kp_name) if kp_name else None
        
        day_str = str(row["day"])
        
        # 仅当趋势变化或关键点变化时记录
        if current_trend != prev_trend or kp_value != prev_keypoint_value:
            trend_records.append({
                "时间": day_str,
                "价格": row["close"],
                "趋势": current_trend,
                "趋势名称": TREND_NAMES.get(current_trend, ""),
                "关键点名称": kp_name,
                "关键点": kp_value,
            })
            prev_trend = current_trend
            prev_keypoint_value = kp_value
    
    trend_df = pd.DataFrame(trend_records)
    trend_file = os.path.join(OUTPUT_DIR, f"{symbol}_趋势历史.csv")
    trend_df.to_csv(trend_file, index=False, encoding="utf-8")
    print(f"[完成] {symbol}: {len(trend_df)} 条记录 (原始 {len(df)} 行)")
    return len(trend_records)

if __name__ == "__main__":
    # 获取所有已有的趋势历史文件
    existing = [f.replace("_趋势历史.csv", "") for f in os.listdir(OUTPUT_DIR) if f.endswith("_趋势历史.csv")]
    print(f"找到 {len(existing)} 个已有趋势历史文件: {existing}")
    
    total = 0
    for symbol in existing:
        n = regenerate_symbol(symbol)
        total += n
    
    print(f"\n全部完成！共生成 {total} 条记录")
