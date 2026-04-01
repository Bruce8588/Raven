# Raven 项目工作指南

**你是一个专业的量化交易系统开发助手。接管这个项目后，先通读本文档，再开始工作。**

---

## 项目概述

Raven 是一个股票趋势追踪 Web 系统，帮助用户追踪自选股的分钟级趋势变化。

- **项目路径**：`~/Desktop/Raven/`
- **访问地址**：http://localhost:5019
- **Git 仓库**：https://github.com/Bruce8588/Raven

---

## 技术栈

- **后端**：Python 3.13 + Flask
- **前端**：原生 HTML/CSS/JS（无框架）
- **数据源**：iFinD 金融数据接口
- **依赖**：pandas、requests、flask

---

## 目录结构

```
Raven/
├── web.py                    # Flask 主入口，路由和业务逻辑
├── background_updater.py     # 后台定时更新程序（守护进程）
├── cache.py                 # 缓存管理（stock_cache.json、searched_stocks.json）
├── config/
│   ├── watchlist.json       # 自选股配置列表
│   └── initial_configs.csv   # 初始配置表（趋势判断起点）
├── data/                    # 分钟K线数据（{symbol}_{code}_min1.csv）
├── output/
│   ├── 趋势判断/            # 当前最新趋势（{symbol}_趋势判断.csv）
│   └── 趋势历史/           # 完整分钟级趋势历史（{symbol}_趋势历史.csv）
├── cache/
│   ├── stock_cache.json     # 缓存的当前趋势数据
│   └── searched_stocks.json # 搜索历史记录
├── core/
│   └── analyzer.py          # 趋势分析核心算法
├── fetcher/
│   └── ifind.py             # iFinD 数据获取
├── templates/
│   ├── index.html           # 主页
│   └── trend_detail.html    # 趋势详情页
└── static/
    ├── css/style.css
    └── js/main.js
```

---

## 核心概念

### 趋势体系（10种状态）

每只股票在任意时刻处于以下10种趋势之一：

| 代码 | 名称 | 含义 |
|------|------|------|
| `up` | 上升趋势 | 持续创新高 |
| `up_natural` | 自然回撤 | 高点下跌6% |
| `up_rally` | 回升 | 低点反弹6% |
| `up_secondary` | 次级回撤 | 再次下跌 |
| `up_break` | 上升破碎 | 跌破关键点，转下跌 |
| `down` | 下跌趋势 | 持续创新低 |
| `down_natural` | 自然回升 | 低点反弹6% |
| `down_rally` | 回撤 | 高点下跌6% |
| `down_secondary` | 次级回升 | 再次上涨 |
| `down_break` | 下跌破碎 | 突破关键点，转上涨 |

**核心参数**：
- 上涨触发阈值：+6%（`RALLY_THRESHOLD = 1.06`）
- 下跌触发阈值：-6%（`PULLBACK_THRESHOLD = 0.94`）

**趋势点评**（用户可见）：
| 趋势 | 点评 |
|------|------|
| 上升/下跌趋势 | 进行中的单向运动 |
| 自然回撤/自然回升 | 正常反弹 |
| 回升/回撤 | 可能突破 |
| 次级回升/次级回撤 | 无意义的运动 |
| 上升/下跌破碎 | 趋势可能反转 |

### 关键点代号（配置和输出中统一使用英文代号）

| 代号 | 含义 |
|------|------|
| `key_high` | 关键高点 |
| `key_low` | 关键低点 |
| `n_high` | N值高点 |
| `n_low` | N值低点 |
| `rally_high` | 回升高点 |
| `rally_low` | 回撤低点 |
| `secondary_high` | 次级高点 |
| `secondary_low` | 次级低点 |
| `break_high` | 破碎阻力 |
| `break_low` | 破碎支撑 |

---

## 数据流

```
用户搜索 → /query 接口 → iFinD 获取数据 → analyzer 分析 → 缓存 + 输出文件
```

**三个数据层级**：

1. **分钟数据**（原始）
   - 路径：`data/{symbol}_{code}_min1.csv`
   - 字段：`day, high, low, close`

2. **趋势判断**（当前状态）
   - 路径：`output/趋势判断/{symbol}_趋势判断.csv`
   - 内容：当前趋势代码、趋势名称、全部关键点

3. **趋势历史**（完整记录）
   - 路径：`output/趋势历史/{symbol}_趋势历史.csv`
   - 内容：从配置点到最新时间的每分钟趋势变化

**两种趋势历史 CSV 格式**（需兼容）：
- **旧格式**：包含所有KP字段（`trend, trend_name, key_high, key_low...`）
- **新格式**：精简格式（`时间,价格,趋势,趋势名称,关键点名称,关键点`）

读取趋势历史时，**优先判断是否有 `trend` 字段**来判断格式。

---

## 关键 API 路由

| 路由 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 主页 |
| `/api/trends` | GET | 获取自选股列表（含趋势）|
| `/api/history` | GET | 获取历史搜索列表 |
| `/query` | POST | 搜索股票并返回趋势 |
| `/api/trend_detail/<symbol>` | GET | 获取某只股票的趋势详情 |

---

## 工作流程

### 1. 启动网站

```bash
cd ~/Desktop/Raven
python3 web.py
```

### 2. 修改代码后

修改 Python 文件后，Flask 会自动 reload（debug 模式）。
修改 HTML/JS 后，用户刷新浏览器即可。

### 3. 添加新股票到自选股

1. 编辑 `config/watchlist.json`，添加股票信息
2. 格式：`"sh002475": {"name": "立讯精密", "code": "002475", "market": "SH"}`

### 4. 补生成缺失的趋势文件

运行：
```bash
cd ~/Desktop/Raven
python3 /tmp/backfill_trends.py
```

### 5. 重启后台更新程序

```bash
# 杀掉旧进程
pkill -f "python3 web.py"
# 重新启动
cd ~/Desktop/Raven && python3 web.py > /tmp/raven_web.log 2>&1 &
```

---

## 趋势历史 CSV 格式说明

### 新格式（后台生成）
```
时间,价格,趋势,趋势名称,关键点名称,关键点
2026-03-24 09:30:00,27.42,up_natural,自然回撤,n_low,26.50
```
每条记录代表一个关键点变化。

### 旧格式（早期生成）
```
时间,day,high,low,close,trend,trend_name,key_high,key_low,...
```
每条记录代表一分钟的完整状态。

**读取时判断格式**：
```python
df = pd.read_csv(csv_path)
if 'trend' in df.columns:
    # 旧格式：每分钟完整数据
else:
    # 新格式：关键点变化记录
```

---

## 前端关键逻辑（main.js）

### 显示函数

| 函数 | 作用 |
|------|------|
| `showResult(data)` | 显示查询结果大卡片 |
| `renderStocks()` | 渲染自选股列表 |
| `renderHistory()` | 渲染历史搜索列表 |
| `filterStocksByNames()` | 过滤股票列表 |

### 关键数据字段

| 字段 | 说明 |
|------|------|
| `data.trend_code` | 趋势代码（如 `up_natural`）|
| `data.trend_name` | 趋势名称（如 `自然回撤`）|
| `data.description` | 趋势描述（已简化为不含KP代号）|
| `data.signal_color` | 信号颜色 |
| `TREND_DESC[trend_code]` | 趋势点评（5字）|

### 跳转逻辑

- 整张卡片可点击 → `goToDetail(symbol)`
- 不再需要📊按钮

---

## 趋势详情页（trend_detail.html）

### 数据来源

- `/api/trend_detail/<symbol>` 返回的数据
- `records`：趋势历史（优先）或趋势判断
- `minute_records`：分钟K线数据（500条）

### 展示模块

1. **配置信息区块**：配置日期、初始趋势、相关关键点
2. **每分钟数据区块**：时间、趋势、趋势名称、价格、关键点

### 关键JS函数

| 函数 | 作用 |
|------|------|
| `loadTrendDetail()` | 加载并渲染详情页 |
| `renderHeader()` | 渲染股票头部信息 |
| `renderConfigInfo()` | 渲染配置信息（只显示相关KP）|
| `renderMinuteSection()` | 渲染分钟级趋势记录（滑条控制）|

### 每分钟数据格式（API返回）

```json
{
  "time": "2026-03-24 09:30",
  "trend_code": "up_natural",
  "trend_name": "自然回撤",
  "close": 27.42,
  "自然回撤": 26.50,
  "remark": "自然回撤"
}
```

---

## 调试方法

### 查看后端日志
```bash
tail -f /tmp/raven_web.log
```

### 测试 API
```bash
curl http://localhost:5019/api/trends
curl http://localhost:5019/api/trend_detail/sh600406
```

### 查看数据文件
```bash
cat ~/Desktop/Raven/cache/stock_cache.json | python3 -m json.tool | head -50
cat ~/Desktop/Raven/output/趋势判断/sh600406_趋势判断.csv
```

---

## 重要规则

1. **修改后端代码后**，确认网站仍能正常启动
2. **修改前端代码后**，让用户强制刷新（Cmd+Shift+R）
3. **不要直接修改 `cache/stock_cache.json`**，通过 `cache.py` 的 API 操作
4. **搜索历史只能通过搜索产生**，后台更新不应该调用 `add_searched()`
5. **数据唯一真实源**是 `output/趋势判断/` 和 `output/趋势历史/` 文件夹
6. **输出 CSV 时使用 UTF-8 编码**

---

## 常见问题

### Q: 趋势详情页显示空白
A: 检查 `/api/trend_detail/<symbol>` 返回的 `records` 是否为空，可能趋势历史 CSV 缺失或格式不匹配

### Q: 历史搜索里出现自选股
A: 后台更新程序错误调用了 `add_searched()`，检查 `background_updater.py`

### Q: 数据格式不匹配
A: 趋势历史 CSV 有新旧两种格式，后端读取时需兼容判断

### Q: 某只股票没有趋势数据
A: 检查 `data/` 是否有分钟数据文件，`output/趋势判断/` 是否有判断文件

---

## 提交规范

修改代码后，在 `~/Desktop/Raven/` 目录下提交：

```bash
cd ~/Desktop/Raven
git add .
git commit -m "[类型] 简短描述"
git push
```

提交类型：新增、修改、修复、优化、文档、配置
