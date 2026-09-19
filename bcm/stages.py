"""階段判定：把 (G, dG, I, dI) 映射到景氣循環六階段，並加上遲滯避免頻繁跳動。"""
from __future__ import annotations

import pandas as pd

STAGE_NAMES = {
    1: "景氣衰退", 2: "景氣谷底", 3: "景氣復甦",
    4: "景氣擴張", 5: "景氣高峰", 6: "景氣趨緩",
}

# 圖中三個箭頭：債券 / 股票 / 原物料
STAGE_ASSETS = {
    1: ("債↑", "股↓", "原物料↓"),
    2: ("債↑", "股↑", "原物料↓"),
    3: ("債↑", "股↑", "原物料↑"),
    4: ("債↓", "股↑", "原物料↑"),
    5: ("債↓", "股↓", "原物料↑"),
    6: ("債↓", "股↓", "原物料↓"),
}


def classify_point(g: float, dg: float, i: float) -> int:
    """單點判定。

    邏輯（對應原圖的三個箭頭）：
      成長在線上 (G>=0)
        動能仍為正 → 通膨仍低 = 復甦(3)；通膨已起 = 擴張(4)
        動能轉負   → 高峰(5)          ← 成長率高點已過，這是 4 與 5 的分界
      成長在線下 (G<0)
        動能轉正   → 谷底(2)          ← 跌勢趨緩，股票先落底
        動能仍為負 → 通膨仍高 = 趨緩(6)；通膨已落 = 衰退(1)
                                       （6 與 1 的分界＝債券箭頭何時翻正）
    """
    if pd.isna(g) or pd.isna(dg) or pd.isna(i):
        return 0
    if g >= 0:
        if dg > 0:
            return 3 if i < 0 else 4
        return 5
    if dg >= 0:
        return 2
    return 6 if i >= 0 else 1


def classify(G: pd.Series, dG: pd.Series, I: pd.Series) -> pd.Series:
    """逐日的原始判定（未加遲滯）。"""
    return pd.Series(
        [classify_point(g, dg, i) for g, dg, i in zip(G, dG, I)],
        index=G.index, name="raw_stage",
    )


def apply_hysteresis(raw: pd.Series, confirm: int = 63) -> pd.Series:
    """遲滯：新階段需連續 `confirm` 個交易日成立才正式換檔。

    預設 63 個交易日（約三個月）。這個值是實測出來的：景氣階段持續的單位是
    「季」而不是「週」，確認期設太短（例如兩週）會讓判定在日頻雜訊下不停跳動，
    時間軸被切成幾十段碎片，反而讀不出循環。
    """
    out, current, streak, pending = [], 0, 0, 0
    for v in raw:
        if v == 0:                      # 資料不足
            out.append(current)
            continue
        if current == 0:                # 首次取得有效判定，直接建立
            current, streak, pending = v, 0, v
            out.append(current)
            continue
        if v == current:
            streak, pending = 0, current
        else:
            streak = streak + 1 if v == pending else 1
            pending = v
            if streak >= confirm:
                current, streak = v, 0
        out.append(current)
    return pd.Series(out, index=raw.index, name="stage")


def run(G: pd.Series, I: pd.Series, freq: str = "ME",
        momentum_periods: int = 3, confirm: int = 2) -> pd.DataFrame:
    """完整流程：由 G/I 算出動能、原始階段與遲滯後的正式階段。

    階段判定在**月頻**上進行，不是日頻。原因是實測出來的：
    日頻的原始判定中位連續長度只有 2 天，因此任何「需連續 N 日」的遲滯條件
    要嘛形同虛設（N 小），要嘛永遠達不到而把階段鎖死（N 大）。
    景氣階段本來就是月度概念，在月頻上判定才有意義。

    G/I 仍以日頻回傳供圖表使用；階段以月頻判定後再展開回日頻。
    """
    g_m = G.resample(freq).last().dropna()
    i_m = I.resample(freq).last().dropna()
    dg_m = g_m - g_m.shift(momentum_periods)
    raw_m = classify(g_m, dg_m, i_m)
    stage_m = apply_hysteresis(raw_m, confirm=confirm)

    dG = (G.resample(freq).last() - G.resample(freq).last().shift(momentum_periods)
          ).reindex(G.index, method="ffill")
    dI = (I.resample(freq).last() - I.resample(freq).last().shift(momentum_periods)
          ).reindex(I.index, method="ffill")
    return pd.DataFrame({
        "G": G, "dG": dG, "I": I, "dI": dI,
        "raw_stage": raw_m.reindex(G.index, method="ffill").fillna(0).astype(int),
        "stage": stage_m.reindex(G.index, method="ffill").fillna(0).astype(int),
    })


def describe(stage: int) -> str:
    if stage == 0:
        return "資料不足"
    b, e, c = STAGE_ASSETS[stage]
    return f"階段{stage} {STAGE_NAMES[stage]}（{b} {e} {c}）"
