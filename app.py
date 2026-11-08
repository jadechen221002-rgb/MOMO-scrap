import re
import time

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

# ---------------------------------------------------------------
# 頁面設定
# ---------------------------------------------------------------
st.set_page_config(page_title="MOMO 商品價格查詢", page_icon="🛒", layout="wide")

API_URL = "https://apisearch.momoshop.com.tw/momoSearchCloud/moec/textSearch"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
    )
}


# ---------------------------------------------------------------
# 爬蟲 (CODE01)
# ---------------------------------------------------------------
def build_payload(keyword: str, page: int) -> dict:
    return {
        "host": "momoshop",
        "flag": "searchEngine",
        "data": {
            "specialGoodsType": "",
            "isBrandSeriesPage": "false",
            "authorNo": "",
            "originalCateCode": "",
            "cateType": "",
            "searchValue": keyword,
            "cateCode": "",
            "cateLevel": "-1",
            "cp": "N",
            "NAM": "N",
            "first": "N",
            "freeze": "N",
            "superstore": "N",
            "tvshop": "N",
            "china": "N",
            "tomorrow": "N",
            "stockYN": "N",
            "prefere": "N",
            "threeHours": "N",
            "video": "N",
            "cycle": "N",
            "cod": "N",
            "superstorePay": "N",
            "showType": "chessboardType",
            "curPage": str(page),
            "priceS": "0",
            "priceE": "9999999",
            "searchType": "1",
            "reduceKeyword": "",
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
            "adSource": "tenmax",
        },
    }


def clean_price(value) -> int | None:
    """把 '$1,299' 之類的字串轉成整數"""
    digits = re.sub(r"[^\d]", "", str(value))
    return int(digits) if digits else None


@st.cache_data(ttl=600, show_spinner=False)
def crawl_momo(keyword: str, pages: int) -> pd.DataFrame:
    rows = []
    for page in range(1, pages + 1):
        resp = requests.post(
            API_URL, headers=HEADERS, json=build_payload(keyword, page), timeout=15
        )
        resp.raise_for_status()
        goods = resp.json().get("rtnSearchData", {}).get("goodsInfoList", [])
        if not goods:  # 沒有更多資料就提前結束
            break
        for g in goods:
            rows.append(
                {
                    "頁碼": page,
                    "品名": g.get("goodsName", ""),
                    "價格": clean_price(g.get("goodsPrice", "")),
                }
            )
        time.sleep(0.5)  # 避免請求過於頻繁

    df = pd.DataFrame(rows, columns=["頁碼", "品名", "價格"])
    return df.dropna(subset=["價格"]).astype({"價格": int}).reset_index(drop=True)


# ---------------------------------------------------------------
# 資料處理與圖表 (CODE02)
# ---------------------------------------------------------------
def add_price_range(df: pd.DataFrame, bins: int = 6) -> pd.DataFrame:
    df = df.copy()
    if df["價格"].nunique() <= 1:
        df["價格區間"] = df["價格"].astype(str)
        return df
    df["價格區間"] = pd.qcut(df["價格"], q=min(bins, df["價格"].nunique()), duplicates="drop")
    df["價格區間"] = df["價格區間"].apply(lambda x: f"{int(x.left)}~{int(x.right)}")
    return df


def line_chart(df: pd.DataFrame, mean_price: float):
    plot_df = df.reset_index().rename(columns={"index": "商品編號"})
    fig = px.line(
        plot_df,
        x="商品編號",
        y="價格",
        markers=True,
        hover_data=["品名", "頁碼"],
        title="商品價格走勢",
    )
    fig.add_hline(
        y=mean_price,
        line_dash="dash",
        line_color="red",
        annotation_text=f"平均 {mean_price:,.0f}",
    )
    return fig


def pie_chart(df: pd.DataFrame):
    count = df["價格區間"].value_counts().reset_index()
    count.columns = ["價格區間", "商品數量"]
    return px.pie(count, names="價格區間", values="商品數量", title="價格區間佔比", hole=0.3)


def sunburst_chart(df: pd.DataFrame):
    sdf = df.copy()
    sdf["品名簡稱"] = sdf["品名"].str.slice(0, 15)
    return px.sunburst(
        sdf,
        path=["價格區間", "品名簡稱"],
        values="價格",
        title="價格區間 → 商品 旭日圖",
    )


# ---------------------------------------------------------------
# Streamlit 介面
# ---------------------------------------------------------------
st.title("🛒 MOMO 商品價格查詢與視覺化")

with st.sidebar:
    st.header("查詢條件")
    keyword = st.text_input("商品名稱", value="行動電源")
    pages = st.number_input("爬取頁數", min_value=1, max_value=20, value=2, step=1)
    chart_type = st.radio("圖表類型", ["折線圖", "圓餅圖", "旭日圖"])
    run = st.button("開始查詢", type="primary", use_container_width=True)

if run:
    if not keyword.strip():
        st.warning("請輸入商品名稱")
        st.stop()
    try:
        with st.spinner("爬取中，請稍候..."):
            st.session_state["df"] = crawl_momo(keyword.strip(), int(pages))
            st.session_state["keyword"] = keyword.strip()
    except requests.RequestException as e:
        st.error(f"請求失敗：{e}")
        st.stop()

df = st.session_state.get("df")

if df is None:
    st.info("請在左側輸入商品名稱與頁數，然後按「開始查詢」。")
elif df.empty:
    st.warning("查無資料，請換個關鍵字或稍後再試。")
else:
    df = add_price_range(df)
    mean_price = df["價格"].mean()

    st.subheader(f"「{st.session_state['keyword']}」查詢結果")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("商品數量", f"{len(df)}")
    c2.metric("平均價格", f"{mean_price:,.0f}")
    c3.metric("最高價格", f"{df['價格'].max():,}")
    c4.metric("最低價格", f"{df['價格'].min():,}")

    if chart_type == "折線圖":
        fig = line_chart(df, mean_price)
    elif chart_type == "圓餅圖":
        fig = pie_chart(df)
    else:
        fig = sunburst_chart(df)
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("商品明細")
    st.dataframe(df[["頁碼", "品名", "價格"]], use_container_width=True)

    st.download_button(
        "下載 CSV",
        data=df[["頁碼", "品名", "價格"]].to_csv(index=False).encode("utf-8-sig"),
        file_name=f"MOMO_{st.session_state['keyword']}.csv",
        mime="text/csv",
    )
