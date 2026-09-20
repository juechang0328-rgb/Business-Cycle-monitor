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
    if PROFILE == "macro":
        return {"yahoo": MACRO_YAHOO, "fred": MACRO_FRED,
                "growth": ECON_GROWTH, "inflation": ECON_INFLATION,
                "dashboard": ECON_DASHBOARD, "reality": ECON_REALITY,
                "groups": MACRO_GROUPS, "health": MACRO_HEALTH,
                "unavailable": MACRO_UNAVAILABLE,
                "fixed_order": FIXED_ORDER_GROUPS}
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


# =================================================================== MACRO
# 總經儀表板：以描述「現在市場在發生什麼」為目的，不宣稱預測。
# 涵蓋景氣動能、通膨利率、央行流動性、金融壓力、市場情緒五塊。

MACRO_FRED = [
    # 景氣動能
    "PAYEMS", "UNRATE", "SAHMREALTIME", "INDPRO", "IC4WSA", "PERMIT",
    # 通膨與利率
    "PCEPILFE", "CPILFESL", "DFII10", "T10YIE",
    # 公債殖利率全期限（原始數據，利差由此推導而來）
    "DGS1MO", "DGS3MO", "DGS6MO", "DGS1", "DGS2", "DGS3",
    "DGS5", "DGS7", "DGS10", "DGS20", "DGS30",
    # 政策利率：曲線的左端錨點
    "DFEDTARU", "DFEDTARL", "DFF",
    # FOMC 點陣圖（Summary of Economic Projections）：每季更新，觀測日在未來
    "FEDTARMD", "FEDTARMDLR",
    # 央行流動性（單位不一致，見 bcm/derived.py）
    "WALCL", "WTREGEN", "RRPONTSYD", "DTWEXBGS",
    # 準備金稀缺程度：淨流動性想代理的其實是這件事，而這兩個是直接測量。
    "WRESBAL",          # 銀行體系準備金餘額（週三，百萬美元）
    "SOFR", "IORB",     # 擔保隔夜融資利率、準備金利率（皆為百分點）
    # 金融壓力
    "T10Y2Y", "T10Y3M", "BAMLH0A0HYM2", "NFCI",
    # NFCI 的三個子指數：拆開才知道緊或鬆是哪一塊造成的
    "NFCIRISK", "NFCICREDIT", "NFCILEVERAGE",
]

MACRO_YAHOO = [
    "HG=F", "GC=F", "CL=F", "^VIX", "^GSPC", "^IXIC",
    # 台股。^TWII 為發行量加權股價指數（上市），^TWOII 為櫃買指數（上櫃）。
    # 兩者的交易時段與美股不重疊，因此最新值通常比美股指數早一個日曆日。
    "^TWII", "^TWOII",
    "ZQ=F",   # 30 天期 Fed Funds 期貨（隱含利率 = 100 − 價格）
    # 資金流向比值用的 ETF（相對強弱，見 bcm/derived.py 的 RATIO_* 系列）
    "SPY",    # 標普500（市值加權）
    "RSP",    # 標普500 等權重 —— 與 SPY 的比值是市場廣度
    "IWM",    # 羅素2000 小型股
    "HYG",    # 高收益債
    "LQD",    # 投資級公司債
    # 能源
    "BZ=F",   # 布蘭特原油（CL=F 是西德州 WTI，兩者價差反映運輸與品質差異）
    "NG=F",   # 天然氣
    "RB=F",   # RBOB 汽油
    # 金屬
    "SI=F",   # 白銀
    "PL=F",   # 鉑
    "ALI=F",  # 鋁
    # 農產品
    "ZC=F",   # 玉米
    "ZW=F",   # 小麥
    "ZS=F",   # 黃豆
    "SB=F",   # 糖
    "KC=F",   # 咖啡
    "CT=F",   # 棉花
    # 綜合
    "DBC",    # 商品指數 ETF（廣泛）
    "DBA",    # 農產品 ETF
]

# 明確記錄「想要但拿不到」的序列 —— 不是遺漏，是已知限制。
# 沒有這份清單，抓不到的指標會變成靜默的缺口。
MACRO_UNAVAILABLE = [
    {"name": "ISM 製造業 PMI（新訂單−客戶存貨）", "symbol": "NAPM",
     "reason": "FRED 於 2016-06-24 應 ISM 要求移除全部 22 個 ISM 序列（授權問題）",
     "workaround": "ISM 官網僅提供當期；歷史需 DBnomics、investing.com 或付費源"},
    {"name": "MOVE 債券波動率指數", "symbol": "MOVE",
     "reason": "ICE BofA 專有資料，無免費 API",
     "workaround": "需 Bloomberg／Refinitiv 訂閱，或改用 ^TYX 波動度粗略替代"},
    {"name": "花旗經濟驚奇指數 CESI", "symbol": "CESIUSD",
     "reason": "Citigroup 專有資料，無免費 API",
     "workaround": "需 Bloomberg 或財經 M 平方訂閱"},
]

# 健康檢查用：(顯示名稱, 欄位代碼, 頻率)
MACRO_HEALTH = [
    ("非農就業",        "PAYEMS",       "monthly"),
    ("失業率",          "UNRATE",       "monthly"),
    ("Sahm Rule",       "SAHMREALTIME", "monthly"),
    ("工業生產",        "INDPRO",       "monthly"),
    ("初領失業金4週均",  "IC4WSA",       "weekly"),
    ("建照核發",        "PERMIT",       "monthly"),
    ("核心PCE",         "PCEPILFE",     "monthly"),
    ("核心CPI",         "CPILFESL",     "monthly"),
    ("10年實質利率",    "DFII10",       "daily"),
    ("10年期殖利率",    "DGS10",        "daily"),
    ("2年期殖利率",     "DGS2",         "daily"),
    ("通膨預期10Y",     "T10YIE",       "daily"),
    ("銀行準備金",      "WRESBAL",      "weekly"),
    ("SOFR",            "SOFR",         "daily"),
    ("準備金利率IORB",  "IORB",         "daily"),
    ("Fed 總資產",      "WALCL",        "weekly"),
    ("財政部TGA",       "WTREGEN",      "weekly"),
    ("隔夜逆回購",      "RRPONTSYD",    "daily"),
    ("美元指數",        "DTWEXBGS",     "daily"),
    ("10Y-2Y 利差",     "T10Y2Y",       "daily"),
    ("10Y-3M 利差",     "T10Y3M",       "daily"),
    ("高收益債利差",    "BAMLH0A0HYM2", "daily"),
    ("金融條件NFCI",    "NFCI",         "weekly"),
    ("銅",              "HG=F",         "daily"),
    ("黃金",            "GC=F",         "daily"),
    ("原油",            "CL=F",         "daily"),
    ("VIX",             "^VIX",         "daily"),
    ("標普500",         "^GSPC",        "daily"),
    ("納斯達克",        "^IXIC",        "daily"),
    ("SPY",             "SPY",          "daily"),
    ("RSP",             "RSP",          "daily"),
    ("IWM",             "IWM",          "daily"),
    ("HYG",             "HYG",          "daily"),
    ("LQD",             "LQD",          "daily"),
    ("台灣加權指數",    "^TWII",        "daily"),
    ("櫃買OTC指數",     "^TWOII",       "daily"),
    ("政策利率上限",    "DFEDTARU",     "daily"),
    ("政策利率下限",    "DFEDTARL",     "daily"),
    ("有效聯邦資金利率", "DFF",          "daily"),
    ("Fed Funds 期貨",  "ZQ=F",         "daily"),
    ("點陣圖中位數",    "FEDTARMD",     "projection"),
    ("點陣圖長期中位數", "FEDTARMDLR",  "quarterly"),
    ("1個月期殖利率",   "DGS1MO",       "daily"),
    ("3個月期殖利率",   "DGS3MO",       "daily"),
    ("6個月期殖利率",   "DGS6MO",       "daily"),
    ("1年期殖利率",     "DGS1",         "daily"),
    ("3年期殖利率",     "DGS3",         "daily"),
    ("5年期殖利率",     "DGS5",         "daily"),
    ("7年期殖利率",     "DGS7",         "daily"),
    ("20年期殖利率",    "DGS20",        "daily"),
    ("30年期殖利率",    "DGS30",        "daily"),
    ("NFCI風險",        "NFCIRISK",     "weekly"),
    ("NFCI信用",        "NFCICREDIT",   "weekly"),
    ("NFCI槓桿",        "NFCILEVERAGE", "weekly"),
    ("布蘭特原油",      "BZ=F",         "daily"),
    ("天然氣",          "NG=F",         "daily"),
    ("RBOB汽油",        "RB=F",         "daily"),
    ("白銀",            "SI=F",         "daily"),
    ("鉑",              "PL=F",         "daily"),
    ("鋁",              "ALI=F",        "daily"),
    ("玉米",            "ZC=F",         "daily"),
    ("小麥",            "ZW=F",         "daily"),
    ("黃豆",            "ZS=F",         "daily"),
    ("糖",              "SB=F",         "daily"),
    ("咖啡",            "KC=F",         "daily"),
    ("棉花",            "CT=F",         "daily"),
    ("商品指數DBC",     "DBC",          "daily"),
    ("農產品DBA",       "DBA",          "daily"),
]

# 這些區塊維持宣告順序，不依變化幅度重排 ——
# 天期順序本身就是資訊，打亂後曲線形狀就讀不出來了。
FIXED_ORDER_GROUPS = {"公債殖利率", "市場情緒", "資金流向"}

# 儀表板分組：(區塊標題, [(顯示名稱, 代碼, 呈現方式, 門檻或說明)])
# mode：pct=百分比變化、diff=絕對差、level=水準值
MACRO_GROUPS = [
    ("市場情緒", [
        # 這一區固定順序（見 FIXED_ORDER_GROUPS）：先看波動、再看美股、
        # 最後看台股，每天位置一樣才好比對。
        # price：主值是指數點位，變化以 % 呈現。
        # 用 pct 的話主值會變成「近三個月報酬率」，下面那行就成了
        # 「報酬率相對三個月前的報酬率」，差分做兩次，讀不出意思。
        ("VIX",         "^VIX",   "level", {"calm": 15, "stress": 25}),
        ("標普500",     "^GSPC",  "price", None),
        ("納斯達克",    "^IXIC",  "price", None),
        ("台灣加權指數", "^TWII",  "price", None),
        ("櫃買OTC指數",  "^TWOII", "price", None),
    ]),
    ("資金流向", [
        # 全是「A／B 的比值」。比值的絕對水準沒有意義，看的是走勢方向：
        # 上升代表資金往分子那一端流。這一區同樣固定順序，由「風險偏好」
        # 到「市場結構」排列。
        ("小型股／大型股",   "RATIO_SMALL_LARGE", "price", None),
        ("納斯達克／標普",   "RATIO_NDX_SPX",     "price", None),
        ("櫃買／加權",       "RATIO_OTC_TWSE",    "price", None),
        ("高收益債／投資級", "RATIO_HY_IG",       "price", None),
        ("循環股／防禦股",   "RATIO_CYC_DEF",     "price", None),
        ("等權重／市值加權", "RATIO_BREADTH",     "price", None),
    ]),
    ("景氣動能", [
        ("工業生產年增", "INDPRO",       "yoy",   None),
        ("非農就業3月年化", "PAYEMS",    "m3ann", None),
        ("初領失業金4週均", "IC4WSA",    "level", None),
        ("Sahm Rule",    "SAHMREALTIME", "level", {"warn": 0.50}),
        ("建照核發年增",  "PERMIT",      "yoy",   None),
        ("銅金比",       "COPPER_GOLD",  "level", None),
    ]),
    ("通膨與利率", [
        ("核心PCE年增",  "PCEPILFE",     "yoy",   {"target": 2.0}),
        ("核心CPI年增",  "CPILFESL",     "yoy",   {"target": 2.0}),
        ("10年實質利率", "DFII10",       "level", None),
        ("通膨預期10Y",  "T10YIE",       "level", None),
    ]),
    ("公債殖利率", [
        ("政策利率上限", "DFEDTARU", "level", None),
        ("有效聯邦資金利率", "DFF", "level", None),
        ("市場定價（期貨）", "FF_IMPLIED", "level", None),
        ("1個月",  "DGS1MO", "level", None),
        ("3個月",  "DGS3MO", "level", None),
        ("6個月",  "DGS6MO", "level", None),
        ("1年",    "DGS1",   "level", None),
        ("2年",    "DGS2",   "level", None),
        ("3年",    "DGS3",   "level", None),
        ("5年",    "DGS5",   "level", None),
        ("7年",    "DGS7",   "level", None),
        ("10年",   "DGS10",  "level", None),
        ("20年",   "DGS20",  "level", None),
        ("30年",   "DGS30",  "level", None),
    ]),
    ("央行流動性", [
        ("Fed 淨流動性", "NET_LIQ",      "level", None),
        ("銀行準備金",   "WRESBAL",      "level", None),
        ("SOFR−IORB",   "SOFR_IORB",    "level", {"scarce": 0.0}),
        ("Fed 總資產",   "WALCL",        "level", None),
        ("財政部TGA",    "WTREGEN",      "level", None),
        ("隔夜逆回購",   "RRPONTSYD",    "level", None),
        ("美元指數",     "DTWEXBGS",     "level", None),
    ]),
    ("金融壓力", [
        ("10Y-2Y 利差",  "T10Y2Y",       "level", {"invert_zone": 0.0}),
        ("10Y-3M 利差",  "T10Y3M",       "level", {"invert_zone": 0.0}),
        # FRED BAMLH0A0HYM2 的單位是「百分點」（3.20 = 320bp），
        # 門檻必須同單位。先前誤用基點數值，導致任何值都判為「極度冒險」。
        ("高收益債利差", "BAMLH0A0HYM2", "level",
         {"calm": 3.00, "normal": 4.50, "stress": 5.00, "unit": "pp"}),
        ("金融條件NFCI", "NFCI",         "level", {"tight": 0.0}),
        ("NFCI·風險",    "NFCIRISK",     "level", {"tight": 0.0}),
        ("NFCI·信用",    "NFCICREDIT",   "level", {"tight": 0.0}),
        ("NFCI·槓桿",    "NFCILEVERAGE", "level", {"tight": 0.0}),
    ]),
    ("原物料 · 能源", [
        ("WTI 原油",     "CL=F",     "pct", None),
        ("布蘭特原油",   "BZ=F",     "pct", None),
        ("天然氣",       "NG=F",     "pct", None),
        ("RBOB 汽油",    "RB=F",     "pct", None),
        ("油金比",       "OIL_GOLD", "level", None),
    ]),
    ("原物料 · 金屬", [
        ("黃金",   "GC=F", "pct", None),
        ("白銀",   "SI=F", "pct", None),
        ("銅",     "HG=F", "pct", None),
        ("鉑",     "PL=F", "pct", None),
        ("鋁",     "ALI=F", "pct", None),
    ]),
    ("原物料 · 農產品", [
        ("玉米",   "ZC=F", "pct", None),
        ("小麥",   "ZW=F", "pct", None),
        ("黃豆",   "ZS=F", "pct", None),
        ("糖",     "SB=F", "pct", None),
        ("咖啡",   "KC=F", "pct", None),
        ("棉花",   "CT=F", "pct", None),
    ]),
    ("原物料 · 綜合", [
        ("商品指數 DBC",   "DBC", "pct", None),
        ("農產品 DBA",     "DBA", "pct", None),
        ("銅金比",         "COPPER_GOLD", "level", None),
    ]),
]
