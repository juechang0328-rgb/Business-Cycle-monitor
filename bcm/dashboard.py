"""產生單一自足的 HTML 儀表板（內嵌 SVG，不依賴任何 CDN，可離線開啟）。"""
from __future__ import annotations

import html
from datetime import datetime

import pandas as pd

from . import stages

STAGE_COLORS = {
    1: "#5B8DB8",  # 衰退 藍
    2: "#6FA85A",  # 谷底 綠
    3: "#E0913A",  # 復甦 橙
    4: "#D4B82E",  # 擴張 黃
    5: "#3FA396",  # 高峰 青
    6: "#8E7CB8",  # 趨緩 紫
}

STAGE_DESC = {
    1: "成長低迷且持續惡化，通膨已回落。央行開始降息，債券領先落底。",
    2: "成長仍在低檔，但下跌動能已止穩。股票先於實體經濟反彈，靠的是折現率下降而非盈餘。",
    3: "成長轉正並加速，通膨仍低。股債商品齊漲，資產配置最甜蜜的一段。",
    4: "成長強勁，通膨明確上行。央行轉為緊縮，債券開始下跌。",
    5: "經濟仍熱，但成長率的高點已過。通膨續揚、估值受壓，股票開始領先下跌。",
    6: "成長轉負，通膨見頂回落但利率仍高。股債商品齊跌，最難熬的一段。",
}


# ------------------------------------------------------------------ SVG 工具
def _esc(t) -> str:
    return html.escape(str(t))


def _scale(v, lo, hi, out_lo, out_hi):
    if hi == lo:
        return (out_lo + out_hi) / 2
    return out_lo + (v - lo) / (hi - lo) * (out_hi - out_lo)


def _nice_bounds(lo: float, hi: float, pad: float = 0.12) -> tuple[float, float]:
    span = hi - lo or 1.0
    return lo - span * pad, hi + span * pad


def clock_svg(df: pd.DataFrame, w: int = 560, h: int = 460,
              resample: str = "W-FRI") -> str:
    """景氣時鐘：x=通膨分數 I，y=成長分數 G，路徑依時間著色為各階段。

    日頻軌跡雜訊太高會糊成一團，因此降頻到週頻再畫，螺旋才看得出來。
    """
    d = df.dropna(subset=["G", "I"])
    if d.empty:
        return "<p>資料不足</p>"
    if resample:
        d = d.resample(resample).last().dropna(subset=["G", "I"])
    if len(d) < 2:
        return "<p>資料不足</p>"
    m = {"l": 56, "r": 18, "t": 18, "b": 46}
    pw, ph = w - m["l"] - m["r"], h - m["t"] - m["b"]

    xlo, xhi = _nice_bounds(d["I"].min(), d["I"].max())
    ylo, yhi = _nice_bounds(d["G"].min(), d["G"].max())
    px = lambda v: m["l"] + _scale(v, xlo, xhi, 0, pw)
    py = lambda v: m["t"] + _scale(v, ylo, yhi, ph, 0)

    p = [f'<svg viewBox="0 0 {w} {h}" class="chart" role="img" '
         f'aria-label="景氣時鐘散布圖">']
    p.append(f'<rect x="{m["l"]}" y="{m["t"]}" width="{pw}" height="{ph}" class="plot"/>')

    # 象限說明
    zx, zy = px(0), py(0)
    p.append(f'<line x1="{zx:.1f}" y1="{m["t"]}" x2="{zx:.1f}" y2="{m["t"]+ph}" class="axis0"/>')
    p.append(f'<line x1="{m["l"]}" y1="{zy:.1f}" x2="{m["l"]+pw}" y2="{zy:.1f}" class="axis0"/>')
    for label, qx, qy in [("成長↑ 通膨↓", m["l"] + 8, m["t"] + 20),
                          ("成長↑ 通膨↑", m["l"] + pw - 8, m["t"] + 20),
                          ("成長↓ 通膨↓", m["l"] + 8, m["t"] + ph - 10),
                          ("成長↓ 通膨↑", m["l"] + pw - 8, m["t"] + ph - 10)]:
        anchor = "start" if qx < m["l"] + pw / 2 else "end"
        p.append(f'<text x="{qx}" y="{qy}" class="quad" text-anchor="{anchor}">{label}</text>')

    # 軌跡：每段以「該段起點的階段」著色
    pts = list(zip(d["I"].tolist(), d["G"].tolist(), d["stage"].tolist()))
    for (x1, y1, s1), (x2, y2, _) in zip(pts, pts[1:]):
        c = STAGE_COLORS.get(int(s1), "#9aa4b2")
        p.append(f'<line x1="{px(x1):.1f}" y1="{py(y1):.1f}" x2="{px(x2):.1f}" '
                 f'y2="{py(y2):.1f}" stroke="{c}" stroke-width="2" '
                 f'stroke-linecap="round" opacity="0.75"/>')

    # 起點與現在
    x0, y0, _ = pts[0]
    xn, yn, sn = pts[-1]
    p.append(f'<circle cx="{px(x0):.1f}" cy="{py(y0):.1f}" r="4" class="startpt"/>')
    # 起點與終點太近時省略標籤，避免與「現在」重疊
    far = abs(px(x0) - px(xn)) > 64 or abs(py(y0) - py(yn)) > 30
    if far:
        p.append(f'<text x="{px(x0)+8:.1f}" y="{py(y0)-8:.1f}" class="ptlabel">'
                 f'起點 {d.index[0].date()}</text>')
    cn = STAGE_COLORS.get(int(sn), "#9aa4b2")
    p.append(f'<circle cx="{px(xn):.1f}" cy="{py(yn):.1f}" r="11" fill="{cn}" '
             f'opacity="0.28"/>')
    p.append(f'<circle cx="{px(xn):.1f}" cy="{py(yn):.1f}" r="6.5" fill="{cn}" '
             f'stroke="var(--bg)" stroke-width="2.5"/>')
    p.append(f'<text x="{px(xn)+12:.1f}" y="{py(yn)+4:.1f}" class="ptlabel strong">現在</text>')

    # 座標軸
    p.append(f'<text x="{m["l"]+pw/2}" y="{h-12}" class="axlabel" '
             f'text-anchor="middle">通膨分數 I →</text>')
    p.append(f'<text x="16" y="{m["t"]+ph/2}" class="axlabel" text-anchor="middle" '
             f'transform="rotate(-90 16 {m["t"]+ph/2})">成長分數 G →</text>')
    for v in [-2, -1, 0, 1, 2]:
        if xlo <= v <= xhi:
            p.append(f'<text x="{px(v):.1f}" y="{m["t"]+ph+16}" class="tick" '
                     f'text-anchor="middle">{v}</text>')
        if ylo <= v <= yhi:
            p.append(f'<text x="{m["l"]-8}" y="{py(v)+4:.1f}" class="tick" '
                     f'text-anchor="end">{v}</text>')
    p.append("</svg>")
    return "".join(p)


def timeseries_svg(df: pd.DataFrame, w: int = 900, h: int = 300) -> str:
    """G 與 I 的時間序列，背景以階段色塊標示。"""
    d = df.dropna(subset=["G", "I"])
    if d.empty:
        return "<p>資料不足</p>"
    m = {"l": 46, "r": 16, "t": 16, "b": 34}
    pw, ph = w - m["l"] - m["r"], h - m["t"] - m["b"]
    lo, hi = _nice_bounds(min(d["G"].min(), d["I"].min()),
                          max(d["G"].max(), d["I"].max()))
    n = len(d)
    px = lambda i: m["l"] + (i / max(n - 1, 1)) * pw
    py = lambda v: m["t"] + _scale(v, lo, hi, ph, 0)

    p = [f'<svg viewBox="0 0 {w} {h}" class="chart" role="img" '
         f'aria-label="成長與通膨分數時間序列">']

    # 階段色帶
    st = d["stage"].tolist()
    start = 0
    for i in range(1, n + 1):
        if i == n or st[i] != st[start]:
            c = STAGE_COLORS.get(int(st[start]), "#9aa4b2")
            x1, x2 = px(start), px(i - 1)
            p.append(f'<rect x="{x1:.1f}" y="{m["t"]}" width="{max(x2-x1,0.8):.1f}" '
                     f'height="{ph}" fill="{c}" opacity="0.16"/>')
            start = i

    p.append(f'<line x1="{m["l"]}" y1="{py(0):.1f}" x2="{m["l"]+pw}" '
             f'y2="{py(0):.1f}" class="axis0"/>')

    for col, cls in [("G", "lineG"), ("I", "lineI")]:
        smooth = d[col].rolling(5, min_periods=1).mean()
        pts = " ".join(f"{px(i):.1f},{py(v):.1f}" for i, v in enumerate(smooth))
        p.append(f'<polyline points="{pts}" class="{cls}"/>')

    for v in [-2, -1, 0, 1, 2]:
        if lo <= v <= hi:
            p.append(f'<text x="{m["l"]-8}" y="{py(v)+4:.1f}" class="tick" '
                     f'text-anchor="end">{v}</text>')
    step = max(n // 6, 1)
    for i in range(0, n, step):
        p.append(f'<text x="{px(i):.1f}" y="{m["t"]+ph+20}" class="tick" '
                 f'text-anchor="middle">{d.index[i].strftime("%Y-%m")}</text>')
    p.append("</svg>")
    return "".join(p)


def bars_html(parts: pd.DataFrame, specs: list[dict]) -> str:
    """成分 z-score 橫條（以 0 為中心，左負右正）。"""
    w = {s["name"]: s["weight"] for s in specs}
    row = parts.iloc[-1]
    out = ['<div class="bars">']
    for name in parts.columns:
        v = row[name]
        if pd.isna(v):
            out.append(f'<div class="bar-row"><span class="bar-name">{_esc(name)}</span>'
                       f'<span class="bar-track"></span>'
                       f'<span class="bar-val muted">n/a</span></div>')
            continue
        pct = min(abs(v), 3.0) / 3.0 * 50
        side = (f'left:50%;width:{pct:.1f}%' if v >= 0
                else f'right:50%;width:{pct:.1f}%')
        cls = "pos" if v >= 0 else "neg"
        out.append(
            f'<div class="bar-row">'
            f'<span class="bar-name">{_esc(name)} <em>{w.get(name,0):.0%}</em></span>'
            f'<span class="bar-track"><i class="bar-fill {cls}" style="{side}"></i></span>'
            f'<span class="bar-val {cls}">{v:+.2f}</span></div>')
    out.append("</div>")
    return "".join(out)


def market_table(panel: pd.DataFrame, spec: list[tuple]) -> str:
    rows = []
    for label, code, mode in spec:
        if code not in panel.columns:
            rows.append(f"<tr><td>{_esc(label)}</td><td class='num muted'>—</td>"
                        f"<td class='num muted'>—</td></tr>")
            continue
        s = panel[code].dropna()
        if len(s) < 64:
            rows.append(f"<tr><td>{_esc(label)}</td>"
                        f"<td class='num'>{s.iloc[-1]:,.2f}</td>"
                        f"<td class='num muted'>歷史不足</td></tr>")
            continue
        if mode == "pct":
            chg, unit = (s.iloc[-1] / s.iloc[-64] - 1) * 100, "%"
        else:
            chg, unit = s.iloc[-1] - s.iloc[-64], "pp"
        cls = "pos" if chg >= 0 else "neg"
        rows.append(f"<tr><td>{_esc(label)}</td>"
                    f"<td class='num'>{s.iloc[-1]:,.2f}</td>"
                    f"<td class='num {cls}'>{chg:+.2f}{unit}</td></tr>")
    return ("<table><thead><tr><th>標的</th><th class='num'>最新</th>"
            "<th class='num'>3個月變化</th></tr></thead><tbody>"
            + "".join(rows) + "</tbody></table>")


def stage_strip(current: int) -> str:
    cells = []
    for s in range(1, 7):
        on = "on" if s == current else ""
        b, e, c = stages.STAGE_ASSETS[s]
        cells.append(
            f'<div class="stage-cell {on}" style="--sc:{STAGE_COLORS[s]}">'
            f'<div class="sc-num">階段{s}</div>'
            f'<div class="sc-name">{stages.STAGE_NAMES[s]}</div>'
            f'<div class="sc-assets">{b} {e} {c}</div></div>')
    return f'<div class="stage-strip">{"".join(cells)}</div>'


def recent_transitions(df: pd.DataFrame, limit: int = 6) -> str:
    d = df.dropna(subset=["G", "I"])
    st = d["stage"]
    changes = st.ne(st.shift())
    idx = list(st.index[changes])[-limit:]
    rows = []
    for i, ts in enumerate(idx):
        s = int(st.loc[ts])
        end = idx[i + 1] if i + 1 < len(idx) else d.index[-1]
        days = max((end - ts).days, 0)
        rows.append(f"<tr><td class='num'>{ts.date()}</td>"
                    f"<td><span class='dot' style='background:{STAGE_COLORS.get(s,'#888')}'></span>"
                    f"階段{s} {stages.STAGE_NAMES.get(s,'—')}</td>"
                    f"<td class='num'>{days} 天</td></tr>")
    return ("<table><thead><tr><th>進入日期</th><th>階段</th><th class='num'>持續</th>"
            "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>")


# ------------------------------------------------------------------ 組裝頁面
CSS = """
:root{
  --bg:#ffffff; --panel:#f7f8fa; --line:#e3e6ea; --ink:#16191d; --muted:#6b7280;
  --pos:#1a7f5a; --neg:#c0392b; --g:#2563eb; --i:#d97706;
}
:root:not([data-theme="light"]){ @media (prefers-color-scheme:dark){
  --bg:#12151a; --panel:#1a1e25; --line:#2b313b; --ink:#e8eaed; --muted:#9aa4b2;
  --pos:#4ade80; --neg:#f87171; --g:#60a5fa; --i:#fbbf24;
}}
:root[data-theme="dark"]{
  --bg:#12151a; --panel:#1a1e25; --line:#2b313b; --ink:#e8eaed; --muted:#9aa4b2;
  --pos:#4ade80; --neg:#f87171; --g:#60a5fa; --i:#fbbf24;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:15px/1.6 -apple-system,"Noto Sans TC","PingFang TC","Microsoft JhengHei",sans-serif;}
.wrap{max-width:1040px;margin:0 auto;padding:28px 16px 60px}
h1{font-size:23px;margin:0 0 2px;letter-spacing:.3px}
h2{font-size:15px;margin:30px 0 12px;color:var(--muted);font-weight:600;
  text-transform:none;letter-spacing:.5px}
.sub{color:var(--muted);font-size:13px;margin:0 0 22px}
.demo{background:#c0392b;color:#fff;padding:9px 14px;border-radius:8px;
  font-weight:600;margin-bottom:18px;font-size:14px}
.hero{background:var(--panel);border:1px solid var(--line);border-left:6px solid var(--hc);
  border-radius:12px;padding:20px 22px;margin-bottom:8px}
.hero .lab{color:var(--muted);font-size:13px;margin-bottom:4px}
.hero .big{font-size:30px;font-weight:700;line-height:1.25}
.hero .arrows{font-size:17px;margin-top:6px;color:var(--muted)}
.hero .desc{margin-top:12px;color:var(--muted);font-size:14px;max-width:70ch}
.scores{display:flex;gap:26px;flex-wrap:wrap;margin-top:16px;padding-top:14px;
  border-top:1px solid var(--line)}
.score .k{color:var(--muted);font-size:12px}
.score .v{font-size:21px;font-weight:700;font-variant-numeric:tabular-nums}
.note{background:var(--panel);border:1px solid var(--line);border-radius:8px;
  padding:10px 14px;font-size:13px;color:var(--muted);margin-top:10px}
.stage-strip{display:grid;grid-template-columns:repeat(6,1fr);gap:6px;margin:14px 0 4px}
.stage-cell{background:var(--panel);border:1px solid var(--line);border-radius:8px;
  padding:9px 7px;text-align:center;opacity:.45}
.stage-cell.on{opacity:1;border-color:var(--sc);background:color-mix(in srgb,var(--sc) 14%,var(--panel));
  box-shadow:0 0 0 2px color-mix(in srgb,var(--sc) 30%,transparent)}
.sc-num{font-size:11px;color:var(--muted)}
.sc-name{font-weight:700;font-size:13px;margin:1px 0 3px}
.sc-assets{font-size:10.5px;color:var(--muted);letter-spacing:-.3px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px 18px}
.card h3{margin:0 0 10px;font-size:14px;font-weight:600}
.chart{width:100%;height:auto;display:block}
.plot{fill:none;stroke:var(--line)}
.axis0{stroke:var(--muted);stroke-width:1;stroke-dasharray:3 3;opacity:.55}
.tick{font-size:10px;fill:var(--muted)}
.axlabel{font-size:11px;fill:var(--muted)}
.quad{font-size:10px;fill:var(--muted);opacity:.65}
.ptlabel{font-size:10.5px;fill:var(--muted)}
.ptlabel.strong{fill:var(--ink);font-weight:700}
.startpt{fill:var(--muted)}
.lineG{fill:none;stroke:var(--g);stroke-width:2}
.lineI{fill:none;stroke:var(--i);stroke-width:2;stroke-dasharray:5 3}
.legend{display:flex;gap:16px;font-size:12px;color:var(--muted);margin-top:8px}
.legend i{display:inline-block;width:14px;height:3px;vertical-align:middle;margin-right:5px}
.bars{display:flex;flex-direction:column;gap:7px}
.bar-row{display:grid;grid-template-columns:150px 1fr 56px;align-items:center;gap:10px;font-size:13px}
.bar-name em{color:var(--muted);font-style:normal;font-size:11px}
.bar-track{position:relative;height:16px;background:var(--bg);border:1px solid var(--line);
  border-radius:4px;overflow:hidden}
.bar-track::after{content:"";position:absolute;left:50%;top:0;bottom:0;width:1px;background:var(--line)}
.bar-fill{position:absolute;top:2px;bottom:2px;border-radius:2px}
.bar-fill.pos{background:var(--pos)} .bar-fill.neg{background:var(--neg)}
.bar-val{text-align:right;font-variant-numeric:tabular-nums;font-size:12.5px}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th,td{padding:7px 6px;border-bottom:1px solid var(--line);text-align:left}
th{color:var(--muted);font-weight:600;font-size:12px}
.num{text-align:right;font-variant-numeric:tabular-nums}
.pos{color:var(--pos)} .neg{color:var(--neg)} .muted{color:var(--muted)}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:7px;vertical-align:-1px}
footer{margin-top:34px;padding-top:16px;border-top:1px solid var(--line);
  color:var(--muted);font-size:12px;line-height:1.7}
@media(max-width:760px){
  .grid{grid-template-columns:1fr}
  .stage-strip{grid-template-columns:repeat(3,1fr)}
  .bar-row{grid-template-columns:110px 1fr 50px}
  h1{font-size:20px} .hero .big{font-size:24px}
}
"""


def render_html(result: pd.DataFrame, g_parts: pd.DataFrame, i_parts: pd.DataFrame,
                panel: pd.DataFrame, cfg, demo: bool = False) -> str:
    d = result.dropna(subset=["G", "I"])
    last, date = d.iloc[-1], d.index[-1].date()
    stage = int(last["stage"])
    raw = int(last["raw_stage"])
    color = STAGE_COLORS.get(stage, "#888")
    b, e, c = stages.STAGE_ASSETS.get(stage, ("—", "—", "—"))

    pending = ""
    if raw != stage and raw != 0:
        pending = (f'<div class="note">⚠ 原始判定已轉為 <b>階段{raw} '
                   f'{stages.STAGE_NAMES[raw]}</b>，但尚未滿足連續確認天數，'
                   f'因此正式階段暫不換檔 —— 這是轉折觀察期，值得留意。</div>')

    demo_banner = ('<div class="demo">⚠ 這是以合成資料產生的示範頁面，'
                   '數字不具任何參考價值。請執行 <code>python run.py --html</code> '
                   '取得真實資料。</div>') if demo else ""

    return f"""<!DOCTYPE html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>景氣循環監測</title>
<style>{CSS}</style></head><body><div class="wrap">

<h1>景氣循環監測</h1>
<p class="sub">資料日期 {date}　·　產生時間 {datetime.now():%Y-%m-%d %H:%M}　·　
近 {(d.index[-1]-d.index[0]).days // 365} 年軌跡</p>
{demo_banner}

<div class="hero" style="--hc:{color}">
  <div class="lab">目前判定</div>
  <div class="big">階段 {stage}　{stages.STAGE_NAMES.get(stage,'—')}</div>
  <div class="arrows">債券 {b[1:]}　股票 {e[1:]}　原物料 {c[3:]}</div>
  <div class="desc">{STAGE_DESC.get(stage,'')}</div>
  <div class="scores">
    <div class="score"><div class="k">成長分數 G</div>
      <div class="v">{last['G']:+.2f}</div></div>
    <div class="score"><div class="k">G 三個月動能</div>
      <div class="v">{last['dG']:+.2f}</div></div>
    <div class="score"><div class="k">通膨分數 I</div>
      <div class="v">{last['I']:+.2f}</div></div>
    <div class="score"><div class="k">I 三個月動能</div>
      <div class="v">{last['dI']:+.2f}</div></div>
  </div>
</div>
{pending}
{stage_strip(stage)}

<h2>景氣時鐘</h2>
<div class="card">
  {clock_svg(d)}
  <p class="sub" style="margin:10px 0 0">
    路徑顏色代表當時所處階段。順時針前進代表循環正常推進。</p>
</div>

<h2>分數走勢</h2>
<div class="card">
  {timeseries_svg(d)}
  <div class="legend"><span><i style="background:var(--g)"></i>成長分數 G</span>
  <span><i style="background:var(--i)"></i>通膨分數 I</span>
  <span>背景色＝當時階段</span></div>
</div>

<div class="grid" style="margin-top:18px">
  <div class="card"><h3>成長軸 G 成分</h3>{bars_html(g_parts, cfg.GROWTH_SPECS)}</div>
  <div class="card"><h3>通膨軸 I 成分</h3>{bars_html(i_parts, cfg.INFLATION_SPECS)}</div>
</div>

<div class="grid" style="margin-top:18px">
  <div class="card"><h3>市場儀表板</h3>{market_table(panel, cfg.DASHBOARD)}</div>
  <div class="card"><h3>近期換檔紀錄</h3>{recent_transitions(result)}</div>
</div>

<footer>
  成分數值為三個月動能的滾動 z-score（截斷於 ±3）。
  階段換檔需連續成立達設定天數，以避免分數在 0 附近來回時頻繁跳動。<br>
  資料來源：yfinance（價格）、FRED 公開 CSV（利率與利差）。<br>
  市場資料反映的是<b>對景氣的預期</b>而非景氣本身 —— 反應快，但會有假訊號。
  本頁僅供研究參考，不構成投資建議。
</footer>
</div></body></html>"""
