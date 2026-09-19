#!/usr/bin/env python3
"""模型檢驗：這套階段判定到底有沒有訊息量？

投影片對每個階段宣稱了債／股／原物料的方向。這支程式就檢驗那個宣稱：
在模型判定為階段 N 的日子裡，資產後續是不是真的照箭頭走。

用法：
    python validate.py --cache data/panel.csv

判讀：方向命中率要顯著高於 50% 才代表有訊息量。50% 上下＝與丟銅板無異。
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

from bcm import indicators as cfg
from bcm import scoring, stages
from bcm.sources import load_cache

# 投影片宣稱的方向：(債券, 股票, 原物料)，+1 為上漲
CLAIMED = {1: (+1, -1, -1), 2: (+1, +1, -1), 3: (+1, +1, +1),
           4: (-1, +1, +1), 5: (-1, -1, +1), 6: (-1, -1, -1)}


def forward_returns(panel: pd.DataFrame, h: int, ahead: bool = True):
    """三類資產在 h 個交易日的報酬。ahead=True 取未來（預測檢驗）。"""
    stock = panel["^GSPC"].pct_change(h)
    bond = -panel["DGS10"].diff(h)          # 殖利率下降＝債券價格上漲
    comm = (panel["CL=F"].pct_change(h) + panel["HG=F"].pct_change(h)) / 2
    if ahead:
        stock, bond, comm = stock.shift(-h), bond.shift(-h), comm.shift(-h)
    return stock, bond, comm


def hit_rate(result: pd.DataFrame, panel: pd.DataFrame, h: int,
             ahead: bool = True, min_n: int = 20):
    stock, bond, comm = forward_returns(panel, h, ahead)
    d = pd.DataFrame({"stage": result["stage"], "bond": bond,
                      "stock": stock, "comm": comm}).dropna()
    d = d[d.stage > 0]
    hits = total = 0
    rows = []
    for s in range(1, 7):
        g = d[d.stage == s]
        if len(g) < min_n:
            continue
        h_s = 0
        cells = []
        for col, exp in zip(("bond", "stock", "comm"), CLAIMED[s]):
            m = g[col].mean()
            ok = np.sign(m) == exp
            h_s += ok
            cells.append(f"{m*100:+6.2f}{'bp' if col=='bond' else '%':<2}{'✓' if ok else '✗'}")
        hits += h_s
        total += 3
        rows.append((s, len(g), cells, h_s))
    return hits, total, rows


def main() -> int:
    p = argparse.ArgumentParser(description="檢驗階段判定是否具備訊息量")
    p.add_argument("--cache", default="data/panel.csv")
    args = p.parse_args()

    panel = load_cache(args.cache)
    if panel is None:
        print(f"讀不到 {args.cache}", file=sys.stderr)
        return 1

    G, _ = scoring.build_axis(panel, cfg.GROWTH_SPECS)
    I, _ = scoring.build_axis(panel, cfg.INFLATION_SPECS)
    result = stages.run(G, I).dropna(subset=["G", "I"])

    print(f"資料期間 {result.index[0].date()} → {result.index[-1].date()}\n")
    print("【預測檢驗】判定為某階段後，資產後續是否照箭頭走？")
    print(f"{'視野':<10}{'方向命中':>12}{'G與股市相關':>16}")
    print("─" * 40)
    for h, lab in [(21, "1個月"), (63, "3個月"), (126, "6個月"), (252, "12個月")]:
        hits, total, _ = hit_rate(result, panel, h)
        fwd = panel["^GSPC"].pct_change(h).shift(-h)
        c = pd.concat([G, fwd], axis=1).dropna()
        corr = c.iloc[:, 0].corr(c.iloc[:, 1])
        print(f"{lab:<10}{hits}/{total} = {hits/total*100:3.0f}%{corr:>15.3f}")

    hits, total, rows = hit_rate(result, panel, 63, ahead=False)
    print(f"\n【同期檢驗】判定當下，該期間資產走勢是否符合箭頭？"
          f"  {hits}/{total} = {hits/total*100:.0f}%")
    print(f"\n{'階段':<12}{'N':>6} │ {'債券':>12}{'股票':>12}{'原物料':>12} │ 命中")
    print("─" * 62)
    for s, n, cells, h_s in rows:
        print(f"階段{s} {stages.STAGE_NAMES[s]:<6}{n:>6} │ "
              f"{cells[0]:>12}{cells[1]:>12}{cells[2]:>12} │ {h_s}/3")

    print("\n判讀：命中率需顯著高於 50% 才代表有訊息量。")
    print("      50% 上下＝與丟銅板無異，此時任何『當前階段』的宣稱都不該被採信。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
