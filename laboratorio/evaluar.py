"""Motor y veredicto del laboratorio, con el proceso de los profesionales:

- Riesgo normalizado (Carver): cada unidad de posicion arriesga una desviacion
  diaria del mercado, asi todos los mercados pesan igual.
- Costos: un spread completo por cada unidad que cambia la posicion.
- Dentro / fuera de muestra (Davey): 70 % mas viejo / 30 % mas reciente, y las
  reglas del veredicto se fijaron antes de ver resultados.
- Alarmas de Radge: acierto > 75 %, profit factor > 3, < 100 operaciones,
  o que gane en un solo mercado.
- Monte Carlo (Davey): barajar anos de la cartera para ver drawdowns posibles.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from laboratorio.estrategias import vol_precio

CORTE = 0.70
DIAS = 256
VOL_OBJETIVO = 0.15          # la cartera se lleva a 15 % de volatilidad anual para medir drawdowns


def retornos(df: pd.DataFrame, pos: pd.Series) -> pd.Series:
    """Retorno diario en unidades de riesgo, neto de spread. Sin mirar el futuro:
    la posicion decidida al cierre de t gana o pierde el movimiento de t+1."""
    v = vol_precio(df).shift(1)
    p = pos.shift(1).fillna(0)
    bruto = p * df["close"].diff() / v
    costo = p.diff().abs().fillna(0) * df["spread_precio"].replace(0, np.nan).fillna(df["spread_precio"].median()) / v
    return (bruto - costo).replace([np.inf, -np.inf], np.nan).dropna()


def operaciones(df: pd.DataFrame, pos: pd.Series) -> pd.Series:
    """R de cada operacion (tramo con el mismo signo de posicion), en unidades de riesgo."""
    r = retornos(df, pos)
    signo = np.sign(pos.shift(1).reindex(r.index).fillna(0))
    tramo = (signo != signo.shift()).cumsum()
    return r[signo != 0].groupby(tramo[signo != 0]).sum()


def sharpe(r: pd.Series) -> float:
    return float(r.mean() / r.std() * np.sqrt(DIAS)) if len(r) > 20 and r.std() > 0 else np.nan


def max_dd(r: pd.Series) -> float:
    eq = (1 + r).cumprod()
    return float((eq / eq.cummax() - 1).min())


def montecarlo(r: pd.Series, anos: int = 1, n: int = 5000, semilla: int = 1) -> dict:
    """Bloques de 20 dias barajados: prob. de perder en un ano y de caer 20 % o mas."""
    rng = np.random.default_rng(semilla)
    x = r.to_numpy()
    largo, bloque = DIAS * anos, 20
    inicios = rng.integers(0, len(x) - bloque, (n, largo // bloque))
    sim = x[(inicios[..., None] + np.arange(bloque)).reshape(n, -1)]
    eq = np.cumprod(1 + sim, axis=1)
    dd = (eq / np.maximum.accumulate(eq, axis=1) - 1).min(axis=1)
    return {"prob_perder_1_ano": float((eq[:, -1] < 1).mean()), "prob_dd_20": float((dd <= -0.20).mean()),
            "dd_mediano": float(np.median(dd))}


def evaluar(datos: dict[str, pd.DataFrame], estrategias: dict) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Devuelve (tabla por mercado, tabla por estrategia, retornos de cartera por estrategia)."""
    filas, carteras = [], {}
    for nombre, (fn, autor, tipo) in estrategias.items():
        rs = {}
        for sim, df in datos.items():
            pos = fn(df)
            r = retornos(df, pos)
            corte = r.index[int(len(r) * CORTE)]
            ops = operaciones(df, pos)
            ops_fin = ops.index  # numero de tramo; se usa solo para contar
            ganado, perdido = ops[ops > 0].sum(), -ops[ops < 0].sum()
            filas.append({"estrategia": nombre, "mercado": sim, "desde": r.index[0].date(),
                          "sharpe_dentro": sharpe(r[r.index < corte]), "sharpe_fuera": sharpe(r[r.index >= corte]),
                          "operaciones": len(ops_fin), "acierto": float((ops > 0).mean()) if len(ops) else np.nan,
                          "profit_factor": float(ganado / perdido) if perdido > 0 else np.nan,
                          "pos_hoy": float(pos.iloc[-1]), "corte": corte.date()})
            rs[sim] = r
        cartera = pd.DataFrame(rs).fillna(0).mean(axis=1)
        cartera = cartera[cartera.index >= pd.DataFrame(rs).dropna(thresh=3).index.min()]
        carteras[nombre] = (cartera, autor, tipo)
    por_mercado = pd.DataFrame(filas)

    resumen = []
    for nombre, (cart, autor, tipo) in carteras.items():
        m = por_mercado[por_mercado["estrategia"] == nombre]
        corte = cart.index[int(len(cart) * CORTE)]
        escala = VOL_OBJETIVO / (cart[cart.index < corte].std() * np.sqrt(DIAS))   # escala fijada dentro de muestra
        r = cart * escala
        dentro, fuera = r[r.index < corte], r[r.index >= corte]
        mc = montecarlo(r)
        alarmas = []
        if (m["acierto"] > 0.75).any():
            alarmas.append("acierto > 75 %")
        if (m["profit_factor"] > 3).any():
            alarmas.append("profit factor > 3")
        if m["operaciones"].sum() < 100:
            alarmas.append("menos de 100 operaciones")
        positivos = float((m["sharpe_fuera"] > 0).mean())
        if positivos <= 1 / len(m):
            alarmas.append("gana en un solo mercado")
        s_in, s_out = sharpe(dentro), sharpe(fuera)
        # Reglas fijadas antes de mirar resultados
        if tipo == "referencia":
            veredicto = "REFERENCIA"
        elif s_in > 0.3 and s_out > 0.3 and positivos >= 0.6 and not alarmas:
            veredicto = "APRUEBA: a papel"
        elif s_out > 0 and s_in > 0:
            veredicto = "EN DUDA"
        else:
            veredicto = "DESCARTA"
        resumen.append({"estrategia": nombre, "autor": autor, "tipo": tipo, "desde": cart.index[0].date(),
                        "corte": corte.date(), "sharpe_dentro": s_in, "sharpe_fuera": s_out,
                        "retorno_anual_fuera": float(fuera.mean() * DIAS), "max_dd": max_dd(r),
                        "mercados_positivos_fuera": positivos, "operaciones": int(m["operaciones"].sum()),
                        "acierto_medio": float(m["acierto"].mean()), **mc,
                        "alarmas": "; ".join(alarmas) or "ninguna", "veredicto": veredicto})
        carteras[nombre] = r
    return por_mercado, pd.DataFrame(resumen), carteras
