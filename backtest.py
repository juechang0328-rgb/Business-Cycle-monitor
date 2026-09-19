#!/usr/bin/env python3
"""擇時回測：用階段判定進出股市，真的會比買進持有好嗎？

這支程式回答唯一重要的問題 —— 這套模型能不能提升報酬率。

訊號一律延遲一個月才使用：月底才知道當月的判定，隔月才能交易。
不做這個延遲，回測會偷看未來，結果全部作廢。
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

from bcm import indicators as cfg
from bcm import scoring, stages
from bcm.sources import load_cache

# 投影片標示「股票↑」的階段：谷底、復甦、擴張
BULLISH_STAGES = (2, 3, 4)


def metrics(ret: pd.Series, periods_per_year: int = 12) -> dict:
    ret = ret.dropna()
    if ret.empty:
        return {}
    cum = (1 + ret).cumprod()
    years = len(ret) / periods_per_year
    cagr = cum.iloc[-1] ** (1 / years) - 1 if years > 0 else np.nan
    dd = (cum / cum.cummax() - 1).min()
    vol = ret.std() * np.sqrt(periods_per_year)
    return {"CAGR": cagr, "最大回檔": dd, "年化波動": vol,
            "報酬/波動": cagr / vol if vol else np.nan,
            "累積倍數": cum.iloc[-1]}


def run_backtest(panel: pd.DataFrame, profile: str, cost_bps: float = 10.0):
    cfg.PROFILE = profile
    a = cfg.active()
    G, _ = scoring.build_axis(panel, a["growth"])
    I, _ = scoring.build_axis(panel, a["inflation"])
    result = stages.run(G, I)

    px = panel["^GSPC"].resample("ME").last().dropna()
    ret = px.pct_change()

    stage = result["stage"].resample("ME").last()
    # 關鍵：訊號延遲一個月，避免偷看未來
    signal = stage.shift(1).reindex(ret.index)

    in_mkt = signal.isin(BULLISH_STAGES)
    turnover = in_mkt.ne(in_mkt.shift()).fillna(False)
    cost = turnover * (cost_bps / 10000)

    strat = ret.where(in_mkt, 0.0) - cost
    d = pd.DataFrame({"買進持有": ret, "階段擇時": strat}).dropna()
    return d, in_mkt.reindex(d.index).fillna(False), signal.reindex(d.index)


def main() -> int:
    p = argparse.ArgumentParser(description="階段擇時 vs 買進持有")
    p.add_argument("--cache", default="data/panel.csv")
    p.add_argument("--profile", default="econ", choices=["mvp", "full", "econ"])
    p.add_argument("--cost-bps", type=float, default=10.0,
                   help="每次進出的單邊成本（基點），預設 10bp")
    args = p.parse_args()

    panel = load_cache(args.cache)
    if panel is None or "^GSPC" not in panel.columns:
        print(f"讀不到 {args.cache} 或缺少 ^GSPC", file=sys.stderr)
        return 1

    d, in_mkt, signal = run_backtest(panel, args.profile, args.cost_bps)
    print(f"指標組合 {args.profile}　期間 {d.index[0].date()} → {d.index[-1].date()}"
          f"　共 {len(d)} 個月")
    print(f"持有股票的時間佔比 {in_mkt.mean()*100:.0f}%　"
          f"進出次數 {int(in_mkt.ne(in_mkt.shift()).sum())} 次\n")

    rows = {k: metrics(d[k]) for k in d.columns}
    keys = ["累積倍數", "CAGR", "最大回檔", "年化波動", "報酬/波動"]
    print(f"{'':<12}" + "".join(f"{k:>12}" for k in keys))
    print("─" * 74)
    for name, m in rows.items():
        cells = []
        for k in keys:
            v = m.get(k, np.nan)
            cells.append(f"{v:>11.2f}x" if k == "累積倍數"
                         else (f"{v*100:>11.1f}%" if k != "報酬/波動"
                               else f"{v:>12.2f}"))
        print(f"{name:<12}" + "".join(cells))

    bh, st = rows["買進持有"], rows["階段擇時"]
    diff = st["CAGR"] - bh["CAGR"]
    print(f"\n年化報酬差異：{diff*100:+.2f} 個百分點")
    print("→ 為正才代表擇時有價值；為負代表不如直接買進持有。")

    print("\n【這個回測的限制】")
    print("  樣本期間股市大多在上漲，任何會空手的策略都天生吃虧，")
    print("  因此本測試對擇時策略並不公平。不能只憑這一項下結論 ——")
    print("  要連同 validate.py 的中性檢驗（相關係數、能否分辨衰退）一起看。")
    print(f"  另外樣本僅 {len(d)} 個月，獨立的三個月觀測約 {len(d)//3} 個。")

    # 只有在空手時才算避開跌勢，逐月比對
    out = ~in_mkt
    if out.sum():
        avoided = d.loc[out, "買進持有"]
        print(f"\n空手期間（{out.sum()} 個月）大盤平均月報酬 "
              f"{avoided.mean()*100:+.2f}%")
        print("→ 若為正，代表這些時候空手是錯的，擇時反而錯過上漲。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
