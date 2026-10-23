"""Senales SUBE / BAJA para opciones binarias, sacadas del precio real de MT5.

Sirve para operar a mano en IQ Option (u otro broker) los mismos pares reales
que cotiza MT5: EURUSD, GBPUSD, XAUUSD... NO sirve para activos OTC, cuyo
precio lo genera el broker y no existe en ningun mercado.

Tres piezas:
  - reglas: senal +1 (SUBE), -1 (BAJA) o 0 al cierre de cada vela de 1 minuto,
    solo con velas ya cerradas.
  - backtest: para cada senal historica, compara el cierre de la vela de la
    senal con el cierre `n` velas despues. Acierto con IC 95 % contra el
    equilibrio del pago (54.05 % con 85 %).
  - registro en papel: en vivo, cada senal se anota sola con el precio de
    entrada y, al vencer, con el precio real. Asi se mide sin arriesgar plata.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import diario, riesgo


# --------------------------------------------------------------------------
# Reglas. Convencion: la senal en t usa solo velas cerradas hasta t.
# --------------------------------------------------------------------------
def _rsi(c: pd.Series, periodo: int) -> pd.Series:
    delta = c.diff()
    g = delta.clip(lower=0).ewm(alpha=1 / periodo, adjust=False).mean()
    p = (-delta.clip(upper=0)).ewm(alpha=1 / periodo, adjust=False).mean()
    rs = g / p.replace(0, np.nan)
    v = 100 - 100 / (1 + rs)
    v[: periodo + 1] = np.nan
    return v


def rsi_reversion(df: pd.DataFrame, periodo: int = 14, bajo: int = 30, alto: int = 70) -> pd.Series:
    """SUBE cuando el RSI vuelve a cruzar hacia arriba el nivel bajo; BAJA cuando
    cruza hacia abajo el alto. Es la logica de la mayoria de flechas 'COMPRA/VENDE'."""
    v = _rsi(df["close"], periodo)
    prev = v.shift(1)
    s = pd.Series(0, index=df.index, dtype=int)
    s[(prev < bajo) & (v >= bajo)] = 1
    s[(prev > alto) & (v <= alto)] = -1
    return s.rename(f"rsi:{periodo}:{bajo}:{alto}")


def cruce_medias(df: pd.DataFrame, rapida: int = 5, lenta: int = 20) -> pd.Series:
    """SUBE en el cruce de la media rapida sobre la lenta; BAJA en el cruce contrario."""
    c = df["close"]
    d = np.sign(c.rolling(rapida).mean() - c.rolling(lenta).mean())
    prev = d.shift(1)
    s = pd.Series(0, index=df.index, dtype=int)
    s[(prev <= 0) & (d > 0)] = 1
    s[(prev >= 0) & (d < 0)] = -1
    s[: lenta] = 0
    return s.rename(f"ma:{rapida}:{lenta}")


def momentum(df: pd.DataFrame, velas: int = 3) -> pd.Series:
    """SUBE tras `velas` cierres alcistas seguidos; BAJA tras `velas` bajistas.
    Solo dispara en la vela que completa la racha, no en las siguientes."""
    d = np.sign(df["close"].diff())
    arriba = (d > 0).astype(int).rolling(velas).sum() == velas
    abajo = (d < 0).astype(int).rolling(velas).sum() == velas
    s = pd.Series(0, index=df.index, dtype=int)
    s[arriba & ~arriba.shift(1, fill_value=False)] = 1
    s[abajo & ~abajo.shift(1, fill_value=False)] = -1
    return s.rename(f"mom:{velas}")


REGLAS = {"rsi": rsi_reversion, "ma": cruce_medias, "mom": momentum}


def resolver_regla(spec: str):
    """'rsi:14:30:70', 'ma:5:20', 'mom:3'."""
    partes = spec.split(":")
    if partes[0] not in REGLAS:
        raise ValueError(f"regla desconocida: {partes[0]}. Use {list(REGLAS)}")
    fn, params = REGLAS[partes[0]], [int(x) for x in partes[1:]]
    return (lambda d: fn(d, *params)), spec


# --------------------------------------------------------------------------
# Backtest por vencimiento
# --------------------------------------------------------------------------
def resultado(direccion: int, entrada: float, salida: float) -> str:
    """Como liquida una binaria: igual precio = empate (devuelven la inversion)."""
    if salida == entrada:
        return "empate"
    return "gana" if (salida > entrada) == (direccion > 0) else "pierde"


@dataclass
class Prueba:
    regla: str
    vence_min: int
    senales: int
    ganadas: int
    perdidas: int
    empates: int
    acierto: float
    ic_bajo: float
    ic_alto: float
    equilibrio: float
    expectativa: float     # por cada $1, con el acierto observado

    @property
    def tiene_ventaja(self) -> bool:
        return self.senales >= 30 and self.ic_bajo > self.equilibrio

    def resumen(self) -> str:
        if self.senales < 30:
            etiqueta = "MUESTRA CHICA"
        elif self.tiene_ventaja:
            etiqueta = "CON VENTAJA HISTORICA"
        elif self.ic_alto < self.equilibrio:
            etiqueta = "PIERDE EN EL HISTORICO"
        else:
            etiqueta = "SIN VENTAJA PROBADA"
        return (f"{etiqueta} | {self.senales} senales a {self.vence_min} min: acierto "
                f"{self.acierto:.1%} [IC {self.ic_bajo:.1%}, {self.ic_alto:.1%}] vs equilibrio "
                f"{self.equilibrio:.1%}, {self.expectativa * 10:+.2f} por cada $10")


def backtest(df: pd.DataFrame, senal: pd.Series, vence_velas: int, pago: float,
             nombre: str = "") -> Prueba:
    """Entrada al cierre de la vela de la senal, salida al cierre `vence_velas` despues.

    Es optimista en un punto: en vivo entras unos segundos tarde y a otro precio.
    Por eso el registro en papel en vivo pesa mas que este numero.
    """
    if vence_velas < 1:
        raise ValueError("el vencimiento en velas debe ser >= 1")
    c = df["close"].to_numpy()
    s = senal.to_numpy()
    g = p = e = 0
    for t in np.flatnonzero(s[: len(c) - vence_velas]):
        r = resultado(int(s[t]), c[t], c[t + vence_velas])
        g += r == "gana"
        p += r == "pierde"
        e += r == "empate"
    n = g + p
    bajo, alto = diario.wilson(g, n)
    acierto = g / n if n else float("nan")
    eq = riesgo.equilibrio_binaria(pago)
    exp = riesgo.expectativa_binaria(acierto, pago) if n else float("nan")
    return Prueba(nombre, vence_velas, n, g, p, e, acierto, bajo, alto, eq, exp)


# --------------------------------------------------------------------------
# En vivo: senales pendientes de vencer
# --------------------------------------------------------------------------
@dataclass
class Pendiente:
    simbolo: str
    regla: str
    direccion: int
    entrada: float
    vence: pd.Timestamp       # hora local de la maquina
    vela: pd.Timestamp

    @property
    def texto_direccion(self) -> str:
        return "SUBE" if self.direccion > 0 else "BAJA"


def vencidas(pendientes: list[Pendiente], ahora: pd.Timestamp) -> tuple[list, list]:
    """Separa las que ya vencieron de las que siguen abiertas."""
    listas = [x for x in pendientes if ahora >= x.vence]
    abiertas = [x for x in pendientes if ahora < x.vence]
    return listas, abiertas


def anotar_papel(ruta: str, pend: Pendiente, salida: float, pago: float,
                 retraso_seg: float) -> dict:
    r = resultado(pend.direccion, pend.entrada, salida)
    return diario.registrar(
        ruta, mercado="iqoption", simbolo=pend.simbolo, direccion=pend.texto_direccion.lower(),
        monto=1.0, resultado=r, pago=pago, senal=pend.regla,
        nota=f"papel | entrada {pend.entrada:g} salida {salida:g} | lectura +{retraso_seg:.1f}s",
    )


# --------------------------------------------------------------------------
# Datos de MT5 (import tardio: el paquete solo existe en Windows)
# --------------------------------------------------------------------------
def velas_m1(simbolo: str, n: int) -> pd.DataFrame:
    """Ultimas n velas de 1 minuto cerradas. Requiere el terminal ya conectado."""
    import MetaTrader5 as mt5
    if not mt5.symbol_select(simbolo, True):
        raise RuntimeError(f"simbolo no disponible: {simbolo}")
    crudo = mt5.copy_rates_from_pos(simbolo, mt5.TIMEFRAME_M1, 0, n + 1)
    if crudo is None or len(crudo) == 0:
        raise RuntimeError(f"sin velas M1 de {simbolo}: {mt5.last_error()}")
    df = pd.DataFrame(crudo)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return df.set_index("time").iloc[:-1][["open", "high", "low", "close"]]


def precio_actual(simbolo: str) -> float:
    """Precio medio (bid+ask)/2: las binarias liquidan cerca del medio, no del bid."""
    import MetaTrader5 as mt5
    t = mt5.symbol_info_tick(simbolo)
    if t is None:
        raise RuntimeError(f"sin cotizacion de {simbolo}: {mt5.last_error()}")
    return (t.bid + t.ask) / 2


def mercado_cerrado(ultima_vela: pd.Timestamp, hora_servidor: pd.Timestamp,
                    max_min: int = 3) -> bool:
    """Si la ultima vela M1 cerrada tiene mas de `max_min` minutos (en hora del
    broker), el par no esta cotizando: fin de semana o feriado. Ahi IQ Option
    solo ofrece OTC, y el bot no da senales."""
    return (hora_servidor - ultima_vela) > pd.Timedelta(minutes=max_min + 1)


def vence_en_velas(vence_seg: int) -> int | None:
    """Vencimientos multiplos de 1 minuto se pueden probar en velas M1; 30 s no."""
    return vence_seg // 60 if vence_seg >= 60 and vence_seg % 60 == 0 else None
