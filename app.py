#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app.py  —  ブラウザで「ポチッ」と鑑定を出す骨組み（Streamlit）／新版 v3

★v3 で整えたもの：占星術の知識がない一般の利用者（お客様本人）でも迷わないよう、
  画面を①〜④の4ステップに整理し、専門家向けの生データはexpanderに畳んだ。

起動:
    pip install streamlit pyswisseph
    streamlit run app.py
  → ブラウザが自動で開く（localhost:8501）。まずはこれで自分専用に動く。

この骨組みでやっていること:
  ① フォームで お名前・生年月日時・出生地 を入力
  ② ボタンで compute_chart() を呼び、ホロスコープ図を表示
  ③ 鑑定文生成（01の career ロジック）→ 画面表示
  ④ PDFワークシート（render_sheet.py / render_reading.py を呼ぶ）
"""
import datetime as dt
import json
import os
import re
import traceback
import streamlit as st
import streamlit.components.v1 as components
from compute_chart import compute_chart
from generate_chart_auto import build_svg   # ← 既存の南インド式ジェネレータを流用
from chart_bridge import chart_json_to_svg_data  # ← JSON→SVG用データの橋渡し（画面・PDF共通）
from build_reading import build_reading     # ← 材料ボード→Claude API→鑑定文
from build_worksheet_pdf import build_worksheet_pdf  # ← 鑑定文+JSON→2枚綴じPDF（同じSVGを再利用）

# set_page_config は「スクリプト内で最初に呼ぶstreamlitコマンド」である必要があるため、
# パスワードゲートより前のここで呼ぶ。
st.set_page_config(page_title="インド占星術で見るあなたの天職", page_icon="🪔")


def _resolve_api_key():
    """ANTHROPIC_API_KEY を 環境変数 → Streamlit secrets の順で探す。無ければ None。"""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    try:
        return st.secrets.get("ANTHROPIC_API_KEY")
    except Exception:
        return None


def _safe_key(raw_name: str) -> str:
    """自由入力のお名前から、ダウンロードファイル名・一時ファイル名に使う安全な文字列を作る。"""
    key = re.sub(r'[\\/:*?"<>|\s]+', "_", raw_name or "").strip("_")
    return key or "chart"


def _show_error(user_message: str, exc: Exception) -> None:
    """一般利用者にはトレースバックを見せず、詳細はサーバーログにだけ出す。"""
    st.error(user_message)
    traceback.print_exc()


def _check_password():
    """APP_PASSWORD が secrets に設定されていれば、簡易パスワードゲートを表示する。
    設定されていなければ（＝ローカル動作時）認証をスキップして常に通す。
    試験運用（少人数への限定公開）向けの最小限の入り口用。"""
    try:
        required = st.secrets.get("APP_PASSWORD")
    except Exception:
        required = None
    if not required:
        return True
    if st.session_state.get("_authed"):
        return True

    st.title("🪔 インド占星術で見るあなたの天職")
    st.caption("試験運用中のため、合言葉をご存じの方のみご利用いただけます。")
    pw = st.text_input("合言葉", type="password")
    if st.button("入る"):
        if pw == required:
            st.session_state["_authed"] = True
            st.rerun()
        else:
            st.error("合言葉が違います。")
    return False


if not _check_password():
    st.stop()

# --- 出生地アトラス：47都道府県庁所在地＋長岡市・見附市（新潟）。あとから増やせる ---
CITIES = {
    "札幌市 (北海道)": (43.0642, 141.3469, 9),
    "青森市 (青森)": (40.8244, 140.7400, 9),
    "盛岡市 (岩手)": (39.7036, 141.1527, 9),
    "仙台市 (宮城)": (38.2682, 140.8694, 9),
    "秋田市 (秋田)": (39.7186, 140.1024, 9),
    "山形市 (山形)": (38.2404, 140.3633, 9),
    "福島市 (福島)": (37.7500, 140.4678, 9),
    "水戸市 (茨城)": (36.3418, 140.4468, 9),
    "宇都宮市 (栃木)": (36.5658, 139.8836, 9),
    "前橋市 (群馬)": (36.3907, 139.0604, 9),
    "さいたま市 (埼玉)": (35.8617, 139.6455, 9),
    "千葉市 (千葉)": (35.6073, 140.1063, 9),
    "東京都区部 (東京)": (35.6895, 139.6917, 9),
    "横浜市 (神奈川)": (35.4437, 139.6380, 9),
    "新潟市 (新潟)": (37.9161, 139.0364, 9),
    "長岡市 (新潟)": (37.4500, 138.8500, 9),
    "見附市 (新潟)": (37.5333, 138.9167, 9),
    "富山市 (富山)": (36.6953, 137.2113, 9),
    "金沢市 (石川)": (36.5613, 136.6562, 9),
    "福井市 (福井)": (36.0652, 136.2216, 9),
    "甲府市 (山梨)": (35.6642, 138.5684, 9),
    "長野市 (長野)": (36.6513, 138.1810, 9),
    "岐阜市 (岐阜)": (35.3912, 136.7223, 9),
    "静岡市 (静岡)": (34.9769, 138.3831, 9),
    "名古屋市 (愛知)": (35.1815, 136.9066, 9),
    "津市 (三重)": (34.7303, 136.5086, 9),
    "大津市 (滋賀)": (35.0045, 135.8686, 9),
    "京都市 (京都)": (35.0116, 135.7681, 9),
    "大阪市 (大阪)": (34.6864, 135.5200, 9),
    "神戸市 (兵庫)": (34.6913, 135.1830, 9),
    "奈良市 (奈良)": (34.6851, 135.8330, 9),
    "和歌山市 (和歌山)": (34.2261, 135.1675, 9),
    "鳥取市 (鳥取)": (35.5039, 134.2381, 9),
    "松江市 (島根)": (35.4723, 133.0505, 9),
    "岡山市 (岡山)": (34.6618, 133.9344, 9),
    "広島市 (広島)": (34.3966, 132.4596, 9),
    "山口市 (山口)": (34.1858, 131.4706, 9),
    "徳島市 (徳島)": (34.0658, 134.5593, 9),
    "高松市 (香川)": (34.3401, 134.0434, 9),
    "松山市 (愛媛)": (33.8416, 132.7657, 9),
    "高知市 (高知)": (33.5597, 133.5311, 9),
    "福岡市 (福岡)": (33.6064, 130.4181, 9),
    "佐賀市 (佐賀)": (33.2494, 130.2988, 9),
    "長崎市 (長崎)": (32.7448, 129.8737, 9),
    "熊本市 (熊本)": (32.7898, 130.7417, 9),
    "大分市 (大分)": (33.2382, 131.6126, 9),
    "宮崎市 (宮崎)": (31.9111, 131.4239, 9),
    "鹿児島市 (鹿児島)": (31.5602, 130.5581, 9),
    "那覇市 (沖縄)": (26.2124, 127.6809, 9),
    "（この中にない・自分で入力する）": None,
}

def render_horoscope_svg(data, display_name):
    """ホロスコープ図の SVG を作り、画面幅に合わせて表示する。"""
    svg_data = chart_json_to_svg_data(data, display_name)
    svg = build_svg(svg_data)
    # 画面幅に追従させる（viewBox はそのまま、固定 width/height だけレスポンシブ化）
    svg_responsive = svg.replace(
        'width="1100" height="1420"',
        'width="100%" style="height:auto; max-width:760px; display:block; margin:0 auto;"',
        1,
    )
    components.html(
        f'<div style="display:flex; justify-content:center;">{svg_responsive}</div>',
        height=1000, scrolling=False,
    )
    return svg  # ダウンロード用に元の SVG（固定サイズ）を返す


st.title("🪔 インド占星術で見るあなたの天職")
st.caption("生年月日・出生地を入力するだけで、あなたの出生チャートと鑑定文を自動で作成します。")
st.info("現在は試験運用中です。入力された生年月日・出生地などの情報はサーバーに保存されません"
        "（各処理はその場限りで、処理が終わると破棄されます）。", icon="🔒")

st.header("① 生年月日・出生地を入力してください")
# ※ st.form は使わない：出生地で「自分で入力する」を選んだ時に、緯度経度欄が
#   その場で（ボタンを押す前に）表示・編集できるようにするため。
name = st.text_input("お名前", "", placeholder="例：山田 花子")
c1, c2 = st.columns(2)
with c1:
    bdate = st.date_input("生年月日", dt.date(1990, 1, 1),
                          min_value=dt.date(1900, 1, 1),
                          max_value=dt.date(2100, 12, 31))
with c2:
    btime = st.time_input("出生時刻", dt.time(12, 0), step=60)
st.caption("正確な時刻がわからない場合は 12:00 のままで構いません。")

city = st.selectbox("出生地", list(CITIES.keys()))
if CITIES[city] is None:
    st.caption("地図アプリなどで「（お住まいの市区町村名） 緯度経度」と検索すると調べられます。")
    cc1, cc2, cc3 = st.columns(3)
    lat = cc1.number_input("緯度（北緯+）", value=37.45, format="%.4f")
    lon = cc2.number_input("経度（東経+）", value=138.85, format="%.4f")
    tz  = cc3.number_input("時差", value=9.0, step=0.5)
    city_name = st.text_input("地名（表示用）", "")
else:
    lat, lon, tz = CITIES[city]
    city_name = city.split(" ")[0]

submitted = st.button("鑑定チャートを作成", type="primary")

if submitted:
    birth_dt = dt.datetime.combine(bdate, btime)
    data = compute_chart(name, birth_dt, tz, lat, lon,
                         city=city_name, country="Japan",
                         include_outer=True)
    # フォーム送信時に結果を保存。別ボタン（鑑定文を生成）で再実行されても結果が
    # 消えないよう session_state に持たせる。新しく算出したら前の鑑定文はクリア。
    st.session_state["data"] = data
    st.session_state["name"] = name
    st.session_state["key"] = _safe_key(name)
    st.session_state["reading"] = None
    st.session_state["worksheet_pdf"] = None

data = st.session_state.get("data")
if data:
    name = st.session_state.get("name", "")
    key = st.session_state.get("key", "chart")

    st.header("② あなたのホロスコープチャート")
    st.success(f"算出しました：{data['ascendant']['sign']} 昇（Asc {data['ascendant']['degree']}）")

    # ホロスコープ図（南インド式ラーシ・チャート）
    try:
        svg = render_horoscope_svg(data, name.replace("_", " ") if name else "あなた")
    except Exception as e:
        _show_error("ホロスコープ図の表示でエラーが発生しました。時間をおいて再度お試しください。", e)
        svg = None

    with st.expander("詳しいデータを見る（占星術に詳しい方向け）"):
        if svg:
            st.download_button(
                "チャート図(SVG)をダウンロード",
                data=svg,
                file_name=f"{key}_chart.svg",
                mime="image/svg+xml",
            )

        st.subheader("惑星")
        rows = []
        for k, p in data["planets"].items():
            rows.append({"惑星": p["name_en"], "サイン": p["sign"], "度数": p["degree"],
                         "ハウス": p["house"], "逆行": "R" if p["retrograde"] else "",
                         "ナクシャトラ": p.get("nakshatra", "")})
        st.dataframe(rows, hide_index=True, use_container_width=True)

        st.subheader("ヴィムショッタリ・ダシャー（直近）")
        st.dataframe(data["dasha"]["periods"][:8], hide_index=True, use_container_width=True)

        st.subheader("チャラ・カラカ")
        st.write({k: v for k, v in data["karakas"].items() if not k.startswith("_") and k != "scheme"})

        st.download_button(
            "chart_data.json をダウンロード",
            data=json.dumps(data, ensure_ascii=False, indent=2),
            file_name=f"{key}_chart_data.json",
            mime="application/json",
        )

        st.json(data)

    # --- 鑑定文: 材料ボード → Claude API → 完成鑑定文 ---
    st.header("③ 鑑定文を作成")
    st.caption("AIが自動で鑑定文を作成します。生成のたびに文章表現が少しずつ変わります。")

    if st.button("鑑定文を生成", type="primary"):
        api_key = _resolve_api_key()
        if not api_key:
            st.error("APIキーが未設定です。環境変数 ANTHROPIC_API_KEY を設定するか、"
                     "`.streamlit/secrets.toml` に ANTHROPIC_API_KEY を書いてください。")
        else:
            try:
                with st.spinner("鑑定文を生成しています…（十数秒かかることがあります）"):
                    st.session_state["reading"] = build_reading(data, api_key=api_key)
                    st.session_state["worksheet_pdf"] = None  # 鑑定文が変われば古いPDFは無効
            except Exception as e:
                _show_error("鑑定文の生成でエラーが発生しました。時間をおいて再度お試しください。", e)

    if st.session_state.get("reading"):
        st.markdown(st.session_state["reading"])
        st.download_button(
            "鑑定文(.md)をダウンロード",
            data=st.session_state["reading"],
            file_name=f"{key}_reading.md",
            mime="text/markdown",
        )

        # --- PDFワークシート（チャート＋鑑定文の2枚綴じ・A4） ---
        st.header("④ PDFを保存")
        st.caption("チャート図と鑑定文をまとめた2ページのPDFを作成します。")
        if st.button("PDFワークシートを作る", type="primary"):
            try:
                with st.spinner("PDFワークシートを作っています…"):
                    st.session_state["worksheet_pdf"] = build_worksheet_pdf(
                        data, st.session_state["reading"], key
                    )
            except Exception as e:
                _show_error("PDFの作成でエラーが発生しました。時間をおいて再度お試しください。", e)

        if st.session_state.get("worksheet_pdf"):
            st.download_button(
                "ワークシートPDFをダウンロード",
                data=st.session_state["worksheet_pdf"],
                file_name=f"{key}_set.pdf",
                mime="application/pdf",
            )
