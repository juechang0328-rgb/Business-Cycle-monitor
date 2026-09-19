"""產生單一自足的 HTML 儀表板（內嵌 SVG，不依賴任何 CDN，可離線開啟）。"""
from __future__ import annotations

import html
from datetime import datetime

import pandas as pd

from . import stages

# 六階段配色。此順序經 CVD／對比驗證：相鄰配對（含 6→1 的循環回捲）
# 在明暗兩種模式下皆通過。要改色請重跑調色盤驗證，不要憑眼睛選。
STAGE_COLORS = {
    1: "#2a78d6",  # 衰退 藍
    2: "#eb6834",  # 谷底 橙
    3: "#1baf7a",  # 復甦 青綠
    4: "#eda100",  # 擴張 黃
    5: "#e87ba4",  # 高峰 洋紅
    6: "#008300",  # 趨緩 綠
}
STAGE_COLORS_DARK = {
    1: "#3987e5", 2: "#d95926", 3: "#199e70",
    4: "#c98500", 5: "#d55181", 6: "#008300",
}

def sc(stage) -> str:
    """SVG 內以 CSS 變數引用階段色，深色模式才會自動切換。"""
    n = int(stage) if stage and int(stage) in STAGE_COLORS else 0
    return f"var(--st{n})" if n else "var(--muted)"

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
              resample: str = "ME") -> str:
    """景氣時鐘：x=通膨分數 I，y=成長分數 G，路徑依時間著色為各階段。

    日頻甚至週頻的軌跡雜訊太高會糊成一團義大利麵，因此降頻到月頻再畫，
    路徑才讀得出方向。階段判定本來也是在月頻上進行，兩者一致。
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
        c = sc(s1)
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
    cn = sc(sn)
    p.append(f'<circle cx="{px(xn):.1f}" cy="{py(yn):.1f}" r="11" fill="{cn}" '
             f'opacity="0.28"/>')
    p.append(f'<circle cx="{px(xn):.1f}" cy="{py(yn):.1f}" r="6.5" fill="{cn}" '
             f'stroke="var(--bg)" stroke-width="2.5"/>')
    p.append(f'<text x="{px(xn)+12:.1f}" y="{py(yn)+4:.1f}" class="ptlabel strong">'
             f'現在 {d.index[-1].strftime("%Y-%m")}</text>')
    # 每年第一個點標年份，讓讀者能沿路徑定位時間
    seen = set()
    for k, ts in enumerate(d.index):
        if ts.year not in seen and k not in (0, len(d) - 1):
            seen.add(ts.year)
            p.append(f'<circle cx="{px(pts[k][0]):.1f}" cy="{py(pts[k][1]):.1f}" '
                     f'r="2.5" fill="var(--muted)"/>')
            p.append(f'<text x="{px(pts[k][0])+6:.1f}" y="{py(pts[k][1])-6:.1f}" '
                     f'class="tick">{ts.year}</text>')

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
            c = sc(st[start])
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
        if s.empty:
            rows.append(f"<tr><td>{_esc(label)}</td><td class='num muted'>—</td>"
                        f"<td class='num muted'>無資料</td></tr>")
            continue
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
            f'<div class="stage-cell {on}" style="--sc:var(--st{s})">'
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
                    f"<td><span class='dot' style='background:{sc(s)}'></span>"
                    f"階段{s} {stages.STAGE_NAMES.get(s,'—')}</td>"
                    f"<td class='num'>{days} 天</td></tr>")
    return ("<table><thead><tr><th>進入日期</th><th>階段</th><th class='num'>持續</th>"
            "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>")


# ------------------------------------------------------------------ 組裝頁面
CSS = """
:root{
  --bg:#ffffff; --panel:#f7f8fa; --line:#e3e6ea; --ink:#16191d; --muted:#6b7280;
  --pos:#1a7f5a; --neg:#c0392b; --g:#2563eb; --i:#d97706;
  --st1:#2a78d6; --st2:#eb6834; --st3:#1baf7a;
  --st4:#eda100; --st5:#e87ba4; --st6:#008300;
}
:root:not([data-theme="light"]){ @media (prefers-color-scheme:dark){
  --bg:#12151a; --panel:#1a1e25; --line:#2b313b; --ink:#e8eaed; --muted:#9aa4b2;
  --pos:#4ade80; --neg:#f87171; --g:#60a5fa; --i:#fbbf24;
  --st1:#3987e5; --st2:#d95926; --st3:#199e70;
  --st4:#c98500; --st5:#d55181; --st6:#008300;
}}
:root[data-theme="dark"]{
  --bg:#12151a; --panel:#1a1e25; --line:#2b313b; --ink:#e8eaed; --muted:#9aa4b2;
  --pos:#4ade80; --neg:#f87171; --g:#60a5fa; --i:#fbbf24;
  --st1:#3987e5; --st2:#d95926; --st3:#199e70;
  --st4:#c98500; --st5:#d55181; --st6:#008300;
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
.score .v{font-size:21px;font-weight:700}
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
.axis0{stroke:var(--line);stroke-width:1;opacity:1}
.tick{font-size:10px;fill:var(--muted)}
.axlabel{font-size:11px;fill:var(--muted)}
.quad{font-size:10px;fill:var(--muted);opacity:.65}
.ptlabel{font-size:10.5px;fill:var(--muted)}
.ptlabel.strong{fill:var(--ink);font-weight:700}
.startpt{fill:var(--muted)}
.lineG{fill:none;stroke:var(--g);stroke-width:2}
.lineReal{fill:none;stroke:var(--ink);stroke-width:2}
.endpt{fill:var(--ink)}
.tl-label{font-size:11.5px;fill:#fff;font-weight:600;
  paint-order:stroke;stroke:rgba(0,0,0,.28);stroke-width:2.5px}
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
.tl-wrap{overflow:hidden}
.tl-legend{display:flex;flex-wrap:wrap;gap:12px;margin-top:10px;font-size:12px;color:var(--muted)}
.tl-legend span{display:flex;align-items:center;gap:5px}
.tl-legend i{width:11px;height:11px;border-radius:3px;display:inline-block}
.explain{background:var(--panel);border:1px solid var(--line);border-radius:12px;
  padding:18px 20px;margin-top:18px}
.explain h3{margin:0 0 10px;font-size:14px}
.explain p{margin:0 0 10px;font-size:13.5px;color:var(--muted);max-width:78ch}
.explain b{color:var(--ink)}
.explain ul{margin:6px 0 10px;padding-left:20px;font-size:13.5px;color:var(--muted)}
.explain li{margin-bottom:5px}
.warnbox{background:var(--panel);border:1px solid var(--line);border-left:4px solid var(--i);
  border-radius:8px;padding:12px 16px;margin-top:14px;font-size:13.5px;color:var(--muted)}
.warnbox b{color:var(--ink)}
.outlook{margin-top:4px}
.ol-dur{font-size:13.5px;color:var(--muted);margin:0 0 14px}
.ol-dur b{color:var(--ink)}
.oc-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:12px}
.oc{background:var(--panel);border:1px solid var(--line);border-left:4px solid var(--oc);
  border-radius:10px;padding:13px 15px}
.oc-head{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.oc-name{font-weight:700;font-size:14px}
.oc-pct{font-size:22px;font-weight:700}
.oc-bar{height:6px;background:var(--bg);border-radius:3px;margin:8px 0 5px;overflow:hidden}
.oc-bar i{display:block;height:100%;background:var(--oc);border-radius:3px}
.oc-n{font-size:11.5px;color:var(--muted);margin-bottom:8px}
.flips{margin:0;padding-left:17px;font-size:12.5px;color:var(--muted)}
.flips li{margin-bottom:6px}
.gap{display:block;font-size:11px;opacity:.8;margin-top:1px}
.flips-ok{margin:0;font-size:12.5px;color:var(--muted)}
.flips-ok b{color:var(--ink)}
.am{margin-top:18px;background:var(--panel);border:1px solid var(--line);
  border-radius:10px;padding:14px 16px}
.am h4{margin:0 0 4px;font-size:13.5px}
.am-row{display:grid;grid-template-columns:22px 60px 88px 1fr;align-items:center;
  gap:8px;padding:5px 0;border-bottom:1px solid var(--line);font-size:13px}
.am-row:last-child{border-bottom:none}
.am-rank{color:var(--muted);font-size:11px}
.am-name{font-weight:600}
.am-val{text-align:right;font-variant-numeric:tabular-nums}
.am-note{color:var(--muted);font-size:11.5px}
@media(max-width:600px){.am-row{grid-template-columns:20px 54px 1fr;}
  .am-note{display:none}}
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
                panel: pd.DataFrame, cfg, demo: bool = False,
                full_result: pd.DataFrame | None = None) -> str:
    d = result.dropna(subset=["G", "I"])
    last, date = d.iloc[-1], d.index[-1].date()
    stage = int(last["stage"])
    raw = int(last["raw_stage"])
    color = sc(stage)
    b, e, c = stages.STAGE_ASSETS.get(stage, ("—", "—", "—"))

    pending = ""
    if raw != stage and raw != 0:
        pending = (f'<div class="note">⚠ 原始判定已轉為 <b>階段{raw} '
                   f'{stages.STAGE_NAMES[raw]}</b>，但尚未滿足連續確認月數，'
                   f'因此正式階段暫不換檔 —— 這是轉折觀察期，值得留意。</div>')

    # 長期時間軸用完整歷史；一個景氣循環約 4-5 年，只看三年看不到完整循環
    long_df = full_result if full_result is not None else result
    span_years = (long_df.index[-1] - long_df.index[0]).days / 365.25
    short_span = ""
    if span_years < 4.5:
        short_span = ('<div class="warnbox">⚠ <b>這段期間短於一個完整景氣循環。</b>'
                      f'目前資料只涵蓋約 {span_years:.1f} 年，而一個循環通常要 4–5 年，'
                      '所以看不到全部六個階段是正常的，不代表景氣沒有循環。'
                      '想看完整循環，用 <code>--start 2006-01-01 --years 20</code> 重跑。</div>')

    from . import forecast
    try:
        o = forecast.next_stage_outlook(long_df)
        outlook = outlook_html(o, forecast.asset_momentum(panel))
    except Exception as e:                      # 推估失敗不應讓整頁掛掉
        outlook = f'<div class="warnbox">下一階段推估無法產生：{_esc(e)}</div>'

    reality = "".join(
        f'<div class="card"><h3>{_esc(t)}</h3>'
        f'{reality_svg(panel, long_df, code, tf)}'
        f'<p class="sub" style="margin:8px 0 0">{_esc(desc)}</p></div>'
        for t, code, tf, desc, _good in getattr(cfg, "REALITY_CHECK", []))

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

<h2>下一階段推估</h2>
{outlook}

<h2>階段時間軸</h2>
<div class="card tl-wrap">
  {stage_timeline_svg(long_df)}
  {timeline_legend()}
  <p class="sub" style="margin:10px 0 0">
    涵蓋全部可用歷史（非僅顯示區間）。色塊寬度＝該階段持續多久，滑過可看起迄日期。</p>
</div>
{short_span}

<h2>這兩個分數是什麼</h2>
<div class="explain">
  <p><b>成長分數 G</b> 不是 GDP，也不是任何官方統計。它是「<b>市場現在怎麼替景氣定價</b>」的
  綜合分數 —— 把四個對景氣最敏感的市場訊號，各自算出「過去三個月的變化」，
  再換算成 z-score（相對於自己的歷史，現在是偏高還偏低），最後加權平均。</p>
  <ul>
    <li><b>G = 0</b>　三個月動能處於歷史平均水準</li>
    <li><b>G = +1</b>　比歷史平均高一個標準差，市場在對「景氣轉強」定價</li>
    <li><b>G = −1</b>　反之</li>
  </ul>
  <p><b>通膨分數 I</b> 同理，衡量市場對物價與原物料的定價。
  兩者一起決定六個階段 —— G 決定股票方向，I 決定債券與原物料方向。</p>
  <p><b>它跟「驗證景氣循環」是什麼關係？</b>
  嚴格說，G <b>不驗證</b>景氣，它<b>提前反映</b>景氣。市場定價平均領先實體經濟約 6–9 個月，
  所以 G 是領先代理變數，不是景氣本身。真正要驗證，得看下面的實體經濟數據 ——
  如果 G 轉弱後幾個月，初領失業金真的開始上升、工業生產真的走弱，那就代表訊號有效；
  如果沒有，那就是假訊號。</p>
</div>

<h2>實體經濟對照</h2>
<div class="grid">{reality}</div>
<p class="sub" style="margin:10px 0 0">
  背景色塊是當時的階段判定，黑線是真實經濟數據。
  兩者是否對得上，就是這套系統可不可信的檢驗。</p>

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
  階段判定在月頻上進行，換檔需連續兩個月成立。<br>
  資料來源：yfinance（價格）、FRED 公開 CSV（利率與利差）。<br>
  市場資料反映的是<b>對景氣的預期</b>而非景氣本身 —— 反應快，但會有假訊號。
  本頁僅供研究參考，不構成投資建議。
</footer>
</div></body></html>"""


# ------------------------------------------------------- 階段時間軸與實體對照
def stage_timeline_svg(df: pd.DataFrame, w: int = 900, h: int = 92) -> str:
    """一條水平時間軸，把整段歷史的階段畫成色塊 —— 最直觀的「看懂循環」入口。"""
    d = df.dropna(subset=["G", "I"])
    if d.empty:
        return "<p>資料不足</p>"
    m = {"l": 4, "r": 4, "t": 4, "b": 26}
    pw, bh = w - m["l"] - m["r"], h - m["t"] - m["b"]
    n = len(d)
    px = lambda i: m["l"] + (i / max(n - 1, 1)) * pw

    p = [f'<svg viewBox="0 0 {w} {h}" class="chart" role="img" '
         f'aria-label="景氣階段時間軸">']
    st = d["stage"].tolist()
    start = 0
    for i in range(1, n + 1):
        if i == n or st[i] != st[start]:
            s0 = int(st[start])
            x1, x2 = px(start), px(i - 1)
            seg_w = max(x2 - x1, 1.0)
            # 2px 表面間隙分隔相鄰色塊，不用描邊
            p.append(f'<rect x="{x1:.1f}" y="{m["t"]}" width="{max(seg_w-2,1):.1f}" '
                     f'height="{bh}" fill="{sc(s0)}" rx="3">'
                     f'<title>階段{s0} {stages.STAGE_NAMES.get(s0,"")}　'
                     f'{d.index[start].date()} → {d.index[i-1].date()}</title></rect>')
            if seg_w > 72 and s0:                       # 夠寬才放字，避免被裁切
                p.append(f'<text x="{(x1+x2)/2:.1f}" y="{m["t"]+bh/2+4:.1f}" '
                         f'class="tl-label" text-anchor="middle">'
                         f'{s0} {stages.STAGE_NAMES.get(s0,"")}</text>')
            start = i

    # 年度刻度：間距不足就跳年標示，避免標籤互相疊字
    years = sorted({d.index[i].year for i in range(n)})
    first_pos = {y: next(i for i in range(n) if d.index[i].year == y) for y in years}
    min_gap = 46
    last_x = -1e9
    for y in years:
        x = px(first_pos[y])
        if x - last_x < min_gap:
            continue
        last_x = x
        p.append(f'<line x1="{x:.1f}" y1="{m["t"]}" x2="{x:.1f}" '
                 f'y2="{m["t"]+bh}" stroke="var(--bg)" stroke-width="1" opacity=".55"/>')
        # 首尾標籤向內縮，避免被畫布邊緣裁掉
        tx = min(max(x, 16), w - 16)
        p.append(f'<text x="{tx:.1f}" y="{h-8}" class="tick" '
                 f'text-anchor="middle">{y}</text>')
    p.append("</svg>")
    return "".join(p)


def timeline_legend() -> str:
    items = "".join(
        f'<span><i style="background:{sc(s)}"></i>{s} {stages.STAGE_NAMES[s]}</span>'
        for s in range(1, 7))
    return f'<div class="tl-legend">{items}</div>'


def reality_svg(panel: pd.DataFrame, result: pd.DataFrame, code: str,
                transform: str, w: int = 430, h: int = 190) -> str:
    """實體經濟對照：真實數據疊在階段色帶上，用來檢驗市場訊號有沒有說對。

    每張圖各有自己的 y 軸（絕不把兩個不同量綱疊在同一個座標系上）。
    """
    if code not in panel.columns:
        return "<p class='sub'>此序列無資料</p>"
    idx = result.dropna(subset=["G", "I"]).index
    s = panel[code].reindex(idx)
    if transform == "yoy":
        s = panel[code].pct_change(252).reindex(idx) * 100
    s = s.dropna()
    if len(s) < 10:
        return "<p class='sub'>歷史不足</p>"

    m = {"l": 44, "r": 10, "t": 10, "b": 24}
    pw, ph = w - m["l"] - m["r"], h - m["t"] - m["b"]
    lo, hi = _nice_bounds(float(s.min()), float(s.max()), 0.10)
    n = len(s)
    px = lambda i: m["l"] + (i / max(n - 1, 1)) * pw
    py = lambda v: m["t"] + _scale(v, lo, hi, ph, 0)

    p = [f'<svg viewBox="0 0 {w} {h}" class="chart" role="img" aria-label="{_esc(code)}">']
    st = result["stage"].reindex(s.index).ffill().fillna(0).tolist()
    start = 0
    for i in range(1, n + 1):
        if i == n or st[i] != st[start]:
            p.append(f'<rect x="{px(start):.1f}" y="{m["t"]}" '
                     f'width="{max(px(i-1)-px(start),0.8):.1f}" height="{ph}" '
                     f'fill="{sc(st[start])}" opacity="0.18"/>')
            start = i

    if lo <= 0 <= hi:
        p.append(f'<line x1="{m["l"]}" y1="{py(0):.1f}" x2="{m["l"]+pw}" '
                 f'y2="{py(0):.1f}" class="axis0"/>')
    pts = " ".join(f"{px(i):.1f},{py(v):.1f}" for i, v in enumerate(s))
    p.append(f'<polyline points="{pts}" class="lineReal"/>')
    # 只標端點，不是每個點都標
    p.append(f'<circle cx="{px(n-1):.1f}" cy="{py(s.iloc[-1]):.1f}" r="4.5" '
             f'class="endpt"/>')
    unit = "%" if transform == "yoy" else ""
    p.append(f'<text x="{px(n-1)-6:.1f}" y="{py(s.iloc[-1])-10:.1f}" '
             f'class="ptlabel strong" text-anchor="end">{s.iloc[-1]:,.1f}{unit}</text>')

    for v in [lo + (hi - lo) * f for f in (0.05, 0.5, 0.95)]:
        p.append(f'<text x="{m["l"]-7}" y="{py(v)+4:.1f}" class="tick" '
                 f'text-anchor="end">{v:,.0f}</text>')
    step = max(n // 4, 1)
    for i in range(0, n, step):
        p.append(f'<text x="{px(i):.1f}" y="{h-7}" class="tick" '
                 f'text-anchor="middle">{s.index[i].strftime("%Y-%m")}</text>')
    p.append("</svg>")
    return "".join(p)


# ------------------------------------------------------------ 下一階段推估
def outlook_html(o: dict, assets: list[dict]) -> str:
    """下一階段推估：歷史基準機率 + 需要什麼條件翻轉才會發生。"""
    cur, n = o["current"], o["sample_size"]
    med = o["median_duration"]
    elapsed = o["elapsed_months"]

    if n == 0:
        return '<div class="warnbox">歷史樣本不足，無法估計下一階段。</div>'

    dur_txt = (f"已持續 <b>{elapsed}</b> 個月"
               + (f"，歷史上此階段中位持續 <b>{med:.0f}</b> 個月" if med == med else ""))
    if med == med and elapsed > med:
        dur_txt += "　—　已超過中位持續期，轉折風險升高"

    cards = []
    for c in o["candidates"]:
        col = sc(c["stage"])
        pct = c["prob"] * 100
        if c["flips"]:
            reasons = "".join(
                f'<li>{_esc(f["text"])}'
                f'<span class="gap">目前 {f["current"]:+.2f}，距分界 {f["gap"]:.2f}</span></li>'
                for f in c["flips"])
            why = f"<ul class='flips'>{reasons}</ul>"
        else:
            why = ('<p class="flips-ok">判定條件<b>已經滿足</b>，'
                   '正在等待連續確認期 —— 這是最接近換檔的狀態。</p>')
        cards.append(
            f'<div class="oc" style="--oc:{col}">'
            f'  <div class="oc-head">'
            f'    <span class="oc-name">階段{c["stage"]} {stages.STAGE_NAMES[c["stage"]]}</span>'
            f'    <span class="oc-pct">{pct:.0f}%</span></div>'
            f'  <div class="oc-bar"><i style="width:{pct:.0f}%"></i></div>'
            f'  <div class="oc-n">歷史上 {c["count"]} / {n} 次</div>'
            f'  {why}</div>')

    rank = "".join(
        f'<div class="am-row"><span class="am-rank">{i+1}</span>'
        f'<span class="am-name">{_esc(m["name"])}</span>'
        f'<span class="am-val {"pos" if m["value"]>=0 else "neg"}">'
        f'{m["value"]:+.2f}{m["unit"]}</span>'
        f'<span class="am-note">{_esc(m["note"])}</span></div>'
        for i, m in enumerate(assets))

    return f"""
<div class="outlook">
  <p class="ol-dur">{dur_txt}</p>
  <div class="oc-grid">{"".join(cards)}</div>
  <div class="am">
    <h4>三類資產目前的三個月動能</h4>
    <p class="sub" style="margin:0 0 8px">
      投影片三個箭頭的當前讀數。強弱順序就是判斷階段的直覺依據 ——
      例如原物料領先而債券墊底，對應的是通膨上行、利率承壓的階段。</p>
    {rank}
  </div>
  <div class="warnbox" style="margin-top:14px">
    <b>這些百分比是歷史基準率，不是模型預測。</b>
    意思是「過去處在同一階段時，下一段實際走到哪裡」的次數佔比，
    樣本數 N={n}。N 只有個位數時，該百分比幾乎沒有參考價值。
    這套模型尚未證明具備預測力（見 <code>validate.py</code>），
    請把它當作「目前距離各個分界有多遠」的量尺，而不是預測。
  </div>
</div>"""
