"""總經儀表板與資料健康檢查的測試。

重點放在單位換算 —— 這是本專案已經踩過兩次的地雷：
一次是 RRPONTSYD（十億 vs 百萬），一次是高收益債利差門檻（基點 vs 百分點）。
兩者都不會拋錯，只會安靜地算出錯的數字。
"""
import numpy as np
import pandas as pd
import pytest

from bcm import derived, health, macro_dash


# ------------------------------------------------------------ 單位換算
def test_net_liquidity_converts_rrp_from_billions_to_millions():
    """RRPONTSYD 以十億美元計，WALCL/WTREGEN 以百萬美元計，必須 ×1000。"""
    idx = pd.bdate_range("2026-01-01", periods=5)
    panel = pd.DataFrame({
        "WALCL":     [7_000_000.0] * 5,   # 百萬 → 7 兆
        "WTREGEN":   [500_000.0] * 5,     # 百萬 → 0.5 兆
        "RRPONTSYD": [200.0] * 5,         # 十億 → 0.2 兆
    }, index=idx)
    out, skipped = derived.add_derived(panel)
    assert not skipped.get("NET_LIQ")
    # 7兆 − 0.5兆 − 0.2兆 = 6.3兆 = 6,300,000 百萬
    assert out["NET_LIQ"].iloc[-1] == pytest.approx(6_300_000.0)
    # 若忘了換算會得到 6,499,800 —— 明確排除這個錯誤值
    assert out["NET_LIQ"].iloc[-1] != pytest.approx(7_000_000 - 500_000 - 200)


def test_hy_oas_thresholds_are_in_percent_not_basis_points():
    """FRED BAMLH0A0HYM2 單位是百分點。門檻若誤用基點，任何值都會判成極窄。"""
    import bcm.indicators as cfg
    cfg.PROFILE = "macro"
    groups = cfg.active()["groups"]
    th = next(item[3] for _, items in groups for item in items
              if item[1] == "BAMLH0A0HYM2")
    assert th["calm"] < 10 and th["stress"] < 10, "門檻應為百分點量級（約 3~5）"

    # 320bp = 3.20% 應判為常態，而非極窄
    assert macro_dash.threshold_note("BAMLH0A0HYM2", 3.20, th)[0] == "常態區間"
    assert macro_dash.threshold_note("BAMLH0A0HYM2", 2.50, th)[0] == "利差極窄"
    assert macro_dash.threshold_note("BAMLH0A0HYM2", 6.00, th)[1] == "alert"


def test_sahm_gap_uses_min_of_moving_average():
    """Sahm 缺口減的是「3MMA 的前 12 個月最低值」，不是原始失業率的最低值。"""
    idx = pd.date_range("2024-01-31", periods=30, freq="ME")
    # 中間插入單月低點：原始最低值會被它拉低，3MMA 的最低值不會
    u = np.full(30, 4.0)
    u[10] = 3.0
    u[-3:] = [4.6, 4.8, 5.0]
    out, _ = derived.add_derived(pd.DataFrame({"UNRATE": u}, index=idx))
    gap = out["SAHM_GAP"].dropna()
    mma = pd.Series(u, index=idx).rolling(3).mean()
    expected = mma.iloc[-1] - mma.rolling(12).min().iloc[-1]
    assert gap.iloc[-1] == pytest.approx(expected)
    # 用原始最低值會算出更大的缺口 —— 確認沒有算成那個
    assert gap.iloc[-1] != pytest.approx(mma.iloc[-1] - u.min())


def test_derived_reports_missing_inputs_instead_of_silently_skipping():
    idx = pd.bdate_range("2026-01-01", periods=3)
    panel = pd.DataFrame({"WALCL": [1.0, 2.0, 3.0]}, index=idx)
    out, skipped = derived.add_derived(panel)
    assert "NET_LIQ" not in out.columns
    assert set(skipped["NET_LIQ"]) == {"WTREGEN", "RRPONTSYD"}


# ------------------------------------------------------------ 健康檢查
def test_health_flags_all_nan_column():
    """迴歸測試：IC4WSA 曾因對齊營業日而整欄變 NaN，卻沒有任何警示。"""
    idx = pd.bdate_range("2026-08-01", periods=30)
    panel = pd.DataFrame({"A": np.arange(30.0), "B": np.nan}, index=idx)
    h = health.check_panel(panel, [("甲", "A", "daily"), ("乙", "B", "daily")])
    assert h.set_index("代碼").loc["B", "status"] == "無資料"
    assert h.set_index("代碼").loc["A", "status"] == "正常"
    assert h.iloc[0]["代碼"] == "B", "異常項目應排在最前面"


def test_health_detects_stale_and_delayed():
    idx = pd.bdate_range("2026-01-01", periods=200)
    panel = pd.DataFrame({"D": np.arange(200.0)}, index=idx)
    panel.loc[idx[-20:], "D"] = np.nan          # 日頻卻 20 個營業日沒更新
    h = health.check_panel(panel, [("日頻", "D", "daily")], asof=idx[-1])
    assert h.iloc[0]["status"] in ("延遲", "停更")

    panel2 = panel.copy()
    panel2["D"] = np.arange(200.0)
    h2 = health.check_panel(panel2, [("日頻", "D", "daily")], asof=idx[-1])
    assert h2.iloc[0]["status"] == "正常"


def test_health_missing_column_is_reported():
    idx = pd.bdate_range("2026-01-01", periods=5)
    h = health.check_panel(pd.DataFrame({"A": range(5)}, index=idx),
                           [("不存在", "ZZZ", "daily")])
    assert h.iloc[0]["status"] == "無資料"
    assert h.iloc[0]["n"] == 0


def test_health_summary_counts():
    idx = pd.bdate_range("2026-01-01", periods=10)
    panel = pd.DataFrame({"A": np.arange(10.0), "B": np.nan}, index=idx)
    h = health.check_panel(panel, [("甲", "A", "daily"), ("乙", "B", "daily")])
    s = health.summarise(h)
    assert s["total"] == 2 and s["ok"] == 1 and s["missing"] == 1
    assert not s["healthy"]


# ------------------------------------------------------------ 呈現邏輯
def test_yoy_uses_calendar_year_not_fixed_row_count():
    idx = pd.bdate_range("2024-01-01", periods=700)
    s = pd.Series(np.linspace(100, 200, 700), index=idx)
    panel = pd.DataFrame({"X": s})
    yoy = macro_dash.metric_series(panel, "X", "yoy")
    # 以日曆年對齊：最後一點應約等於「相對一年前」的變化
    prev = s.reindex([idx[-1] - pd.DateOffset(years=1)], method="ffill").iloc[0]
    assert yoy.iloc[-1] == pytest.approx((s.iloc[-1] / prev - 1) * 100, rel=1e-6)


def test_rate_mode_change_is_labelled_as_percentage_points():
    """比率型指標的主值已是百分比，其變化必須標成 pp，否則同卡出現兩個矛盾的 %。"""
    assert macro_dash.CHANGE_UNIT["pct"] == "pp"
    assert macro_dash.CHANGE_UNIT["yoy"] == "pp"
    assert macro_dash.CHANGE_UNIT["level"] == ""
    assert macro_dash.CHANGE_LABEL["pct"] != macro_dash.CHANGE_LABEL["level"]


def test_far_threshold_does_not_flatten_sparkline():
    """遠離資料的門檻不得納入座標範圍，否則真實波動被壓成平線。"""
    idx = pd.bdate_range("2026-01-01", periods=120)
    s = pd.Series(np.linspace(-1.2, -0.8, 120), index=idx)
    far = macro_dash.sparkline(s, thresholds={"far": 500.0})
    assert "spark-th" not in far, "500 遠離資料，不該撐開座標軸"

    near = macro_dash.sparkline(s, thresholds={"calm": -1.0})
    assert "spark-th" in near, "門檻落在資料範圍內，應該畫出來"


def test_inversion_zero_line_always_shown():
    """倒掛指標的零軸是語意本身：整條線都在負值區時更需要看見它。"""
    idx = pd.bdate_range("2026-01-01", periods=120)
    s = pd.Series(np.linspace(-1.2, -0.8, 120), index=idx)
    out = macro_dash.sparkline(s, thresholds={"invert_zone": 0.0})
    assert "spark-th" in out, "invert_zone 不受距離限制，必須畫出零軸"


def test_missing_series_renders_placeholder_card():
    idx = pd.bdate_range("2026-01-01", periods=10)
    panel = pd.DataFrame({"A": np.arange(10.0)}, index=idx)
    card = macro_dash.metric_card(panel, "不存在", "ZZZ", "level", None)
    assert "mcard missing" in card and "無資料" in card


def test_arrow_matches_displayed_value():
    """顯示 +0.00 時不該配 ▲ —— 方向要依四捨五入後的顯示值判斷。"""
    idx = pd.bdate_range("2026-01-01", periods=200)
    s = pd.Series(5.0, index=idx)
    s.iloc[-1] = 5.001                       # 變化小到顯示為 +0.00
    card = macro_dash.metric_card(pd.DataFrame({"X": s}), "測試", "X", "level", None)
    assert "+0.00" in card
    assert "▲" not in card and "▼" not in card


# ------------------------------------------------- 變化幅度排序與異常標示
def _wiggly_panel(n=600):
    idx = pd.bdate_range(end="2026-09-18", periods=n)
    rng = np.random.default_rng(3)
    calm = pd.Series(np.cumsum(rng.normal(0, 0.01, n)) + 10, index=idx)
    shock = calm.copy()
    shock.iloc[-60:] += np.linspace(0, 5, 60)      # 近期大幅偏離
    return pd.DataFrame({"CALM": calm, "SHOCK": shock}, index=idx)


def test_change_zscore_flags_unusual_move():
    panel = _wiggly_panel()
    z_calm = macro_dash.change_zscore(panel["CALM"].dropna())
    z_shock = macro_dash.change_zscore(panel["SHOCK"].dropna())
    assert abs(z_shock) > abs(z_calm)
    assert abs(z_shock) >= macro_dash.ANOMALY_Z


def test_rank_items_puts_largest_move_first():
    panel = _wiggly_panel()
    items = [("平穩", "CALM", "level", None), ("劇變", "SHOCK", "level", None)]
    assert macro_dash.rank_items(panel, items)[0][1] == "SHOCK"


def test_missing_series_sinks_to_bottom():
    panel = _wiggly_panel()
    items = [("缺料", "NOPE", "level", None), ("平穩", "CALM", "level", None)]
    assert macro_dash.rank_items(panel, items)[-1][1] == "NOPE"


def test_anomaly_chip_rendered_when_z_exceeds_threshold():
    """迴歸測試：z 分數算出來了卻沒插進卡片標記，曾導致區塊說有異常但卡片沒標。"""
    panel = _wiggly_panel()
    card = macro_dash.metric_card(panel, "劇變", "SHOCK", "level", None, zscore=3.4)
    assert "zchip" in card and "3.4σ" in card
    quiet = macro_dash.metric_card(panel, "平穩", "CALM", "level", None, zscore=0.3)
    assert "zchip" not in quiet


def test_group_anomaly_count_matches_rendered_chips():
    """區塊標題宣稱的異常數，必須等於卡片上實際畫出的標記數。"""
    import re
    panel = _wiggly_panel()
    html = macro_dash.groups_html(panel, [
        ("測試", [("平穩", "CALM", "level", None),
                  ("劇變", "SHOCK", "level", None)])])
    chips = len(re.findall(r'class="zchip"', html))
    claimed = sum(int(m) for m in re.findall(r'⚠ (\d+) 項變化異常', html))
    assert chips == claimed == 1


# ------------------------------------------------------------ 殖利率曲線
def test_yield_curve_overlays_current_and_past():
    idx = pd.bdate_range(end="2026-09-18", periods=400)
    rng = np.random.default_rng(5)
    base = pd.Series(np.cumsum(rng.normal(0, 0.01, 400)) + 4.0, index=idx)
    panel = pd.DataFrame({c: base + off for c, off in
                          [("DGS3MO", 0.4), ("DGS2", 0.0), ("DGS10", 0.3),
                           ("DGS30", 0.5)]}, index=idx)
    out = macro_dash.yield_curve_svg(panel)
    assert "<svg" in out
    assert "現在" in out and "3個月前" in out
    assert "各天期數值" in out, "應附可展開的數值表，不能只有圖"


def test_yield_curve_degrades_without_data():
    idx = pd.bdate_range(end="2026-09-18", periods=50)
    out = macro_dash.yield_curve_svg(pd.DataFrame({"X": range(50)}, index=idx))
    assert "<svg" not in out and "尚無" in out


def test_fixed_order_groups_are_not_resorted():
    """殖利率天期有內在順序，不可依變化幅度重排。"""
    import re
    panel = _wiggly_panel()
    group = [("測試", [("平穩", "CALM", "level", None),
                       ("劇變", "SHOCK", "level", None)])]
    sorted_html = macro_dash.groups_html(panel, group)
    fixed_html = macro_dash.groups_html(panel, group, fixed_order={"測試"})
    order = lambda h: re.findall(r'class="m-name">([^<]+)<', h)
    assert order(sorted_html)[0] == "劇變", "預設應依變化幅度排序"
    assert order(fixed_html) == ["平穩", "劇變"], "指定固定順序時應維持宣告順序"


# ------------------------------------------------------------ 曲線型態判讀
CURVES = {
    "正斜率":  [("3M",4.2),("1Y",4.3),("2Y",4.4),("5Y",4.7),("10Y",5.0),("30Y",5.3)],
    "倒掛":    [("3M",5.4),("1Y",5.1),("2Y",4.8),("5Y",4.4),("10Y",4.2),("30Y",4.3)],
    "倒掛U":   [("3M",5.3),("1Y",4.6),("2Y",4.2),("5Y",4.1),("10Y",4.3),("30Y",4.6)],
    "駝峰":    [("3M",3.8),("1Y",4.3),("2Y",4.6),("5Y",4.4),("10Y",4.1),("30Y",3.9)],
    "平坦":    [("3M",4.30),("1Y",4.32),("2Y",4.28),("5Y",4.35),("10Y",4.40),("30Y",4.45)],
    "陡峭":    [("3M",2.0),("1Y",2.4),("2Y",2.9),("5Y",3.4),("10Y",3.9),("30Y",4.2)],
}


@pytest.mark.parametrize("key,expect", [
    ("正斜率", "正斜率"), ("倒掛", "倒掛"), ("倒掛U", "倒掛"),
    ("駝峰", "正斜率"), ("平坦", "平坦"), ("陡峭", "陡峭"),
])
def test_curve_primary_shape(key, expect):
    assert expect in macro_dash.classify_curve(CURVES[key])[0]


def test_curve_secondary_feature():
    """主型態與次要特徵可同時成立 —— 整體倒掛但中段落底後長端回升。"""
    assert "U 型" in macro_dash.classify_curve(CURVES["倒掛U"])[0]
    assert "駝峰" in macro_dash.classify_curve(CURVES["駝峰"])[0]
    assert "U 型" not in macro_dash.classify_curve(CURVES["倒掛"])[0], \
        "長端未實質回升時不該標成 U 型"


def test_curve_needs_enough_tenors():
    assert macro_dash.classify_curve([("3M", 4.0), ("10Y", 4.2)])[0] == "資料不足"


def test_policy_band_drawn_on_curve():
    idx = pd.bdate_range(end="2026-09-18", periods=400)
    base = pd.Series(np.linspace(4.0, 4.4, 400), index=idx)
    panel = pd.DataFrame({
        "DGS3MO": base + 0.5, "DGS2": base + 0.1, "DGS10": base,
        "DGS30": base + 0.2,
        "DFEDTARU": pd.Series(4.75, index=idx),
        "DFEDTARL": pd.Series(4.50, index=idx),
    })
    out = macro_dash.yield_curve_svg(panel)
    assert "policy-band" in out, "應畫出政策利率區間"
    assert "shape-tag" in out, "應顯示型態判讀"


# ------------------------------------------------------ 資料來源與性質標註
def test_every_tenor_declares_security_type():
    """每個天期都要標明是國庫券還是附息債券 —— 這決定它是不是曲線的輸入點。"""
    from bcm import glossary
    for code, (kind, auction) in glossary.TENOR_KIND.items():
        meta = glossary.get(code)
        assert meta is not None, code
        assert kind in meta["src"], f"{code} 未標註證券類型"
        assert "標售" in meta["src"]


def test_cmt_methodology_is_documented():
    """CMT 用的是報價而非成交價，且本身是擬合曲線 —— 這點必須寫明。"""
    from bcm import glossary
    f = glossary.get("DGS3")["formula"]
    assert "報價" in f and "monotone convex" in f
    assert "實際標售的證券" in glossary.get("DGS3")["what"], \
        "須說明該天期是輸入點而非內插值"


def test_curve_card_states_provenance():
    idx = pd.bdate_range(end="2026-09-18", periods=300)
    base = pd.Series(np.linspace(4.0, 4.3, 300), index=idx)
    panel = pd.DataFrame({c: base + o for c, o in
                          [("DGS3MO", .5), ("DGS2", .1), ("DGS10", 0), ("DGS30", .2)]})
    out = macro_dash.yield_curve_svg(panel)
    assert "實際標售的證券" in out
    assert "內插" in out


# ------------------------------------------------------ 期貨隱含利率與點陣圖
def test_fed_funds_futures_implied_rate():
    """Fed Funds 期貨的報價慣例：隱含利率 = 100 − 價格。"""
    idx = pd.bdate_range(end="2026-09-18", periods=5)
    panel = pd.DataFrame({"ZQ=F": [96.12] * 5}, index=idx)
    out, skipped = derived.add_derived(panel)
    assert not skipped.get("FF_IMPLIED")
    assert out["FF_IMPLIED"].iloc[-1] == pytest.approx(3.88)


def test_projection_series_not_flagged_stale():
    """點陣圖的觀測日標在未來年度，不可用『落後幾天』判為停更。"""
    future = pd.Timestamp("2026-09-18") + pd.DateOffset(years=2)
    idx = pd.DatetimeIndex([pd.Timestamp("2026-12-31"), future])
    panel = pd.DataFrame({"FEDTARMD": [3.6, 3.1]}, index=idx)
    h = health.check_panel(panel, [("點陣圖", "FEDTARMD", "projection")],
                           asof=pd.Timestamp("2026-09-18"))
    assert h.iloc[0]["status"] == "正常"
    assert "預測至" in h.iloc[0]["detail"]


def test_projection_series_flagged_when_outdated():
    """若最後一筆預測年度已過去，代表 SEP 沒更新，應標為延遲。"""
    idx = pd.DatetimeIndex([pd.Timestamp("2024-12-31")])
    panel = pd.DataFrame({"FEDTARMD": [4.4]}, index=idx)
    h = health.check_panel(panel, [("點陣圖", "FEDTARMD", "projection")],
                           asof=pd.Timestamp("2026-09-18"))
    assert h.iloc[0]["status"] == "延遲"
    assert "SEP" in h.iloc[0]["detail"]


# ------------------------------------------- 向前填補讓健康檢查看不見停更序列
# 面板裡每一欄都被填補到最後一個營業日，所以從面板本身看，任何序列都像是
# 「今天剛更新」。真實觀測日必須在填補前記下並隨快取一起保存，否則這個
# 用來抓「指標默默失效」的檢查，自己就先失效了。

def test_forward_fill_hides_stalled_series_without_last_obs():
    from bcm import health

    idx = pd.bdate_range("2026-01-01", "2026-09-18")
    # 真實觀測停在 3 月，但面板已被填補到 9 月
    panel = pd.DataFrame({"UNRATE": 4.2}, index=idx)
    spec = [("失業率", "UNRATE", "monthly")]

    naive = health.check_panel(panel, spec, asof=idx[-1])
    assert naive.iloc[0]["status"] == "正常", "沒有觀測日紀錄時只能看到假的正常"
    assert not naive.iloc[0]["verified"]

    真 = pd.Series({"UNRATE": pd.Timestamp("2026-03-01")})
    checked = health.check_panel(panel, spec, asof=idx[-1], last_obs=真)
    assert checked.iloc[0]["status"] == "停更"
    assert checked.iloc[0]["last"] == pd.Timestamp("2026-03-01")
    assert checked.iloc[0]["verified"]
    assert health.summarise(checked)["unverified"] == 0
    assert health.summarise(naive)["unverified"] == 1


def test_last_obs_recorded_before_forward_fill():
    from bcm.sources import last_observations, to_business_days

    idx = pd.bdate_range("2026-01-01", periods=40)
    raw = pd.DataFrame({"DAILY": 1.0, "MONTHLY": np.nan}, index=idx)
    raw.loc[idx[5], "MONTHLY"] = 3.0
    lo = last_observations(raw)
    assert lo["MONTHLY"] == idx[5] and lo["DAILY"] == idx[-1]
    # 填補後從面板本身再也看不出 MONTHLY 停在第 6 天
    filled = to_business_days(raw)
    assert filled["MONTHLY"].last_valid_index() == idx[-1]


def test_cache_roundtrip_keeps_last_obs(tmp_path):
    from bcm.sources import load_cache, merge_panel, save_cache, last_obs_of

    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=20)
    panel = pd.DataFrame({"A": 1.0, "B": 2.0}, index=idx)
    lo = pd.Series({"A": idx[-1], "B": idx[3]})
    path = tmp_path / "panel.csv"
    save_cache(panel, str(path), last_obs=lo)

    got = load_cache(str(path))
    assert last_obs_of(got)["B"] == idx[3]

    # 合併時逐欄取較晚的觀測日，且不會弄丟舊欄位的紀錄
    newer = pd.DataFrame({"B": 2.0}, index=idx)
    newer.attrs["last_obs"] = pd.Series({"B": idx[-1]})
    merged = merge_panel(got, newer)
    m = last_obs_of(merged)
    assert m["B"] == idx[-1] and m["A"] == idx[-1]


def test_publication_lag_overrides_prevent_false_delays():
    """發布延遲因序列而異：核心PCE 落後兩個月是正常的，不該報成延遲。"""
    from bcm import health

    idx = pd.bdate_range("2026-01-01", "2026-09-18")
    panel = pd.DataFrame({"PCEPILFE": 2.9, "UNRATE": 4.2}, index=idx)
    lo = pd.Series({"PCEPILFE": pd.Timestamp("2026-07-01"),
                    "UNRATE": pd.Timestamp("2026-07-01")})
    h = health.check_panel(panel,
                          [("核心PCE", "PCEPILFE", "monthly"),
                           ("失業率", "UNRATE", "monthly")],
                          asof=idx[-1], last_obs=lo)
    by = h.set_index("代碼")["status"].to_dict()
    # 同樣落後 79 天：核心PCE 屬正常，失業率則確實太久沒更新
    assert by["PCEPILFE"] == "正常"
    assert by["UNRATE"] == "延遲"


def test_card_shows_true_observation_date_not_panel_date():
    """卡片下緣的日期若用面板日期，月頻指標會看起來像今天剛公布。"""
    idx = pd.bdate_range("2026-01-01", "2026-09-18")
    panel = pd.DataFrame({"PCEPILFE": 2.9}, index=idx)
    true_obs = pd.Timestamp("2026-07-01")

    html = macro_dash.metric_card(panel, "核心PCE", "PCEPILFE", "level", None,
                                  last_obs=true_obs)
    assert "2026-07-01" in html
    assert "2026-09-18" not in html
    # 沒有紀錄時退回面板日期（維持原行為，不至於空白）
    assert "2026-09-18" in macro_dash.metric_card(
        panel, "核心PCE", "PCEPILFE", "level", None)


def test_balance_sheet_cards_show_readable_units():
    """央行資產負債表以百萬美元發布，直接印出是 6,746,548 —— 沒人讀得出量級。"""
    idx = pd.bdate_range("2026-01-01", periods=120)
    panel = pd.DataFrame({"WALCL": np.linspace(6.8e6, 6.75e6, 120),
                          "WTREGEN": np.linspace(8.0e5, 8.77e5, 120)},
                         index=idx)
    walcl = macro_dash.metric_card(panel, "Fed 總資產", "WALCL", "level", None)
    assert "兆美元" in walcl and "6,746,5" not in walcl
    tga = macro_dash.metric_card(panel, "財政部TGA", "WTREGEN", "level", None)
    assert "十億美元" in tga
    # 變化量也要跟著換算，否則箭頭方向會和顯示值對不上
    raw = panel["WTREGEN"]
    expect = (raw.iloc[-1] - raw.iloc[-64]) * 1e-3
    assert f"{expect:+,.2f}" in tga
    assert "▲" in tga                     # 上升，且與顯示值同號


def test_short_history_does_not_claim_three_months():
    """序列還短時（剛換資料來源）不能沿用「近3個月」的標籤。

    櫃買指數改由櫃買中心取得後，一開始只有當月十幾筆；沿用原標籤
    會把三天的變化講成三個月的變化。
    """
    idx = pd.bdate_range("2026-09-01", periods=14)
    short = pd.DataFrame({"^TWOII": np.linspace(402.0, 401.0, 14)}, index=idx)
    html = macro_dash.metric_card(short, "櫃買OTC", "^TWOII", "level", None)
    assert "近3個月" not in html
    assert "近" in html and "天" in html

    # 歷史夠長時維持原本的標籤
    long_idx = pd.bdate_range("2025-01-01", periods=300)
    long = pd.DataFrame({"^TWOII": np.linspace(300.0, 400.0, 300)},
                        index=long_idx)
    assert "近3個月" in macro_dash.metric_card(
        long, "櫃買OTC", "^TWOII", "level", None)


def test_span_days_reports_actual_window():
    idx = pd.bdate_range("2026-09-01", periods=14)
    panel = pd.DataFrame({"X": np.arange(14.0)}, index=idx)
    snap = macro_dash.metric_snapshot(panel, "X", "level")
    assert snap["span_days"] < 20            # 只有兩週多的資料
    assert snap["change"] < 14               # 不是頭尾相減
