#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
compute_chart_worker.py — compute_chart() を独立プロセスとして実行するための単体スクリプト

compute_chart_isolated.py から subprocess 経由で呼ばれる。標準入力から JSON でパラメータを
受け取り、compute_chart() の結果を標準出力に JSON で返す。単体スクリプトとして直接
`python3 compute_chart_worker.py` で起動するので、Streamlit（app.py）の実行状態とは
無関係な、まっさらな別プロセスになる。
"""
import datetime as dt
import json
import sys

from compute_chart import compute_chart


def main():
    payload = json.loads(sys.stdin.read())
    birth_dt = dt.datetime.fromisoformat(payload["birth_dt"])
    data = compute_chart(
        payload["name"], birth_dt, payload["tz_hours"], payload["lat"], payload["lon"],
        city=payload.get("city", ""), state=payload.get("state", ""),
        country=payload.get("country", ""), include_outer=payload.get("include_outer", True),
    )
    json.dump(data, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
