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


def test_full_cycle_visits_every_stage_in_order():
    G, I = _synthetic_cycle()
    out = stages.run(G, I, momentum_periods=3, confirm=2)
    seq = out["stage"].loc[out["stage"] > 0]
    # 壓縮成不重複的階段序列
    order = [s for s, nxt in zip(seq, list(seq[1:]) + [None]) if s != nxt]
    assert set(order) >= {1, 2, 3, 4, 5, 6}, f"未走完六階段：{order}"
    # 循環必須向前推進。允許跳過一階（月頻取樣下，某階段可能不足一個月
    # 就被跨過），但絕不可倒退 —— 倒退代表判定邏輯有問題。
    for a, b in zip(order, order[1:]):
        step = (b - a) % 6
        assert step in (1, 2), f"階段 {a} → {b} 並非向前推進"


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
