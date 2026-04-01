#!/usr/bin/env python3
"""
多线程处理61只缺失股票：获取分钟数据 + 趋势分析 + 追加到initial_configs.csv
"""
import os
import sys
import time
import pandas as pd
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# 配置路径
BASE_DIR = "/Users/isenfengming/Desktop/Raven"
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_CSV = os.path.join(BASE_DIR, "config/initial_configs.csv")
LOCK = threading.Lock()

# 61只股票列表（从缺失股票文件读取）
STOCKS = [
    ("000001", "SZ", "平安银行"),
    ("000002", "SZ", "万科A"),
    ("000045", "SZ", "深纺织A"),
    ("000049", "SZ", "德赛电池"),
    ("000055", "SZ", "方大集团"),
    ("000060", "SZ", "中金岭南"),
    ("000062", "SZ", "深圳华强"),
    ("000063", "SZ", "中兴通讯"),
    ("000065", "SZ", "北方国际"),
    ("000066", "SZ", "中国长城"),
    ("000100", "SZ", "TCL科技"),
    ("000155", "SZ", "川能动力"),
    ("000650", "SZ", "仁和药业"),
    ("000651", "SZ", "格力电器"),
    ("000657", "SZ", "中钨高新"),
    ("000661", "SZ", "长春高新"),
    ("000672", "SZ", "上峰水泥"),
    ("000681", "SZ", "视觉中国"),
    ("000682", "SZ", "东方电子"),
    ("000705", "SZ", "浙江震元"),
    ("000719", "SZ", "中原传媒"),
    ("000725", "SZ", "京东方A"),
    ("000726", "SZ", "鲁泰A"),
    ("000728", "SZ", "国元证券"),
    ("000751", "SZ", "锌业股份"),
    ("000759", "SZ", "中百集团"),
    ("000768", "SZ", "中航西飞"),
    ("000776", "SZ", "广发证券"),
    ("000783", "SZ", "长江证券"),
    ("000786", "SZ", "北新建材"),
    ("000799", "SZ", "酒鬼酒"),
    ("000807", "SZ", "云铝股份"),
    ("000831", "SZ", "中国稀土"),
    ("000848", "SZ", "承德露露"),
    ("000858", "SZ", "五粮液"),
    ("000862", "SZ", "银星能源"),
    ("000876", "SZ", "新希望"),
    ("000877", "SZ", "天山股份"),
    ("000878", "SZ", "云南铜业"),
    ("000880", "SZ", "潍柴重机"),
    ("000890", "SZ", "法尔胜"),
    ("000892", "SZ", "欢瑞世纪"),
    ("000893", "SZ", "亚钾国际"),
    ("000895", "SZ", "双汇发展"),
    ("000899", "SZ", "赣能股份"),
    ("000921", "SZ", "海信家电"),
    ("000930", "SZ", "中粮科技"),
    ("000932", "SZ", "华菱钢铁"),
    ("000933", "SZ", "神火股份"),
    ("003000", "SZ", "劲仔食品"),
    ("003006", "SZ", "百亚股份"),
    ("003012", "SZ", "东鹏控股"),
    ("003015", "SZ", "日久光电"),
    ("605011", "SH", "杭州热电"),
    ("605337", "SH", "李子园"),
    ("605338", "SH", "巴比食品"),
    ("605378", "SH", "野马电池"),
    ("605488", "SH", "福莱新材"),
    ("605499", "SH", "东鹏饮料"),
    ("605598", "SH", "上海港湾"),
    ("605599", "SH", "菜百股份"),
]

sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "core"))
from core.config.rules import *

# ============ iFind fetcher ============
import requests

REFRESH_TOKEN = "eyJzaWduX3RpbWUiOiIyMDI2LTAzLTMxIDIwOjEzOjUyIn0=.eyJ1aWQiOiI4NTU2ODc3MDciLCJ1c2VyIjp7InJlZnJlc2hUb2tlbkV4cGlyZWRUaW1lIjoiMjAyNi0wNC0yMyAxOTo0MDoyMCIsInVzZXJJZCI6Ijg1NTY4NzcwNyJ9fQ==.7FAC158C8BB57B374681C467906414F4824BE722510803665FC5C977CB91BC62"
TOKEN_URL = "https://quantapi.51ifind.com/api/v1/get_access_token"
HIGH_FREQ_URL = "https://quantapi.51ifind.com/api/v1/high_frequency"

class IFinDFetcher:
    def __init__(self):
        self.access_token = None
        self.token_expire_time = None
    
    def _get_access_token(self):
        if self.access_token and self.token_expire_time:
            if datetime.now() < self.token_expire_time:
                return self.access_token
        headers = {"Content-Type": "application/json", "refresh_token": REFRESH_TOKEN}
        try:
            response = requests.post(TOKEN_URL, headers=headers, timeout=30)
            result = response.json()
            if result.get("errorcode") == 0:
                self.access_token = result["data"]["access_token"]
                self.token_expire_time = datetime.now() + timedelta(days=7)
                return self.access_token
            else:
                print(f"  获取access_token失败: {result.get('errmsg')}")
                return None
        except Exception as e:
            print(f"  请求access_token失败: {e}")
            return None

    def get_minute_data(self, code_ifind, days=7):
        if not self.access_token:
            self._get_access_token()
        if not self.access_token:
            return None

        end_time = datetime.now()
        start_time = end_time - timedelta(days=days)

        data = {
            "codes": code_ifind,
            "indicators": "high,low,close",
            "starttime": start_time.strftime("%Y-%m-%d 09:15:00"),
            "endtime": end_time.strftime("%Y-%m-%d 15:15:00"),
            "functionpara": {"Interval": "1", "Fill": "Original"}
        }

        headers = {"Content-Type": "application/json", "access_token": self.access_token}

        try:
            response = requests.post(HIGH_FREQ_URL, json=data, headers=headers, timeout=120)
            result = response.json()
            
            if result.get("errorcode") == 0 and result.get("tables"):
                table = result["tables"][0]
                time_list = table.get("time", [])
                table_data = table.get("table", {})
                
                if not time_list:
                    return None
                
                n = len(time_list)
                row_data = {"day": time_list}
                for field in ("high", "low", "close"):
                    arr = table_data.get(field, [])
                    if not isinstance(arr, list):
                        arr = []
                    row_data[field] = arr[:n] if len(arr) != n else arr
                
                df = pd.DataFrame(row_data)
                df = df.dropna(subset=["high", "low", "close"])
                if df.empty:
                    return None
                df["day"] = pd.to_datetime(df["day"])
                df = df[(df["day"].dt.hour < 15) | 
                        ((df["day"].dt.hour == 14) & (df["day"].dt.minute <= 57))]
                return df
            else:
                if "token" in str(result.get('errmsg', '')).lower():
                    self.access_token = None
                    return self.get_minute_data(code_ifind, days)
                return None
        except Exception as e:
            return None

# ============ 趋势分析函数（从trend.py提取） ============
def init_state(stock_info):
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
        "rally_triggered": False,
    }
    return state

def update_trend(state, high, low):
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

    if trend == "up":
        if high is not None and (key_high is None or high > key_high):
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
        if rally_triggered and n_low is not None and low is not None and low < n_low:
            secondary_low = n_low
            new_trend = "up_secondary"
        elif rally_high is not None and n_low is not None and low is not None and low < rally_high * PULLBACK_THRESHOLD and low >= n_low:
            secondary_low = low
            new_trend = "up_secondary"
        elif rally_high is not None and high is not None and high > rally_high and (key_high is None or high < key_high):
            rally_high = high
        elif high is not None and (key_high is None or high > key_high):
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

    elif trend == "down":
        if low is not None and (key_low is None or low < key_low):
            key_low = low
        if key_low is not None and high is not None and high > key_low * RALLY_THRESHOLD:
            n_high = high
            new_trend = "down_natural"

    elif trend == "down_natural":
        if high is not None and (n_high is None or high > n_high):
            n_high = high
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
            n_low = None
            rally_high = None
            secondary_low = None
            rally_triggered = False
            new_trend = "up"
        elif break_high is not None and low is not None and low < break_high * 0.94:
            rally_low = low
            new_trend = "down_rally"

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

def analyze_df(df, initial_trend="up"):
    """对DataFrame进行趋势分析，返回最终状态"""
    state = init_state({"trend": initial_trend})
    for _, row in df.iterrows():
        high = float(row["high"])
        low = float(row["low"])
        state = update_trend(state, high, low)
    return state

# ============ 单只股票处理函数 ============
def process_stock(code, market, name):
    """处理单只股票：获取数据 + 分析 + 返回结果"""
    start_time = time.time()
    try:
        # 构造iFind代码
        code_ifind = f"{code}.{'SZ' if market == 'SZ' else 'SH'}"
        
        # 构造数据文件路径
        if market == "SH":
            symbol_prefix = f"sh{code}"
        else:
            symbol_prefix = code
        
        db_file = os.path.join(DATA_DIR, f"{symbol_prefix}_{code}_min1.csv")
        
        # 优先读取本地CSV数据
        df = None
        if os.path.exists(db_file):
            try:
                df = pd.read_csv(db_file)
                df["day"] = pd.to_datetime(df["day"])
                df = df.sort_values("day").reset_index(drop=True)
                print(f"  [本地] {code} {name}: {len(df)} 条数据")
            except Exception as e:
                print(f"  [本地] {code} 读取失败: {e}")
                df = None
        
        # 如果本地没有数据，从iFind获取最近7天数据
        if df is None or len(df) == 0:
            fetcher = IFinDFetcher()
            df = fetcher.get_minute_data(code_ifind, days=7)
            if df is not None:
                print(f"  [iFind] {code} {name}: {len(df)} 条数据")
                # 保存到本地
                if market == "SH":
                    save_file = os.path.join(DATA_DIR, f"sh{code}_{code}_min1.csv")
                else:
                    save_file = os.path.join(DATA_DIR, f"{code}_{code}_min1.csv")
                df.to_csv(save_file, index=False, encoding="utf-8")
            else:
                print(f"  [失败] {code} {name}: 无法获取数据")
                return None
        
        if df is None or len(df) == 0:
            print(f"  [失败] {code} {name}: 无有效数据")
            return None
        
        # 分析趋势
        state = analyze_df(df)
        
        # 获取最新一条数据
        latest = df.iloc[-1]
        latest_time = latest["day"]
        latest_price = float(latest["close"])
        
        elapsed = time.time() - start_time
        
        result = {
            "股票代码": f"{code}{market}",
            "最新时间": str(latest_time),
            "当前价格": latest_price,
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
            "elapsed": elapsed,
        }
        
        print(f"  [完成] {code} {name}: {state['trend']} ({TREND_NAMES.get(state['trend'])}) | 价格={latest_price} | 耗时={elapsed:.2f}s")
        return result
        
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"  [异常] {code} {name}: {e} | 耗时={elapsed:.2f}s")
        return None

def write_result(result):
    """线程安全地追加结果到CSV"""
    if result is None:
        return
    with LOCK:
        df_new = pd.DataFrame([result])
        # 删除耗时列
        df_new = df_new.drop(columns=["elapsed"])
        
        if os.path.exists(OUTPUT_CSV):
            df_existing = pd.read_csv(OUTPUT_CSV)
            # 检查是否已存在
            existing_mask = df_existing["股票代码"] == result["股票代码"]
            if existing_mask.any():
                df_existing = df_existing[~existing_mask]
            df_combined = pd.concat([df_existing, df_new], ignore_index=True)
            df_combined.to_csv(OUTPUT_CSV, index=False, encoding="utf-8")
        else:
            df_new.to_csv(OUTPUT_CSV, index=False, encoding="utf-8")

def main():
    print(f"=" * 60)
    print(f"开始处理 {len(STOCKS)} 只股票 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"=" * 60)
    
    overall_start = time.time()
    results = []
    failures = []
    successes = []
    
    # 多线程执行，15个线程
    with ThreadPoolExecutor(max_workers=15) as executor:
        futures = {executor.submit(process_stock, code, market, name): (code, name) 
                   for code, market, name in STOCKS}
        
        for future in as_completed(futures):
            code, name = futures[future]
            try:
                result = future.result()
                if result is not None:
                    successes.append((code, name))
                    # 立即写入CSV
                    write_result(result)
                    results.append(result)
                else:
                    failures.append((code, name))
            except Exception as e:
                failures.append((code, name))
                print(f"  [异常] {code} {name}: {e}")
    
    overall_elapsed = time.time() - overall_start
    
    print(f"\n{'=' * 60}")
    print(f"处理完成！| 耗时: {overall_elapsed:.1f}秒")
    print(f"成功: {len(successes)}/{len(STOCKS)}")
    print(f"失败: {len(failures)}/{len(STOCKS)}")
    if failures:
        print(f"失败列表:")
        for code, name in failures:
            print(f"  - {code} {name}")
    print(f"{'=' * 60}")
    
    return results, failures

if __name__ == "__main__":
    main()
