#!/usr/bin/env python3
"""
Raven 网页界面 - Flask 服务器
"""
import os
import sys
import json
import glob
import math
import threading
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify
import pandas as pd

# 添加项目根目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False

# 尝试导入配置
try:
    from config.stocks import ALL_STOCKS
except ImportError:
    ALL_STOCKS = {}

# 导入缓存模块
from cache import StockCache
stock_cache = StockCache()

# 导入后台更新模块
from background_updater import BackgroundUpdater, start_background_updater, stop_background_updater

# 输出目录
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
WATCHLIST_PATH = os.path.join(BASE_DIR, "config", "watchlist.json")
SETTINGS_PATH = os.path.join(BASE_DIR, "config", "settings.json")

# iFinD API 配置
TOKEN_URL = "https://quantapi.51ifind.com/api/v1/get_access_token"


def load_watchlist():
    """加载自选股"""
    if os.path.exists(WATCHLIST_PATH):
        with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _load_stocks_mapping():
    """加载股票名称-代码映射表"""
    # 优先使用全市场映射表（3473只）
    mapping_path = os.path.join(BASE_DIR, "config", "stocks_name_mapping_full.json")
    if os.path.exists(mapping_path):
        with open(mapping_path, "r", encoding="utf-8") as f:
            return json.load(f)
    # 回退到旧映射表（81只）
    mapping_path = os.path.join(BASE_DIR, "config", "stocks_name_mapping.json")
    if os.path.exists(mapping_path):
        with open(mapping_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def get_latest_trend_csv():
    """获取最新的趋势CSV文件"""
    pattern = os.path.join(OUTPUT_DIR, "趋势追踪_*.csv")
    files = glob.glob(pattern)
    if not files:
        return None
    latest = max(files, key=os.path.getmtime)
    return latest


def _get_current_trend_from_csv(symbol: str, info: dict) -> dict | None:
    """
    从 output/趋势判断/{symbol}_趋势判断.csv 读取当前趋势数据。
    返回 dict 包含 trend_code, trend_name, key_*, n_*, rally_*, secondary_* 等字段。
    如果 CSV 不存在或为空则返回 None（此时应使用 cache 作为备用）。
    """
    trend_csv_path = os.path.join(OUTPUT_DIR, "趋势判断", f"{symbol}_趋势判断.csv")
    if not os.path.exists(trend_csv_path):
        return None
    try:
        df = pd.read_csv(trend_csv_path)
        if df.empty:
            return None
        # 取最后一行（最新记录）
        row = df.iloc[-1]
        return {
            "trend_code": str(row.get("趋势代码", "")) if pd.notna(row.get("趋势代码")) else "",
            "trend_name": str(row.get("趋势名称", "")) if pd.notna(row.get("趋势名称")) else "",
            "key_high": float(row["key_high"]) if pd.notna(row.get("key_high")) else None,
            "key_low": float(row["key_low"]) if pd.notna(row.get("key_low")) else None,
            "n_low": float(row["n_low"]) if pd.notna(row.get("n_low")) else None,
            "n_high": float(row["n_high"]) if pd.notna(row.get("n_high")) else None,
            "rally_high": float(row["rally_high"]) if pd.notna(row.get("rally_high")) else None,
            "rally_low": float(row["rally_low"]) if pd.notna(row.get("rally_low")) else None,
            "secondary_low": float(row["secondary_low"]) if pd.notna(row.get("secondary_low")) else None,
            "secondary_high": float(row["secondary_high"]) if pd.notna(row.get("secondary_high")) else None,
            "update_time": str(row.get("更新时间", "")) if pd.notna(row.get("更新时间")) else "",
        }
    except Exception as e:
        print(f"[_get_current_trend_from_csv] 读取 {symbol} 趋势CSV失败: {e}")
        return None


def load_all_trends():
    """加载所有股票趋势数据"""
    csv_path = get_latest_trend_csv()
    if not csv_path or not os.path.exists(csv_path):
        return []

    try:
        df = pd.read_csv(csv_path)
        # 按时间降序，只取每个股票最新一条
        df['时间_dt'] = pd.to_datetime(df['时间'])
        df = df.sort_values('时间_dt', ascending=False)
        # 去重，每个股票只保留最新一条
        df = df.drop_duplicates(subset=['股票代码'], keep='first')
        return df.to_dict('records')
    except Exception as e:
        print(f"加载趋势数据失败: {e}")
        return []


def get_trend_description(trend_code, price, record):
    """生成趋势解读（不含关键点代号）"""
    if trend_code == "up":
        return "价格处于上升趋势，等待回调后买入机会"
    elif trend_code == "up_natural":
        return "自然回撤中，关注是否止跌"
    elif trend_code == "up_rally":
        return "回升阶段，关注能否突破"
    elif trend_code == "up_secondary":
        return "次级回撤中，等待回升信号"
    elif trend_code == "up_break":
        return "关键支撑已破，注意风险"
    elif trend_code == "down":
        return "下跌趋势，等待止跌信号"
    elif trend_code == "down_natural":
        return "自然回升中，关注是否突破"
    elif trend_code == "down_rally":
        return "回撤阶段，注意风险"
    elif trend_code == "down_secondary":
        return "次级回升中，关注能否突破"
    elif trend_code == "down_break":
        return "突破关键阻力，趋势可能反转"
    return ""


def get_signal(trend_code):
    """根据趋势代码返回信号标签
    上升体系：上升/自然回撤/回升/次级回撤 → 红色
    上升破碎 → 黑色
    下跌体系：下跌/自然回升/回撤/次级回升 → 绿色
    下跌破碎 → 橙色
    """
    signals = {
        # 上升体系（红色系）
        "up": {"text": "买入信号", "color": "#dc2626"},           # 深红
        "up_natural": {"text": "卖出信号", "color": "#dc2626"},   # 深红
        "up_rally": {"text": "关注突破", "color": "#dc2626"},    # 深红
        "up_secondary": {"text": "等待回升", "color": "#dc2626"}, # 深红
        "up_break": {"text": "注意风险", "color": "#000000"},      # 黑色
        
        # 下跌体系（绿色系）
        "down": {"text": "下跌趋势", "color": "#16a34a"},         # 深绿
        "down_natural": {"text": "回升中", "color": "#16a34a"},   # 深绿
        "down_rally": {"text": "回撤风险", "color": "#16a34a"},  # 深绿
        "down_secondary": {"text": "关注突破", "color": "#16a34a"}, # 深绿
        "down_break": {"text": "趋势反转", "color": "#f97316"},   # 橙色
    }
    return signals.get(trend_code, {"text": "未知", "color": "#999"})


def clean_nan(obj):
    """递归清理 dict/list 中的 NaN，替换为 None"""
    if isinstance(obj, dict):
        return {k: clean_nan(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_nan(v) for v in obj]
    elif isinstance(obj, float) and math.isnan(obj):
        return None
    return obj


def _fetch_stock_unknown(stock_name: str) -> dict | None:
    """
    尝试从iFind获取未知股票（不在自选股名单中）
    stock_name: 可能是股票名称或代码
    返回分析后的数据字典，失败返回None
    """
    try:
        from fetcher.ifind import IFinDFetcher
        from core.analyzer import MarketTrendAnalyzer
        from core.config.rules import TREND_NAMES
        
        # 检查是否像股票代码（6位数字）
        is_code = stock_name.isdigit() and len(stock_name) == 6
        
        # 先尝试按名称查找（从映射表）
        actual_name = stock_name  # 保存原始输入的名称
        market_from_mapping = None  # 从映射表获取的market
        if not is_code:
            stocks_mapping = _load_stocks_mapping()
            for code, info in stocks_mapping.items():
                name = info.get("name", "")
                if stock_name == name or stock_name in name or name in stock_name:
                    # 找到匹配的股票，按代码处理
                    is_code = True
                    stock_name = code  # 用代码继续
                    actual_name = name  # 保存实际名称
                    market_from_mapping = info.get("market")  # 保存market
                    print(f"[DEBUG] Found in mapping: code={stock_name}, market={market_from_mapping}, name={actual_name}")
                    break
        
        print(f"[DEBUG] After mapping lookup: is_code={is_code}, stock_name={stock_name}, market_from_mapping={market_from_mapping}")
        
        if is_code:
            code = stock_name
            # 确定要尝试的市场列表（优先使用映射表的market，但也尝试另一个）
            if market_from_mapping:
                other = "SZ" if market_from_mapping == "SH" else "SH"
                market_list = [(market_from_mapping, f".{market_from_mapping}"), (other, f".{other}")]
            else:
                market_list = [("SH", ".SH"), ("SZ", ".SZ")]
            
            for market_name, suffix in market_list:
                try:
                    fetcher = IFinDFetcher()
                    df = fetcher.get_minute_data(f"{code}{suffix}", days=7)
                    if df is not None and len(df) > 0:
                        # 保存数据
                        db_dir = os.path.join(BASE_DIR, "data")
                        os.makedirs(db_dir, exist_ok=True)
                        df.to_csv(os.path.join(db_dir, f"unknown_{code}_min1.csv"), index=False, encoding="utf-8")
                        
                        # 分析趋势
                        config_path = os.path.join(BASE_DIR, "config", "initial_configs.csv")
                        analyzer = MarketTrendAnalyzer(config_path)
                        analyzer_symbol = f"sh{code}" if market_name == "SH" else f"sz{code}"
                        result = analyzer.update_trend(analyzer_symbol, float(df.iloc[-1]["close"]))
                        
                        if result:
                            trend_code = result.get("trend", "")
                            signal = get_signal(trend_code)
                            return {
                                "symbol": f"{market_name.lower()}{code}",
                                "name": actual_name,
                                "code": code,
                                "market": market_name,
                                "price": float(df.iloc[-1]["close"]),
                                "trend_code": trend_code,
                                "trend_name": TREND_NAMES.get(trend_code, trend_code),
                                "signal_text": signal["text"],
                                "signal_color": signal["color"],
                                "key_high": result.get("key_high"),
                                "key_low": result.get("key_low"),
                                "n_high": result.get("n_high"),
                                "n_low": result.get("n_low"),
                                "rally_high": result.get("rally_high"),
                                "rally_low": result.get("rally_low"),
                                "secondary_high": result.get("secondary_high"),
                                "secondary_low": result.get("secondary_low"),
                                "description": get_trend_description(trend_code, float(df.iloc[-1]["close"]), result),
                                "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "from_cache": False,
                            }
                except Exception as e:
                    print(f"[未知股票] 尝试{market_name}{code}失败: {e}")
                    continue
        else:
            # 尝试作为股票名称搜索（从initial_configs中查找）
            config_path = os.path.join(BASE_DIR, "config", "initial_configs.csv")
            if os.path.exists(config_path):
                configs_df = pd.read_csv(config_path)
                # 模糊匹配名称
                for _, row in configs_df.iterrows():
                    cfg_name = str(row.get('股票代码', ''))  # 这里股票代码列其实是名称
                    # 更正：CSV里没有名称列，只有代码
                    pass
            
            # 如果是名称，尝试直接用代码方式获取
            return None
        
        return None
    except Exception as e:
        print(f"[未知股票] 获取失败: {e}")
        return None


def _fetch_stock_from_ifind(symbol: str, info: dict) -> dict | None:
    """
    从iFind获取单只股票数据并分析
    只分析配置时间点之后的数据
    使用完整的逐帧分析处理历史数据
    返回分析后的数据字典，失败返回None
    """
    try:
        from fetcher.ifind import IFinDFetcher
        from core.trend import TrendAnalyzer, init_state, update_trend
        from core.config.rules import TREND_NAMES
        
        code_raw = info.get("code", "")
        market = info.get("market", "")
        
        # 转换代码格式
        if market.upper() == "SZ":
            code_ifind = f"{code_raw}.SZ"
            config_code = f"{code_raw}SZ"  # e.g. "000333SZ"
        elif market.upper() == "SH":
            code_ifind = f"{code_raw}.SH"
            config_code = f"{code_raw}SH"  # e.g. "600089SH"
        else:
            code_ifind = code_raw
            config_code = code_raw
        
        # 获取该股票的配置时间点和初始状态
        config_time = None
        stock_config = {}
        config_path = os.path.join(BASE_DIR, "config", "initial_configs.csv")
        if os.path.exists(config_path):
            configs_df = pd.read_csv(config_path)
            config_row = configs_df[configs_df['股票代码'] == config_code]
            if not config_row.empty:
                row = config_row.iloc[0]
                config_time_str = row.get('最新时间')
                if config_time_str and pd.notna(config_time_str):
                    try:
                        config_time = pd.to_datetime(config_time_str)
                    except:
                        pass
                # 构建初始状态配置
                stock_config = {
                    "trend": row.get('趋势代码', 'up'),
                    "key_high": row.get('key_high'),
                    "key_low": row.get('key_low'),
                    "n_low": row.get('n_low'),
                    "n_high": row.get('n_high'),
                    "rally_high": row.get('rally_high'),
                    "rally_low": row.get('rally_low'),
                    "secondary_low": row.get('secondary_low'),
                    "secondary_high": row.get('secondary_high'),
                    "break_low": row.get('break_low'),
                    "break_high": row.get('break_high'),
                }
        
        fetcher = IFinDFetcher()
        df = fetcher.get_minute_data(code_ifind, days=7)
        
        if df is None or df.empty:
            return None
        
        # 过滤数据：只保留配置时间点之后的数据
        df['day'] = pd.to_datetime(df['day'])
        if config_time:
            df = df[df['day'] >= config_time]
            if df.empty:
                print(f"[查询] {info.get('name', symbol)} 在配置时间点后无数据")
                return None
        
        # 按时间排序
        df = df.sort_values("day").reset_index(drop=True)
        
        # 保存到CSV
        db_dir = os.path.join(BASE_DIR, "data")
        os.makedirs(db_dir, exist_ok=True)
        db_file = os.path.join(db_dir, f"{symbol}_{code_raw}_min1.csv")
        if os.path.exists(db_file):
            old_df = pd.read_csv(db_file)
            old_df["day"] = pd.to_datetime(old_df["day"])
            df = pd.concat([old_df, df], ignore_index=True)
            df = df.drop_duplicates(subset=["day"], keep="last")
            df = df.sort_values("day").reset_index(drop=True)
        df.to_csv(db_file, index=False, encoding="utf-8")
        
        # 使用逐帧分析处理历史数据
        state = init_state(stock_config) if stock_config else init_state({"trend": "up"})
        
        # 保存历史趋势记录（每行只记录一个趋势状态+一个关键点，仅在变化时记录）
        # 关键点映射：每个趋势对应的关键点字段名
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
        
        trend_records = []
        trend_judgment_records = []  # 每分钟一条分析记录
        prev_trend = None
        prev_keypoint_value = None
        prev_day = None
        
        for _, row in df.iterrows():
            high = float(row["high"])
            low = float(row["low"])
            state = update_trend(state, high, low)
            
            current_trend = state["trend"]
            kp_name = TREND_KEYPOINT_MAP.get(current_trend, "")
            kp_value = state.get(kp_name) if kp_name else None
            
            day_str = str(row["day"])
            
            # 趋势判断：每行都记录
            trend_judgment_records.append({
                "时间": day_str,
                "当前价格": row["close"],
                "趋势代码": current_trend,
                "趋势名称": TREND_NAMES.get(current_trend, ""),
                "key_high": state.get("key_high"),
                "key_low": state.get("key_low"),
                "n_low": state.get("n_low"),
                "n_high": state.get("n_high"),
                "rally_high": state.get("rally_high"),
                "rally_low": state.get("rally_low"),
                "secondary_low": state.get("secondary_low"),
                "secondary_high": state.get("secondary_high"),
                "break_low": state.get("break_low"),
                "break_high": state.get("break_high"),
            })
            
            # 仅当趋势变化或关键点变化时记录一行
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
                prev_day = day_str
        
        # 保存趋势历史到CSV（追加模式）
        output_dir = os.path.join(BASE_DIR, "output", "趋势历史")
        os.makedirs(output_dir, exist_ok=True)
        trend_df = pd.DataFrame(trend_records)
        trend_file = os.path.join(output_dir, f"{symbol}_趋势历史.csv")
        if os.path.exists(trend_file):
            existing_df = pd.read_csv(trend_file)
            existing_df["时间"] = pd.to_datetime(existing_df["时间"])
            trend_df["时间"] = pd.to_datetime(trend_df["时间"])
            trend_df = pd.concat([existing_df, trend_df], ignore_index=True)
            # 按时间、趋势、关键点三重去重，保留最后的记录
            # （同一时间同一趋势可能有不同关键点值变化，都应保留）
            trend_df = trend_df.drop_duplicates(subset=["时间", "趋势", "关键点名称"], keep="last")
            trend_df = trend_df.sort_values("时间").reset_index(drop=True)
        trend_df.to_csv(trend_file, index=False, encoding="utf-8")

        # 保存趋势判断到CSV（每条分析记录，追加模式）
        judgment_dir = os.path.join(BASE_DIR, "output", "趋势判断")
        os.makedirs(judgment_dir, exist_ok=True)
        judgment_df = pd.DataFrame(trend_judgment_records)
        judgment_file = os.path.join(judgment_dir, f"{symbol}_趋势判断.csv")
        if os.path.exists(judgment_file):
            existing_j = pd.read_csv(judgment_file)
            existing_j["时间"] = pd.to_datetime(existing_j["时间"])
            judgment_df["时间"] = pd.to_datetime(judgment_df["时间"])
            judgment_df = pd.concat([existing_j, judgment_df], ignore_index=True)
            judgment_df = judgment_df.drop_duplicates(subset=["时间"], keep="last")
            judgment_df = judgment_df.sort_values("时间").reset_index(drop=True)
        judgment_df.to_csv(judgment_file, index=False, encoding="utf-8")

        # 获取最终趋势
        trend_code = state["trend"]
        signal = get_signal(trend_code)
        current_price = float(df.iloc[-1]["close"])

        # 更新 initial_configs.csv（保存最新趋势状态）
        config_path = os.path.join(BASE_DIR, "config", "initial_configs.csv")
        latest_time = df.iloc[-1]["day"] if len(df) > 0 else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        new_row = {
            "股票代码": config_code,
            "最新时间": latest_time,
            "当前价格": current_price,
            "趋势代码": trend_code,
            "趋势名称": TREND_NAMES.get(trend_code, ""),
            "key_high": state.get("key_high"),
            "key_low": state.get("key_low"),
            "n_low": state.get("n_low"),
            "n_high": state.get("n_high"),
            "rally_high": state.get("rally_high"),
            "rally_low": state.get("rally_low"),
            "secondary_low": state.get("secondary_low"),
            "secondary_high": state.get("secondary_high"),
            "break_low": state.get("break_low"),
            "break_high": state.get("break_high"),
        }
        if os.path.exists(config_path):
            try:
                configs_df = pd.read_csv(config_path)
                # 更新已有行或追加新行
                mask = configs_df['股票代码'] == config_code
                if mask.any():
                    for col, val in new_row.items():
                        configs_df.loc[mask, col] = val
                else:
                    configs_df = pd.concat([configs_df, pd.DataFrame([new_row])], ignore_index=True)
                configs_df.to_csv(config_path, index=False, encoding="utf-8")
            except Exception as e:
                print(f"[配置表更新失败] {e}")
        else:
            # 创建新的配置表
            pd.DataFrame([new_row]).to_csv(config_path, index=False, encoding="utf-8")
        
        return {
            "name": info.get("name", symbol),
            "code": code_raw,
            "market": market,
            "price": current_price,
            "trend_code": trend_code,
            "trend_name": TREND_NAMES.get(trend_code, trend_code),
            "signal_text": signal["text"],
            "signal_color": signal["color"],
            "key_high": state.get("key_high"),
            "key_low": state.get("key_low"),
            "n_high": state.get("n_high"),
            "n_low": state.get("n_low"),
            "rally_high": state.get("rally_high"),
            "rally_low": state.get("rally_low"),
            "secondary_high": state.get("secondary_high"),
            "secondary_low": state.get("secondary_low"),
            "description": get_trend_description(trend_code, current_price, state),
            "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "config_time": config_time.strftime("%Y-%m-%d") if config_time else None,
        }
    except Exception as e:
        print(f"[查询] iFind获取失败: {e}")
        import traceback
        traceback.print_exc()
        return None


@app.route('/')
def index():
    """主页"""
    return render_template('index.html')


@app.route('/api/trends')
def api_trends():
    """获取所有股票趋势（展示全部自选股）"""
    from core.config.rules import TREND_NAMES
    watchlist = load_watchlist()
    cache_data = stock_cache.get_all()
    searched = set(stock_cache.get_searched())

    # 从 initial_configs.csv 读取上次记录的趋势状态（用于判断是否变化）
    prev_trend_map = {}
    config_path = os.path.join(BASE_DIR, "config", "initial_configs.csv")
    if os.path.exists(config_path):
        try:
            configs_df = pd.read_csv(config_path)
            for _, row in configs_df.iterrows():
                code = str(row.get('股票代码', ''))
                prev_trend_map[code] = {
                    '趋势代码': row.get('趋势代码', ''),
                    '当前价格': row.get('当前价格', 0),
                    '时间': str(row.get('最新时间', '')),
                }
        except Exception as e:
            print(f"[api/trends] 读取配置失败: {e}")

    result = []
    for symbol, info in watchlist.items():
        cache_record = cache_data.get(symbol, {})
        # 配置表格式: "002129SZ", 自选股symbol格式: "sh002129"
        # 需要转换为配置表格式才能正确匹配
        stock_code = info.get('code', '')
        market = info.get('market', '')
        config_key = f"{stock_code}{market}"  # e.g. "002129SZ"
        prev_config = prev_trend_map.get(config_key, {})

        # 优先从趋势判断CSV读取当前趋势数据
        csv_trend = _get_current_trend_from_csv(symbol, info)
        prev_trend = prev_config.get('趋势代码', '')

        if csv_trend and csv_trend.get('trend_code'):
            # CSV 存在且有数据，使用 CSV（趋势数据的唯一真实数据源）
            trend_code = csv_trend['trend_code']
            signal = get_signal(trend_code)
            curr_trend = trend_code
            changed = curr_trend != prev_trend and prev_trend != ''
            result.append({
                "symbol": symbol,
                "name": info.get('name', symbol),
                "code": info.get('code', ''),
                "market": info.get('market', ''),
                "price": cache_record.get('price', 0) if cache_record else 0,
                "trend_code": trend_code,
                "trend_name": csv_trend.get('trend_name', ''),
                "signal_text": signal['text'],
                "signal_color": signal['color'],
                "key_high": csv_trend.get('key_high'),
                "key_low": csv_trend.get('key_low'),
                "n_low": csv_trend.get('n_low'),
                "n_high": csv_trend.get('n_high'),
                "rally_high": csv_trend.get('rally_high'),
                "rally_low": csv_trend.get('rally_low'),
                "secondary_low": csv_trend.get('secondary_low'),
                "secondary_high": csv_trend.get('secondary_high'),
                "description": get_trend_description(trend_code, cache_record.get('price', 0) if cache_record else 0, csv_trend),
                "changed": changed,
                "update_time": csv_trend.get('update_time', ''),
                "from_cache": False,
                "has_trend_data": True,
            })
        elif cache_record and cache_record.get('trend_code'):
            # CSV 无数据，使用缓存（搜索过的股票有完整趋势数据）
            signal = get_signal(cache_record.get('trend_code', ''))
            curr_trend = cache_record.get('trend_code', '')
            changed = curr_trend != prev_trend and prev_trend != ''
            result.append({
                "symbol": symbol,
                "name": info.get('name', symbol),
                "code": info.get('code', ''),
                "market": info.get('market', ''),
                "price": cache_record.get('price', 0),
                "trend_code": cache_record.get('trend_code', ''),
                "trend_name": cache_record.get('trend_name', ''),
                "signal_text": signal['text'],
                "signal_color": signal['color'],
                "key_high": cache_record.get('key_high'),
                "key_low": cache_record.get('key_low'),
                "n_low": cache_record.get('n_low'),
                "n_high": cache_record.get('n_high'),
                "rally_high": cache_record.get('rally_high'),
                "rally_low": cache_record.get('rally_low'),
                "secondary_low": cache_record.get('secondary_low'),
                "secondary_high": cache_record.get('secondary_high'),
                "description": cache_record.get('description', ''),
                "changed": changed,
                "update_time": cache_record.get('update_time', ''),
                "from_cache": True,
                "has_trend_data": True,
            })
        else:
            # 无缓存数据的自选股：尝试从 initial_configs 读取
            prev_data = prev_config or {}
            prev_trend_code = prev_data.get('趋势代码', '')
            if prev_trend_code:
                signal = get_signal(prev_trend_code)
                result.append({
                    "symbol": symbol,
                    "name": info.get('name', symbol),
                    "code": info.get('code', ''),
                    "market": info.get('market', ''),
                    "price": float(prev_data.get('当前价格', 0)) or 0,
                    "trend_code": prev_trend_code,
                    "trend_name": TREND_NAMES.get(prev_trend_code, prev_trend_code),
                    "signal_text": signal['text'],
                    "signal_color": signal['color'],
                    "key_high": None,
                    "key_low": None,
                    "n_low": None,
                    "n_high": None,
                    "rally_high": None,
                    "rally_low": None,
                    "secondary_low": None,
                    "secondary_high": None,
                    "description": get_trend_description(prev_trend_code, prev_data.get('当前价格', 0), prev_data),
                    "changed": False,
                    "update_time": prev_data.get('时间', ''),
                    "has_trend_data": True,
                })
            else:
                # 完全无数据
                result.append({
                    "symbol": symbol,
                    "name": info.get('name', symbol),
                    "code": info.get('code', ''),
                    "market": info.get('market', ''),
                    "price": 0,
                    "trend_code": '',
                    "trend_name": '暂无趋势数据',
                    "signal_text": '待分析',
                    "signal_color": '#9ca3af',
                    "key_high": None,
                    "key_low": None,
                    "n_low": None,
                    "n_high": None,
                    "rally_high": None,
                    "rally_low": None,
                    "secondary_low": None,
                    "secondary_high": None,
                    "description": '暂无趋势数据，请先搜索该股票',
                    "changed": False,
                    "update_time": '',
                    "has_trend_data": False,
                })

    # 补充：缓存中已搜索但不在自选股的股票
    for symbol, entry in cache_data.items():
        if symbol not in watchlist:
            signal = get_signal(entry.get('trend_code', ''))
            result.append({
                "symbol": symbol,
                "name": entry.get('name', symbol),
                "code": entry.get('code', ''),
                "market": entry.get('market', ''),
                "price": entry.get('price', 0),
                "trend_code": entry.get('trend_code', ''),
                "trend_name": entry.get('trend_name', ''),
                "signal_text": signal['text'],
                "signal_color": signal['color'],
                "key_high": entry.get('key_high'),
                "key_low": entry.get('key_low'),
                "n_low": entry.get('n_low'),
                "n_high": entry.get('n_high'),
                "rally_high": entry.get('rally_high'),
                "rally_low": entry.get('rally_low'),
                "secondary_low": entry.get('secondary_low'),
                "secondary_high": entry.get('secondary_high'),
                "description": entry.get('description', ''),
                "changed": False,
                "update_time": entry.get('update_time', ''),
                "from_cache": True,
                "has_trend_data": bool(entry.get('trend_code')),
            })

    return jsonify(clean_nan(result))


@app.route('/query', methods=['POST'])
def query():
    """查询单只股票（优先使用缓存，缓存无效/过期则从iFind获取）"""
    data = request.get_json()
    stock_name = data.get('name', '').strip()

    if not stock_name:
        return jsonify({"error": "请输入股票名称"}), 400

    watchlist = load_watchlist()

    # 模糊匹配
    matches = []
    for symbol, info in watchlist.items():
        name = info.get('name', '')
        code = info.get('code', '')
        if stock_name in name or name in stock_name or symbol == stock_name or code == stock_name:
            matches.append(symbol)

    if len(matches) == 0:
        # 尝试直接匹配股票代码
        for symbol, info in watchlist.items():
            if stock_name == info.get('code'):
                matches.append(symbol)
                break

    if len(matches) == 0:
        # 自选股中没有，尝试从iFind获取（作为新的股票）
        result = _fetch_stock_unknown(stock_name)
        if result:
            # 将搜索结果写入缓存和历史记录
            result_symbol = result.get("symbol", stock_name)
            stock_cache.set(result_symbol, result)
            stock_cache.add_searched(result_symbol)
            return jsonify(clean_nan(result))
        return jsonify({"error": f"未找到股票: {stock_name}", "matches": []}), 404

    if len(matches) > 1:
        return jsonify({
            "error": f"匹配到多个股票，请输入更完整的名称",
            "matches": [{"symbol": s, "name": watchlist.get(s, {}).get('name', s)} for s in matches]
        }), 300

    symbol = matches[0]
    info = watchlist[symbol]

    # Step 1: 检查缓存（只有缓存有效时才使用）
    cached = stock_cache.get(symbol)
    if cached is not None and cached.get('trend_code'):
        # 确保搜索记录写入 searched_stocks.json
        stock_cache.add_searched(symbol)
        signal = get_signal(cached.get('trend_code', ''))
        return jsonify(clean_nan({
            "symbol": symbol,
            "name": cached.get('name', symbol),
            "code": info.get('code', ''),
            "market": info.get('market', ''),
            "price": cached.get('price', 0),
            "trend_code": cached.get('trend_code', ''),
            "trend_name": cached.get('trend_name', ''),
            "signal_text": signal['text'],
            "signal_color": signal['color'],
            "key_high": cached.get('key_high'),
            "key_low": cached.get('key_low'),
            "n_low": cached.get('n_low'),
            "n_high": cached.get('n_high'),
            "rally_high": cached.get('rally_high'),
            "rally_low": cached.get('rally_low'),
            "secondary_low": cached.get('secondary_low'),
            "secondary_high": cached.get('secondary_high'),
            "description": cached.get('description', ''),
            "update_time": cached.get('update_time', ''),
            "from_cache": True,
        }))

    # Step 2: 缓存无或过期，从iFind获取
    result_data = _fetch_stock_from_ifind(symbol, info)

    if result_data is None:
        # iFind获取也失败了，返回缓存数据（即使过期）
        trends = load_all_trends()
        trend_map = {t.get('股票代码'): t for t in trends}
        trend_data = trend_map.get(symbol, {})
        if trend_data:
            signal = get_signal(trend_data.get('趋势代码', ''))
            return jsonify(clean_nan({
                "symbol": symbol,
                "name": info.get('name', symbol),
                "code": info.get('code', ''),
                "market": info.get('market', ''),
                "price": float(trend_data.get('当前价格', 0)),
                "trend_code": trend_data.get('趋势代码', ''),
                "trend_name": trend_data.get('趋势名称', ''),
                "signal_text": signal['text'],
                "signal_color": signal['color'],
                "key_high": trend_data.get('key_high'),
                "key_low": trend_data.get('key_low'),
                "n_low": trend_data.get('n_low'),
                "n_high": trend_data.get('n_high'),
                "rally_high": trend_data.get('rally_high'),
                "rally_low": trend_data.get('rally_low'),
                "secondary_low": trend_data.get('secondary_low'),
                "secondary_high": trend_data.get('secondary_high'),
                "description": get_trend_description(trend_data.get('趋势代码', ''), trend_data.get('当前价格', 0), trend_data),
                "changed": trend_data.get('是否变化', '否') == '是',
                "update_time": str(trend_data.get('时间', '')),
                "from_cache": False,
                "error": "ifind_failed",
            }))
        return jsonify({
            "symbol": symbol,
            "name": info.get('name', symbol),
            "price": 0,
            "trend_code": "",
            "trend_name": "获取失败",
            "signal_text": "无数据",
            "signal_color": "#999",
            "description": "无法获取趋势数据，请稍后重试",
            "error": "no_data"
        }), 500

    # Step 3: 保存到缓存
    stock_cache.set(symbol, result_data)
    stock_cache.add_searched(symbol)

    signal = get_signal(result_data.get('trend_code', ''))
    return jsonify(clean_nan({
        "symbol": symbol,
        "name": result_data.get('name', symbol),
        "code": result_data.get('code', ''),
        "market": result_data.get('market', ''),
        "price": result_data.get('price', 0),
        "trend_code": result_data.get('trend_code', ''),
        "trend_name": result_data.get('trend_name', ''),
        "signal_text": signal['text'],
        "signal_color": signal['color'],
        "key_high": result_data.get('key_high'),
        "key_low": result_data.get('key_low'),
        "n_low": result_data.get('n_low'),
        "n_high": result_data.get('n_high'),
        "rally_high": result_data.get('rally_high'),
        "rally_low": result_data.get('rally_low'),
        "secondary_low": result_data.get('secondary_low'),
        "secondary_high": result_data.get('secondary_high'),
        "description": result_data.get('description', ''),
        "update_time": result_data.get('update_time', ''),
        "from_cache": False,
    }))


@app.route('/api/refresh', methods=['POST'])
def api_refresh():
    """后台刷新：更新所有已搜索股票的数据"""
    try:
        searched = stock_cache.get_searched()
        if not searched:
            return jsonify({"errorcode": 0, "errmsg": "无已搜索股票", "updated": 0})
        
        results = []
        for symbol in searched:
            watchlist = load_watchlist()
            info = watchlist.get(symbol, {})
            if not info:
                # 尝试找匹配
                for k, v in watchlist.items():
                    if v.get("code") == symbol:
                        info = v
                        symbol = k
                        break
            if not info:
                continue
            
            result_data = _fetch_stock_from_ifind(symbol, info)
            if result_data:
                stock_cache.set(symbol, result_data)
                results.append({"symbol": symbol, "name": result_data.get("name"), "status": "success"})
            else:
                results.append({"symbol": symbol, "status": "failed"})
            import time
            time.sleep(1)
        
        return jsonify({
            "errorcode": 0,
            "errmsg": f"刷新完成",
            "updated": len([r for r in results if r.get("status") == "success"]),
            "total": len(results),
            "details": results,
        })
    except Exception as e:
        return jsonify({"errorcode": 1, "errmsg": str(e)}), 500


@app.route('/api/stocks')
def api_stocks():
    """获取自选股列表"""
    watchlist = load_watchlist()
    return jsonify([
        {"symbol": s, "code": v.get('code', ''), "name": v.get('name', s), "market": v.get('market', '')}
        for s, v in watchlist.items()
    ])


def load_settings():
    """加载系统设置"""
    if os.path.exists(SETTINGS_PATH):
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_settings(settings):
    """保存系统设置"""
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=4)


def get_saved_token():
    """从settings.json读取保存的token"""
    settings = load_settings()
    return settings.get("ifind_token"), settings.get("token_expire_time")


@app.route('/api/check_token', methods=['GET'])
def api_check_token():
    """检查iFinD Token是否有效
    
    返回:
        errorcode: 0 = 有效, -1301 = Token过期或无效
    """
    # 优先使用settings.json中保存的token
    refresh_token, expire_time = get_saved_token()
    
    # 尝试从ifind.py获取默认token
    if not refresh_token:
        try:
            from fetcher.ifind import REFRESH_TOKEN
            refresh_token = REFRESH_TOKEN
        except ImportError:
            pass
    
    if not refresh_token:
        return jsonify({
            "errorcode": -1301,
            "errmsg": "未配置iFinD Token，请输入新Token"
        })
    
    # 检查本地记录的过期时间
    if expire_time:
        try:
            expire_dt = datetime.strptime(expire_time, "%Y-%m-%d")
            if datetime.now() >= expire_dt:
                return jsonify({
                    "errorcode": -1301,
                    "errmsg": f"Token已于 {expire_time} 过期，请提供新Token"
                })
        except ValueError:
            pass
    
    # 调用iFinD API验证token
    headers = {"Content-Type": "application/json", "refresh_token": refresh_token}
    try:
        import requests
        response = requests.post(TOKEN_URL, headers=headers, timeout=15)
        result = response.json()
        
        if result.get("errorcode") == 0:
            # Token有效，更新过期时间（从API响应中获取或默认7天后）
            api_expire = result.get("data", {}).get("refresh_token_expire_time")
            if not api_expire:
                # API未返回具体过期时间，默认7天
                api_expire = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
            
            settings = load_settings()
            settings["ifind_token"] = refresh_token
            settings["token_expire_time"] = api_expire
            save_settings(settings)
            
            return jsonify({
                "errorcode": 0,
                "errmsg": "Token有效",
                "expire_time": api_expire
            })
        else:
            # Token无效或已过期
            err_msg = result.get("errmsg", "Token无效")
            # 检查是否明确是过期错误
            if "过期" in err_msg or "无效" in err_msg or "失败" in err_msg:
                return jsonify({
                    "errorcode": -1301,
                    "errmsg": f"Token已过期: {err_msg}，请提供新Token"
                })
            return jsonify({
                "errorcode": -1301,
                "errmsg": f"Token验证失败: {err_msg}"
            })
    except ImportError:
        return jsonify({
            "errorcode": -1301,
            "errmsg": "无法导入requests模块，请安装: pip install requests"
        })
    except Exception as e:
        return jsonify({
            "errorcode": -1301,
            "errmsg": f"Token验证请求失败: {str(e)}"
        })


@app.route('/api/update_token', methods=['POST'])
def api_update_token():
    """保存新的iFinD Token到settings.json
    
    请求体: { "token": "新token字符串" }
    """
    data = request.get_json()
    new_token = data.get('token', '').strip()
    
    if not new_token:
        return jsonify({
            "errorcode": 1,
            "errmsg": "Token不能为空"
        }), 400
    
    # 先用新token验证有效性
    headers = {"Content-Type": "application/json", "refresh_token": new_token}
    try:
        import requests
        response = requests.post(TOKEN_URL, headers=headers, timeout=15)
        result = response.json()
        
        if result.get("errorcode") == 0:
            # Token有效，保存
            api_expire = result.get("data", {}).get("refresh_token_expire_time")
            if not api_expire:
                api_expire = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
            
            settings = load_settings()
            settings["ifind_token"] = new_token
            settings["token_expire_time"] = api_expire
            save_settings(settings)
            
            return jsonify({
                "errorcode": 0,
                "errmsg": "Token保存成功",
                "expire_time": api_expire
            })
        else:
            err_msg = result.get("errmsg", "Token无效")
            return jsonify({
                "errorcode": 1,
                "errmsg": f"Token验证失败: {err_msg}"
            }), 400
    except Exception as e:
        return jsonify({
            "errorcode": 1,
            "errmsg": f"验证请求失败: {str(e)}"
        }), 500


@app.route('/api/cache/clear', methods=['POST'])
def api_cache_clear():
    """清空缓存"""
    try:
        stock_cache.clear_all()
        return jsonify({"errorcode": 0, "errmsg": "缓存已清空"})
    except Exception as e:
        return jsonify({"errorcode": 1, "errmsg": str(e)}), 500


@app.route('/trend_detail/<symbol>')
def trend_detail_page(symbol):
    """趋势详情页"""
    return render_template('trend_detail.html', symbol=symbol)


@app.route('/api/history')
def api_history():
    """获取历史搜索列表（仅从searched_stocks.json，只包含真正被搜索过的股票）"""
    try:
        # 只从 searched_stocks.json 读取，不要混入 watchlist 数据
        searched = stock_cache.get_searched()
        cache_data = stock_cache.get_all()

        result = []
        for symbol in searched:
            # 只从 cache 读取数据（cache 在 /query 时写入）
            # 不从 watchlist 补全，避免自选股混入历史记录
            cache_entry = cache_data.get(symbol, {})

            # 如果 cache 里没有该 symbol 的数据（从未被成功搜索），跳过
            if not cache_entry:
                continue

            name = cache_entry.get('name') or symbol
            code = cache_entry.get('code') or ''
            market = cache_entry.get('market') or ''
            price = cache_entry.get('price', 0)
            trend_code = cache_entry.get('trend_code', '')
            trend_name = cache_entry.get('trend_name', '')
            signal = get_signal(trend_code)

            result.append({
                "symbol": symbol,
                "name": name,
                "code": code,
                "market": market,
                "price": price,
                "trend_code": trend_code,
                "trend_name": trend_name,
                "signal_text": signal['text'],
                "signal_color": signal['color'],
                "has_detail": os.path.exists(os.path.join(BASE_DIR, "output", "趋势历史", f"{symbol}_趋势历史.csv")),
            })

        return jsonify(clean_nan({
            "errorcode": 0,
            "total": len(result),
            "history": result,
        }))
    except Exception as e:
        return jsonify({"errorcode": 1, "errmsg": str(e)}), 500


@app.route('/api/trend_detail/<symbol>')
def api_trend_detail(symbol):
    """获取某只股票的趋势详情历史（从趋势历史CSV读取，按Excel格式返回）"""
    try:
        watchlist = load_watchlist()
        cache_data = stock_cache.get_all()

        info = watchlist.get(symbol, {})
        cache_entry = cache_data.get(symbol, {})

        # 基本信息
        name = info.get('name') or cache_entry.get('name') or symbol
        code = info.get('code') or cache_entry.get('code') or ''
        market = info.get('market') or cache_entry.get('market') or ''
        current_price = cache_entry.get('price', 0)

        # 优先从趋势判断 CSV 读取当前趋势，cache 只作为备用
        csv_trend = _get_current_trend_from_csv(symbol, info)
        if csv_trend and csv_trend.get('trend_code'):
            current_trend_code = csv_trend['trend_code']
            current_trend_name = csv_trend['trend_name']
        else:
            current_trend_code = cache_entry.get('trend_code', '')
            current_trend_name = cache_entry.get('trend_name', '')
        signal = get_signal(current_trend_code)

        # ========== 配置信息：从 initial_configs.csv 读取 ==========
        config_info = {}
        config_path = os.path.join(BASE_DIR, "config", "initial_configs.csv")
        if os.path.exists(config_path):
            try:
                configs_df = pd.read_csv(config_path)
                # 转换 symbol 为 config_code 格式：sh000333 -> 000333SH
                market_upper = market.upper() if market else None
                if market_upper:
                    raw_code = code if code else symbol.replace('sh', '').replace('sz', '')
                    config_key = f"{raw_code}{market_upper}"
                else:
                    config_key = symbol.upper().replace('SH', 'SH').replace('SZ', 'SZ')
                
                config_row = configs_df[configs_df['股票代码'] == config_key]
                if not config_row.empty:
                    row = config_row.iloc[0]
                    config_info = {
                        "config_date": str(row.get('最新时间', ''))[:10] if pd.notna(row.get('最新时间')) else None,
                        "config_trend": row.get('趋势代码', ''),
                        "config_trend_name": row.get('趋势名称', ''),
                        "key_high": row.get('key_high'),
                        "key_low": row.get('key_low'),
                        "n_high": row.get('n_high'),
                        "n_low": row.get('n_low'),
                        "rally_high": row.get('rally_high'),
                        "rally_low": row.get('rally_low'),
                        "secondary_high": row.get('secondary_high'),
                        "secondary_low": row.get('secondary_low'),
                        "break_high": row.get('break_high'),
                        "break_low": row.get('break_low'),
                    }
            except Exception as e:
                print(f"[trend_detail] 读取配置信息失败: {e}")

        # ========== 每分钟数据 ==========
        minute_records = []
        if code and market:
            min_data_path = os.path.join(BASE_DIR, "data", f"{symbol}_{code}_min1.csv")
            if os.path.exists(min_data_path):
                try:
                    min_df = pd.read_csv(min_data_path)
                    min_df['day'] = pd.to_datetime(min_df['day'], errors='coerce')
                    min_df = min_df.sort_values('day', ascending=True).reset_index(drop=True)
                    # 过滤掉 config_info.config_date 之前的数据
                    if config_info.get('config_date'):
                        config_dt = pd.to_datetime(config_info['config_date'], errors='coerce')
                        if pd.notna(config_dt):
                            min_df = min_df[min_df['day'] >= config_dt]
                    # 只保留最后 500 条（避免数据量过大）
                    if len(min_df) > 500:
                        min_df = min_df.iloc[-500:]
                    for _, row in min_df.iterrows():
                        minute_records.append({
                            "time": str(row.get('day', '')),
                            "open": float(row['open']) if pd.notna(row.get('open')) else None,
                            "high": float(row['high']) if pd.notna(row.get('high')) else None,
                            "low": float(row['low']) if pd.notna(row.get('low')) else None,
                            "close": float(row['close']) if pd.notna(row.get('close')) else None,
                            "volume": float(row['volume']) if pd.notna(row.get('volume')) else None,
                        })
                except Exception as e:
                    print(f"[trend_detail] 读取分钟数据失败: {e}")

        # 趋势类型 → Excel列名 映射
        TREND_TO_COLUMN = {
            "up": "上升趋势",
            "up_natural": "自然回撤",
            "up_rally": "回升",
            "up_secondary": "次级回撤",
            "down": "下跌趋势",
            "down_natural": "自然回升",
            "down_rally": "回撤",
            "down_secondary": "次级回升",
        }
        # 趋势类型 → 关键点字段名 映射
        TREND_TO_KEYPOINT = {
            "up": "key_high",
            "up_natural": "n_low",
            "up_rally": "rally_high",
            "up_secondary": "secondary_low",
            "down": "key_low",
            "down_natural": "n_high",
            "down_rally": "rally_low",
            "down_secondary": "secondary_high",
        }
        # 关键点字段名 → Excel列名（反向映射）
        KEYPOINT_TO_COLUMN = {v: k for k, v in TREND_TO_COLUMN.items()}
        KEYPOINT_TO_COLUMN.update({v: k for k, v in TREND_TO_KEYPOINT.items()})

        def kp_to_col(kp_name):
            """将关键点字段名转为Excel列名"""
            return KEYPOINT_TO_COLUMN.get(kp_name, kp_name)

        def trend_to_col(trend_code):
            """将趋势代码转为Excel列名"""
            return TREND_TO_COLUMN.get(trend_code, "")

        # 尝试读取趋势历史CSV（优先），否则读趋势判断CSV
        trend_history_path = os.path.join(BASE_DIR, "output", "趋势历史", f"{symbol}_趋势历史.csv")
        trend_judge_path = os.path.join(BASE_DIR, "output", "趋势判断", f"{symbol}_趋势判断.csv")

        records = []
        if os.path.exists(trend_history_path):
            # 检测 CSV 格式：新格式(时间,价格,趋势,趋势名称,关键点名称,关键点) 或 旧格式(时间,day,high,low,close,trend,trend_name,key_high,...)
            df = pd.read_csv(trend_history_path)
            df['时间_dt'] = pd.to_datetime(df['时间'], errors='coerce')
            df = df.sort_values('时间_dt', ascending=True).reset_index(drop=True)

            has_full_kp = 'key_high' in df.columns or 'trend' in df.columns
            if has_full_kp:
                # 旧格式：每分钟完整数据，包含 trend, key_high 等全部字段
                prev_trend = None
                for _, row in df.iterrows():
                    trend_code = str(row.get('trend', ''))
                    time_str = str(row.get('时间', ''))[:16]
                    close_price = float(row['close']) if pd.notna(row.get('close')) else None
                    key_high = float(row['key_high']) if pd.notna(row.get('key_high')) else None
                    key_low = float(row['key_low']) if pd.notna(row.get('key_low')) else None
                    n_low = float(row['n_low']) if pd.notna(row.get('n_low')) else None
                    n_high = float(row['n_high']) if pd.notna(row.get('n_high')) else None
                    rally_high = float(row['rally_high']) if pd.notna(row.get('rally_high')) else None
                    rally_low = float(row['rally_low']) if pd.notna(row.get('rally_low')) else None
                    secondary_low = float(row['secondary_low']) if pd.notna(row.get('secondary_low')) else None
                    secondary_high = float(row['secondary_high']) if pd.notna(row.get('secondary_high')) else None
                    rec = {
                        "time": time_str, "trend_code": trend_code,
                        "trend_name": str(row.get('trend_name', '')),
                        "close": close_price,
                        "上升趋势": key_high, "自然回撤": n_low, "回升": rally_high,
                        "次级回撤": secondary_low, "下跌趋势": key_low, "自然回升": n_high,
                        "回撤": rally_low, "次级回升": secondary_high,
                        "ratio": None,
                        "remark": str(row.get('trend_name', '')),
                    }
                    records.append(rec)
            else:
                # 新格式：关键点变化记录（时间,价格,趋势,趋势名称,关键点名称,关键点）
                KEYPOINT_CN = {
                    'key_high': '上升趋势', 'key_low': '下跌趋势',
                    'n_low': '自然回撤', 'n_high': '自然回升',
                    'rally_high': '回升', 'rally_low': '回撤',
                    'secondary_low': '次级回撤', 'secondary_high': '次级回升',
                }
                prev_kp_value = None
                for _, row in df.iterrows():
                    trend_code = str(row.get('趋势', ''))
                    kp_name = str(row.get('关键点名称', ''))
                    kp_value = float(row['关键点']) if pd.notna(row.get('关键点')) else None
                    price = float(row['价格']) if pd.notna(row.get('价格')) else None
                    time_str = str(row.get('时间', ''))[:16]
                    ratio = None
                    if kp_value is not None and prev_kp_value and prev_kp_value != 0:
                        ratio = round(kp_value / prev_kp_value, 3)
                    kp_cn = KEYPOINT_CN.get(kp_name, kp_name)
                    rec = {
                        "time": time_str, "trend_code": trend_code,
                        "trend_name": str(row.get('趋势名称', '')),
                        "close": price,
                        "上升趋势": None, "自然回撤": None, "回升": None,
                        "次级回撤": None, "下跌趋势": None, "自然回升": None,
                        "回撤": None, "次级回升": None,
                        "ratio": ratio, "remark": kp_cn,
                    }
                    if kp_cn in rec and kp_value is not None:
                        rec[kp_cn] = kp_value
                    records.append(rec)
                    if kp_value is not None:
                        prev_kp_value = kp_value

        if not records and os.path.exists(trend_judge_path):
            # 趋势判断CSV格式：时间,当前价格,趋势代码,趋势名称,key_high,key_low,...
            df = pd.read_csv(trend_judge_path)
            df['时间_dt'] = pd.to_datetime(df['时间'], errors='coerce')
            df = df.sort_values('时间_dt', ascending=True).reset_index(drop=True)

            # 只保留趋势变化的关键记录
            prev_trend = None
            for _, row in df.iterrows():
                trend_code = str(row.get('趋势代码', ''))
                if trend_code == prev_trend:
                    continue  # 跳过同一趋势的连续记录
                prev_trend = trend_code

                time_str = str(row.get('时间', ''))[:10]
                price = float(row.get('当前价格', 0)) if pd.notna(row.get('当前价格')) else 0

                # 提取各关键点
                key_high = float(row['key_high']) if pd.notna(row.get('key_high')) else None
                key_low = float(row['key_low']) if pd.notna(row.get('key_low')) else None
                n_low = float(row['n_low']) if pd.notna(row.get('n_low')) else None
                n_high = float(row['n_high']) if pd.notna(row.get('n_high')) else None
                rally_high = float(row['rally_high']) if pd.notna(row.get('rally_high')) else None
                rally_low = float(row['rally_low']) if pd.notna(row.get('rally_low')) else None
                secondary_low = float(row['secondary_low']) if pd.notna(row.get('secondary_low')) else None
                secondary_high = float(row['secondary_high']) if pd.notna(row.get('secondary_high')) else None

                rec = {
                    "time": time_str,
                    "上升趋势": key_high,
                    "自然回撤": n_low,
                    "回升": rally_high,
                    "次级回撤": secondary_low,
                    "下跌趋势": key_low,
                    "自然回升": n_high,
                    "回撤": rally_low,
                    "次级回升": secondary_high,
                    "ratio": None,
                    "remark": TREND_TO_COLUMN.get(trend_code, ''),
                }
                records.append(rec)

        if records:
            return jsonify(clean_nan({
                "errorcode": 0,
                "symbol": symbol,
                "name": name,
                "code": code,
                "market": market,
                "current_price": current_price,
                "current_trend_code": current_trend_code,
                "current_trend_name": current_trend_name,
                "signal_text": signal['text'],
                "signal_color": signal['color'],
                "config_info": config_info,
                "total_records": len(records),
                "records": records,
                "minute_records": minute_records,
                "minute_total": len(minute_records),
            }))
        else:
            return jsonify(clean_nan({
                "errorcode": 1,
                "errmsg": f"暂无趋势历史数据: {symbol}",
                "symbol": symbol,
                "name": name,
                "code": code,
                "market": market,
                "current_price": current_price,
                "current_trend_code": current_trend_code,
                "current_trend_name": current_trend_name,
                "signal_text": signal['text'],
                "signal_color": signal['color'],
                "config_info": config_info,
                "total_records": 0,
                "records": [],
                "minute_records": minute_records,
                "minute_total": len(minute_records),
            }))

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"errorcode": 1, "errmsg": str(e)}), 500


@app.route('/api/cache/status', methods=['GET'])
def api_cache_status():
    """获取缓存状态"""
    try:
        cache_data = stock_cache.get_all()
        searched = stock_cache.get_searched()
        return jsonify({
            "errorcode": 0,
            "cached_count": len(cache_data),
            "searched_count": len(searched),
            "searched": searched,
        })
    except Exception as e:
        return jsonify({"errorcode": 1, "errmsg": str(e)}), 500


if __name__ == '__main__':
    print("=" * 50)
    print("📊 Raven 股票趋势追踪系统 - 网页界面")
    print("=" * 50)
    csv_path = get_latest_trend_csv()
    if csv_path:
        print(f"✅ 检测到趋势数据: {os.path.basename(csv_path)}")
    else:
        print("⚠️ 未检测到趋势数据文件，请先运行 tracker.py")
    print("🌐 启动服务器: http://localhost:5000")
    print("=" * 50)
    
    # 启动后台更新器（5分钟间隔）
    start_background_updater(interval=300)
    
    app.run(host='0.0.0.0', port=5019, debug=True, threaded=True)
