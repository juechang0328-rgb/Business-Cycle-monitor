# Business Cycle Monitor

美國總經指標的每日儀表板。GitHub Actions 每天台北時間早上 7:00 抓取
FRED／Yahoo／櫃買中心的資料，產生單一靜態頁面並部署到 GitHub Pages。

## 先讀這個

**[WORKFLOW.md](WORKFLOW.md) 是這個專案的協作規範，動手之前請先讀完。**
其中「開工前先講計畫」與「撞牆就停，不要硬試」兩節請務必遵守。

## 專案結構

| 路徑 | 用途 |
|---|---|
| `run.py` | 進入點：抓取 → 組面板 → 產生 HTML |
| `bcm/sources.py` | 資料抓取與快取。**本專案大部分的坑都在這裡** |
| `bcm/indicators.py` | 指標設定（抓哪些、分幾區、怎麼呈現） |
| `bcm/derived.py` | 衍生序列（比值、淨流動性等），單位換算集中在此 |
| `bcm/macro_dash.py` | 儀表板渲染 |
| `bcm/health.py` | 資料健康檢查 |
| `bcm/glossary.py` | 每個指標的定義、來源、判讀方式 |
| `validate.py` / `backtest.py` | 景氣階段模型的檢驗工具（結論：無預測力） |

## 資料的兩種類別

- **可重建**：`data/panel.csv.gz` 與其 sidecar。隨時能從 FRED／Yahoo
  重抓，因此不進版控，改由 Actions cache 保存。
- **不可重建**：`data/twoii_history.csv`。櫃買中心的 API 只提供當月，
  今天沒存下來明天就補不回來。這一份**必須**留在版控裡。

## 常用指令

```bash
python -m pytest -q                                   # 109 項測試
python run.py --profile macro --offline \
  --cache data/panel.csv.gz --macro out.html          # 離線產生頁面
python validate.py --cache data/panel.csv.gz          # 檢驗模型是否有訊息量
```

## 已知限制

- 景氣階段模型**經實測沒有預測力**（方向命中率 ≈50%），因此原本的
  景氣循環頁已移除，只保留描述性的總經儀表板。檢驗工具保留在
  `validate.py`／`backtest.py`，結論不要重新包裝成「有訊號」。
- 儀表板只描述已經發生的事，不預測。測試會擋下預測性用語。
