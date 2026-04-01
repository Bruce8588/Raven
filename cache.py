from typing import Optional
#!/usr/bin/env python3
"""
Raven 股票数据缓存模块
功能：缓存iFind获取的股票趋势数据，减少API调用
"""
import json
import os
import time
import threading
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE_DIR, "cache")
CACHE_EXPIRE_MINUTES = 15  # 缓存15分钟过期

# 线程锁
_cache_lock = threading.Lock()


class StockCache:
    """股票数据缓存管理器"""
    
    def __init__(self, cache_dir=None):
        self.cache_dir = cache_dir or CACHE_DIR
        self.cache_file = os.path.join(self.cache_dir, "stock_cache.json")
        self.searched_file = os.path.join(self.cache_dir, "searched_stocks.json")
        os.makedirs(self.cache_dir, exist_ok=True)
    
    def _load_cache(self) -> dict:
        """加载缓存文件（线程安全）"""
        with _cache_lock:
            if os.path.exists(self.cache_file):
                try:
                    with open(self.cache_file, "r", encoding="utf-8") as f:
                        return json.load(f)
                except (json.JSONDecodeError, IOError):
                    return {}
            return {}
    
    def _save_cache(self, data: dict):
        """保存缓存文件（线程安全）"""
        with _cache_lock:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    
    def _load_searched(self) -> list:
        """加载已搜索股票列表（线程安全）"""
        with _cache_lock:
            if os.path.exists(self.searched_file):
                try:
                    with open(self.searched_file, "r", encoding="utf-8") as f:
                        return json.load(f)
                except (json.JSONDecodeError, IOError):
                    return []
            return []
    
    def _save_searched(self, data: list):
        """保存已搜索股票列表（线程安全）"""
        with _cache_lock:
            with open(self.searched_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    
    def get(self, symbol: str) -> Optional[dict]:
        """获取缓存数据，如果存在且未过期则返回，否则返回None"""
        cache = self._load_cache()
        entry = cache.get(symbol)
        if entry is None:
            return None
        
        update_time_str = entry.get("update_time", "")
        if not update_time_str:
            return None
        
        try:
            update_time = datetime.strptime(update_time_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
        
        if datetime.now() - update_time > timedelta(minutes=CACHE_EXPIRE_MINUTES):
            return None
        
        return entry
    
    def set(self, symbol: str, data: dict):
        """保存股票数据到缓存"""
        cache = self._load_cache()
        entry = {
            "name": data.get("name", symbol),
            "price": data.get("price", 0),
            "trend_code": data.get("trend_code", ""),
            "trend_name": data.get("trend_name", ""),
            "signal_text": data.get("signal_text", ""),
            "signal_color": data.get("signal_color", "#999"),
            "key_high": data.get("key_high"),
            "key_low": data.get("key_low"),
            "n_high": data.get("n_high"),
            "n_low": data.get("n_low"),
            "rally_high": data.get("rally_high"),
            "rally_low": data.get("rally_low"),
            "secondary_high": data.get("secondary_high"),
            "secondary_low": data.get("secondary_low"),
            "description": data.get("description", ""),
            "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        cache[symbol] = entry
        self._save_cache(cache)
    
    def is_fresh(self, symbol: str) -> bool:
        """检查缓存是否新鲜（未过期）"""
        return self.get(symbol) is not None
    
    def get_all(self) -> dict:
        """获取所有缓存数据"""
        return self._load_cache()
    
    def get_searched(self) -> list:
        """获取所有已搜索的股票代码列表"""
        return self._load_searched()
    
    def add_searched(self, symbol: str):
        """添加股票到已搜索列表"""
        searched = self._load_searched()
        if symbol not in searched:
            searched.append(symbol)
            self._save_searched(searched)
    
    def get_stale_stocks(self, minutes: int = 5) -> list:
        """获取需要刷新的股票（在缓存中但超过指定分钟未更新的）"""
        cache = self._load_cache()
        stale = []
        cutoff = datetime.now() - timedelta(minutes=minutes)
        
        for symbol, entry in cache.items():
            update_time_str = entry.get("update_time", "")
            if not update_time_str:
                continue
            try:
                update_time = datetime.strptime(update_time_str, "%Y-%m-%d %H:%M:%S")
                if update_time < cutoff:
                    stale.append(symbol)
            except ValueError:
                continue
        
        return stale
    
    def remove(self, symbol: str):
        """从缓存中删除指定股票"""
        cache = self._load_cache()
        if symbol in cache:
            del cache[symbol]
            self._save_cache(cache)
        
        # 也从已搜索列表移除
        searched = self._load_searched()
        if symbol in searched:
            searched.remove(symbol)
            self._save_searched(searched)
    
    def clear_all(self):
        """清空所有缓存"""
        self._save_cache({})
        self._save_searched([])
