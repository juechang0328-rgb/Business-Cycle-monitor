#!/usr/bin/env python3
"""景氣循環監測 —— 每日更新。

用法：
    python run.py                      # 終端機輸出當前階段
    python run.py --html               # 另外產生 dashboard.html 儀表板
    python run.py --html out.html      # 指定輸出檔名
    python run.py --years 5            # 儀表板顯示近 5 年（預設 3 年）
    python run.py --csv out.csv        # 匯出完整時間序列
    python run.py --demo --html        # 用合成資料預覽版面（不連網）

註：z-score 需要較長的歷史基準，因此實際抓取起點early於顯示區間。
"""
from __future__ import annotations

import argparse
import sys
import unicodedata

import pandas as pd

from bcm import dashboard
from bcm import indicators as cfg
from bcm import scoring, stages
from bcm.sources import build_panel


def _width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _width(text))


def compute(panel: pd.DataFrame, confirm: int = 10):
    G, g_parts = scoring.build_axis(panel, cfg.GROWTH_SPECS)
    I, i_parts = scoring.build_axis(panel, cfg.INFLATION_SPECS)
    return stages.run(G, I, confirm=confirm), g_parts, i_parts


def render_text(result, g_parts, i_parts, panel) -> str:
    d = result.dropna(subset=["G", "I"])
    last, date = d.iloc[-1], d.index[-1].date()
    stage = int(last["stage"])

    lines = ["=" * 62,
             f"  景氣循環定位   資料日期 {date}",
             "=" * 62,
             f"  {stages.describe(stage)}",
             "",
             f"  成長分數 G = {last['G']:+.2f}   3個月動能 dG = {last['dG']:+.2f}",
             f"  通膨分數 I = {last['I']:+.2f}   3個月動能 dI = {last['dI']:+.2f}"]
    raw = int(last["raw_stage"])
    if raw != stage and raw != 0:
        lines.append(f"  ⚠ 原始判定已轉為 階段{raw} {stages.STAGE_NAMES[raw]}，"
                     f"尚未滿足連續確認天數，暫不換檔")

    def block(title, parts, specs):
        out = ["", f"  【{title}】成分 z-score（3個月動能）"]
        w = {s["name"]: s["weight"] for s in specs}
        row = parts.iloc[-1]
        for name in parts.columns:
            v, label = row[name], _pad(name, 22)
            if pd.isna(v):
                out.append(f"    {label}   n/a          (權重 {w[name]:.0%})")
                continue
            n = int(min(abs(v), 3.0) * 5)
            bar = (" " * (15 - n) + "█" * n + " " * 15) if v < 0 else (" " * 15 + _pad("█" * n, 15))
            out.append(f"    {label} {v:+5.2f}  |{bar}|  (權重 {w[name]:.0%})")
        return out

    lines += block("成長軸 G", g_parts, cfg.GROWTH_SPECS)
    lines += block("通膨軸 I", i_parts, cfg.INFLATION_SPECS)

    lines += ["", "  【市場儀表板】最新值 / 3個月變化"]
    for label, code, mode in cfg.DASHBOARD:
        p = _pad(label, 18)
        if code not in panel.columns:
            lines.append(f"    {p}   n/a")
            continue
        s = panel[code].dropna()
        if len(s) < 64:
            lines.append(f"    {p} {s.iloc[-1]:>10,.2f}   （歷史不足）")
            continue
        chg = (s.iloc[-1] / s.iloc[-64] - 1) * 100 if mode == "pct" else s.iloc[-1] - s.iloc[-64]
        lines.append(f"    {p} {s.iloc[-1]:>10,.2f}   {chg:+7.2f}"
                     f"{'%' if mode == 'pct' else 'pp'}")
    return "\n".join(lines + ["", "=" * 62])


def synthetic_panel() -> pd.DataFrame:
    """合成面板：僅供離線預覽版面，數值無意義。"""
    import numpy as np
    n = 2400
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    rng = np.random.default_rng(11)
    cyc = np.sin(2 * np.pi * np.arange(n) / 1050)
    out = {}
    for tk in cfg.YAHOO_TICKERS:
        beta = 0.30 if tk in ("HG=F", "CL=F", "XLI", "SOXX", "IWM", "HYG", "DBC") else 0.06
        out[tk] = 100 * np.exp(np.cumsum(rng.normal(0, 0.008, n)) + cyc * beta)
    for code in cfg.FRED_CODES:
        out[code] = 2.2 + cyc * 1.1 + np.cumsum(rng.normal(0, 0.008, n))
    return pd.DataFrame(out, index=idx)


def main() -> int:
    p = argparse.ArgumentParser(description="景氣循環六階段監測")
    p.add_argument("--start", default="2015-01-01",
                   help="抓取起始日（需早於顯示區間，供 z-score 建立基準）")
    p.add_argument("--years", type=int, default=3, help="儀表板顯示最近幾年（預設 3）")
    p.add_argument("--confirm", type=int, default=10, help="換檔需連續確認的交易日數")
    p.add_argument("--html", nargs="?", const="dashboard.html", default=None,
                   help="產生 HTML 儀表板")
    p.add_argument("--csv", help="匯出完整時間序列")
    p.add_argument("--demo", action="store_true", help="用合成資料預覽版面（不連網）")
    args = p.parse_args()

    if args.demo:
        panel = synthetic_panel()
    else:
        try:
            panel = build_panel(cfg.YAHOO_TICKERS, cfg.FRED_CODES, start=args.start)
        except Exception as e:
            print(f"資料抓取失敗：{e}", file=sys.stderr)
            print("請確認可連到 finance.yahoo.com 與 fred.stlouisfed.org。"
                  "要先看版面可加 --demo。", file=sys.stderr)
            return 1

    result, g_parts, i_parts = compute(panel, confirm=args.confirm)
    print(render_text(result, g_parts, i_parts, panel))

    if args.html:
        cutoff = result.index[-1] - pd.DateOffset(years=args.years)
        view = result.loc[result.index >= cutoff]
        html = dashboard.render_html(view, g_parts.loc[g_parts.index >= cutoff],
                                     i_parts.loc[i_parts.index >= cutoff],
                                     panel, cfg, demo=args.demo)
        with open(args.html, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"\n  儀表板已輸出：{args.html}")

    if args.csv:
        pd.concat([result, g_parts.add_prefix("G:"), i_parts.add_prefix("I:")],
                  axis=1).to_csv(args.csv)
        print(f"  時間序列已輸出：{args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
