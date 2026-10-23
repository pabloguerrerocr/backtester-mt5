"""ICC de Trades by Sci (Indicacion, Correccion, Continuacion) como reglas fijas.

Reglas, tal como las explica en el Day Trading Crash Course #1-#6 y el Trading
Course 003 (transcripciones en aprender-trading/sci/texto):

- Swing alto/bajo: pivote fractal con `k` velas a cada lado. Se conoce `k`
  velas despues (sin mirar el futuro).
- Indicacion (marco mayor): un cierre por encima del ultimo swing alto pone el
  marco en alcista; un cierre por debajo del ultimo swing bajo, en bajista.
- Correccion (marco menor): el marco menor rompe en contra del mayor.
- Continuacion = entrada: el marco menor vuelve a romper a favor del mayor
  despues de esa correccion. Entrada a la apertura de la vela siguiente, con
  spread.
- Stop: detras del ultimo swing del marco menor (el higher low para compras,
  el lower high para ventas), como dice en el Crash Course #5.
- Objetivo: R fijo (el reporta 1:4 a 1:7), o salida por tiempo.

Mismo protocolo que setups/estudio.py: 70 % mas viejo dentro de muestra,
30 % mas reciente fuera de muestra, y se exige que gane en los dos.

    python -W ignore -m setups.icc
"""
from __future__ import annotations

import itertools
import sys

import numpy as np
import pandas as pd

from setups.estudio import CORTE, atr, metricas, velas

SIMBOLOS = ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "USTEC", "US30", "US500"]
PARES = {("H4", "H1"): 30_000, ("H1", "M15"): 120_000}   # (marco mayor, marco de entrada): velas del menor
KS = [3, 5]                     # velas a cada lado del pivote
RS = [2.0, 3.0, 4.0]
MAX_VELAS = {"H1": 120, "M15": 192}   # 5 dias en H1, 2 dias en M15
SESIONES = {"todas": None, "nueva_york": (12, 17)}   # hora UTC de la entrada


# --------------------------------------------------------------------------
# Estructura
# --------------------------------------------------------------------------
def estructura(df: pd.DataFrame, k: int) -> pd.DataFrame:
    """Ultimo swing alto/bajo confirmado y estado de tendencia (+1/-1/0) por vela."""
    h, l, c = (df[x].to_numpy() for x in ("high", "low", "close"))
    n = len(c)
    sw_h = np.full(n, np.nan)
    sw_l = np.full(n, np.nan)
    tend = np.zeros(n, dtype=int)
    ult_h = ult_l = np.nan
    estado = 0
    for i in range(n):
        p = i - k                                   # pivote que se confirma en esta vela
        if p - k >= 0:
            ventana_h, ventana_l = h[p - k:i + 1], l[p - k:i + 1]
            if h[p] == ventana_h.max():
                ult_h = h[p]
            if l[p] == ventana_l.min():
                ult_l = l[p]
        if np.isfinite(ult_h) and c[i] > ult_h:
            estado = 1
        elif np.isfinite(ult_l) and c[i] < ult_l:
            estado = -1
        sw_h[i], sw_l[i], tend[i] = ult_h, ult_l, estado
    return pd.DataFrame({"sw_h": sw_h, "sw_l": sw_l, "tend": tend}, index=df.index)


def senales_icc(mayor: pd.DataFrame, menor: pd.DataFrame, k: int, tf_mayor: str) -> pd.DataFrame:
    """Senal +1/-1 en el marco menor y el stop estructural de cada una."""
    em = estructura(mayor, k)
    # la vela mayor solo se conoce al cerrar: se indexa por su hora de cierre
    em.index = mayor.index + pd.Timedelta(hours=int(tf_mayor[1:]))
    sesgo = em["tend"].reindex(menor.index, method="ffill").fillna(0).astype(int).to_numpy()

    es = estructura(menor, k)
    t_men = es["tend"].to_numpy()
    sw_h, sw_l = es["sw_h"].to_numpy(), es["sw_l"].to_numpy()
    n = len(menor)
    senal, stop = np.zeros(n, dtype=int), np.full(n, np.nan)
    hubo_correccion = False
    for i in range(1, n):
        if sesgo[i] != sesgo[i - 1]:
            hubo_correccion = False                 # nueva indicacion en el marco mayor
        if sesgo[i] != 0 and t_men[i] == -sesgo[i]:
            hubo_correccion = True                  # el menor rompe en contra: correccion
        giro = t_men[i] == sesgo[i] and t_men[i - 1] == -sesgo[i]
        if sesgo[i] != 0 and hubo_correccion and giro:
            senal[i] = sesgo[i]
            stop[i] = sw_l[i] if sesgo[i] > 0 else sw_h[i]
            hubo_correccion = False
    return pd.DataFrame({"senal": senal, "stop": stop}, index=menor.index)


def simular(df: pd.DataFrame, sen: pd.DataFrame, r_obj: float, max_velas: int, a: pd.Series) -> pd.DataFrame:
    o, h, l, c = (df[x].to_numpy() for x in ("open", "high", "low", "close"))
    sp, av = df["spread_precio"].to_numpy(), a.to_numpy()
    s, st = sen["senal"].to_numpy(), sen["stop"].to_numpy()
    n = len(c)
    filas, libre = [], 0
    for t in np.flatnonzero(s):
        if t < libre or t + 1 >= n or not np.isfinite(st[t]):
            continue
        d = int(s[t])
        ent = o[t + 1] + d * sp[t + 1]
        riesgo = d * (ent - st[t])
        if riesgo < 0.25 * av[t]:                   # stop ya cruzado o ridiculamente pegado
            continue
        obj = ent + d * r_obj * riesgo
        fin = min(t + 1 + max_velas, n)
        r, salida = None, fin - 1
        for j in range(t + 1, fin):
            if (l[j] <= st[t]) if d > 0 else (h[j] >= st[t]):
                r, salida = -1.0, j
                break
            if (h[j] >= obj) if d > 0 else (l[j] <= obj):
                r, salida = r_obj, j
                break
        if r is None:
            r = d * (c[salida] - ent) / riesgo
        filas.append((df.index[t], d, r))
        libre = salida + 1
    return pd.DataFrame(filas, columns=["senal", "dir", "r"])


def estudio() -> pd.DataFrame:
    filas = []
    for sim, ((tf_may, tf_men), n) in itertools.product(SIMBOLOS, PARES.items()):
        try:
            menor = velas(sim, tf_men, n)
            mayor = velas(sim, tf_may, n // 4 + 500)
        except RuntimeError as e:
            print(e, file=sys.stderr)
            continue
        mayor = mayor[mayor.index >= menor.index[0] - pd.Timedelta(days=60)]
        a = atr(menor)
        corte = menor.index[int(len(menor) * CORTE)]
        print(f"{sim} {tf_may}->{tf_men}: {menor.index[0]:%Y-%m-%d} a {menor.index[-1]:%Y-%m-%d}, "
              f"corte {corte:%Y-%m-%d}", file=sys.stderr)
        for k in KS:
            sen = senales_icc(mayor, menor, k, tf_may)
            for (nom_ses, ses), r_obj in itertools.product(SESIONES.items(), RS):
                s = sen.copy()
                if ses:
                    s.loc[~menor["hora_utc"].between(ses[0], ses[1] - 1), "senal"] = 0
                ops = simular(menor, s, r_obj, MAX_VELAS[tf_men], a)
                dentro, fuera = metricas(ops[ops["senal"] < corte]), metricas(ops[ops["senal"] >= corte])
                filas.append({"simbolo": sim, "marcos": f"{tf_may}->{tf_men}", "k": k, "sesion": nom_ses,
                              "R": r_obj, **{f"in_{x}": v for x, v in dentro.items()},
                              **{f"out_{x}": v for x, v in fuera.items()}})
    return pd.DataFrame(filas)


if __name__ == "__main__":
    import MetaTrader5 as mt5
    if not mt5.initialize(timeout=20000):
        sys.exit(f"MT5 no responde: {mt5.last_error()}")
    try:
        tabla = estudio()
    finally:
        mt5.shutdown()
    tabla.to_csv("setups/resultados_icc.csv", index=False)
    pd.set_option("display.width", 220)
    cols = ["simbolo", "marcos", "k", "sesion", "R", "in_n", "in_acierto", "in_r_medio", "in_t",
            "out_n", "out_acierto", "out_r_medio", "out_t", "out_pf"]
    print(tabla[cols].round(3).to_string(index=False))
    total = pd.DataFrame({"acierto_medio": [tabla["in_acierto"].mean(), tabla["out_acierto"].mean()],
                          "r_medio": [tabla["in_r_medio"].mean(), tabla["out_r_medio"].mean()],
                          "combos_r>0": [(tabla["in_r_medio"] > 0).sum(), (tabla["out_r_medio"] > 0).sum()]},
                         index=["dentro", "fuera"])
    print("\n== Promedio de todas las combinaciones ==\n", total.round(3).to_string())
    ok = tabla[(tabla["in_n"] >= 50) & (tabla["in_t"] > 2) & (tabla["out_n"] >= 20)
               & (tabla["out_r_medio"] > 0) & (tabla["out_t"] > 2)]
    print(f"\n== Sobreviven (t > 2 dentro Y fuera): {len(ok)} de {len(tabla)} ==")
    print(ok[cols].round(3).to_string(index=False) if len(ok) else "ninguna")
