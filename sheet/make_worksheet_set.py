#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2枚綴じワークシート（チャート＋鑑定文）を1つのA4・2ページPDFにまとめる。

  入力 : --name "<名前>"（例 Sato_Jun）。--data でチャートJSONを直接指定も可。
  処理 : 既存の build をそのまま再利用してチャートPDFと鑑定文PDFを作り、
         それらを A4 縦 2ページに綴じる。
  出力 : output/<名前>_set.pdf（生成後に open で開く）

設計方針:
  - 描画ロジックは持たない。チャートは render_sheet.build()、鑑定文は
    render_reading.build_reading() を呼ぶ（render_all.py と同じ流儀）。
  - 既存ファイル（render_sheet.py / render_reading.py / calibration.json）は変更しない。
    綴じる処理はこのスクリプトの中だけに閉じる。
  - 1ページ目：チャートPDFのページを A4 に「全体が収まるよう」縦横比を保って拡大し中央配置。
    倍率＝min(A4幅/元幅, A4高さ/元高さ)×余白係数。元ページのサイズは page.rect から読む。
  - 2ページ目：鑑定文PDF（すでにA4）は insert_pdf でそのまま追加（拡大しない）。
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

import fitz  # PyMuPDF

# 既存スクリプトの build と道具を再利用（描画ロジックを二重に持たない）
from render_sheet import ROOT, CHART_JSON_DIR, build as build_chart, shrink_with_ghostscript
from render_reading import build_reading, resolve_md

CALIB = ROOT / "calibration.json"
CHART_TEMPLATE = ROOT / "template" / "template.pdf"
OUT_DIR = ROOT / "output"

A4_W, A4_H = 595.28, 841.89  # A4 縦（PDFポイント）


# ---------- 綴じる ----------
def bind_a4(chart_pdf, reading_pdf, out_pdf, margin_factor=0.98):
    """チャートPDF（1ページ目・A4に拡大中央配置）と鑑定文PDF（2ページ目・そのまま）を
    A4縦2ページの1つのPDFに綴じる。"""
    out = fitz.open()

    # --- 1ページ目：チャートを A4 にフィットさせて中央配置 ---
    src = fitz.open(chart_pdf)
    sp = src[0]
    sw, sh = sp.rect.width, sp.rect.height  # 元ページの実寸（決め打ちしない）
    scale = min(A4_W / sw, A4_H / sh) * margin_factor
    dw, dh = sw * scale, sh * scale
    x0, y0 = (A4_W - dw) / 2, (A4_H - dh) / 2
    page1 = out.new_page(width=A4_W, height=A4_H)
    page1.show_pdf_page(fitz.Rect(x0, y0, x0 + dw, y0 + dh), src, 0)

    # --- 2ページ目：鑑定文（すでにA4）をそのまま追加 ---
    rd = fitz.open(reading_pdf)
    out.insert_pdf(rd)

    # フル埋め込みで一旦保存 → ghostscript があればサブセット軽量化（既存と同じ流儀）
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = tmp.name
    out.save(tmp_path, deflate=True, garbage=4)
    out.close()
    src.close()
    rd.close()

    ok = shrink_with_ghostscript(tmp_path, out_pdf)
    Path(tmp_path).unlink(missing_ok=True)
    if not ok:
        print("[note] ghostscript が無いため軽量化をスキップしました（出力は正しいがサイズ大）。"
              "`brew install ghostscript` 等で gs を入れると数十分の一になります。")
    return out_pdf


# ---------- 1人ぶんの生成 ----------
def make_set(name, data_json, out_set, chart_key="D1", md_path=None, margin_factor=0.98):
    """チャートPDFと鑑定文PDFを作り、A4・2ページに綴じる。
    個別PDF（<名前>.pdf / <名前>_reading.pdf）も output に残す。"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    chart_pdf = OUT_DIR / f"{name}.pdf"
    reading_pdf = OUT_DIR / f"{name}_reading.pdf"

    # チャート（render_sheet.build をそのまま）
    build_chart(str(CHART_TEMPLATE), str(data_json), str(CALIB), str(chart_pdf), chart_key)

    # 鑑定文（render_reading.build_reading をそのまま）
    md = Path(md_path) if md_path else resolve_md(name)
    if not md or not Path(md).exists():
        raise SystemExit(f"鑑定文 .md が見つかりません: name={name}（--md で指定もできます）")
    build_reading(str(md), str(data_json), str(CALIB), str(reading_pdf))

    # 綴じる
    bind_a4(chart_pdf, reading_pdf, str(out_set), margin_factor=margin_factor)
    return out_set


def open_file(p):
    try:
        subprocess.run(["open", str(p)], check=False)
    except Exception as e:
        print(f"[note] 自動で開けませんでした（手動で開いてください）: {e}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="チャート＋鑑定文を A4・2ページに綴じる")
    ap.add_argument("--name", default=None, help="名前キー（例 Sato_Jun）。未指定かつ --data も無ければ Sato_Jun")
    ap.add_argument("--data", default=None, help="チャートJSON（未指定なら 00 の output/JSON から名前で解決）")
    ap.add_argument("--md", default=None, help="鑑定文 .md（未指定なら名前から自動解決）")
    ap.add_argument("--out", default=None, help="出力PDF（未指定なら output/<名前>_set.pdf）")
    ap.add_argument("--chart", default="D1", help="使う分割図キー（既定 D1）")
    ap.add_argument("--margin", type=float, default=0.98, help="A4フィット時の余白係数（既定 0.98）")
    ap.add_argument("--no-open", dest="open_after", action="store_false",
                    help="生成後に自動で開かない")
    a = ap.parse_args()

    # 名前・JSON の解決（--data 優先。名前は出力ファイル名と鑑定文解決に使う）
    if a.data:
        data = Path(a.data)
        if not data.exists():
            raise SystemExit(f"チャートJSONが見つかりません: {data}")
        stem = data.stem
        name = a.name or (stem[:-len("_chart_data")] if stem.endswith("_chart_data") else stem)
    else:
        name = a.name or "Sato_Jun"
        data = CHART_JSON_DIR / f"{name}_chart_data.json"
        if not data.exists():
            raise SystemExit(f"チャートJSONが見つかりません: {data}")

    out_set = Path(a.out) if a.out else (OUT_DIR / f"{name}_set.pdf")
    out_set.parent.mkdir(parents=True, exist_ok=True)

    make_set(name, str(data), str(out_set), chart_key=a.chart, md_path=a.md, margin_factor=a.margin)
    print("written:", out_set)
    if a.open_after:
        open_file(out_set)
