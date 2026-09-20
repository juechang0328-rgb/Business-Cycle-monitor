"""每日總結：把當天資料裡「值得看一眼」的東西挑出來。

設計上刻意只做**描述**，不做預測。理由是這個專案自己的檢驗結果：
景氣階段模型與未來報酬的相關近於零、無法分辨衰退、擇時回測輸給買進持有
（見 validate.py 與 backtest.py）。既然如此，用同一批資料寫出
「後市看好／應加碼」這類句子，只是把沒有預測力的東西包裝成有信心的文字。

因此總結回答的是「今天有什麼變了」，不是「接下來會怎樣」。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import health, macro_dash


def _pct_or_pt(mode: str) -> str:
    return "pp" if mode in ("yoy", "m3ann", "pct") else ""


def collect(panel: pd.DataFrame, cfg) -> dict:
    """蒐集當天的重點事實。全部可回溯到具體數字。"""
    a = cfg.active()
    groups = a.get("groups", [])
    asof = panel.index[-1]

    # 1) 變化最極端的指標（以各自歷史變化分布的 z 分數衡量）
    movers = []
    for title, items in groups:
        for name, code, mode, th in items:
            snap = macro_dash.metric_snapshot(panel, code, mode)
            if not snap["ok"]:
                continue
            z = macro_dash.change_zscore(snap["series"])
            if np.isnan(z):
                continue
            movers.append({
                "group": title, "name": name, "code": code, "mode": mode,
                "z": z, "change": snap["change"], "current": snap["current"],
            })
    movers.sort(key=lambda m: -abs(m["z"]))

    # 2) 跨越門檻的項目
    crossings = []
    for title, items in groups:
        for name, code, mode, th in items:
            if not th:
                continue
            snap = macro_dash.metric_snapshot(panel, code, mode)
            if not snap["ok"]:
                continue
            note, lvl = macro_dash.threshold_note(code, snap["current"], th)
            if lvl in ("warn", "alert"):
                crossings.append({"name": name, "code": code, "note": note,
                                  "level": lvl, "current": snap["current"]})

    # 3) 殖利率曲線型態，以及與三個月前相比是否改變
    curve_now = macro_dash._curve_at(panel, asof)
    curve_prev = macro_dash._curve_at(panel, asof - pd.DateOffset(months=3))
    shape_now = macro_dash.classify_curve(curve_now)[0] if len(curve_now) >= 4 else None
    shape_prev = macro_dash.classify_curve(curve_prev)[0] if len(curve_prev) >= 4 else None

    # 4) 資料健康
    h = health.check_panel(panel, a.get("health", []), asof=asof)
    hsum = health.summarise(h)

    return {"asof": asof, "movers": movers, "crossings": crossings,
            "shape_now": shape_now, "shape_prev": shape_prev,
            "health": hsum, "health_bad": h[h["status"] != "正常"]}


def sentences(facts: dict, top: int = 3) -> list[str]:
    """把事實寫成句子。每一句都對應可查證的數字。"""
    out = []

    if facts["shape_now"]:
        if facts["shape_prev"] and facts["shape_prev"] != facts["shape_now"]:
            out.append(f"殖利率曲線由三個月前的<b>{facts['shape_prev']}</b>"
                       f"轉為<b>{facts['shape_now']}</b>。")
        else:
            out.append(f"殖利率曲線維持<b>{facts['shape_now']}</b>。")

    big = [m for m in facts["movers"] if abs(m["z"]) >= macro_dash.ANOMALY_Z][:top]
    if big:
        parts = []
        for m in big:
            direction = "上升" if m["change"] > 0 else "下降"
            parts.append(f"{m['name']}（{m['group']}）{direction} "
                         f"{abs(m['change']):,.2f}{_pct_or_pt(m['mode'])}"
                         f"，為歷史 {abs(m['z']):.1f}σ")
        out.append("三個月變化最不尋常的是：" + "；".join(parts) + "。")
    else:
        top3 = facts["movers"][:top]
        if top3:
            parts = [f"{m['name']} {m['change']:+,.2f}{_pct_or_pt(m['mode'])}"
                     for m in top3]
            out.append("沒有指標的變化達到 2σ；"
                       "變化相對較大的是 " + "、".join(parts) + "。")

    alerts = [c for c in facts["crossings"] if c["level"] == "alert"]
    warns = [c for c in facts["crossings"] if c["level"] == "warn"]
    if alerts:
        out.append("處於警戒區間的有：" +
                   "、".join(f"{c['name']}（{c['note']}）" for c in alerts) + "。")
    if warns:
        out.append("需留意：" +
                   "、".join(f"{c['name']}（{c['note']}）" for c in warns) + "。")
    if not alerts and not warns:
        out.append("目前沒有指標落在警戒區間。")

    hs = facts["health"]
    if hs["ok"] < hs["total"]:
        bad = facts["health_bad"]
        names = "、".join(bad["指標"].head(3).tolist())
        more = f" 等 {len(bad)} 項" if len(bad) > 3 else ""
        out.append(f"⚠ 資料異常：{names}{more}，"
                   f"該指標的判讀請暫時保留。")

    return out


def render(panel: pd.DataFrame, cfg) -> str:
    facts = collect(panel, cfg)
    lines = sentences(facts)
    body = "".join(f"<li>{s}</li>" for s in lines)
    return f"""
<section class="brief">
  <div class="brief-head">
    <span class="brief-title">今日重點</span>
    <span class="brief-date">{facts['asof'].date()}</span>
  </div>
  <ul class="brief-list">{body}</ul>
  <p class="brief-foot">
    這段摘要由當日數據依固定規則產生，<b>只描述已經發生的變化，不預測後市</b>。
    「σ」指該指標本次三個月變化相對於自身歷史變化分布的標準差倍數，
    用來跨指標比較變化是否不尋常。
  </p>
</section>"""
