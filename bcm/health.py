"""資料健康檢查：每個序列到底有沒有更新、是不是該更新卻沒更新。

存在的理由很具體：先前 IC4WSA 因為觀測日落在星期六而被對齊營業日的程式
整欄丟成 NaN —— 不報錯、不中斷，指標就這樣安靜地失效了。
任何自動化的資料流都需要一層「它真的有資料嗎」的檢查。
"""
from __future__ import annotations

import pandas as pd

# 各頻率允許的落後天數上限。超過就視為異常，而非「還沒公布」。
# 取值考量：公布延遲 + 假期 + 週末。
TOLERANCE_DAYS = {
    "daily": 6,        # 連假最長約 5 天
    "weekly": 12,
    "monthly": 55,     # 月資料常延遲 3-6 週公布
    "quarterly": 135,
}

STATUS_ORDER = {"無資料": 0, "停更": 1, "延遲": 2, "正常": 3}


def check_series(s: pd.Series, freq: str, asof: pd.Timestamp) -> dict:
    valid = s.dropna()
    if valid.empty:
        return {"status": "無資料", "last": None, "age_days": None,
                "n": 0, "detail": "整個序列都是缺值"}
    last = valid.index[-1]
    age = (asof - last).days
    tol = TOLERANCE_DAYS.get(freq, 55)
    if age > tol * 3:
        status, detail = "停更", f"已 {age} 天無新值（容許 {tol} 天）"
    elif age > tol:
        status, detail = "延遲", f"落後 {age} 天（容許 {tol} 天）"
    else:
        status = "正常"
        detail = "今日更新" if age <= 1 else f"{age} 天前更新"
    return {"status": status, "last": last, "age_days": age,
            "n": int(valid.notna().sum()), "detail": detail}


def check_panel(panel: pd.DataFrame, specs: list[tuple],
                asof: pd.Timestamp | None = None) -> pd.DataFrame:
    """specs：[(顯示名稱, 欄位代碼, 頻率), ...]"""
    asof = asof or panel.index[-1]
    rows = []
    for name, code, freq in specs:
        if code not in panel.columns:
            rows.append({"指標": name, "代碼": code, "頻率": freq,
                         "status": "無資料", "last": None, "age_days": None,
                         "n": 0, "detail": "面板中沒有這個欄位"})
            continue
        r = check_series(panel[code], freq, asof)
        rows.append({"指標": name, "代碼": code, "頻率": freq, **r})
    df = pd.DataFrame(rows)
    df["_order"] = df["status"].map(STATUS_ORDER)
    return df.sort_values(["_order", "指標"]).drop(columns="_order")


def summarise(health: pd.DataFrame) -> dict:
    counts = health["status"].value_counts().to_dict()
    total = len(health)
    ok = counts.get("正常", 0)
    return {
        "total": total, "ok": ok,
        "delayed": counts.get("延遲", 0),
        "stalled": counts.get("停更", 0),
        "missing": counts.get("無資料", 0),
        "ratio": ok / total if total else 0.0,
        "healthy": ok == total,
    }
