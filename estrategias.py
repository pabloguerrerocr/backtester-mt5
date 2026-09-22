"""Senales de entrada/salida.

Convencion: la senal de la barra t se calcula SOLO con informacion cerrada
hasta t. El motor la ejecuta en t+1. Ninguna estrategia mira el futuro.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def cruce_medias(df: pd.DataFrame, rapida: int = 20, lenta: int = 50) -> pd.Series:
    """Largo cuando la media rapida esta sobre la lenta. 1 = largo, 0 = fuera."""
    c = df["close"]
    mr = c.rolling(rapida).mean()
    ml = c.rolling(lenta).mean()
    senal = (mr > ml).astype(float)
    senal[mr.isna() | ml.isna()] = np.nan
    return senal.rename(f"MA{rapida}/{lenta}")


def rsi(df: pd.DataFrame, periodo: int = 14, compra: int = 30, venta: int = 70) -> pd.Series:
    """Compra en sobreventa, vende en sobrecompra. Mantiene posicion entre umbrales."""
    delta = df["close"].diff()
    ganancia = delta.clip(lower=0).ewm(alpha=1 / periodo, adjust=False).mean()
    perdida = (-delta.clip(upper=0)).ewm(alpha=1 / periodo, adjust=False).mean()
    rs = ganancia / perdida.replace(0, np.nan)
    valor = 100 - 100 / (1 + rs)

    senal = pd.Series(np.nan, index=df.index)
    senal[valor < compra] = 1.0
    senal[valor > venta] = 0.0
    senal = senal.ffill().fillna(0.0)
    senal[: periodo + 1] = np.nan
    return senal.rename(f"RSI{periodo} {compra}/{venta}")


def comprar_y_mantener(df: pd.DataFrame) -> pd.Series:
    return pd.Series(1.0, index=df.index, name="buy & hold")


CATALOGO = {
    "ma": cruce_medias,
    "rsi": rsi,
    "bh": comprar_y_mantener,
}
