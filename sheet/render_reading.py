#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
鑑定文ワークシート自動生成
  入力 : 鑑定文の .md（# タイトル / ## 見出し＋本文…）と チャートデータJSON（meta 用）
  土台 : 飾り枠付きの「鑑定文ページ」。本番台紙が無いうちは簡易枠を自前で描く。
  設定 : calibration.json の "reading" ブロック（枠・タイトル・meta・本文矩形の座標）
  出力 : 02_jyotish_sheet/output/<名前>_reading.pdf

設計方針:
  - 描画ロジックは render_sheet.py を再利用する（フォント登録・幅計測・テキスト描画・
    テンプレ読み込み・meta 印字・ghostscript 軽量化）。ここで新しく持つのは
    「.md の読み取り」と「本文の流し込み＋自動フォント調整」だけ。
  - 何を描くかは .md／JSON、どこに描くかは calibration.json["reading"]。

本文の流し込み:
  - 飾り枠の内側の本文矩形に「見出し→本文→余白→次の見出し…」を上から流す。
  - 日本語の折り返しは PyMuPDF の insert_textbox に任せる（既存の NotoSerifJP）。
  - 既定サイズ（既定 11pt）で全体が矩形に入るか測り、入らなければ段階的に縮める
    （最小 既定 8pt）。見出しは本文に連動して縮む。最小でも入らなければ最小で詰めて
    「本文が約N行（約M文字）入りきりません」と警告する。
"""
import argparse
import math
import tempfile
from pathlib import Path

import fitz  # PyMuPDF

# render_sheet の道具をそのまま使う（描画ロジックを二重に持たない）
from render_sheet import (
    ROOT,
    CHART_JSON_DIR,
    Sheet,
    draw_header,
    hex2rgb,
    load_json,
    shrink_with_ghostscript,
)

# 鑑定文 .md の置き場（00→01→02 の並びに合わせた相対指定）
MD_DIR = ROOT.parent / "01_Claudeホロスコープ仕事案" / "鑑定文"


# ---------- .md の読み取り ----------
def parse_md(md_path):
    """鑑定文 .md を (タイトル, [(見出し, 本文), ...]) に分解する。

    - 先頭の『# 見出し』＝ページタイトル（最初の1つだけ。無ければ None）。
    - 『## 見出し』ごとに新しいセクション。続く段落が本文。
    - 見出しより前に本文がある場合は、見出し None のリード文として扱う。
    - 段落（空行区切り）は本文中で改行として保持する。
    """
    title = None
    sections = []        # [{"heading": str|None, "paras": [str]}]
    cur = None           # 現在のセクション
    buf = []             # 現在の段落の行バッファ

    def ensure_section(heading):
        nonlocal cur
        cur = {"heading": heading, "paras": []}
        sections.append(cur)

    def flush_para():
        nonlocal buf
        if not buf:
            return
        if cur is None:
            ensure_section(None)  # 見出し前のリード文
        # 折り返し前提の和文なので、連続行はそのまま連結する
        cur["paras"].append("".join(buf))
        buf = []

    for raw in Path(md_path).read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if line.startswith("## "):
            flush_para()
            ensure_section(line[3:].strip())
        elif line.startswith("# "):
            flush_para()
            if title is None:
                title = line[2:].strip()
            else:
                ensure_section(line[2:].strip())  # 2つ目以降の H1 は見出し扱い
        elif line.strip() == "":
            flush_para()                          # 空行＝段落の区切り
        else:
            buf.append(line.strip())
    flush_para()

    out = []
    for s in sections:
        body = "\n".join(p for p in s["paras"] if p)
        out.append((s["heading"], body))
    return title, out


def build_blocks(sections):
    """(見出し, 本文) のセクション列を、流し込み用の (種別, テキスト) 列に変換。
    種別は 'head'（見出し）か 'body'（本文）。"""
    blocks = []
    for heading, body in sections:
        if heading:
            blocks.append(("head", heading))
        if body.strip():
            blocks.append(("body", body))
    return blocks


# ---------- 日本語の作文ルール（禁則処理・字下げ）----------
# 行頭禁則：この文字は行の先頭に置かない（前の行末にぶら下げる）。
#   句読点・閉じ括弧・小書き仮名・長音など。全角/半角の両方を含める。
KINSOKU_HEAD = set(
    "、。，．・：；？！ー々ゝゞヽヾ゛゜…‥"
    "）〕］｝〉》」』】〟’”"
    "ぁぃぅぇぉっゃゅょゎゕゖァィゥェォッャュョヮヵヶ"
    ",.!?:;)]}>）」』"
)
# 行末禁則：この文字は行の末尾に置かない（次の行の先頭へ送る）。開き括弧など。
KINSOKU_TAIL = set("（〔［｛〈《「『【〘〖‘“([{<")

# 段落の字下げ（一マス下げ）に使う全角スペース1つぶんの幅。
INDENT_CHAR = "　"

# 英数字（半角の 0-9 A-Z a-z）。連続する並びは「11」「D1」のように途中で改行しない。
ASCII_ALNUM = set("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")


def _next_token(text, i):
    """text[i] から始まる1トークンを返す。半角英数字が続く並びはひとかたまり、
    それ以外は1文字。（英数字を行またぎで割らないため）"""
    if text[i] in ASCII_ALNUM:
        j = i
        while j < len(text) and text[j] in ASCII_ALNUM:
            j += 1
        return text[i:j]
    return text[i]


def _sizes(flow, body_size):
    """この本文サイズに対する (本文サイズ, 見出しサイズ, 行送り, 見出し後余白, 段落後余白)。"""
    head_size = body_size * flow["heading_scale"]
    line_height = flow["line_height"]
    head_gap = body_size * flow["head_gap_factor"]
    body_gap = body_size * flow["section_gap_factor"]
    return head_size, line_height, head_gap, body_gap


def wrap_paragraph(font, text, size, width, indent=False):
    """1段落を width に収まる行へ折り返す。日本語の禁則処理つき。
    返り値は [(行テキスト, 左オフセット), ...]。
      - indent=True のとき、最初の行だけ全角1マスぶん右に寄せる（字下げ）。
      - 行頭禁則文字は前の行末にぶら下げる（右端を少しはみ出して置く）＝ぶら下げ方式。
      - 行末禁則文字（開き括弧など）は次の行の先頭へ送る。
    """
    lines = []
    n = len(text)
    i = 0
    first = True
    indent_w = font.text_length(INDENT_CHAR, fontsize=size) if indent else 0.0
    while i < n:
        x_off = indent_w if (first and indent) else 0.0
        line = ""
        cur = x_off
        while i < n:
            tok = _next_token(text, i)  # 英数字の連続はひとかたまり（途中で割らない）
            tw = font.text_length(tok, fontsize=size)
            if cur + tw <= width:
                line += tok
                cur += tw
                i += len(tok)
                continue
            # ここで折り返し
            ch = text[i]
            if len(tok) == 1 and ch in KINSOKU_HEAD and line:
                # ぶら下げ：行頭禁則文字を今の行末にはみ出させて置く
                line += ch
                i += 1
                while i < n and text[i] in KINSOKU_HEAD:
                    line += text[i]
                    i += 1
            elif not line:
                # 行頭でトークンが幅を超える安全策（通常は起きない）：まるごと置く
                line += tok
                i += len(tok)
            break
        # 行末禁則：末尾が開き括弧なら1字を次の行へ送る（後ろにまだ文字がある時だけ）
        if i < n and len(line) > 1 and line[-1] in KINSOKU_TAIL:
            i -= 1
            line = line[:-1]
        lines.append((line, x_off))
        first = False
    if not lines:
        lines.append(("", indent_w if indent else 0.0))
    return lines


def layout_block(font, kind, txt, size, width, indent_body=True):
    """1ブロック（見出し or 本文）を折り返し済みの行リストにする。
    本文は空行区切りの段落ごとに折り返し、各段落の先頭行を字下げする。
    見出しは字下げしない。返り値は [(行テキスト, 左オフセット), ...]。"""
    lines = []
    if kind == "head":
        for para in txt.split("\n"):
            lines.extend(wrap_paragraph(font, para, size, width, indent=False))
    else:
        for para in txt.split("\n"):
            if not para.strip():
                continue
            lines.extend(wrap_paragraph(font, para, size, width, indent=indent_body))
    return lines


def measure_total_height(fonts, blocks, width, flow, body_size):
    """blocks を幅 width に自前折り返しで流したときに必要な総高さ（ポイント）を測る。
    fonts は (regular_font, bold_font) の fitz.Font タプル。"""
    reg, bold = fonts
    head_size, line_height, head_gap, body_gap = _sizes(flow, body_size)
    total = 0.0
    for kind, txt in blocks:
        if not txt.strip():
            continue
        size = head_size if kind == "head" else body_size
        font = bold if kind == "head" else reg
        lines = layout_block(font, kind, txt, size, width)
        total += len(lines) * size * line_height
        total += head_gap if kind == "head" else body_gap
    return total


def choose_body_size(reg_font, bold_font, blocks, rect, flow):
    """矩形に収まる最大の本文サイズを選ぶ。
    戻り値 (body_size, fits, overflow_height)。fits=False のときは最小サイズで、
    overflow_height は最小サイズでもあふれる高さ（ポイント）。"""
    fonts = (fitz.Font(fontfile=reg_font), fitz.Font(fontfile=bold_font))

    base = flow["body_size"]
    floor = flow["min_body_size"]
    step = flow["size_step"]

    size = base
    chosen = floor
    fits = False
    while size >= floor - 1e-9:
        need = measure_total_height(fonts, blocks, rect.width, flow, size)
        if need <= rect.height:
            chosen, fits = size, True
            break
        size = round(size - step, 4)

    overflow = 0.0
    if not fits:
        chosen = floor
        need = measure_total_height(fonts, blocks, rect.width, flow, floor)
        overflow = max(0.0, need - rect.height)

    return chosen, fits, overflow


def draw_flow(sheet, blocks, rect, flow, body_size):
    """選んだサイズで本文矩形に、自前折り返し（禁則処理・字下げ）で1行ずつ描く。"""
    head_size, line_height, head_gap, body_gap = _sizes(flow, body_size)
    col_head = hex2rgb(flow["color_heading"])
    col_body = hex2rgb(flow["color_body"])

    y = rect.y0
    for kind, txt in blocks:
        if not txt.strip():
            continue
        if y >= rect.y1:
            break
        size = head_size if kind == "head" else body_size
        font = sheet.fb if kind == "head" else sheet.fr
        bold = kind == "head"
        color = col_head if kind == "head" else col_body
        lines = layout_block(font, kind, txt, size, rect.width)
        advance = size * line_height
        ascent = size * font.ascender  # ベースラインは行の上端から ascent 下
        for line, x_off in lines:
            if y + ascent > rect.y1:  # この行のベースラインが枠の下に出るなら止める
                break
            if line:
                sheet.text(rect.x0 + x_off, y + ascent, line, size, color, bold=bold)
            y += advance
        y += head_gap if kind == "head" else body_gap


# ---------- 簡易の飾り枠（本番台紙が無いとき）----------
def draw_simple_frame(page, cr):
    f = cr["frame"]
    W, H = cr["page"]["width"], cr["page"]["height"]
    m, g = f["margin"], f["inner_gap"]
    col = hex2rgb(f["color"])
    page.draw_rect(fitz.Rect(m, m, W - m, H - m), color=col, width=f["line_width"])
    page.draw_rect(fitz.Rect(m + g, m + g, W - m - g, H - m - g),
                   color=col, width=f["inner_line_width"])


# ---------- メイン ----------
def build_reading(md_path, data_json, calib_json, out_pdf, template=None):
    calib = load_json(calib_json)
    cr = calib["reading"]
    data = load_json(data_json)

    title, sections = parse_md(md_path)
    blocks = build_blocks(sections)

    # ページ用意：本番台紙があれば読み込み、無ければ A4 を起こして簡易枠を描く
    if template and Path(template).exists():
        doc = fitz.open(template)
        page = doc[0]
    else:
        doc = fitz.open()
        page = doc.new_page(width=cr["page"]["width"], height=cr["page"]["height"])
        draw_simple_frame(page, cr)

    # Sheet には reading ブロックを渡す → draw_header が cr["header"] を見るようになる
    reg_font = str(ROOT / calib["fonts"]["regular"])
    bold_font = str(ROOT / calib["fonts"]["bold"])
    sheet = Sheet(page, cr, reg_font, bold_font)

    # タイトル（中央寄せ・太字）
    t = cr["title"]
    title_text = title or t.get("default", "鑑定文")
    tx = t["center_x"] - sheet.w(title_text, t["font"], bold=True) / 2
    sheet.text(tx, t["baseline_y"], title_text, t["font"], hex2rgb(t["color"]), bold=True)

    # meta（氏名・生年月日時・出生地）— render_sheet の位置決めロジックを流用
    draw_header(sheet, data)

    # 仕切り線
    d = cr.get("divider")
    if d:
        page.draw_line((d["x0"], d["y"]), (d["x1"], d["y"]),
                       color=hex2rgb(d["color"]), width=d["width"])

    # 本文の流し込み（自動フォント調整）
    flow = cr["flow"]
    rect = fitz.Rect(cr["body"]["x0"], cr["body"]["y0"], cr["body"]["x1"], cr["body"]["y1"])
    body_size, fits, overflow = choose_body_size(reg_font, bold_font, blocks, rect, flow)
    draw_flow(sheet, blocks, rect, flow, body_size)

    if not fits:
        line_h = body_size * flow["line_height"]
        over_lines = max(1, math.ceil(overflow / line_h))
        chars_per_line = max(1, int(rect.width / body_size))  # 和文は概ね1字＝1サイズ幅
        over_chars = over_lines * chars_per_line
        print(f"[warn] 本文が約{over_lines}行（約{over_chars}文字）入りきりません。"
              f"最小{flow['min_body_size']}ptで詰めました。"
              f"本文を短くするか、calibration.json の reading.body 矩形を広げてください。")
    else:
        print(f"[note] 本文サイズ {body_size}pt で枠に収まりました。")

    # フル埋め込みで一旦保存 → ghostscript があればサブセット軽量化（render_sheet と同じ）
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


def resolve_md(name):
    """鑑定文 .md を探す。仕様の『<名前>_仕事.md』と実ファイルの
    『鑑定文_<名前>_仕事_<日付>.md』の両方に対応し、複数あれば新しい方を使う。"""
    exact = MD_DIR / f"{name}_仕事.md"
    if exact.exists():
        return exact
    cands = sorted(MD_DIR.glob(f"*{name}_仕事*.md"), key=lambda p: p.stat().st_mtime)
    if cands:
        return cands[-1]
    return None


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="鑑定文ワークシート（鑑定文ページPDF）生成")
    ap.add_argument("--name", default="Sato_Jun",
                    help="名前キー（ファイル名用、例 Sato_Jun）。--md/--data/--out 未指定時の既定解決に使う")
    ap.add_argument("--md", default=None, help="鑑定文 .md（未指定なら名前から自動解決）")
    ap.add_argument("--data", default=None, help="チャートJSON（未指定なら 00 の output/JSON から解決）")
    ap.add_argument("--calib", default=str(ROOT / "calibration.json"))
    ap.add_argument("--template", default=str(ROOT / "template/reading_template.pdf"),
                    help="鑑定文ページの本番台紙PDF。無ければ A4＋簡易枠を自動生成")
    ap.add_argument("--out", default=None, help="出力PDF（未指定なら output/<名前>_reading.pdf）")
    a = ap.parse_args()

    md = Path(a.md) if a.md else resolve_md(a.name)
    if not md or not Path(md).exists():
        raise SystemExit(f"鑑定文 .md が見つかりません: name={a.name} "
                         f"（{MD_DIR} に <名前>_仕事 を含む .md を置くか --md で指定）")
    data = Path(a.data) if a.data else (CHART_JSON_DIR / f"{a.name}_chart_data.json")
    if not Path(data).exists():
        raise SystemExit(f"チャートJSONが見つかりません: {data}")
    out = Path(a.out) if a.out else (ROOT / "output" / f"{a.name}_reading.pdf")
    out.parent.mkdir(parents=True, exist_ok=True)

    path = build_reading(str(md), str(data), a.calib, str(out), a.template)
    print("written:", path)
