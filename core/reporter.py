"""
报告生成器
"""
import pandas as pd
import os
from datetime import datetime


class Reporter:
    def __init__(self, output_dir: str = "output"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def generate(self, results: list) -> pd.DataFrame:
        """生成规范报告

        Args:
            results: 每只股票的趋势状态列表（来自 analyzer.batch_update）

        Returns:
            包含以下列的 DataFrame：
            时间、股票代码、股票名称、当前价格、趋势、趋势名称、配置时间、
            key_high、key_low、n_low、n_high、rally_high、rally_low、
            secondary_low、secondary_high、是否变化
        """
        if not results:
            return pd.DataFrame()

        rows = []
        for r in results:
            row = {
                "时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "股票代码": r.get("stock_code", ""),
                "当前价格": r.get("current_price", 0),
                "趋势代码": r.get("trend", ""),
                "趋势名称": r.get("trend_name", ""),
                "配置时间": r.get("config_time", ""),
                "key_high": r.get("key_high"),
                "key_low": r.get("key_low"),
                "n_low": r.get("n_low"),
                "n_high": r.get("n_high"),
                "rally_high": r.get("rally_high"),
                "rally_low": r.get("rally_low"),
                "secondary_low": r.get("secondary_low"),
                "secondary_high": r.get("secondary_high"),
                "是否变化": "是" if r.get("changed") else "否",
            }
            rows.append(row)

        df = pd.DataFrame(rows)
        # 按股票代码排序
        df = df.sort_values("股票代码").reset_index(drop=True)
        return df

    def save(self, df: pd.DataFrame, output_dir: str = None, filename: str = None):
        """保存到CSV文件

        Args:
            df: 报告 DataFrame
            output_dir: 输出目录（默认使用 self.output_dir）
            filename: 文件名（默认自动生成：趋势追踪_YYYYMMDD_HHMMSS.csv）
        """
        if df.empty:
            return

        if output_dir is None:
            output_dir = self.output_dir

        os.makedirs(output_dir, exist_ok=True)

        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"趋势追踪_{timestamp}.csv"

        filepath = os.path.join(output_dir, filename)
        df.to_csv(filepath, index=False, encoding="utf-8-sig")
        print(f"  ✓ 报告已保存: {filepath}")
        return filepath

    def save_append(self, df: pd.DataFrame, filename: str):
        """追加模式保存（用于持续追踪）"""
        filepath = os.path.join(self.output_dir, filename)

        if os.path.exists(filepath):
            existing = pd.read_csv(filepath, encoding="utf-8-sig")
            combined = pd.concat([existing, df], ignore_index=True)
            combined.to_csv(filepath, index=False, encoding="utf-8-sig")
        else:
            df.to_csv(filepath, index=False, encoding="utf-8-sig")
