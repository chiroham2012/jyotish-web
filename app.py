#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app.py  —  ブラウザで「ポチッ」と鑑定を出す骨組み（Streamlit）／新版 v2

★v2 で追加したもの：ホロスコープ図（南インド式ラーシ・チャート）の画面表示。
  compute_chart() の JSON を generate_chart_auto.build_svg() に橋渡しして SVG を描く。

起動:
    pip install streamlit pyswisseph
    streamlit run app.py
  → ブラウザが自動で開く（localhost:8501）。まずはこれで自分専用に動く。

この骨組みでやっていること:
  1) フォームで 氏名・生年月日時・出生地 を入力
  2) 出生地 → 緯度経度（簡易アトラス。無ければ手入力）
  3) ボタンで compute_chart() を呼び、PL互換 JSON を生成
  4) 画面に「ホロスコープ図」＋惑星表＋ダシャー＋カラカ＋JSONダウンロード

次に足すところ（コメントで TODO を置いた）:
  - 鑑定文生成（01の career ロジック）→ .md
  - PDFワークシート（render_sheet.py / render_reading.py を呼ぶ）
"""
import datetime as dt
import json
import os
import streamlit as st
import streamlit.components.v1 as components
from compute_chart import compute_chart
from generate_chart_auto import build_svg   # ← 既存の南インド式ジェネレータを流用
from chart_bridge import chart_json_to_svg_data  # ← JSON→SVG用データの橋渡し（画面・PDF共通）
from build_reading import build_reading     # ← 材料ボード→Claude API→鑑定文
from build_worksheet_pdf import build_worksheet_pdf  # ← 鑑定文+JSON→2枚綴じPDF（同じSVGを再利用）

# set_page_config は「スクリプト内で最初に呼ぶstreamlitコマンド」である必要があるため、
# パスワードゲートより前のここで呼ぶ。
st.set_page_config(page_title="ホロスコープ鑑定支援", page_icon="🪔")


def _resolve_api_key():
    """ANTHROPIC_API_KEY を 環境変数 → Streamlit secrets の順で探す。無ければ None。"""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    try:
        return st.secrets.get("ANTHROPIC_API_KEY")
    except Exception:
        return None


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

    st.title("🪔 ホロスコープ鑑定支援")
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

# --- 簡易アトラス（出生地→緯度経度・TZ）。まずは主要都市。あとから増やせる ---
CITIES = {
    "長岡市 (新潟)":   (37 + 27/60, 138 + 51/60, 9),
    "新潟市 (新潟)":   (37 + 55/60, 139 +  3/60, 9),
    "見附市 (新潟)":   (37 + 32/60, 138 + 55/60, 9),
    "東京都区部":      (35 + 41/60, 139 + 41/60, 9),
    "横浜市 (神奈川)": (35 + 27/60, 139 + 38/60, 9),
    "大阪市 (大阪)":   (34 + 41/60, 135 + 30/60, 9),
    "（手入力する）":  None,
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


st.title("🪔 ホロスコープ鑑定支援")
st.caption("Parashara's Light 不要 — 入力してボタンを押すと自動で算出します。")
st.info("現在は試験運用中です。入力された生年月日・出生地などの情報はサーバーに保存されません"
        "（各処理はその場限りで、処理が終わると破棄されます）。", icon="🔒")

with st.form("birth"):
    name = st.text_input("氏名（ファイル名用キー）", "Sato_Hanako")
    c1, c2 = st.columns(2)
    with c1:
        bdate = st.date_input("生年月日", dt.date(2026, 6, 23),
                              min_value=dt.date(1900, 1, 1),
                              max_value=dt.date(2100, 12, 31))
    with c2:
        btime = st.time_input("出生時刻", dt.time(14, 49, 27), step=60)

    city = st.selectbox("出生地", list(CITIES.keys()))
    if CITIES[city] is None:
        cc1, cc2, cc3 = st.columns(3)
        lat = cc1.number_input("緯度（北緯+）", value=37.45, format="%.4f")
        lon = cc2.number_input("経度（東経+）", value=138.85, format="%.4f")
        tz  = cc3.number_input("時差", value=9.0, step=0.5)
        city_name = st.text_input("地名（表示用）", "")
    else:
        lat, lon, tz = CITIES[city]
        city_name = city.split(" ")[0]

    include_outer = st.checkbox("トランスサタニアン(天王星・海王星・冥王星)を含める", True)
    submitted = st.form_submit_button("鑑定チャートを作成", type="primary")

if submitted:
    birth_dt = dt.datetime.combine(bdate, btime)
    data = compute_chart(name, birth_dt, tz, lat, lon,
                         city=city_name, country="Japan",
                         include_outer=include_outer)
    # フォーム送信時に結果を保存。別ボタン（鑑定文を生成）で再実行されても結果が
    # 消えないよう session_state に持たせる。新しく算出したら前の鑑定文はクリア。
    st.session_state["data"] = data
    st.session_state["name"] = name
    st.session_state["reading"] = None
    st.session_state["worksheet_pdf"] = None

data = st.session_state.get("data")
if data:
    name = st.session_state.get("name", "chart")

    st.success(f"算出しました：{data['ascendant']['sign']} 昇（Asc {data['ascendant']['degree']}）")

    # ホロスコープ図（南インド式ラーシ・チャート）
    st.subheader("ホロスコープ図（南インド式ラーシ・チャート）")
    try:
        svg = render_horoscope_svg(data, name.replace("_", " "))
        st.download_button(
            "チャート図(SVG)をダウンロード",
            data=svg,
            file_name=f"{name}_chart.svg",
            mime="image/svg+xml",
        )
    except Exception as e:
        st.error(f"ホロスコープ図の描画でエラー: {e}")
        st.exception(e)

    # 惑星表
    st.subheader("惑星")
    rows = []
    for k, p in data["planets"].items():
        rows.append({"惑星": p["name_en"], "サイン": p["sign"], "度数": p["degree"],
                     "ハウス": p["house"], "逆行": "R" if p["retrograde"] else "",
                     "ナクシャトラ": p.get("nakshatra", "")})
    st.dataframe(rows, hide_index=True, use_container_width=True)

    # ダシャー（現在の期）
    st.subheader("ヴィムショッタリ・ダシャー（直近）")
    st.dataframe(data["dasha"]["periods"][:8], hide_index=True, use_container_width=True)

    # カラカ
    st.subheader("チャラ・カラカ")
    st.write({k: v for k, v in data["karakas"].items() if not k.startswith("_") and k != "scheme"})

    # JSON ダウンロード（下流プログラムへの受け渡し）
    st.download_button(
        "chart_data.json をダウンロード",
        data=json.dumps(data, ensure_ascii=False, indent=2),
        file_name=f"{name}_chart_data.json",
        mime="application/json",
    )

    # --- 鑑定文（下書き）: 材料ボード → Claude API → 完成鑑定文 ---
    st.subheader("鑑定文（下書き）")
    st.caption("材料ボードの範囲内で Claude が下書きします。最終確認は鑑定者が行ってください。"
               "※生成のたびに Anthropic API の従量課金が発生します。")

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
                st.error(f"鑑定文の生成でエラーが発生しました：{e}")
                st.exception(e)

    if st.session_state.get("reading"):
        st.markdown(st.session_state["reading"])
        st.download_button(
            "鑑定文(.md)をダウンロード",
            data=st.session_state["reading"],
            file_name=f"{name}_reading.md",
            mime="text/markdown",
        )

        # --- PDFワークシート（チャート＋鑑定文の2枚綴じ・A4） ---
        st.subheader("PDFワークシート（チャート＋鑑定文の2枚綴じ）")
        if st.button("PDFワークシートを作る"):
            try:
                with st.spinner("PDFワークシートを作っています…"):
                    st.session_state["worksheet_pdf"] = build_worksheet_pdf(
                        data, st.session_state["reading"], name
                    )
            except Exception as e:
                st.error(f"PDFワークシートの生成でエラーが発生しました：{e}")
                st.exception(e)

        if st.session_state.get("worksheet_pdf"):
            st.download_button(
                "ワークシートPDFをダウンロード",
                data=st.session_state["worksheet_pdf"],
                file_name=f"{name}_set.pdf",
                mime="application/pdf",
            )

    with st.expander("生成された JSON を確認"):
        st.json(data)
