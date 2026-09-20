"""指標詞條：定義、公式、資料來源、怎麼看。

每張卡片都可展開對應詞條。寫在這裡而不是散在各處，
是為了讓「這個數字怎麼來的」永遠只有一個答案。
"""
from __future__ import annotations

# key = 面板欄位代碼
META: dict[str, dict[str, str]] = {
    # ------------------------------------------------------------ 景氣動能
    "INDPRO": dict(
        full="工業生產指數 Industrial Production Index",
        src="FRED · INDPRO（Fed 理事會編製，1919 年起）",
        formula="年增率 =（本月指數 ÷ 一年前指數 − 1）× 100",
        what="衡量製造業、礦業、公用事業的實際產出量，不受物價影響。",
        how="這是「景氣本身」而非對景氣的預期。年增轉負通常代表實質衰退已在發生。"),
    "PAYEMS": dict(
        full="非農業就業人數 All Employees, Total Nonfarm",
        src="FRED · PAYEMS（勞工統計局 BLS，月頻）",
        formula="3個月年化 =（本月 ÷ 3個月前）^4 − 1",
        what="扣除農業部門的受僱總人數，是最受市場關注的就業數據。",
        how="就業屬同時至落後指標。3個月年化可濾掉單月雜訊，看趨勢比看單月準。"),
    "IC4WSA": dict(
        full="初次申請失業救濟金 4 週移動平均",
        src="FRED · IC4WSA（勞工部，週頻，觀測日為週六）",
        formula="過去 4 週初領件數的移動平均（季調後）",
        what="企業裁員的最早訊號，頻率高、公布快。",
        how="領先指標。由低點明顯回升常領先景氣轉弱數月。注意它的觀測日在週六。"),
    "SAHMREALTIME": dict(
        full="Sahm Rule 即時衰退指標",
        src="FRED · SAHMREALTIME（由 Claudia Sahm 提出）",
        formula="3個月移動平均失業率 − 前 12 個月該移動平均的最低值",
        what="用失業率的相對上升幅度判斷衰退是否已經開始。",
        how="≥0.50 歷史上幾乎必然對應衰退。但它是<b>落後</b>指標 —— 觸發時股市常已跌一段。"),
    "PERMIT": dict(
        full="新建住宅建照核發數 New Private Housing Units Authorized",
        src="FRED · PERMIT（人口普查局，月頻，1960 年起）",
        formula="年增率 =（本月 ÷ 一年前 − 1）× 100",
        what="房屋開工前的法定許可數量，年化千戶。",
        how="對利率最敏感的部門，歷史上最可靠的單一領先指標之一。"),
    "COPPER_GOLD": dict(
        full="銅金比 Copper / Gold Ratio",
        src="Yahoo Finance · HG=F ÷ GC=F（均為 COMEX 期貨）",
        formula="（銅價 ÷ 金價）× 1000",
        what="工業需求（銅）相對避險需求（金）的強弱。",
        how="走升＝實體需求增溫、風險偏好上升；與 10 年期美債殖利率高度正相關。"),
    "OIL_GOLD": dict(
        full="油金比 Oil / Gold Ratio",
        src="Yahoo Finance · CL=F ÷ GC=F（WTI 原油與 COMEX 黃金）",
        formula="（WTI 油價 ÷ 金價）× 1000",
        what="能源需求相對避險需求的強弱，也常被視為通膨壓力的代理。",
        how="走升多見於景氣擴張末段或供給衝擊；走跌常伴隨需求轉弱或避險升溫。"
             "與銅金比同向時訊號較可信，背離時通常是供給面因素在主導。"),

    # ------------------------------------------------------------ 通膨與利率
    "PCEPILFE": dict(
        full="核心個人消費支出物價指數 Core PCE Price Index",
        src="FRED · PCEPILFE（經濟分析局 BEA，月頻）",
        formula="年增率 =（本月 ÷ 一年前 − 1）× 100",
        what="扣除食品與能源的 PCE 物價，<b>Fed 的法定通膨目標所依據的指標</b>。",
        how="Fed 目標為 2%。它的權重會隨消費行為調整，因此通常低於核心 CPI。"),
    "CPILFESL": dict(
        full="核心消費者物價指數 Core CPI",
        src="FRED · CPILFESL（勞工統計局 BLS，月頻）",
        formula="年增率 =（本月 ÷ 一年前 − 1）× 100",
        what="扣除食品與能源的消費者物價。權重固定，住房佔比高。",
        how="住房分項有明顯遞延，因此核心 CPI 通常比實際租金走勢晚 6-12 個月反映。"),
    "DFII10": dict(
        full="10 年期抗通膨公債殖利率（實質利率）",
        src="FRED · DFII10（TIPS 市場報價，日頻）",
        formula="直接取市場報價。亦約等於 DGS10 − T10YIE。",
        what="扣除通膨預期後的無風險借貸成本，全球風險資產的定價之錨。",
        how="快速走升會壓縮高估值成長股的本益比。看方向比看絕對值重要。"),
    "T10YIE": dict(
        full="10 年期損益兩平通膨率 Breakeven Inflation Rate",
        src="FRED · T10YIE（由名目公債與 TIPS 殖利率推算）",
        formula="10 年期名目殖利率 − 10 年期 TIPS 殖利率",
        what="債市對未來 10 年平均通膨的定價。",
        how="市場的通膨預期，通常領先實際 CPI。含有流動性與風險溢酬，非純預期。"),
    "DGS10": dict(
        full="10 年期美國公債殖利率",
        src="FRED · DGS10（財政部固定到期日殖利率，日頻）",
        formula="直接取市場報價",
        what="全球長期資金成本的基準。",
        how="受成長預期、通膨預期、期限溢酬三者影響，單看數值難以歸因。"),
    "DGS2": dict(
        full="2 年期美國公債殖利率",
        src="FRED · DGS2（財政部固定到期日殖利率，日頻）",
        formula="直接取市場報價",
        what="最貼近市場對未來兩年<b>政策利率路徑</b>的定價。",
        how="Fed 轉向的預期會先反映在 2 年期上，通常快於 10 年期。"),

    # ------------------------------------------------------------ 央行流動性
    "NET_LIQ": dict(
        full="Fed 淨流動性 Net Liquidity",
        src="FRED · WALCL、WTREGEN、RRPONTSYD",
        formula="WALCL − WTREGEN − RRPONTSYD×1000　"
                "（前兩者以百萬美元計、RRPONTSYD 以十億計，故需換算）",
        what="Fed 資產負債表扣掉被財政部帳戶與逆回購「鎖住」的部分，"
             "約略代表實際留在銀行體系的流動性。",
        how="這是市場常用的近似值，<b>非官方定義</b>。擴張時常伴隨風險資產上漲，"
             "但因果關係有爭議，不應視為訊號。"),
    "WALCL": dict(
        full="Fed 總資產（週三水準）",
        src="FRED · WALCL（每週三公布，單位：百萬美元）",
        formula="直接取值",
        what="聯準會持有的公債、MBS 等資產總額。",
        how="縮表時緩步下降。單看它不等於流動性，須扣除 TGA 與逆回購。"),
    "WTREGEN": dict(
        full="財政部一般帳戶 TGA 餘額",
        src="FRED · WTREGEN（週平均，單位：百萬美元）",
        formula="直接取值",
        what="美國財政部存在 Fed 的活期帳戶，等同政府的支票帳戶。",
        how="TGA 上升＝資金從民間流入政府帳戶＝抽離銀行體系流動性，反之亦然。"),
    "RRPONTSYD": dict(
        full="隔夜逆回購 ON RRP 餘額",
        src="FRED · RRPONTSYD（日頻，<b>單位：十億美元</b>）",
        formula="直接取值",
        what="貨幣市場基金等機構把閒錢存放在 Fed 的工具。",
        how="餘額上升＝資金停泊在 Fed、未進入市場。注意它的單位與 WALCL 不同。"),
    "DTWEXBGS": dict(
        full="名目廣義貿易加權美元指數",
        src="FRED · DTWEXBGS（Fed 編製，2006 年 1 月＝100）",
        formula="對主要貿易夥伴貨幣的幾何加權平均",
        what="比 DXY 更能代表美元的實際貿易權重（DXY 歐元佔 57%）。",
        how="美元走強＝全球美元流動性緊縮，壓抑新興市場與以美元計價的原物料。"),

    # ------------------------------------------------------------ 金融壓力
    "T10Y2Y": dict(
        full="殖利率曲線 10 年期減 2 年期",
        src="FRED · T10Y2Y（日頻，單位：百分點）",
        formula="10 年期殖利率 − 2 年期殖利率",
        what="長短天期利差，負值稱為「倒掛」。",
        how="倒掛到衰退平均落後 12-18 個月，倒掛當下不是賣出訊號。"
             "真正的警訊是<b>倒掛解除後的牛市陡峭化</b> —— 短端因降息預期急跌。"),
    "T10Y3M": dict(
        full="殖利率曲線 10 年期減 3 個月",
        src="FRED · T10Y3M（日頻，單位：百分點）",
        formula="10 年期殖利率 − 3 個月期國庫券殖利率",
        what="學術研究中預測衰退能力最強的期限組合。",
        how="比 10Y-2Y 更貼近當前政策利率，倒掛訊號通常較晚出現但較準。"),
    "BAMLH0A0HYM2": dict(
        full="ICE BofA 美國高收益債選擇權調整利差 HY OAS",
        src="FRED · BAMLH0A0HYM2（日頻，<b>單位：百分點</b>，3.20＝320bp）",
        formula="高收益債殖利率 − 對應期限公債殖利率（已調整提前償還選擇權）",
        what="市場對非投資等級企業違約風險的定價。",
        how="&lt;300bp 市場高度樂觀、300-450bp 常態、&gt;500bp 融資緊縮。"
             "突然跳升往往早於股市大跌。"),
    "NFCI": dict(
        full="芝加哥 Fed 全國金融條件指數",
        src="FRED · NFCI（週頻，105 項指標合成）",
        formula="標準化後的加權合成，長期平均＝0",
        what="綜合貨幣、債券、股票市場與銀行體系的鬆緊程度。",
        how="&gt;0 代表金融條件緊於歷史平均，&lt;0 代表寬鬆。"),

    # ------------------------------------------------------------ 原物料
    "CL=F": dict(
        full="西德州中級原油 WTI 期貨",
        src="Yahoo Finance · CL=F（NYMEX 連續近月合約）",
        formula="近三個月變化率",
        what="美國基準原油，交割地為奧克拉荷馬州庫欣。",
        how="受美國頁岩油產量與庫存影響較大。與布蘭特的價差反映運輸與出口瓶頸。"),
    "BZ=F": dict(
        full="布蘭特原油 Brent 期貨",
        src="Yahoo Finance · BZ=F（ICE 連續近月合約）",
        formula="近三個月變化率",
        what="全球基準原油，北海產出，約三分之二的國際原油以它定價。",
        how="比 WTI 更能反映全球供需與地緣風險。台灣進口油價較貼近布蘭特。"),
    "NG=F": dict(
        full="亨利港天然氣期貨",
        src="Yahoo Finance · NG=F（NYMEX 連續近月合約）",
        formula="近三個月變化率",
        what="美國天然氣基準價格。",
        how="季節性極強（暖氣與空調需求），且儲存成本高，波動遠大於原油。"),
    "RB=F": dict(
        full="RBOB 汽油期貨",
        src="Yahoo Finance · RB=F（NYMEX 連續近月合約）",
        formula="近三個月變化率",
        what="美國零售汽油的上游批發價。",
        how="直接影響 CPI 能源分項與消費者觀感，常領先零售油價 2-4 週。"),
    "GC=F": dict(
        full="COMEX 黃金期貨",
        src="Yahoo Finance · GC=F（連續近月合約）",
        formula="近三個月變化率",
        what="兼具避險資產與抗通膨資產的雙重身分。",
        how="與實質利率呈負相關（持有黃金無利息）。避險與通膨兩個驅動力常互相抵消。"),
    "SI=F": dict(
        full="COMEX 白銀期貨",
        src="Yahoo Finance · SI=F（連續近月合約）",
        formula="近三個月變化率",
        what="約一半需求來自工業（電子、太陽能），一半來自投資。",
        how="因此波動大於黃金，且兼有工業金屬與貴金屬的雙重性格。"),
    "HG=F": dict(
        full="COMEX 銅期貨",
        src="Yahoo Finance · HG=F（連續近月合約）",
        formula="近三個月變化率",
        what="俗稱「銅博士」，用途橫跨營建、電力、電動車與電網。",
        how="工業需求最敏感的金屬。但近年受電網與再生能源結構性需求影響，"
             "與傳統景氣循環的連動性已不如過去。"),
    "PL=F": dict(
        full="NYMEX 鉑金期貨",
        src="Yahoo Finance · PL=F（連續近月合約）",
        formula="近三個月變化率",
        what="主要用於柴油車觸媒轉換器與工業催化劑。",
        how="供給高度集中於南非，易受當地電力與罷工影響。"),
    "ALI=F": dict(
        full="COMEX 鋁期貨",
        src="Yahoo Finance · ALI=F（連續近月合約）",
        formula="近三個月變化率",
        what="用於運輸、包裝、營建，冶煉極度耗電。",
        how="電價與能源成本是關鍵驅動因素，常與天然氣價格連動。"
             "此合約流動性低於 LME 鋁，報價可能較不連續。"),
    "ZC=F": dict(
        full="CBOT 玉米期貨",
        src="Yahoo Finance · ZC=F（連續近月合約）",
        formula="近三個月變化率",
        what="全球最大宗的穀物，同時用於飼料與乙醇。",
        how="受美國中西部天候、乙醇政策與出口需求主導，季節性明顯。"),
    "ZW=F": dict(
        full="CBOT 小麥期貨",
        src="Yahoo Finance · ZW=F（連續近月合約）",
        formula="近三個月變化率",
        what="主要的人類主食穀物。",
        how="對地緣政治極敏感（黑海地區佔全球出口大宗）。"),
    "ZS=F": dict(
        full="CBOT 黃豆期貨",
        src="Yahoo Finance · ZS=F（連續近月合約）",
        formula="近三個月變化率",
        what="用於飼料（豆粕）與食用油（豆油）。",
        how="中國進口需求與南美產季天候是兩大變數。"),
    "SB=F": dict(
        full="ICE 11 號原糖期貨",
        src="Yahoo Finance · SB=F（連續近月合約）",
        formula="近三個月變化率",
        what="全球自由市場原糖基準價。",
        how="巴西產量與乙醇比價（糖可轉作乙醇）是主要驅動。"),
    "KC=F": dict(
        full="ICE 阿拉比卡咖啡期貨",
        src="Yahoo Finance · KC=F（連續近月合約）",
        formula="近三個月變化率",
        what="高品質咖啡豆的國際基準價。",
        how="巴西與越南天候（霜害、乾旱）常造成劇烈波動。"),
    "CT=F": dict(
        full="ICE 2 號棉花期貨",
        src="Yahoo Finance · CT=F（連續近月合約）",
        formula="近三個月變化率",
        what="紡織原料，需求與成衣消費連動。",
        how="與合成纖維（石化產品）有替代關係，因此也受油價間接影響。"),
    "DBC": dict(
        full="Invesco DB 商品指數追蹤基金",
        src="Yahoo Finance · DBC（ETF）",
        formula="近三個月變化率",
        what="追蹤 14 種主要商品的廣泛商品 ETF，能源權重偏高。",
        how="可作為整體原物料方向的單一代理。注意它使用期貨，有轉倉成本。"),
    "DBA": dict(
        full="Invesco DB 農產品指數基金",
        src="Yahoo Finance · DBA（ETF）",
        formula="近三個月變化率",
        what="追蹤一籃子農產品期貨。",
        how="農產品與工業景氣連動弱，主要受天候與地緣政治影響。"),

    # ------------------------------------------------------------ 市場情緒
    "^VIX": dict(
        full="Cboe 波動率指數 VIX",
        src="Yahoo Finance · ^VIX（Cboe 編製，日頻）",
        formula="由標普500 近月與次月選擇權權利金反推的 30 天隱含波動率（年化）",
        what="市場對未來 30 天波動幅度的定價，俗稱「恐慌指數」。",
        how="&lt;15 低波動、15-25 常態、&gt;25 高波動。極端高點常對應市場底部，"
             "但低 VIX 不代表安全，只代表市場<b>目前</b>不認為有風險。"),
    "^GSPC": dict(
        full="標準普爾 500 指數",
        src="Yahoo Finance · ^GSPC",
        formula="近三個月變化率",
        what="美國大型股市值加權指數，全球風險資產的基準。",
        how="本儀表板顯示的是三個月報酬率，不是指數點位。"),
}

# ------------------------------------------------------------ 公債殖利率
_TENOR_HOW = {
    "DGS1MO": "最貼近隔夜政策利率，幾乎等於 Fed 當前的目標區間。",
    "DGS3MO": "貨幣市場基準。與 10 年期的利差是預測衰退能力最強的組合。",
    "DGS6MO": "反映未來半年的政策預期，降息循環啟動前會先鬆動。",
    "DGS1":   "一年內的政策路徑定價，對 Fed 措辭變化敏感。",
    "DGS2":   "市場對未來兩年政策利率的定價，Fed 轉向最先反映在這裡。",
    "DGS3":   "介於政策預期與期限溢酬之間的過渡天期。",
    "DGS5":   "中段曲線的代表，常用於判斷市場對「中期均衡利率」的看法。",
    "DGS7":   "中長段過渡，流動性略低於 5 年與 10 年。",
    "DGS10":  "全球長期資金成本的基準，房貸與企業債定價多以此為錨。",
    "DGS20":  "長端天期，受期限溢酬與退休金／保險需求影響大。",
    "DGS30":  "最長天期，主要反映長期通膨預期與財政可持續性的疑慮。",
}
for _code, _how in _TENOR_HOW.items():
    _yrs = {"DGS1MO": "1 個月", "DGS3MO": "3 個月", "DGS6MO": "6 個月"}.get(
        _code, _code.replace("DGS", "") + " 年")
    META.setdefault(_code, dict(
        full=f"{_yrs}期美國公債殖利率",
        src=f"FRED · {_code}（財政部固定到期日殖利率 CMT，日頻，單位：%）",
        formula="直接取市場報價。CMT 為財政部由次級市場報價擬合出的標準天期殖利率。",
        what=f"借錢給美國政府 {_yrs} 的年化報酬率，視為該天期的無風險利率。",
        how=_how))

META["^IXIC"] = dict(
    full="納斯達克綜合指數 NASDAQ Composite",
    src="Yahoo Finance · ^IXIC",
    formula="近三個月變化率",
    what="納斯達克交易所全部上市股票的市值加權指數，科技股權重高。",
    how="與標普500 的相對強弱反映市場的風險偏好與成長股／價值股輪動。"
        "對實質利率變化比標普500 更敏感。")

META["NFCIRISK"] = dict(
    full="NFCI 風險子指數",
    src="FRED · NFCIRISK（芝加哥 Fed，週頻）",
    formula="NFCI 三大子指數之一，標準化後長期平均＝0",
    what="衡量金融部門的波動度與資金取得風險。",
    how=">0 代表風險程度高於歷史平均。這一塊通常最快反應市場壓力。")
META["NFCICREDIT"] = dict(
    full="NFCI 信用子指數",
    src="FRED · NFCICREDIT（芝加哥 Fed，週頻）",
    formula="NFCI 三大子指數之一",
    what="衡量信用取得的難易程度，含各類利差與放款條件。",
    how=">0 代表信用條件緊於平均。與高收益債利差方向通常一致。")
META["NFCILEVERAGE"] = dict(
    full="NFCI 槓桿子指數",
    src="FRED · NFCILEVERAGE（芝加哥 Fed，週頻）",
    formula="NFCI 三大子指數之一",
    what="衡量債務與股權的槓桿水準。",
    how="注意方向：<b>槓桿下降會使 NFCI 上升</b>（視為條件收緊），"
        "因為去槓桿代表資金收縮。這一塊常是三者中最遲鈍的。")


def get(code: str) -> dict | None:
    return META.get(code)
