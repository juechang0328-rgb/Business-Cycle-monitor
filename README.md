# Business Cycle Monitor

以**日頻、免費、免 API key** 的市場資料定位景氣循環六階段，並產生可隨時開啟的 HTML 儀表板。

## 用法一：GitHub Actions 自動更新（推薦，不必在本機跑）

每個交易日收盤後自動抓資料、重算階段、把儀表板發佈成網頁。
設定完成後你只要開同一個網址就能隨時看最新狀態。

**一次性設定**（在 GitHub 網頁上操作）：

1. 進 repo → **Settings** → **Pages** → Source 選 **GitHub Actions**
2. 進 **Actions** 分頁，若提示啟用工作流程就按啟用
3. 進 **Actions** → 選「景氣循環儀表板」→ **Run workflow** 手動跑第一次

跑完後網址是 `https://<你的帳號>.github.io/Business-Cycle-monitor/`。
之後每週一至週五 22:00 UTC（美股收盤後約兩小時）自動更新。

排程定義在 [`.github/workflows/dashboard.yml`](.github/workflows/dashboard.yml)，
要改時間就改裡面的 `cron`。

## 用法二：在本機跑

```bash
pip install -r requirements.txt

python run.py --html          # 判定當前階段 + 產生 dashboard.html
open dashboard.html           # macOS（Windows 用 start、Linux 用 xdg-open）
```

想先看版面而不連網：

```bash
python run.py --demo --html   # 用合成資料預覽（頁面會標示為示範資料）
```

## 資料快取

加上 `--cache` 會把抓到的資料存成 `data/panel.csv`，下次執行時併入更新：

```bash
python run.py --html --cache data/panel.csv
```

好處是**抓取失敗那天不會開天窗** —— 程式會沿用快取並在畫面上標示資料已過期幾天。
排程工作流程預設就有開快取，並把 `data/panel.csv` 寫回 repo，
所以歷史會一天天累積起來，不依賴單次抓取成功。

## 儀表板內容

| 區塊 | 內容 |
|---|---|
| 目前判定 | 階段編號與名稱、債券／股票／原物料三個箭頭、成長與通膨分數 |
| 六階段條 | 標示目前位置 |
| 景氣時鐘 | x=通膨分數、y=成長分數，近三年軌跡依當時階段著色 |
| 分數走勢 | G 與 I 的時間序列，背景色塊標示當時階段 |
| 成分 z-score | 每個指標對兩個軸的貢獻與權重 |
| 市場儀表板 | 各標的最新值與三個月變化 |
| 近期換檔紀錄 | 何時進入哪個階段、持續多久 |

單一自足 HTML，不依賴 CDN，可離線開啟，支援深色模式與手機版面。

## MVP 指標組合

只用 6 個 Yahoo ticker + 5 個 FRED 序列：

**yfinance（價格）**　`^GSPC` 標普500、`GC=F` 黃金、`HG=F` 銅、`CL=F` 原油、`XLI`／`XLU` 工業與公用事業

**FRED（利率，免 API key）**　`DGS2`／`DGS5`／`DGS10` 2/5/10年期殖利率、`T10Y2Y` 期限利差、`T10YIE` 通膨預期

| 軸 | 成分 | 權重 |
|---|---|---|
| 成長 G | 銅金比 / 循環股·防禦股 / 股市動能 / 殖利率曲線 | 30·25·25·20% |
| 通膨 I | 銅 / 原油 / 通膨預期 / 黃金 | 30·30·25·15% |

要擴充成含信用利差、類股輪動、VIX、美元的完整組合，把 `bcm/indicators.py`
的 `PROFILE` 改成 `"full"` 即可。

## 判定邏輯

| 階段 | 名稱 | 債券 | 股票 | 原物料 | 條件 |
|---|---|:--:|:--:|:--:|---|
| 1 | 景氣衰退 | ↑ | ↓ | ↓ | G<0、動能<0、通膨已落 |
| 2 | 景氣谷底 | ↑ | ↑ | ↓ | G<0 但**動能轉正** |
| 3 | 景氣復甦 | ↑ | ↑ | ↑ | G≥0 上升、通膨仍低 |
| 4 | 景氣擴張 | ↓ | ↑ | ↑ | G≥0 上升、通膨已起 |
| 5 | 景氣高峰 | ↓ | ↓ | ↑ | G 高但**動能轉負** |
| 6 | 景氣趨緩 | ↓ | ↓ | ↓ | G<0 下降、通膨仍高 |

兩個分界值得記住：

- **階段 4 vs 5** 的差別不是經濟好不好（兩段都好），而是**成長率還在不在加速**
- **階段 6 vs 1** 的差別是**通膨落了沒** —— 那決定債券箭頭何時翻正

換檔需連續 10 個交易日成立，避免分數在 0 附近來回跳動。儀表板會在
「原始判定已轉向但尚未確認」時顯示轉折觀察提示。

## 常用參數

```bash
python run.py --years 5          # 儀表板顯示近 5 年（預設 3）
python run.py --start 2010-01-01 # 拉長 z-score 基準期（預設 2015）
python run.py --confirm 15       # 提高換檔門檻，訊號更穩但更慢
python run.py --csv out.csv      # 匯出完整時間序列
```

## 專案結構

```
.github/workflows/
  dashboard.yml   每日排程：抓資料 → 跑測試 → 產生儀表板 → 發佈 GitHub Pages
bcm/
  sources.py      資料抓取（yfinance + FRED，含重試、快取合併與單位正規化）
  indicators.py   指標設定：ticker、軸別、權重  ← 要調整就改這裡
  scoring.py      動能 → z-score → 加權合成（純函數）
  stages.py       六階段判定與遲滯（純函數）
  dashboard.py    HTML 儀表板（手刻 SVG，無外部相依）
run.py            CLI
tests/            22 項測試，含合成完整循環的端到端驗證
```

## 文件

| 檔案 | 說明 |
|---|---|
| [`docs/01-景氣循環監測指標研究.md`](docs/01-景氣循環監測指標研究.md) | 完整研究：四層指標架構、月頻與台灣指標、各階段 signature、假訊號防呆 |
| [`docs/02-日頻資料源與ticker對照.md`](docs/02-日頻資料源與ticker對照.md) | 資料源選擇：為何殖利率走 FRED 而非 Yahoo |
| [`config/indicators.yml`](config/indicators.yml) | 完整指標目錄（含月頻與台灣官方指標），供後續擴充 |

## 限制

- 市場資料是**對景氣的預期**，不是景氣本身 —— 反應快，但會有假訊號
  （例如純流動性驅動的反彈）。要提高可靠度，下一步加初領失業金
  （週頻、FRED `IC4WSA`）CP 值最高。
- 權重是先驗設定，**未經回測最佳化**。
- 期貨為連續合約，轉倉時有跳空；影響已由三個月動能取 z-score 稀釋。
- Yahoo 偶爾會對資料中心 IP（包含 GitHub Actions runner）限流，
  排程可能某天抓不到。快取機制就是為此設計的 —— 那天會沿用前一日資料並標示過期，
  不會讓歷史斷掉。FRED 沒有這個問題。
