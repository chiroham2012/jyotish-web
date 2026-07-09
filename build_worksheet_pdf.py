#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_worksheet_pdf.py — 鑑定文(markdown文字列) ＋ 計算JSON から、
2枚綴じワークシートPDF（1p目チャート／2p目鑑定文・A4）のバイト列を作る。

チャート図（1ページ目）は、画面表示（app.py）とまったく同じ
generate_chart_auto.build_svg() の出力をそのままPDF化する（chart_bridge.py で
橋渡し）。こうすることで「画面とPDFでチャート図のデザインが食い違う」ことが
起きなくなる（2026-07-08、旧テンプレート render_sheet.py 経由だと画面側の
デザイン改善が反映されない食い違いが実際に発生し、これに切り替えて解消した）。

鑑定文（2ページ目）は、sheet/render_reading.py の本文流し込みロジック
（禁則処理・字下げ・自動フォント調整）をそのまま再利用する
（このページ自体はチャート図のデザインに依存しないため、旧来のロジックで問題ない）。
2ページを綴じる処理も、sheet/make_worksheet_set.bind_a4() をそのまま再利用する。

sheet/ 配下（render_sheet.py / render_reading.py / make_worksheet_set.py /
calibration.json / fonts/）は、本番の02_jyotish_sheetフォルダから公開用に
同梱(vendoring)したコピー。render_sheet.py の南インド式チャート描画機能自体は
このアプリでは使わないが、make_worksheet_set.py がimportするため同梱が必要。

方針:
    ・生成物はすべて一時フォルダに書き、読み取り後に削除する
      （sheet/output/ 相当の場所には何も残さない。保存先はStreamlitの
        ダウンロードボタン経由で利用者自身が選べる）。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
_SHEET_DIR = os.path.join(_HERE, "sheet")  # 公開用に同梱(vendoring)済み（元は ../02_jyotish_sheet/）
if _SHEET_DIR not in sys.path:
    sys.path.insert(0, _SHEET_DIR)

import make_worksheet_set  # noqa: E402（sys.path 追加後に import。bind_a4/CALIB/build_reading を使う）

from generate_chart_auto import build_svg  # ← 画面表示と同じチャートSVGジェネレータ
from chart_bridge import chart_json_to_svg_data  # ← JSON→SVG用データの橋渡し（app.pyと共通）


_RSVG_CANDIDATES = ["rsvg-convert", "/opt/homebrew/bin/rsvg-convert", "/usr/local/bin/rsvg-convert"]


def _find_rsvg_convert():
    """rsvg-convert の実行ファイルを探す。見つからなければ分かりやすいエラーにする。"""
    for candidate in _RSVG_CANDIDATES:
        path = shutil.which(candidate) or (candidate if os.path.exists(candidate) else None)
        if path:
            return path
    raise RuntimeError(
        "rsvg-convert が見つかりません。ターミナルで `brew install librsvg` を実行してください。"
    )


def _build_chart_pdf(data, name, tmp_dir, out_path):
    """画面表示と同じ新デザインのSVGを、そのままPDF化してファイルに保存する。

    SVG→PDF変換は rsvg-convert（librsvg）を使う。PyMuPDF(fitz)の内蔵SVGレンダラーは
    font-family指定を無視して常に内蔵CJKフォールバックフォントを使い、そのフォントが
    長音記号「ー」のグリフを落とす不具合があるため（2026-07-09 に実機で確認・再現済み。
    例：「ラーフ」→「ラフ」）、フォント名の変更では直らず変換エンジン自体を差し替えた。
    """
    display_name = name.replace("_", " ")
    svg_data = chart_json_to_svg_data(data, display_name)
    svg = build_svg(svg_data)
    svg_path = Path(tmp_dir) / f"{name}.svg"
    svg_path.write_text(svg, encoding="utf-8")
    # -d/-p 72dpi 指定で、SVGのユーザー単位(px)とPDFのポイント(pt)を1:1にする
    # （旧fitz変換時のページサイズ=SVGのwidth/heightそのままpt、と揃えるため）。
    subprocess.run(
        [_find_rsvg_convert(), "-f", "pdf", "-d", "72", "-p", "72", "-o", str(out_path), str(svg_path)],
        check=True,
    )


def build_worksheet_pdf(data, reading_md, name):
    """data(dict) と reading_md(str) から2枚綴じワークシートPDFを生成し、
    そのバイト列を返す（チャート1ページ目＝新デザインSVG／鑑定文2ページ目・A4）。
    02_jyotish_sheet/output/ には何も残さない（一時フォルダで生成→読み取り→削除）。
    """
    tmp_dir = None
    tmp_json_path = None
    tmp_md_path = None
    try:
        tmp_dir = Path(tempfile.mkdtemp(prefix="jyotish_worksheet_"))

        # 1ページ目：チャート（新デザインSVGを直接PDF化）
        chart_pdf = tmp_dir / f"{name}.pdf"
        _build_chart_pdf(data, name, tmp_dir, chart_pdf)

        # 材料をいったんファイルへ（既存の render_reading.build_reading はファイル入力の作り）
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as tf:
            json.dump(data, tf, ensure_ascii=False)
            tmp_json_path = tf.name

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as tf:
            tf.write(reading_md)
            tmp_md_path = tf.name

        # 2ページ目：鑑定文（既存の render_reading.build_reading をそのまま再利用）
        reading_pdf = tmp_dir / f"{name}_reading.pdf"
        make_worksheet_set.build_reading(
            tmp_md_path, tmp_json_path, str(make_worksheet_set.CALIB), str(reading_pdf)
        )

        # 綴じる（既存の bind_a4 をそのまま再利用）
        out_pdf = tmp_dir / f"{name}_set.pdf"
        make_worksheet_set.bind_a4(str(chart_pdf), str(reading_pdf), str(out_pdf))

        return Path(out_pdf).read_bytes()
    finally:
        for p in (tmp_json_path, tmp_md_path):
            if p and os.path.exists(p):
                os.remove(p)
        if tmp_dir and tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    # 単体テスト：チャートJSONと鑑定文.mdのパスを渡すと、ワークシートPDFを生成する。
    if len(sys.argv) < 4:
        print("使い方: python3 build_worksheet_pdf.py <chart_data.json> <reading.md> <名前>")
        sys.exit(1)
    with open(sys.argv[1], encoding="utf-8") as fp:
        _data = json.load(fp)
    with open(sys.argv[2], encoding="utf-8") as fp:
        _md = fp.read()
    _pdf_bytes = build_worksheet_pdf(_data, _md, sys.argv[3])
    print(f"生成OK：{len(_pdf_bytes)} バイト")
