"""Corre todas las configuraciones en los 5 símbolos y guarda cada operación.

    python estudio.py            # ~10 min con 6 procesos
Salida: resultados/operaciones.csv.gz (una fila por operación y configuración).
"""
from __future__ import annotations

import itertools
import os
import sys
import time
from multiprocessing import Pool

import pandas as pd

import modelos as M
from smc import COSTO, cargar

AQUI = os.path.dirname(os.path.abspath(__file__))
SIMBOLOS = ["USTEC", "US500", "EURUSD", "GBPUSD", "XAUUSD"]

AM = [(600, 660)]
TRES = [(180, 240), (600, 660), (840, 900)]
NY_AM = [(510, 660)]
KZ = [(420, 600)]
IFVG_V = [(570, 690)]

# La configuración "del profesional" de cada modelo: la que se reporta como principal.
PRO = {
    "Silver Bullet (ICT / JadeCap)": ("sb", dict(ventanas=AM, objetivo="rr", rr=2.0,
                                                 entrada="borde", k=2)),
    "Modelo 2022 (ICT)": ("sb", dict(ventanas=NY_AM, liquidez="sesion", objetivo="rr",
                                     rr=2.0, entrada="borde", k=2)),
    "iFVG (modelo de Josh)": ("ifvg", dict(objetivo="dol", entrada="cierre", k=2)),
    "CRT clásico H4 (Romeo)": ("crt", dict(entrada="cierre_c2", horas_c2=(1, 5, 9))),
    "CRT + TBS (Modelo #1)": ("crt", dict(entrada="tbs", horas_c2=(1, 5, 9))),
}


def rejilla():
    """Variantes razonables de cada modelo, para medir sobreajuste."""
    out = []
    for v, e, (obj, rr), k, pd_ in itertools.product(
            [("AM", AM), ("3 ventanas", TRES)], ["borde", "ce"],
            [("rr", 2.0), ("rr", 3.0), ("dol", 0)], [1, 2, 3], [False, True]):
        out.append(("Silver Bullet", "sb", dict(ventanas=v[1], entrada=e, objetivo=obj,
                                                rr=rr, k=k, premium_discount=pd_),
                    f"{v[0]} {e} {obj}{rr or ''} k{k}{' PD' if pd_ else ''}"))
    for v, e, (obj, rr), k, pd_ in itertools.product(
            [("8:30-11", NY_AM), ("7-10", KZ)], ["borde", "ce"],
            [("rr", 2.0), ("rr", 3.0), ("dol", 0)], [2, 3], [False, True]):
        out.append(("Modelo 2022", "sb", dict(ventanas=v[1], liquidez="sesion", entrada=e,
                                              objetivo=obj, rr=rr, k=k, premium_discount=pd_),
                    f"{v[0]} {e} {obj}{rr or ''} k{k}{' PD' if pd_ else ''}"))
    for liq, e, (obj, rr), k, pd_ in itertools.product(
            ["swing", "sesion"], ["cierre", "retorno"],
            [("dol", 0), ("rr", 2.0), ("rr", 3.0)], [1, 2, 3], [False, True]):
        out.append(("iFVG", "ifvg", dict(liquidez=liq, entrada=e, objetivo=obj, rr=rr, k=k,
                                         premium_discount=pd_),
                    f"{liq} {e} {obj}{rr or ''} k{k}{' PD' if pd_ else ''}"))
    for ent, horas, clave, vm, rrm in itertools.product(
            ["cierre_c2", "tbs"], [(1, 5, 9), ()], [False, True], [1, 2], [0.0, 2.0]):
        out.append(("CRT + TBS" if ent == "tbs" else "CRT clásico", "crt",
                    dict(entrada=ent, horas_c2=horas, nivel_clave=clave, velas_max=vm,
                         rr_min=rrm),
                    f"{'1/5/9' if horas else 'todas'}{' clave' if clave else ''} "
                    f"{vm}v rr>={rrm:g}"))
    return out


_DATOS = {}


def _datos(s):
    if s not in _DATOS:
        _DATOS[s] = (cargar(s, "M5"), cargar(s, "M15"), cargar(s, "H4"))
    return _DATOS[s]


def correr(tarea):
    simbolo, familia, tipo, params, nombre, es_pro = tarea
    m5, m15, h4 = _datos(simbolo)
    costo = COSTO[simbolo]
    if tipo == "sb":
        ops = M.barrido_mss_fvg(m5, costo, **params)
    elif tipo == "ifvg":
        ops = M.ifvg(m5, costo, **params)
    else:
        ops = M.crt(h4, m5, costo, ltf=m15, **params)
    idx = m5.index
    return pd.DataFrame([{
        "simbolo": simbolo, "familia": familia, "config": nombre, "pro": es_pro,
        "entrada_t": idx[o.t_entrada], "salida_t": idx[o.t_salida],
        "direccion": o.direccion, "r": o.r,
        "r_bruto": o.r + costo / abs(o.entrada - o.sl), "motivo": o.motivo,
    } for o in ops])


def main():
    tareas = []
    for s in SIMBOLOS:
        for nombre, (tipo, p) in PRO.items():
            tareas.append((s, nombre, tipo, p, "pro", True))
        for fam, tipo, p, nombre in rejilla():
            tareas.append((s, fam, tipo, p, nombre, False))
    # agrupar por símbolo para que cada proceso cargue pocos archivos
    tareas.sort(key=lambda x: x[0])
    t0 = time.time()
    with Pool(6) as pool:
        partes = []
        for i, df in enumerate(pool.imap(correr, tareas, chunksize=8), 1):
            partes.append(df)
            if i % 50 == 0:
                print(f"{i}/{len(tareas)} ({time.time() - t0:.0f}s)", flush=True)
    todo = pd.concat([p for p in partes if len(p)], ignore_index=True)
    os.makedirs(os.path.join(AQUI, "resultados"), exist_ok=True)
    todo.to_csv(os.path.join(AQUI, "resultados", "operaciones.csv.gz"), index=False)
    print(f"{len(tareas)} corridas, {len(todo):,} operaciones, {time.time() - t0:.0f}s")


if __name__ == "__main__":
    sys.exit(main())
