# 行情记录自动化追踪系统

## 系统用途

本系统用于**实时追踪股票趋势变化**，基于利弗莫尔规则（Livermore Rule），从配置时间点开始逐日/逐分钟监控趋势发展，并在趋势发生变化时生成报告。

## 核心逻辑

系统使用 TD交易系统 中的趋势判断引擎，追踪以下趋势状态：

| 趋势代码 | 趋势名称 | 含义 |
|---------|---------|------|
| up | 上升趋势 | 买入信号 |
| up_natural | 自然回撤 | 观望 |
| up_rally | 回升 | 买入机会 |
| up_secondary | 次级回撤 | 谨慎 |
| up_break | 破碎 | 离场信号 |
| down | 下跌趋势 | 卖出/做空 |
| down_natural | 自然回升 | 观望 |
| down_rally | 回撤 | 做空机会 |
| down_secondary | 次级回升 | 谨慎 |
| down_break | 破碎 | 反转信号 |

## 目录结构

```
行情记录/
├── CLAUDE.md              # 本文档
├── tracker.py             # 主程序入口
├── core/
│   ├── __init__.py
│   ├── config/
│   │   ├── __init__.py
│   │   └── rules.py       # 趋势规则配置
│   ├── trend.py           # 核心趋势引擎（从TD交易系统复制）
│   ├── analyzer.py        # 趋势分析器
│   └── reporter.py        # 报告生成器
├── fetcher/
│   ├── __init__.py
│   └── ifind.py           # iFinD 数据获取模块（从Star复制）
├── config/
│   ├── watchlist.json     # 自选股列表（从Star复制）
│   ├── initial_configs.csv # 全市场初始趋势配置
│   └── settings.json     # 系统设置
└── output/                # 报告输出目录
```

## 使用方法

### 1. 安装依赖

```bash
pip install pandas requests
```

### 2. 配置自选股

编辑 `config/watchlist.json`，添加需要追踪的股票：

```json
{
  "sh605305": {
    "code": "605305",
    "name": "中际联合",
    "market": "SH"
  }
}
```

### 3. 配置设置

编辑 `config/settings.json`：

```json
{
    "interval": 15,           // 轮询间隔（分钟）
    "notify_on_change": true, // 趋势变化时通知
    "output_dir": "output"    // 输出目录
}
```

### 4. 运行

```bash
# 持续追踪（每15分钟更新一次）
python tracker.py

# 仅运行一次
python tracker.py --once
```

### 5. 输出

每次运行会在 `output/` 目录下生成报告文件：
- `趋势追踪_YYYYMMDD_HHMMSS.csv`

报告包含：时间、股票代码、股票名称、当前价格、趋势代码、趋势名称、配置时间。

## 工作流程

1. **启动**：加载初始配置（`initial_configs.csv`）和自选股列表
2. **获取价格**：通过 iFinD API 获取自选股实时价格
3. **更新趋势**：对每只股票，基于当前价格更新趋势状态
4. **生成报告**：将结果保存为 CSV 文件
5. **等待**：按设置的间隔时间后重复

## 注意事项

- 确保 iFinD API 的 refresh_token 有效（见 `fetcher/ifind.py`）
- 初始配置应定期更新，以保持趋势判断的准确性
- 建议在交易时间内运行，以获取完整的趋势变化信息
