"""Metricas de desempeno ajustadas por riesgo."""
from __future__ import annotations

import numpy as np
import pandas as pd

BARRAS_POR_ANIO = {"M15": 96 * 252, "H1": 24 * 252, "H4": 6 * 252, "D1": 252, "W1": 52}

# Una serie de retornos constantes da std ~1e-19 en vez de 0 exacto. Sin esta
# tolerancia el Sharpe sale del orden de 1e16 y parece un resultado espectacular.
TOL_VOL = 1e-12


def max_drawdown(equity: pd.Series) -> float:
    pico = equity.cummax()
    return float((equity / pico - 1).min())


def resumen(equity: pd.Series, retornos: pd.Series, timeframe: str) -> dict:
    n = BARRAS_POR_ANIO.get(timeframe, 252)
    anios = len(retornos) / n

    total = float(equity.iloc[-1] - 1)
    cagr = float(equity.iloc[-1] ** (1 / anios) - 1) if anios > 0 else np.nan
    desv = float(retornos.std())
    vol = desv * np.sqrt(n)
    sharpe = float(retornos.mean() / desv * np.sqrt(n)) if desv > TOL_VOL else np.nan

    activo = retornos[retornos != 0]
    acierto = float((activo > 0).mean()) if len(activo) else np.nan

    return {
        "retorno_total": total,
        "cagr": cagr,
        "vol_anual": vol,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown(equity),
        "barras_ganadoras": acierto,
        "anios": anios,
    }


def tabla(filas: dict[str, dict]) -> str:
    cols = ["retorno_total", "cagr", "vol_anual", "sharpe", "max_drawdown", "operaciones"]
    etiquetas = ["Retorno", "CAGR", "Vol anual", "Sharpe", "Max DD", "Ops"]
    ancho = max(len(k) for k in filas) + 2

    out = ["  " + "Estrategia".ljust(ancho) + "".join(e.rjust(12) for e in etiquetas)]
    out.append("  " + "-" * (ancho + 12 * len(etiquetas)))
    for nombre, m in filas.items():
        celdas = []
        for c in cols:
            v = m.get(c)
            if v is None or (isinstance(v, float) and np.isnan(v)):
                celdas.append("n/d".rjust(12))
            elif c == "operaciones":
                celdas.append(f"{int(v)}".rjust(12))
            elif c == "sharpe":
                celdas.append(f"{v:.2f}".rjust(12))
            else:
                celdas.append(f"{v * 100:+.2f}%".rjust(12))
        out.append("  " + nombre.ljust(ancho) + "".join(celdas))
    return "\n".join(out)
