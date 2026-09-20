"""每日總結的測試。

重點在於確保它<b>只描述、不預測</b> —— 這是刻意的設計限制，
因為本專案的檢驗顯示景氣階段模型不具預測力，用同一批資料寫出
帶方向性的建議只會把沒有依據的東西包裝得像有依據。
"""
import numpy as np
import pandas as pd
import pytest

import bcm.indicators as cfg
from bcm import briefing, derived


@pytest.fixture
def panel():
    idx = pd.bdate_range(end="2026-09-18", periods=700)
    rng = np.random.default_rng(11)
    n = len(idx)

    def ou(start, mu, vol, theta=0.004):
        x = np.empty(n); x[0] = start
        for i in range(1, n):
            x[i] = x[i-1] + theta*(mu - x[i-1]) + rng.normal(0, vol)
        return x

    d = {"DGS3MO": ou(5.0, 4.9, 0.02), "DGS2": ou(4.3, 4.2, 0.02),
         "DGS5": ou(4.1, 4.1, 0.02), "DGS10": ou(4.2, 4.2, 0.02),
         "DGS30": ou(4.5, 4.5, 0.02),
         "^VIX": np.clip(ou(17, 18, 0.5, 0.02), 9, 60),
         "BAMLH0A0HYM2": ou(3.3, 3.4, 0.03),
         "T10Y2Y": ou(-0.1, -0.1, 0.02),
         "T10Y3M": ou(-0.8, -0.8, 0.02),
         "^GSPC": 7000*np.exp(np.cumsum(rng.normal(0.0003, 0.009, n)))}
    p = pd.DataFrame(d, index=idx)
    p, _ = derived.add_derived(p)
    return p


@pytest.fixture(autouse=True)
def macro_profile():
    old = cfg.PROFILE
    cfg.PROFILE = "macro"
    yield
    cfg.PROFILE = old


def test_collect_returns_verifiable_facts(panel):
    f = briefing.collect(panel, cfg)
    assert f["asof"] == panel.index[-1]
    assert f["shape_now"], "應判定出曲線型態"
    for m in f["movers"]:
        assert set(m) >= {"name", "code", "z", "change", "current"}
        assert np.isfinite(m["z"])


def test_sentences_are_descriptive_not_predictive(panel):
    """不得出現預測或投資建議的措辭。"""
    text = "".join(briefing.sentences(briefing.collect(panel, cfg)))
    forbidden = ["將會", "預期會", "看好", "看壞", "建議買", "建議賣",
                 "應加碼", "應減碼", "後市", "目標價", "可望"]
    for w in forbidden:
        assert w not in text, f"總結不應出現預測性措辭：{w}"


def test_sentences_cover_curve_threshold_and_health(panel):
    lines = briefing.sentences(briefing.collect(panel, cfg))
    joined = "".join(lines)
    assert "殖利率曲線" in joined
    assert ("警戒區間" in joined or "需留意" in joined)
    assert len(lines) >= 3


def test_shape_change_is_reported(panel, monkeypatch):
    """曲線型態與三個月前不同時必須明講。"""
    from bcm import macro_dash
    calls = {"n": 0}

    def fake(curve):
        calls["n"] += 1
        return ("倒掛", "") if calls["n"] == 1 else ("正斜率（正常）", "")

    monkeypatch.setattr(macro_dash, "classify_curve", fake)
    f = briefing.collect(panel, cfg)
    assert "轉為" in "".join(briefing.sentences(f))


def test_health_problem_is_surfaced(panel):
    """資料有問題時必須在總結裡警示，不能只藏在健康檢查表。"""
    broken = panel.copy()
    broken["^VIX"] = np.nan
    text = "".join(briefing.sentences(briefing.collect(broken, cfg)))
    assert "資料有問題" in text and "先不要看" in text


def test_render_produces_section(panel):
    html = briefing.render(panel, cfg)
    assert 'class="brief"' in html and "今日重點" in html
    # 先前這裡斷言頁面上必須印著「不預測後市」。改為檢查真正該保證的性質：
    # 摘要本身不得出現預測或建議的用語 —— 貼一句免責聲明擋不住一句
    # 「後市看好」，但這個檢查可以。
    for word in ("預測", "將會", "可望", "看好", "看壞", "建議買", "建議賣",
                 "目標價", "應該買", "逢低"):
        assert word not in html, f"摘要不得出現預測／建議用語：{word}"
