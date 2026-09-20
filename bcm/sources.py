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


# 每個正式代號這次實際用了哪個來源。必須記下來並存進快取：
# 同一個欄位換了來源（指數 ~200 點 vs ETF ~46 元）卻沿用舊資料的話，
# 兩種尺度會被接在同一條序列上，算出來的變化率完全是垃圾，而且不會報錯。
ALIAS_SOURCE: dict[str, str] = {}

# 有權威原生來源的序列：優先用它，不必繞 Yahoo。
NATIVE_SOURCE = {}          # 在 fetch_tpex_index 定義後填入（見檔案下方）
NATIVE_NAME = {"^TWOII": "TPEx"}

CHART_HOSTS = ("query1.finance.yahoo.com", "query2.finance.yahoo.com")


def _chart_get(url: str, timeout: int) -> tuple[int, dict | None, dict]:
    """取一次 chart JSON，回傳 (HTTP 狀態碼, JSON, 回應標頭)。

    優先用 curl_cffi 並冒充 Chrome。這是關鍵：Yahoo 不只看 User-Agent，
    還看 TLS 指紋（JA3）。urllib 就算把 UA 字串設成 Chrome，握手層看起來
    仍然是 Python，會被回 429 —— 那是機器人偵測，不是真的流量超限，
    所以退避重試再久也沒用。curl_cffi 是 yfinance 自己的相依套件，
    本來就會裝，不必新增依賴。
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
        "Referer": "https://finance.yahoo.com/",
    }
    try:
        from curl_cffi import requests as creq
        r = creq.get(url, headers=headers, timeout=timeout,
                     impersonate="chrome")
        body = None
        if r.status_code == 200:
            import json as _json
            body = _json.loads(r.text)
        return r.status_code, body, dict(r.headers)
    except ImportError:
        pass

    import json
    import urllib.error
    import urllib.request
    try:
        with urllib.request.urlopen(
                urllib.request.Request(url, headers=headers),
                timeout=timeout) as r:
            return 200, json.loads(r.read().decode("utf-8")), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, None, dict(e.headers)


def fetch_yahoo_chart(symbol: str, start: str = "2005-01-01",
                      timeout: int = 20, retries: int = 4) -> pd.Series:
    """繞過 yfinance，直接打 Yahoo 的 chart 端點取收盤價。

    存在的理由：yfinance 下載前會先查 quoteSummary 拿時區，那一步對某些
    指數（例如櫃買 ^TWOII）會失敗，於是整欄變成空的 —— 但 chart 端點本身
    是有資料的。少了這條路就只能改用 ETF 代理，失去真正的指數。
    """
    import urllib.parse

    p1 = int(pd.Timestamp(start).timestamp())
    p2 = int(pd.Timestamp.today().normalize().timestamp()) + 86400
    path = (f"/v8/finance/chart/{urllib.parse.quote(symbol)}"
            f"?period1={p1}&period2={p2}&interval=1d")

    last: str = "未知"
    for attempt in range(retries):
        host = CHART_HOSTS[attempt % len(CHART_HOSTS)]
        code, body, hdrs = _chart_get(f"https://{host}{path}", timeout)
        if code == 200 and body is not None:
            return _parse_chart(body)
        last = f"HTTP {code}"
        if code == 404:
            raise RuntimeError(f"{symbol} 查無此標的（HTTP 404）")
        if attempt == retries - 1:
            break
        wait = 2 ** attempt
        if code == 429:
            wait = float(hdrs.get("Retry-After") or 0) or 3 * (attempt + 1)
        time.sleep(min(wait, 20))
    raise RuntimeError(f"chart 端點重試 {retries} 次仍失敗：{last}")


def _parse_chart(data: dict) -> pd.Series:
    res = (data.get("chart") or {}).get("result") or []
    if not res:
        raise RuntimeError((data.get("chart") or {}).get("error") or "無資料")
    node = res[0]
    ts = node.get("timestamp") or []
    ind = node.get("indicators") or {}
    quote = (ind.get("quote") or [{}])[0]
    adj = (ind.get("adjclose") or [{}])[0]
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


# ------------------------------------------------------------ 櫃買中心（TPEx）
# Yahoo Finance 的報價 API 沒有收錄櫃買指數：把 TLS 指紋偽裝處理掉之後，
# 它對 ^TWOII 回的是明確的 HTTP 404，不再是機器人偵測的 429。
# （使用者看到的 tw.stock.yahoo.com 是 Yahoo 奇摩股市，和 finance.yahoo.com
#  的報價 API 是兩套不同的東西。）
# 正確的來源是櫃買中心自己：權威、不限流、不需要偽裝。
#
# 站方在 2024 年改版過，新舊端點並存且文件不齊，因此列出多個候選格式
# 一一嘗試，並把實際成功的那個印出來。抓不到時退回 ETF 代理。
TPEX_ENDPOINTS = [
    # 新版（改版後）：單日全部指數
    ("tpex-www-dailyIndex",
     "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyIndex"
     "?date={ymd}&response=json"),
    # OpenAPI：櫃買指數（資料集名稱由站方 swagger 目錄確認）
    ("tpex-openapi-index",
     "https://www.tpex.org.tw/openapi/v1/tpex_index"),
    # 舊版：整月每日指數（民國年/月）
    ("tpex-st42",
     "https://www.tpex.org.tw/web/stock/aftertrading/daily_index/"
     "st42_result.php?l=zh-tw&d={roc}&o=json"),
]


def _http_json(url: str, timeout: int = 20) -> tuple[int, object | None, str]:
    """取一次 JSON，回傳 (狀態碼, 解析後物件或 None, 前 200 字原文)。

    原文一起回傳是刻意的：端點格式沒有文件時，看得到回應長什麼樣子
    才有辦法決定下一步，否則只能盲猜。
    """
    import json
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json,text/plain,*/*",
    }
    try:
        from curl_cffi import requests as creq
        r = creq.get(url, headers=headers, timeout=timeout,
                     impersonate="chrome")
        text, code = r.text, r.status_code
    except Exception as e:
        return 0, None, f"{type(e).__name__}: {e}"[:200]
    try:
        return code, json.loads(text), text[:200]
    except Exception:
        return code, None, text[:200]


def _tpex_rows(obj) -> list:
    """把 TPEx 幾種回應格式攤平成資料列。"""
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        for k in ("aaData", "tables", "data", "result"):
            v = obj.get(k)
            if isinstance(v, list) and v:
                if k == "tables" and isinstance(v[0], dict):
                    return v[0].get("data") or []
                return v
    return []


# OpenAPI 目錄：候選端點全部猜錯時，改用站方自己的 swagger 清單找出
# 正確的資料集名稱。硬猜網址的問題是失敗了也學不到東西；讀目錄至少能
# 把「站方到底提供哪些資料集」印出來，下一步才有依據。
TPEX_CATALOGS = [
    "https://www.tpex.org.tw/openapi/swagger.json",
    "https://www.tpex.org.tw/openapi/v1/swagger.json",
    "https://www.tpex.org.tw/openapi/swagger/v1/swagger.json",
]


def discover_tpex_index_paths() -> list[str]:
    """從 OpenAPI 目錄找出可能是「指數」的資料集完整網址。

    一定要把目錄宣告的 basePath／servers 接回去。第一版直接用
    "https://www.tpex.org.tw/openapi" + "/tpex_index"，漏掉了 /v1，
    結果 21 個候選全部打到站方的 404 頁 —— 目錄讀對了，網址卻組錯。
    """
    for cat in TPEX_CATALOGS:
        code, obj, peek = _http_json(cat)
        if not isinstance(obj, dict):
            print(f"  · TPEx 目錄 {cat} 讀不到（HTTP {code}）：{peek[:80]}")
            continue
        paths = obj.get("paths")
        if not isinstance(paths, dict):
            continue
        base = obj.get("basePath")                      # Swagger 2.0
        if not base:                                    # OpenAPI 3
            servers = obj.get("servers") or []
            base = servers[0].get("url") if servers else None
        base = (base or "/openapi/v1").rstrip("/")
        if base.startswith("http"):
            root = base
        else:
            root = "https://www.tpex.org.tw" + (
                base if base.startswith("/") else "/" + base)
        hits = [p for p in paths
                if "index" in p.lower() or "指數" in str(paths[p])]
        # 名稱剛好是「櫃買指數」的排前面，避免先去試成分股、報酬指數
        hits.sort(key=lambda p: (p.strip("/") != "tpex_index", len(p)))
        print(f"  TPEx 目錄共 {len(paths)} 個資料集（base={base}），"
              f"疑似指數的有 {len(hits)} 個：{hits[:6]}")
        return [root + (p if p.startswith("/") else "/" + p) for p in hits]
    return []


def fetch_tpex_index(start: str = "2005-01-01") -> pd.Series:
    """從櫃買中心取櫃買指數收盤。先試已知端點，失敗則查 OpenAPI 目錄。"""
    today = pd.Timestamp.today().normalize()
    roc = f"{today.year - 1911}/{today.month:02d}"
    tried = [(n, t.format(ymd=today.strftime("%Y%m%d"), roc=roc))
             for n, t in TPEX_ENDPOINTS]

    def attempt(name: str, url: str) -> pd.Series | None:
        code, obj, peek = _http_json(url)
        rows = _tpex_rows(obj) if obj is not None else []
        if not rows:
            print(f"  · TPEx {name} 無法使用（HTTP {code}）：{peek[:110]}")
            return None
        out = _parse_tpex(rows)
        if out is None or out.empty:
            print(f"  · TPEx {name} 格式無法解析：{str(rows[0])[:110]}")
            return None
        return out

    for name, url in tried:
        got = attempt(name, url)
        if got is not None:
            print(f"  TPEx：櫃買指數取自 {name}（{len(got)} 筆）")
            return got.loc[start:]

    for url in discover_tpex_index_paths():
        got = attempt(url.rsplit("/", 1)[-1], url)
        if got is not None:
            print(f"  TPEx：櫃買指數取自 {url}（{len(got)} 筆）")
            return got.loc[start:]

    raise RuntimeError("櫃買中心所有候選端點都取不到指數")


def _parse_tpex(rows: list) -> pd.Series | None:
    """從資料列裡找出（日期, 收盤指數）。

    TPEx 的欄位名稱與順序在改版前後不一致，因此用「找得到日期就用」的
    寬鬆解法，而不是寫死欄位位置 —— 寫死一改版就靜靜地壞掉。
    """
    out: dict[pd.Timestamp, float] = {}
    for row in rows:
        vals = list(row.values()) if isinstance(row, dict) else list(row)
        d = v = None
        for x in vals:
            if not isinstance(x, str):
                continue
            t = x.strip()
            if d is None:
                d = _tpex_date(t)
                if d is not None:
                    continue
            if v is None and d is not None:
                try:
                    v = float(t.replace(",", ""))
                except ValueError:
                    pass
        if d is not None and v is not None:
            out[d] = v
    if not out:
        return None
    return pd.Series(out).sort_index()


def _tpex_date(t: str) -> pd.Timestamp | None:
    """接受民國年（115/09/19）與西元年（2026-09-19、20260919）。"""
    import re
    if re.fullmatch(r"\d{2,3}/\d{1,2}/\d{1,2}", t):
        y, m, d = t.split("/")
        try:
            return pd.Timestamp(int(y) + 1911, int(m), int(d))
        except ValueError:
            return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return pd.Timestamp(pd.to_datetime(t, format=fmt))
        except Exception:
            continue
    return None


NATIVE_SOURCE["^TWOII"] = fetch_tpex_index


def prefetch_aliases(alias: dict[str, list[str]], start: str,
                     retries: int = 2) -> dict[str, pd.Series]:
    """在大批下載之前，先用 chart 端點取第一順位代號。

    重試次數刻意壓低：GitHub Actions 的出口 IP 被 Yahoo 限流得很兇，
    真的被擋時多試幾次也救不回來，只是讓每天的排程白等幾十秒。
    """
    out: dict[str, tuple[pd.Series, str]] = {}
    for canon, cands in alias.items():
        if not cands:
            continue
        native = NATIVE_SOURCE.get(canon)
        if native is not None:
            try:
                s = native(start)
            except Exception as e:
                print(f"  · {canon} 原生來源失敗：{e}")
            else:
                if not s.empty:
                    name = NATIVE_NAME.get(canon, canon)
                    out[canon] = (s, name)
                    ALIAS_SOURCE[canon] = name
                    print(f"  {canon} 取自原生來源（{len(s)} 筆，"
                          f"起自 {s.index[0].date()}）")
                    continue
        try:
            s = fetch_yahoo_chart(cands[0], start=start, retries=retries)
        except Exception as e:
            print(f"  · 預抓 {cands[0]} 失敗：{e}")
            continue
        if not s.empty:
            out[canon] = (s, cands[0])
            ALIAS_SOURCE[canon] = cands[0]
            print(f"  Yahoo：{canon} 預抓成功（{len(s)} 筆，"
                  f"起自 {s.index[0].date()}）")
    return out


def apply_prefetched(close: pd.DataFrame,
                     pre: dict[str, tuple[pd.Series, str]]) -> pd.DataFrame:
    """把預抓到的序列寫回面板，覆蓋批次下載可能取到的備援代理。

    來源標記也要一起蓋回去。pick_alias 在這之後才跑，它看到 yfinance
    抓到了較低順位的代理就會把 ALIAS_SOURCE 改寫成代理的代號 ——
    於是「值來自櫃買中心、標記寫著 ETF」，merge_panel 的來源變更防護
    比對標記後認為沒換來源，就把兩種尺度的資料接在同一欄裡
    （ETF 約 44 元接上指數約 402 點），而且完全不會報錯。
    """
    for canon, (s, src) in pre.items():
        close = close.reindex(close.index.union(s.index))
        close[canon] = s.reindex(close.index)
        ALIAS_SOURCE[canon] = src
    return close


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
            ALIAS_SOURCE[canon] = winner
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
            ALIAS_SOURCE[canon] = c
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

    # 先打 chart 端點，再做 yfinance 的大批下載。
    # 順序是關鍵：Yahoo 的限流是我們自己觸發的 —— 前一版把 chart 放在批次
    # 下載之後，結果 4 次重試全部 429。第一順位（真正的指數）值得用
    # 還沒被用掉的配額去換。
    pre = prefetch_aliases(alias, start)

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
            close = apply_prefetched(close, pre)
            # 預抓已經試過第一順位了，這裡只補「預抓沒碰過」的候選，
            # 不要把剛剛被 429 擋掉的代號再重試一輪浪費時間
            rest = {k: v[1:] for k, v in alias.items()
                    if k not in pre and len(v) > 1}
            close = fill_missing_via_chart(close, rest, start,
                                           {k: r - 1 for k, r in chosen.items()
                                            if r})
            close.attrs["alias_source"] = dict(ALIAS_SOURCE)
            return close
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
    src = {k: v for f in frames for k, v in
           getattr(f, "attrs", {}).get("alias_source", {}).items()}
    if src:
        out.attrs["alias_source"] = src
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


def load_meta(path: str) -> tuple[pd.Series, dict[str, str]]:
    """讀回 (每欄最後觀測日, {正式代號: 實際來源代號})。"""
    import os
    empty = pd.Series(dtype="datetime64[ns]")
    if not os.path.exists(path):
        return empty, {}
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=["last_obs"])
    except Exception:
        return empty, {}
    src = {}
    if "source" in df.columns:
        src = {k: v for k, v in df["source"].dropna().items() if v}
    return pd.to_datetime(df["last_obs"]).sort_index(), src


def load_last_obs(path: str) -> pd.Series:
    return load_meta(path)[0]


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
    lo, src = load_meta(meta_path(path))
    _attach(df, "last_obs", lo[lo.index.isin(df.columns)] if len(lo) else lo)
    if src:
        df.attrs["alias_source"] = src
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
    alias_src = dict(getattr(panel, "attrs", {}).get("alias_source") or {})
    panel, inline = split_projections(panel)
    panel.to_csv(path)
    proj = _combine_proj(_combine_proj(attached, inline),
                         projections if projections is not None
                         else pd.DataFrame())
    if len(proj):
        proj.to_csv(projection_path(path))
    lo = last_obs if last_obs is not None else attached_lo
    if lo is not None and len(lo):
        meta = lo.rename("last_obs").to_frame()
        src = alias_src
        if src:
            meta["source"] = pd.Series(src)
        meta.to_csv(meta_path(path))


def merge_panel(old: pd.DataFrame | None, new: pd.DataFrame) -> pd.DataFrame:
    """把新抓的資料併入舊快取：欄與列取聯集，重疊處以新資料為準。

    目的是讓排程即使某天抓取失敗或缺了幾檔，歷史也不會斷掉。
    前瞻性序列不參與列聯集（否則時間軸會被拉到未來），另外合併後掛回 attrs。
    """
    chunks = [projections_of(old)]
    lo_old, lo_new = last_obs_of(old), last_obs_of(new)
    src_old = dict(getattr(old, "attrs", {}).get("alias_source") or {})
    src_new = dict(getattr(new, "attrs", {}).get("alias_source") or {})
    p_attached_new = projections_of(new)
    new, p_new = split_projections(new)
    if old is not None and not old.empty:
        old, p_old = split_projections(old)
        # 來源換了就把舊欄位整欄丟掉，不要接在一起。
        # 櫃買指數約 200 點、代理 ETF 約 46 元，混在同一欄算出的變化率
        # 是純粹的垃圾，而且不會報錯 —— 只會看起來像市場崩了。
        switched = [c for c, v in src_new.items()
                    if c in old.columns and src_old.get(c, v) != v]
        for c in switched:
            print(f"  來源變更：{c} 由 {src_old[c]} 改為 {src_new[c]}，"
                  f"捨棄舊快取欄位")
        if switched:
            old = old.drop(columns=switched)
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
    merged_src = {**src_old, **src_new}
    if merged_src:
        out.attrs["alias_source"] = merged_src
    return out
