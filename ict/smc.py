"""Piezas de Smart Money / ICT, codificadas de forma mecánica y sin mirar el futuro.

Convenciones:
- Las velas vienen en hora del bróker (MetaQuotes-Demo): UTC+2 en invierno y
  UTC+3 en verano, con el cambio de hora EUROPEO. Nueva York queda a 7 h casi
  todo el año, pero a 6 h unas tres semanas de marzo y una de noviembre. Por eso
  se convierte con zonas horarias reales (verificado en `pruebas_ict.py` con la
  apertura de las 9:30 del USTEC).
- Una decisión tomada al cierre de la barra t solo usa información hasta t.
- Un swing de orden k en la barra i se conoce recién al cierre de i + k.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

AQUI = os.path.dirname(os.path.abspath(__file__))
ZONA_BROKER = "Europe/Athens"   # EET/EEST: mismo horario que el servidor


def a_nueva_york(indice: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return (indice.tz_localize(ZONA_BROKER, ambiguous="NaT", nonexistent="shift_forward")
            .tz_convert("America/New_York").tz_localize(None))

# Costo de ida y vuelta en unidades de precio: spread típico de un bróker retail
# más deslizamiento. La demo reporta spreads menores que los de una cuenta real.
COSTO = {
    "USTEC": 1.8,       # ~1.2 pt de spread + 0.6 de deslizamiento
    "US500": 0.6,
    "EURUSD": 0.00012,  # 1.0 pip + 0.2
    "GBPUSD": 0.00016,
    "XAUUSD": 0.35,
}


def _leer(simbolo: str, tf: str) -> pd.DataFrame:
    df = pd.read_csv(os.path.join(AQUI, "datos", f"{simbolo}_{tf}.csv"), parse_dates=["time"])
    df = df.set_index("time")
    ny = a_nueva_york(df.index)
    df = df[~ny.isna()]
    ny = ny[~ny.isna()]
    df["ny_min"] = ny.hour * 60 + ny.minute
    df["ny_dia"] = ny.normalize()
    return df


_DANADOS = {}


def dias_danados(simbolo: str) -> pd.DatetimeIndex:
    """Días en que la demo dejó el precio congelado.

    En USTEC y US500 el feed de la demo se quedó casi quieto de oct-2024 a ene-2025:
    velas de 5 minutos de 0,25 puntos en plena apertura de NY. Un día es dañado si
    la mediana del rango relativo de sus velas M5 es menor al 15 % de la mediana
    de toda la serie (en divisas y oro el 1 % más tranquilo está en ~45 %).
    """
    if simbolo not in _DANADOS:
        m5 = _leer(simbolo, "M5")
        d = ((m5["high"] - m5["low"]) / m5["close"]).groupby(m5["ny_dia"]).median()
        _DANADOS[simbolo] = d.index[d < 0.15 * d.median()]
    return _DANADOS[simbolo]


def cargar(simbolo: str, tf: str) -> pd.DataFrame:
    df = _leer(simbolo, tf)
    return df[~df["ny_dia"].isin(dias_danados(simbolo))]


def swings(h: np.ndarray, l: np.ndarray, k: int):
    """Swing alto en i si h[i] es el máximo estricto de la izquierda y >= la derecha.

    Devuelve (idx_alto, idx_bajo): índices de los pivotes. Cada uno se confirma
    en i + k, nunca antes.
    """
    n = len(h)
    alto, bajo = [], []
    for i in range(k, n - k):
        izq_h, der_h = h[i - k:i], h[i + 1:i + k + 1]
        if h[i] > izq_h.max() and h[i] >= der_h.max():
            alto.append(i)
        izq_l, der_l = l[i - k:i], l[i + 1:i + k + 1]
        if l[i] < izq_l.min() and l[i] <= der_l.min():
            bajo.append(i)
    return np.array(alto, dtype=int), np.array(bajo, dtype=int)


_CACHE = {}


def _clave(nombre, a, *extra):
    """Las mismas velas dan siempre el mismo resultado: se calcula una vez por proceso."""
    return (nombre, len(a), float(a[0]), float(a[-1]), float(a.sum())) + extra


def barridos_de_swing(h, l, k, vida=288):
    clave = _clave("sw", h, float(l.sum()), k, vida)
    if clave not in _CACHE:
        _CACHE[clave] = _barridos_de_swing(h, l, k, vida)
    return _CACHE[clave]


def _barridos_de_swing(h, l, k, vida=288):
    """Marca las barras que toman liquidez de un swing previo aún intacto.

    barrido_alto[t] = precio del swing alto tomado en t (NaN si ninguno).
    Un swing solo está disponible desde i + k + 1 y se descarta tras `vida` barras.
    """
    n = len(h)
    ia, ib = swings(h, l, k)
    b_alto = np.full(n, np.nan)
    b_bajo = np.full(n, np.nan)
    act_a, act_b = [], []          # (precio, índice)
    pa = pb = 0
    for t in range(n):
        while pa < len(ia) and ia[pa] + k < t:
            act_a.append((h[ia[pa]], ia[pa])); pa += 1
        while pb < len(ib) and ib[pb] + k < t:
            act_b.append((l[ib[pb]], ib[pb])); pb += 1
        act_a = [x for x in act_a if t - x[1] <= vida]
        act_b = [x for x in act_b if t - x[1] <= vida]
        tomados = [x for x in act_a if h[t] > x[0]]
        if tomados:
            b_alto[t] = max(x[0] for x in tomados)
            act_a = [x for x in act_a if h[t] <= x[0]]
        tomados = [x for x in act_b if l[t] < x[0]]
        if tomados:
            b_bajo[t] = min(x[0] for x in tomados)
            act_b = [x for x in act_b if l[t] >= x[0]]
    return b_alto, b_bajo, ia, ib


def niveles_sesion(df: pd.DataFrame):
    clave = _clave("ses", df["high"].to_numpy(), float(df["low"].sum()))
    if clave not in _CACHE:
        _CACHE[clave] = _niveles_sesion(df)
    return _CACHE[clave]


def _niveles_sesion(df: pd.DataFrame):
    """Liquidez de sesión que ICT marca cada día (hora de NY):

    Asia 20:00-24:00 del día previo, Londres 02:00-05:00, máximo y mínimo del día
    anterior. Cada nivel se vuelve visible cuando su sesión cerró.
    Devuelve barrido_alto / barrido_bajo por barra (primera toma del día).
    """
    h, l = df["high"].to_numpy(), df["low"].to_numpy()
    m = df["ny_min"].to_numpy()
    dias = df["ny_dia"].to_numpy()
    n = len(df)
    b_alto = np.full(n, np.nan)
    b_bajo = np.full(n, np.nan)

    limites = np.flatnonzero(np.r_[True, dias[1:] != dias[:-1], True])
    previo = None       # (ini, fin) del día anterior
    for a, b in zip(limites[:-1], limites[1:]):
        niveles_a, niveles_b = [], []   # (precio, visible_desde_idx)
        if previo is not None:
            pa, pb_ = previo
            niveles_a.append((h[pa:pb_].max(), a))
            niveles_b.append((l[pa:pb_].min(), a))
            asia = np.arange(pa, pb_)[m[pa:pb_] >= 20 * 60]
            if len(asia):
                niveles_a.append((h[asia].max(), a))
                niveles_b.append((l[asia].min(), a))
        lon = np.arange(a, b)[(m[a:b] >= 120) & (m[a:b] < 300)]
        if len(lon):
            niveles_a.append((h[lon].max(), lon[-1] + 1))
            niveles_b.append((l[lon].min(), lon[-1] + 1))
        vivos_a, vivos_b = list(niveles_a), list(niveles_b)
        for t in range(a, b):
            tom = [p for p, d in vivos_a if d <= t and h[t] > p]
            if tom:
                b_alto[t] = max(tom)
                vivos_a = [(p, d) for p, d in vivos_a if not (d <= t and h[t] > p)]
            tom = [p for p, d in vivos_b if d <= t and l[t] < p]
            if tom:
                b_bajo[t] = min(tom)
                vivos_b = [(p, d) for p, d in vivos_b if not (d <= t and l[t] < p)]
        previo = (a, b)
    return b_alto, b_bajo


def medio_dia_previo(df: pd.DataFrame) -> np.ndarray:
    """50 % del rango del día anterior de NY: la línea premium/discount de ICT."""
    g = df.groupby("ny_dia").agg(alto=("high", "max"), bajo=("low", "min"))
    medio = ((g["alto"] + g["bajo"]) / 2).shift(1)
    return df["ny_dia"].map(medio).to_numpy()


def ultimo_swing(indices: np.ndarray, k: int, t: int):
    """Último pivote confirmado al cierre de t (índice del pivote) o None."""
    pos = np.searchsorted(indices, t - k, side="right") - 1
    return int(indices[pos]) if pos >= 0 else None


def swing_objetivo(indices, precios, k, t, entrada, direccion, distancia_min):
    """Liquidez opuesta más cercana (confirmada al cierre de t) a >= distancia_min."""
    visibles = indices[:np.searchsorted(indices, t - k, side="right")]
    if not len(visibles):
        return None
    p = precios[visibles[-200:]]
    if direccion > 0:
        cand = p[p >= entrada + distancia_min]
        return float(cand.min()) if len(cand) else None
    cand = p[p <= entrada - distancia_min]
    return float(cand.max()) if len(cand) else None


# ─────────────────────────────────────────────────────────── simulador de operaciones
@dataclass
class Orden:
    t_senal: int            # barra al cierre de la cual se decide
    direccion: int          # +1 largo, -1 corto
    entrada: float          # precio límite, o NaN = a mercado en la apertura de t_senal+1
    sl: float
    tp: float
    expira: int             # última barra en la que puede llenarse
    salida_tiempo: int      # barra a cuyo cierre se cierra por tiempo
    tp1: float = np.nan     # parcial del 50 % y stop a break-even (CRT)
    etiqueta: str = ""


@dataclass
class Operacion:
    t_entrada: int
    t_salida: int
    direccion: int
    entrada: float
    sl: float
    tp: float
    r: float                # resultado neto en múltiplos del riesgo
    motivo: str
    extra: dict = field(default_factory=dict)


def simular(o, h, l, c, orden: Orden, costo: float, riesgo_min_costos: float = 3.0):
    """Recorre las barras siguientes a la señal. Conservador cuando el OHLC es ambiguo:

    - si una barra toca stop y objetivo, cuenta el stop;
    - en la barra en que se llena la límite solo se revisa el stop;
    - si el precio llega al objetivo antes de llenar la orden, se cancela;
    - un hueco que salta el stop sale a la apertura (peor que el stop).
    """
    d = orden.direccion
    n = len(c)
    ini = orden.t_senal + 1
    if ini >= n:
        return None

    # 1. llenado
    if np.isnan(orden.entrada):
        te, px = ini, o[ini]
    else:
        te = None
        for t in range(ini, min(orden.expira, n - 1) + 1):
            if d > 0:
                if h[t] >= orden.tp and l[t] > orden.entrada:
                    return None
                if l[t] <= orden.entrada:
                    te, px = t, min(o[t], orden.entrada); break
            else:
                if l[t] <= orden.tp and h[t] < orden.entrada:
                    return None
                if h[t] >= orden.entrada:
                    te, px = t, max(o[t], orden.entrada); break
        if te is None:
            return None

    riesgo = (px - orden.sl) * d
    if riesgo <= 0 or riesgo < riesgo_min_costos * costo:
        return None
    if (orden.tp - px) * d <= 0:
        return None

    parcial = not np.isnan(orden.tp1) and (orden.tp1 - px) * d > 0
    sl, mitad_cobrada = orden.sl, None

    def cerrar(t, precio, motivo):
        bruto = (precio - px) * d
        if mitad_cobrada is not None:
            bruto = 0.5 * mitad_cobrada + 0.5 * bruto
        return Operacion(te, t, d, px, orden.sl, orden.tp, (bruto - costo) / riesgo, motivo)

    fin = min(orden.salida_tiempo, n - 1)
    # barra de llenado: solo stop
    if (d > 0 and l[te] <= sl) or (d < 0 and h[te] >= sl):
        return cerrar(te, sl, "stop")
    for t in range(te + 1, fin + 1):
        # huecos en la apertura
        if (o[t] - sl) * d <= 0:
            return cerrar(t, o[t], "stop (hueco)")
        toca_sl = l[t] <= sl if d > 0 else h[t] >= sl
        toca_tp = h[t] >= orden.tp if d > 0 else l[t] <= orden.tp
        toca_tp1 = parcial and mitad_cobrada is None and (
            h[t] >= orden.tp1 if d > 0 else l[t] <= orden.tp1)
        if toca_sl:
            return cerrar(t, sl, "break-even" if mitad_cobrada is not None else "stop")
        if toca_tp1:
            mitad_cobrada = (orden.tp1 - px) * d
            sl = px
            if toca_tp:   # llegó a los dos objetivos en la misma barra
                return cerrar(t, orden.tp, "objetivo")
            continue
        if toca_tp:
            return cerrar(t, orden.tp, "objetivo")
    return cerrar(fin, c[fin], "tiempo")
