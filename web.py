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


def get_latest_trend_csv():
    """获取最新的趋势CSV文件"""
    pattern = os.path.join(OUTPUT_DIR, "趋势追踪_*.csv")
    files = glob.glob(pattern)
    if not files:
        return None
    latest = max(files, key=os.path.getmtime)
    return latest


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
    """生成趋势解读"""
    def fmt(v):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return "无"
        try:
            return f"{float(v):.2f}"
        except:
            return "无"

    if trend_code == "up":
        return f"价格处于上升趋势，等待回调后买入机会"
    elif trend_code == "up_natural":
        n_low = fmt(record.get('n_low'))
        return f"自然回撤中，n_low={n_low}，关注是否止跌"
    elif trend_code == "up_rally":
        rally_high = fmt(record.get('rally_high'))
        return f"回升阶段，rally_high={rally_high}，关注能否突破"
    elif trend_code == "up_secondary":
        secondary_low = fmt(record.get('secondary_low'))
        return f"次级回撤，secondary_low={secondary_low}，等待回升信号"
    elif trend_code == "up_break":
        break_low = fmt(record.get('key_low'))
        return f"关键支撑{break_low}已破，注意风险"
    elif trend_code == "down":
        key_low = fmt(record.get('key_low'))
        return f"下跌趋势，key_low={key_low}，等待止跌信号"
    elif trend_code == "down_natural":
        n_high = fmt(record.get('n_high'))
        return f"自然回升中，n_high={n_high}，关注是否突破"
    elif trend_code == "down_rally":
        rally_low = fmt(record.get('rally_low'))
        return f"回撤阶段，rally_low={rally_low}，注意风险"
    elif trend_code == "down_secondary":
        secondary_high = fmt(record.get('secondary_high'))
        return f"次级回升，secondary_high={secondary_high}，关注能否突破"
    elif trend_code == "down_break":
        break_high = fmt(record.get('key_high'))
        return f"突破关键阻力{break_high}，趋势可能反转"
    return "趋势未确定"


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
        
        if is_code:
            code = stock_name
            # 尝试SH和SZ
            for market in [("SH", ".SH"), ("SZ", ".SZ")]:
                market_name, suffix = market
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
                                "name": f"股票{code}",
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
        
        # 保存历史趋势记录
        trend_records = []
        for _, row in df.iterrows():
            high = float(row["high"])
            low = float(row["low"])
            state = update_trend(state, high, low)
            
            trend_records.append({
                "时间": row["day"],
                "价格": row["close"],
                "趋势": state["trend"],
                "趋势名称": TREND_NAMES.get(state["trend"], ""),
                "key_high": state.get("key_high"),
                "key_low": state.get("key_low"),
                "n_low": state.get("n_low"),
                "n_high": state.get("n_high"),
                "rally_high": state.get("rally_high"),
                "rally_low": state.get("rally_low"),
                "secondary_low": state.get("secondary_low"),
                "secondary_high": state.get("secondary_high"),
            })
        
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
            trend_df = trend_df.drop_duplicates(subset=["时间"], keep="last")
            trend_df = trend_df.sort_values("时间").reset_index(drop=True)
        trend_df.to_csv(trend_file, index=False, encoding="utf-8")
        
        # 获取最终趋势
        trend_code = state["trend"]
        signal = get_signal(trend_code)
        current_price = float(df.iloc[-1]["close"])
        
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
    """获取所有股票趋势"""
    trends = load_all_trends()
    watchlist = load_watchlist()

    result = []
    for t in trends:
        symbol = t.get('股票代码', '')
        # 从watchlist获取名称
        name = symbol
        if symbol in watchlist:
            name = watchlist[symbol].get('name', symbol)
        elif symbol.startswith('sh') or symbol.startswith('sz'):
            # 尝试从ALL_STOCKS匹配
            code = symbol[2:]
            for k, v in watchlist.items():
                if v.get('code') == code:
                    name = v.get('name', symbol)
                    break

        signal = get_signal(t.get('趋势代码', ''))
        result.append({
            "symbol": symbol,
            "name": name,
            "price": float(t.get('当前价格', 0)),
            "trend_code": t.get('趋势代码', ''),
            "trend_name": t.get('趋势名称', ''),
            "signal_text": signal['text'],
            "signal_color": signal['color'],
            "key_high": t.get('key_high'),
            "key_low": t.get('key_low'),
            "n_low": t.get('n_low'),
            "n_high": t.get('n_high'),
            "rally_high": t.get('rally_high'),
            "rally_low": t.get('rally_low'),
            "secondary_low": t.get('secondary_low'),
            "secondary_high": t.get('secondary_high'),
            "description": get_trend_description(t.get('趋势代码', ''), t.get('当前价格', 0), t),
            "changed": t.get('是否变化', '否') == '是',
            "update_time": str(t.get('时间', '')),
        })

    # 补充缓存中已搜索但不在CSV中的股票
    cache_data = stock_cache.get_all()
    cache_symbols_in_result = {r["symbol"] for r in result}
    for symbol, entry in cache_data.items():
        if symbol not in cache_symbols_in_result:
            signal = get_signal(entry.get('trend_code', ''))
            result.append({
                "symbol": symbol,
                "name": entry.get('name', symbol),
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
