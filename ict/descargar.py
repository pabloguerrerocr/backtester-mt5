"""Baja velas M5, M15, H4 y D1 del terminal MT5 (cuenta demo) a CSV, por trozos.

El terminal limita cada pedido a `maxbars` (100 000); por eso se pide mes a mes.
"""
import datetime as dt
import os
import sys

import MetaTrader5 as mt5
import pandas as pd

AQUI = os.path.dirname(os.path.abspath(__file__))
TF = {"M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
      "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1}


def bajar(simbolo, tf, desde, hasta):
    trozos, ini = [], desde
    while ini < hasta:
        fin = min(ini + dt.timedelta(days=31), hasta)
        r = mt5.copy_rates_range(simbolo, TF[tf], ini, fin)
        if r is not None and len(r):
            trozos.append(pd.DataFrame(r))
        ini = fin
    if not trozos:
        return None
    df = pd.concat(trozos).drop_duplicates("time").sort_values("time")
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return df[["time", "open", "high", "low", "close", "tick_volume", "spread"]]


if __name__ == "__main__":
    simbolos = sys.argv[1:] or ["EURUSD", "GBPUSD", "XAUUSD"]
    assert mt5.initialize(), mt5.last_error()
    desde = dt.datetime(2019, 1, 1, tzinfo=dt.timezone.utc)
    hasta = dt.datetime(2026, 9, 24, tzinfo=dt.timezone.utc)
    for s in simbolos:
        mt5.symbol_select(s, True)
        for tf in TF:
            df = bajar(s, tf, desde, hasta)
            if df is None:
                print(s, tf, "sin datos", mt5.last_error(), flush=True)
                continue
            df.to_csv(os.path.join(AQUI, "datos", f"{s}_{tf}.csv"), index=False)
            print(s, tf, len(df), df.time.iloc[0], "->", df.time.iloc[-1],
                  f"spread0={(df.spread == 0).mean():.0%}", flush=True)
    mt5.shutdown()
