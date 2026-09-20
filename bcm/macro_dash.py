"""總經儀表板：五大區塊 × 指標卡片 + 資料健康檢查。

定位：描述「現在市場在發生什麼」，不宣稱預測。
每張卡片包含當前值、變化、12 個月迷你走勢，以及（若有）門檻位置。
"""
from __future__ import annotations

import html
from datetime import datetime

import numpy as np
import pandas as pd

from . import briefing, derived, glossary, health


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
    out = ((s / base - 1) * 100).replace([np.inf, -np.inf], np.nan).dropna()
    if not out.empty or len(s) < 2:
        return out
    # 歷史還不足一個 offset 時（例如序列剛換資料來源），上面整條都會是
    # 缺值，卡片就變成「無資料」—— 明明有資料只是還不夠長。
    # 改以序列第一筆為基準，實際比較了多久由卡片照實標示。
    s = s.dropna()
    return ((s / s.iloc[0] - 1) * 100).replace(
        [np.inf, -np.inf], np.nan).dropna()



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
    return s                                        # level / price


def metric_snapshot(panel: pd.DataFrame, code: str, mode: str) -> dict:
    s = metric_series(panel, code, mode)
    if s.empty:
        return {"ok": False}
    cur = float(s.iloc[-1])
    # 變化基準用「三個月前的那一天」，不是「往回數 63 列」。
    # 數列數會因為交易日多寡而漂移：台股與美股的交易日不重疊，同樣數 63 列
    # 落到的日期就差好幾天，標籤寫「近3個月」卻不是真的三個月。
    # 歷史不足三個月時退回序列第一筆，實際比較了多久由 span_days 據實回報。
    target = s.index[-1] - pd.DateOffset(months=3)
    earlier = s.loc[:target]
    if len(earlier):
        prev, base_date = float(earlier.iloc[-1]), earlier.index[-1]
    else:
        prev, base_date = float(s.iloc[0]), s.index[0]
    return {"ok": True, "series": s, "current": cur, "prev": prev,
            "change": cur - prev, "last_date": s.index[-1],
            # 實際比較了多久。序列還短時（例如剛換資料來源）不能沿用
            # 「近3個月」這個標籤，那會把三天的變化講成三個月的變化。
            "span_days": int((s.index[-1] - base_date).days)}


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

    # 把資料點一併嵌入，讓瀏覽器自己做游標查值 —— 不需要伺服器。
    # 日期用 YYMMDD 六碼、數值依量級決定小數位，以控制頁面大小。
    dec = 0 if abs(hi) >= 1000 else (2 if abs(hi) >= 1 else 4)
    d_attr = ",".join(t.strftime("%y%m%d") for t in d.index)
    v_attr = ",".join(f"{v:.{dec}f}" for v in d)
    p = [f'<svg viewBox="0 0 {w} {h}" class="spark" preserveAspectRatio="none" '
         f'data-d="{d_attr}" data-v="{v_attr}" '
         f'data-lo="{lo:.6g}" data-hi="{hi:.6g}" '
         f'data-pad="{2}" data-w="{w}" data-h="{h}" '
         f'role="img" aria-label="近 {months} 個月走勢">']
    for key, tv in shown:
        p.append(f'<line x1="2" y1="{py(tv):.1f}" x2="{w-2}" y2="{py(tv):.1f}" '
                 f'class="spark-th"><title>門檻 {key}={tv}</title></line>')
    pts = " ".join(f"{px(i):.1f},{py(v):.1f}" for i, v in enumerate(d))
    # 單一中性色：走勢圖只表示形狀，不暗示好壞
    p.append(f'<polyline points="{pts}" class="spark-line"/>')
    p.append(f'<circle cx="{px(n-1):.1f}" cy="{py(float(d.iloc[-1])):.1f}" '
             f'r="2.6" class="spark-dot"/>')
    p.append(f'<line class="spark-cross" x1="0" y1="2" x2="0" y2="{h-2}"/>')
    p.append(f'<circle class="spark-hit" cx="0" cy="0" r="3"/>')
    p.append("</svg>")
    return "".join(p)


# ------------------------------------------------------------------ 卡片
def threshold_note(code: str, cur: float, th: dict | None) -> tuple[str, str]:
    """回傳 (狀態文字, 狀態等級)。等級用於上色：calm/normal/warn/alert。"""
    if not th:
        return "", ""
    if "warn" in th and code == "SAHMREALTIME":
        # 單向指標：只有「上升越過 0.50」有意義，往下掉不是好消息也不是事件。
        # 因此顯示「離觸發還有多遠」，而不是光寫一個門檻數字。
        return (("已觸發衰退訊號", "alert") if cur >= th["warn"]
                else (f"距觸發 {th['warn'] - cur:.2f}pp", "calm"))
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
    if "scarce" in th:          # SOFR − IORB：轉正代表附買回市場在搶錢
        if cur <= th["scarce"] - 3:
            return ("準備金充裕", "calm")
        if cur <= th["scarce"] + 5:
            return ("接近中性", "normal")
        if cur <= th["scarce"] + 15:
            return ("準備金偏緊", "warn")
        return ("附買回市場吃緊", "alert")
    if "tight" in th:
        return (("條件偏緊", "warn") if cur > th["tight"] else ("條件寬鬆", "calm"))
    return "", ""


def glossary_block(code: str) -> str:
    """卡片上的 ⓘ 展開說明。

    用 <details> 而非右鍵選單或 hover 提示：右鍵會與瀏覽器原生選單衝突、
    行動裝置沒有右鍵、hover 在觸控裝置上也不存在。<details> 三者皆可用，
    而且不需要 JavaScript。
    """
    m = glossary.get(code)
    if not m:
        return ""
    rows = [("定義", m["what"]), ("計算", m["formula"]),
            ("來源", m["src"]), ("怎麼看", m["how"])]
    body = "".join(f'<dt>{k}</dt><dd>{v}</dd>' for k, v in rows)
    return (f'<details class="gloss"><summary>ⓘ 說明</summary>'
            f'<div class="gloss-body"><p class="gloss-full">{m["full"]}</p>'
            f'<dl>{body}</dl></div></details>')


# price：指數／價格。主值顯示點位本身，變化以 % 呈現。
# 不用 pct 是因為 pct 會把「近三個月報酬率」當成主值，下面那行就變成
# 「報酬率相對三個月前的報酬率」—— 差分做了兩次，沒人讀得懂。
UNIT_BY_MODE = {"yoy": "%", "m3ann": "%", "pct": "%", "level": "", "price": ""}
# 比率型指標的主值本身已是比率，其「變化」是比率的變化，單位為百分點，
# 標籤必須與水準型區分，否則同一張卡上會出現兩個看似矛盾的百分比。
CHANGE_LABEL = {"level": "近3個月", "yoy": "較3個月前",
                "m3ann": "較3個月前", "pct": "較3個月前", "price": "近3個月"}
CHANGE_UNIT = {"level": "", "yoy": "pp", "m3ann": "pp", "pct": "pp",
               "price": "%"}


# 原始 FRED 序列的顯示單位換算。央行資產負債表各項以「百萬美元」發布，
# 直接印出來是 6,746,548 這種數字 —— 正確但沒人讀得出量級。
# （衍生序列的換算寫在 bcm/derived.py，兩邊不重複。）
SCALE_BY_CODE = {
    "WALCL":     (1e-6, "兆美元"),      # 百萬 → 兆
    "WRESBAL":   (1e-6, "兆美元"),
    "WTREGEN":   (1e-3, "十億美元"),    # 百萬 → 十億（TGA 量級較小）
    "RRPONTSYD": (1.0,  "十億美元"),    # 本來就是十億
}


# 比值卡片的白話判讀：{代碼: (上升時的意思, 下降時的意思)}。
# 只描述「錢往哪邊流」這件已經發生的事，不講後市 ——
# 本專案實測過景氣階段模型沒有預測力，這一區同樣不該被當成訊號。
RATIO_READING = {
    "RATIO_SMALL_LARGE": ("資金下沉到小型股，風險偏好提高",
                          "資金退回大型股避險"),
    "RATIO_NDX_SPX":     ("資金偏好成長與科技股",
                          "往價值與防禦類股輪動"),
    "RATIO_OTC_TWSE":    ("台股投機氣氛升溫，中小型股較強",
                          "台股資金集中到權值股"),
    "RATIO_HY_IG":       ("願意承擔信用風險換取收益",
                          "信用市場轉趨保守"),
    "RATIO_CYC_DEF":     ("市場押景氣擴張",
                          "往防禦類股撤退"),
    "RATIO_BREADTH":     ("上漲的家數變廣",
                          "漲勢集中在少數權值股"),
}


def history_rank(s: pd.Series, years: int = 5) -> tuple[float, str] | None:
    """現值落在自己近 N 年區間的第幾百分位。

    比值的絕對數字沒有意義，但「它相對自己的歷史算高還是低」有。
    少了這個，卡片上那串數字對讀者來說就只是一串數字。
    """
    if s is None or len(s) < 60:
        return None
    win = s.loc[s.index[-1] - pd.DateOffset(years=years):].dropna()
    if len(win) < 60:
        win = s.dropna()
    if len(win) < 60:
        return None
    pct = float((win <= win.iloc[-1]).mean() * 100)
    band = "偏低" if pct < 25 else ("偏高" if pct > 75 else "中性")
    return pct, band


def metric_card(panel: pd.DataFrame, name: str, code: str,
                mode: str, th: dict | None, zscore: float | None = None,
                last_obs: pd.Timestamp | None = None) -> str:
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
    raw_scale = SCALE_BY_CODE.get(code) if mode == "level" else None
    if mode == "price":
        cur_disp = _fmt(cur)
        pct = (cur / snap["prev"] - 1) * 100 if snap["prev"] else float("nan")
        chg_disp = f"{pct:+,.2f}%"
    elif spec and mode == "level":
        cur_disp = _fmt(cur * spec["scale"], spec["display_unit"])
        chg_disp = f'{chg*spec["scale"]:+,.2f}'
    elif raw_scale:
        f, u = raw_scale
        cur_disp = _fmt(cur * f, u)
        chg_disp = f"{chg*f:+,.2f}"
    else:
        cur_disp = _fmt(cur, unit)
        chg_disp = f"{chg:+,.2f}{cunit}"

    # 變化的極端程度：以該指標自己的歷史變化分布為基準
    zchip = ""
    if zscore is not None and not np.isnan(zscore) and abs(zscore) >= ANOMALY_Z:
        zchip = (f'<span class="zchip">⚠ {abs(zscore):.1f}σ</span>')

    # 卡片下緣的日期要是「真實觀測日」。面板每一欄都被向前填補到最後一個
    # 營業日，直接用 snap["last_date"] 會讓月頻指標看起來像今天剛公布。
    obs = last_obs if last_obs is not None and not pd.isna(last_obs) \
        else snap["last_date"]
    obs_date = pd.Timestamp(obs).date()

    # 歷史不足 3 個月時照實說比較了幾天，不要沿用「近3個月」的標籤
    span = snap.get("span_days")
    chg_lab = CHANGE_LABEL.get(mode, "近3個月")
    if span is not None and span < 70:
        chg_lab = f"近{span}天" if span >= 2 else "較前一筆"

    note, lvl = threshold_note(code, cur, th)
    # 方向本身不帶好壞：VIX 與信用利差上升是壞事，用綠漲紅跌會傳達相反意思。
    # 因此變化值用中性色，只以箭頭表示方向，語意由門檻徽章承擔。
    # 依四捨五入後的顯示值判斷方向，避免出現「▲ +0.00」這種自相矛盾的組合
    if mode == "price":
        shown_chg = round(pct, 2)
    else:
        _sc = spec["scale"] if spec and mode == "level" else (
            raw_scale[0] if raw_scale else 1)
        shown_chg = round(chg * _sc, 2)
    arrow = "▲" if shown_chg > 0 else ("▼" if shown_chg < 0 else "—")

    # 比值卡片：徽章顯示它在自己歷史區間的位置，下方補一行白話判讀。
    # 只給一個比值的絕對數字，讀者無從判斷現在算高還是低、錢往哪流。
    reading = rank_badge = ""
    if code in RATIO_READING:
        rk = history_rank(snap["series"])
        if rk:
            pct_rank, band = rk
            rank_badge = (f'<span class="m-badge normal" '
                          f'title="現值落在近 5 年區間的第 {pct_rank:.0f} 百分位">'
                          f'5年{band} {pct_rank:.0f}%</span>')
        up, down = RATIO_READING[code]
        if shown_chg:
            reading = (f'<div class="m-note">'
                       f'{up if shown_chg > 0 else down}</div>')

    badge = (f'<span class="m-badge {lvl}">{_esc(note)}</span>' if note
             else rank_badge)
    return (
        f'<div class="mcard">'
        f'  <div class="m-head"><span class="m-name">{_esc(name)}</span>{badge}</div>'
        f'  <div class="m-val">{cur_disp}</div>'
        f'  <div class="m-chg"><span class="m-arrow">{arrow}</span>{chg_disp}'
        f'<span class="m-chg-lab">{chg_lab}</span>{zchip}</div>{reading}'
        f'  {sparkline(snap["series"], thresholds=th)}'
        f'  <div class="m-sub">{obs_date}　{_esc(code)}</div>'
        f'  {glossary_block(code)}'
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

    # 沒有真實觀測日紀錄時，「最後更新」只是面板日期，不能當成已驗證
    nver = summary.get("unverified", 0)
    unverified_note = (
        f'<div class="warnbox"><b>{nver} 項的更新日期尚未驗證</b><br>'
        f'<span class="sub2">快取裡還沒有這些欄位的真實觀測日紀錄，'
        f'表中的「最後更新」暫時沿用面板日期，因此不足以判斷是否停更。'
        f'下一次線上抓取後會自動補上。</span></div>') if nver else ""

    # 未驗證也算「不能宣稱正常」：否則標題會寫「全部正常」，
    # 而底下同時寫著「更新日期尚未驗證」，自相矛盾
    has_problem = bool(len(bad) or skipped or nver)
    banner_cls = "ok" if not has_problem else (
        "alert" if (summary["missing"] or summary["stalled"]) else "warn")
    if not has_problem:
        banner_txt = "全部 %d 項資料正常" % summary["total"]
    elif len(bad) or skipped:
        banner_txt = (f'{len(bad)} 項異常　·　'
                      f'{summary["ok"]}/{summary["total"]} 項正常')
    else:
        banner_txt = f'{nver} 項更新日期待驗證'
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
    超過容許值三倍視為停更。容差已計入公布延遲與連假。
    「最後更新」取自向前填補<b>之前</b>的真實觀測日 —— 面板裡每一欄都被填到
    最後一個營業日，只看面板會讓每個序列都像是今天剛更新。</p>
    {unverified_note}
  </div>
</details>"""


# 少數區塊光看數字判讀不出來，在標題下補一行說明它能回答什麼問題。
GROUP_NOTES = {
    "央行流動性":
        "這一區<b>不是訊號區</b>。本專案實測 2003 年以來 Fed 淨流動性與標普500 的關係，"
        "方向會隨時代翻轉（2008–09 同期 −0.67、2010–19 +0.19、2022–26 領先 +0.36），"
        "無法用來預測。它的用途是看「管道還通不通」：真正有門檻可判讀的是 "
        "<b>SOFR−IORB</b> 與<b>銀行準備金</b> —— 前者持續轉正代表準備金已經稀缺，"
        "Fed 就得停止縮表。其餘幾項是拆解用的零件。",
    "市場情緒":
        "台股與美股交易時段不重疊，台股的最新值通常比美股早一個日曆日。"
        "這一區<b>固定順序</b>，不依變化幅度重排 —— 每天位置一樣才好比對。",
    "資金流向":
        "全部是<b>比值</b>（A÷B），回答的是「錢往哪邊跑」，不是「會漲還是會跌」。"
        "相除之後兩邊共同的因素（大盤漲跌、利率水準）大致抵銷，"
        "剩下的才是資金偏好的變化。"
        "<br><b>怎麼看這幾張卡</b>：比值那個數字本身不用管，看另外兩樣 ——"
        "① <b>徽章</b>：現值落在自己近 5 年區間的第幾百分位（偏低／中性／偏高）；"
        "② <b>灰線那句話</b>：近三個月的方向代表錢往哪邊流。"
        "兩者要一起看：「偏低且還在往下」是持續的趨勢，"
        "「偏低但轉為往上」才是變化。"
        "<br>這些是<b>同期描述</b>，不是領先指標。本專案已經實測過景氣階段模型"
        "對未來報酬沒有預測力，這一區同樣不該拿來擇時。",
}


def groups_html(panel: pd.DataFrame, groups: list[tuple],
                extra: dict[str, str] | None = None,
                fixed_order: set[str] | None = None,
                last_obs: pd.Series | None = None) -> str:
    extra = extra or {}
    fixed_order = fixed_order or set()
    lo = last_obs if last_obs is not None else pd.Series(dtype="datetime64[ns]")
    out = []
    for title, items in groups:
        # 有內在順序的區塊（例如殖利率天期）維持宣告順序
        ordered = items if title in fixed_order else rank_items(panel, items)
        cards, n_anom = [], 0
        for it in ordered:
            snap = metric_snapshot(panel, it[1], it[2])
            z = (change_zscore(snap["series"], relative=it[2] == "price")
                 if snap["ok"] else float("nan"))
            # 沒有判讀意義的指標不計入「變化異常」：標題掛著警告、
            # 點開卻發現是離門檻還很遠的 Sahm Rule，只會磨掉警告的可信度
            dormant = snap["ok"] and is_dormant(it[1], it[3], snap["current"])
            if not np.isnan(z) and abs(z) >= ANOMALY_Z and not dormant:
                n_anom += 1
            cards.append(metric_card(panel, *it, zscore=z,
                                     last_obs=lo.get(it[1])))
        n_ok = sum(1 for it in items if metric_snapshot(panel, it[1], it[2])["ok"])
        anom = (f'<span class="grp-anom">⚠ {n_anom} 項變化異常</span>'
                if n_anom else "")
        note = GROUP_NOTES.get(title, "")
        note_html = f'<p class="grp-note">{note}</p>' if note else ""
        out.append(
            f'<section class="grp"><h2>{_esc(title)}'
            f'<span class="grp-n">{n_ok}/{len(items)}</span>{anom}</h2>'
            f'{note_html}{extra.get(title, "")}'
            f'<div class="mgrid">{"".join(cards)}</div></section>')
    return "".join(out)


# 游標查值：全部在瀏覽器裡跑，不需要伺服器。
# 資料已嵌在每個 <svg> 的 data-d / data-v 屬性裡。
HOVER_JS = """
<div id="tip"></div>
<script>
(function(){
  var tip = document.getElementById('tip');
  function fmtDate(s){            // YYMMDD -> YYYY-MM-DD
    return '20'+s.slice(0,2)+'-'+s.slice(2,4)+'-'+s.slice(4,6);
  }
  function attach(svg){
    var ds = svg.getAttribute('data-d'), vs = svg.getAttribute('data-v');
    if(!ds || !vs) return;
    var dates = ds.split(','), vals = vs.split(',').map(Number);
    var lo = +svg.getAttribute('data-lo'), hi = +svg.getAttribute('data-hi');
    var W = +svg.getAttribute('data-w'), H = +svg.getAttribute('data-h');
    var pad = +svg.getAttribute('data-pad');
    var cross = svg.querySelector('.spark-cross');
    var hit = svg.querySelector('.spark-hit');
    var n = vals.length;
    function px(i){ return pad + i/Math.max(n-1,1)*(W-pad*2); }
    function py(v){ return 3 + (hi-v)/(hi-lo)*(H-6); }

    function move(ev){
      var r = svg.getBoundingClientRect();
      var cx = (ev.touches ? ev.touches[0].clientX : ev.clientX);
      var cy = (ev.touches ? ev.touches[0].clientY : ev.clientY);
      var frac = (cx - r.left) / r.width;
      var i = Math.round(frac * (n-1));
      if(i < 0) i = 0; if(i > n-1) i = n-1;
      svg.classList.add('on');
      cross.setAttribute('x1', px(i)); cross.setAttribute('x2', px(i));
      hit.setAttribute('cx', px(i)); hit.setAttribute('cy', py(vals[i]));
      tip.innerHTML = fmtDate(dates[i]) + '　<b>' + vals[i] + '</b>';
      tip.classList.add('on');
      var tw = tip.offsetWidth, th = tip.offsetHeight;
      var left = cx + 12, top = cy - th - 10;
      if(left + tw > window.innerWidth - 8) left = cx - tw - 12;
      if(top < 8) top = cy + 16;
      tip.style.left = left + 'px'; tip.style.top = top + 'px';
    }
    function leave(){
      svg.classList.remove('on'); tip.classList.remove('on');
    }
    svg.addEventListener('mousemove', move);
    svg.addEventListener('mouseleave', leave);
    svg.addEventListener('touchstart', move, {passive:true});
    svg.addEventListener('touchmove', move, {passive:true});
    svg.addEventListener('touchend', leave);
  }
  document.querySelectorAll('svg.spark').forEach(attach);
})();
</script>
"""


# ------------------------------------------------------------------- 頁面
CSS = """
/* 配色原則
   1. 狀態色（ok／warn／alert）在兩種模式維持同一組色相家族，只換明度階。
      先前深色模式直接換成另一組更亮的色（#4ade80／#fbbf24），對比高達 9–10:1，
      比數值本身還搶眼，且綠色由青綠跳成薄荷綠 —— 看起來像另一套設計。
   2. 深色底改用中性灰。原本的 #0f1216 帶藍調，和藍色走勢線同色系，
      整頁糊成一片冷藍。
   3. 兩種模式的狀態色都落在 4.4–7.0:1，足以閱讀又不會蓋過主要數字。
   4. 折線色 s1/s2/s3 為已驗證的分類色序（色盲可辨），不隨模式換色相。 */
:root{
  --bg:#fff;--panel:#f7f8fa;--card:#fff;--line:#e3e6ea;--ink:#16191d;--muted:#6b7280;
  --accent:#2a78d6;--ok:#0f7a2e;--warn:#a86a00;--alert:#bf3030;--dead:#8b8f98;
  --band:#6b7280;--band-op:.14;
  --s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;
}
:root:not([data-theme="light"]){@media(prefers-color-scheme:dark){
  --bg:#101010;--panel:#191918;--card:#1c1c1b;--line:#34342f;--ink:#ececea;--muted:#a3a29a;
  --accent:#3987e5;--ok:#35b45e;--warn:#d99a17;--alert:#e06a6a;--dead:#7d7c75;
  --band:#ffffff;--band-op:.09;
  --s1:#3987e5;--s2:#d95926;--s3:#199e70;}}
:root[data-theme="dark"]{
  --bg:#101010;--panel:#191918;--card:#1c1c1b;--line:#34342f;--ink:#ececea;--muted:#a3a29a;
  --accent:#3987e5;--ok:#35b45e;--warn:#d99a17;--alert:#e06a6a;--dead:#7d7c75;
  --band:#ffffff;--band-op:.09;
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
.brief{background:var(--panel);border:1px solid var(--line);
 border-left:5px solid var(--accent);border-radius:12px;
 padding:15px 18px 13px;margin-bottom:18px}
.brief-head{display:flex;align-items:baseline;gap:10px;margin-bottom:9px}
.brief-title{font-weight:700;font-size:15px}
.brief-date{color:var(--muted);font-size:12px}
.brief-list{margin:0;padding-left:19px;font-size:13.5px;line-height:1.75}
.brief-list li{margin-bottom:5px}
.brief-list b{color:var(--ink)}
.brief-foot{margin:10px 0 0;padding-top:9px;border-top:1px solid var(--line);
 font-size:11.5px;color:var(--muted);line-height:1.65}
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
.grp-note{font-size:12.5px;color:var(--muted);margin:-4px 0 12px;max-width:88ch;
 line-height:1.7;border-left:2px solid var(--line);padding-left:10px}
.zchip{margin-left:6px;font-size:10.5px;color:var(--warn);
 border:1px solid currentColor;border-radius:99px;padding:0 5px;white-space:nowrap}
/* 殖利率曲線圖。先前 .chart／.tick／.grid 完全沒有規則，SVG 的 <text>
   沒指定 fill 就預設黑色 —— 淺色模式剛好看起來正常，深色模式下座標軸
   等於消失在背景裡。這類「只有一半模式會壞」的缺漏最容易漏掉。 */
.chart{width:100%;height:auto;display:block}
.tick{fill:var(--muted);font-size:11.5px;font-variant-numeric:tabular-nums}
.grid{stroke:var(--line);stroke-width:1}
.curve-lab{font-size:11.5px;font-weight:700}
.policy-band{fill:var(--band);opacity:var(--band-op)}
.policy-lab{font-size:10.5px;fill:var(--muted)}
.shape{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin-bottom:10px}
.shape-tag{font-size:15px;font-weight:700;padding:3px 11px;border-radius:99px;
 background:color-mix(in srgb,var(--accent) 14%,transparent);color:var(--accent)}
.shape-note{font-size:12.5px;color:var(--muted);flex:1;min-width:260px;line-height:1.6}
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
.m-note{font-size:11.5px;color:var(--muted);line-height:1.5;margin:4px 0 1px;
 padding-left:8px;border-left:2px solid var(--line)}
.spark{width:100%;height:40px;display:block;margin:4px 0 2px}
.spark-line{fill:none;stroke:var(--accent);stroke-width:1.6;
 stroke-linejoin:round;stroke-linecap:round}
.spark-dot{fill:var(--accent)}
.spark-th{stroke:var(--muted);stroke-width:1;opacity:.45}
.spark-empty{height:40px;display:flex;align-items:center;color:var(--muted);font-size:11.5px}
.gloss{margin-top:7px;border-top:1px solid var(--line);padding-top:6px}
.gloss summary{cursor:pointer;font-size:11px;color:var(--muted);list-style:none;
 display:inline-block;padding:1px 0}
.gloss summary::-webkit-details-marker{display:none}
.gloss summary:hover{color:var(--accent)}
.gloss[open] summary{color:var(--accent);margin-bottom:5px}
.gloss-body{font-size:11.5px;line-height:1.65}
.gloss-full{margin:0 0 6px;font-weight:600;color:var(--ink);font-size:12px}
.gloss dl{margin:0;display:grid;grid-template-columns:44px 1fr;gap:3px 8px}
.gloss dt{color:var(--muted);font-size:10.5px;padding-top:1px}
.gloss dd{margin:0;color:var(--muted)}
.gloss b{color:var(--ink)}
.spark-cross{stroke:var(--muted);stroke-width:1;opacity:0;pointer-events:none}
.spark-hit{fill:var(--accent);opacity:0;pointer-events:none}
.spark.on .spark-cross,.spark.on .spark-hit{opacity:.85}
.spark{cursor:crosshair}
#tip{position:fixed;z-index:50;background:var(--card);border:1px solid var(--line);
 border-radius:7px;padding:6px 9px;font-size:12px;box-shadow:0 4px 14px rgba(0,0,0,.14);
 pointer-events:none;opacity:0;transition:opacity .08s;white-space:nowrap}
#tip.on{opacity:1}
#tip b{font-variant-numeric:tabular-nums}
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
           demo: bool = False, projections: pd.DataFrame | None = None,
           last_obs: pd.Series | None = None) -> str:
    a = cfg.active()
    groups = a.get("groups", [])
    hspec = a.get("health", [])
    unavailable = a.get("unavailable", [])
    asof = panel.index[-1]

    # 前瞻性序列不在面板裡（會汙染時間軸），但仍要納入健康檢查：
    # 只為檢查而暫時併進來，asof 已先從面板取定，不受未來日期影響。
    hpanel = panel if projections is None or not len(projections) \
        else panel.join(projections, how="outer")
    h = health.check_panel(hpanel, hspec, asof=asof, last_obs=last_obs)
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
  <br>區塊內先看<b>這個變化有沒有判讀意義</b>，再看<b>變化有多極端</b>
  （變化量相對該指標自己歷史變化分布的 z 分數）。單向指標離門檻還很遠時
  （例如 Sahm Rule 距觸發 0.50 尚有一段），它往哪動都不代表事情，會被排到後面，
  也不計入「變化異常」。排在前面<b>不分方向</b>，只代表動得不尋常，可能是好事也可能是壞事。
  公債殖利率區塊例外，固定依天期排列。
</p>
{demo_banner}
{briefing.render(panel, cfg, health_df=h)}
{health_panel(h, summary, unavailable, skipped or {})}
{groups_html(panel, groups,
             extra={"公債殖利率": yield_curve_svg(panel)
                    + dotplot_table(projections, panel)},
             fixed_order=a.get("fixed_order"), last_obs=last_obs)}

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
</div>{HOVER_JS}</body></html>"""


# ------------------------------------------------------- 變化幅度標準化排序
# 不同指標的變化量無法直接比較：VIX 漲 5 點與 CPI 漲 0.3pp 是不同量綱。
# 因此改用「這次的三個月變化，相對於該指標自己歷史上的三個月變化」有多極端，
# 也就是變化量的 z-score。如此才能跨指標排序。
ANOMALY_Z = 2.0          # |z| 超過此值標示為異常


def change_zscore(s: pd.Series, offset=None, relative: bool = False) -> float:
    """本次變化在該序列歷史變化分布中的 z 分數。

    relative：改用百分比變化而非絕對變化。指數點位一定要開這個 ——
    標普從 3,446 漲到 47,741，同樣「漲 300 點」在 1998 和 2026 意義天差地遠，
    拿絕對變化量做 z 分數會系統性地把近期的波動誇大成異常。
    """
    offset = offset or pd.DateOffset(months=3)
    if s.empty or len(s) < 60:
        return float("nan")
    base = _shift_by(s, offset)
    if relative:
        diffs = ((s / base - 1) * 100).replace(
            [np.inf, -np.inf], np.nan).dropna()
    else:
        diffs = (s - base).dropna()
    if len(diffs) < 30:
        return float("nan")
    sd = diffs.std()
    if not sd or np.isnan(sd):
        return float("nan")
    return float((diffs.iloc[-1] - diffs.mean()) / sd)


# 只有單向移動才帶有訊息的指標。
# {代碼: (有意義的方向, 門檻鍵, 安全邊距)}，方向 +1 表示「上升越過門檻」才算事件。
#
# 為什麼需要這張表：排序是依變化量的 z 分數，但「變化大」不等於「有意義」。
# Sahm Rule 現值 −0.07、離觸發門檻 0.50 還有 0.57pp，這種距離下它往上往下
# 動都不代表任何事 —— 它的公式是「與前 12 個月最低值的差」，失業率創新低時
# 分母會被重設，負得更多完全不是好消息也不是壞消息。可是它的 |z| 很容易偏大，
# 結果版面最好的位置被一個根本不需要看的指標佔走。
#
# 要新增項目請確認它真的是單向的：例如高收益債利差、核心PCE 兩個方向都有
# 訊息，就不該放進來。
ONE_SIDED = {
    "SAHMREALTIME": (+1, "warn", 0.20),
}


def is_dormant(code: str, th: dict | None, current: float) -> bool:
    """目前的變化是否不具判讀意義（單向指標且離門檻還很遠）。"""
    spec = ONE_SIDED.get(code)
    if not spec or not th:
        return False
    sign, key, margin = spec
    limit = th.get(key)
    if limit is None or current is None or np.isnan(current):
        return False
    gap = (limit - current) if sign > 0 else (current - limit)
    return gap > margin


def rank_items(panel: pd.DataFrame, items: list[tuple]) -> list[tuple]:
    """區塊內排序：先看「這個變化有沒有判讀意義」，再看變化有多極端。

    只用 |z| 排序會把「動得大但不代表任何事」的指標推到最前面，
    所以先分層：有意義的在前、暫時沒有判讀意義的沉到後面、取不到值的最後。
    """
    scored = []
    for it in items:
        name, code, mode, th = it
        snap = metric_snapshot(panel, code, mode)
        if not snap["ok"]:
            scored.append((it, 2, 0.0))
            continue
        z = change_zscore(snap["series"], relative=mode == "price")
        tier = 1 if is_dormant(code, th, snap["current"]) else 0
        scored.append((it, tier, 0.0 if np.isnan(z) else abs(z)))
    return [it for it, _, _ in sorted(scored, key=lambda t: (t[1], -t[2]))]


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


# 曲線型態判讀。教科書通常只教正斜率／倒掛／平坦三種，
# 但實務上「駝峰」與「U 型」同樣常見 —— 後者正是政策利率高、
# 市場預期降息、長端又有期限溢酬時的典型形狀。
FLAT_BAND = 0.25          # |10Y−3M| 在此範圍內視為平坦
STEEP_BAND = 1.50


def classify_curve(curve: list[tuple[str, float]]) -> tuple[str, str]:
    """回傳 (型態名稱, 說明)。curve 為 [(天期標籤, 殖利率), ...] 由短到長。

    分成「主型態」與「次要特徵」兩層，因為兩者可以同時成立 ——
    2024-25 年的美債曲線就是典型：整體仍倒掛（10Y 低於 3M），
    但中段落底後長端回升，形狀像一個碗。只講其中一個都不完整。
    """
    d = dict(curve)
    labels = [l for l, _ in curve]
    if len(curve) < 4:
        return "資料不足", "可用天期太少，無法判斷形狀。"

    short = d.get("3M", d.get("1M", curve[0][1]))
    long_ = d.get("10Y", curve[-1][1])
    overall = long_ - short

    vals = [v for _, v in curve]
    n = len(vals)
    i_min, i_max = vals.index(min(vals)), vals.index(max(vals))
    depth = max(vals) - min(vals)

    # 主型態：由整體斜率決定
    if overall < -FLAT_BAND:
        main = "倒掛"
        note = (f"10 年期低於短端 {abs(overall):.2f} 個百分點。"
                "歷史上倒掛領先衰退約 12-18 個月，但倒掛<b>當下</b>不是賣出訊號 —— "
                "真正的警訊是倒掛解除時的牛市陡峭化。")
    elif overall > STEEP_BAND:
        main = "陡峭正斜率"
        note = (f"10 年期高於短端 {overall:.2f} 個百分點。"
                "多見於降息循環中後段，或市場定價強勁復甦與通膨。")
    elif overall > FLAT_BAND:
        main = "正斜率（正常）"
        note = (f"10 年期高於短端 {overall:.2f} 個百分點，"
                "符合教科書的常態形狀：借越久、要求的補償越多。")
    else:
        main = "平坦"
        note = (f"10 年期與短端僅差 {overall:+.2f} 個百分點。"
                "常見於倒掛前後的過渡期，方向尚未確立。")

    # 次要特徵：最低／最高點是否落在中段
    extra = ""
    if 0 < i_min < n - 1 and depth > FLAT_BAND:
        rebound = vals[-1] - vals[i_min]
        if rebound > FLAT_BAND:
            main += " · U 型"
            extra = (f"　最低點落在 {labels[i_min]}，長端再回升 {rebound:.2f} 個百分點。"
                     "這不是教科書的標準三型，而是政策利率壓住短端、"
                     "市場預期降息壓低中段、長端又因期限溢酬與財政供給而偏高的結果 —— "
                     "緊縮週期末段相當常見。")
    elif 0 < i_max < n - 1 and depth > FLAT_BAND:
        main += " · 駝峰"
        extra = (f"　最高點落在 {labels[i_max]}，兩端較低。"
                 "通常代表市場認為升息還有最後一段，但之後會轉為降息。")
    return main, note + extra


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

    end_labels: list[tuple[float, float, str, int]] = []
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
            end_labels.append((last[0], last[1], name, slot))
    # 右側標籤依 y 排序後強制間隔，避免三條線末端接近時文字疊在一起
    end_labels.sort(key=lambda t: t[1])
    prev_y = -1e9
    for x, y, name, slot in end_labels:
        y = max(y, prev_y + 14)
        prev_y = y
        p.append(f'<text x="{x+10:.1f}" y="{y+4:.1f}" '
                 f'class="curve-lab" fill="var(--s{slot})">{name}</text>')

    # 政策利率區間：曲線的左端錨點，畫成水平帶
    band = None
    for up, lo_c in [("DFEDTARU", "DFEDTARL")]:
        if up in panel.columns and lo_c in panel.columns:
            u, l = panel[up].dropna(), panel[lo_c].dropna()
            if len(u) and len(l):
                band = (float(u.iloc[-1]), float(l.iloc[-1]))
    if band and lo <= band[0] <= hi:
        y_u, y_l = py(band[0]), py(band[1])
        p.append(f'<rect x="{m["l"]}" y="{min(y_u,y_l):.1f}" width="{pw}" '
                 f'height="{max(abs(y_l-y_u),2):.1f}" class="policy-band">'
                 f'<title>政策利率目標區間 {band[1]:.2f}–{band[0]:.2f}%</title></rect>')
        p.append(f'<text x="{m["l"]+6}" y="{min(y_u,y_l)-5:.1f}" '
                 f'class="policy-lab">政策利率 {band[1]:.2f}–{band[0]:.2f}%</text>')
    p.append("</svg>")

    shape, shape_note = classify_curve(curves[0][1])
    shape_html = (f'<div class="shape"><span class="shape-tag">{_esc(shape)}</span>'
                  f'<span class="shape-note">{shape_note}</span></div>')

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
    return (f'<div class="card">{shape_html}{"".join(p)}'
            f'<div class="legend">{legend}</div>'
            f'<p class="sub2" style="margin:8px 0 0">'
            f'橫軸為天期，採等距排列。曲線整體上移＝殖利率全面走升；'
            f'短端上升快於長端＝平坦化；短端下降快於長端＝陡峭化。</p>'
            f'<p class="sub2" style="margin:6px 0 0">'
            f'圖上每個天期都是<b>財政部實際標售的證券</b>（1M–1Y 為國庫券，'
            f'2Y–30Y 為附息債券），不是由鄰近天期內插而來。'
            f'CMT 的擬合僅用於輸入點之間未輸出的天期（如 4Y、8Y）。</p>'
            f'{table}</div>')


# --------------------------------------------------------- FOMC 點陣圖（前瞻）
# 點陣圖不是時間序列，而是「這次會議對未來各年度的預測」。FEDTARMD 的觀測日標在
# 被預測的年度（例如 2029-01-01），混進日頻面板會把時間軸拉到未來，其他序列全被
# 向前填補成平線 —— 曾經因此讓儀表板上每一項的「近三個月變化」都變成 0.00%。
# 因此獨立存放、獨立呈現：一張表，欄位是被預測的年度，而不是一張走勢圖。
# （FEDTARMDLR 長期中位數的觀測日是會議日，屬於正常的日頻序列，取最新值即可。）


def dotplot_table(proj: pd.DataFrame | None,
                  panel: pd.DataFrame | None = None) -> str:
    """把 FOMC 點陣圖畫成表格：欄＝被預測的年度，外加長期中位數。"""
    by_year: dict[int, float] = {}
    if proj is not None and len(proj) and "FEDTARMD" in proj.columns:
        s = proj["FEDTARMD"].dropna()
        this_year = (panel.index[-1].year if panel is not None and len(panel)
                     else pd.Timestamp.today().year)
        for d, v in s.items():
            # 同一年若有多筆（快取曾被向前填補），取最後一筆＝該年度的預測值
            if d.year >= this_year:
                by_year[d.year] = float(v)

    lr = None
    if panel is not None and "FEDTARMDLR" in panel.columns:
        t = panel["FEDTARMDLR"].dropna()
        if len(t):
            # 面板裡這一欄被向前填補到最後一個營業日，取 index[-1] 會誤稱
            # 「今天更新」。SEP 每季才改一次，因此取最後一次「數值改變」的日期，
            # 那才是發布這份預測的 FOMC 會議日。
            changed = t[t.ne(t.shift())]
            lr = (float(t.iloc[-1]), changed.index[-1])
    if not by_year and lr is None:
        return ""

    years = sorted(by_year)
    heads = "".join(f'<th class="num">{y} 年底</th>' for y in years)
    cells = "".join(f'<td class="num">{by_year[y]:.2f}</td>' for y in years)
    if lr is not None:
        heads += '<th class="num">長期（r*）</th>'
        cells += f'<td class="num">{lr[0]:.2f}</td>'
    asof = (f"　·　最後一次更新 {lr[1].date()}（FOMC 會議）"
            if lr is not None else "")
    return (f'<div class="card"><div class="mlabel">FOMC 點陣圖中位數（%）'
            f'<span class="sub2" style="font-weight:400"> · 前瞻預測，非市場價格'
            f'{_esc(asof)}</span></div>'
            f'<table class="htable"><thead><tr>{heads}</tr></thead>'
            f'<tbody><tr>{cells}</tr></tbody></table>'
            f'<p class="sub2" style="margin:8px 0 0">'
            f'來源 FRED · FEDTARMD／FEDTARMDLR（Summary of Economic Projections，'
            f'每年 3／6／9／12 月更新）。這是<b>FOMC 對未來的預測</b>，不是已發生的'
            f'事實，因此不放進日頻時間軸、也不計算「近三個月變化」——'
            f'把它併入日頻面板會讓其他指標被向前填補成平線。'
            f'與上方「市場定價（期貨）」相比即可看出市場信不信 Fed 的路徑。</p>'
            f'</div>')
