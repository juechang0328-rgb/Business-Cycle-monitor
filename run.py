#!/usr/bin/env python3
"""景氣循環監測 —— 每日更新版。

用法：
    python run.py                 # 抓最新資料並輸出當前階段
    python run.py --start 2015-01-01
    python run.py --history 12    # 另外列出最近 12 個月的階段軌跡
    python run.py --csv out.csv   # 輸出完整時間序列
"""
from __future__ import annotations

import argparse
import sys
import unicodedata

import pandas as pd

from bcm import indicators as cfg
from bcm import scoring, stages
from bcm.sources import build_panel


def _width(text: str) -> int:
    """顯示寬度：CJK 全形字佔 2 欄。"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def _pad(text: str, width: int) -> str:
    """依顯示寬度補空白（str.ljust 只算字元數，中文會跑版）。"""
    return text + " " * max(0, width - _width(text))


def compute(panel: pd.DataFrame, confirm: int = 10) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    G, g_parts = scoring.build_axis(panel, cfg.GROWTH_SPECS)
    I, i_parts = scoring.build_axis(panel, cfg.INFLATION_SPECS)
    result = stages.run(G, I, confirm=confirm)
    return result, g_parts, i_parts


def render(result: pd.DataFrame, g_parts: pd.DataFrame, i_parts: pd.DataFrame,
           panel: pd.DataFrame) -> str:
    last = result.dropna(subset=["G", "I"]).iloc[-1]
    date = result.dropna(subset=["G", "I"]).index[-1].date()
    stage = int(last["stage"])

    lines = [
        "=" * 62,
        f"  景氣循環定位   資料日期 {date}",
        "=" * 62,
        f"  {stages.describe(stage)}",
        "",
        f"  成長分數 G = {last['G']:+.2f}   3個月動能 dG = {last['dG']:+.2f}",
        f"  通膨分數 I = {last['I']:+.2f}   3個月動能 dI = {last['dI']:+.2f}",
    ]
    raw = int(last["raw_stage"])
    if raw != stage:
        lines.append(f"  ⚠ 原始判定為 階段{raw} {stages.STAGE_NAMES[raw]}，"
                     f"尚未滿足連續確認天數，暫不換檔")

    def block(title: str, parts: pd.DataFrame, specs: list[dict]) -> list[str]:
        out = ["", f"  【{title}】成分 z-score（3個月動能）"]
        w = {s["name"]: s["weight"] for s in specs}
        row = parts.iloc[-1]
        for name in parts.columns:
            v = row[name]
            label = _pad(name, 22)
            if pd.isna(v):
                out.append(f"    {label}   n/a          (權重 {w[name]:.0%})")
                continue
            bar_len = int(min(abs(v), 3.0) * 5)
            if v < 0:
                bar = _pad("", 15 - bar_len) + "█" * bar_len + " " * 15
            else:
                bar = " " * 15 + _pad("█" * bar_len, 15)
            out.append(f"    {label} {v:+5.2f}  |{bar}|  (權重 {w[name]:.0%})")
        return out

    lines += block("成長軸 G", g_parts, cfg.GROWTH_SPECS)
    lines += block("通膨軸 I", i_parts, cfg.INFLATION_SPECS)

    lines += ["", "  【市場儀表板】最新值 / 3個月變化"]
    for label, code, mode in cfg.DASHBOARD:
        padded = _pad(label, 18)
        if code not in panel.columns:
            lines.append(f"    {padded}   n/a")
            continue
        s = panel[code].dropna()
        if len(s) < 64:
            lines.append(f"    {padded} {s.iloc[-1]:>10,.2f}   （歷史不足）")
            continue
        chg = (s.iloc[-1] / s.iloc[-64] - 1) * 100 if mode == "pct" else s.iloc[-1] - s.iloc[-64]
        unit = "%" if mode == "pct" else "pp"
        lines.append(f"    {padded} {s.iloc[-1]:>10,.2f}   {chg:+7.2f}{unit}")

    lines += ["", "=" * 62]
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description="景氣循環六階段每日監測")
    p.add_argument("--start", default="2005-01-01", help="資料起始日")
    p.add_argument("--confirm", type=int, default=10, help="換檔需連續確認的交易日數")
    p.add_argument("--history", type=int, default=0, help="額外列出最近 N 個月的階段軌跡")
    p.add_argument("--csv", help="把完整時間序列寫出到 CSV")
    args = p.parse_args()

    try:
        panel = build_panel(cfg.YAHOO_TICKERS, cfg.FRED_CODES, start=args.start)
    except Exception as e:
        print(f"資料抓取失敗：{e}", file=sys.stderr)
        print("請確認網路可連到 finance.yahoo.com 與 fred.stlouisfed.org。", file=sys.stderr)
        return 1

    result, g_parts, i_parts = compute(panel, confirm=args.confirm)
    print(render(result, g_parts, i_parts, panel))

    if args.history:
        monthly = result.dropna(subset=["G", "I"]).resample("ME").last()
        print("\n  最近階段軌跡")
        for ts, row in monthly.tail(args.history).iterrows():
            st = int(row["stage"])
            print(f"    {ts.date()}  G={row['G']:+.2f}  I={row['I']:+.2f}  "
                  f"{stages.describe(st)}")

    if args.csv:
        pd.concat([result, g_parts.add_prefix("G:"), i_parts.add_prefix("I:")],
                  axis=1).to_csv(args.csv)
        print(f"\n  已輸出：{args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
