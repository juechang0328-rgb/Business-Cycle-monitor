"""資料抓取層：yfinance（價格）＋ FRED CSV（殖利率／利差，免 API key）。

設計原則：
- 只用日頻、免費、免註冊的資料源，每天可自動更新。
- yfinance 負責「價格」；FRED 負責「利率與利差」。
  Yahoo 的殖利率指數（^TNX/^FVX/^TYX/^IRX）可用，但沒有 2 年期，
  且歷史上曾以「殖利率×10」報價，需正規化；FRED 的 DGS2/DGS5/DGS10 乾淨得多。
"""
from __future__ import annotations

import io
import time
from typing import Iterable

import pandas as pd

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={code}"

# 前瞻性序列：觀測日標在「被預測的未來年度」而非發布日。
# 這類資料不可混入日頻面板 —— 它會把面板的時間軸拉到未來，
# 使其他序列被向前填補成一條長長的平線，連帶讓「三個月變化」變成 0。
# 因此一律分離存放。
# 注意只有 FEDTARMD 屬於這一類：它的觀測日是「被預測的年度」（2029-01-01）。
# FEDTARMDLR（長期中位數）雖然也是預測，但觀測日標在 FOMC 會議日（過去），
# 留在日頻面板裡是正確的。
PROJECTION_CODES = {"FEDTARMD"}


# --------------------------------------------------------------------- yfinance
# Yahoo 的指數代號不穩定，同一個指數在不同時期／不同區域站台可能是不同代號，
# 而抓不到時 yfinance 只會安靜地回傳空欄位。因此對有疑慮的序列列出候選代號，
# 一次全抓，取第一個真的有資料的，並把它更名為正式代號。
TICKER_ALIASES = {
    # 櫃買（OTC / TPEx）指數。^TWOII 是 Yahoo 台股站上櫃買指數的代號，
    # 但 yfinance 的下載路徑會先查 quoteSummary 取時區，這一步對它會失敗
    # （回報 possibly delisted; no timezone found），於是整欄安靜地變成空的。
    # 注意它和 ^TWO／^OTCI 不同 —— 那兩個是真的查無此標的（明確 404）。
    # 因此保留 ^TWOII 為第一順位，由 chart API 直接補抓（見 fetch_yahoo_chart），
    # 真的都失敗時才退到櫃買市場掛牌的 ETF 當代理。
    "^TWOII": ["^TWOII", "006201.TWO", "6201.TWO"],
}


def fetch_yahoo_chart(symbol: str, start: str = "2005-01-01",
                      timeout: int = 20) -> pd.Series:
    """繞過 yfinance，直接打 Yahoo 的 chart 端點取收盤價。

    存在的理由：yfinance 下載前會先查 quoteSummary 拿時區，那一步對某些
    指數（例如櫃買 ^TWOII）會失敗，於是整欄變成空的 —— 但 chart 端點本身
    是有資料的。少了這條路就只能改用 ETF 代理，失去真正的指數。
    """
    import json
    import urllib.parse
    import urllib.request

    p1 = int(pd.Timestamp(start).timestamp())
    p2 = int(pd.Timestamp.today().normalize().timestamp()) + 86400
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/"
           f"{urllib.parse.quote(symbol)}"
           f"?period1={p1}&period2={p2}&interval=1d")
    req = urllib.request.Request(url, headers={
        # 預設的 Python-urllib UA 會被 Yahoo 擋掉
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    res = (data.get("chart") or {}).get("result") or []
    if not res:
        raise RuntimeError((data.get("chart") or {}).get("error") or "無資料")
    node = res[0]
    ts = node.get("timestamp") or []
    quote = ((node.get("indicators") or {}).get("quote") or [{}])[0]
    adj = ((node.get("indicators") or {}).get("adjclose") or [{}])[0]
    vals = adj.get("adjclose") or quote.get("close") or []
    if not ts or not vals:
        raise RuntimeError("chart 端點沒有收盤價")
    s = pd.Series(vals, index=pd.to_datetime(ts, unit="s"), dtype="float64")
    # 指數以當地時間報價，只取日期即可；同日多筆取最後一筆
    s.index = s.index.normalize()
    return s[~s.index.duplicated(keep="last")].dropna().sort_index()


def resolve_aliases(tickers: Iterable[str]) -> tuple[list[str], dict[str, list[str]]]:
    """把帶有候選代號的清單展開成 (實際要抓的代號, {正式代號: 候選清單})。"""
    out, alias = [], {}
    for t in tickers:
        cands = TICKER_ALIASES.get(t)
        if cands:
            alias[t] = list(cands)
            out.extend(c for c in cands if c not in out)
        elif t not in out:
            out.append(t)
    return out, alias


def pick_alias(close: pd.DataFrame,
               alias: dict[str, list[str]]) -> tuple[pd.DataFrame, dict[str, int]]:
    """每組候選代號取第一個有資料者，更名為正式代號，其餘候選欄位丟掉。

    同時回傳每組「選到第幾順位」，讓後續的 chart 端點只去補更高順位的代號 ——
    否則第一順位（真正的指數）永遠不會被重試，會被較低順位的代理搶走。
    """
    chosen: dict[str, int] = {}
    for canon, cands in alias.items():
        rank = next((i for i, c in enumerate(cands)
                     if c in close.columns and close[c].notna().any()), None)
        winner = cands[rank] if rank is not None else None
        # 必須先丟掉落選欄位再更名：否則把候選更名為正式代號會和原本那個
        # 空的同名欄撞名，接著的 drop 會把兩欄一起刪掉，資料又沒了。
        drop = [c for c in cands if c in close.columns and c != winner]
        if drop:
            close = close.drop(columns=drop)
        if winner is None:
            if canon not in close.columns:
                close[canon] = float("nan")
        else:
            chosen[canon] = rank
            if winner != canon:
                close = close.rename(columns={winner: canon})
    return close, chosen


def fill_missing_via_chart(close: pd.DataFrame, alias: dict[str, list[str]],
                           start: str,
                           chosen: dict[str, int] | None = None) -> pd.DataFrame:
    """用 chart 端點補抓 yfinance 漏掉的代號。

    yfinance 下載前會先查 quoteSummary 拿時區，那一步對某些指數會失敗，
    整欄於是安靜地變成空的。只要 chart 端點有資料就能救回來。

    `chosen` 是 pick_alias 選到的順位：只重試比它更前面的候選，
    這樣真正的指數才有機會蓋過備援的 ETF 代理。
    """
    chosen = chosen or {}
    for canon, cands in alias.items():
        rank = chosen.get(canon)
        retry = cands if rank is None else cands[:rank]
        if not retry:
            continue
        for c in retry:
            try:
                s = fetch_yahoo_chart(c, start=start)
            except Exception as e:
                print(f"  · chart 端點 {c} 失敗：{e}")
                continue
            if s.empty:
                continue
            # 台股交易日與美股不完全重疊，索引取聯集才不會把資料切掉
            close = close.reindex(close.index.union(s.index))
            close[canon] = s.reindex(close.index)
            print(f"  Yahoo：{canon} 由 chart 端點取得"
                  f"（代號 {c}，{len(s)} 筆，起自 {s.index[0].date()}）")
            break
        else:
            if rank is None:
                print(f"  ⚠ Yahoo：{canon} 的候選代號全部抓不到資料"
                      f"（試過 {'、'.join(cands)}）")
            elif rank > 0:
                print(f"  Yahoo：{canon} 改用代號 {cands[rank]}"
                      f"（較前順位皆無資料）")
    return close


def fetch_yahoo(tickers: Iterable[str], start: str = "2005-01-01",
                retries: int = 3) -> pd.DataFrame:
    """抓取 Yahoo 收盤價，回傳 DataFrame(index=日期, columns=ticker)。"""
    import yfinance as yf

    tickers, alias = resolve_aliases(tickers)
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            raw = yf.download(tickers, start=start, progress=False,
                              auto_adjust=True, group_by="column")
            if raw is None or len(raw) == 0:
                raise RuntimeError("Yahoo 回傳空資料")
            close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]]
            if isinstance(close, pd.Series):
                close = close.to_frame(tickers[0])
            close.columns = [str(c) for c in close.columns]
            close, chosen = pick_alias(close.sort_index(), alias)
            return fill_missing_via_chart(close, alias, start, chosen)
        except Exception as e:  # 網路波動時退避重試
            last_err = e
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"Yahoo 抓取失敗：{last_err}")


def normalize_yahoo_yield(s: pd.Series) -> pd.Series:
    """Yahoo 殖利率指數（^TNX 等）歷史上曾以 yield×10 報價（42.5 = 4.25%）。

    以中位數做健全性檢查：美債殖利率不可能長期在 20% 以上，
    若中位數 > 20 視為 ×10 報價並還原。
    """
    s = pd.to_numeric(s, errors="coerce")
    if s.dropna().empty:
        return s
    return s / 10.0 if s.median() > 20 else s


# ------------------------------------------------------------------------- FRED
def fetch_fred(codes: Iterable[str], retries: int = 3) -> pd.DataFrame:
    """從 FRED 的公開 CSV 端點抓資料 —— 不需要 API key。

    回傳 DataFrame(index=日期, columns=series code)。
    """
    import urllib.request

    out: dict[str, pd.Series] = {}
    for code in codes:
        last_err: Exception | None = None
        for attempt in range(retries):
            try:
                with urllib.request.urlopen(FRED_CSV.format(code=code), timeout=30) as r:
                    text = r.read().decode("utf-8")
                df = pd.read_csv(io.StringIO(text))
                # 欄名在新舊版本間為 observation_date 或 DATE
                date_col = df.columns[0]
                df[date_col] = pd.to_datetime(df[date_col])
                # FRED 以 "." 表示缺值
                val = pd.to_numeric(df[df.columns[1]].replace(".", pd.NA), errors="coerce")
                out[code] = pd.Series(val.values, index=df[date_col], name=code)
                break
            except Exception as e:
                last_err = e
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
        else:
            raise RuntimeError(f"FRED 抓取失敗 {code}：{last_err}")
    return pd.DataFrame(out).sort_index()


# ------------------------------------------------------------------- 組合成面板
def build_panel(yahoo_tickers: Iterable[str], fred_codes: Iterable[str],
                start: str = "2005-01-01") -> pd.DataFrame:
    """把兩個來源併成單一日頻面板（營業日、向前填補）。"""
    frames = []
    yahoo_tickers, fred_codes = list(yahoo_tickers), list(fred_codes)
    if yahoo_tickers:
        frames.append(fetch_yahoo(yahoo_tickers, start=start))
    if fred_codes:
        frames.append(fetch_fred(fred_codes).loc[start:])
    panel = pd.concat(frames, axis=1)
    panel = panel[~panel.index.duplicated(keep="last")].sort_index()
    panel, proj = split_projections(panel)
    # 每欄「真正的最後一筆觀測日」必須在向前填補之前記下來。
    # 之後面板裡每一欄都被填到最後一天，從面板本身再也看不出來誰其實停更了 ——
    # 資料健康檢查沒有這份紀錄就只會一律回報「今日更新」。
    last_obs = last_observations(panel)
    # 時間軸上界取「非前瞻序列的最後一筆」，避免被未來日期拉長
    end = panel.dropna(how="all").index.max() if len(panel) else None
    out = to_business_days(panel, end=end)
    _attach(out, "projections", proj)
    _attach(out, "last_obs", last_obs)
    return out


def last_observations(raw: pd.DataFrame) -> pd.Series:
    """每欄最後一筆真實觀測日（必須在向前填補之前呼叫）。"""
    if raw is None or raw.empty:
        return pd.Series(dtype="datetime64[ns]")
    d = {c: raw[c].last_valid_index() for c in raw.columns}
    d = {c: v for c, v in d.items() if v is not None}
    return pd.Series(d, dtype="datetime64[ns]").sort_index()


def last_obs_of(df: pd.DataFrame | None) -> pd.Series:
    """取出掛在面板 attrs 上的「最後觀測日」紀錄。"""
    if df is None:
        return pd.Series(dtype="datetime64[ns]")
    v = getattr(df, "attrs", {}).get("last_obs")
    if isinstance(v, pd.Series):
        return v
    if not isinstance(v, dict) or not v:
        return pd.Series(dtype="datetime64[ns]")
    return pd.Series({k: pd.Timestamp(d) for k, d in v.items()},
                     dtype="datetime64[ns]").sort_index()


def _combine_last_obs(older: pd.Series, newer: pd.Series) -> pd.Series:
    """逐欄取較晚的觀測日。"""
    if newer is None or not len(newer):
        return older if older is not None else pd.Series(dtype="datetime64[ns]")
    if older is None or not len(older):
        return newer
    idx = older.index.union(newer.index)
    a = pd.to_datetime(older.reindex(idx))
    b = pd.to_datetime(newer.reindex(idx))
    return b.where(a.isna() | (b.notna() & (b >= a)), a).sort_index()


def to_business_days(panel: pd.DataFrame,
                     end: pd.Timestamp | None = None) -> pd.DataFrame:
    """對齊到營業日並向前填補。

    必須先展開到「每日曆日」再取營業日 —— 不能直接 reindex 到營業日。
    週頻序列（例如初領失業金 IC4WSA）的日期標在星期六，
    直接 reindex 到營業日會把整欄資料丟光，且不會報錯，只會靜靜地全變 NaN。

    `end` 用來限制時間軸上界。不設限時，只要有任何一欄含未來日期
    （例如 FOMC 點陣圖），整個面板就會被拉到那個未來日期，
    其餘序列全部被向前填補成平線 —— 這個錯誤不會報錯，只會讓
    「近三個月變化」全部變成 0。
    """
    if panel.empty:
        return panel
    lo = panel.index.min()
    hi = end if end is not None else panel.index.max()
    hi = min(hi, panel.index.max())
    daily = panel.reindex(pd.date_range(lo, panel.index.max(), freq="D")).ffill()
    return daily.reindex(pd.bdate_range(lo, hi))


def split_projections(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """把前瞻性序列從日頻面板分離出來。"""
    cols = [c for c in panel.columns if c in PROJECTION_CODES]
    proj = panel[cols].dropna(how="all") if cols else pd.DataFrame()
    rest = panel.drop(columns=cols)
    return rest, proj


# --------------------------------------------------------------------- 快取
def projection_path(path: str) -> str:
    """前瞻性序列的存放位置：與面板同目錄，檔名加 .projections。"""
    import os
    base, ext = os.path.splitext(path)
    return f"{base}.projections{ext or '.csv'}"


def meta_path(path: str) -> str:
    """每欄最後觀測日的存放位置。"""
    import os
    base, ext = os.path.splitext(path)
    return f"{base}.lastobs{ext or '.csv'}"


def load_last_obs(path: str) -> pd.Series:
    import os
    if not os.path.exists(path):
        return pd.Series(dtype="datetime64[ns]")
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=["last_obs"])
        return pd.to_datetime(df["last_obs"]).sort_index()
    except Exception:
        return pd.Series(dtype="datetime64[ns]")


def drop_future(panel: pd.DataFrame,
                today: pd.Timestamp | None = None) -> pd.DataFrame:
    """丟掉今天之後的列。

    快取是逐日累積的，只要有一天不小心把未來日期寫進去，之後每次合併
    都會把它帶回來。因此讀取與合併時都要再過濾一次，而不是只在抓取時處理。
    """
    if panel is None or panel.empty:
        return panel
    t = pd.Timestamp(today).normalize() if today is not None \
        else pd.Timestamp.today().normalize()
    return panel.loc[panel.index <= t]


# attrs 只放「純量容器」（dict），不放 DataFrame／Series。
# pandas 在 concat 時會用 `==` 比較兩邊的 attrs，值是 DataFrame 的話那個比較會
# 直接拋 ValueError：面板任兩欄做 pd.concat 就會爆掉，而且錯誤訊息完全看不出
# 原因出在 attrs。因此進出 attrs 時一律轉換。
def _attach(df: pd.DataFrame, key: str, value) -> None:
    if value is None or not len(value):
        df.attrs.pop(key, None)
        return
    if key == "projections":
        df.attrs[key] = {c: {d.strftime("%Y-%m-%d"): float(v)
                             for d, v in value[c].dropna().items()}
                         for c in value.columns}
    else:
        df.attrs[key] = {k: pd.Timestamp(v).strftime("%Y-%m-%d")
                         for k, v in value.items() if not pd.isna(v)}


def projections_of(df: pd.DataFrame | None) -> pd.DataFrame:
    """取出掛在面板 attrs 上的前瞻性序列（沒有就回空表）。"""
    if df is None:
        return pd.DataFrame()
    p = getattr(df, "attrs", {}).get("projections")
    if isinstance(p, pd.DataFrame):
        return p
    if not isinstance(p, dict) or not p:
        return pd.DataFrame()
    cols = {c: pd.Series({pd.Timestamp(d): v for d, v in obs.items()})
            for c, obs in p.items() if obs}
    return pd.DataFrame(cols).sort_index() if cols else pd.DataFrame()


def compress_projections(proj: pd.DataFrame) -> pd.DataFrame:
    """折疊成「每個被預測年度一筆」，日期用年初 —— FRED 原始資料就是這個形狀。

    需要這一步是因為舊快取裡的前瞻序列已經被向前填補成每日一筆（783 筆）。
    若不折疊，這些偽造出來的日期會在每次合併時被保留下來，永遠留在檔案裡。
    折疊對乾淨的原始資料是無作用的（本來就一年一筆）。
    """
    if proj is None or not len(proj):
        return pd.DataFrame() if proj is None else proj
    by_year: dict[int, dict] = {}
    for col in proj.columns:
        for d, v in proj[col].dropna().items():
            by_year.setdefault(d.year, {})[col] = float(v)
    years = sorted(by_year)
    if not years:
        return proj.iloc[:0]
    out = pd.DataFrame([by_year[y] for y in years],
                       index=pd.to_datetime([f"{y}-01-01" for y in years]))
    return out.reindex(columns=list(proj.columns))


def _combine_proj(older: pd.DataFrame, newer: pd.DataFrame) -> pd.DataFrame:
    """合併兩份前瞻性序列，重疊處以 newer 為準。"""
    if newer is None or not len(newer):
        return compress_projections(older) if older is not None \
            else pd.DataFrame()
    if older is None or not len(older):
        return compress_projections(newer)
    return compress_projections(newer.combine_first(older).sort_index())


def load_projections(path: str) -> pd.DataFrame | None:
    import os
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
    except Exception:
        return None
    return df.sort_index() if len(df) else None


def load_cache(path: str) -> pd.DataFrame | None:
    """讀取先前存下的面板；不存在或毀損時回傳 None。

    舊版快取可能混入前瞻性序列與未來日期的列，讀進來時一併清掉，
    前瞻性序列改掛在 attrs["projections"]。
    """
    import os
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
    except Exception:
        return None
    if not len(df):
        return None
    df, inline = split_projections(df.sort_index())
    df = drop_future(df).dropna(how="all")
    if df.empty:
        return None
    stored = load_projections(projection_path(path))
    proj = _combine_proj(inline, stored if stored is not None
                         else pd.DataFrame())
    _attach(df, "projections", proj)
    lo = load_last_obs(meta_path(path))
    _attach(df, "last_obs", lo[lo.index.isin(df.columns)] if len(lo) else lo)
    return df


def save_cache(panel: pd.DataFrame, path: str,
               projections: pd.DataFrame | None = None,
               last_obs: pd.Series | None = None) -> None:
    import os
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    attached = projections_of(panel)
    attached_lo = last_obs_of(panel)
    panel, inline = split_projections(panel)
    panel.to_csv(path)
    proj = _combine_proj(_combine_proj(attached, inline),
                         projections if projections is not None
                         else pd.DataFrame())
    if len(proj):
        proj.to_csv(projection_path(path))
    lo = last_obs if last_obs is not None else attached_lo
    if lo is not None and len(lo):
        lo.rename("last_obs").to_frame().to_csv(meta_path(path))


def merge_panel(old: pd.DataFrame | None, new: pd.DataFrame) -> pd.DataFrame:
    """把新抓的資料併入舊快取：欄與列取聯集，重疊處以新資料為準。

    目的是讓排程即使某天抓取失敗或缺了幾檔，歷史也不會斷掉。
    前瞻性序列不參與列聯集（否則時間軸會被拉到未來），另外合併後掛回 attrs。
    """
    chunks = [projections_of(old)]
    lo_old, lo_new = last_obs_of(old), last_obs_of(new)
    p_attached_new = projections_of(new)
    new, p_new = split_projections(new)
    if old is not None and not old.empty:
        old, p_old = split_projections(old)
        chunks += [p_old, p_attached_new, p_new]
        merged = new.combine_first(old)
        merged = merged.reindex(
            columns=sorted(set(old.columns) | set(new.columns)))
    else:
        chunks += [p_attached_new, p_new]
        merged = new
    out = drop_future(merged.sort_index())
    proj = pd.DataFrame()
    for c in chunks:
        proj = _combine_proj(proj, c)
    _attach(out, "projections", proj)
    lo = _combine_last_obs(lo_old, lo_new)
    _attach(out, "last_obs", lo[lo.index.isin(out.columns)] if len(lo) else lo)
    return out
