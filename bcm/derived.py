"""衍生序列：由多個原始序列計算而來的指標。

單位是這裡最容易出錯的地方。FRED 各序列的單位並不一致 ——
例如 WALCL 與 WTREGEN 以百萬美元計，RRPONTSYD 卻以十億美元計。
直接相減會差 1000 倍，而且不會報錯，只會安靜地算出錯的數字。
因此每個衍生序列都必須明確寫出單位換算，並在此處集中管理。
"""
from __future__ import annotations

import pandas as pd

# 每個衍生序列：需要哪些原始欄位、怎麼算、單位、以及為何這樣算
DERIVED = {
    "NET_LIQ": {
        "name": "Fed 淨流動性",
        "requires": ["WALCL", "WTREGEN", "RRPONTSYD"],
        # WALCL、WTREGEN 單位為百萬美元；RRPONTSYD 為十億美元，需 ×1000
        "fn": lambda p: p["WALCL"] - p["WTREGEN"] - p["RRPONTSYD"] * 1000,
        "unit": "百萬美元",
        "scale": 1e-6,          # 顯示時換算為兆美元
        "display_unit": "兆美元",
        "note": "WALCL − WTREGEN − RRPONTSYD×1000（RRPONTSYD 以十億計，需轉百萬）",
    },
    "COPPER_GOLD": {
        "name": "銅金比",
        "requires": ["HG=F", "GC=F"],
        "fn": lambda p: p["HG=F"] / p["GC=F"] * 1000,
        "unit": "比值×1000",
        "scale": 1.0,
        "display_unit": "",
        "note": "COMEX 銅／黃金，乘 1000 便於閱讀",
    },
    "OIL_GOLD": {
        "name": "油金比",
        "requires": ["CL=F", "GC=F"],
        "fn": lambda p: p["CL=F"] / p["GC=F"] * 1000,
        "unit": "比值×1000",
        "scale": 1.0,
        "display_unit": "",
        "note": "WTI 原油／黃金，乘 1000 便於閱讀",
    },
    "FF_IMPLIED": {
        "name": "期貨隱含政策利率",
        "requires": ["ZQ=F"],
        # 30 天期 Fed Funds 期貨的報價慣例：隱含利率 = 100 − 價格
        "fn": lambda p: 100 - p["ZQ=F"],
        "unit": "%",
        "scale": 1.0,
        "display_unit": "",
        "note": "100 − ZQ=F 價格。這是近月合約，反映未來約一個月的政策利率定價",
    },
    "SOFR_IORB": {
        "name": "SOFR − IORB 利差",
        "requires": ["SOFR", "IORB"],
        # 兩者同為百分點，可直接相減。這是「準備金夠不夠」最直接的溫度計：
        # 附買回市場的隔夜利率高於 Fed 付給銀行的準備金利率，代表市場上搶錢。
        "fn": lambda p: (p["SOFR"] - p["IORB"]) * 100,
        "unit": "基點",
        "scale": 1.0,
        "display_unit": "bp",
        "note": "(SOFR − IORB)×100；長期為負或零，轉正且持續＝準備金開始稀缺",
    },
    # ---------------------------------------------------- 資金流向（相對強弱）
    # 這一組全是「A／B 的比值」。比值的絕對水準沒有意義，看的是它在自己
    # 歷史區間裡的位置，以及走勢方向：上升代表資金往分子那一端流。
    # 一律乘 100 只是為了讓數字好讀，不影響變化率。
    "RATIO_NDX_SPX": {
        "name": "納斯達克／標普500",
        "requires": ["^IXIC", "^GSPC"],
        "fn": lambda p: p["^IXIC"] / p["^GSPC"] * 100,
        "unit": "比值×100",
        "scale": 1.0,
        "display_unit": "",
        "note": "成長股相對大盤；上升＝資金偏好成長與科技",
    },
    "RATIO_SMALL_LARGE": {
        "name": "小型股／大型股",
        "requires": ["IWM", "SPY"],
        "fn": lambda p: p["IWM"] / p["SPY"] * 100,
        "unit": "比值×100",
        "scale": 1.0,
        "display_unit": "",
        "note": "羅素2000／標普500；上升＝風險偏好提高，資金下沉到小型股",
    },
    "RATIO_OTC_TWSE": {
        "name": "櫃買／加權",
        "requires": ["^TWOII", "^TWII"],
        "fn": lambda p: p["^TWOII"] / p["^TWII"] * 10000,
        "unit": "比值×10000",
        "scale": 1.0,
        "display_unit": "",
        "note": "台股中小型股相對權值股；上升＝散戶與投機資金活躍",
    },
    "RATIO_BREADTH": {
        "name": "等權重／市值加權",
        "requires": ["RSP", "SPY"],
        "fn": lambda p: p["RSP"] / p["SPY"] * 100,
        "unit": "比值×100",
        "scale": 1.0,
        "display_unit": "",
        "note": "RSP／SPY；下降＝漲勢集中在少數權值股（市場廣度變差）",
    },
    # 這裡曾經有 HYG／LQD 的「高收益債／投資級」比值，已移除。
    # 原因：HYG 存續期約 3.5 年、LQD 約 8.5 年，升息時 LQD 單純因為天期長
    # 而跌更多，比值就上升。實測近三個月比值 +2.47%，而「存續期差 5 年 ×
    # 殖利率 +0.48pp」的純利率效應就有 +2.40% —— 97% 與信用風險無關。
    # 同期真正的信用指標（高收益債利差 OAS）反而走闊 +0.04pp，方向相反。
    # 信用風險偏好看 BAMLH0A0HYM2 就好，它的定義本身已扣掉利率與存續期。
    "RATIO_CYC_DEF": {
        "name": "循環股／防禦股",
        "requires": ["XLI", "XLU"],
        "fn": lambda p: p["XLI"] / p["XLU"] * 100,
        "unit": "比值×100",
        "scale": 1.0,
        "display_unit": "",
        "note": "工業／公用事業；上升＝押景氣向上，下降＝往防禦類股避險",
    },
    "SAHM_GAP": {
        "name": "Sahm Rule 缺口",
        "requires": ["UNRATE"],
        # 正確定義：3個月移動平均失業率 − 前12個月「該移動平均」的最低值
        # （不是減原始失業率的最低值，這是常見錯誤）
        "fn": lambda p: (
            p["UNRATE"].rolling(3).mean()
            - p["UNRATE"].rolling(3).mean().rolling(12).min()
        ),
        "unit": "百分點",
        "scale": 1.0,
        "display_unit": "pp",
        "note": "3MMA(UNRATE) − min(前12個月的 3MMA)；≥0.50 歷史上幾乎必然衰退",
    },
}


def available(panel: pd.DataFrame, key: str) -> bool:
    """該衍生序列所需的原始欄位是否齊備且有值。"""
    spec = DERIVED[key]
    return all(c in panel.columns and panel[c].notna().any()
               for c in spec["requires"])


def missing_inputs(panel: pd.DataFrame, key: str) -> list[str]:
    spec = DERIVED[key]
    return [c for c in spec["requires"]
            if c not in panel.columns or panel[c].isna().all()]


def add_derived(panel: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    """把所有可計算的衍生序列加入面板。

    回傳 (面板, {無法計算的序列: 缺少的原始欄位})。
    缺料時不靜默跳過 —— 呼叫端要能把它顯示出來。
    """
    out = panel.copy()
    skipped: dict[str, list[str]] = {}
    for key, spec in DERIVED.items():
        if available(out, key):
            try:
                out[key] = spec["fn"](out)
            except Exception as e:                # 計算失敗一樣要留下痕跡
                skipped[key] = [f"計算失敗：{e}"]
        else:
            skipped[key] = missing_inputs(out, key)
    return out, skipped
