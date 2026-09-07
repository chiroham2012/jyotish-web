#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_reading.py — 計算JSON から「完成鑑定文（お客様モードの散文）」を作る。

流れ（Phase 2 の中心）:
    compute_chart() の JSON(data)
      → 材料ボード生成（career_findings_mvp.build_board を再利用）
      → 執筆プロンプト＋象意辞典＋文体メモ とともに Claude API へ
      → 完成鑑定文（markdown 文字列）を返す

方針（執筆プロンプトの原則をそのまま踏襲）:
    ・材料ボードに出ている「材料の範囲内」だけで書く。作り話・一般論を足さない。
    ・断定を避け、含みのある優しい語り口。相手を名前で呼ぶ。
    ・出力は「鑑定者が最終確認する下書き」。最終責任と最終文は人間。

APIキーは環境変数 ANTHROPIC_API_KEY か、呼び出し側から api_key= で渡す
（Streamlit の st.secrets を app.py 側で解決して渡す想定）。使うたび従量課金。
"""
import json
import os
import re
import sys
import tempfile

# --- 執筆ロジック(01)の場所。公開用に career_findings_mvp.py と執筆プロンプト等を
#     この下の career/ に同梱(vendoring)済み（元は ../01_Claudeホロスコープ仕事案/ を参照）。
_HERE = os.path.dirname(os.path.abspath(__file__))
_CAREER_DIR = os.path.join(_HERE, "career")
if _CAREER_DIR not in sys.path:
    sys.path.insert(0, _CAREER_DIR)

import career_findings_mvp  # noqa: E402  （sys.path 追加後に import）

# 執筆に渡す参照ドキュメント（01 フォルダ内）。
_REF_DOCS = [
    "執筆プロンプト_簡易鑑定_仕事.md",
    "象意辞典_仕事.md",
    "文体・表現の癖メモ_仕事.md",
]

MODEL = "claude-opus-5"

# 考える量（thinking の深さ）。low / medium / high / xhigh / max が指定できる。
# 2026-09-07に実測して "high" のままにすると決めた。low/medium/high の3水準で
# 鑑定文を生成して比べたところ、費用は1回$0.154〜$0.170（差は約2円）で
# ほぼ変わらず、品質もどれも良好だった。このアプリの費用の約6割は毎回送る
# 固定プロンプト（象意辞典など15,180トークン）が占めていて、考える量は
# 費用にほとんど効かない。したがってeffortはコスト調整には使えない。
# 下げる意味がないので、品質がいちばん安定する既定値のままにしておく。
EFFORT = "high"


def build_board_from_data(data: dict):
    """compute_chart の JSON(dict) から材料ボードのテキストと chart を返す。

    career_findings_mvp.build_board() はファイルパスを取る作りなので、
    data を一時JSONに書き出して渡す（スキーマは検証済みで互換）。
    """
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as tf:
            json.dump(data, tf, ensure_ascii=False)
            tmp_path = tf.name
        board_text, chart = career_findings_mvp.build_board(tmp_path)
        return board_text, chart
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


def _load_reference_docs() -> str:
    """執筆プロンプト・象意辞典・文体メモを連結して返す。"""
    parts = []
    for name in _REF_DOCS:
        path = os.path.join(_CAREER_DIR, name)
        with open(path, encoding="utf-8") as fp:
            parts.append(f"\n\n===== {name} =====\n\n" + fp.read())
    return "".join(parts)


_SYSTEM_FRAMING = """\
あなたはインド占星術（ジョーティシュ）の「仕事（職業の方向性・適性）」を鑑定する執筆者です。
以下に添える【執筆プロンプト】【象意辞典】【文体・表現の癖メモ】に厳密に従ってください。

守ること（最優先）:
・渡された「材料ボード」に出ている材料の範囲内だけで書く。材料にないこと（作り話・一般論・
  当たり障りのないバーナム）は足さない。
・結論を断定しすぎない。「〜かもしれません」「〜こともあります」「〜と考えられます」のように
  含みを持たせ、相手を名前で呼ぶ、優しい語り口。
・出力は「お客様モード」の散文。出典記号や専門用語は控えめに。お客様が読んで安心できる温度で。
・これは鑑定者が最終確認する下書きです。もっともらしく整えることより、材料への忠実さを優先。

出力の体裁（標準書式・厳守）:
  既存の配布ワークシートと体裁をそろえるため、必ず次の Markdown 構成で出力すること。
  タイトル直下にメタ情報（対象/作成日/材料ボード等）を書かない。最初の "##" より前の行は
  本文としてそのまま印字されるため、タイトル行の次はすぐ最初の見出しに入ること。

  # 仕事の方向性について

  ## あなたという器
  （1室＝その人自身の性質）
  ## 仕事の中心にあるもの
  （10室＝仕事の中心となる配置）
  ## 活かせる強み
  （支持材料＝後押しする配置・才能）
  ## 心に留めておきたいこと
  （反証材料＝慎重に見る点。断定せず柔らかく）
  ## その力は見えないところで育ちます
  （中立リフレーム＝反証を希望に転じる）
  ## 具体的なお仕事の一例
  （材料ボードに出ている職業キーワード＝10室支配星の在住ハウスの方向、
    関与している惑星やカラカの象徴領域から、実際に想像しやすい具体的な
    職業・職種の候補を数個挙げる。以下を必ず守る:
    ・候補は材料ボードにある職業キーワードの範囲から選ぶ。材料にない職種を
      思いつきで足さない。挙げる根拠が材料ボードのどの配置かを自分の中で
      確認してから書く。
    ・断定しない。「たとえば〜のようなお仕事」「〜なども考えられます」と
      あくまで一例・ヒントとして示し、これに限られるという印象を与えない。
    ・3〜6個程度を、箇条書きではなく散文の中で自然に挙げる。
    ・「必ず向いている／これをやるべき」といった強い言い方はしない。
      最後に「もちろんこれは一例で、活かし方はいろいろあります」の一文を添える。）
  ## ひとことメッセージ
  （締めの一言）

分量（厳守）:
  全体で 1,300〜1,500 字程度に収めること（見出しを含む）。この鑑定文はそのまま
  配布用A4ワークシートの2ページ目に流し込まれるため、これを超えると末尾が
  印刷されずに欠落する（2026-09-07、実際に「ひとことメッセージ」がまるごと
  消えているのを発見して分量指示を追加した）。
  上の7つの見出しはすべて残したうえで、各節をおおむね150〜250字にまとめる。
  節を削ったり材料を落としたりするのではなく、一文一文の言い回しを締めて短くすること。
"""


# 鑑定文に混ざってはいけない文字体系（ギリシャ・キリル・ヘブライ・アラビア・
# デーヴァナーガリー・タイ・ハングル）。2026-09-07、生成した鑑定文5本のうち1本に
# ロシア語の単語（"людям"）が紛れ込んでいるのを発見したため検査を入れた。
# このアプリは一般利用者が使い、鑑定者の手直しが入らないまま配布物になるので、
# 明らかな異物はここで弾いて作り直す。
_FOREIGN_SCRIPT = re.compile(
    "["
    "\u0370-\u03FF"   # ギリシャ
    "\u0400-\u052F"   # キリル
    "\u0590-\u05FF"   # ヘブライ
    "\u0600-\u06FF"   # アラビア
    "\u0900-\u097F"   # デーヴァナーガリー
    "\u0E00-\u0E7F"   # タイ
    "\uAC00-\uD7AF"   # ハングル
    "]+"
)


def foreign_script_in(text):
    """鑑定文に日本語以外の文字体系が紛れていれば、その断片のリストを返す。"""
    return _FOREIGN_SCRIPT.findall(text or "")


def build_reading(data, api_key=None, effort=None):
    """計算JSON(data) から完成鑑定文（markdown 文字列）を生成して返す。

    api_key を渡さない場合は環境変数 ANTHROPIC_API_KEY 等から自動解決する。
    effort を渡すとその回だけ考える量を変えられる（省略時は EFFORT）。

    出力に日本語以外の文字体系が紛れた場合は一度だけ生成し直す（foreign_script_in 参照）。
    """
    import anthropic  # 遅延 import（未インストールでも import 時にこけないように）

    board_text, chart = build_board_from_data(data)
    name = chart.get("meta", {}).get("name", "").strip() or "この方"

    system_text = _SYSTEM_FRAMING + _load_reference_docs()
    user_text = (
        f"次は {name} さんの材料ボードです。この材料の範囲内だけで、"
        f"{name} さんの簡易鑑定文（お客様モードの散文）を書いてください。\n\n"
        f"{board_text}"
    )

    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

    def _generate():
        # system は安定プレフィックス → cache_control で繰り返し実行のコストを抑える。
        with client.messages.stream(
            model=MODEL,
            max_tokens=4000,
            thinking={"type": "adaptive"},
            output_config={"effort": effort or EFFORT},
            system=[
                {
                    "type": "text",
                    "text": system_text,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_text}],
        ) as stream:
            message = stream.get_final_message()
        return "".join(
            block.text for block in message.content if block.type == "text"
        ).strip()

    # まれに日本語以外の文字が紛れることがある（実測で5本に1本）。配布物に
    # そのまま載ると事故なので、見つけたら一度だけ作り直す。2回目も駄目なら
    # そのまま返し、呼び出し側（app.py）が画面で警告する。
    reading = _generate()
    stray = foreign_script_in(reading)
    if stray:
        print(f"[warn] 鑑定文に日本語以外の文字 {stray} が混入したため生成し直します。")
        reading = _generate()
        if foreign_script_in(reading):
            print("[warn] 生成し直しても混入が残りました。呼び出し側で警告してください。")
    return reading


if __name__ == "__main__":
    # 単体テスト：チャートJSONのパスを引数に渡すと、材料ボードと鑑定文を表示する。
    if len(sys.argv) < 2:
        print("使い方: python3 build_reading.py <chart_data.json>")
        sys.exit(1)
    with open(sys.argv[1], encoding="utf-8") as fp:
        _data = json.load(fp)
    _board, _ = build_board_from_data(_data)
    print(_board)
    print("\n\n========== 鑑定文（下書き） ==========\n")
    print(build_reading(_data))
