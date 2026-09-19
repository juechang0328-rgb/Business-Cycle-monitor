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
    # 以下兩項不計入分數，僅作為「實體經濟對照」——
    # 用真實經濟數據檢驗市場訊號有沒有說對
    "IC4WSA",                  # 初領失業金4週移動平均（週頻）
    "INDPRO",                  # 工業生產指數（月頻）
]

# 實體經濟對照：(標題, 代碼, 轉換, 說明, 方向)
# 方向 up_is_good=False 表示數值上升代表景氣轉壞
REALITY_CHECK = [
    ("初領失業金 4 週均", "IC4WSA", "level",
     "企業開始裁員的最早訊號，週頻公布。上升＝景氣轉壞。", False),
    ("工業生產年增率", "INDPRO", "yoy",
     "實際生產了多少東西。這是景氣本身，不是對景氣的預期。", True),
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
    if PROFILE == "econ":
        return {"yahoo": [], "fred": ECON_FRED, "growth": ECON_GROWTH,
                "inflation": ECON_INFLATION, "dashboard": ECON_DASHBOARD,
                "reality": ECON_REALITY}
    if PROFILE == "full":
        return {"yahoo": FULL_YAHOO, "fred": FULL_FRED, "growth": FULL_GROWTH,
                "inflation": FULL_INFLATION, "dashboard": FULL_DASHBOARD}
    return {"yahoo": MVP_YAHOO, "fred": MVP_FRED, "growth": MVP_GROWTH,
            "inflation": MVP_INFLATION, "dashboard": MVP_DASHBOARD}


_a = active()
REALITY_CHECK = _a.get("reality", REALITY_CHECK)
YAHOO_TICKERS = _a["yahoo"]
FRED_CODES = _a["fred"]
GROWTH_SPECS = _a["growth"]
INFLATION_SPECS = _a["inflation"]
DASHBOARD = _a["dashboard"]


# ==================================================================== ECON
# 以「具實證領先性質的經濟指標」建構，而非市場價格動能。
# 選用原則：全部在 FRED（免 API key），且歷史夠長 —— 這是能不能驗證的關鍵。
# 市場 ETF（XLI/XLU 等）1998 年才有，econ 組合可回溯到 1967 年，
# 涵蓋約 8 次衰退而非 1 次。
ECON_FRED = [
    # --- 成長軸：領先指標 ---
    "PERMIT",        # 建照核發（1960-）利率最敏感部門，歷史上最可靠的單一領先指標
    "IC4WSA",        # 初領失業金4週均（1967-）週頻，轉折極靈敏
    "AWHMAN",        # 製造業每週工時（1939-）先減工時再減人
    "T10Y2Y",        # 殖利率曲線 10Y-2Y（1976-）用水準，不用動能
    "NEWORDER",      # 核心資本財新訂單（1992-）企業資本支出意願
    # --- 通膨軸 ---
    "CPIAUCSL",      # CPI（1947-）
    "PPIACO",        # 生產者物價（1913-）領先 CPI 約 1-2 季
    "T10YIE",        # 損益兩平通膨率（2003-）
    # --- 驗證目標（不計入分數）---
    "INDPRO",        # 工業生產（1919-）代表「景氣本身」
    "USREC",         # NBER 衰退認定（1854-）官方答案
    "UNRATE",        # 失業率（1948-）
]

ECON_GROWTH = [
    {"name": "建照核發",      "series": "PERMIT",   "mode": "pct",  "weight": 0.25},
    {"name": "初領失業金",    "series": "IC4WSA",   "mode": "pct",  "weight": 0.25,
     "invert": True},
    {"name": "製造業工時",    "series": "AWHMAN",   "mode": "pct",  "weight": 0.15},
    {"name": "殖利率曲線",    "series": "T10Y2Y",   "mode": "diff", "weight": 0.20},
    {"name": "資本財新訂單",  "series": "NEWORDER", "mode": "pct",  "weight": 0.15},
]

ECON_INFLATION = [
    {"name": "CPI",        "series": "CPIAUCSL", "mode": "pct",  "weight": 0.40},
    {"name": "PPI",        "series": "PPIACO",   "mode": "pct",  "weight": 0.35},
    {"name": "通膨預期",   "series": "T10YIE",   "mode": "diff", "weight": 0.25},
]

ECON_DASHBOARD = [
    ("建照核發",     "PERMIT",   "pct"),
    ("初領失業金",   "IC4WSA",   "pct"),
    ("工業生產",     "INDPRO",   "pct"),
    ("失業率",       "UNRATE",   "diff"),
    ("10Y-2Y 利差",  "T10Y2Y",   "diff"),
    ("CPI",          "CPIAUCSL", "pct"),
]

ECON_REALITY = [
    ("工業生產年增率", "INDPRO", "yoy",
     "景氣本身。模型若有效，G 轉折應領先這條線數個月。", True),
    ("失業率", "UNRATE", "level",
     "落後指標，用來事後確認衰退是否真的發生。", False),
]
