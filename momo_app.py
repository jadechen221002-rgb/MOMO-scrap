import re
import time

import pandas as pd
import plotly.express as px
import streamlit as st
from curl_cffi import requests

# ------------------------------------------------------------------
# 頁面設定
# ------------------------------------------------------------------
st.set_page_config(page_title="MOMO 商品價格查詢", page_icon="🛒", layout="wide")

API_URL = "https://apisearch.momoshop.com.tw/momoSearchCloud/moec/textSearch"
HOME_URL = "https://www.momoshop.com.tw/"
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Content-Type": "application/json;charset=UTF-8",
    "Origin": "https://www.momoshop.com.tw",
    "Referer": "https://www.momoshop.com.tw/",
}


# ------------------------------------------------------------------
# 爬蟲（CODE01）
# ------------------------------------------------------------------
def build_payload(keyword: str, page: int) -> dict:
    return {
        "host": "momoshop",
        "flag": "searchEngine",
        "data": {
            "searchValue": keyword,
            "searchType": "1",
            "cateLevel": "-1",
            "curPage": str(page),
            "priceS": "0",
            "priceE": "9999999",
            "showType": "chessboardType",
            "isFuzzy": "0",
            "rtnCateDatainfo": {
                "cateCode": "",
                "cateLv": "-1",
                "keyword": keyword,
                "curPage": str(page),
                "historyDoPush": "false",
                "timestamp": int(time.time() * 1000),
            },
            "flag": 2018,
            "serviceCode": "MT01",
            "addressSearchData": {},
        },
    }


def extract_brand(name: str) -> str:
    """商品名稱通常以【品牌】開頭，抓不到就歸為「其他」"""
    m = re.search(r"【(.+?)】", name)
    return m.group(1).strip() if m else "其他"


@st.cache_data(show_spinner=False, ttl=600)
def fetch_momo(keyword: str, start_page: int, end_page: int) -> pd.DataFrame:
    session = requests.Session(impersonate="chrome")  # 模擬 Chrome TLS 指紋
    session.get(HOME_URL, headers=HEADERS)  # 先取得 cookie

    rows = []
    for page in range(start_page, end_page + 1):
        resp = session.post(API_URL, headers=HEADERS, json=build_payload(keyword, page))
        if resp.status_code != 200:
            raise RuntimeError(f"第 {page} 頁請求失敗（HTTP {resp.status_code}）：{resp.text[:200]}")

        goods = resp.json().get("rtnSearchData", {}).get("goodsInfoList", [])
        if not goods:  # 沒資料就不用再往後抓
            break
        for p in goods:
            rows.append(
                {
                    "頁數": page,
                    "品名": p.get("goodsName", ""),
                    "價格": p.get("goodsPrice", ""),
                    "商品代碼": p.get("goodsCode", ""),
                }
            )
        time.sleep(1)  # 禮貌性延遲，避免被封鎖

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # 價格清理：去除 $、逗號與其他非數字字元
    df["價格"] = df["價格"].astype(str).str.replace(r"[^\d]", "", regex=True)
    df = df[df["價格"] != ""].copy()
    df["價格"] = df["價格"].astype(int)
    df["品牌"] = df["品名"].apply(extract_brand)
    df["連結"] = "https://www.momoshop.com.tw/goods/GoodsDetail.jsp?i_code=" + df["商品代碼"].astype(str)
    return df.reset_index(drop=True)


def add_price_range(df: pd.DataFrame) -> pd.DataFrame:
    bins = [0, 300, 500, 1000, 1500, 2000, 3000, float("inf")]
    labels = ["300以下", "301-500", "501-1000", "1001-1500", "1501-2000", "2001-3000", "3000以上"]
    df = df.copy()
    df["價格區間"] = pd.cut(df["價格"], bins=bins, labels=labels, right=True)
    return df


# ------------------------------------------------------------------
# 側邊欄：使用者輸入
# ------------------------------------------------------------------
st.title("🛒 MOMO 購物網商品價格查詢與視覺化")

with st.sidebar:
    st.header("查詢條件")
    keyword = st.text_input("商品關鍵字", value="行動電源")
    col1, col2 = st.columns(2)
    start_page = col1.number_input("起始頁", min_value=1, max_value=50, value=1, step=1)
    end_page = col2.number_input("結束頁", min_value=1, max_value=50, value=1, step=1)
    chart_type = st.radio("圖表類型", ["圓餅圖", "折線圖", "旭日圖"])
    run = st.button("開始查詢", type="primary", use_container_width=True)

if end_page < start_page:
    st.sidebar.error("結束頁不可小於起始頁")
    st.stop()

# ------------------------------------------------------------------
# 查詢（結果存入 session_state，切換圖表時不用重爬）
# ------------------------------------------------------------------
if run:
    if not keyword.strip():
        st.warning("請輸入商品關鍵字")
        st.stop()
    with st.spinner("爬取中，請稍候…"):
        try:
            st.session_state["df"] = fetch_momo(keyword.strip(), int(start_page), int(end_page))
            st.session_state["keyword"] = keyword.strip()
        except Exception as e:
            st.error(f"爬取失敗：{e}")
            st.stop()

if "df" not in st.session_state:
    st.info("請在左側輸入商品關鍵字與頁數，然後按「開始查詢」。")
    st.stop()

df = st.session_state["df"]
kw = st.session_state["keyword"]

if df.empty:
    st.warning("查無資料，請換個關鍵字或頁數再試。")
    st.stop()

# ------------------------------------------------------------------
# 統計（CODE02）
# ------------------------------------------------------------------
avg_price = df["價格"].mean()
c1, c2, c3, c4 = st.columns(4)
c1.metric("商品數量", f"{len(df)} 筆")
c2.metric("平均價格", f"${avg_price:,.0f}")
c3.metric("最高價格", f"${df['價格'].max():,}")
c4.metric("最低價格", f"${df['價格'].min():,}")

# ------------------------------------------------------------------
# 視覺化（改用 Plotly：由瀏覽器渲染中文，不需下載字型檔）
# ------------------------------------------------------------------
st.subheader(f"「{kw}」價格分析 - {chart_type}")
df_r = add_price_range(df)

if chart_type == "圓餅圖":
    pie_df = df_r.groupby("價格區間", observed=True).size().reset_index(name="商品數")
    fig = px.pie(pie_df, names="價格區間", values="商品數", hole=0.3,
                 title=f"MOMO「{kw}」價格區間分布")
    fig.update_traces(textinfo="label+percent+value")

elif chart_type == "折線圖":
    line_df = df.reset_index().rename(columns={"index": "商品序號"})
    fig = px.line(line_df, x="商品序號", y="價格", hover_data=["品名", "頁數"],
                  markers=True, title=f"MOMO「{kw}」商品售價")
    fig.add_hline(y=avg_price, line_dash="dash", line_color="red",
                  annotation_text=f"平均 ${avg_price:,.0f}")

else:  # 旭日圖：價格區間 → 品牌
    top_brands = df_r["品牌"].value_counts().head(15).index
    sun_df = df_r.copy()
    sun_df["品牌"] = sun_df["品牌"].where(sun_df["品牌"].isin(top_brands), "其他")
    sun_df = (sun_df.groupby(["價格區間", "品牌"], observed=True)
              .size().reset_index(name="商品數"))
    fig = px.sunburst(sun_df, path=["價格區間", "品牌"], values="商品數",
                      title=f"MOMO「{kw}」價格區間 → 品牌（前 15 大品牌）")

fig.update_layout(height=600, font=dict(size=14))
st.plotly_chart(fig, use_container_width=True)

# ------------------------------------------------------------------
# 資料表與下載
# ------------------------------------------------------------------
st.subheader("原始資料")
st.dataframe(
    df[["頁數", "品名", "品牌", "價格", "連結"]],
    use_container_width=True,
    column_config={"連結": st.column_config.LinkColumn("商品連結", display_text="前往")},
)

csv = df.drop(columns=["連結"]).to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
st.download_button("下載 CSV", data=csv,
                   file_name=f"MOMO_{kw}_{time.strftime('%Y%m%d')}.csv", mime="text/csv")
