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


# --------------------------------------------------------------------- yfinance
def fetch_yahoo(tickers: Iterable[str], start: str = "2005-01-01",
                retries: int = 3) -> pd.DataFrame:
    """抓取 Yahoo 收盤價，回傳 DataFrame(index=日期, columns=ticker)。"""
    import yfinance as yf

    tickers = list(tickers)
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
            return close.sort_index()
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
    idx = pd.bdate_range(panel.index.min(), panel.index.max())
    return panel.reindex(idx).ffill()
