"""總經儀表板：五大區塊 × 指標卡片 + 資料健康檢查。

定位：描述「現在市場在發生什麼」，不宣稱預測。
每張卡片包含當前值、變化、12 個月迷你走勢，以及（若有）門檻位置。
"""
from __future__ import annotations

import html
from datetime import datetime

import numpy as np
import pandas as pd

from . import derived, health


def _esc(t) -> str:
    return html.escape(str(t))


def _fmt(v: float, unit: str = "") -> str:
    if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
        return "—"
    a = abs(v)
    if a >= 1e12:
        return f"{v/1e12:,.2f}兆"
    if a >= 1e8:
        return f"{v/1e8:,.2f}億"
    if a >= 10000:
        return f"{v:,.0f}{unit}"
    if a >= 100:
        return f"{v:,.1f}{unit}"
    return f"{v:,.2f}{unit}"


# ------------------------------------------------------------------ 指標計算
def _shift_by(s: pd.Series, offset) -> pd.Series:
    """取「N 個日曆單位之前」的值。

    不用固定列數（例如 252 個交易日）—— 那會因假日多寡而漂移，
    且對月頻序列（在日頻面板中被向前填補）尤其不準。
    """
    prev = s.reindex(s.index - offset, method="ffill")
    return pd.Series(prev.values, index=s.index)


def _pct_over(s: pd.Series, offset) -> pd.Series:
    base = _shift_by(s, offset)
    return ((s / base - 1) * 100).replace([np.inf, -np.inf], np.nan).dropna()



def metric_series(panel: pd.DataFrame, code: str, mode: str) -> pd.Series:
    """依呈現方式把原始欄位轉成要顯示的序列。"""
    if code not in panel.columns:
        return pd.Series(dtype=float)
    s = panel[code].dropna()
    if s.empty:
        return s
    if mode == "yoy":
        return _pct_over(panel[code], pd.DateOffset(years=1))
    if mode == "m3ann":
        base = _shift_by(panel[code], pd.DateOffset(months=3))
        return (((panel[code] / base) ** 4 - 1) * 100).dropna()
    if mode == "pct":
        return _pct_over(panel[code], pd.DateOffset(months=3))
    return s                                        # level


def metric_snapshot(panel: pd.DataFrame, code: str, mode: str) -> dict:
    s = metric_series(panel, code, mode)
    if s.empty:
        return {"ok": False}
    cur = float(s.iloc[-1])
    # 變化基準：日頻序列比 3 個月前，低頻序列比前一個可得值
    lookback = 63 if len(s) > 80 else max(len(s) // 4, 1)
    prev = float(s.iloc[-lookback - 1]) if len(s) > lookback else float(s.iloc[0])
    return {"ok": True, "series": s, "current": cur, "prev": prev,
            "change": cur - prev, "last_date": s.index[-1]}


# ------------------------------------------------------------------ 迷你圖
def sparkline(s: pd.Series, w: int = 190, h: int = 40,
              months: int = 12, thresholds: dict | None = None) -> str:
    if s.empty:
        return '<div class="spark-empty">無資料</div>'
    cut = s.index[-1] - pd.DateOffset(months=months)
    d = s.loc[s.index >= cut]
    if len(d) < 2:
        d = s.tail(max(len(s), 2))
    lo, hi = float(d.min()), float(d.max())
    span = hi - lo if hi > lo else abs(hi) * 0.1 or 1.0
    # 門檻只在「離資料不遠」時才納入座標範圍。否則一條遠在天邊的門檻線
    # 會把整個範圍撐開，真實波動被壓成一條平線 —— 資訊量歸零。
    # 例外：invert_zone（零軸）是該指標語意的定義本身，
    # 整條線都在單側時更需要看到它，因此不受距離限制。
    limit_lo, limit_hi = lo - span, hi + span
    shown = []
    if thresholds:
        for k, v in thresholds.items():
            if not isinstance(v, (int, float)):
                continue
            if k == "invert_zone" or limit_lo <= v <= limit_hi:
                shown.append((k, v))
    vals = [lo, hi] + [v for _, v in shown]
    lo, hi = min(vals), max(vals)
    if hi == lo:
        hi = lo + 1
    pad = (hi - lo) * 0.12
    lo, hi = lo - pad, hi + pad
    n = len(d)
    px = lambda i: 2 + i / max(n - 1, 1) * (w - 4)
    py = lambda v: 3 + (hi - v) / (hi - lo) * (h - 6)

    p = [f'<svg viewBox="0 0 {w} {h}" class="spark" preserveAspectRatio="none" '
         f'role="img" aria-label="近 {months} 個月走勢">']
    for key, tv in shown:
        p.append(f'<line x1="2" y1="{py(tv):.1f}" x2="{w-2}" y2="{py(tv):.1f}" '
                 f'class="spark-th"><title>門檻 {key}={tv}</title></line>')
    pts = " ".join(f"{px(i):.1f},{py(v):.1f}" for i, v in enumerate(d))
    # 單一中性色：走勢圖只表示形狀，不暗示好壞
    p.append(f'<polyline points="{pts}" class="spark-line"/>')
    p.append(f'<circle cx="{px(n-1):.1f}" cy="{py(float(d.iloc[-1])):.1f}" '
             f'r="2.6" class="spark-dot"/>')
    p.append("</svg>")
    return "".join(p)


# ------------------------------------------------------------------ 卡片
def threshold_note(code: str, cur: float, th: dict | None) -> tuple[str, str]:
    """回傳 (狀態文字, 狀態等級)。等級用於上色：calm/normal/warn/alert。"""
    if not th:
        return "", ""
    if "warn" in th and code == "SAHMREALTIME":
        return (("已觸發衰退訊號", "alert") if cur >= th["warn"]
                else (f"門檻 {th['warn']:.2f}", "calm"))
    if "target" in th:
        gap = cur - th["target"]
        lvl = "calm" if abs(gap) < 0.5 else ("warn" if gap > 0 else "normal")
        return (f"距目標 {gap:+.1f}pp", lvl)
    if "invert_zone" in th:
        return (("倒掛中", "alert") if cur < 0 else ("正斜率", "calm"))
    if "stress" in th and "calm" in th and code == "BAMLH0A0HYM2":
        if cur < th["calm"]:
            return ("利差極窄", "warn")      # 市場高度樂觀，風險定價偏低
        if cur < th["normal"]:
            return ("常態區間", "calm")
        if cur < th["stress"]:
            return ("略為走闊", "warn")
        return ("融資緊縮", "alert")
    if "stress" in th and "calm" in th:              # VIX
        if cur < th["calm"]:
            return ("低波動", "calm")
        if cur < th["stress"]:
            return ("常態", "normal")
        return ("高波動", "alert")
    if "tight" in th:
        return (("條件偏緊", "warn") if cur > th["tight"] else ("條件寬鬆", "calm"))
    return "", ""


UNIT_BY_MODE = {"yoy": "%", "m3ann": "%", "pct": "%", "level": ""}
# 比率型指標的主值本身已是比率，其「變化」是比率的變化，單位為百分點，
# 標籤必須與水準型區分，否則同一張卡上會出現兩個看似矛盾的百分比。
CHANGE_LABEL = {"level": "近3個月", "yoy": "較3個月前",
                "m3ann": "較3個月前", "pct": "較3個月前"}
CHANGE_UNIT = {"level": "", "yoy": "pp", "m3ann": "pp", "pct": "pp"}


def metric_card(panel: pd.DataFrame, name: str, code: str,
                mode: str, th: dict | None, zscore: float | None = None) -> str:
    snap = metric_snapshot(panel, code, mode)
    if not snap["ok"]:
        return (f'<div class="mcard missing"><div class="m-name">{_esc(name)}</div>'
                f'<div class="m-val">—</div>'
                f'<div class="m-sub">無資料（{_esc(code)}）</div></div>')

    cur, chg = snap["current"], snap["change"]
    unit = UNIT_BY_MODE.get(mode, "")
    # 衍生序列可能有自己的顯示單位與縮放
    spec = derived.DERIVED.get(code)
    cunit = CHANGE_UNIT.get(mode, "")
    if spec and mode == "level":
        cur_disp = _fmt(cur * spec["scale"], spec["display_unit"])
        chg_disp = f'{chg*spec["scale"]:+,.2f}'
    else:
        cur_disp = _fmt(cur, unit)
        chg_disp = f"{chg:+,.2f}{cunit}"

    # 變化的極端程度：以該指標自己的歷史變化分布為基準
    zchip = ""
    if zscore is not None and not np.isnan(zscore) and abs(zscore) >= ANOMALY_Z:
        zchip = (f'<span class="zchip">⚠ {abs(zscore):.1f}σ</span>')

    note, lvl = threshold_note(code, cur, th)
    # 方向本身不帶好壞：VIX 與信用利差上升是壞事，用綠漲紅跌會傳達相反意思。
    # 因此變化值用中性色，只以箭頭表示方向，語意由門檻徽章承擔。
    # 依四捨五入後的顯示值判斷方向，避免出現「▲ +0.00」這種自相矛盾的組合
    shown_chg = round(chg * (spec["scale"] if spec and mode == "level" else 1), 2)
    arrow = "▲" if shown_chg > 0 else ("▼" if shown_chg < 0 else "—")
    badge = f'<span class="m-badge {lvl}">{_esc(note)}</span>' if note else ""
    return (
        f'<div class="mcard">'
        f'  <div class="m-head"><span class="m-name">{_esc(name)}</span>{badge}</div>'
        f'  <div class="m-val">{cur_disp}</div>'
        f'  <div class="m-chg"><span class="m-arrow">{arrow}</span>{chg_disp}'
        f'<span class="m-chg-lab">{CHANGE_LABEL.get(mode, "近3個月")}</span>{zchip}</div>'
        f'  {sparkline(snap["series"], thresholds=th)}'
        f'  <div class="m-sub">{snap["last_date"].date()}　{_esc(code)}</div>'
        f'</div>')


# ------------------------------------------------------------ 資料健康面板
STATUS_ICON = {"正常": "●", "延遲": "▲", "停更": "■", "無資料": "✕"}
STATUS_CLS = {"正常": "ok", "延遲": "warn", "停更": "alert", "無資料": "dead"}


def _hrows(df: pd.DataFrame) -> str:
    return "".join(
        f'<tr class="{STATUS_CLS[r["status"]]}">'
        f'<td><span class="sdot">{STATUS_ICON[r["status"]]}</span>{_esc(r["指標"])}</td>'
        f'<td class="mono">{_esc(r["代碼"])}</td>'
        f'<td>{_esc(r["頻率"])}</td>'
        f'<td class="num">{r["last"].date() if r["last"] is not None else "—"}</td>'
        f'<td class="num">{r["n"]:,}</td>'
        f'<td class="sub2">{_esc(r["detail"])}</td></tr>'
        for _, r in df.iterrows())


def health_panel(h: pd.DataFrame, summary: dict, unavailable: list[dict],
                 skipped: dict[str, list[str]]) -> str:
    chips = "".join(
        f'<span class="hchip {STATUS_CLS[k]}">{STATUS_ICON[k]} {k} {v}</span>'
        for k, v in [("正常", summary["ok"]), ("延遲", summary["delayed"]),
                     ("停更", summary["stalled"]), ("無資料", summary["missing"])]
        if v)

    bad = h[h["status"] != "正常"]
    good = h[h["status"] == "正常"]

    # 異常項目直接攤開；正常的收進次層摺疊，避免 20 幾列「0 天前更新」洗版
    bad_block = ""
    if len(bad):
        bad_block = (
            '<table class="htable"><thead><tr><th>指標</th><th>代碼</th><th>頻率</th>'
            '<th class="num">最後更新</th><th class="num">筆數</th><th>狀態</th>'
            f'</tr></thead><tbody>{_hrows(bad)}</tbody></table>')
    good_block = ""
    if len(good):
        good_block = (
            f'<details class="sub-fold"><summary>正常項目 {len(good)} 項</summary>'
            '<table class="htable"><thead><tr><th>指標</th><th>代碼</th><th>頻率</th>'
            '<th class="num">最後更新</th><th class="num">筆數</th><th>狀態</th>'
            f'</tr></thead><tbody>{_hrows(good)}</tbody></table></details>')

    una = "".join(
        f'<li><b>{_esc(u["name"])}</b>（<code>{_esc(u["symbol"])}</code>）<br>'
        f'<span class="sub2">{_esc(u["reason"])}</span><br>'
        f'<span class="sub2">替代：{_esc(u["workaround"])}</span></li>'
        for u in unavailable)

    skip = ""
    if skipped:
        items = "".join(f'<li><code>{_esc(k)}</code> 缺少 {_esc("、".join(v))}</li>'
                        for k, v in skipped.items())
        skip = (f'<div class="warnbox"><b>衍生指標無法計算：</b>'
                f'<ul class="tight">{items}</ul></div>')

    has_problem = bool(len(bad) or skipped)
    banner_cls = "ok" if not has_problem else (
        "alert" if (summary["missing"] or summary["stalled"]) else "warn")
    banner_txt = ("全部 %d 項資料正常" % summary["total"] if not has_problem
                  else f'{len(bad)} 項異常　·　{summary["ok"]}/{summary["total"]} 項正常')
    # 有問題才預設展開；一切正常時不該佔版面
    open_attr = " open" if has_problem else ""

    return f"""
<details class="health {banner_cls}"{open_attr}>
  <summary>
    <span class="h-title">資料健康檢查</span>
    <span class="h-state">{banner_txt}</span>
    <span class="h-chips">{chips}</span>
  </summary>
  <div class="h-body">
    {skip}
    {bad_block}
    {good_block}
    <details class="sub-fold"><summary>已知無法取得的指標 {len(unavailable)} 項</summary>
      <ul class="una">{una}</ul></details>
    <p class="sub2">判定標準：日頻容許落後 6 天、週頻 12 天、月頻 55 天。
    超過容許值三倍視為停更。容差已計入公布延遲與連假。</p>
  </div>
</details>"""


def groups_html(panel: pd.DataFrame, groups: list[tuple],
                extra: dict[str, str] | None = None,
                fixed_order: set[str] | None = None) -> str:
    extra = extra or {}
    fixed_order = fixed_order or set()
    out = []
    for title, items in groups:
        # 有內在順序的區塊（例如殖利率天期）維持宣告順序
        ordered = items if title in fixed_order else rank_items(panel, items)
        cards, n_anom = [], 0
        for it in ordered:
            snap = metric_snapshot(panel, it[1], it[2])
            z = change_zscore(snap["series"]) if snap["ok"] else float("nan")
            if not np.isnan(z) and abs(z) >= ANOMALY_Z:
                n_anom += 1
            cards.append(metric_card(panel, *it, zscore=z))
        n_ok = sum(1 for it in items if metric_snapshot(panel, it[1], it[2])["ok"])
        anom = (f'<span class="grp-anom">⚠ {n_anom} 項變化異常</span>'
                if n_anom else "")
        out.append(
            f'<section class="grp"><h2>{_esc(title)}'
            f'<span class="grp-n">{n_ok}/{len(items)}</span>{anom}</h2>'
            f'{extra.get(title, "")}'
            f'<div class="mgrid">{"".join(cards)}</div></section>')
    return "".join(out)


# ------------------------------------------------------------------- 頁面
CSS = """
:root{
  --bg:#fff;--panel:#f7f8fa;--card:#fff;--line:#e3e6ea;--ink:#16191d;--muted:#6b7280;
  --accent:#2a78d6;--ok:#1a7f5a;--warn:#c07600;--alert:#c0392b;--dead:#8b8f98;
  --s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;
}
:root:not([data-theme="light"]){@media(prefers-color-scheme:dark){
  --bg:#0f1216;--panel:#171b21;--card:#1a1e25;--line:#2b313b;--ink:#e8eaed;--muted:#9aa4b2;
  --accent:#3987e5;--ok:#4ade80;--warn:#fbbf24;--alert:#f87171;--dead:#6b7280;
  --s1:#3987e5;--s2:#d95926;--s3:#199e70;}}
:root[data-theme="dark"]{
  --bg:#0f1216;--panel:#171b21;--card:#1a1e25;--line:#2b313b;--ink:#e8eaed;--muted:#9aa4b2;
  --accent:#3987e5;--ok:#4ade80;--warn:#fbbf24;--alert:#f87171;--dead:#6b7280;
  --s1:#3987e5;--s2:#d95926;--s3:#199e70;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
 font:15px/1.6 -apple-system,"Noto Sans TC","PingFang TC","Microsoft JhengHei",sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:26px 16px 60px}
header{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;margin-bottom:6px}
.nav{margin-left:auto}
.nav a{color:var(--accent);text-decoration:none;font-size:13px}
.nav a:hover{text-decoration:underline}
h1{font-size:22px;margin:0;letter-spacing:.3px}
.asof{color:var(--muted);font-size:13px}
.lede{color:var(--muted);font-size:13.5px;margin:0 0 18px;max-width:80ch}

/* 健康檢查 */
.health{border:1px solid var(--line);border-radius:12px;background:var(--panel);
 margin-bottom:22px;border-left:5px solid var(--ok)}
.health.warn{border-left-color:var(--warn)} .health.alert{border-left-color:var(--alert)}
.health summary{cursor:pointer;padding:13px 16px;display:flex;align-items:center;
 gap:12px;flex-wrap:wrap;list-style:none}
.health summary::-webkit-details-marker{display:none}
.health summary::after{content:"▾";margin-left:auto;color:var(--muted)}
.health[open] summary::after{content:"▴"}
.h-title{font-weight:700;font-size:14px}
.h-state{color:var(--muted);font-size:13px}
.h-chips{display:flex;gap:6px;flex-wrap:wrap}
.hchip{font-size:11.5px;padding:2px 8px;border-radius:99px;border:1px solid var(--line)}
.hchip.ok{color:var(--ok)} .hchip.warn{color:var(--warn)}
.hchip.alert{color:var(--alert)} .hchip.dead{color:var(--dead)}
.h-body{padding:0 16px 16px}
.htable{width:100%;border-collapse:collapse;font-size:12.5px}
.htable th,.htable td{padding:6px 7px;border-bottom:1px solid var(--line);text-align:left}
.htable th{color:var(--muted);font-weight:600;font-size:11.5px}
.htable tr.warn .sdot{color:var(--warn)} .htable tr.alert .sdot{color:var(--alert)}
.htable tr.dead .sdot{color:var(--dead)} .htable tr.ok .sdot{color:var(--ok)}
.sdot{margin-right:7px;font-size:10px}
.una{margin:6px 0 12px;padding-left:18px;font-size:12.5px}
.sub-fold{margin-top:10px;border-top:1px solid var(--line);padding-top:8px}
.sub-fold summary{cursor:pointer;font-size:12.5px;color:var(--muted);padding:2px 0}
.sub-fold summary::marker{color:var(--muted)}
.una li{margin-bottom:9px}
.tight{margin:6px 0 0;padding-left:18px}

/* 指標卡 */
.grp{margin-top:26px}
.grp h2{font-size:14px;color:var(--muted);margin:0 0 11px;font-weight:600;
 display:flex;align-items:baseline;gap:8px}
.grp-n{font-size:11.5px;opacity:.75}
.grp-anom{font-size:11.5px;color:var(--warn);margin-left:4px}
.zchip{margin-left:6px;font-size:10.5px;color:var(--warn);
 border:1px solid currentColor;border-radius:99px;padding:0 5px;white-space:nowrap}
.curve-lab{font-size:11.5px;font-weight:700}
.legend{display:flex;gap:14px;flex-wrap:wrap;margin-top:10px;font-size:12px;color:var(--muted)}
.legend span{display:flex;align-items:center;gap:5px}
.legend i{width:14px;height:3px;border-radius:2px;display:inline-block}
.mgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(216px,1fr));gap:12px}
.mcard{background:var(--card);border:1px solid var(--line);border-radius:11px;
 padding:12px 13px 9px;display:flex;flex-direction:column;gap:3px}
.mcard.missing{opacity:.55}
.m-head{display:flex;align-items:flex-start;justify-content:space-between;gap:6px;
 min-height:32px}
.m-name{font-size:12.5px;color:var(--muted);line-height:1.35}
.m-badge{font-size:10.5px;padding:1px 6px;border-radius:99px;white-space:nowrap;
 border:1px solid currentColor;opacity:.9}
.m-badge.calm{color:var(--ok)} .m-badge.normal{color:var(--muted)}
.m-badge.warn{color:var(--warn)} .m-badge.alert{color:var(--alert)}
.m-val{font-size:23px;font-weight:700;line-height:1.15;letter-spacing:-.4px}
.m-chg{font-size:12px;color:var(--muted);font-variant-numeric:tabular-nums}
.m-arrow{margin-right:4px;font-size:9px;vertical-align:1px}
.m-chg-lab{margin-left:6px;opacity:.7;font-size:11px}
.spark{width:100%;height:40px;display:block;margin:4px 0 2px}
.spark-line{fill:none;stroke:var(--accent);stroke-width:1.6;
 stroke-linejoin:round;stroke-linecap:round}
.spark-dot{fill:var(--accent)}
.spark-th{stroke:var(--muted);stroke-width:1;opacity:.45}
.spark-empty{height:40px;display:flex;align-items:center;color:var(--muted);font-size:11.5px}
.m-sub{font-size:10.5px;color:var(--muted);opacity:.85;
 white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sub2{color:var(--muted);font-size:11.5px}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11.5px}
.num{text-align:right;font-variant-numeric:tabular-nums}
.warnbox{background:var(--bg);border:1px solid var(--line);border-left:3px solid var(--warn);
 border-radius:8px;padding:10px 13px;margin:10px 0;font-size:12.5px;color:var(--muted)}
footer{margin-top:34px;padding-top:16px;border-top:1px solid var(--line);
 color:var(--muted);font-size:12px;line-height:1.75}
footer b{color:var(--ink)}
@media(max-width:640px){
  .mgrid{grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:9px}
  .m-val{font-size:19px} h1{font-size:19px}
  .htable th:nth-child(3),.htable td:nth-child(3),
  .htable th:nth-child(5),.htable td:nth-child(5){display:none}
}
"""


def render(panel: pd.DataFrame, cfg, skipped: dict[str, list[str]] | None = None,
           demo: bool = False) -> str:
    a = cfg.active()
    groups = a.get("groups", [])
    hspec = a.get("health", [])
    unavailable = a.get("unavailable", [])
    asof = panel.index[-1]

    h = health.check_panel(panel, hspec, asof=asof)
    summary = health.summarise(h)

    demo_banner = ('<div class="warnbox" style="border-left-color:var(--alert)">'
                   '<b>⚠ 示範資料</b>　本頁以合成資料產生，數字不具參考價值。'
                   '</div>') if demo else ""

    return f"""<!DOCTYPE html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>總經儀表板</title><style>{CSS}</style></head><body><div class="wrap">

<header>
  <h1>總經儀表板</h1>
  <span class="asof">資料日期 {asof.date()}　·　產生於 {datetime.now():%Y-%m-%d %H:%M}</span>
  <nav class="nav"><a href="index.html">景氣循環儀表板 →</a></nav>
</header>
<p class="lede">
  用途是<b>描述現在市場在發生什麼</b>，不是預測。每張卡片顯示最新值、近三個月變化、
  近 12 個月走勢，以及（若適用）關鍵門檻位置。走勢線一律使用中性色 ——
  上升不等於是好事，例如 VIX 與信用利差走高代表風險升高。
</p>
{demo_banner}
{health_panel(h, summary, unavailable, skipped or {})}
{groups_html(panel, groups, extra={"公債殖利率": yield_curve_svg(panel)},
             fixed_order=a.get("fixed_order"))}

<footer>
  <b>資料來源</b>　FRED 公開 CSV（免 API key）、Yahoo Finance。<br>
  <b>單位處理</b>　Fed 淨流動性 = WALCL − WTREGEN − RRPONTSYD×1000。
  WALCL 與 WTREGEN 以百萬美元計，RRPONTSYD 以十億美元計，
  不做這個換算會讓逆回購的影響被縮小為千分之一。<br>
  <b>Sahm Rule</b>　= 3個月移動平均失業率 − 前 12 個月該移動平均的最低值
  （非原始失業率的最低值）。<br>
  <b>限制</b>　本專案的景氣階段模型經檢驗<b>不具預測力</b>
  （見 <code>validate.py</code> 與 <code>backtest.py</code>）。
  本頁僅供理解現況，不構成投資建議。
</footer>
</div></body></html>"""


# ------------------------------------------------------- 變化幅度標準化排序
# 不同指標的變化量無法直接比較：VIX 漲 5 點與 CPI 漲 0.3pp 是不同量綱。
# 因此改用「這次的三個月變化，相對於該指標自己歷史上的三個月變化」有多極端，
# 也就是變化量的 z-score。如此才能跨指標排序。
ANOMALY_Z = 2.0          # |z| 超過此值標示為異常


def change_zscore(s: pd.Series, offset=None) -> float:
    """本次變化在該序列歷史變化分布中的 z 分數。"""
    offset = offset or pd.DateOffset(months=3)
    if s.empty or len(s) < 60:
        return float("nan")
    base = _shift_by(s, offset)
    diffs = (s - base).dropna()
    if len(diffs) < 30:
        return float("nan")
    sd = diffs.std()
    if not sd or np.isnan(sd):
        return float("nan")
    return float((diffs.iloc[-1] - diffs.mean()) / sd)


def rank_items(panel: pd.DataFrame, items: list[tuple]) -> list[tuple]:
    """區塊內依變化的極端程度排序，最不尋常的排最前面。

    取不到值的指標一律沉到最後，避免缺料卡佔據視線焦點。
    """
    scored = []
    for it in items:
        snap = metric_snapshot(panel, it[1], it[2])
        z = change_zscore(snap["series"]) if snap["ok"] else float("nan")
        scored.append((it, z))
    return [it for it, _ in sorted(
        scored,
        key=lambda t: (-abs(t[1]) if not np.isnan(t[1]) else 1e9, ))]


# ----------------------------------------------------------- 殖利率曲線圖
CURVE_TENORS = [
    ("1M", "DGS1MO"), ("3M", "DGS3MO"), ("6M", "DGS6MO"), ("1Y", "DGS1"),
    ("2Y", "DGS2"), ("3Y", "DGS3"), ("5Y", "DGS5"), ("7Y", "DGS7"),
    ("10Y", "DGS10"), ("20Y", "DGS20"), ("30Y", "DGS30"),
]


def _curve_at(panel: pd.DataFrame, when: pd.Timestamp) -> list[tuple[str, float]]:
    out = []
    for label, code in CURVE_TENORS:
        if code not in panel.columns:
            continue
        s = panel[code].dropna()
        if s.empty:
            continue
        v = s.asof(when)
        if pd.notna(v):
            out.append((label, float(v)))
    return out


def yield_curve_svg(panel: pd.DataFrame, w: int = 860, h: int = 320) -> str:
    """殖利率曲線：現在 vs 三個月前 vs 一年前，疊在同一張圖上比較形狀變化。

    橫軸為天期，採等距排列（非按年數比例）—— 否則短天期會被擠在左緣，
    而曲線形狀的變化正好最常發生在短端。
    """
    if not any(c in panel.columns for _, c in CURVE_TENORS):
        return '<p class="sub2">尚無公債殖利率資料</p>'
    asof = panel.index[-1]
    snaps = [
        ("現在", asof, 1),
        ("3個月前", asof - pd.DateOffset(months=3), 2),
        ("1年前", asof - pd.DateOffset(years=1), 3),
    ]
    curves = [(lab, _curve_at(panel, when), slot) for lab, when, slot in snaps]
    curves = [c for c in curves if len(c[1]) >= 3]
    if not curves:
        return '<p class="sub2">尚無公債殖利率資料</p>'

    labels = [l for l, _ in CURVE_TENORS
              if any(l in dict(c[1]) for c in curves)]
    m = dict(l=48, r=92, t=16, b=38)
    pw, ph = w - m["l"] - m["r"], h - m["t"] - m["b"]
    vals = [v for _, c, _ in curves for _, v in c]
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.18 or 0.5
    lo, hi = lo - pad, hi + pad
    px = lambda i: m["l"] + (i / max(len(labels) - 1, 1)) * pw
    py = lambda v: m["t"] + (hi - v) / (hi - lo) * ph

    p = [f'<svg viewBox="0 0 {w} {h}" class="chart" role="img" '
         f'aria-label="美國公債殖利率曲線，現在與過去比較">']
    for k in range(6):
        v = lo + (hi - lo) * k / 5
        p.append(f'<line x1="{m["l"]}" y1="{py(v):.1f}" x2="{m["l"]+pw}" '
                 f'y2="{py(v):.1f}" class="grid"/>')
        p.append(f'<text x="{m["l"]-8}" y="{py(v)+4:.1f}" class="tick" '
                 f'text-anchor="end">{v:.2f}</text>')
    for i, lab in enumerate(labels):
        p.append(f'<text x="{px(i):.1f}" y="{m["t"]+ph+20}" class="tick" '
                 f'text-anchor="middle">{lab}</text>')

    for name, curve, slot in curves:
        d = dict(curve)
        pts, last = [], None
        for i, lab in enumerate(labels):
            if lab in d:
                pts.append(f"{px(i):.1f},{py(d[lab]):.1f}")
                last = (px(i), py(d[lab]), d[lab])
        dash = '' if slot == 1 else (' stroke-dasharray="6 3"' if slot == 2
                                     else ' stroke-dasharray="2 3"')
        p.append(f'<polyline points="{" ".join(pts)}" fill="none" '
                 f'stroke="var(--s{slot})" stroke-width="2.4" '
                 f'stroke-linejoin="round"{dash}/>')
        for i, lab in enumerate(labels):
            if lab in d:
                p.append(f'<circle cx="{px(i):.1f}" cy="{py(d[lab]):.1f}" r="3" '
                         f'fill="var(--s{slot})"><title>{name} {lab} '
                         f'{d[lab]:.2f}%</title></circle>')
        if last:
            p.append(f'<text x="{last[0]+10:.1f}" y="{last[1]+4:.1f}" '
                     f'class="curve-lab" fill="var(--s{slot})">{name}</text>')
    p.append("</svg>")

    legend = "".join(
        f'<span><i style="background:var(--s{slot})"></i>{name}</span>'
        for name, _, slot in curves)
    now = dict(curves[0][1])
    prev = dict(curves[1][1]) if len(curves) > 1 else {}
    rows = "".join(
        f'<tr><td>{l}</td><td class="num">{now.get(l, float("nan")):.2f}</td>'
        f'<td class="num">{prev.get(l, float("nan")):.2f}</td>'
        f'<td class="num">{now.get(l, float("nan")) - prev.get(l, float("nan")):+.2f}</td></tr>'
        for l in labels if l in now)
    table = (f'<details class="sub-fold"><summary>各天期數值</summary>'
             f'<table class="htable"><thead><tr><th>天期</th>'
             f'<th class="num">現在</th><th class="num">3個月前</th>'
             f'<th class="num">變化</th></tr></thead><tbody>{rows}</tbody>'
             f'</table></details>')
    return (f'<div class="card">{"".join(p)}'
            f'<div class="legend">{legend}</div>'
            f'<p class="sub2" style="margin:8px 0 0">'
            f'橫軸為天期，採等距排列。曲線整體上移＝殖利率全面走升；'
            f'短端上升快於長端＝平坦化；短端下降快於長端＝陡峭化。</p>'
            f'{table}</div>')
