#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
鑑定支援アプリ MVP — 第2層プロトタイプ
テーマ：仕事（職業の方向性・適性）

入力：パラーシャラの光のチャートJSON（例：satojun_chart_data.json）
出力：支持／反証／中立に分類した「材料（finding）」リスト

設計原則（ルール集 §1 と対応）：
  1. 結論ではなく材料を出す（断定文を生成しない）
  2. 根拠を必ず添える（basis）
  3. 矛盾を隠さない（支持・反証を両方並べる）
  4. 強度を明示（strength 1〜3）
  5. 統合と執筆は人間（このプログラムは材料まで）

実装済み（2026-06-04 時点）：
  - カテゴリA：10室支配星の在住ハウス（方向の手がかり＋dusthanaの弱さペア）
  - カテゴリB：カラカ（太陽・土星・水星）の状態
  - カテゴリC：惑星ごとの職業象意（10室系との関与フィルタ付き）
  - 品位：高揚／減衰／定座に加え、自然の友敵関係（friend／enemy／neutral）
  - コンバスト（簡易）・shadbala 補強（暫定しきい値）
  - アスペクト（graha drishti）：ハウス単位（標準7＋特殊 火4/8・木5/9・土3/10、
    ノード5/9）。関与フィルタへの接続＋凶星アスペクト（反証）／吉星アスペクト（救済）

未実装（TODO。ルール集 §6 と対応）：
  - papakartari yoga（凶星の挟み込み）
  - ムーラトリコーナの度数判定
  - カテゴリD（D10 との整合）

このコードは Cursor で育てる出発点。ルールテーブルは上部に分離してあるので、
ルール集Markdown（§3-A / §3-B / §3-C / §4）と突き合わせて拡張・修正していく。

使い方：
  python3 career_findings_mvp.py satojun_chart_data.json
"""

import json
import sys
import os
import datetime
from dataclasses import dataclass, field
from typing import List

# 入力JSONは、パイプラインの output/JSON を直接読む（重複・手コピーを解消）。
# 出力（材料ボード）はこのスクリプトと同じフォルダ内に保存する。
# 2026-06-16 整理：PDF→JSON/SVGパイプライン一式を ../00_ホロPDFからJSON生成/ に集約。
JSON_DIR = os.path.join("..", "00_ホロPDFからJSON生成", "output", "JSON")
OUTPUT_DIR = "材料ボード"

# =========================================================
# ルールテーブル（ルール集の各カテゴリと対応。ここを編集して育てる）
# =========================================================

# サイン→支配星（ハウス支配星の算出に使う）
SIGN_LORD = {
    "Aries": "Ma", "Taurus": "Ve", "Gemini": "Me", "Cancer": "Mo",
    "Leo": "Su", "Virgo": "Me", "Libra": "Ve", "Scorpio": "Ma",
    "Sagittarius": "Ju", "Capricorn": "Sa", "Aquarius": "Sa", "Pisces": "Ju",
}

# サインの性質：(元素, 性質(モダリティ), 支配星)。
# 性質の語は佐藤さんの流派に合わせる：活動 / 固着 / 変通（固定・柔軟とは呼ばない）。
# ここは「場の色」のタグまで。豊かな描写は象意辞典（第3層）側で補う。
SIGN_NATURE = {
    "Aries":       ("火", "活動", "Ma"),
    "Taurus":      ("地", "固着", "Ve"),
    "Gemini":      ("風", "変通", "Me"),
    "Cancer":      ("水", "活動", "Mo"),
    "Leo":         ("火", "固着", "Su"),
    "Virgo":       ("地", "変通", "Me"),
    "Libra":       ("風", "活動", "Ve"),
    "Scorpio":     ("水", "固着", "Ma"),
    "Sagittarius": ("火", "変通", "Ju"),
    "Capricorn":   ("地", "活動", "Sa"),
    "Aquarius":    ("風", "固着", "Sa"),
    "Pisces":      ("水", "変通", "Ju"),
}

# サイン英名→和名（材料ボード表示用）
SIGN_JP = {
    "Aries": "牡羊", "Taurus": "牡牛", "Gemini": "双子", "Cancer": "蟹",
    "Leo": "獅子", "Virgo": "乙女", "Libra": "天秤", "Scorpio": "蠍",
    "Sagittarius": "射手", "Capricorn": "山羊", "Aquarius": "水瓶", "Pisces": "魚",
}

# 品位：高揚・減衰・定座（§4 修飾ルール）
EXALTATION = {"Su": "Aries", "Mo": "Taurus", "Ma": "Capricorn", "Me": "Virgo",
              "Ju": "Cancer", "Ve": "Pisces", "Sa": "Libra"}
DEBILITATION = {"Su": "Libra", "Mo": "Scorpio", "Ma": "Cancer", "Me": "Pisces",
                "Ju": "Capricorn", "Ve": "Virgo", "Sa": "Aries"}
OWN_SIGNS = {"Su": ["Leo"], "Mo": ["Cancer"], "Ma": ["Aries", "Scorpio"],
             "Me": ["Gemini", "Virgo"], "Ju": ["Sagittarius", "Pisces"],
             "Ve": ["Taurus", "Libra"], "Sa": ["Capricorn", "Aquarius"]}

# 自然の友敵関係（ナイサルギカ・マイトリ＝Parasharaの標準表）。
# 在住サインの支配星が、その惑星にとって friend / enemy / neutral かで品位を振る。
# ここに載らない相手（自分自身を除く）は neutral 扱い。
# TODO: temporal(tatkalika)・五重(panchadha)の合成、ムーラトリコーナの度数判定は未実装。
NATURAL_FRIENDS = {
    "Su": ["Mo", "Ma", "Ju"],
    "Mo": ["Su", "Me"],
    "Ma": ["Su", "Mo", "Ju"],
    "Me": ["Su", "Ve"],
    "Ju": ["Su", "Mo", "Ma"],
    "Ve": ["Me", "Sa"],
    "Sa": ["Me", "Ve"],
}
NATURAL_ENEMIES = {
    "Su": ["Ve", "Sa"],
    "Mo": [],
    "Ma": ["Me"],
    "Me": ["Mo"],
    "Ju": ["Me", "Ve"],
    "Ve": ["Su", "Mo"],
    "Sa": ["Su", "Mo", "Ma"],
}

# 品位 → (polarity, strength, ラベル)。dignity() の戻り値を finding に変換するときの共通表。
DIGNITY_INFO = {
    "exalted":     ("support", 3, "高揚"),
    "own":         ("support", 2, "定座"),
    "friend":      ("support", 1, "友好サイン"),
    "neutral":     (None,      0, "中立サイン"),
    "enemy":       ("refute",  1, "敵対サイン"),
    "debilitated": ("refute",  2, "減衰"),
}

DUSTHANAS = {6, 8, 12}  # §4：方向(中立)＋弱さ(反証)を両方出す室

# §4：アスペクト（graha drishti）。whole sign 前提で「在住ハウスから数えた
# ハウス単位」で判定する。全惑星の標準アスペクト＝7番目に加え、下記の特殊
# アスペクトを足す（いずれも在住ハウスから数えた n 番目のハウスを見る）。
SPECIAL_ASPECTS = {
    "Ma": [4, 8],   # 火星
    "Ju": [5, 9],   # 木星
    "Sa": [3, 10],  # 土星
}
# ラーフ／ケートゥは在住ハウスから 5・9 番目にアスペクトを与える（佐藤さん確認・
# 2026-06-04）。7 番目を含めない流派の採用。標準7番目は付けない点に注意。
NODE_ASPECTS = [5, 9]

# 自然の吉星／凶星（救済・凶アスペクト判定に使う）。月・水星は吉星に含める
# （佐藤さん確認・2026-06-04）。
BENEFICS = {"Ju", "Ve", "Mo", "Me"}
MALEFICS = {"Su", "Ma", "Sa", "Ra", "Ke"}

# §3-A：10室支配星の在住ハウス12通り（方向の手がかり＝中立）
CATEGORY_A = {
    1: "独立・自分の名前で立つ・リーダー・自己表現",
    2: "金融・財務・家業・食・声/言葉・教育",
    3: "営業・メディア・執筆・技能/手仕事・芸能・運輸",
    4: "不動産・乗物・教育機関・農業・ホスピタリティ・地元密着",
    5: "創造・娯楽・芸術・投機・助言・政治",
    6: "雇われ仕事・奉仕・医療・法務/係争・軍警察・金融回収",
    7: "商売・ビジネス・貿易・接客・外国/他者と組む",
    8: "研究・探究・掘り下げる・保険/遺産・オカルト・心理・外科・生と死・危機管理",
    9: "高等教育・法/宗教/哲学・助言職/師・出版・外国",
    10: "王道のキャリア・天職・天命・権威・地位・公的/政府・強い職業意識",
    11: "利益・ネットワーク・大組織/団体・収入源が複数・果報・夢の達成",
    12: "外国/海外・隠遁・スピリチュアル・施設・慈善・舞台裏",
}

# §3-B：カラカ（自然表示星）の象徴領域
KARAKA_B = {
    "Su": "地位・権威・公職・政府・経営トップ・指導・父系",
    "Sa": "労働・奉仕・規律・大衆・長期事業・現場/肉体・サービス・公務員・裁判官",
    "Me": "商売・知性・言葉・通訳・編集・文筆・計算・分析・仲介・通信/IT・学者・専門家",
}

# §3-C：惑星ごとの職業象意（関与フィルタを通った時だけ発火）
PLANET_C = {
    "Ma": "技術・工学・機械・製造・軍/警察・外科・スポーツ/競争・不動産/土地・金属・消防/危機対応",
    "Ju": "教育・教師・助言/カウンセラー・宗教/哲学・法律・財務/銀行・医療(治療側)・出版・コンサル",
    "Ve": "芸術・美・デザイン・音楽/芸能・美容/宝石/贅沢品・ホスピタリティ・メディア/広告・乗物・女性関連",
    "Mo": "大衆相手(小売/飲食)・ケア/看護/心理・水/液体・食/家庭・移動の多い職・一般向けメディア",
}

# shadbala（rupas）の暫定しきい値（§7.1 の発見。TODO: 値は検証して調整）
SHADBALA_STRONG = 1.3
SHADBALA_WEAK = 1.0

PLANET_JP = {"Su": "太陽", "Mo": "月", "Ma": "火星", "Me": "水星",
             "Ju": "木星", "Ve": "金星", "Sa": "土星", "Ra": "ラーフ", "Ke": "ケートゥ"}


# =========================================================
# データモデル：finding 一件（ルール集 §5 のスキーマに対応）
# =========================================================
@dataclass
class Finding:
    factor: str          # どんな配置か
    basis: str           # なぜこの方向／極性になるか
    polarity: str        # support / refute / neutral
    strength: int        # 1〜3
    theme: str = "仕事/方向性"
    sources: List[str] = field(default_factory=list)
    note: str = ""


# =========================================================
# 基本ユーティリティ
# =========================================================
def parse_deg(s):
    """'02:58'（度:分）→ 度(float）"""
    d, m = s.split(":")
    return int(d) + int(m) / 60.0


def dignity(planet, sign):
    """高揚/減衰/定座/友好/敵対/中立を返す。
       高揚・減衰・定座を先に判定し、残りは在住サインの支配星との
       自然の友敵関係（NATURAL_FRIENDS/ENEMIES）で friend/enemy/neutral に振る。"""
    if EXALTATION.get(planet) == sign:
        return "exalted"
    if DEBILITATION.get(planet) == sign:
        return "debilitated"
    if sign in OWN_SIGNS.get(planet, []):
        return "own"
    lord = SIGN_LORD.get(sign)
    if lord is None or lord == planet:
        return "neutral"
    if lord in NATURAL_FRIENDS.get(planet, []):
        return "friend"
    if lord in NATURAL_ENEMIES.get(planet, []):
        return "enemy"
    return "neutral"


def sign_desc(sign):
    """サインの性質を『牡羊座＝火/活動/火星支配』の形で返す。
       元素・性質(活動/固着/変通)・支配星まで。豊かな描写は象意辞典(第3層)側。"""
    el, mod, lord = SIGN_NATURE[sign]
    return f"{SIGN_JP[sign]}座＝{el}/{mod}/{PLANET_JP[lord]}支配"


def tenth_house_sign(chart):
    return chart["charts"]["D1"]["houses"]["10"]["sign"]


def is_combust(planet, planets):
    """簡易コンバスト：太陽と同室で度数差が閾値未満。
       TODO: 惑星別の正確な閾値・順逆（逆行）対応。"""
    if planet == "Su":
        return False
    p, su = planets[planet], planets["Su"]
    if p["house"] != su["house"]:
        return False
    threshold = 12.0  # 順行水星の目安
    return abs(parse_deg(p["degree"]) - parse_deg(su["degree"])) < threshold


def shadbala_of(chart, planet):
    return chart.get("shadbala", {}).get(planet)


def career_involvement(planet, planets, tenth_lord_house, tenth_lord=None):
    """関与フィルタ（§3-C）。関与ありなら理由（日本語の短い文字列）を、
       なしなら None を返す。判定根拠を finding の basis に出せるよう理由を返す。
       【在住】10室・1室在住、または10室支配星と同室。
       【アスペクト】10室・1室・10室支配星のいずれかにアスペクトを投げる、
                    または10室支配星からアスペクトを受ける（§4 アスペクト方針）。"""
    h = planets[planet]["house"]
    # 在住による関与（従来ルール）
    if h == 10:
        return "10室在住"
    if h == 1:
        return "1室（ラグナ）在住"
    if h == tenth_lord_house:
        return "10室支配星と同室"
    # アスペクトによる関与（新規）
    cast = aspect_houses(planet, h)
    if 10 in cast:
        return "10室へアスペクト"
    if 1 in cast:
        return "1室（ラグナ）へアスペクト"
    if tenth_lord_house in cast:
        return "10室支配星へアスペクト"
    if tenth_lord and tenth_lord in planets and tenth_lord != planet:
        lord_h = planets[tenth_lord].get("house")
        if lord_h is not None and h in aspect_houses(tenth_lord, lord_h):
            return "10室支配星からアスペクトを受ける"
    return None


def is_career_involved(planet, planets, tenth_lord_house, tenth_lord=None):
    """career_involvement() の真偽ラッパ（既存呼び出しとの互換用）。"""
    return career_involvement(planet, planets, tenth_lord_house, tenth_lord) is not None


def aspect_houses(planet, from_house):
    """planet が from_house に在住するとき、ドリシュティ（視線）を投げる
       ハウス番号の集合を返す。whole sign 前提で「在住ハウスから数えた
       ハウス単位」で判定する。標準＝7番目、特殊＝火星4/8・木星5/9・土星3/10。
       ラーフ／ケートゥは NODE_ASPECTS で制御（既定は空＝対象外、流派確認待ち）。"""
    if planet in ("Ra", "Ke"):
        nths = list(NODE_ASPECTS)
    else:
        nths = [7] + SPECIAL_ASPECTS.get(planet, [])
    # n 番目のハウス＝在住ハウスから n-1 進めた先（1〜12 に正規化）
    return {((from_house - 1 + (n - 1)) % 12) + 1 for n in nths}


def planets_aspecting_house(target_house, planets, exclude=None):
    """target_house にアスペクトを投げている惑星コードの集合を返す。
       在住している惑星はアスペクトではないため含めない。伝統惑星のみ対象
       （外惑星 Ur/Ne/Pl は PLANET_JP 非掲載なので自然に除外される）。"""
    result = set()
    for p, info in planets.items():
        if p == exclude or p not in PLANET_JP:
            continue
        h = info.get("house")
        if h is None or h == target_house:
            continue
        if target_house in aspect_houses(p, h):
            result.add(p)
    return result


def benefic_malefic_aspects(target_planet, planets):
    """target_planet にアスペクトしている惑星を、自然の吉星／凶星に分けて
       (吉星リスト, 凶星リスト) で返す（在住惑星・自分自身は除く）。"""
    th = planets[target_planet].get("house")
    if th is None:
        return [], []
    casters = planets_aspecting_house(th, planets, exclude=target_planet)
    benefics = sorted(c for c in casters if c in BENEFICS)
    malefics = sorted(c for c in casters if c in MALEFICS)
    return benefics, malefics


def aspect_findings(planet, planets, findings, theme, has_refute):
    """§4：凶星アスペクト＝反証、吉星アスペクト＝救済 の finding を足す共通処理。
       凶星アスペクトは無条件で反証を1枚。吉星アスペクトは、その惑星に既に
       反証材料（減衰・敵対・コンバスト等）があるときだけ救済（支持）を1枚足す
       （過剰な支持＝バーナムを避け、既存の反証は消さず併置：設計原則3）。"""
    jp = PLANET_JP[planet]
    benefics, malefics = benefic_malefic_aspects(planet, planets)
    if malefics:
        names = "・".join(PLANET_JP[m] for m in malefics)
        findings.append(Finding(
            factor=f"{jp} が凶星（{names}）からアスペクト",
            basis=f"凶星のドリシュティを受け、{jp}の象徴機能に圧力・障害・遠回りの面",
            polarity="refute", strength=1, theme=theme,
            sources=["§4 アスペクト"],
        ))
    if has_refute and benefics:
        names = "・".join(PLANET_JP[b] for b in benefics)
        findings.append(Finding(
            factor=f"{jp} が吉星（{names}）からアスペクト（救済）",
            basis=f"{jp}は減衰/敵対/コンバスト等の反証を持つが、吉星のドリシュティが緩和する",
            polarity="support", strength=1, theme=theme,
            sources=["§4 アスペクト", "救済"],
            note="既存の反証材料は消さず、緩和材料として併置（設計原則3）",
        ))


# =========================================================
# サインの性質：1室(器)と10室(仕事の場)の「場の色」
# =========================================================
def category_signs(chart, findings):
    """1室(器・本人のベース)と10室(仕事の場)の在住サインの性質を『場の色』
       として中立で出す。惑星の象意はこの色で読む（お手本の読み筋）。
       元素・性質(活動/固着/変通)・支配星までの事実タグ。豊かな描写は象意辞典。"""
    houses = chart["charts"]["D1"]["houses"]
    for hnum, label in (("1", "1室(器・本人のベース)"), ("10", "10室(仕事の場)")):
        sign = houses[hnum]["sign"]
        findings.append(Finding(
            factor=f"{label}は{SIGN_JP[sign]}座",
            basis=f"場の色：{sign_desc(sign)}",
            polarity="neutral", strength=1, theme="仕事/方向性",
            sources=["サインの性質"],
            note="サインの性質。惑星の象意をこの色で読む（豊かな意味は象意辞典）",
        ))


# =========================================================
# カテゴリA：10室支配星の在住ハウス
# =========================================================
def category_a(chart, findings):
    planets = chart["planets"]
    sign10 = tenth_house_sign(chart)
    lord = SIGN_LORD[sign10]
    lh = planets[lord]["house"]
    direction = CATEGORY_A[lh]

    findings.append(Finding(
        factor=f"10室支配星({PLANET_JP[lord]})が{lh}室に在住",
        basis=f"ラグナ→10室={sign10}→支配星={PLANET_JP[lord]}。{lh}室の方向：{direction}",
        polarity="neutral", strength=2,
        sources=["§3-A", "ハウス支配ルール"],
        note="方向の手がかり。単独では断定せず、複数材料の重なりで強くする",
    ))
    # §4：dusthana なら「弱さ(反証)」も必ずペアで出す
    if lh in DUSTHANAS:
        findings.append(Finding(
            factor=f"10室支配星({PLANET_JP[lord]})が{lh}室(dusthana)に在住",
            basis=f"{lh}室は6/8/12のいずれか。職業エネルギーが表に出にくい／遠回りの面",
            polarity="refute", strength=2,
            sources=["§3-A", "§4 dusthana方針"],
            note="同じ配置の『方向(中立)』材料と必ず対で見る",
        ))
    return lh  # カテゴリCの関与判定で使う


# =========================================================
# カテゴリB：カラカ（太陽・土星・水星）の状態
# =========================================================
def category_b(chart, findings):
    planets = chart["planets"]
    for k in ["Su", "Sa", "Me"]:
        p = planets[k]
        sign, h = p["sign"], p["house"]
        dig = dignity(k, sign)
        sb = shadbala_of(chart, k)
        domain = KARAKA_B[k]

        # 品位（高揚/定座/友好＝支持、敵対/減衰＝反証。中立は finding を出さない）
        pol, st, label = DIGNITY_INFO[dig]
        if pol == "support":
            findings.append(Finding(
                factor=f"カラカ {PLANET_JP[k]} が{label}({sign})",
                basis=f"{PLANET_JP[k]}=職業の自然表示星。{label}で領域が発露しやすい。領域：{domain}",
                polarity="support", strength=st,
                theme="仕事/適性", sources=["§3-B", "品位"],
            ))
        elif pol == "refute":
            findings.append(Finding(
                factor=f"カラカ {PLANET_JP[k]} が{label}({sign})",
                basis=f"{PLANET_JP[k]}の象徴領域({domain})の発露に難（{label}）",
                polarity="refute", strength=st,
                theme="仕事/適性", sources=["§3-B", "品位"],
                note="吉星アスペクトがあれば別途『救済』材料が併記される（§4）",
            ))

        # 在住ハウス（10/1室=支持寄り、dusthana=反証材料）
        if h in (10, 1):
            findings.append(Finding(
                factor=f"カラカ {PLANET_JP[k]} が{h}室に在住",
                basis=f"仕事/自己の舞台に直結。領域：{domain}／在住サイン：{sign_desc(sign)}",
                polarity="support", strength=2, theme="仕事/適性",
                sources=["§3-B", "サインの性質"],
            ))
        elif h in DUSTHANAS:
            findings.append(Finding(
                factor=f"カラカ {PLANET_JP[k]} が{h}室(dusthana)に在住",
                basis=f"{PLANET_JP[k]}の領域({domain})が表に出にくい面／在住サイン：{sign_desc(sign)}",
                polarity="refute", strength=1, theme="仕事/適性",
                sources=["§3-B", "サインの性質"],
            ))

        # コンバスト
        if is_combust(k, planets):
            findings.append(Finding(
                factor=f"{PLANET_JP[k]} がコンバスト(太陽と近接)",
                basis="減光により象徴機能が弱まる",
                polarity="refute", strength=1, theme="仕事/適性",
                sources=["§4 修飾"],
            ))

        # shadbala 補強（§7.1）
        if sb is not None and sb >= SHADBALA_STRONG:
            findings.append(Finding(
                factor=f"{PLANET_JP[k]} は強い(shadbala {sb} rupas)",
                basis="強さの数値が高く、象徴領域が発露しやすい",
                polarity="support", strength=2, theme="仕事/適性",
                sources=["§7.1 shadbala"], note="しきい値は暫定",
            ))
        elif sb is not None and sb < SHADBALA_WEAK:
            findings.append(Finding(
                factor=f"{PLANET_JP[k]} は弱い(shadbala {sb} rupas)",
                basis="強さの数値が低く、発露に力が要る",
                polarity="refute", strength=1, theme="仕事/適性",
                sources=["§7.1 shadbala"], note="しきい値は暫定",
            ))

        # アスペクト（§4）：凶星アスペクト＝反証、反証があれば吉星アスペクト＝救済
        has_refute = (pol == "refute") or is_combust(k, planets)
        aspect_findings(k, planets, findings, "仕事/適性", has_refute)


# =========================================================
# カテゴリC：惑星ごとの職業象意（関与フィルタ付き）
# =========================================================
def category_c(chart, findings, tenth_lord_house):
    planets = chart["planets"]
    tenth_lord = SIGN_LORD[tenth_house_sign(chart)]  # アスペクト関与の判定に使う
    for k in ["Ma", "Ju", "Ve", "Mo"]:
        p = planets[k]
        sign, h = p["sign"], p["house"]
        domain = PLANET_C[k]
        dig = dignity(k, sign)
        sb = shadbala_of(chart, k)

        # 関与フィルタ（§3-C）：通らなければ職業材料として弱い
        reason = career_involvement(k, planets, tenth_lord_house, tenth_lord)
        if reason is None:
            note = ""
            if dig in ("exalted", "own"):
                note = (f"※{'高揚' if dig == 'exalted' else '定座'}で素質はあるが、"
                        f"10室系と関与薄く職業の主軸になりにくい")
            findings.append(Finding(
                factor=f"{PLANET_JP[k]} は10室系と関与が薄い（{h}室在住）",
                basis="関与フィルタ：10室/1室/10室支配星と無関係な惑星の象意は職業材料として弱い",
                polarity="neutral", strength=1, theme="仕事/方向性",
                sources=["§3-C 関与フィルタ"], note=note,
            ))
            continue

        # 関与あり → 方向材料（中立）。高揚/定座なら方向材料そのものの強度を底上げ
        strength = 3 if dig in ("exalted", "own") else 2
        findings.append(Finding(
            factor=f"{PLANET_JP[k]} が職業に関与（{reason}）",
            basis=f"関与の根拠：{reason}。{PLANET_JP[k]}の方向：{domain}／在住サイン：{sign_desc(sign)}",
            polarity="neutral", strength=strength, theme="仕事/方向性",
            sources=["§3-C", "§4 アスペクト", "サインの性質"],
        ))
        # 品位の支持/反証材料（高揚/定座は上の強度に反映済みなので重複させない。中立サインは出さない）
        pol, st, label = DIGNITY_INFO[dig]
        if pol == "support" and dig not in ("exalted", "own"):
            findings.append(Finding(
                factor=f"{PLANET_JP[k]} が{label}({sign})",
                basis=f"関与する{PLANET_JP[k]}が{label}で、{domain}方向の発露を後押し",
                polarity="support", strength=st, theme="仕事/方向性",
                sources=["§3-C", "品位"],
            ))
        elif pol == "refute":
            findings.append(Finding(
                factor=f"{PLANET_JP[k]} が{label}({sign})",
                basis=f"関与する惑星だが{label}で、方向({domain})の発露に難",
                polarity="refute", strength=st, theme="仕事/方向性",
                sources=["§3-C", "品位"],
            ))
        if sb is not None and sb >= SHADBALA_STRONG:
            findings.append(Finding(
                factor=f"{PLANET_JP[k]} は強い(shadbala {sb} rupas)",
                basis=f"関与する惑星が強く、{PLANET_JP[k]}方向({domain})の材料が強まる",
                polarity="support", strength=3, theme="仕事/方向性",
                sources=["§7.1 shadbala"], note="しきい値は暫定",
            ))
        elif sb is not None and sb < SHADBALA_WEAK:
            findings.append(Finding(
                factor=f"{PLANET_JP[k]} は弱い(shadbala {sb} rupas)",
                basis="関与するが強さが低く、発露に力が要る",
                polarity="refute", strength=1, theme="仕事/方向性",
                sources=["§7.1 shadbala"], note="しきい値は暫定",
            ))

        # アスペクト（§4）：凶星アスペクト＝反証、反証があれば吉星アスペクト＝救済
        has_refute = (pol == "refute") or is_combust(k, planets)
        aspect_findings(k, planets, findings, "仕事/方向性", has_refute)


# =========================================================
# 出力（第3層＝材料ボードの簡易版）
# =========================================================
def render(findings, chart):
    meta = chart["meta"]
    calc = meta.get("calc", {})
    L = []
    L.append("=" * 72)
    L.append("鑑定支援 — 材料ボード（第2層プロトタイプ）")
    L.append("テーマ：仕事（職業の方向性・適性）")
    L.append(f"対象：{meta.get('name', '?')}  / アヤナーンシャ：{calc.get('ayanamsha', '?')}")
    L.append("=" * 72)

    groups = {"support": [], "refute": [], "neutral": []}
    for f in findings:
        groups[f.polarity].append(f)

    titles = {
        "support": "【支持】方向・適性を後押しする材料",
        "refute": "【反証】慎重に見る／障害・遠回りの材料",
        "neutral": "【中立】方向の手がかり（吉凶ではない）",
    }
    for pol in ["support", "refute", "neutral"]:
        L.append("")
        L.append(titles[pol])
        L.append("-" * 72)
        if not groups[pol]:
            L.append("（なし）")
        for f in groups[pol]:
            L.append(f"・[{'★' * f.strength}] {f.factor}")
            L.append(f"    根拠：{f.basis}")
            L.append(f"    出所：{', '.join(f.sources)}  テーマ：{f.theme}")
            if f.note:
                L.append(f"    注 ：{f.note}")

    L.append("")
    L.append("=" * 72)
    L.append("※ これは『材料』であり結論ではありません。")
    L.append("※ 支持・反証・中立を突き合わせ、矛盾も含めて一つの像に統合し、")
    L.append("   自分の言葉で書くのは鑑定者の仕事です（human-in-the-loop）。")
    L.append("※ 未実装(TODO)：papakartari・ムーラトリコーナ度数判定・D10。")
    L.append("=" * 72)
    return "\n".join(L)


def build_board(path):
    """JSONを読み、材料ボードのテキストとchartを返す。"""
    with open(path, encoding="utf-8") as fp:
        chart = json.load(fp)
    findings = []
    category_signs(chart, findings)
    tenth_lord_house = category_a(chart, findings)
    category_b(chart, findings)
    category_c(chart, findings, tenth_lord_house)
    return render(findings, chart), chart


def script_dir():
    return os.path.dirname(os.path.abspath(__file__))


def choose_file_interactively():
    """チャートJSONファイル/ の .json を一覧表示し、番号で選ばせる。
       パスを手で打たずに済むようにするための対話メニュー。"""
    base = script_dir()
    json_dir = os.path.join(base, JSON_DIR)
    if not os.path.isdir(json_dir):
        json_dir = base  # フォルダが無い場合はスクリプトと同じ場所を探す
    files = sorted(f for f in os.listdir(json_dir) if f.lower().endswith(".json"))
    if not files:
        print(f"JSONファイルが見つかりません（探した場所：{json_dir}）")
        return None

    print("=" * 60)
    print("どのチャートの材料ボードを作りますか？番号を入力して Enter。")
    print("（やめる場合は q を入力して Enter）")
    print("-" * 60)
    for i, f in enumerate(files, 1):
        print(f"  {i}: {f}")
    print("=" * 60)

    while True:
        ans = input("番号 > ").strip()
        if ans.lower() in ("q", "quit", "exit"):
            print("中止しました。")
            return None
        if ans.isdigit() and 1 <= int(ans) <= len(files):
            return os.path.join(json_dir, files[int(ans) - 1])
        print(f"1〜{len(files)} の番号、または q を入力してください。")


def save_output(text, chart):
    """材料ボード/ に『材料ボード_名前_日付.txt』で保存し、保存パスを返す。"""
    base = script_dir()
    out_dir = os.path.join(base, OUTPUT_DIR)
    os.makedirs(out_dir, exist_ok=True)
    name = chart.get("meta", {}).get("name", "chart").strip().replace(" ", "_") or "chart"
    date = datetime.date.today().isoformat()
    path = os.path.join(out_dir, f"材料ボード_{name}_{date}.txt")
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(text)
    return path


def main():
    # 引数でJSONを指定された場合は従来どおり（画面に表示のみ）。
    if len(sys.argv) > 1:
        text, _ = build_board(sys.argv[1])
        print(text)
        return

    # 引数なし → 番号メニュー。選択 → 表示 → 材料ボード/ に自動保存。
    path = choose_file_interactively()
    if path is None:
        return
    text, chart = build_board(path)
    print()
    print(text)
    saved = save_output(text, chart)
    print()
    print(f"保存しました → {saved}")


if __name__ == "__main__":
    main()
