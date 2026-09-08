#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_worksheet_pdf.py — 鑑定文(markdown文字列) ＋ 計算JSON から、
2枚綴じワークシートPDF（1p目チャート／2p目鑑定文・A4）のバイト列を作る。

チャート図（1ページ目）は、画面表示（app.py）とまったく同じ
generate_chart_auto の部品一覧（build_primitives）から描く（chart_bridge.py で
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
    ・OSに別途インストールが要る外部コマンド（rsvg-convert / ghostscript）には
      頼らない。Streamlit Cloud の土台OSのサポート終了で apt が使えなくなり、
      それらを入れられなくなったため（2026-09-08）。SVG→PDF変換もフォントの
      軽量化も、pip で入る範囲（PyMuPDF・fontTools）だけで完結させる。
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import fitz  # PyMuPDF

_HERE = os.path.dirname(os.path.abspath(__file__))
_SHEET_DIR = os.path.join(_HERE, "sheet")  # 公開用に同梱(vendoring)済み（元は ../02_jyotish_sheet/）
if _SHEET_DIR not in sys.path:
    sys.path.insert(0, _SHEET_DIR)

import make_worksheet_set  # noqa: E402（sys.path 追加後に import。bind_a4/CALIB/build_reading を使う）
import render_sheet  # noqa: E402（同梱フォントのパス解決と hex2rgb を借りる）

import generate_chart_auto as gca  # ← 画面表示と同じチャート部品ジェネレータ
from chart_bridge import chart_json_to_svg_data  # ← JSON→描画用データの橋渡し（app.pyと共通）


def _font_paths():
    """同梱の NotoSerifJP（明朝）の実ファイルパスを (通常, 太字) で返す。"""
    calib = render_sheet.load_json(str(make_worksheet_set.CALIB))
    return (str(render_sheet.ROOT / calib["fonts"]["regular"]),
            str(render_sheet.ROOT / calib["fonts"]["bold"]))


# ---------- フォントの絞り込み ----------
# NotoSerifJP は日本語の全文字を持つため1書体で約25MBあり、そのまま埋め込むと
# 2ページで約80MBのPDFになる。以前は ghostscript が「使った文字だけ」に絞って
# くれていたが、Streamlit Cloud の土台OS（Debian bullseye）のサポート終了で
# OS側にghostscriptを入れられなくなった（2026-09-08）。そこでPythonだけで
# 同じことをする。PyMuPDF内蔵の subset_fonts() はこのOTFを扱えず
# （"Reserved charstring byte" で失敗）、fallback=True 側にも不具合があるため使わない。

def _collect_strings(obj, out):
    """入れ子のdict/listから文字列だけを拾う（チャートJSONの取りこぼし防止）。"""
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect_strings(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _collect_strings(v, out)


def _used_characters(data, reading_md, primitives):
    """PDFに現れうる文字を集める。多めに入れても数KBしか増えないので、
    取りこぼし（＝その字だけ印字されない事故）を防ぐ側に寄せる。"""
    parts = [reading_md, "".join(chr(c) for c in range(0x20, 0x7F))]
    parts += [p["s"] for p in primitives if p["t"] == "text"]
    _collect_strings(data.get("meta", {}), parts)
    calib = render_sheet.load_json(str(make_worksheet_set.CALIB))
    _collect_strings(calib.get("reading", {}).get("title", {}), parts)
    return set("".join(parts))


def _subset_font(src_path, chars, dst_path):
    import io
    from fontTools.subset import Options, Subsetter
    from fontTools.ttLib import TTFont

    font = TTFont(src_path, lazy=True)
    options = Options()
    # 合字・カーニング・縦書き用の表は、PyMuPDF の文字描画が参照しないので落とす
    # （絞り込みが約2倍速くなり、フォントも小さくなる。字幅は hmtx が持つので不変）。
    options.drop_tables += ["DSIG", "GSUB", "GPOS", "GDEF", "BASE",
                            "vhea", "vmtx", "VORG"]
    # retain_gids は必須。これを外すと文字番号が振り直され、MuPDFが日本語の字形を
    # 見つけられずPDF上で日本語だけ真っ白に消える（英数字は出るので気づきにくい）。
    # 番号を保つとフォントファイル自体は約770KBになるが、中身は空の字形ばかりなので
    # PDFに圧縮して入れると150KB程度に収まる。
    options.retain_gids = True
    subsetter = Subsetter(options=options)
    subsetter.populate(text="".join(sorted(chars)))
    subsetter.subset(font)
    buf = io.BytesIO()
    font.save(buf)
    font.close()
    Path(dst_path).write_bytes(buf.getvalue())


def _make_subset_fonts(chars, tmp_dir):
    """使う文字だけに絞ったフォントを一時フォルダに作り、(通常, 太字) のパスを返す。"""
    reg_src, bold_src = _font_paths()
    reg_dst = Path(tmp_dir) / "subset-regular.otf"
    bold_dst = Path(tmp_dir) / "subset-bold.otf"
    _subset_font(reg_src, chars, reg_dst)
    _subset_font(bold_src, chars, bold_dst)
    return str(reg_dst), str(bold_dst)


def _calib_with_fonts(reg_font, bold_font, tmp_dir):
    """フォントだけ差し替えた calibration.json を一時フォルダに作り、そのパスを返す。

    render_reading は calibration.json の fonts を `ROOT / 値` で解決するが、
    値が絶対パスならそのまま採用される（pathlib の仕様）。この抜け道を使うことで、
    手元版から複製している sheet/ 側のファイルを一切変更せずに、
    絞り込み済みフォントを2ページ目にも使わせる。
    """
    calib = render_sheet.load_json(str(make_worksheet_set.CALIB))
    calib["fonts"] = {"regular": reg_font, "bold": bold_font}
    path = Path(tmp_dir) / "calibration.json"
    path.write_text(json.dumps(calib, ensure_ascii=False), encoding="utf-8")
    return str(path)


def _draw_text(page, fonts, p):
    """部品1つぶんの文字を描く。SVGの text-anchor と letter-spacing を再現する。"""
    font = fonts[p["bold"]]
    size, spacing, s = p["size"], p["spacing"], p["s"]
    if spacing:
        widths = [font.text_length(ch, fontsize=size) for ch in s]
        total = sum(widths) + spacing * len(s)
    else:
        widths = None
        total = font.text_length(s, fontsize=size)

    x = p["x"]
    if p["anchor"] == "middle":
        x -= total / 2
    elif p["anchor"] == "end":
        x -= total

    fontname = "njpb" if p["bold"] else "njp"
    color = render_sheet.hex2rgb(p["fill"])
    if spacing:
        # SVGの字間は各文字の前後に半分ずつ入る（librsvgが使うPangoの流儀）
        cur = x + spacing / 2
        for ch, w in zip(s, widths):
            page.insert_text((cur, p["y"]), ch, fontname=fontname, fontsize=size, color=color)
            cur += w + spacing
    else:
        page.insert_text((x, p["y"]), s, fontname=fontname, fontsize=size, color=color)


def _draw_prim(page, fonts, p):
    t = p["t"]
    if t == "text":
        _draw_text(page, fonts, p)
    elif t == "rect":
        rect = fitz.Rect(p["x"], p["y"], p["x"] + p["w"], p["y"] + p["h"])
        # PyMuPDF の radius は短辺に対する比率で指定する
        radius = p["rx"] / min(p["w"], p["h"]) if p["rx"] else None
        page.draw_rect(
            rect,
            color=render_sheet.hex2rgb(p["stroke"]) if p["stroke"] else None,
            fill=render_sheet.hex2rgb(p["fill"]) if p["fill"] else None,
            width=p["width"] if p["stroke"] else 0,
            radius=radius,
        )
    elif t == "line":
        page.draw_line((p["x1"], p["y1"]), (p["x2"], p["y2"]),
                       color=render_sheet.hex2rgb(p["stroke"]), width=p["width"])
    elif t == "polygon":
        pts = p["points"]
        page.draw_polyline([*pts, pts[0]],
                           color=render_sheet.hex2rgb(p["stroke"]), width=p["width"])
    elif t == "circle":
        page.draw_circle((p["cx"], p["cy"]), p["r"],
                         color=None, fill=render_sheet.hex2rgb(p["fill"]),
                         fill_opacity=p["opacity"])
    else:
        raise ValueError(f"未知の描画部品: {t}")


def _build_chart_pdf(primitives, fonts_paths, out_path):
    """画面表示とまったく同じ部品一覧から、チャート図のPDFを直接描いて保存する。

    以前は SVG を書き出して外部コマンド rsvg-convert でPDF化していたが、
    Streamlit Cloud の土台OS（Debian bullseye）のサポート終了で apt が使えなくなり、
    OS側にlibrsvgを入れられなくなった（2026-09-08）。そこで中間のSVGをやめ、
    PyMuPDF の描画機能で同じ絵を直接描くことにして、外部コマンド依存をなくした。

    ※ PyMuPDF の「SVG読み取り機能」には戻さないこと。font-family指定を無視して
      内蔵CJKフォールバックフォントを使い、長音記号「ー」のグリフを落とす
      （2026-07-09に実機で確認。例：「ラーフ」→「ラフ」）。ここで使っているのは
      フォントを明示して文字を直接描く機能で、それとは別物。
    """
    reg_font, bold_font = fonts_paths
    doc = fitz.open()
    page = doc.new_page(width=gca.W, height=gca.H)
    page.insert_font(fontname="njp", fontfile=reg_font)
    page.insert_font(fontname="njpb", fontfile=bold_font)
    fonts = {False: fitz.Font(fontfile=reg_font), True: fitz.Font(fontfile=bold_font)}

    for prim in primitives:
        _draw_prim(page, fonts, prim)

    doc.save(str(out_path), deflate=True, garbage=4)
    doc.close()


def reading_fit_report(reading_md):
    """鑑定文が2ページ目の本文枠に収まるかを、実際の組版ロジックで事前に確かめる。

    収まるなら None、収まらないなら利用者向けの説明文（str）を返す。

    render_reading.draw_flow は枠に入りきらない分を黙って捨てる作りで、警告も
    サーバーログに print されるだけで画面には出ない。そのため2026-09-07まで
    「鑑定文の末尾（ひとことメッセージ）がまるごと欠けたPDF」が、誰にも
    気づかれないまま作られていた。同じことが二度と起きないよう、PDFを作る前に
    ここで検知して、呼び出し側（app.py）が画面に警告を出せるようにしている。
    """
    import fitz
    import render_reading as rr

    calib = rr.load_json(str(make_worksheet_set.CALIB))
    cr = calib["reading"]
    flow = cr["flow"]
    rect = fitz.Rect(cr["body"]["x0"], cr["body"]["y0"], cr["body"]["x1"], cr["body"]["y1"])
    reg_font = str(rr.ROOT / calib["fonts"]["regular"])
    bold_font = str(rr.ROOT / calib["fonts"]["bold"])

    # parse_md はファイルパスを取る作りなので、いったん一時ファイルへ書き出す
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as tf:
            tf.write(reading_md)
            tmp_path = tf.name
        _, sections = rr.parse_md(tmp_path)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

    blocks = rr.build_blocks(sections)
    body_size, fits, overflow = rr.choose_body_size(reg_font, bold_font, blocks, rect, flow)
    if fits:
        return None

    # 和文は概ね「1文字＝フォントサイズ幅」なので、溢れた高さから文字数を概算する
    line_h = body_size * flow["line_height"]
    chars_per_line = max(1, int(rect.width / body_size))
    over_chars = max(1, int(overflow / line_h * chars_per_line))
    return (f"鑑定文が長いため、末尾のおよそ{over_chars}文字がPDFに入りきりません"
            f"（このまま作ると、最後の見出しの文章が欠けた状態になります）。")


def build_worksheet_pdf(data, reading_md, name):
    """data(dict) と reading_md(str) から2枚綴じワークシートPDFを生成し、
    そのバイト列を返す（チャート1ページ目＝新デザイン／鑑定文2ページ目・A4）。
    sheet/output/ 相当の場所には何も残さない（一時フォルダで生成→読み取り→削除）。
    """
    tmp_dir = None
    tmp_json_path = None
    tmp_md_path = None
    try:
        tmp_dir = Path(tempfile.mkdtemp(prefix="jyotish_worksheet_"))

        primitives = gca.build_primitives(chart_json_to_svg_data(data, name.replace("_", " ")))
        fonts_paths = _make_subset_fonts(
            _used_characters(data, reading_md, primitives), tmp_dir
        )

        # 1ページ目：チャート（画面と同じ部品一覧から直接PDF化）
        chart_pdf = tmp_dir / f"{name}.pdf"
        _build_chart_pdf(primitives, fonts_paths, chart_pdf)

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
            tmp_md_path, tmp_json_path,
            _calib_with_fonts(*fonts_paths, tmp_dir), str(reading_pdf)
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
