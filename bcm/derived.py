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
