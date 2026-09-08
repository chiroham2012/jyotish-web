"""
南インド式ラーシ・チャート 自動生成スクリプト（デザイン改善版 v2）
使い方:
    python3 generate_chart_auto.py 田中太郎.pdf   # PDF自動読み取り
    python3 generate_chart_auto.py               # PERSON_DATAを使う（手動モード）

v2 の変更点（見た目のみ。build_svg の入出力インターフェイスは不変）:
  - チャートをページ中央に配置（左右対称のレイアウトへ）
  - 惑星を「記号／度数」の列で揃え、セル中央にブロック配置（縦横センタリング）
  - 右の凡例＋下の凡例 → チャート下に一本化した整列グリッドへ
  - 罫線・装飾を軽く、余白を広めに（すっきりモダン）

描画の持ち方（2026-09-08）:
  各 draw_* は「部品の一覧」（rect/line/polygon/circle/text の辞書のリスト）を返し、
  build_svg はそれをSVGへ、build_worksheet_pdf.py はそれを直接PDFへ描く。
  レイアウトの計算をここ1か所に置くことで、画面（SVG）とPDFの見た目が食い違わない。
"""
import math, sys, re

# ===== フォント（ここを差し替えれば全体の書体が変わる）=====
FONT = "Noto Serif CJK JP, serif"

# ===== レイアウト定数 =====
W, H       = 1100, 1420
CHART_SIZE = 720
CHART_X    = (W - CHART_SIZE) / 2      # ← ページ中央に配置
CHART_Y    = 250
CELL       = CHART_SIZE / 4

BG      = "#faf6ec"
LINE    = "#d8c39a"      # 細い内側の罫線（明るめ）
LINE_DK = "#b79256"      # 外枠
TEXT    = "#3a2a14"
SUB     = "#8a6a44"
FAINT   = "#c9b48d"

PLANET_COLOR = {
    "As": "#2e7d57", "Su": "#e8862e", "Mo": "#3a8fc4",
    "Me": "#444444", "Ve": "#b8841a", "Ma": "#d94e3a",
    "Ju": "#c07a10", "Sa": "#7a5a3a", "Ra": "#7a3aa8",
    "Ke": "#9a7ac4", "Ur": "#2a6a8a", "Ne": "#3a5aa8",
    "Pl": "#6a2a6a",
}

def planet_color(code):
    base = code.rstrip("R")
    return PLANET_COLOR.get(base, PLANET_COLOR.get(code, TEXT))

SIGNS = [
    (0, 0, "うお座",     "Pis", 11),
    (1, 0, "おひつじ座", "Ari",  0),
    (2, 0, "おうし座",   "Tau",  1),
    (3, 0, "ふたご座",   "Gem",  2),
    (3, 1, "かに座",     "Can",  3),
    (3, 2, "しし座",     "Leo",  4),
    (3, 3, "おとめ座",   "Vir",  5),
    (2, 3, "てんびん座", "Lib",  6),
    (1, 3, "さそり座",   "Sco",  7),
    (0, 3, "いて座",     "Sag",  8),
    (0, 2, "やぎ座",     "Cap",  9),
    (0, 1, "みずがめ座", "Aqu", 10),
]
SIGN_POS = {eng: (col, row) for col, row, _, eng, _ in SIGNS}
SIGN_IDX = {eng: idx for _, _, _, eng, idx in SIGNS}
IDX_TO_ENG = {v: k for k, v in SIGN_IDX.items()}

LEGEND = [
    ("As", "アセンダント", "肉体、外見、自分自身、ペルソナ",      "#2e7d57"),
    ("Su", "太陽",         "魂、社会性、仕事、意志、自信",         "#e8862e"),
    ("Mo", "月",           "心、感情、潜在意識、人気、感受性",     "#3a8fc4"),
    ("Me", "水星",         "知性、思考、コミュニケーション、学習", "#444444"),
    ("Ve", "金星",         "愛、調和、芸術、美、楽しみ、恋愛",     "#b8841a"),
    ("Ma", "火星",         "行動力、情熱、勇気、エネルギー",       "#d94e3a"),
    ("Ju", "木星",         "幸運、智慧、拡大、成長、道徳",         "#c07a10"),
    ("Sa", "土星",         "責任、忍耐、規律、現実化、努力",       "#7a5a3a"),
    ("Ra", "ラーフ",       "欲望、物質的繁栄、海外、変革",         "#7a3aa8"),
    ("Ke", "ケートゥ",     "霊性、内省、解脱、執着の手放し",       "#9a7ac4"),
    ("Ur", "天王星",       "改革、独創、自由、突然の変化",         "#2a6a8a"),
    ("Ne", "海王星",       "理想、霊性、芸術、境界の溶解",         "#3a5aa8"),
    ("Pl", "冥王星",       "深層、変容、破壊と再生、根源的な力",   "#6a2a6a"),
]

# =============================================================
# ★ 手動モード用サンプルデータ
# =============================================================
PERSON_DATA = {
    "name":      "Yamada Hanako",
    "birthinfo": "1990/4/1  09:00  /  Kyoto, Kyoto, Japan",
    "planets": [
        ("As",  "Ari", "05:22"), ("Ve",  "Ari", "18:44"),
        ("Su",  "Tau", "11:30"), ("Me",  "Tau", "27:08"),
        ("Mo",  "Can", "03:15"), ("JuR", "Can", "22:50"),
        ("Ra",  "Aqu", "14:33"), ("Ke",  "Leo", "14:33"),
        ("Ma",  "Cap", "08:19"), ("SaR", "Cap", "29:41"),
        ("Ur",  "Sag", "06:02"), ("Ne",  "Sco", "12:17"),
        ("Pl",  "Sco", "16:55"),
    ],
}

# =============================================================
# 部品（プリミティブ）の作り方。SVGにもPDFにも描けるよう、見た目の情報だけを持つ。
def _rect(x, y, w, h, fill=None, stroke=None, width=1, rx=0):
    return {"t": "rect", "x": x, "y": y, "w": w, "h": h,
            "fill": fill, "stroke": stroke, "width": width, "rx": rx}

def _line(x1, y1, x2, y2, stroke, width=1):
    return {"t": "line", "x1": x1, "y1": y1, "x2": x2, "y2": y2,
            "stroke": stroke, "width": width}

def _polygon(points, stroke, width=1):
    return {"t": "polygon", "points": points, "stroke": stroke, "width": width}

def _circle(cx, cy, r, fill, opacity=1.0):
    return {"t": "circle", "cx": cx, "cy": cy, "r": r, "fill": fill, "opacity": opacity}

def _text(x, y, s, size, fill, bold=False, anchor="start", spacing=0):
    # SVGは連続する空白を1つにまとめて表示する。ここで先に揃えておくことで、
    # SVG（画面）とPDFで文字の並びが食い違わないようにする。
    return {"t": "text", "x": x, "y": y, "s": " ".join(str(s).split()), "size": size,
            "fill": fill, "bold": bold, "anchor": anchor, "spacing": spacing}


def cell_xy(col, row):
    return CHART_X + col * CELL, CHART_Y + row * CELL

def draw_title(name, birthinfo):
    mid = W / 2
    return [
        _text(mid, 90, f"{name}さん", 42, TEXT, bold=True, anchor="middle", spacing=1),
        _text(mid, 134, "インド占星術 出生図", 23, TEXT, anchor="middle", spacing=4),
        _text(mid, 172, birthinfo, 14, SUB, anchor="middle"),
    ]

def draw_grid():
    out = []
    # 外枠（細めで上品に）
    out.append(_rect(CHART_X, CHART_Y, CHART_SIZE, CHART_SIZE,
                     stroke=LINE_DK, width=2, rx=4))
    # 内側の格子（さらに細く）
    for i in range(1, 4):
        x = CHART_X + i * CELL
        out.append(_line(x, CHART_Y, x, CHART_Y + CHART_SIZE, LINE))
        y = CHART_Y + i * CELL
        out.append(_line(CHART_X, y, CHART_X + CHART_SIZE, y, LINE))
    # 中央（2×2）に細いダイヤモンド1本だけ。装飾は最小限に。
    cx, cy = CHART_X + CHART_SIZE/2, CHART_Y + CHART_SIZE/2
    r = CELL - 18
    out.append(_polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)], FAINT))
    out.append(_circle(cx, cy, 3, FAINT))
    return out

def draw_sign_labels():
    out = []
    for col, row, jp, _, _ in SIGNS:
        x, y = cell_xy(col, row)
        out.append(_text(x + 14, y + 27, jp, 15, SUB))
    return out

def draw_house_numbers(asc_sign_idx):
    out = []
    for col, row, _, _, sign_idx in SIGNS:
        x, y = cell_xy(col, row)
        house = ((sign_idx - asc_sign_idx) % 12) + 1
        out.append(_text(x + CELL - 13, y + CELL - 13, str(house), 15, FAINT, anchor="end"))
    return out

JP_SYM = {"Su":"太","Mo":"月","Me":"水","Ve":"金","Ma":"火","Ju":"木","Sa":"土",
          "Ur":"天","Ne":"海","Pl":"冥"}

def draw_planets(planets):
    """各セルの惑星を『記号／度数』の2列で揃え、セル中央にブロック配置する。
    1つのマスに惑星が集中して(目安5個以上)既定の行高さでは収まりきらない場合は、
    行の高さと文字サイズを人数に応じて縮め、マスからはみ出さないようにする。"""
    cell_planets = {}
    for code, sign_eng, deg in planets:
        if sign_eng not in SIGN_POS:
            raise ValueError(f"未知の星座略称: {sign_eng}  コード={code}")
        pos = SIGN_POS[sign_eng]
        cell_planets.setdefault(pos, []).append((code, deg))

    out = []
    ROW_H_MAX = 30         # 1惑星あたりの行の高さ（余裕がある場合の上限）
    SYM_COL   = 30         # 記号の列幅（度数の左端がここで揃う。逆行Rマーク分の余白を含む）
    DEG_W     = 44         # 度数(DD:MM)の想定幅
    BLOCK_W   = SYM_COL + DEG_W

    for (col, row), items in cell_planets.items():
        x, y = cell_xy(col, row)
        n = len(items)
        # 星座名(上)とハウス番号(下)を避けた、惑星を置ける縦の範囲
        area_top = y + 42
        area_bot = y + CELL - 26
        avail_h  = area_bot - area_top
        # 行の高さは「既定の30px」と「全員がちょうど収まる高さ」の小さい方
        row_h = min(ROW_H_MAX, avail_h / n) if n else ROW_H_MAX
        scale = row_h / ROW_H_MAX
        sym_size = max(19 * scale, 11)
        deg_size = max(16 * scale, 9)
        r_size   = max(13 * scale, 9)
        block_h  = n * row_h
        first_base = area_top + max((avail_h - block_h) / 2, 0) + row_h * 0.7
        block_x = x + (CELL - BLOCK_W) / 2
        sym_cx  = block_x + SYM_COL / 2 - 2   # 記号は自分の列の中央に
        deg_x   = block_x + SYM_COL           # 度数は左端を揃える

        for i, (code, deg) in enumerate(items):
            base = first_base + i * row_h
            color = planet_color(code)
            is_retro  = code.endswith("R")
            base_code = code[:-1] if is_retro else code
            sym = JP_SYM.get(base_code, base_code)
            out.append(_text(sym_cx, base, sym, sym_size, color, bold=True, anchor="middle"))
            if is_retro:
                # 記号の右肩に小さく superscript として乗せる（度数の列とは重ならない位置）
                out.append(_text(sym_cx + 6*scale, base - 12*scale, "R", r_size, color, bold=True))
            out.append(_text(deg_x, base, deg, deg_size, color))
    return out

def draw_legend_below():
    """チャート下に一本化した凡例（2列×5行、中央揃え）。"""
    out = []
    top = CHART_Y + CHART_SIZE + 66
    out.append(_text(W/2, top, "各記号が表す人生の要素", 18, TEXT,
                     bold=True, anchor="middle", spacing=2))
    out.append(_line(W/2 - 150, top + 14, W/2 + 150, top + 14, FAINT))

    col_w = 430
    grid_x = CHART_X               # ← 凡例の左端をチャートの左端に揃える（左揃えのまま右へ）
    gy = top + 52
    row_h = 42
    LEFT = 7                       # 左列に7項目、右列に6項目
    for i, (code, name, meaning, color) in enumerate(LEGEND):
        if i < LEFT:
            c, r = 0, i
        else:
            c, r = 1, i - LEFT
        cx = grid_x + c * col_w
        cy = gy + r * row_h
        out.append(_circle(cx + 15, cy - 5, 14, color, opacity=0.9))
        out.append(_text(cx + 15, cy, code, 12, "#ffffff", bold=True, anchor="middle"))
        out.append(_text(cx + 40, cy - 3, name, 14, TEXT, bold=True))
        out.append(_text(cx + 40, cy + 14, meaning, 11.5, SUB))
    return out

def build_primitives(data):
    """チャート1枚ぶんの部品一覧を返す。SVG化もPDF化もこの一覧から行う。"""
    name, birthinfo, planets = data["name"], data["birthinfo"], data["planets"]
    asc_entries = [(c, s, d) for c, s, d in planets if c == "As"]
    if not asc_entries:
        raise ValueError("planets に As（アセンダント）がありません")
    asc_sign_idx = SIGN_IDX[asc_entries[0][1]]
    return [
        _rect(0, 0, W, H, fill=BG),
        *draw_title(name, birthinfo),
        *draw_grid(),
        *draw_sign_labels(),
        *draw_house_numbers(asc_sign_idx),
        *draw_planets(planets),
        *draw_legend_below(),
    ]

# ---------- SVGへの書き出し ----------
def _n(v):
    """座標・サイズをSVGの属性値へ。小数第1位まで（元の :.1f 表記に合わせる）。"""
    r = round(float(v), 1)
    return str(int(r)) if r == int(r) else str(r)

def _esc(s):
    """氏名など外部由来の文字列を属性・本文に安全に埋め込む。"""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def _prim_to_svg(p):
    t = p["t"]
    if t == "rect":
        a = f'x="{_n(p["x"])}" y="{_n(p["y"])}" width="{_n(p["w"])}" height="{_n(p["h"])}"'
        a += f' fill="{p["fill"]}"' if p["fill"] else ' fill="none"'
        if p["stroke"]:
            a += f' stroke="{p["stroke"]}" stroke-width="{_n(p["width"])}"'
        if p["rx"]:
            a += f' rx="{_n(p["rx"])}"'
        return f"<rect {a}/>"
    if t == "line":
        return (f'<line x1="{_n(p["x1"])}" y1="{_n(p["y1"])}" x2="{_n(p["x2"])}" '
                f'y2="{_n(p["y2"])}" stroke="{p["stroke"]}" stroke-width="{_n(p["width"])}"/>')
    if t == "polygon":
        pts = " ".join(f"{_n(x)},{_n(y)}" for x, y in p["points"])
        return (f'<polygon points="{pts}" fill="none" '
                f'stroke="{p["stroke"]}" stroke-width="{_n(p["width"])}"/>')
    if t == "circle":
        a = f'cx="{_n(p["cx"])}" cy="{_n(p["cy"])}" r="{_n(p["r"])}" fill="{p["fill"]}"'
        if p["opacity"] != 1.0:
            a += f' opacity="{p["opacity"]}"'
        return f"<circle {a}/>"
    a = (f'x="{_n(p["x"])}" y="{_n(p["y"])}" font-family="{FONT}" '
         f'font-size="{_n(p["size"])}"')
    if p["bold"]:
        a += ' font-weight="bold"'
    if p["anchor"] != "start":
        a += f' text-anchor="{p["anchor"]}"'
    a += f' fill="{p["fill"]}"'
    if p["spacing"]:
        a += f' letter-spacing="{_n(p["spacing"])}"'
    return f'<text {a}>{_esc(p["s"])}</text>'

def build_svg(data):
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
             f'viewBox="0 0 {W} {H}">']
    parts += [_prim_to_svg(p) for p in build_primitives(data)]
    parts.append("</svg>")
    return "\n".join(parts)

# =============================================================
# PDF自動読み取り（座標ベース）※ v1 から変更なし
# =============================================================
def parse_pdf(pdf_path):
    import pdfplumber
    from datetime import datetime

    with pdfplumber.open(pdf_path) as pdf:
        page  = pdf.pages[0]
        text  = page.extract_text()
        words = page.extract_words()

    lines     = text.split("\n")
    full_text = " ".join(lines)

    DATE_PAT = re.compile(r'^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)|^City|^State|^Country|^Vimsh|^Sign')
    name = "Unknown"
    for line in lines[:5]:
        l = line.strip()
        if l and not DATE_PAT.match(l) and not re.match(r'^\d', l):
            name = l
            break

    m = re.search(r'(\w{3} \d+, \d{4}) (\d+:\d+):\d+', full_text)
    birth_date_fmt = "不明"
    if m:
        try:
            dt = datetime.strptime(f"{m.group(1)} {m.group(2)}", "%b %d, %Y %H:%M")
            birth_date_fmt = dt.strftime("%Y/%-m/%-d %H:%M")
        except:
            birth_date_fmt = m.group(1)

    def search_val(pattern):
        r = re.search(pattern, full_text)
        return r.group(1) if r else ""

    city    = search_val(r'City\s*:\s*(\S+)')
    state   = search_val(r'State\s*:\s*(\S+)')
    country = search_val(r'Country\s*:\s*(\S+)')
    birthinfo = f"{birth_date_fmt}  /  {city}, {state}, {country}"

    HOUSE_LABELS = ['1st','2nd','3rd','4th','5th','6th','7th',
                    '8th','9th','10th','11th','12th']
    house_coords = {}
    for w in words:
        if w['text'] in HOUSE_LABELS:
            num = int(re.sub(r'\D', '', w['text']))
            if num not in house_coords:
                house_coords[num] = (w['x0'], w['top'])

    if len(house_coords) < 12:
        raise ValueError(f"ハウスラベルが不足しています（{len(house_coords)}/12）")

    max_hy = max(house_coords[h][1] for h in range(1,13))
    bottom_hs = sorted([h for h in range(1,13) if abs(house_coords[h][1]-max_hy)<5],
                       key=lambda h: house_coords[h][0])
    cell_w = abs(house_coords[bottom_hs[1]][0] - house_coords[bottom_hs[0]][0])

    min_hx = min(house_coords[h][0] for h in range(1,13))
    left_col_houses = [h for h in range(1,13) if abs(house_coords[h][0]-min_hx) < 5]
    row_ys = sorted(set(round(house_coords[h][1], 1) for h in left_col_houses))
    row_tops = [row_ys[0] - cell_w] + list(row_ys[:-1])
    row_bots = list(row_ys)

    VALID = {'As','Su','Mo','Me','Ve','Ma','Ju','Sa','Ra','Ke','Ur','Ne','Pl',
             'NeR','SaR','JuR','MaR','MeR','VeR','SuR','MoR','UrR','PlR','KeR','RaR'}
    DEG   = re.compile(r'^\d+:\d+$')

    def split_word(txt):
        m2 = re.match(r'^([A-Z][a-zA-Z]*R?)(\d+:\d+)$', txt)
        if m2 and m2.group(1) in VALID:
            return [m2.group(1), m2.group(2)]
        codes = []
        remaining = txt
        while remaining:
            found = False
            for code in sorted(VALID, key=len, reverse=True):
                if remaining.startswith(code):
                    codes.append(code)
                    remaining = remaining[len(code):]
                    found = True
                    break
            if not found:
                return [txt]
        return codes if codes else [txt]

    row_ys_list = list(row_ys)
    max_y = max(house_coords[h][1] for h in range(1,13))
    bottom_houses = [h for h in range(1,13) if abs(house_coords[h][1]-max_y) < 5]
    col_xs_raw = sorted(set(house_coords[h][0] for h in bottom_houses))

    def nearest_row(yv):
        return min(range(len(row_ys_list)), key=lambda i: abs(row_ys_list[i]-yv))
    def nearest_col(xv):
        return min(range(len(col_xs_raw)), key=lambda i: abs(col_xs_raw[i]-xv))

    grid_to_sign = {(col, row): eng for col, row, _, eng, _ in SIGNS}

    as_grid_col = nearest_col(house_coords[1][0])
    as_grid_row = nearest_row(house_coords[1][1])
    as_sign = grid_to_sign.get((as_grid_col, as_grid_row))
    if not as_sign:
        raise ValueError(f"アセンダント星座が特定できません（grid={as_grid_col},{as_grid_row}）")

    print(f"  アセンダント星座: {as_sign}")

    seen   = set()
    planets = []
    for house_num, (hx, hy) in sorted(house_coords.items()):
        row_idx  = nearest_row(hy)
        col_idx  = nearest_col(hx)
        y0 = row_tops[row_idx]
        y1 = row_bots[row_idx]
        x0 = hx - cell_w
        x1 = hx + 5
        sign_eng = grid_to_sign.get((col_idx, row_idx))
        if not sign_eng:
            continue
        raw = sorted([w for w in words
            if x0 <= w['x0'] <= x1 and y0 <= w['top'] <= y1
            and w['text'] not in HOUSE_LABELS],
            key=lambda x: x['top'])
        txts = []
        for w in raw:
            txts.extend(split_word(w['text']))
        i = 0
        while i < len(txts):
            if txts[i] in VALID and txts[i] not in seen:
                if i+1 < len(txts) and DEG.match(txts[i+1]):
                    planets.append((txts[i], sign_eng, txts[i+1]))
                    seen.add(txts[i])
                    i += 2
                    continue
            i += 1

    return {"name": name, "birthinfo": birthinfo, "planets": planets}


if __name__ == "__main__":
    if len(sys.argv) >= 2:
        pdf_path = sys.argv[1]
        print(f"PDFを読み込んでいます: {pdf_path}")
        data = parse_pdf(pdf_path)
        print(f"名前: {data['name']}")
        print(f"生年月日: {data['birthinfo']}")
        print("惑星データ:")
        for p in data["planets"]:
            print(f"  {p}")
        print()
    else:
        data = PERSON_DATA

    svg = build_svg(data)
    out_path = f'{data["name"].replace(" ", "_")}.svg'
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"Generated: {out_path}")
