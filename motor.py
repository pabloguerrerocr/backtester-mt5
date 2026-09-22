"""Motor de backtest vectorizado, sin look-ahead y con costos."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Resultado:
    equity: pd.Series          # curva de capital de la estrategia (base 1.0)
    equity_bh: pd.Series       # buy & hold sobre el mismo periodo
    retornos: pd.Series        # retornos netos por barra
    posicion: pd.Series        # posicion efectivamente mantenida en cada barra
    operaciones: int
    costo_total: float         # fraccion de capital consumida por costos


def correr(
    df: pd.DataFrame,
    senal: pd.Series,
    costo_por_operacion: float = 0.0,
    retraso: int = 1,
) -> Resultado:
    """Ejecuta la senal con `retraso` barras y descuenta costos en cada cambio.

    costo_por_operacion es una fraccion (0.0001 = 1 punto basico) aplicada a
    cada cambio de posicion: cubre spread mas comision mas slippage.
    """
    if retraso < 1:
        raise ValueError("retraso debe ser >= 1: ejecutar en la misma barra es look-ahead")

    ret = df["close"].pct_change()
    pos = senal.shift(retraso)

    valido = pos.notna() & ret.notna()
    ret, pos = ret[valido], pos[valido]

    cambios = pos.diff().abs().fillna(pos.abs())
    costos = cambios * costo_por_operacion

    ret_neto = pos * ret - costos
    equity = (1 + ret_neto).cumprod()
    equity_bh = (1 + ret).cumprod()

    return Resultado(
        equity=equity,
        equity_bh=equity_bh,
        retornos=ret_neto,
        posicion=pos,
        operaciones=int((cambios > 0).sum()),
        costo_total=float(costos.sum()),
    )


@dataclass
class Costo:
    fraccion: float               # costo por cambio de posicion, fraccion del precio
    spread_bp: float              # spread medio observado en el historico
    pct_velas_sin_spread: float   # cuanto del historico trae spread = 0
    piso_aplicado: bool

    @property
    def bp(self) -> float:
        return self.fraccion * 10_000


def costo_desde_spread(
    df: pd.DataFrame,
    punto: float,
    comision_bp: float = 0.0,
    piso_bp: float = 0.5,
) -> Costo:
    """Costo por operacion a partir del spread historico, con piso obligatorio.

    El campo `spread` de las velas llega en cero en buena parte del historico
    (en una demo puede ser el 100%). Tomarlo al pie de la letra equivale a
    suponer que operar es gratis, que es justo el sesgo que este proyecto mide.
    Por eso se aplica un piso: nunca se asume un costo menor a `piso_bp`.
    """
    spread_bp = float(df["spread"].mean() * punto / df["close"].mean() * 10_000)
    efectivo = max(spread_bp, piso_bp)
    return Costo(
        fraccion=(efectivo + comision_bp) / 10_000,
        spread_bp=spread_bp,
        pct_velas_sin_spread=float((df["spread"] == 0).mean()),
        piso_aplicado=efectivo > spread_bp,
    )
