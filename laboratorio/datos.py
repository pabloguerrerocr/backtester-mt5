"""Velas diarias de MT5 con copia local, para poder correr el laboratorio con MT5 cerrado.

Cada corrida intenta traer la historia fresca de MT5; si no puede, usa la ultima
copia en laboratorio/cache/. Asi la tarea programada nunca se queda sin datos.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pandas as pd

CACHE = Path(__file__).parent / "cache"
DESDE = dt.datetime(2005, 1, 1)
TERMINAL = r"C:\Program Files\MetaTrader 5\terminal64.exe"   # con la ruta, initialize abre MT5 si esta cerrado

# simbolo de MetaQuotes-Demo -> clase de activo. Mismos parametros para todos:
# si una regla solo funciona en un mercado, es suerte (Radge, Carver).
MERCADOS = {
    "EURUSD": "divisas", "GBPUSD": "divisas", "USDJPY": "divisas", "AUDUSD": "divisas",
    "USDCAD": "divisas", "USDCHF": "divisas", "NZDUSD": "divisas",
    "XAUUSD": "metales", "XAGUSD": "metales",
    "US500": "indices", "USTEC": "indices", "US30": "indices",
    "XTIUSD": "energia", "XBRUSD": "energia",
    "BTCUSD": "cripto",
}


def _desde_mt5(simbolo: str) -> pd.DataFrame | None:
    import MetaTrader5 as mt5
    if not mt5.symbol_select(simbolo, True):
        return None
    crudo = mt5.copy_rates_range(simbolo, mt5.TIMEFRAME_D1, DESDE, dt.datetime.now())
    info = mt5.symbol_info(simbolo)
    if crudo is None or len(crudo) < 300 or info is None:
        return None
    df = pd.DataFrame(crudo)
    df["time"] = pd.to_datetime(df["time"], unit="s").dt.normalize()
    df = df.set_index("time").iloc[:-1]                    # el dia de hoy sigue abierto
    df["spread_precio"] = df["spread"] * info.point
    return df[["open", "high", "low", "close", "spread_precio"]]


def diarias(simbolos=MERCADOS) -> dict[str, pd.DataFrame]:
    """{simbolo: velas D1}. Usa MT5 si responde; si no, la copia local."""
    CACHE.mkdir(exist_ok=True)
    try:
        import MetaTrader5 as mt5
        hay_mt5 = mt5.initialize(path=TERMINAL, timeout=60000)
    except ImportError:
        hay_mt5 = False
    print("MT5 conectado" if hay_mt5 else "MT5 no responde: uso la copia local", file=sys.stderr)
    salida = {}
    try:
        for s in simbolos:
            archivo = CACHE / f"{s}_D1.csv"
            df = _desde_mt5(s) if hay_mt5 else None
            if df is not None:
                df.to_csv(archivo)
            elif archivo.exists():
                df = pd.read_csv(archivo, index_col=0, parse_dates=True)
            if df is None:
                print(f"  sin datos de {s}", file=sys.stderr)
                continue
            salida[s] = df
    finally:
        if hay_mt5:
            mt5.shutdown()
    return salida
