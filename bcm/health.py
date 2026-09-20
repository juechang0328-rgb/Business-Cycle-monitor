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


def check_series(s: pd.Series, freq: str, asof: pd.Timestamp,
                 last_obs: pd.Timestamp | None = None) -> dict:
    """last_obs：該欄真正的最後觀測日。

    面板裡每一欄都被向前填補到最後一天，所以 `s.dropna().index[-1]` 永遠等於
    面板的最後一天 —— 不給 last_obs 的話，這個檢查只會一律回報「今日更新」，
    完全看不出哪一個序列其實已經停更。真實觀測日由 bcm/sources.py 在填補前記下。
    """
    valid = s.dropna()
    if valid.empty:
        return {"status": "無資料", "last": None, "age_days": None,
                "n": 0, "detail": "整個序列都是缺值"}
    last = pd.Timestamp(last_obs) if last_obs is not None \
        and not pd.isna(last_obs) else valid.index[-1]
    age = (asof - last).days
    if freq == "projection":
        # 預測型序列（例如 FOMC 點陣圖）的觀測日標在被預測的未來年度，
        # 用「落後幾天」判斷毫無意義，改看最後一筆是否仍指向未來。
        if age < 0:
            return {"status": "正常", "last": last, "age_days": age,
                    "n": int(valid.notna().sum()),
                    "detail": f"預測至 {last.date()}"}
        return {"status": "延遲", "last": last, "age_days": age,
                "n": int(valid.notna().sum()),
                "detail": f"最後預測年度已過期 {age} 天，等待下次 SEP 更新"}
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
                asof: pd.Timestamp | None = None,
                last_obs: pd.Series | None = None) -> pd.DataFrame:
    """specs：[(顯示名稱, 欄位代碼, 頻率), ...]

    last_obs：{欄位代碼: 真實最後觀測日}。缺這份紀錄時退回用面板日期，
    但那樣會因為向前填補而看不出停更，因此 summarise 會標記為 unverified。
    """
    asof = asof or panel.index[-1]
    lo = last_obs if last_obs is not None else pd.Series(dtype="datetime64[ns]")
    rows = []
    for name, code, freq in specs:
        if code not in panel.columns:
            rows.append({"指標": name, "代碼": code, "頻率": freq,
                         "status": "無資料", "last": None, "age_days": None,
                         "n": 0, "detail": "面板中沒有這個欄位",
                         "verified": False})
            continue
        r = check_series(panel[code], freq, asof, last_obs=lo.get(code))
        rows.append({"指標": name, "代碼": code, "頻率": freq, **r,
                     "verified": code in lo.index})
    df = pd.DataFrame(rows)
    df["_order"] = df["status"].map(STATUS_ORDER)
    return df.sort_values(["_order", "指標"]).drop(columns="_order")


def summarise(health: pd.DataFrame) -> dict:
    counts = health["status"].value_counts().to_dict()
    total = len(health)
    ok = counts.get("正常", 0)
    present = health[health["status"] != "無資料"]
    unverified = int((~present["verified"]).sum()) if "verified" in health \
        else len(present)
    return {
        "total": total, "ok": ok, "unverified": unverified,
        "delayed": counts.get("延遲", 0),
        "stalled": counts.get("停更", 0),
        "missing": counts.get("無資料", 0),
        "ratio": ok / total if total else 0.0,
        "healthy": ok == total,
    }
