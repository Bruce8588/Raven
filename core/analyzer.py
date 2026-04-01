"""
趋势分析器
从配置时间点开始，逐日/逐分钟追踪趋势发展
"""
import pandas as pd
import sys
import os

# 确保 core 模块可导入
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.trend import init_state, update_trend
from core.config.rules import TREND_NAMES

# 股票代码到iFinD格式的转换映射
_MARKET_SUFFIX = {
    "SZ": ".SZ",
    "SH": ".SH",
}


class MarketTrendAnalyzer:
    def __init__(self, initial_configs_path: str):
        """加载全市场初始配置"""
        self.configs = pd.read_csv(initial_configs_path)
        # 预处理：清理股票代码列的BOM和空格
        self.configs.columns = self.configs.columns.str.strip()
        if "﻿股票代码" in self.configs.columns:
            self.configs.rename(columns={"﻿股票代码": "股票代码"}, inplace=True)
        self.configs["股票代码"] = self.configs["股票代码"].astype(str).str.strip()
        # 建立索引：快速查询
        self._index = {row["股票代码"]: row for _, row in self.configs.iterrows()}

    def get_stock_config(self, stock_code: str) -> dict:
        """根据股票代码获取配置

        Args:
            stock_code: 股票代码，支持多种格式：
            - "000156SZ" / "000156SH"（配置原生格式）
            - "sh002129" / "sz000333"（watchlist格式，小写前缀+代码）
            - "002129"（纯代码，需要进一步匹配）

        Returns:
            包含趋势、key_high、key_low、n_low、n_high、配置时间等的字典
        """
        # 标准化输入
        stock_code = str(stock_code).strip()

        # 1. 尝试直接匹配
        row = self._index.get(stock_code)
        if row is not None:
            return row.to_dict()

        # 2. 尝试小写前缀格式 -> 大写后缀格式
        # 如 "sh002129" -> 尝试 "002129SH"
        normalized = stock_code.lower()
        if normalized.startswith("sh") or normalized.startswith("sz"):
            market = "SH" if normalized.startswith("sh") else "SZ"
            code_part = normalized[2:]  # 去掉前缀
            transformed = f"{code_part}{market}"
            row = self._index.get(transformed)
            if row is not None:
                return row.to_dict()

        # 3. 尝试去掉后缀匹配（如 "000333SZ" -> "000333"）
        code_clean = stock_code.rstrip("SZSHszsh")
        for key in self._index:
            if key.rstrip("SZSHszsh") == code_clean:
                return self._index[key].to_dict()

        return None

    def _init_state_from_config(self, stock_code: str) -> dict:
        """从配置初始化趋势状态（用于实时追踪）"""
        config = self.get_stock_config(stock_code)
        if config is None:
            return None

        stock_info = {
            "trend": config.get("趋势代码", "up"),
            "key_high": config.get("key_high"),
            "key_low": config.get("key_low"),
            "n_low": config.get("n_low"),
            "n_high": config.get("n_high"),
            "rally_high": config.get("rally_high"),
            "rally_low": config.get("rally_low"),
            "secondary_low": config.get("secondary_low"),
            "secondary_high": config.get("secondary_high"),
            "break_low": config.get("break_low"),
            "break_high": config.get("break_high"),
        }
        return init_state(stock_info)

    def update_trend(self, stock_code: str, current_price: float) -> dict:
        """基于当前价格更新趋势

        Args:
            stock_code: 股票代码
            current_price: 当前价格

        Returns:
            包含当前趋势、是否变化、关键点等信息的字典
        """
        config = self.get_stock_config(stock_code)
        if config is None:
            return None

        # 初始化状态（从配置时间点）
        state = self._init_state_from_config(stock_code)
        if state is None:
            return None

        original_trend = state["trend"]

        # 使用当前价格更新趋势（假设当前价格为收盘价，高低价相同或使用盘口数据）
        state = update_trend(state, current_price, current_price)

        changed = state["trend"] != original_trend

        return {
            "stock_code": stock_code,
            "current_price": current_price,
            "trend": state["trend"],
            "trend_name": TREND_NAMES.get(state["trend"], state["trend"]),
            "changed": changed,
            "config_time": config.get("最新时间"),
            "key_high": state["key_high"],
            "key_low": state["key_low"],
            "n_low": state["n_low"],
            "n_high": state["n_high"],
            "rally_high": state["rally_high"],
            "rally_low": state["rally_low"],
            "secondary_low": state["secondary_low"],
            "secondary_high": state["secondary_high"],
        }

    def batch_update(self, stock_prices: dict) -> list:
        """批量更新多只股票

        Args:
            stock_prices: {股票代码: 当前价格} 字典

        Returns:
            每只股票的趋势状态列表
        """
        results = []
        for stock_code, price in stock_prices.items():
            result = self.update_trend(stock_code, price)
            if result:
                results.append(result)
        return results

    def get_stock(self, stock_code: str) -> dict:
        """获取股票配置的内部方法（兼容别名）"""
        return self.get_stock_config(stock_code)

    def get_watchlist_from_configs(self, watchlist_codes: list) -> pd.DataFrame:
        """从初始配置中筛选自选股的配置

        Args:
            watchlist_codes: 自选股代码列表，如 ["000333SZ", "002129SZ"]

        Returns:
            筛选后的配置 DataFrame
        """
        mask = self.configs["股票代码"].isin(watchlist_codes)
        return self.configs[mask]
