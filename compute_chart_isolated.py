#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
compute_chart_isolated.py — compute_chart() を独立プロセスで実行するラッパー

なぜ必要か:
  compute_chart() は pyswisseph（C言語の天文計算ライブラリ）を呼ぶ。稀に、特定の
  緯度経度・日時の組み合わせで pyswisseph 側がセグメンテーションフォルト（Cレベルの
  異常終了）を起こすことが公開環境（Streamlit Cloud）で確認された。セグフォルトは
  Python の try/except では捕まえられず、同じプロセスで動く Streamlit サーバー全体を
  巻き込んで落としてしまう（＝1人の入力が原因で他の利用者のアクセスも止まる）。
  そこで compute_chart() の呼び出しだけを別プロセスに分離し、そのプロセスが
  クラッシュしても本体（Streamlitサーバー）は生き残るようにする。

  ★ multiprocessing ではなく subprocess を使う理由:
  最初 multiprocessing（spawn）で実装したところ、子プロセスが Streamlit の
  「__main__ = app.py」状態を引き継いでしまい、app.py 全体を bare mode
  （streamlit run を介さない状態）で丸ごと再実行してしまう不具合が実際に起きた
  （ログに "missing ScriptRunContext" が大量に出た）。streamlit run 環境と
  multiprocessing の既知の相性問題。subprocess で独立スクリプト
  （compute_chart_worker.py）を起動する方式なら、この問題を回避できる
  （build_worksheet_pdf.py の rsvg-convert 呼び出しと同じ方式）。
"""
import datetime as dt
import json
import os
import subprocess
import sys

_WORKER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "compute_chart_worker.py")


def compute_chart_safe(name, birth_dt, tz_hours, lat, lon,
                       city="", state="", country="",
                       include_outer=True, timeout=20):
    """compute_chart() を独立プロセスで実行する。戻り値の意味は compute_chart() と同じ。
    プロセスがクラッシュ（セグフォルト等）またはタイムアウトした場合は RuntimeError を出す。"""
    payload = {
        "name": name,
        "birth_dt": birth_dt.isoformat(),
        "tz_hours": tz_hours,
        "lat": lat,
        "lon": lon,
        "city": city,
        "state": state,
        "country": country,
        "include_outer": include_outer,
    }
    try:
        proc = subprocess.run(
            [sys.executable, _WORKER_PATH],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("計算がタイムアウトしました（時間をおいて再度お試しください）")

    if proc.returncode != 0:
        detail = (proc.stderr or "").strip()[-500:]
        raise RuntimeError(f"計算プロセスが異常終了しました（exit code {proc.returncode}）。"
                           f"入力した緯度・経度・時差の値をご確認ください。{(' 詳細: ' + detail) if detail else ''}")

    return json.loads(proc.stdout)
