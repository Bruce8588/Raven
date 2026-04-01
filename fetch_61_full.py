#!/usr/bin/env python3
"""
获取61只股票的6年完整分钟数据 + 趋势分析
- 30并发线程
- 2020-2026完整分钟数据（分3大块取）
- 保存到小黑盒
- 更新 initial_configs.csv
"""
import os
import sys
import time
import pandas as pd
import requests
import threading
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_DIR = "/Users/isenfengming/Desktop/Raven"
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "core"))

from core.config.rules import *

# ========== 小黑盒路径 ==========
MIN_DATA_DIR = "/Volumes/小黑盒/量化文件/数据库/分钟数据"
TREND_DIR = "/Volumes/小黑盒/量化文件/数据库/趋势分析结果"
OUTPUT_CSV = os.path.join(BASE_DIR, "config/initial_configs.csv")
LOCK = threading.Lock()

os.makedirs(MIN_DATA_DIR, exist_ok=True)
os.makedirs(TREND_DIR, exist_ok=True)

# ========== 61只股票列表 ==========
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

# ========== iFind API ==========
REFRESH_TOKEN = "eyJzaWduX3RpbWUiOiIyMDI2LTAzLTMxIDIxOjQ1OjE2In0=.eyJ1aWQiOiI4NTU2ODc3MDciLCJ1c2VyIjp7InJlZnJlc2hUb2tlbkV4cGlyZWRUaW1lIjoiMjAyNi0wNC0yMyAxOTo0MDoyMCIsInVzZXJJZCI6Ijg1NTY4NzcwNyJ9fQ==.D915427AA3B512500675EF4A6ADF97B1F545D98C7089C016F8D16D514A8F4ADA"
TOKEN_URL = "https://quantapi.51ifind.com/api/v1/get_access_token"
HIGH_FREQ_URL = "https://quantapi.51ifind.com/api/v1/high_frequency"

# 全局共享token（线程安全）
_global_token = {"token": None, "expire": None, "lock": threading.Lock()}


def get_access_token():
    """获取access_token（全局共享，自动刷新）"""
    with _global_token["lock"]:
        if _global_token["token"] and _global_token["expire"]:
            if datetime.now() < _global_token["expire"]:
                return _global_token["token"]
    headers = {"Content-Type": "application/json", "refresh_token": REFRESH_TOKEN}
    try:
        response = requests.post(TOKEN_URL, headers=headers, timeout=30)
        result = response.json()
        if result.get("errorcode") == 0:
            token = result["data"]["access_token"]
            with _global_token["lock"]:
                _global_token["token"] = token
                _global_token["expire"] = datetime.now() + timedelta(days=7)
            return token
    except Exception:
        pass
    return None


def fetch_chunk(code_ifind, start_time, end_time):
    """获取指定时间范围的数据"""
    token = get_access_token()
    if not token:
        return pd.DataFrame()

    data = {
        "codes": code_ifind,
        "indicators": "high,low,close",
        "starttime": start_time.strftime("%Y-%m-%d 09:15:00"),
        "endtime": end_time.strftime("%Y-%m-%d 15:15:00"),
        "functionpara": {"Interval": "1", "Fill": "Original"}
    }
    headers = {"Content-Type": "application/json", "access_token": token}

    try:
        response = requests.post(HIGH_FREQ_URL, json=data, headers=headers, timeout=300)
        result = response.json()
        if result.get("errorcode") == 0 and result.get("tables"):
            table = result["tables"][0]
            time_list = table.get("time", [])
            table_data = table.get("table", {})
            if not time_list:
                return pd.DataFrame()
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
                return pd.DataFrame()
            df["day"] = pd.to_datetime(df["day"])
            df = df[(df["day"].dt.hour < 15) |
                    ((df["day"].dt.hour == 14) & (df["day"].dt.minute <= 57))]
            return df
        elif "token" in str(result.get('errmsg', '')).lower():
            with _global_token["lock"]:
                _global_token["token"] = None
    except Exception:
        pass
    return pd.DataFrame()


def get_full_data_2020_2026(code_ifind):
    """获取2020-2026完整数据（分3大块取）"""
    chunks = []
    # 分3大块：2020-2021, 2022-2023, 2024-2026
    ranges = [
        (datetime(2020, 1, 1), datetime(2021, 12, 31)),
        (datetime(2022, 1, 1), datetime(2023, 12, 31)),
        (datetime(2024, 1, 1), datetime(2026, 4, 1)),
    ]
    for start, end in ranges:
        df = fetch_chunk(code_ifind, start, end)
        if df is not None and not df.empty:
            chunks.append(df)
        time.sleep(0.3)

    if not chunks:
        return pd.DataFrame()
    result = pd.concat(chunks, ignore_index=True)
    result = result.drop_duplicates(subset=["day"], keep="first")
    result = result.sort_values("day").reset_index(drop=True)
    return result


# ========== 趋势分析（从core/trend.py） ==========
def init_state(stock_info):
    trend = stock_info.get("trend", "up")
    return {
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


def update_trend(state, high, low):
    t = state
    trend = t["trend"]
    kh, kl = t["key_high"], t["key_low"]
    nl, nh = t["n_low"], t["n_high"]
    rh, rl = t["rally_high"], t["rally_low"]
    sl, sh = t["secondary_low"], t["secondary_high"]
    bl, bh = t["break_low"], t["break_high"]
    rt = t.get("rally_triggered", False)
    nt = trend

    if trend == "up":
        if high is not None and (kh is None or high > kh):
            kh = high
        if kh is not None and low is not None and low < kh * PULLBACK_THRESHOLD:
            nl = low
            nt = "up_natural"
    elif trend == "up_natural":
        if nl is not None and low is not None and low < nl:
            nl = low
        if nl is not None and high is not None and high > nl * RALLY_THRESHOLD:
            rh = high
            rt = True
            nt = "up_rally"
    elif trend == "up_rally":
        if rh is not None and high is not None and high > rh:
            rh = high
        if rt and nl is not None and low is not None and low < nl:
            sl = nl
            nt = "up_secondary"
        elif rh is not None and nl is not None and low is not None and low < rh * PULLBACK_THRESHOLD and low >= nl:
            sl = low
            nt = "up_secondary"
        elif rh is not None and high is not None and high > rh and (kh is None or high < kh):
            rh = high
        elif high is not None and (kh is None or high > kh):
            kh = high
            nt = "up"
    elif trend == "up_secondary":
        if sl is not None and low is not None and low < sl and (nl is None or low > nl):
            sl = low
        elif sl is not None and rh is not None and high is not None and high > sl and high < rh:
            pass
        elif sl is not None and rh is not None and high is not None and high > sl and high > rh:
            rh = high
            nt = "up_rally"
        elif sl is not None and nl is not None and low is not None and low < sl and low < nl:
            bl = nl
            nt = "up_break"
    elif trend == "up_break":
        if bl is not None and low is not None and low < bl and (nl is None or low > nl * 0.97):
            bl = low
        elif bl is not None and nl is not None and low is not None and low < bl and low < nl * 0.97:
            kl = low
            nt = "down"
        elif bl is not None and high is not None and high > bl * 1.06:
            rh = high
            nl = bl
            nt = "up_rally"
    elif trend == "down":
        if low is not None and (kl is None or low < kl):
            kl = low
        if kl is not None and high is not None and high > kl * RALLY_THRESHOLD:
            nh = high
            nt = "down_natural"
    elif trend == "down_natural":
        if high is not None and (nh is None or high > nh):
            nh = high
        if nh is not None and low is not None and low < nh * PULLBACK_THRESHOLD:
            rl = low
            sh = low
            nt = "down_rally"
    elif trend == "down_rally":
        if rl is not None and high is not None and high > rl * RALLY_THRESHOLD:
            sh = high
            nt = "down_secondary"
        elif rl is not None and low is not None and low < rl and (kl is None or low >= kl):
            rl = low
        elif kl is not None and low is not None and low < kl:
            nt = "down"
    elif trend == "down_secondary":
        if sh is not None and high is not None and high > sh and (nh is None or high < nh):
            sh = high
        elif sh is not None and nh is not None and high is not None and high > sh and high > nh:
            bh = high
            nt = "down_break"
        elif sh is not None and rl is not None and low is not None and low < sh and low > rl:
            pass
        elif sh is not None and rl is not None and low is not None and low < sh and low < rl:
            nt = "down_rally"
    elif trend == "down_break":
        if bh is not None and high is not None and high > bh and (nh is None or high < nh * 1.03):
            bh = high
        elif bh is not None and nh is not None and high is not None and high > bh and high > nh * 1.03:
            kh = high
            nl = None
            rh = None
            sl = None
            rt = False
            nt = "up"
        elif bh is not None and low is not None and low < bh * 0.94:
            rl = low
            nt = "down_rally"

    t["trend"] = nt
    t["key_high"] = kh
    t["key_low"] = kl
    t["n_low"] = nl
    t["n_high"] = nh
    t["rally_high"] = rh
    t["rally_low"] = rl
    t["secondary_low"] = sl
    t["secondary_high"] = sh
    t["break_low"] = bl
    t["break_high"] = bh
    t["rally_triggered"] = rt
    return t


def analyze_df(df, initial_trend="up"):
    """对DataFrame进行趋势分析"""
    state = init_state({"trend": initial_trend})
    records = []
    for _, row in df.iterrows():
        state = update_trend(state, float(row["high"]), float(row["low"]))
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
    return pd.DataFrame(records)


# ========== 单只股票处理函数 ==========
def process_stock(code, market, name):
    """处理单只股票：获取数据 + 分析 + 保存"""
    start_time = time.time()
    stock_code = f"{code}{market}"
    code_ifind = f"{code}.{'SZ' if market == 'SZ' else 'SH'}"
    min_file = os.path.join(MIN_DATA_DIR, f"{stock_code}_min1.csv")
    trend_file = os.path.join(TREND_DIR, f"{stock_code}_趋势判断.csv")

    try:
        # 1. 获取完整数据
        print(f"  [开始] {stock_code} {name}...", flush=True)
        df = get_full_data_2020_2026(code_ifind)

        if df is None or df.empty:
            print(f"  [失败] {stock_code} {name}: 无法获取数据", flush=True)
            return None

        print(f"  [获取] {stock_code} {name}: {len(df)} 条数据", flush=True)

        # 2. 保存分钟数据
        df.to_csv(min_file, index=False, encoding="utf-8")

        # 3. 趋势分析
        trend_df = analyze_df(df)
        trend_df.to_csv(trend_file, index=False, encoding="utf-8")

        # 4. 构建结果
        latest = df.iloc[-1]
        final = trend_df.iloc[-1]
        result = {
            "股票代码": stock_code,
            "最新时间": str(latest["day"]),
            "当前价格": float(latest["close"]),
            "趋势代码": final["趋势代码"],
            "趋势名称": final["趋势名称"],
            "key_high": final["key_high"],
            "key_low": final["key_low"],
            "n_low": final["n_low"],
            "n_high": final["n_high"],
            "rally_high": final["rally_high"],
            "rally_low": final["rally_low"],
            "secondary_low": final["secondary_low"],
            "secondary_high": final["secondary_high"],
            "break_low": final["break_low"],
            "break_high": final["break_high"],
        }

        elapsed = time.time() - start_time
        print(f"  [完成] {stock_code} {name}: {final['趋势名称']} | 价格={latest['close']} | {len(df)}条 | {elapsed:.1f}s", flush=True)
        return result

    except Exception as e:
        elapsed = time.time() - start_time
        print(f"  [异常] {stock_code} {name}: {e} | {elapsed:.1f}s", flush=True)
        import traceback
        traceback.print_exc()
        return None


def write_config(result):
    """线程安全地追加/更新结果到initial_configs.csv"""
    if result is None:
        return
    with LOCK:
        df_new = pd.DataFrame([result])
        if os.path.exists(OUTPUT_CSV):
            df_existing = pd.read_csv(OUTPUT_CSV)
            mask = df_existing["股票代码"] == result["股票代码"]
            if mask.any():
                df_existing = df_existing[~mask]
            df_combined = pd.concat([df_existing, df_new], ignore_index=True)
        else:
            df_combined = df_new
        df_combined.to_csv(OUTPUT_CSV, index=False, encoding="utf-8")


def main():
    overall_start = time.time()
    print(f"{'='*60}")
    print(f"开始处理 {len(STOCKS)} 只股票 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}", flush=True)

    successes = []
    failures = []

    # 先初始化token
    get_access_token()
    print(f"[初始化] Token获取成功", flush=True)

    with ThreadPoolExecutor(max_workers=30) as executor:
        futures = {
            executor.submit(process_stock, code, market, name): (code, name)
            for code, market, name in STOCKS
        }
        for future in as_completed(futures):
            code, name = futures[future]
            try:
                result = future.result()
                if result is not None:
                    successes.append((code, name))
                    write_config(result)
                else:
                    failures.append((code, name))
            except Exception as e:
                failures.append((code, name))
                print(f"  [异常] {code} {name}: {e}", flush=True)

    overall_elapsed = time.time() - overall_start

    print(f"\n{'='*60}")
    print(f"处理完成！")
    print(f"成功: {len(successes)}/{len(STOCKS)}")
    print(f"失败: {len(failures)}/{len(STOCKS)}")
    print(f"总耗时: {overall_elapsed:.1f}秒 ({overall_elapsed/60:.1f}分钟)")
    if failures:
        print(f"失败列表:")
        for code, name in failures:
            print(f"  - {code} {name}")
    print(f"{'='*60}", flush=True)

    return len(successes), len(failures), overall_elapsed


if __name__ == "__main__":
    main()
