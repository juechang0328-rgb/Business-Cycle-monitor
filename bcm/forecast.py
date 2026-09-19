"""下一階段推估。

機率**不是模型預測**，而是歷史基準率：在過去出現過的同一階段中，
下一段實際走到哪裡的次數佔比。因此每個機率都必須連同樣本數一起呈現 ——
樣本數只有個位數時，那個百分比幾乎沒有意義。
"""
from __future__ import annotations

import pandas as pd

from . import stages

# 判定使用的三個開關（見 stages.classify_point）
SWITCHES = {
    "g":  "成長分數 G 高於歷史平均",
    "dg": "成長動能仍在上升",
    "i":  "通膨分數 I 高於歷史平均",
}

# 每個階段所需的開關組合：(g>=0, dg>0, i>=0)；None 表示該開關不影響
STAGE_CONDITIONS = {
    1: (False, False, False),
    2: (False, True, None),
    3: (True, True, False),
    4: (True, True, True),
    5: (True, False, None),
    6: (False, False, True),
}

# 開關翻轉的白話意義（對應投影片的三個箭頭）
FLIP_MEANING = {
    ("i", True):   "原物料與通膨動能由弱轉強 → 債券由漲轉跌",
    ("i", False):  "原物料與通膨動能由強轉弱 → 債券由跌轉漲",
    ("dg", True):  "成長動能止跌回升 → 股票領先落底",
    ("dg", False): "成長動能見頂回落 → 股票開始領先下跌",
    ("g", True):   "成長分數站上歷史平均 → 景氣落入擴張側",
    ("g", False):  "成長分數跌破歷史平均 → 景氣落入收縮側",
}


def monthly_stages(result: pd.DataFrame) -> pd.Series:
    s = result["stage"].resample("ME").last()
    return s[s > 0].astype(int)


def transition_counts(result: pd.DataFrame) -> pd.DataFrame:
    """歷史上各階段的下一段落點次數。"""
    st = monthly_stages(result)
    runs = st.ne(st.shift()).cumsum()
    seq = list(st.groupby(runs).first())
    tr = pd.DataFrame(0, index=range(1, 7), columns=range(1, 7), dtype=int)
    for a, b in zip(seq, seq[1:]):
        tr.loc[a, b] += 1
    return tr


def durations(result: pd.DataFrame) -> dict[int, pd.Series]:
    st = monthly_stages(result)
    runs = st.ne(st.shift()).cumsum()
    first = st.groupby(runs).first()
    size = st.groupby(runs).size()
    return {s: size[first == s] for s in range(1, 7)}


def distance_to_boundary(G: float, dG: float, I: float, target: int) -> list[dict]:
    """要走到 target 階段，哪些開關必須翻轉、目前距離門檻多遠。"""
    want = STAGE_CONDITIONS[target]
    now = {"g": G >= 0, "dg": dG > 0, "i": I >= 0}
    values = {"g": G, "dg": dG, "i": I}
    out = []
    for key, need in zip(("g", "dg", "i"), want):
        if need is None or now[key] == need:
            continue
        out.append({
            "switch": key,
            "need": need,
            "current": values[key],
            "gap": abs(values[key]),          # 距離 0 這條分界線的距離
            "text": FLIP_MEANING[(key, need)],
        })
    return out


def next_stage_outlook(result: pd.DataFrame, top: int = 3) -> dict:
    """彙整：目前階段、已持續多久、歷史上下一段最可能走到哪裡。"""
    d = result.dropna(subset=["G", "I"])
    last = d.iloc[-1]
    cur = int(last["stage"])
    st = monthly_stages(result)
    runs = st.ne(st.shift()).cumsum()
    elapsed = int((runs == runs.iloc[-1]).sum())

    tr = transition_counts(result)
    n = int(tr.loc[cur].sum()) if cur in tr.index else 0
    probs = []
    if n:
        p = (tr.loc[cur] / n).sort_values(ascending=False)
        for nxt, prob in p.items():
            if prob <= 0:
                continue
            probs.append({
                "stage": int(nxt),
                "name": stages.STAGE_NAMES[int(nxt)],
                "prob": float(prob),
                "count": int(tr.loc[cur, nxt]),
                "flips": distance_to_boundary(last["G"], last["dG"],
                                              last["I"], int(nxt)),
            })
    dur = durations(result).get(cur, pd.Series(dtype=int))
    return {
        "current": cur,
        "elapsed_months": elapsed,
        "median_duration": float(dur.median()) if len(dur) else float("nan"),
        "sample_size": n,
        "candidates": probs[:top],
        "raw_stage": int(last["raw_stage"]),
        "G": float(last["G"]), "dG": float(last["dG"]), "I": float(last["I"]),
    }


def asset_momentum(panel: pd.DataFrame, lookback: int = 63) -> list[dict]:
    """債券／股票／原物料的三個月動能排序 —— 投影片三個箭頭的當前讀數。"""
    out = []
    specs = [
        ("債券", lambda p: -p["DGS10"].diff(lookback), "殖利率下降＝債券價格上漲", "pp"),
        ("股票", lambda p: p["^GSPC"].pct_change(lookback) * 100, "標普500", "%"),
        ("原物料", lambda p: (p["CL=F"].pct_change(lookback)
                             + p["HG=F"].pct_change(lookback)) / 2 * 100,
         "原油與銅的平均", "%"),
    ]
    for name, fn, note, unit in specs:
        try:
            v = fn(panel).dropna()
            if len(v):
                out.append({"name": name, "value": float(v.iloc[-1]),
                            "unit": unit, "note": note})
        except KeyError:
            continue
    return sorted(out, key=lambda x: x["value"], reverse=True)
