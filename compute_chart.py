#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
compute_chart.py  —  Parashara's Light を使わずにチャートJSONを作るアダプタ

役割:
  生年月日・時刻・場所を入力すると、既存の鑑定文/ワークシート・プログラムが
  読む chart_data.json と「同じスキーマ」の dict を返す。
  → 下流（render_reading.py / render_sheet.py / 鑑定文生成）はそのまま動く。

検証済みの仕様（佐藤花子さんの実データで PL と突き合わせ済み）:
  - アヤナムシャ : Lahiri
  - ハウス       : whole sign
  - ノード       : TRUE_NODE（PL と一致）
  - 度数表記     : 分は切り捨て（PL と一致）

まだ未実装（フェーズ2）でスキーマ上は空/プレースホルダにしてある項目:
  - 分割図 D9 以降（D1 は算出済み）
  - ashtakavarga（アシュタカヴァルガ）
  - shadbala（シャドバラ）
  これらは career 鑑定文には不要。必要になった段階で同じ dict に足せばよい。
"""
import swisseph as swe
import datetime as dt

SIGNS = ["Aries","Taurus","Gemini","Cancer","Leo","Virgo",
         "Libra","Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"]
NAK = ["Ashwini","Bharani","Krittika","Rohini","Mrigashira","Ardra","Punarvasu",
       "Pushya","Ashlesha","Magha","P.Phalguni","U.Phalguni","Hasta","Chitra",
       "Swati","Vishakha","Anuradha","Jyeshtha","Mula","P.Ashadha","U.Ashadha",
       "Shravana","Dhanishta","Satabhi.","P.Bhadra","U.Bhadra","Revati"]
VIM_LORDS = ["Ke","Ve","Su","Mo","Ma","Ra","Ju","Sa","Me"]
VIM_YEARS = {"Ke":7,"Ve":20,"Su":6,"Mo":10,"Ma":7,"Ra":18,"Ju":16,"Sa":19,"Me":17}
NAK_LORD_SEQ = [VIM_LORDS[i % 9] for i in range(27)]
YEAR_DAYS = 365.2425

BODIES = {
    "Su": swe.SUN, "Mo": swe.MOON, "Ma": swe.MARS, "Me": swe.MERCURY,
    "Ju": swe.JUPITER, "Ve": swe.VENUS, "Sa": swe.SATURN,
    "Ra": swe.TRUE_NODE,                    # ← PL と一致するのは真ノード
    "Ur": swe.URANUS, "Ne": swe.NEPTUNE, "Pl": swe.PLUTO,
}
OUTER = {"Ur", "Ne", "Pl"}

# --- 小道具 ---
def _dm(x_in_sign):
    """サイン内の度数 → 'DD:MM'（分は切り捨て = PL 表記）"""
    d = int(x_in_sign)
    m = int((x_in_sign - d) * 60)      # floor
    return f"{d:02d}:{m:02d}"

def _nak_pada(lon):
    span = 360/27
    idx = int(lon // span)
    within = lon - idx*span
    pada = int(within // (span/4)) + 1
    return NAK[idx], pada, NAK_LORD_SEQ[idx], idx, within

def _sublords(lon):
    """KP方式の star/sub/subsub（Vimshottari比率で細分）"""
    span = 360/27
    _, _, star, idx, within = _nak_pada(lon)
    def subdivide(start_lord, seg_within, seg_total):
        order = VIM_LORDS[VIM_LORDS.index(start_lord):] + VIM_LORDS[:VIM_LORDS.index(start_lord)]
        pos = 0.0
        for lord in order:
            seg = seg_total * VIM_YEARS[lord] / 120.0
            if seg_within < pos + seg or lord == order[-1]:
                return lord, pos, seg
            pos += seg
    sub, sub_start, sub_len = subdivide(star, within, span)
    subsub, _, _ = subdivide(sub, within - sub_start, sub_len)
    return {"star": star, "sub": sub, "subsub": subsub}

def _weekday(y, m, d):
    return dt.date(y, m, d).strftime("%a")

def _deg_to_dms_str(deg, is_lat):
    """10進度 → 37N27'00 / 138E51'00 形式"""
    hemi = ("N" if deg >= 0 else "S") if is_lat else ("E" if deg >= 0 else "W")
    total_sec = round(abs(deg) * 3600)          # まず総秒に丸めてから分解（繰り上げ安全）
    d, rem = divmod(total_sec, 3600)
    m, s = divmod(rem, 60)
    return f"{d}{hemi}{m:02d}'{s:02d}"


def compute_chart(name, birth_dt, tz_hours, lat, lon,
                  city="", state="", country="",
                  include_outer=True):
    """
    name      : ファイル名用キー（例 'Sato_Hanako'）
    birth_dt  : datetime（現地時刻）
    tz_hours  : タイムゾーン時差（日本なら +9）
    lat, lon  : 10進度（北緯・東経を正）
    戻り値    : chart_data.json と同スキーマの dict
    """
    ut = (birth_dt.hour + birth_dt.minute/60 + birth_dt.second/3600) - tz_hours
    jd = swe.julday(birth_dt.year, birth_dt.month, birth_dt.day, ut, swe.GREG_CAL)
    swe.set_sid_mode(swe.SIDM_LAHIRI)
    F = swe.FLG_SIDEREAL | swe.FLG_SPEED

    # アセンダント（whole sign）
    _, ascmc = swe.houses_ex(jd, lat, lon, b'W', swe.FLG_SIDEREAL)
    asc_lon = ascmc[0]
    asc_sign_idx = int(asc_lon // 30)
    asc_nak, asc_pada, _, _, _ = _nak_pada(asc_lon)

    def house_of(sign_idx):
        return (sign_idx - asc_sign_idx) % 12 + 1

    # 惑星
    planets, lon_cache = {}, {}
    for key, body in BODIES.items():
        if key in OUTER and not include_outer:
            continue
        pos = swe.calc_ut(jd, body, F)[0]
        plon, speed = pos[0], pos[3]
        lon_cache[key] = plon
        s_idx = int(plon // 30)
        nk, pd, _, _, _ = _nak_pada(plon)
        entry = {
            "name_en": {"Su":"Sun","Mo":"Moon","Ma":"Mars","Me":"Mercury",
                        "Ju":"Jupiter","Ve":"Venus","Sa":"Saturn","Ra":"Rahu",
                        "Ur":"Uranus","Ne":"Neptune","Pl":"Pluto"}[key],
            "sign": SIGNS[s_idx], "degree": _dm(plon % 30),
            "house": house_of(s_idx),
            "retrograde": (key == "Ra") or (speed < 0),
        }
        if key not in OUTER:
            entry.update({"nakshatra": nk, "pada": pd, "lords": _sublords(plon)})
        else:
            entry["outer"] = True
        planets[key] = entry

    # ケートゥ = ラーフ + 180
    ke_lon = (lon_cache["Ra"] + 180) % 360
    lon_cache["Ke"] = ke_lon
    s_idx = int(ke_lon // 30)
    nk, pd, _, _, _ = _nak_pada(ke_lon)
    planets["Ke"] = {"name_en":"Ketu","sign":SIGNS[s_idx],"degree":_dm(ke_lon%30),
                     "house":house_of(s_idx),"retrograde":True,
                     "nakshatra":nk,"pada":pd,"lords":_sublords(ke_lon)}

    # D1 の houses（sign + planets）
    order = ["Su","Mo","Ma","Me","Ju","Ve","Sa","Ra","Ke"] + (["Ur","Ne","Pl"] if include_outer else [])
    d1_houses = {}
    for h in range(1, 13):
        sign_idx = (asc_sign_idx + h - 1) % 12
        occupants = [p for p in order if int(lon_cache[p] // 30) == sign_idx]
        if h == 1:
            occupants = ["As"] + occupants
        d1_houses[str(h)] = {"sign": SIGNS[sign_idx], "planets": occupants}

    # Chara Karaka（7カラカ, MK/PuK 統合）
    kp = ["Su","Mo","Ma","Me","Ju","Ve","Sa"]
    ranked = sorted(kp, key=lambda p: lon_cache[p] % 30, reverse=True)
    karakas = dict(zip(["AK","AmK","BK","MK_PuK","PiK","GK","DK"], ranked))

    # Vimshottari Dasha（level2 = Maha-Antar、誕生日以降）
    dasha_periods = _vimshottari(lon_cache["Mo"], birth_dt)

    # sunrise / sunset（取得できなければ空文字）
    sunrise, sunset = _rise_set(jd, lat, lon, tz_hours)

    return {
        "_schema_version": "0.1",
        "_about": "pyswisseph で算出した構造化データ（PL互換スキーマ）。",
        "meta": {
            "name": name,
            "source": "pyswisseph (Swiss Ephemeris)",
            "birth": {"weekday": _weekday(birth_dt.year, birth_dt.month, birth_dt.day),
                      "date": birth_dt.strftime("%Y-%m-%d"),
                      "time": birth_dt.strftime("%H:%M:%S")},
            "place": {"city": city, "state": state, "country": country,
                      "latitude": _deg_to_dms_str(lat, True),
                      "longitude": _deg_to_dms_str(lon, False),
                      "timezone": str(int(tz_hours)), "dst": 0},
            "calc": {"ayanamsha": "Lahiri",
                     "ayanamsha_value": _ayan_str(jd),
                     "sunrise": sunrise, "sunset": sunset, "ishtakal": ""},
            "house_system": "whole_sign",
            "include_outer_planets": include_outer,
        },
        "ascendant": {"sign": SIGNS[asc_sign_idx], "degree": _dm(asc_lon % 30),
                      "nakshatra": asc_nak, "pada": asc_pada,
                      "lords": _sublords(asc_lon)},
        "planets": planets,
        "charts": {"D1": {"name":"Rasi","significations":"body, self, overall life",
                          "houses": d1_houses}},
        "dasha": {"system":"Vimshottari",
                  "_note":"level=2 は Maha-Antar。start は各期の開始日。",
                  "periods": dasha_periods},
        "karakas": {"scheme":"Chara (7-karaka, Jaimini)", **karakas},
        # --- 以下フェーズ2（スキーマの形だけ用意）---
        "ashtakavarga": {"sarvashtakavarga": {}, "bhinnashtakavarga": {}},
        "shadbala": {},
    }


def _vimshottari(moon_lon, birth_dt):
    span = 360/27
    idx = int(moon_lon // span); within = moon_lon - idx*span
    lord = NAK_LORD_SEQ[idx]; frac = within/span
    order = VIM_LORDS[VIM_LORDS.index(lord):] + VIM_LORDS[:VIM_LORDS.index(lord)]
    maha_start = birth_dt - dt.timedelta(days=VIM_YEARS[lord]*frac*YEAR_DAYS)
    rows = []
    for maha in order + order:      # 2周ぶん作って誕生日以降を切り出す
        ao = VIM_LORDS[VIM_LORDS.index(maha):] + VIM_LORDS[:VIM_LORDS.index(maha)]
        a = maha_start
        for antar in ao:
            rows.append({"level":2,"maha":maha,"antar":antar,
                         "start":a.strftime("%Y-%m-%d"), "_dt":a})
            a = a + dt.timedelta(days=VIM_YEARS[maha]*VIM_YEARS[antar]/120.0*YEAR_DAYS)
        maha_start = maha_start + dt.timedelta(days=VIM_YEARS[maha]*YEAR_DAYS)
    # 誕生日を含むアンタルから
    start_i = 0
    for i, r in enumerate(rows):
        if r["_dt"] <= birth_dt:
            start_i = i
    return [{k:v for k,v in r.items() if k != "_dt"} for r in rows[start_i:start_i+40]]


def _ayan_str(jd):
    a = swe.get_ayanamsa_ut(jd)
    d = int(a); m = int((a-d)*60); s = int(round((((a-d)*60)-m)*60))
    return f"-{d:02d}:{m:02d}:{s:02d}"   # PL の符号表記に合わせる


def _rise_set(jd, lat, lon, tz):
    try:
        def local(jd_ut):
            y,m,d,h = swe.revjul(jd_ut + tz/24.0)
            hh=int(h); mm=int((h-hh)*60); ss=int((((h-hh)*60)-mm)*60)
            return f"{hh:02d}:{mm:02d}:{ss:02d}"
        geo = (lon, lat, 0)
        r = swe.rise_trans(jd-0.5, swe.SUN, swe.CALC_RISE|swe.BIT_DISC_CENTER, geo)[1][0]
        s = swe.rise_trans(jd-0.5, swe.SUN, swe.CALC_SET|swe.BIT_DISC_CENTER, geo)[1][0]
        return local(r), local(s)
    except Exception:
        return "", ""


# ---- 単体テスト（佐藤花子さんで実行） ----
if __name__ == "__main__":
    import json
    data = compute_chart(
        name="Sato_Hanako",
        birth_dt=dt.datetime(2026, 6, 23, 14, 49, 27),
        tz_hours=9, lat=37+27/60, lon=138+51/60,
        city="Nagaoka", state="Niigata", country="Japan",
    )
    print(json.dumps(data, ensure_ascii=False, indent=2))
