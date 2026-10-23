"""Senales en vivo, siempre acompanadas de su evidencia.

Una alerta sin el historial de la regla que la genera es una flecha de colores.
Aqui cada senal sale con lo que esa misma regla hizo en el historico reciente,
despues de costos y con ejecucion en la vela siguiente (el mismo motor del
backtester). Si la regla no tiene ventaja, la alerta lo dice en la primera linea.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

import estrategias
import metricas
import motor

T_MINIMO = 2.0


@dataclass
class Evidencia:
    retorno: float
    retorno_bh: float
    sharpe: float
    max_drawdown: float
    operaciones: int
    t: float
    velas: int

    @property
    def tiene_ventaja(self) -> bool:
        return self.t > T_MINIMO and self.retorno > 0 and self.retorno > self.retorno_bh

    def resumen(self) -> str:
        etiqueta = "CON VENTAJA HISTORICA" if self.tiene_ventaja else "SIN VENTAJA PROBADA"
        return (f"{etiqueta} | {self.velas} velas: {self.retorno:+.2%} neto vs "
                f"{self.retorno_bh:+.2%} comprar y mantener, Sharpe {self.sharpe:.2f}, "
                f"max DD {self.max_drawdown:.2%}, {self.operaciones} ops, t = {self.t:.2f}")


@dataclass
class Senal:
    simbolo: str
    timeframe: str
    estrategia: str
    actual: float          # 1 = largo, 0 = fuera
    anterior: float
    precio: float
    vela: pd.Timestamp     # hora (del broker) de la ultima vela cerrada
    evidencia: Evidencia

    @property
    def cambio(self) -> bool:
        return self.actual != self.anterior

    @property
    def accion(self) -> str:
        if not self.cambio:
            return "mantener largo" if self.actual == 1 else "seguir fuera"
        return "ENTRAR LARGO" if self.actual == 1 else "SALIR"

    def texto(self) -> str:
        return (f"[{self.simbolo} {self.timeframe}] {self.estrategia}: {self.accion} "
                f"@ {self.precio:g} (vela {self.vela:%Y-%m-%d %H:%M}, se ejecutaria en la "
                f"siguiente)\n  {self.evidencia.resumen()}")


def evidencia(df: pd.DataFrame, senal: pd.Series, costo: float, timeframe: str) -> Evidencia:
    r = motor.correr(df, senal, costo)
    m = metricas.resumen(r.equity, r.retornos, timeframe)
    ret = r.retornos
    desv = float(ret.std())
    t = float(ret.mean() / desv * math.sqrt(len(ret))) if desv > metricas.TOL_VOL else 0.0
    sharpe = m["sharpe"] if not math.isnan(m["sharpe"]) else 0.0
    return Evidencia(m["retorno_total"], float(r.equity_bh.iloc[-1] - 1), sharpe,
                     m["max_drawdown"], r.operaciones, t, len(ret))


def evaluar(df: pd.DataFrame, simbolo: str, timeframe: str, nombre: str,
            fn, costo: float) -> Senal:
    """Senal de la ultima vela cerrada. `df` no debe incluir la vela en formacion."""
    s = fn(df)
    validas = s.dropna()
    if len(validas) < 2:
        raise ValueError(f"{nombre}: muy pocas velas para calcular la senal")
    return Senal(simbolo, timeframe, nombre, float(validas.iloc[-1]), float(validas.iloc[-2]),
                 float(df["close"].iloc[-1]), validas.index[-1],
                 evidencia(df, s, costo, timeframe))


def resolver_estrategia(spec: str):
    """'ma:20:50' -> cruce de medias 20/50; 'rsi:14:30:70'; 'bh'."""
    partes = spec.split(":")
    clave, params = partes[0], [int(x) for x in partes[1:]]
    if clave not in estrategias.CATALOGO:
        raise ValueError(f"estrategia desconocida: {clave}. Use {list(estrategias.CATALOGO)}")
    fn = estrategias.CATALOGO[clave]
    return (lambda d: fn(d, *params)), spec


def velas_mt5(simbolo: str, timeframe: str, n: int) -> tuple[pd.DataFrame, float]:
    """Velas cerradas y costo por operacion desde el terminal. Import tardio:
    el paquete MetaTrader5 solo existe en Windows y las pruebas no lo necesitan."""
    import datos
    datos.conectar()
    try:
        df = datos.velas(simbolo, timeframe, n)
        punto = datos.punto(simbolo)
    finally:
        datos.desconectar()
    return df, punto
