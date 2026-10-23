"""Diario de operaciones: solo agrega filas, nunca reescribe lo anotado.

Es la pieza mas importante del asesor. Sin un registro honesto de lo que pasa
en vivo, cualquier estrategia "funciona" en la cabeza.
"""
from __future__ import annotations

import csv
import math
import os
from dataclasses import dataclass

import pandas as pd

from . import riesgo

COLUMNAS = ["fecha", "mercado", "simbolo", "direccion", "monto", "resultado",
            "pnl", "pago", "senal", "nota"]
RESULTADOS = {"gana", "pierde", "empate"}
MERCADOS = {"mt5", "iqoption", "otro"}


def registrar(ruta: str, *, mercado: str, simbolo: str, direccion: str, monto: float,
              resultado: str, pnl: float | None = None, pago: float | None = None,
              senal: str = "", nota: str = "", fecha: pd.Timestamp | None = None) -> dict:
    """Anota una operacion cerrada.

    En binarias basta con `pago` (0.85) y `resultado`: el pnl se calcula solo
    (gana -> +monto*pago, pierde -> -monto, empate -> 0). En MT5 se pasa `pnl`.
    """
    if resultado not in RESULTADOS:
        raise ValueError(f"resultado debe ser uno de {sorted(RESULTADOS)}")
    if mercado not in MERCADOS:
        raise ValueError(f"mercado debe ser uno de {sorted(MERCADOS)}")
    if monto <= 0:
        raise ValueError("el monto debe ser positivo")
    if pnl is None:
        if pago is None:
            raise ValueError("falta pnl (MT5) o pago (binarias)")
        pnl = {"gana": monto * pago, "pierde": -monto, "empate": 0.0}[resultado]

    fila = {
        "fecha": (fecha or pd.Timestamp.now()).strftime("%Y-%m-%d %H:%M:%S"),
        "mercado": mercado, "simbolo": simbolo.upper(), "direccion": direccion.lower(),
        "monto": round(float(monto), 2), "resultado": resultado,
        "pnl": round(float(pnl), 2), "pago": "" if pago is None else pago,
        "senal": senal, "nota": nota,
    }
    nuevo = not os.path.exists(ruta)
    os.makedirs(os.path.dirname(os.path.abspath(ruta)), exist_ok=True)
    with open(ruta, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS)
        if nuevo:
            w.writeheader()
        w.writerow(fila)
    return fila


def cargar(ruta: str) -> pd.DataFrame:
    if not os.path.exists(ruta):
        return pd.DataFrame(columns=COLUMNAS)
    df = pd.read_csv(ruta, encoding="utf-8")
    df["fecha"] = pd.to_datetime(df["fecha"])
    return df


def wilson(aciertos: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Intervalo de confianza del acierto. Con pocas operaciones es enorme."""
    if n == 0:
        return (0.0, 1.0)
    p = aciertos / n
    centro = (p + z * z / (2 * n)) / (1 + z * z / n)
    margen = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, centro - margen), min(1.0, centro + margen))


@dataclass
class Estadisticas:
    n: int
    ganadas: int
    perdidas: int
    acierto: float
    ic_bajo: float
    ic_alto: float
    pnl_total: float
    expectativa: float           # pnl medio por operacion
    max_drawdown: float          # en dinero, sobre el pnl acumulado
    peor_racha: int
    equilibrio: float | None     # solo binarias con pago uniforme
    veredicto: str


def estadisticas(df: pd.DataFrame, filtro_mercado: str | None = None,
                 filtro_senal: str | None = None) -> Estadisticas:
    d = df
    if filtro_mercado:
        d = d[d["mercado"] == filtro_mercado]
    if filtro_senal:
        d = d[d["senal"].fillna("") == filtro_senal]
    d = d[d["resultado"] != "empate"]

    n = len(d)
    g = int((d["resultado"] == "gana").sum())
    p = g / n if n else float("nan")
    bajo, alto = wilson(g, n)
    pnl = d["pnl"].astype(float)
    acumulado = pnl.cumsum()
    dd = float((acumulado - acumulado.cummax().clip(lower=0)).min()) if n else 0.0

    racha = peor = 0
    for r in d["resultado"]:
        racha = racha + 1 if r == "pierde" else 0
        peor = max(peor, racha)

    pagos = pd.to_numeric(d.get("pago", pd.Series(dtype=float)), errors="coerce").dropna()
    equilibrio = riesgo.equilibrio_binaria(float(pagos.mean())) if len(pagos) == n and n else None

    if n < 30:
        veredicto = f"muestra insuficiente ({n} ops): no se puede concluir nada todavia"
    elif equilibrio is not None:
        if bajo > equilibrio:
            veredicto = (f"ventaja probable: el peor caso del IC ({bajo:.1%}) supera "
                         f"el equilibrio ({equilibrio:.1%})")
        elif alto < equilibrio:
            veredicto = (f"pierde dinero: incluso el mejor caso del IC ({alto:.1%}) queda "
                         f"bajo el equilibrio ({equilibrio:.1%})")
        else:
            veredicto = (f"sin evidencia de ventaja: el IC [{bajo:.1%}, {alto:.1%}] "
                         f"incluye el equilibrio ({equilibrio:.1%})")
    else:
        t = pnl.mean() / pnl.std() * math.sqrt(n) if pnl.std() > 0 else 0.0
        veredicto = (f"t = {t:.2f} sobre el pnl por operacion: "
                     + ("ventaja probable" if t > 2 else "sin evidencia de ventaja"))

    return Estadisticas(n, g, n - g, p, bajo, alto, float(pnl.sum()),
                        float(pnl.mean()) if n else 0.0, dd, peor, equilibrio, veredicto)
