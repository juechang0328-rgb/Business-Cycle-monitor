"""純邏輯測試（不碰網路）：以合成資料驗證評分與階段判定。"""
import numpy as np
import pandas as pd
import pytest

from bcm import scoring, stages


# ------------------------------------------------------------------ 階段判定
def test_classify_covers_all_six_stages():
    cases = {
        # (G, dG, I) -> 期望階段
        (-1.0, -0.5, -1.0): 1,   # 成長低且續降、通膨已落 → 衰退
        (-1.0, +0.3, -1.0): 2,   # 成長低但止跌回升      → 谷底
        (+0.5, +0.4, -0.5): 3,   # 成長轉正、通膨仍低     → 復甦
        (+1.0, +0.4, +1.0): 4,   # 成長強、通膨已起       → 擴張
        (+1.0, -0.4, +1.0): 5,   # 成長仍高但動能轉負     → 高峰
        (-0.5, -0.4, +1.0): 6,   # 成長轉負、通膨仍高     → 趨緩
    }
    for (g, dg, i), expected in cases.items():
        assert stages.classify_point(g, dg, i) == expected, (g, dg, i)


def test_classify_handles_missing_data():
    assert stages.classify_point(np.nan, 0.1, 0.1) == 0
    assert stages.classify_point(0.1, np.nan, 0.1) == 0
    assert stages.classify_point(0.1, 0.1, np.nan) == 0


def test_stage_four_five_boundary_is_momentum_not_level():
    """階段4與5的分界在於動能正負，而非成長水準高低。"""
    assert stages.classify_point(2.0, +0.1, 1.0) == 4
    assert stages.classify_point(2.0, -0.1, 1.0) == 5   # 水準更高也一樣是高峰


def test_stage_one_six_boundary_is_inflation():
    """階段6與1的分界在於通膨是否已落（＝債券箭頭何時翻正）。"""
    assert stages.classify_point(-0.5, -0.5, +0.5) == 6
    assert stages.classify_point(-0.5, -0.5, -0.5) == 1


# ------------------------------------------------------------------ 遲滯
def test_hysteresis_ignores_short_lived_flips():
    raw = pd.Series([4] * 30 + [5] * 3 + [4] * 30)
    out = stages.apply_hysteresis(raw, confirm=10)
    assert set(out.unique()) == {4}, "3天的雜訊不應觸發換檔"


def test_hysteresis_switches_after_confirm_window():
    raw = pd.Series([4] * 30 + [5] * 30)
    out = stages.apply_hysteresis(raw, confirm=10)
    assert out.iloc[29] == 4
    assert out.iloc[38] == 4, "第10天前仍不換檔"
    assert out.iloc[39] == 5, "滿10天正式換檔"


def test_hysteresis_resets_streak_on_interruption():
    # 連 9 天 5、被 4 打斷、再連 9 天 5 → 都不該換檔
    raw = pd.Series([4] * 20 + [5] * 9 + [4] + [5] * 9)
    out = stages.apply_hysteresis(raw, confirm=10)
    assert set(out.unique()) == {4}


# ------------------------------------------------------------------ 評分
def test_momentum_modes():
    s = pd.Series(np.arange(1.0, 101.0))
    assert scoring.momentum(s, lookback=10, mode="diff").iloc[-1] == pytest.approx(10.0)
    assert scoring.momentum(s, lookback=10, mode="pct").iloc[-1] == pytest.approx(10 / 90)
    with pytest.raises(ValueError):
        scoring.momentum(s, mode="nonsense")


def test_zscore_is_standardised():
    rng = np.random.default_rng(0)
    s = pd.Series(rng.normal(5.0, 2.0, 2000))
    z = scoring.zscore(s)
    tail = z.iloc[800:]
    assert abs(tail.mean()) < 0.2
    assert 0.8 < tail.std() < 1.2


def test_composite_renormalises_when_a_component_is_missing():
    idx = pd.RangeIndex(3)
    a = pd.Series([1.0, 1.0, 1.0], index=idx)
    b = pd.Series([np.nan, -1.0, 3.0], index=idx)
    out = scoring.composite({"a": a, "b": b}, {"a": 0.5, "b": 0.5})
    assert out.iloc[0] == pytest.approx(1.0), "b 缺值時不應把分數往 0 拉"
    assert out.iloc[1] == pytest.approx(0.0)
    assert out.iloc[2] == pytest.approx(2.0)


def test_composite_rejects_zero_weights():
    s = pd.Series([1.0, 2.0])
    with pytest.raises(ValueError):
        scoring.composite({"a": s}, {"a": 0.0})


def test_clip_limits_extremes():
    s = pd.Series([-99.0, 0.0, 99.0])
    assert list(scoring.clip_z(s, limit=3.0)) == [-3.0, 0.0, 3.0]


def test_invert_flips_sign_in_build_axis():
    idx = pd.bdate_range("2015-01-01", periods=600)
    rng = np.random.default_rng(1)
    panel = pd.DataFrame({"X": 100 + np.cumsum(rng.normal(0, 1, 600))}, index=idx)
    up, _ = scoring.build_axis(panel, [{"name": "x", "series": "X", "weight": 1.0}])
    dn, _ = scoring.build_axis(panel, [{"name": "x", "series": "X", "weight": 1.0,
                                        "invert": True}])
    assert up.dropna().iloc[-1] == pytest.approx(-dn.dropna().iloc[-1])


# ------------------------------------------------- 端到端：合成一個完整循環
def _synthetic_cycle(n_days=2600, period=1300):
    """造一個成長領先通膨 1/4 個週期的合成循環，檢查六階段是否依序走完。"""
    idx = pd.bdate_range("2012-01-01", periods=n_days)
    t = np.arange(n_days)
    G = pd.Series(np.sin(2 * np.pi * t / period), index=idx)
    I = pd.Series(np.sin(2 * np.pi * (t - period / 4) / period), index=idx)
    return G, I


def test_cycle_advances_and_never_reverses():
    """合成循環餵進去，階段序列必須「只前進、不倒退」。

    不要求六階段全數出現：月頻取樣加上平滑會改變有效相位，
    某些階段可能不足一期就被跨過。真正的正確性條件是方向 ——
    倒退代表判定邏輯壞了。
    """
    G, I = _synthetic_cycle()
    out = stages.run(G, I)
    seq = out["stage"].loc[out["stage"] > 0]
    order = [s for s, nxt in zip(seq, list(seq[1:]) + [None]) if s != nxt]

    assert len(set(order)) >= 4, f"至少應走過四個階段：{order}"
    for a, b in zip(order, order[1:]):
        step = (b - a) % 6
        assert step in (1, 2, 3), f"階段 {a} → {b} 為倒退"


def test_cycle_is_periodic():
    """乾淨的合成循環應產出重複的階段序列，而非雜亂跳動。"""
    G, I = _synthetic_cycle()
    seq = stages.run(G, I)["stage"]
    seq = seq[seq > 0]
    order = [s for s, nxt in zip(seq, list(seq[1:]) + [None]) if s != nxt]
    assert len(order) >= 6, "樣本內至少應出現數次換檔"
    period = order[: len(set(order))]
    # 後續應重複同一個順序
    repeats = [order[i:i + len(period)] for i in range(0, len(order) - len(period) + 1,
                                                       len(period))]
    assert repeats[0] == repeats[1], f"階段順序未重複：{order}"


def test_smoothing_makes_transitions_cycle_like():
    """平滑必須讓序列更像循環 —— 這是該參數存在的唯一理由。"""
    G, I = _synthetic_cycle()

    def forward_ratio(**kw):
        seq = stages.run(G, I, **kw)["stage"]
        seq = seq[seq > 0]
        order = [s for s, n in zip(seq, list(seq[1:]) + [None]) if s != n]
        steps = [(b - a) % 6 for a, b in zip(order, order[1:])]
        if not steps:
            return 0.0
        return sum(s in (1, 2) for s in steps) / len(steps)

    assert forward_ratio(smooth=12) >= forward_ratio(smooth=0)


# ------------------------------------------------------------------ 儀表板
def test_dashboard_renders_valid_page():
    """以合成面板確認 HTML 產得出來、關鍵區塊都在。"""
    import run
    from bcm import dashboard, indicators as cfg

    panel = run.synthetic_panel()
    result, gp, ip = run.compute(panel, confirm=2)
    cutoff = result.index[-1] - pd.DateOffset(years=3)
    view = result.loc[result.index >= cutoff]
    html = dashboard.render_html(view, gp.loc[gp.index >= cutoff],
                                 ip.loc[ip.index >= cutoff], panel, cfg, demo=True)

    assert html.startswith("<!DOCTYPE html>") and html.rstrip().endswith("</html>")
    # 時間軸 + 時鐘 + 走勢圖 + 兩張實體經濟對照
    assert html.count("<svg") == 3 + len(cfg.REALITY_CHECK)
    assert "景氣循環監測" in html
    assert "階段時間軸" in html and "實體經濟對照" in html
    assert "這兩個分數是什麼" in html, "頁面需自行解釋 G 與 I"
    assert "示範資料" in html or "示範頁面" in html         # demo 標記必須出現
    stage = int(view.dropna(subset=["G", "I"]).iloc[-1]["stage"])
    assert f"階段 {stage}" in html
    for name in [s["name"] for s in cfg.GROWTH_SPECS]:
        assert name in html


def test_dashboard_marks_demo_only_when_asked():
    import run
    from bcm import dashboard, indicators as cfg

    panel = run.synthetic_panel()
    result, gp, ip = run.compute(panel, confirm=2)
    html = dashboard.render_html(result, gp, ip, panel, cfg, demo=False)
    assert "示範頁面" not in html


def test_all_six_stages_have_colour_and_description():
    from bcm import dashboard
    for s in range(1, 7):
        assert s in dashboard.STAGE_COLORS
        assert s in dashboard.STAGE_COLORS_DARK
        assert dashboard.STAGE_DESC[s].strip()


def test_stage_colours_are_referenced_as_theme_variables():
    """SVG 內必須用 CSS 變數，深色模式才會跟著切換。"""
    from bcm import dashboard
    assert dashboard.sc(3) == "var(--st3)"
    assert dashboard.sc(0) == "var(--muted)"
    assert dashboard.sc(None) == "var(--muted)"


def test_short_window_warns_that_it_is_under_one_cycle():
    """不足一個完整循環（4-5年）時必須明講，否則會誤導成『沒有循環』。"""
    import run
    from bcm import dashboard, indicators as cfg

    panel = run.synthetic_panel()
    result, gp, ip = run.compute(panel, confirm=2)
    short = result.loc[result.index >= result.index[-1] - pd.DateOffset(years=2)]
    html = dashboard.render_html(short, gp, ip, panel, cfg, full_result=short)
    assert "短於一個完整景氣循環" in html

    long_html = dashboard.render_html(short, gp, ip, panel, cfg, full_result=result)
    assert "短於一個完整景氣循環" not in long_html


# ------------------------------------------------------------------ 資料快取
def test_merge_panel_new_data_wins_on_overlap():
    from bcm.sources import merge_panel
    idx = pd.date_range("2026-01-01", periods=3)
    old = pd.DataFrame({"A": [1.0, 2.0, 3.0]}, index=idx)
    new = pd.DataFrame({"A": [9.0]}, index=idx[-1:])
    out = merge_panel(old, new)
    assert out.loc[idx[0], "A"] == 1.0
    assert out.loc[idx[-1], "A"] == 9.0, "重疊處應以新資料為準"


def test_merge_panel_extends_history_and_columns():
    from bcm.sources import merge_panel
    old = pd.DataFrame({"A": [1.0, 2.0]}, index=pd.date_range("2026-01-01", periods=2))
    new = pd.DataFrame({"A": [3.0], "B": [7.0]}, index=pd.date_range("2026-01-03", periods=1))
    out = merge_panel(old, new)
    assert list(out.columns) == ["A", "B"]
    assert len(out) == 3, "歷史應延長而非被覆蓋"
    assert out["A"].tolist() == [1.0, 2.0, 3.0]


def test_merge_panel_handles_empty_cache():
    from bcm.sources import merge_panel
    new = pd.DataFrame({"A": [1.0]}, index=pd.date_range("2026-01-01", periods=1))
    assert merge_panel(None, new).equals(new)
    assert merge_panel(pd.DataFrame(), new).equals(new)


def test_cache_roundtrip(tmp_path):
    from bcm.sources import load_cache, save_cache
    path = str(tmp_path / "sub" / "panel.csv")
    df = pd.DataFrame({"A": [1.0, 2.0]}, index=pd.date_range("2026-01-01", periods=2))
    save_cache(df, path)                       # 應自動建立目錄
    back = load_cache(path)
    assert back is not None
    assert back["A"].tolist() == [1.0, 2.0]


def test_load_cache_returns_none_when_missing_or_corrupt(tmp_path):
    from bcm.sources import load_cache
    assert load_cache(str(tmp_path / "nope.csv")) is None
    bad = tmp_path / "bad.csv"
    bad.write_text("這不是 CSV\x00\x00")
    assert load_cache(str(bad)) is None


# ------------------------------------------- 不同起始日的序列（迴歸測試）
def test_classify_aligns_series_with_different_lengths():
    """成長軸與通膨軸的起始日不同時仍須正常運作。

    迴歸測試：先前 classify 直接 zip 三個序列，zip 會截斷到最短者，
    但索引用完整長度，導致長度不符而拋 ValueError。
    當面板同時含市場資料（1998 起）與經濟資料（1967 起）時必然踩到。
    """
    long_idx = pd.date_range("2000-01-31", periods=200, freq="ME")
    short_idx = long_idx[120:]                     # 通膨軸起始較晚
    G = pd.Series(np.linspace(-1, 1, 200), index=long_idx)
    dG = G.diff(3)
    I = pd.Series(np.linspace(-1, 1, 80), index=short_idx)

    out = stages.classify(G, dG, I)
    assert len(out) == len(long_idx), "應對齊到索引聯集，而非截斷"
    assert (out.loc[long_idx[:120]] == 0).all(), "通膨軸尚無資料處應判為未定"
    assert (out.loc[short_idx] > 0).any(), "兩軸都有資料處應產出有效判定"


def test_run_handles_axes_with_different_start_dates():
    idx = pd.bdate_range("2000-01-03", periods=3000)
    rng = np.random.default_rng(3)
    G = pd.Series(np.cumsum(rng.normal(0, 0.05, 3000)), index=idx)
    I = pd.Series(np.cumsum(rng.normal(0, 0.05, 3000)), index=idx)
    I.iloc[:1500] = np.nan                          # 通膨軸前半段沒有資料
    out = stages.run(G, I)                          # 不可拋錯
    assert len(out) == len(idx)
    assert (out["stage"].iloc[2000:] > 0).any()


# ------------------------------------------------- 週末日期的序列（迴歸測試）
def test_weekend_dated_series_survives_business_day_alignment():
    """日期標在週末的序列不可在對齊營業日時被丟光。

    迴歸測試：初領失業金 IC4WSA 的觀測日是星期六，先前直接
    reindex 到 bdate_range，導致整欄靜默變成 NaN —— 不會報錯，
    只會讓指標默默失效。
    """
    from bcm.sources import to_business_days

    saturdays = pd.date_range("2026-01-03", periods=8, freq="W-SAT")
    weekly = pd.DataFrame({"IC4WSA": range(100, 108)}, index=saturdays)
    weekdays = pd.bdate_range("2026-01-05", periods=30)
    daily = pd.DataFrame({"SPX": np.arange(30.0)}, index=weekdays)

    out = to_business_days(pd.concat([weekly, daily], axis=1).sort_index())
    assert out["IC4WSA"].notna().any(), "週末日期的序列不該整欄消失"
    # 星期六的值應向前填補到下一個星期一
    assert out.loc["2026-01-05", "IC4WSA"] == 100
    assert out["SPX"].notna().any()


def test_all_nan_column_does_not_crash_rendering():
    """整欄無資料的指標不可讓輸出崩潰（例如序列剛加入、尚未抓到值）。"""
    import run
    from bcm import dashboard, indicators as cfg

    panel = run.synthetic_panel()
    panel[cfg.DASHBOARD[0][1]] = np.nan          # 把儀表板第一項清空
    result, gp, ip = run.compute(panel, confirm=2)
    text = run.render_text(result, gp, ip, panel)
    assert "無資料" in text
    html = dashboard.render_html(result, gp, ip, panel, cfg)
    assert "無資料" in html


# --------------------------------------------------------- 前瞻性序列汙染時間軸
# 真實事故：FEDTARMD（FOMC 點陣圖）的觀測日標在被預測的年度（2029-01-01），
# 面板的時間軸因此被拉長 596 個營業日，其他序列全被向前填補成一條平線。
# 結果是儀表板上每一項的「近三個月變化」都顯示 0.00% —— 不報錯、不缺值，
# 只是全部變成同一個數字。以下三個測試各自把一個環節釘住。

def test_projection_column_does_not_extend_timeline():
    from bcm.sources import split_projections, to_business_days

    real = pd.bdate_range("2026-01-01", periods=60)
    panel = pd.DataFrame({"SPX": np.arange(60.0)}, index=real)
    panel.loc[pd.Timestamp("2029-01-01"), "FEDTARMD"] = 3.6
    panel = panel.sort_index()

    rest, proj = split_projections(panel)
    assert list(proj.columns) == ["FEDTARMD"]
    assert "FEDTARMD" not in rest.columns

    end = rest.dropna(how="all").index.max()
    out = to_business_days(rest, end=end)
    assert out.index[-1] == real[-1], "時間軸不該被未來日期拉長"
    # 前瞻序列若留在面板裡，SPX 會被向前填補成平線
    assert out["SPX"].iloc[-1] == 59.0


def test_three_month_change_survives_projection_series():
    """端到端：面板含未來日期欄位時，三個月變化不可塌成 0。"""
    from bcm.sources import merge_panel
    from bcm.macro_dash import metric_snapshot

    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=200)
    raw = pd.DataFrame({"SPX": np.linspace(100.0, 200.0, len(idx))}, index=idx)
    raw.loc[pd.Timestamp.today().normalize() + pd.DateOffset(years=3),
            "FEDTARMD"] = 3.6
    panel = merge_panel(None, raw.sort_index())

    assert panel.index[-1] <= pd.Timestamp.today().normalize()
    assert "FEDTARMD" not in panel.columns
    snap = metric_snapshot(panel, "SPX", "pct")
    assert snap["ok"] and abs(snap["change"]) > 1.0, "三個月變化不該是 0"


def test_cache_roundtrip_quarantines_projections(tmp_path):
    """舊快取裡已經寫進未來日期 —— 讀取時必須自己清乾淨。"""
    from bcm.sources import (load_cache, projection_path, projections_of,
                             save_cache)

    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=30)
    dirty = pd.DataFrame({"SPX": np.arange(30.0)}, index=idx)
    future = pd.Timestamp.today().normalize() + pd.DateOffset(years=3)
    dirty.loc[future, "FEDTARMD"] = 3.6
    dirty.loc[future, "SPX"] = 29.0            # 被向前填補的殘骸
    path = tmp_path / "panel.csv"
    dirty.sort_index().to_csv(path)            # 刻意用原始寫法存下汙染版

    got = load_cache(str(path))
    assert got.index[-1] <= pd.Timestamp.today().normalize()
    assert "FEDTARMD" not in got.columns
    assert len(got) == 30
    proj = projections_of(got)
    assert list(proj.columns) == ["FEDTARMD"] and proj.iloc[-1, 0] == 3.6

    # 再存一次：前瞻序列要落到獨立檔案，主檔案不得含未來日期
    save_cache(got, str(path), projections=proj)
    reread = pd.read_csv(path, index_col=0, parse_dates=True)
    assert "FEDTARMD" not in reread.columns
    assert reread.index[-1] <= pd.Timestamp.today().normalize()
    assert pd.read_csv(projection_path(str(path)), index_col=0,
                       parse_dates=True).iloc[-1, 0] == 3.6


def test_dotplot_table_renders_years_as_columns():
    from bcm.macro_dash import dotplot_table

    year = pd.Timestamp.today().year
    proj = pd.DataFrame(
        {"FEDTARMD": [3.6, 3.4, 3.1]},
        index=pd.to_datetime([f"{year}-01-01", f"{year+1}-01-01",
                              f"{year+2}-01-01"]))
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=40)
    panel = pd.DataFrame({"FEDTARMDLR": 3.0}, index=idx)
    panel.iloc[-10:, 0] = 3.2                    # 最後一次會議調升長期中位數

    html = dotplot_table(proj, panel)
    assert f"{year} 年底" in html and f"{year+2} 年底" in html
    assert "3.60" in html and "3.10" in html
    assert "3.20" in html and "長期（r*）" in html
    # 日期取「最後一次數值改變」，不是被向前填補到的最後一個營業日
    assert str(idx[-10].date()) in html
    assert str(idx[-1].date()) not in html
    assert "前瞻預測" in html
    assert dotplot_table(None) == ""
    assert dotplot_table(pd.DataFrame()) == ""


def test_panel_attrs_survive_concat():
    """attrs 裡放 DataFrame 會讓面板任兩欄的 pd.concat 直接拋錯。

    pandas 在 concat 時以 `==` 比較兩邊的 attrs，值是 DataFrame 的話那個比較
    會拋 ValueError，而且訊息完全看不出問題出在 attrs。因此 attrs 只放 dict。
    """
    from bcm.sources import (last_obs_of, merge_panel, projections_of)

    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=30)
    raw = pd.DataFrame({"A": 1.0, "B": 2.0}, index=idx)
    raw.loc[pd.Timestamp.today().normalize() + pd.DateOffset(years=3),
            "FEDTARMD"] = 3.6
    raw.attrs["last_obs"] = pd.Series({"A": idx[-1], "B": idx[3]})
    panel = merge_panel(None, raw.sort_index())

    assert all(isinstance(v, dict) for v in panel.attrs.values())
    pd.concat([panel["A"], panel["B"]], axis=1)      # 不得拋錯
    # 轉換後內容仍正確
    assert projections_of(panel).iloc[-1, 0] == 3.6
    assert last_obs_of(panel)["B"] == idx[3]


def test_ticker_alias_picks_first_with_data():
    """Yahoo 指數代號不穩定，抓不到時 yfinance 只會安靜回傳空欄位。"""
    from bcm.sources import TICKER_ALIASES, pick_alias, resolve_aliases

    want, alias = resolve_aliases(["^GSPC", "^TWOII"])
    assert want[0] == "^GSPC"
    assert alias["^TWOII"] == TICKER_ALIASES["^TWOII"]
    assert all(c in want for c in alias["^TWOII"])

    cands = alias["^TWOII"]
    idx = pd.bdate_range("2026-01-01", periods=5)
    close = pd.DataFrame({c: np.nan for c in cands}, index=idx)
    close["^GSPC"] = 1.0
    close[cands[1]] = 220.0                    # 第一順位沒資料、第二順位有
    out, chosen = pick_alias(close, alias)
    assert set(out.columns) == {"^GSPC", "^TWOII"}   # 候選欄位已收斂
    assert (out["^TWOII"] == 220.0).all()            # 取到有資料的那個
    assert chosen["^TWOII"] == 1                     # 記下選到第幾順位

    # 全部抓不到時不得拋錯，欄位留著（後續健康檢查會標記無資料）
    empty = pd.DataFrame({c: np.nan for c in cands}, index=idx)
    out2, chosen2 = pick_alias(empty, alias)
    assert "^TWOII" in out2.columns and out2["^TWOII"].isna().all()
    assert "^TWOII" not in chosen2


def test_chart_endpoint_fills_series_yfinance_missed(monkeypatch):
    """yfinance 查不到時區就會讓整欄變空 —— chart 端點要能把它補回來。"""
    from bcm import sources

    idx = pd.bdate_range("2026-01-05", periods=5)          # 美股交易日
    close = pd.DataFrame({"^GSPC": 1.0, "^TWOII": np.nan}, index=idx)
    alias = {"^TWOII": ["^TWOII", "006201.TWO"]}

    calls = []

    def fake(symbol, start="2005-01-01", timeout=20):
        calls.append(symbol)
        if symbol != "^TWOII":
            raise RuntimeError("不該走到代理")
        # 台股有一天是美股休市日，索引必須取聯集才不會被切掉
        tw = pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-07",
                             "2026-01-08", "2026-01-09", "2026-01-12"])
        return pd.Series([200.0, 201, 202, 203, 204, 205], index=tw)

    monkeypatch.setattr(sources, "fetch_yahoo_chart", fake)
    out = sources.fill_missing_via_chart(close, alias, "2026-01-01")

    assert calls == ["^TWOII"]                     # 第一順位就成功，不試代理
    assert out["^TWOII"].notna().sum() == 6
    assert pd.Timestamp("2026-01-12") in out.index  # 索引擴充，資料沒被切掉
    assert out.loc[pd.Timestamp("2026-01-05"), "^GSPC"] == 1.0

    # 已經選到第一順位時不該再打網路
    calls.clear()
    sources.fill_missing_via_chart(out, alias, "2026-01-01", {"^TWOII": 0})
    assert calls == []


def test_chart_endpoint_falls_back_to_next_candidate(monkeypatch):
    from bcm import sources

    idx = pd.bdate_range("2026-01-05", periods=5)
    close = pd.DataFrame({"^TWOII": np.nan}, index=idx)
    alias = {"^TWOII": ["^TWOII", "006201.TWO"]}

    def fake(symbol, start="2005-01-01", timeout=20):
        if symbol == "^TWOII":
            raise RuntimeError("chart 端點沒有收盤價")
        return pd.Series([46.0] * 5, index=idx)

    monkeypatch.setattr(sources, "fetch_yahoo_chart", fake)
    out = sources.fill_missing_via_chart(close, alias, "2026-01-01")
    assert (out["^TWOII"] == 46.0).all()


def test_chart_endpoint_outranks_fallback_proxy(monkeypatch):
    """yfinance 只抓到備援代理時，仍要再試一次真正的指數。

    否則第一順位（櫃買指數本身）永遠不會被重試 —— yfinance 一旦抓到
    ETF 代理就算「有資料」，真正的指數就被靜靜地換掉了。
    """
    from bcm import sources

    idx = pd.bdate_range("2026-01-05", periods=5)
    close = pd.DataFrame({"^TWOII": 46.0}, index=idx)     # 已是代理的資料
    alias = {"^TWOII": ["^TWOII", "006201.TWO"]}

    def fake(symbol, start="2005-01-01", timeout=20):
        assert symbol == "^TWOII", "不該重試比選中順位更後面的候選"
        return pd.Series([200.0] * 5, index=idx)

    monkeypatch.setattr(sources, "fetch_yahoo_chart", fake)
    out = sources.fill_missing_via_chart(close, alias, "2026-01-01",
                                         {"^TWOII": 1})
    assert (out["^TWOII"] == 200.0).all()                # 指數蓋過代理


def test_chart_retries_on_rate_limit(monkeypatch):
    """429 是機器人偵測，換一台主機再試一次值得。

    Yahoo 不只看 User-Agent，還看 TLS 指紋：urllib 就算把 UA 設成 Chrome，
    握手層看起來仍是 Python，會被回 429。真正的修法是用 curl_cffi 冒充
    Chrome（見 _chart_get），但傳輸層失敗時仍要換主機重試。
    """
    from bcm import sources

    calls = []
    payload = {"chart": {"result": [{
        "timestamp": [1767225600, 1767312000],
        "indicators": {"quote": [{"close": [200.0, 201.0]}]}}]}}

    def fake_get(url, timeout):
        calls.append(url)
        if len(calls) == 1:
            return 429, None, {"Retry-After": "0"}
        return 200, payload, {}

    monkeypatch.setattr(sources, "_chart_get", fake_get)
    monkeypatch.setattr(sources.time, "sleep", lambda s: None)
    s = sources.fetch_yahoo_chart("^TWOII", start="2026-01-01")

    assert len(calls) == 2, "429 之後要再試一次"
    assert "query1" in calls[0] and "query2" in calls[1], "換一台主機再試"
    assert list(s.values) == [200.0, 201.0]


def test_chart_does_not_retry_on_404(monkeypatch):
    """404 是真的查無此標的，重試只是浪費時間。"""
    from bcm import sources

    calls = []

    def fake_get(url, timeout):
        calls.append(url)
        return 404, None, {}

    monkeypatch.setattr(sources, "_chart_get", fake_get)
    with pytest.raises(RuntimeError, match="查無此標的"):
        sources.fetch_yahoo_chart("^NOPE", start="2026-01-01")
    assert len(calls) == 1


def test_chart_impersonates_chrome(monkeypatch):
    """必須走 curl_cffi 的瀏覽器冒充，不能退回 urllib 的裸請求。"""
    from curl_cffi import requests as creq
    from bcm import sources

    seen = {}

    class R:
        status_code = 200
        text = '{"chart":{"result":[{"timestamp":[1767225600],' \
               '"indicators":{"quote":[{"close":[200.0]}]}}]}}'
        headers = {}

    def fake(url, **kw):
        seen.update(kw)
        return R()

    monkeypatch.setattr(creq, "get", fake)
    out = sources.fetch_yahoo_chart("^TWOII", start="2026-01-01")
    assert seen.get("impersonate") == "chrome"
    assert "Chrome/" in seen["headers"]["User-Agent"]
    assert list(out.values) == [200.0]


def test_prefetch_runs_before_batch_and_beats_proxy(monkeypatch):
    """預抓必須蓋過批次下載抓到的備援代理。

    Yahoo 的限流是自己觸發的：把 chart 呼叫放在大批下載之後，4 次重試
    全部 429。第一順位（真正的指數）值得用還沒被用掉的配額去換。
    """
    from bcm import sources

    idx = pd.bdate_range("2026-01-05", periods=5)
    alias = {"^TWOII": ["^TWOII", "006201.TWO"]}

    # 這個測試要驗的是 Yahoo 路徑，原生來源必須擋掉 —— 否則在有網路的
    # 環境（CI）會真的連上櫃買中心，測試就變成在測網路而不是測邏輯
    monkeypatch.setattr(sources, "NATIVE_SOURCE", {})
    monkeypatch.setattr(sources, "fetch_yahoo_chart",
                        lambda sym, start="2005-01-01", timeout=20, retries=4:
                        pd.Series([200.0] * 5, index=idx) if sym == "^TWOII"
                        else pd.Series(dtype=float))
    pre = sources.prefetch_aliases(alias, "2026-01-01")
    assert set(pre) == {"^TWOII"}
    assert sources.ALIAS_SOURCE["^TWOII"] == "^TWOII"

    # 批次下載抓到的是代理，預抓的指數要蓋過去 —— 值和來源標記都要
    close = pd.DataFrame({"^TWOII": 46.0, "^GSPC": 7000.0}, index=idx)
    sources.ALIAS_SOURCE["^TWOII"] = "006201.TWO"   # 模擬 pick_alias 改寫
    out = sources.apply_prefetched(close, pre)
    assert (out["^TWOII"] == 200.0).all()
    assert (out["^GSPC"] == 7000.0).all()
    assert sources.ALIAS_SOURCE["^TWOII"] == "^TWOII", \
        "來源標記沒蓋回去的話，merge_panel 會把兩種尺度接在同一欄"


def test_prefetch_failure_leaves_batch_result_alone(monkeypatch):
    from bcm import sources

    idx = pd.bdate_range("2026-01-05", periods=5)
    alias = {"^TWOII": ["^TWOII", "006201.TWO"]}

    def boom(sym, start="2005-01-01", timeout=20, retries=4):
        raise RuntimeError("HTTP Error 429: Too Many Requests")

    monkeypatch.setattr(sources, "NATIVE_SOURCE", {})
    monkeypatch.setattr(sources, "fetch_yahoo_chart", boom)
    pre = sources.prefetch_aliases(alias, "2026-01-01")
    assert pre == {}
    close = pd.DataFrame({"^TWOII": 46.0}, index=idx)
    assert (sources.apply_prefetched(close, pre)["^TWOII"] == 46.0).all()


def test_prefetch_source_label_survives_pick_alias(monkeypatch):
    """值來自原生來源、標記卻寫著 ETF —— 會讓來源變更防護失效。

    實際事故：櫃買指數的值已經換成櫃買中心的資料，但 pick_alias 在
    預抓之後才跑，看到 yfinance 抓到了 ETF 就把標記改寫回 006201.TWO。
    merge_panel 比對標記後認為沒換來源，於是把 ETF（約 44 元）和
    指數（約 402 點）接在同一欄，不報錯，只是數字全錯。
    """
    from bcm import sources

    idx = pd.bdate_range("2026-09-01", periods=14)
    alias = {"^TWOII": ["^TWOII", "006201.TWO"]}
    monkeypatch.setitem(sources.NATIVE_SOURCE, "^TWOII",
                        lambda start: pd.Series([402.0] * 14, index=idx))

    pre = sources.prefetch_aliases(alias, "2026-01-01")
    # yfinance 批次下載抓到了較低順位的 ETF，pick_alias 會改寫標記
    close = pd.DataFrame({"^TWOII": np.nan, "006201.TWO": 44.0}, index=idx)
    close, chosen = sources.pick_alias(close, alias)
    assert sources.ALIAS_SOURCE["^TWOII"] == "006201.TWO"   # 被改寫了

    close = sources.apply_prefetched(close, pre)
    assert sources.ALIAS_SOURCE["^TWOII"] == "TPEx", "標記要跟著值一起蓋回去"
    assert (close["^TWOII"] == 402.0).all()


def test_tpex_parser_handles_roc_and_western_dates():
    """TPEx 改版前後的欄位順序與日期格式都不一樣，解析要夠寬鬆。"""
    from bcm.sources import _parse_tpex, _tpex_date

    assert _tpex_date("115/09/19") == pd.Timestamp("2026-09-19")   # 民國年
    assert _tpex_date("2026-09-19") == pd.Timestamp("2026-09-19")
    assert _tpex_date("20260919") == pd.Timestamp("2026-09-19")
    assert _tpex_date("不是日期") is None

    # 舊版 aaData：list of list，民國年，千分位逗號
    old = [["115/09/18", "245.15", "1,234,567"],
           ["115/09/19", "246.30", "1,111,111"]]
    s = _parse_tpex(old)
    assert s.loc[pd.Timestamp("2026-09-19")] == 246.30

    # 新版：list of dict，西元年
    new = [{"Date": "2026-09-19", "Close": "246.30", "Name": "櫃買指數"}]
    assert _parse_tpex(new).iloc[0] == 246.30

    assert _parse_tpex([["沒有日期", "abc"]]) is None


def test_tpex_rows_flattens_response_shapes():
    from bcm.sources import _tpex_rows

    assert _tpex_rows([{"a": 1}]) == [{"a": 1}]
    assert _tpex_rows({"aaData": [[1, 2]]}) == [[1, 2]]
    assert _tpex_rows({"tables": [{"data": [[3, 4]]}]}) == [[3, 4]]
    assert _tpex_rows({"nothing": 1}) == []
    assert _tpex_rows(None) == []


def test_native_source_wins_over_yahoo(monkeypatch):
    """有權威原生來源時不該再繞 Yahoo。"""
    from bcm import sources

    idx = pd.bdate_range("2026-01-05", periods=5)
    monkeypatch.setitem(sources.NATIVE_SOURCE, "^TWOII",
                        lambda start: pd.Series([245.0] * 5, index=idx))
    monkeypatch.setattr(sources, "fetch_yahoo_chart",
                        lambda *a, **k: pytest.fail("不該呼叫 Yahoo"))

    pre = sources.prefetch_aliases({"^TWOII": ["^TWOII"]}, "2026-01-01")
    series, src = pre["^TWOII"]
    assert (series == 245.0).all() and src == "TPEx"
    assert sources.ALIAS_SOURCE["^TWOII"] == "TPEx"


def test_native_source_failure_falls_back_to_yahoo(monkeypatch):
    from bcm import sources

    idx = pd.bdate_range("2026-01-05", periods=5)

    def boom(start):
        raise RuntimeError("櫃買中心所有候選端點都取不到指數")

    monkeypatch.setitem(sources.NATIVE_SOURCE, "^TWOII", boom)
    monkeypatch.setattr(sources, "fetch_yahoo_chart",
                        lambda sym, start="2005-01-01", retries=2:
                        pd.Series([46.0] * 5, index=idx))
    pre = sources.prefetch_aliases({"^TWOII": ["006201.TWO"]}, "2026-01-01")
    series, src = pre["^TWOII"]
    assert (series == 46.0).all() and src == "006201.TWO"


def test_discover_uses_catalog_basepath(monkeypatch):
    """目錄讀對了，網址還是可能組錯。

    第一版直接用 ".../openapi" + "/tpex_index"，漏掉目錄宣告的 /v1，
    21 個候選全部打到站方的 404 頁。
    """
    from bcm import sources

    spec = {"basePath": "/openapi/v1",
            "paths": {"/tpex_index_consti": {"get": {"summary": "成分股"}},
                      "/tpex_index": {"get": {"summary": "櫃買指數"}},
                      "/tpex_stock_quotes": {"get": {"summary": "個股"}}}}
    monkeypatch.setattr(sources, "_http_json",
                        lambda url, timeout=20: (200, spec, ""))
    urls = sources.discover_tpex_index_paths()

    assert urls[0] == "https://www.tpex.org.tw/openapi/v1/tpex_index", \
        "basePath 要接回去，且櫃買指數本身要排第一"
    assert all(u.startswith("https://www.tpex.org.tw/openapi/v1/") for u in urls)
    assert not any("tpex_stock_quotes" in u for u in urls)


def test_discover_handles_openapi3_servers(monkeypatch):
    from bcm import sources

    spec = {"servers": [{"url": "https://www.tpex.org.tw/openapi/v1"}],
            "paths": {"/tpex_index": {"get": {"summary": "櫃買指數"}}}}
    monkeypatch.setattr(sources, "_http_json",
                        lambda url, timeout=20: (200, spec, ""))
    assert sources.discover_tpex_index_paths() == [
        "https://www.tpex.org.tw/openapi/v1/tpex_index"]


def test_tpex_parser_takes_close_not_open():
    """「日期後的第一個數字」會抓到開盤價。

    實際踩過：TPEx 欄位順序是開盤／最高／最低／收盤，2026-09-18 開盤
    401.05、收盤 412.68，儀表板上顯示的是 401.05。數字看起來完全合理，
    所以不會有人發現 —— 只有拿原始資料對照才看得出來。
    """
    from bcm.sources import _parse_tpex

    # 具名欄位：以欄位名認收盤
    named = [{"Date": "2026-09-18", "Open": "401.05", "High": "412.68",
              "Low": "401.05", "Close": "412.68", "Volume": "2659079"}]
    assert _parse_tpex(named).iloc[0] == 412.68

    zh = [{"日期": "115/09/18", "開盤價": "401.05", "最高價": "412.68",
           "最低價": "401.05", "收盤價": "412.68"}]
    assert _parse_tpex(zh).iloc[0] == 412.68

    # 無欄位名：位置推斷取第 4 個數字（OHLC）
    positional = [["2026-09-18", "401.05", "412.68", "401.05", "412.68"]]
    assert _parse_tpex(positional).iloc[0] == 412.68

    # 不像 OHLC 時退回第一個數字，不要誤拿成交量
    not_ohlc = [["2026-09-18", "401.05", "2659079"]]
    assert _parse_tpex(not_ohlc).iloc[0] == 401.05


def test_twoii_seed_merges_with_live(monkeypatch, tmp_path):
    """歷史種子檔要和即時資料合併，重疊處以即時為準。"""
    from bcm import sources

    seed = tmp_path / "seed.csv"
    seed.write_text("date,close\n2026-09-17,398.17\n2026-09-18,999.0\n")
    monkeypatch.setattr(sources, "TWOII_SEED", str(seed))
    monkeypatch.setattr(sources, "TPEX_ENDPOINTS",
                        [("fake", "https://example.invalid/{ymd}{roc}")])
    monkeypatch.setattr(sources, "_http_json", lambda url, timeout=20: (
        200, [{"Date": "2026-09-18", "Close": "412.68"}], ""))

    out = sources.fetch_tpex_index(start="2000-01-01")
    assert out.loc[pd.Timestamp("2026-09-17")] == 398.17   # 來自種子檔
    assert out.loc[pd.Timestamp("2026-09-18")] == 412.68   # 即時覆蓋種子

    # 即時端點全掛時仍要交出歷史，而不是整欄消失
    monkeypatch.setattr(sources, "_http_json",
                        lambda url, timeout=20: (500, None, "boom"))
    monkeypatch.setattr(sources, "discover_tpex_index_paths", lambda: [])
    fallback = sources.fetch_tpex_index(start="2000-01-01")
    assert len(fallback) == 2 and fallback.iloc[-1] == 999.0
