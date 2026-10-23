"""Gestion de riesgo: cuanto meter, cuando parar y si la cuenta aguanta.

Todo aqui es aritmetica, no prediccion. La pregunta que responde cada funcion
es "si mi acierto real es p, que pasa con mi plata", nunca "va a subir".
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd


# --------------------------------------------------------------------------
# Opciones binarias
# --------------------------------------------------------------------------
def equilibrio_binaria(pago: float) -> float:
    """Acierto minimo para quedar en cero. Pago 0.85 (85 %) -> 54.05 %.

    Ganar paga `pago` por cada unidad arriesgada; perder cuesta la unidad entera.
    E = p * pago - (1 - p) = 0  =>  p = 1 / (1 + pago)
    """
    if pago <= 0:
        raise ValueError("el pago debe ser positivo (0.85 = 85 %)")
    return 1.0 / (1.0 + pago)


def expectativa_binaria(p: float, pago: float) -> float:
    """Ganancia esperada por cada $1 arriesgado."""
    return p * pago - (1.0 - p)


def kelly_binaria(p: float, pago: float) -> float:
    """Fraccion de Kelly. <= 0 significa que no hay apuesta con valor esperado positivo."""
    return p - (1.0 - p) / pago


def monto_binaria(balance: float, p: float, pago: float,
                  riesgo_max_pct: float = 0.01, fraccion_kelly: float = 0.25) -> float:
    """Monto sugerido por operacion. Cero si la expectativa no es positiva.

    Usa un cuarto de Kelly y nunca mas de `riesgo_max_pct` del balance: Kelly
    completo con un p estimado de pocas operaciones quiebra cuentas.
    `p` deberia ser el limite inferior del intervalo de confianza del diario,
    no el acierto observado.
    """
    k = kelly_binaria(p, pago)
    if k <= 0:
        return 0.0
    return round(balance * min(riesgo_max_pct, k * fraccion_kelly), 2)


# --------------------------------------------------------------------------
# Forex / CFD en MT5
# --------------------------------------------------------------------------
@dataclass
class Lotes:
    lotes: float
    riesgo_dinero: float         # lo que se pierde si toca el stop, con ese tamano
    riesgo_objetivo: float       # balance * riesgo_pct
    aviso: str = ""


def lotes_forex(balance: float, riesgo_pct: float, distancia_stop: float,
                tick_size: float, tick_value: float,
                paso: float = 0.01, minimo: float = 0.01, maximo: float = 100.0,
                costo_precio: float = 0.0) -> Lotes:
    """Tamano de posicion para que tocar el stop cueste `riesgo_pct` del balance.

    distancia_stop y costo_precio en unidades de precio (EURUSD: 0.0020 = 20 pips).
    tick_size / tick_value salen de mt5.symbol_info (trade_tick_size,
    trade_tick_value): valor de un tick por 1 lote en la moneda de la cuenta.
    Se redondea hacia abajo: nunca arriesgar mas de lo pedido.
    """
    if distancia_stop <= 0 or tick_size <= 0 or tick_value <= 0:
        raise ValueError("stop, tick_size y tick_value deben ser positivos")
    objetivo = balance * riesgo_pct
    por_lote = (distancia_stop + costo_precio) / tick_size * tick_value
    crudo = objetivo / por_lote
    lotes = math.floor(crudo / paso + 1e-9) * paso
    lotes = min(round(lotes, 8), maximo)
    if lotes < minimo:
        return Lotes(0.0, 0.0, objetivo,
                     f"el lote minimo ({minimo}) arriesga {minimo * por_lote:.2f}, "
                     f"mas que tu limite de {objetivo:.2f}: stop muy amplio o cuenta muy chica")
    return Lotes(lotes, round(lotes * por_lote, 2), objetivo)


# --------------------------------------------------------------------------
# Rachas: lo que la cuenta tiene que aguantar
# --------------------------------------------------------------------------
def prob_racha_perdedora(p_acierto: float, n_ops: int, largo: int) -> float:
    """Probabilidad de ver al menos una racha de `largo` perdidas seguidas en n_ops.

    Programacion dinamica sobre el largo de la racha actual. Con 50 % de acierto,
    una racha de 8 en 300 operaciones pasa ~44 % de las veces.
    """
    if largo <= 0:
        return 1.0
    q = 1.0 - p_acierto
    # estado[i] = prob de llevar i perdidas seguidas sin haber llegado a `largo`
    estado = [1.0] + [0.0] * (largo - 1)
    for _ in range(n_ops):
        nuevo = [0.0] * largo
        nuevo[0] = sum(estado) * p_acierto
        for i in range(largo - 1):
            nuevo[i + 1] = estado[i] * q
        estado = nuevo
    return 1.0 - sum(estado)


# --------------------------------------------------------------------------
# Frenos: reglas que bloquean operar, fijadas antes de abrir el grafico
# --------------------------------------------------------------------------
@dataclass
class ReglasFreno:
    stop_diario_pct: float = 0.03       # perder 3 % del balance en el dia -> se acabo
    max_perdidas_seguidas: int = 3
    max_ops_dia: int = 10


@dataclass
class EstadoFreno:
    bloqueado: bool
    motivos: list[str] = field(default_factory=list)
    pnl_hoy: float = 0.0
    ops_hoy: int = 0
    perdidas_seguidas: int = 0


def evaluar_freno(diario: pd.DataFrame, balance: float, reglas: ReglasFreno,
                  hoy: pd.Timestamp | None = None) -> EstadoFreno:
    """Mira las operaciones de hoy en el diario y dice si hay que parar."""
    hoy = (hoy or pd.Timestamp.now()).normalize()
    if diario.empty:
        return EstadoFreno(False)
    d = diario[pd.to_datetime(diario["fecha"]).dt.normalize() == hoy]
    pnl = float(d["pnl"].sum()) if len(d) else 0.0

    seguidas = 0
    for r in reversed(d["resultado"].tolist()):
        if r == "pierde":
            seguidas += 1
        elif r == "gana":
            break

    motivos = []
    if pnl <= -balance * reglas.stop_diario_pct:
        motivos.append(f"stop diario: perdiste {-pnl:.2f} "
                       f"(limite {balance * reglas.stop_diario_pct:.2f})")
    if seguidas >= reglas.max_perdidas_seguidas:
        motivos.append(f"{seguidas} perdidas seguidas (limite {reglas.max_perdidas_seguidas})")
    if len(d) >= reglas.max_ops_dia:
        motivos.append(f"{len(d)} operaciones hoy (limite {reglas.max_ops_dia})")
    return EstadoFreno(bool(motivos), motivos, pnl, len(d), seguidas)
