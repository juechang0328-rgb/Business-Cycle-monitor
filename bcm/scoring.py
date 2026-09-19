"""評分層：把原始價格面板轉成成長分數 G 與通膨分數 I。

純函數，不碰網路，可單獨測試。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS_3M = 63
ZSCORE_WINDOW = 756  # 約 3 年


def ratio(panel: pd.DataFrame, numerator: str, denominator: str) -> pd.Series:
    """兩個標的的比值，例如 XLI/XLU、銅金比。"""
    return panel[numerator] / panel[denominator]


def momentum(s: pd.Series, lookback: int = TRADING_DAYS_3M,
             mode: str = "pct") -> pd.Series:
    """動能：價格類用變動率，利率／利差類用絕對差值。

    mode="pct"  → 適用價格與比值（如銅金比、XLI/XLU）
    mode="diff" → 適用本身已是百分點的序列（如 10Y-2Y 利差、HY OAS）
    """
    if mode == "pct":
        return s.pct_change(lookback)
    if mode == "diff":
        return s.diff(lookback)
    raise ValueError(f"未知的 mode: {mode}")


def zscore(s: pd.Series, window: int = ZSCORE_WINDOW, min_periods: int = 252) -> pd.Series:
    """滾動 z-score。樣本不足時以 expanding 視窗遞補，避免開頭整段變 NaN。"""
    roll = s.rolling(window, min_periods=min_periods)
    z = (s - roll.mean()) / roll.std()
    exp = s.expanding(min_periods=60)
    z_exp = (s - exp.mean()) / exp.std()
    return z.fillna(z_exp).replace([np.inf, -np.inf], np.nan)


def clip_z(s: pd.Series, limit: float = 3.0) -> pd.Series:
    """截斷極端值，避免單一指標在危機期間綁架整個分數。"""
    return s.clip(-limit, limit)


def composite(components: dict[str, pd.Series],
              weights: dict[str, float]) -> pd.Series:
    """加權合成。權重會依「當下實際有值的成分」重新正規化，
    因此某個成分還沒有資料時不會把分數往 0 拉。"""
    if not components:
        raise ValueError("components 不可為空")
    df = pd.DataFrame(components)
    w = pd.Series({k: weights.get(k, 0.0) for k in df.columns}, dtype=float)
    if w.abs().sum() == 0:
        raise ValueError("權重總和為 0")
    mask = df.notna()
    weighted = (df.fillna(0.0) * w).sum(axis=1)
    active = (mask * w.abs()).sum(axis=1)
    out = weighted / active.replace(0.0, np.nan)
    return out.where(active > 0)


def build_axis(panel: pd.DataFrame, specs: list[dict]) -> tuple[pd.Series, pd.DataFrame]:
    """依設定建構單一軸的分數。

    每個 spec：
      {"name":..., "series": pd.Series 或 (分子, 分母), "mode": "pct"|"diff",
       "invert": bool, "weight": float}
    回傳 (合成分數, 各成分 z-score 表)
    """
    comps: dict[str, pd.Series] = {}
    weights: dict[str, float] = {}
    for spec in specs:
        src = spec["series"]
        s = ratio(panel, *src) if isinstance(src, tuple) else panel[src]
        z = clip_z(zscore(momentum(s, mode=spec.get("mode", "pct"))))
        if spec.get("invert"):
            z = -z
        comps[spec["name"]] = z
        weights[spec["name"]] = float(spec["weight"])
    return composite(comps, weights), pd.DataFrame(comps)
