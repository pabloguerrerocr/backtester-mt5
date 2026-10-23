"""Estrategias publicadas por traders profesionales, con sus reglas y parametros
originales. No se optimiza nada: los parametros son los del autor, iguales en
todos los mercados.

Cada funcion recibe velas diarias y devuelve la posicion deseada al cierre de
cada dia, en "unidades de riesgo" (+1 = comprado con riesgo normal, -1 =
vendido, 0 = fuera; Carver usa valores continuos entre -2 y +2). El motor la
aplica desde el dia siguiente.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(c: pd.Series, n: int) -> pd.Series:
    return c.ewm(span=n, adjust=False).mean()


def atr(df: pd.DataFrame, n: int) -> pd.Series:
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def rsi(c: pd.Series, n: int) -> pd.Series:
    d = c.diff()
    g = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    p = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + g / p.replace(0, np.nan))


def vol_precio(df: pd.DataFrame) -> pd.Series:
    """Desviacion diaria del precio (en unidades de precio), EWMA de 36 dias como Carver."""
    return df["close"].diff().ewm(span=36, adjust=False).std()


# --------------------------------------------------------------------------
def carver_ewmac(df: pd.DataFrame) -> pd.Series:
    """Robert Carver (ex-AHL), Systematic Trading cap. 15: promedio de 4 cruces de EMA
    (8/32, 16/64, 32/128, 64/256), cada uno dividido por la volatilidad y llevado a
    escala con su escalar publicado; pronostico topado en +-20, posicion = pronostico/10."""
    c, v = df["close"], vol_precio(df)
    escalar = {8: 5.3, 16: 3.75, 32: 2.65, 64: 1.87}
    f = sum(((ema(c, n) - ema(c, 4 * n)) / v * k).clip(-20, 20) for n, k in escalar.items()) / 4
    return (f.clip(-20, 20) / 10).fillna(0)


def _por_reglas(df, entra_largo, entra_corto, sale_largo, sale_corto, stop_dist=None) -> pd.Series:
    """Posicion +1/-1/0 recorriendo dia por dia (entradas, salidas y stop de cierre)."""
    c = df["close"].to_numpy()
    el, ec, sl, sc = (np.asarray(x, dtype=bool) for x in (entra_largo, entra_corto, sale_largo, sale_corto))
    sd = None if stop_dist is None else np.asarray(stop_dist, dtype=float)
    pos = np.zeros(len(c))
    p, stop = 0, np.nan
    for i in range(len(c)):
        if p == 1 and (sl[i] or c[i] < stop):
            p = 0
        elif p == -1 and (sc[i] or c[i] > stop):
            p = 0
        if p == 0:
            if el[i]:
                p, stop = 1, c[i] - (sd[i] if sd is not None else np.inf)
            elif ec[i]:
                p, stop = -1, c[i] + (sd[i] if sd is not None else np.inf)
        pos[i] = p
    return pd.Series(pos, index=df.index)


def clenow_tendencia(df: pd.DataFrame) -> pd.Series:
    """Andreas Clenow, Following the Trend: solo a favor de EMA 50 vs EMA 100; entra al
    cierre mas alto (bajo) de 50 dias; sale con stop movil de 3 ATR(100) desde el
    mejor cierre desde la entrada."""
    c = df["close"].to_numpy()
    e50, e100 = ema(df["close"], 50).to_numpy(), ema(df["close"], 100).to_numpy()
    maxi, mini = df["close"].rolling(50).max().to_numpy(), df["close"].rolling(50).min().to_numpy()
    a = (3 * atr(df, 100)).to_numpy()
    pos = np.zeros(len(c))
    p, mejor = 0, np.nan
    for i in range(len(c)):
        if not np.isfinite(a[i]):
            continue
        if p == 1:
            mejor = max(mejor, c[i])
            if c[i] < mejor - a[i]:
                p = 0
        elif p == -1:
            mejor = min(mejor, c[i])
            if c[i] > mejor + a[i]:
                p = 0
        if p == 0:
            if e50[i] > e100[i] and c[i] >= maxi[i]:
                p, mejor = 1, c[i]
            elif e50[i] < e100[i] and c[i] <= mini[i]:
                p, mejor = -1, c[i]
        pos[i] = p
    return pd.Series(pos, index=df.index)


def tortugas(df: pd.DataFrame) -> pd.Series:
    """Las Tortugas de Dennis (Curtis Faith; Jerry Parker la sigue usando), Sistema 2:
    entra al romper el maximo (minimo) de 55 dias, sale al romper el minimo (maximo)
    de 20 dias, stop a 2 N (ATR de 20)."""
    c = df["close"]
    h55, l55 = df["high"].rolling(55).max().shift(1), df["low"].rolling(55).min().shift(1)
    h20, l20 = df["high"].rolling(20).max().shift(1), df["low"].rolling(20).min().shift(1)
    return _por_reglas(df, c > h55, c < l55, c < l20, c > h20, stop_dist=2 * atr(df, 20))


def connors_rsi2(df: pd.DataFrame) -> pd.Series:
    """Larry Connors, Short Term Trading Strategies That Work: reversion a la media.
    Compra si esta sobre la media de 200 y el RSI(2) baja de 10; sale al cerrar sobre
    la media de 5. Espejo para ventas (RSI(2) sobre 90 bajo la media de 200)."""
    c = df["close"]
    m200, m5, r = c.rolling(200).mean(), c.rolling(5).mean(), rsi(c, 2)
    return _por_reglas(df, (c > m200) & (r < 10), (c < m200) & (r > 90), c > m5, c < m5)


def comprar_y_mantener(df: pd.DataFrame) -> pd.Series:
    """Referencia: comprar el primer dia y no hacer nada mas."""
    return pd.Series(1.0, index=df.index)


ESTRATEGIAS = {
    "carver_ewmac": (carver_ewmac, "Robert Carver", "tendencia"),
    "clenow_tendencia": (clenow_tendencia, "Andreas Clenow", "tendencia"),
    "tortugas_55_20": (tortugas, "Tortugas / Jerry Parker", "tendencia"),
    "connors_rsi2": (connors_rsi2, "Larry Connors", "reversion"),
    "comprar_y_mantener": (comprar_y_mantener, "referencia", "referencia"),
}
