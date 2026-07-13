#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
compute_chart_isolated.py — compute_chart() を別プロセスで実行するラッパー

なぜ必要か:
  compute_chart() は pyswisseph（C言語の天文計算ライブラリ）を呼ぶ。稀に、特定の
  緯度経度・日時の組み合わせで pyswisseph 側がセグメンテーションフォルト（Cレベルの
  異常終了）を起こすことが公開環境（Streamlit Cloud）で確認された。セグフォルトは
  Python の try/except では捕まえられず、同じプロセスで動く Streamlit サーバー全体を
  巻き込んで落としてしまう（＝1人の入力が原因で他の利用者のアクセスも止まる）。
  そこで compute_chart() の呼び出しだけを別プロセスに分離し、そのプロセスが
  クラッシュしても本体（Streamlitサーバー）は生き残るようにする。

  ここは multiprocessing の target 用に「app.py（Streamlitのメインスクリプト）とは
  別のモジュール」にする必要がある。spawn 方式は子プロセスで対象モジュールを
  再importするため、もし app.py 自身を target にすると、子プロセス側で
  st.set_page_config() 等のStreamlit呼び出しが再実行されてしまう。
"""
import multiprocessing as mp

from compute_chart import compute_chart


def _worker(kwargs, result_queue):
    try:
        data = compute_chart(**kwargs)
        result_queue.put(("ok", data))
    except Exception as e:
        result_queue.put(("error", f"{type(e).__name__}: {e}"))


def compute_chart_safe(name, birth_dt, tz_hours, lat, lon,
                       city="", state="", country="",
                       include_outer=True, timeout=20):
    """compute_chart() を別プロセスで実行する。戻り値・例外の意味は compute_chart() と同じ。
    プロセスがクラッシュ（セグフォルト等）またはタイムアウトした場合は RuntimeError を出す。"""
    kwargs = dict(name=name, birth_dt=birth_dt, tz_hours=tz_hours, lat=lat, lon=lon,
                  city=city, state=state, country=country, include_outer=include_outer)
    ctx = mp.get_context("spawn")
    result_queue = ctx.Queue()
    proc = ctx.Process(target=_worker, args=(kwargs, result_queue))
    proc.start()
    proc.join(timeout)

    if proc.is_alive():
        proc.terminate()
        proc.join()
        raise RuntimeError("計算がタイムアウトしました（時間をおいて再度お試しください）")

    if proc.exitcode != 0:
        raise RuntimeError(f"計算プロセスが異常終了しました（exit code {proc.exitcode}）。"
                           f"入力した緯度・経度・時差の値をご確認ください。")

    status, payload = result_queue.get()
    if status == "error":
        raise RuntimeError(payload)
    return payload
