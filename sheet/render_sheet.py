#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
インド占星術ワークシート自動生成
  入力 : チャートデータJSON（パラーシャラの光から起こした構造化データ）
  土台 : 装飾入り台紙PDF（罫線・サインラベル・凡例は印刷済み）
  設定 : calibration.json（この台紙専用の座標。台紙を変えたら測り直す）
  出力 : 台紙の上に「惑星＋度数」「ハウス番号」「氏名」「生年月日」を刷り込んだPDF

設計方針:
  - 台紙は描き直さない。上から必要な文字だけをスタンプする（オーバーレイ）。
  - 何を描くかは JSON、どこに描くかは calibration.json。コードは橋渡しに徹する。
"""
import json
import argparse
import tempfile
from pathlib import Path
import fitz  # PyMuPDF

ROOT = Path(__file__).resolve().parent
# チャートJSONは 00_ホロPDFからJSON生成 パイプラインの output/JSON を直接読む。
# 2026-06-16 一本化：02 専用の data/ コピーは廃止（重複・手コピーを解消）。
CHART_JSON_DIR = ROOT.parent / "00_ホロPDFからJSON生成" / "output" / "JSON"


# ---------- 小道具 ----------
def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def load_json(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def shrink_with_ghostscript(src_pdf, dst_pdf):
    """ghostscript があれば埋め込みフォントをサブセット化して軽量化。
    無ければ src をそのままコピー（描画は正しいがファイルは大きい）。
    戻り値: 軽量化できたら True。"""
    import shutil
    import subprocess
    gs = shutil.which("gs") or shutil.which("gswin64c")
    if not gs:
        shutil.copyfile(src_pdf, dst_pdf)
        return False
    cmd = [
        gs, "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.5",
        "-dSubsetFonts=true", "-dEmbedAllFonts=true",
        "-dNOPAUSE", "-dQUIET", "-dBATCH",
        f"-sOutputFile={dst_pdf}", src_pdf,
    ]
    try:
        subprocess.run(cmd, check=True)
        return True
    except Exception:
        shutil.copyfile(src_pdf, dst_pdf)
        return False


class Sheet:
    """1ページ分の描画コンテキスト。フォント登録と幅計測をまとめる。"""

    def __init__(self, page, calib, font_reg, font_bold):
        self.page = page
        self.c = calib
        # ページにフォントを埋め込み（insert_text から名前で参照）
        page.insert_font(fontname="njp", fontfile=font_reg)
        page.insert_font(fontname="njpb", fontfile=font_bold)
        # 幅計測用（実フォントの字送りを使う＝記号幅が日本語1字でも英字2字でも正確）
        self.fr = fitz.Font(fontfile=font_reg)
        self.fb = fitz.Font(fontfile=font_bold)

    def w(self, text, size, bold=False):
        f = self.fb if bold else self.fr
        return f.text_length(text, fontsize=size)

    def text(self, x, y, s, size, color, bold=False):
        """(x, y) はベースライン基準（左下原点の1文字目）。"""
        self.page.insert_text(
            (x, y), s,
            fontname="njpb" if bold else "njp",
            fontsize=size, color=color,
        )


# ---------- ヘッダ（タスク②）----------
def format_birth(meta):
    b = meta["birth"]
    y, m, d = b["date"].split("-")
    hh, mm = b["time"].split(":")[:2]
    pl = meta["place"]
    place = ", ".join(x for x in (pl.get("city"), pl.get("state"), pl.get("country")) if x)
    return f"{int(y)}/{int(m)}/{int(d)} {hh}:{mm}  /  {place}"


def draw_header(sheet, data):
    c = sheet.c["header"]
    meta = data["meta"]

    # 氏名（既定は中央寄せ。下の2行と中心を揃える。印刷済み『さん』には重ねない）
    nm = c["name"]
    name = meta.get("name", "")
    w = sheet.w(name, nm["font"], bold=True)
    if nm.get("mode", "center") == "center":
        x = nm.get("center_x", c["birth"]["center_x"]) - w / 2
        max_right = nm.get("max_right")
        if max_right is not None and x + w > max_right:
            x = max_right - w  # 長い名前は『さん』に被らないよう右端でクランプ
    else:  # 旧方式：『さん』の直前に右寄せ
        x = nm["right_x"] - w
    sheet.text(x, nm["baseline_y"], name, nm["font"], hex2rgb(nm["color"]), bold=True)

    # 生年月日（副題の下、中央寄せ）
    bz = c["birth"]
    line = format_birth(meta)
    x = bz["center_x"] - sheet.w(line, bz["font"]) / 2
    sheet.text(x, bz["baseline_y"], line, bz["font"], hex2rgb(bz["color"]))


# ---------- グリッド（タスク①＋③）----------
def cell_box(calib, sign):
    col, row = calib["sign_layout"][sign]
    gx, gy = calib["grid"]["x"], calib["grid"]["y"]
    return gx[col], gy[row], gx[col + 1], gy[row + 1]  # x0, y0, x1, y1


def planet_entry(data, token):
    """token から (記号, 度数, 逆行, 色) を返す。As は ascendant から拾う。"""
    style = data["_calib"]["planet_style"][token]
    if token == "As":
        return style["sym"], data["ascendant"]["degree"], False, style["color"]
    p = data["planets"][token]
    return style["sym"], p.get("degree", ""), bool(p.get("retrograde", False)), style["color"]


def draw_cell(sheet, data, sign, house_no, planets):
    c = sheet.c
    L = c["cell_layout"]
    x0, y0, x1, y1 = cell_box(c, sign)

    # --- 惑星スタック（左上から下へ）---
    for i, token in enumerate(planets):
        sym, deg, retro, color = planet_entry(data, token)
        col = hex2rgb(color)
        bx = x0 + L["planet_left_inset"]
        by = y0 + L["planet_top_inset"] + i * L["row_step"]

        sheet.text(bx, by, sym, L["font_glyph"], col, bold=True)
        cx = bx + sheet.w(sym, L["font_glyph"], bold=True) + L["glyph_to_deg_gap"]

        if retro:  # 逆行マーク R（小さめ・少し上）
            sheet.text(cx, by - 2.0, "R", L["font_retro"], col)
            cx += sheet.w("R", L["font_retro"]) + L["retro_gap"]

        sheet.text(cx, by, deg, L["font_deg"], col)

    # --- ハウス番号（右下に右寄せ）---
    hs = str(house_no)
    hx = x1 - L["house_right_inset"] - sheet.w(hs, L["font_house"])
    hy = y1 - L["house_bottom_inset"]
    sheet.text(hx, hy, hs, L["font_house"], hex2rgb(L["color_house"]))


def draw_chart(sheet, data, chart_key="D1"):
    houses = data["charts"][chart_key]["houses"]
    planets = data.get("planets", {})
    include_outer = data["meta"].get("include_outer_planets", True)

    def keep(token):
        # As は常に表示。外惑星は meta のトグルに従う。
        if token == "As":
            return True
        if not include_outer and planets.get(token, {}).get("outer"):
            return False
        return True

    def deg_minutes(token):
        # 度数 "DD:MM" を分に直す。元SVGに合わせ、セル内は度数の昇順で上から積む。
        if token == "As":
            d = data.get("ascendant", {}).get("degree", "")
        else:
            d = planets.get(token, {}).get("degree", "")
        try:
            dd, mm = d.split(":")[:2]
            return int(dd) * 60 + int(mm)
        except Exception:
            return 99999  # 度数不明は末尾へ

    for hno, h in houses.items():
        shown = sorted((t for t in h.get("planets", []) if keep(t)), key=deg_minutes)
        draw_cell(sheet, data, h["sign"], hno, shown)


# ---------- メイン ----------
def build(template_pdf, data_json, calib_json, out_pdf, chart_key="D1"):
    calib = load_json(calib_json)
    data = load_json(data_json)
    data["_calib"] = calib  # planet_entry から参照させる

    doc = fitz.open(template_pdf)
    page = doc[0]
    sheet = Sheet(
        page, calib,
        str(ROOT / calib["fonts"]["regular"]),
        str(ROOT / calib["fonts"]["bold"]),
    )

    draw_header(sheet, data)
    draw_chart(sheet, data, chart_key)

    # フル埋め込みで一旦保存（描画は正しいがCJKフォントで重い）→ gs でサブセット軽量化
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = tmp.name
    doc.save(tmp_path, deflate=True, garbage=4)
    doc.close()

    ok = shrink_with_ghostscript(tmp_path, out_pdf)
    Path(tmp_path).unlink(missing_ok=True)
    if not ok:
        print("[note] ghostscript が無いため軽量化をスキップしました（出力は正しいがサイズ大）。"
              "`brew install ghostscript` 等で gs を入れると数十分の一になります。")
    return out_pdf


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="インド占星術ワークシート生成")
    ap.add_argument("--data", default=str(CHART_JSON_DIR / "Sato_Jun_chart_data.json"))
    ap.add_argument("--template", default=str(ROOT / "template/template.pdf"))
    ap.add_argument("--calib", default=str(ROOT / "calibration.json"))
    ap.add_argument("--out", default=str(ROOT / "output/sheet.pdf"))
    ap.add_argument("--chart", default="D1", help="使う分割図キー（既定 D1）")
    a = ap.parse_args()
    path = build(a.template, a.data, a.calib, a.out, a.chart)
    print("written:", path)
