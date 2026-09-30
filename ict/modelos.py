"""Los modelos, tal como los enseñan sus autores, llevados a reglas mecánicas.

Cada función recibe las velas y devuelve la lista de `Operacion` simuladas.
Las reglas y su fuente están documentadas en el README de esta carpeta.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from smc import (Orden, a_nueva_york, barridos_de_swing, medio_dia_previo, niveles_sesion, simular, swing_objetivo,
                 ultimo_swing)


def _en(m, ventanas):
    return any(a <= m < b for a, b in ventanas)


def _hasta_ny(ny_min, dias, t, minuto):
    """Última barra del mismo día de NY con ny_min < minuto (para cierres y vencimientos)."""
    j = t
    n = len(ny_min)
    while j + 1 < n and dias[j + 1] == dias[t] and ny_min[j + 1] < minuto:
        j += 1
    return j


def _objetivo(p, sl, d, modo, rr, t, sw_idx, sw_precio, k):
    riesgo = abs(p - sl)
    if modo == "rr":
        return p + d * rr * riesgo
    # liquidez opuesta ("draw on liquidity"), a no menos de 1R
    return swing_objetivo(sw_idx, sw_precio, k, t, p, d, riesgo)


# ─────────────────────────────────────────── ICT: barrido + MSS + FVG (Silver Bullet / 2022)
def barrido_mss_fvg(df, costo, ventanas, liquidez="swing", objetivo="rr", rr=2.0,
                    entrada="borde", k=2, max_barras=24, cierre_ny=16 * 60,
                    riesgo_min=3.0, premium_discount=False):
    """Silver Bullet (ICT, JadeCap) y modelo de la mentoría 2022 (ICT).

    1. Se toma liquidez: un swing intacto (Silver Bullet) o un nivel de sesión
       (Asia, Londres, día anterior: modelo 2022).
    2. Cambio de estructura (MSS): una vela cierra más allá del último swing opuesto.
    3. El desplazamiento deja un FVG a favor del giro.
    4. Límite en el FVG (borde o 50 % = "consequent encroachment"), stop detrás del
       extremo del barrido, objetivo 2R o la liquidez opuesta.
    Una operación por ventana por día. La orden vence al cerrar la ventana.
    """
    o, h, l, c = (df[x].to_numpy() for x in ("open", "high", "low", "close"))
    m, dias = df["ny_min"].to_numpy(), df["ny_dia"].to_numpy()
    b_alto_sw, b_bajo_sw, ia, ib = barridos_de_swing(h, l, k)
    if liquidez == "sesion":
        b_alto, b_bajo = niveles_sesion(df)
    else:
        b_alto, b_bajo = b_alto_sw, b_bajo_sw

    medio = medio_dia_previo(df)
    ops, n = [], len(c)
    usado = set()   # (día, ventana)
    en_v = np.zeros(n, bool)
    for w in ventanas:
        en_v |= (m >= w[0] - 60) & (m < w[1])
    candidatas = np.flatnonzero(en_v & (~np.isnan(b_alto) | ~np.isnan(b_bajo)))
    for t in candidatas:
        if t >= n - 1:
            break
        ventana = next(w for w in ventanas if w[0] - 60 <= m[t] < w[1])
        clave = (dias[t], ventana)
        if clave in usado:
            continue
        for d, barrido in ((-1, b_alto), (1, b_bajo)):
            if np.isnan(barrido[t]):
                continue
            ext = h[t] if d < 0 else l[t]
            ref_i = ultimo_swing(ib if d < 0 else ia, k, t)
            if ref_i is None:
                continue
            ref = l[ref_i] if d < 0 else h[ref_i]
            fvg = None
            for u in range(t, min(t + max_barras, n - 1)):
                if dias[u] != dias[t] or m[u] >= ventana[1]:
                    break
                ext = max(ext, h[u]) if d < 0 else min(ext, l[u])
                if u - 2 >= t - 1:
                    if d < 0 and h[u] < l[u - 2]:
                        fvg = (h[u], l[u - 2])          # zona bajista [abajo, arriba]
                    if d > 0 and l[u] > h[u - 2]:
                        fvg = (h[u - 2], l[u])
                mss = c[u] < ref if d < 0 else c[u] > ref
                if mss and fvg is not None and _en(m[u], [ventana]):
                    abajo, arriba = fvg
                    if entrada == "ce":
                        p = (abajo + arriba) / 2
                    else:
                        p = abajo if d < 0 else arriba
                    if premium_discount and not (p - medio[u]) * d < 0:
                        break   # largos solo en descuento, cortos solo en premium
                    sl = ext + d * -1 * costo * 0.5
                    tp = _objetivo(p, sl, d, objetivo, rr, u, ib if d < 0 else ia,
                                   l if d < 0 else h, k)
                    if tp is None:
                        break
                    fin_v = _hasta_ny(m, dias, u, ventana[1])
                    orden = Orden(u, d, p, sl, tp, fin_v, _hasta_ny(m, dias, u, cierre_ny))
                    op = simular(o, h, l, c, orden, costo, riesgo_min)
                    if op is not None:
                        ops.append(op)
                        usado.add(clave)
                    break
            if clave in usado:
                break
    return ops


# ─────────────────────────────────────────── iFVG (modelo de Josh, NQ/ES)
def ifvg(df, costo, ventanas=((9 * 60 + 30, 11 * 60 + 30),), liquidez="swing",
         objetivo="dol", rr=2.0, entrada="cierre", k=2, antes=12, max_barras=12,
         cierre_ny=16 * 60, riesgo_min=3.0, max_por_dia=1, premium_discount=False):
    """Inverse FVG: se barre liquidez, y el FVG que empujó el barrido se invierte.

    Largo: el precio barre un mínimo; el FVG bajista que se formó en la caída
    (hasta `antes` barras previas) recibe un cierre por encima de su borde
    superior. Entrada al cierre de esa vela (o en el regreso a la zona), stop
    bajo el mínimo del barrido, objetivo = liquidez interna opuesta o 2R.
    """
    o, h, l, c = (df[x].to_numpy() for x in ("open", "high", "low", "close"))
    m, dias = df["ny_min"].to_numpy(), df["ny_dia"].to_numpy()
    b_alto_sw, b_bajo_sw, ia, ib = barridos_de_swing(h, l, k)
    if liquidez == "sesion":
        b_alto, b_bajo = niveles_sesion(df)
    else:
        b_alto, b_bajo = b_alto_sw, b_bajo_sw

    medio = medio_dia_previo(df)
    ops, n = [], len(c)
    por_dia = {}
    ocupado_hasta = -1
    en_v = np.zeros(n, bool)
    for w in ventanas:
        en_v |= (m >= w[0] - 30) & (m < w[1])
    candidatas = np.flatnonzero(en_v & (~np.isnan(b_alto) | ~np.isnan(b_bajo)))
    for t in candidatas:
        if t < 3 or t >= n - 1 or t <= ocupado_hasta:
            continue
        if por_dia.get(dias[t], 0) >= max_por_dia:
            continue
        for d, barrido in ((1, b_bajo), (-1, b_alto)):
            if np.isnan(barrido[t]):
                continue
            # FVG que empujó hacia el barrido (bajista si d = +1)
            zona = None
            for j in range(t, max(t - antes, 2) - 1, -1):
                if d > 0 and h[j] < l[j - 2]:
                    zona = (h[j], l[j - 2]); break
                if d < 0 and l[j] > h[j - 2]:
                    zona = (h[j - 2], l[j]); break
            if zona is None:
                continue
            abajo, arriba = zona
            ext = l[t] if d > 0 else h[t]
            for u in range(t, min(t + max_barras, n - 2)):
                if dias[u] != dias[t]:
                    break
                ext = min(ext, l[u]) if d > 0 else max(ext, h[u])
                invierte = c[u] > arriba if d > 0 else c[u] < abajo
                if not invierte:
                    continue
                if not _en(m[u], ventanas):
                    break
                if entrada == "cierre":
                    p_ref, lim = c[u], np.nan
                else:
                    lim = arriba if d > 0 else abajo
                    p_ref = lim
                if premium_discount and not (p_ref - medio[u]) * d < 0:
                    break
                sl = ext - d * costo * 0.5
                tp = _objetivo(p_ref, sl, d, objetivo, rr, u, ia if d > 0 else ib,
                               h if d > 0 else l, k)
                if tp is None:
                    break
                orden = Orden(u, d, lim, sl, tp, u + max_barras,
                              _hasta_ny(m, dias, u, cierre_ny))
                op = simular(o, h, l, c, orden, costo, riesgo_min)
                if op is not None:
                    ops.append(op)
                    por_dia[dias[t]] = por_dia.get(dias[t], 0) + 1
                    ocupado_hasta = op.t_salida
                break
            if t <= ocupado_hasta:
                break
    return ops


# ─────────────────────────────────────────── CRT (Romeo) y CRT + TBS
def crt(h4, m5, costo, horas_c2=(1, 5, 9), entrada="cierre_c2", nivel_clave=False,
        velas_max=2, riesgo_min=3.0, rr_min=0.0, ltf=None):
    """Candle Range Theory sobre H4, simulada en M5.

    C1 = vela ancla (su máximo y mínimo son el rango). C2 barre un extremo de C1
    con la mecha y cierra de vuelta adentro. Objetivos: 50 % del rango (parcial y
    stop a break-even) y el extremo opuesto. Stop detrás de la mecha de C2.

    entrada="cierre_c2": a mercado al abrir C3 (CRT clásico). Sabe cómo cerró C2.
    entrada="tbs": NO espera el cierre de C2. En M15 (`ltf`), durante C2 y C3:
    una vela cierra con el CUERPO fuera del rango de C1 (turtle body soup) y luego
    otra cierra más allá del extremo de la última vela opuesta, de vuelta dentro
    del rango (Modelo #1). Entrada en la apertura siguiente; stop tras el extremo
    del barrido.
    horas_c2: hora de NY a la que abre C2 (1, 5 y 9 AM en la versión de Romeo).
    """
    H = h4.reset_index()
    ny_h = a_nueva_york(pd.DatetimeIndex(H["time"])).hour.to_numpy()
    filas = H[["time", "open", "high", "low", "close"]].to_dict("records")
    altos, bajos = H["high"].to_numpy(), H["low"].to_numpy()
    o5, h5, l5, c5 = (m5[x].to_numpy() for x in ("open", "high", "low", "close"))
    t5 = m5.index.values
    ops = []
    for i in range(7, len(H) - 1):
        if horas_c2 and ny_h[i] not in horas_c2:
            continue
        c1, c2 = filas[i - 1], filas[i]
        if c2["time"] - c1["time"] != pd.Timedelta(hours=4):
            continue   # hueco de fin de semana o de datos
        if c1["high"] - c1["low"] <= 0:
            continue
        clave_alto = c1["high"] >= altos[i - 7:i - 1].max()
        clave_bajo = c1["low"] <= bajos[i - 7:i - 1].min()
        medio = (c1["high"] + c1["low"]) / 2
        fin_tiempo = c2["time"] + pd.Timedelta(hours=4 * (1 + velas_max))
        i_fin = np.searchsorted(t5, np.datetime64(fin_tiempo), side="left") - 1

        if entrada == "cierre_c2":
            barre_alto = c2["high"] > c1["high"] and c2["low"] >= c1["low"]
            barre_bajo = c2["low"] < c1["low"] and c2["high"] <= c1["high"]
            if not (barre_alto or barre_bajo):
                continue
            d = -1 if barre_alto else 1
            if nivel_clave and not (clave_alto if d < 0 else clave_bajo):
                continue
            if not c1["low"] < c2["close"] < c1["high"]:
                continue
            tp2 = c1["low"] if d < 0 else c1["high"]
            sl = (c2["high"] if d < 0 else c2["low"]) - d * costo * 0.5
            i_sig = np.searchsorted(t5, np.datetime64(c2["time"] + pd.Timedelta(hours=4)))
            if i_sig >= len(t5) or i_fin <= i_sig:
                continue
            p = o5[i_sig]
            if rr_min and abs(tp2 - p) < rr_min * abs(p - sl):
                continue
            orden = Orden(i_sig - 1, d, np.nan, sl, tp2, i_sig, i_fin, tp1=medio)
            op = simular(o5, h5, l5, c5, orden, costo, riesgo_min)
        else:
            op = _crt_tbs(ltf, o5, h5, l5, c5, t5, c1, c2, medio, i_fin, costo,
                          riesgo_min, rr_min,
                          lados=(clave_alto, clave_bajo) if nivel_clave else (True, True))
        if op is not None:
            op.extra["c2"] = c2["time"]
            ops.append(op)
    return ops


def _crt_tbs(m15, o5, h5, l5, c5, t5, c1, c2, medio, i_fin, costo, riesgo_min, rr_min,
             lados):
    ini, fin = c2["time"], c2["time"] + pd.Timedelta(hours=8)
    a, b = m15.index.searchsorted(ini), m15.index.searchsorted(fin)
    v = m15.iloc[a:b]
    if len(v) < 3:
        return None
    oo, hh, ll, cc = (v[x].to_numpy() for x in ("open", "high", "low", "close"))
    d, ext, j0 = 0, None, None
    for j in range(len(v)):
        if d == 0:
            # turtle body soup: el primer CUERPO que cierra fuera del rango fija el lado
            if lados[0] and cc[j] > c1["high"]:
                d, ext, j0 = -1, hh[j], j
            elif lados[1] and cc[j] < c1["low"]:
                d, ext, j0 = 1, ll[j], j
            continue
        ext = max(ext, hh[j]) if d < 0 else min(ext, ll[j])
        borde = c1["high"] if d < 0 else c1["low"]
        # Modelo #1: cierre más allá de la última vela opuesta, de vuelta dentro
        opuestas = [q for q in range(j0, j) if (cc[q] > oo[q] if d < 0 else cc[q] < oo[q])]
        if not opuestas:
            continue
        q = opuestas[-1]
        confirma = (cc[j] < ll[q] and cc[j] < borde) if d < 0 else                    (cc[j] > hh[q] and cc[j] > borde)
        if not confirma:
            continue
        t_conf = v.index[j] + pd.Timedelta(minutes=15)   # cierre de la vela M15
        i_sig = np.searchsorted(t5, np.datetime64(t_conf))
        if i_sig >= len(t5) or i_fin <= i_sig:
            return None
        p = cc[j]
        tp2 = c1["low"] if d < 0 else c1["high"]
        sl = ext - d * costo * 0.5
        if (medio - p) * d <= 0:
            return None
        if rr_min and abs(tp2 - p) < rr_min * abs(p - sl):
            return None
        orden = Orden(i_sig - 1, d, np.nan, sl, tp2, i_sig, i_fin, tp1=medio)
        return simular(o5, h5, l5, c5, orden, costo, riesgo_min)
    return None
