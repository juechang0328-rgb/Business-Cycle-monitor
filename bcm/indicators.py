"""指標設定。

預設使用 MVP 組合：最少的標的、全部免費免 API key、每天可自動更新。
想擴充時把 PROFILE 改成 "full"。
"""

PROFILE = "mvp"

# ===================================================================== MVP
# yfinance 抓價格；FRED 公開 CSV 抓利率（Yahoo 沒有 2 年期殖利率）
MVP_YAHOO = [
    "^GSPC",   # 標普500
    "GC=F",    # 黃金期貨
    "HG=F",    # 銅期貨
    "CL=F",    # 原油期貨
    "XLI",     # 工業類股（循環）
    "XLU",     # 公用事業（防禦）
]

MVP_FRED = [
    "DGS2", "DGS5", "DGS10",   # 2 / 5 / 10 年期公債殖利率
    "T10Y2Y",                  # 10年-2年利差
    "T10YIE",                  # 10年期損益兩平通膨率
]

# 成長軸：市場對「景氣好不好」的即時投票
MVP_GROWTH = [
    {"name": "銅金比",        "series": ("HG=F", "GC=F"), "mode": "pct",  "weight": 0.30},
    {"name": "循環股/防禦股", "series": ("XLI", "XLU"),   "mode": "pct",  "weight": 0.25},
    {"name": "股市動能",      "series": "^GSPC",          "mode": "pct",  "weight": 0.25},
    {"name": "殖利率曲線",    "series": "T10Y2Y",         "mode": "diff", "weight": 0.20},
]

# 通膨軸：決定債券與原物料箭頭
MVP_INFLATION = [
    {"name": "銅",         "series": "HG=F",   "mode": "pct",  "weight": 0.30},
    {"name": "原油",       "series": "CL=F",   "mode": "pct",  "weight": 0.30},
    {"name": "通膨預期",   "series": "T10YIE", "mode": "diff", "weight": 0.25},
    {"name": "黃金",       "series": "GC=F",   "mode": "pct",  "weight": 0.15},
]

MVP_DASHBOARD = [
    ("標普500",      "^GSPC",  "pct"),
    ("黃金",         "GC=F",   "pct"),
    ("銅",           "HG=F",   "pct"),
    ("原油",         "CL=F",   "pct"),
    ("2年期殖利率",  "DGS2",   "diff"),
    ("5年期殖利率",  "DGS5",   "diff"),
    ("10年期殖利率", "DGS10",  "diff"),
    ("10Y-2Y 利差",  "T10Y2Y", "diff"),
    ("通膨預期",     "T10YIE", "diff"),
]

# ==================================================================== FULL
# 擴充組合：多了信用利差、類股輪動、商品指數、VIX、美元
FULL_YAHOO = MVP_YAHOO + [
    "DBC", "XLY", "XLP", "SOXX", "IWM", "SPY",
    "HYG", "IEF", "TIP", "^VIX", "DX-Y.NYB",
]

FULL_FRED = MVP_FRED + ["T10Y3M", "DFII10", "BAMLH0A0HYM2"]

FULL_GROWTH = [
    {"name": "銅金比",          "series": ("HG=F", "GC=F"), "mode": "pct",  "weight": 0.22},
    {"name": "循環股/防禦股",   "series": ("XLI", "XLU"),   "mode": "pct",  "weight": 0.18},
    {"name": "信用風險偏好",    "series": ("HYG", "IEF"),   "mode": "pct",  "weight": 0.14},
    {"name": "可選/必需消費",   "series": ("XLY", "XLP"),   "mode": "pct",  "weight": 0.12},
    {"name": "小型股/大型股",   "series": ("IWM", "SPY"),   "mode": "pct",  "weight": 0.12},
    {"name": "半導體/大盤",     "series": ("SOXX", "SPY"),  "mode": "pct",  "weight": 0.12},
    {"name": "殖利率曲線",      "series": "T10Y2Y",         "mode": "diff", "weight": 0.10},
]

FULL_INFLATION = [
    {"name": "通膨預期",       "series": "T10YIE",       "mode": "diff", "weight": 0.25},
    {"name": "原油",           "series": "CL=F",         "mode": "pct",  "weight": 0.20},
    {"name": "銅",             "series": "HG=F",         "mode": "pct",  "weight": 0.20},
    {"name": "商品指數",       "series": "DBC",          "mode": "pct",  "weight": 0.20},
    {"name": "抗通膨債/公債",  "series": ("TIP", "IEF"), "mode": "pct",  "weight": 0.15},
]

FULL_DASHBOARD = MVP_DASHBOARD + [
    ("10Y-3M 利差",  "T10Y3M",       "diff"),
    ("10年實質利率", "DFII10",       "diff"),
    ("高收益債利差", "BAMLH0A0HYM2", "diff"),
    ("VIX",          "^VIX",         "diff"),
    ("美元指數",     "DX-Y.NYB",     "pct"),
]


# ------------------------------------------------------------------ 選用設定
def active() -> dict:
    if PROFILE == "full":
        return {"yahoo": FULL_YAHOO, "fred": FULL_FRED, "growth": FULL_GROWTH,
                "inflation": FULL_INFLATION, "dashboard": FULL_DASHBOARD}
    return {"yahoo": MVP_YAHOO, "fred": MVP_FRED, "growth": MVP_GROWTH,
            "inflation": MVP_INFLATION, "dashboard": MVP_DASHBOARD}


_a = active()
YAHOO_TICKERS = _a["yahoo"]
FRED_CODES = _a["fred"]
GROWTH_SPECS = _a["growth"]
INFLATION_SPECS = _a["inflation"]
DASHBOARD = _a["dashboard"]
