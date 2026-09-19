"""日頻指標設定 —— 全部免費、免 API key、每天可自動更新。

分工：
  yfinance → 價格（股票、ETF、期貨）
  FRED CSV → 殖利率與利差（Yahoo 沒有 2 年期殖利率，FRED 有且更乾淨）
"""

# ---------------------------------------------------------------- 原始資料來源
YAHOO_TICKERS = [
    "^GSPC",   # 標普500
    "GC=F",    # 黃金期貨
    "HG=F",    # 銅期貨
    "CL=F",    # 西德州原油期貨
    "DBC",     # 商品指數 ETF
    "XLI", "XLU",   # 工業 / 公用事業（循環 vs 防禦）
    "XLY", "XLP",   # 可選消費 / 必需消費
    "SOXX",         # 半導體
    "IWM", "SPY",   # 小型股 / 大型股
    "HYG", "IEF",   # 高收益債 / 7-10年公債（信用風險偏好）
    "TIP",          # 抗通膨公債（vs IEF ＝ 市場的通膨預期）
    "^VIX",         # 波動率
    "DX-Y.NYB",     # 美元指數
]

FRED_CODES = [
    "DGS2", "DGS5", "DGS10",   # 2 / 5 / 10 年期公債殖利率
    "T10Y2Y",                  # 10年-2年利差
    "T10Y3M",                  # 10年-3個月利差
    "DFII10",                  # 10年期實質利率（TIPS）
    "T10YIE",                  # 10年期損益兩平通膨率
    "BAMLH0A0HYM2",            # 高收益債利差 OAS
]

# ------------------------------------------------------------------ 成長軸 (G)
# series 為 tuple 表示比值；mode="pct" 用變動率，"diff" 用絕對差（已是百分點者）
GROWTH_SPECS = [
    {"name": "銅金比",          "series": ("HG=F", "GC=F"), "mode": "pct",  "weight": 0.22},
    {"name": "循環股/防禦股",    "series": ("XLI", "XLU"),   "mode": "pct",  "weight": 0.18},
    {"name": "信用風險偏好",     "series": ("HYG", "IEF"),   "mode": "pct",  "weight": 0.14},
    {"name": "可選/必需消費",    "series": ("XLY", "XLP"),   "mode": "pct",  "weight": 0.12},
    {"name": "小型股/大型股",    "series": ("IWM", "SPY"),   "mode": "pct",  "weight": 0.12},
    {"name": "半導體/大盤",      "series": ("SOXX", "SPY"),  "mode": "pct",  "weight": 0.12},
    {"name": "殖利率曲線10Y-2Y", "series": "T10Y2Y",         "mode": "diff", "weight": 0.10},
]

# ------------------------------------------------------------------ 通膨軸 (I)
INFLATION_SPECS = [
    {"name": "通膨預期10Y",   "series": "T10YIE",       "mode": "diff", "weight": 0.25},
    {"name": "原油",          "series": "CL=F",         "mode": "pct",  "weight": 0.20},
    {"name": "銅",            "series": "HG=F",         "mode": "pct",  "weight": 0.20},
    {"name": "商品指數",      "series": "DBC",          "mode": "pct",  "weight": 0.20},
    {"name": "抗通膨債/公債", "series": ("TIP", "IEF"), "mode": "pct",  "weight": 0.15},
]

# -------------------------------------------------- 儀表板（僅顯示，不計入分數）
DASHBOARD = [
    ("標普500",        "^GSPC",         "pct"),
    ("黃金",           "GC=F",          "pct"),
    ("2年期殖利率",    "DGS2",          "diff"),
    ("5年期殖利率",    "DGS5",          "diff"),
    ("10年期殖利率",   "DGS10",         "diff"),
    ("10Y-2Y 利差",    "T10Y2Y",        "diff"),
    ("10Y-3M 利差",    "T10Y3M",        "diff"),
    ("10年實質利率",   "DFII10",        "diff"),
    ("高收益債利差",   "BAMLH0A0HYM2",  "diff"),
    ("VIX",            "^VIX",          "diff"),
    ("美元指數",       "DX-Y.NYB",      "pct"),
]
