"""Descarga de velas desde el terminal MetaTrader 5."""
from __future__ import annotations

import pandas as pd
import MetaTrader5 as mt5

TIMEFRAMES = {
    "M15": mt5.TIMEFRAME_M15,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
    "W1": mt5.TIMEFRAME_W1,
}


class ErrorMT5(RuntimeError):
    pass


def conectar() -> None:
    if not mt5.initialize():
        raise ErrorMT5(f"no se pudo abrir el terminal: {mt5.last_error()}")


def desconectar() -> None:
    mt5.shutdown()


def info_cuenta() -> dict:
    a = mt5.account_info()
    if a is None:
        raise ErrorMT5(f"sin cuenta: {mt5.last_error()}")
    return {"login": a.login, "servidor": a.server, "balance": a.balance, "moneda": a.currency}


def velas(simbolo: str, timeframe: str, n: int) -> pd.DataFrame:
    """Ultimas n velas cerradas. Descarta la vela en formacion."""
    if timeframe not in TIMEFRAMES:
        raise ValueError(f"timeframe invalido: {timeframe}. Use {list(TIMEFRAMES)}")
    if not mt5.symbol_select(simbolo, True):
        raise ErrorMT5(f"simbolo no disponible: {simbolo}")

    crudo = mt5.copy_rates_from_pos(simbolo, TIMEFRAMES[timeframe], 0, n + 1)
    if crudo is None or len(crudo) == 0:
        raise ErrorMT5(f"sin datos para {simbolo} {timeframe}: {mt5.last_error()}")

    df = pd.DataFrame(crudo)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df = df.set_index("time").iloc[:-1]  # la ultima vela aun no cerro
    return df[["open", "high", "low", "close", "tick_volume", "spread"]]


def hora_servidor(simbolo: str = "EURUSD") -> pd.Timestamp:
    """Hora del broker. El indice de las velas viene en esta zona, no en UTC."""
    tick = mt5.symbol_info_tick(simbolo)
    if tick is None:
        raise ErrorMT5(f"sin cotizacion para {simbolo}: {mt5.last_error()}")
    return pd.to_datetime(tick.time, unit="s")


def punto(simbolo: str) -> float:
    s = mt5.symbol_info(simbolo)
    if s is None:
        raise ErrorMT5(f"simbolo no disponible: {simbolo}")
    return s.point
