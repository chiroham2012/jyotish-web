#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
chart_bridge.py — compute_chart() の JSON を generate_chart_auto.build_svg() が
要求する形へ変換する、唯一の橋渡し関数。

画面表示（app.py）と PDFワークシート生成（build_worksheet_pdf.py）の両方から
この同じ関数を使うことで、「画面とPDFでチャート図のデザインが食い違う」ことが
今後起きないようにする（2026-07-08、実際にこの食い違いが起きて気づいた教訓）。

変換内容:
  ・星座はフルネーム("Aries")なので3文字略("Ari")へ
  ・逆行は末尾に "R"（ただしラーフ/ケートゥは常時逆行なので付けない＝PL表記に合わせる）
"""
_PLANET_ORDER = ["Su", "Mo", "Ma", "Me", "Ju", "Ve", "Sa", "Ra", "Ke", "Ur", "Ne", "Pl"]


def chart_json_to_svg_data(data, display_name):
    asc = data["ascendant"]
    planets = [("As", asc["sign"][:3], asc["degree"])]
    pdict = data["planets"]
    for code in _PLANET_ORDER:
        p = pdict.get(code)
        if not p:
            continue
        c = code
        if p.get("retrograde") and code not in ("Ra", "Ke"):
            c = code + "R"
        planets.append((c, p["sign"][:3], p["degree"]))
    b = data["meta"]["birth"]
    pl = data["meta"]["place"]
    place_bits = [x for x in (pl.get("city", ""), pl.get("state", ""), pl.get("country", "")) if x]
    birthinfo = f'{b["date"]}  {b["time"][:5]}  /  {", ".join(place_bits)}'
    return {"name": display_name, "birthinfo": birthinfo, "planets": planets}
