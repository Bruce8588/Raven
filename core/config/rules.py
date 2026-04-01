# 趋势规则配置

# 上涨/下跌阈值
RALLY_THRESHOLD = 1.06      # 6% 上涨触发趋势变化
PULLBACK_THRESHOLD = 0.94   # 6% 下跌触发趋势变化
BREAK_THRESHOLD = 0.97      # 3% 跌破关键点

# 趋势代号
TREND_UP = "up"
TREND_UP_NATURAL = "up_natural"
TREND_UP_RALLY = "up_rally"
TREND_UP_SECONDARY = "up_secondary"
TREND_UP_BREAK = "up_break"

TREND_DOWN = "down"
TREND_DOWN_NATURAL = "down_natural"
TREND_DOWN_RALLY = "down_rally"
TREND_DOWN_SECONDARY = "down_secondary"
TREND_DOWN_BREAK = "down_break"

# 趋势名称映射
TREND_NAMES = {
    "up": "上升趋势",
    "up_natural": "自然回撤",
    "up_rally": "回升",
    "up_secondary": "次级回撤",
    "up_break": "破碎",
    "down": "下跌趋势",
    "down_natural": "自然回升",
    "down_rally": "回撤",
    "down_secondary": "次级回升",
    "down_break": "破碎",
}

# 趋势体系
UP_TRENDS = {TREND_UP, TREND_UP_NATURAL, TREND_UP_RALLY, TREND_UP_SECONDARY, TREND_UP_BREAK}
DOWN_TRENDS = {TREND_DOWN, TREND_DOWN_NATURAL, TREND_DOWN_RALLY, TREND_DOWN_SECONDARY, TREND_DOWN_BREAK}
