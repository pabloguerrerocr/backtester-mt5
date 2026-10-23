"""PDF del laboratorio: ranking, veredicto, Monte Carlo y las posiciones de hoy.

Usa el formato fijo de Proyectos/_informe. Lo llama `python -m laboratorio`.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

# el formato de los PDF vive fuera del repo, en Proyectos/_informe (hermano de backtester-mt5)
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_informe"))
from informe import Informe  # noqa: E402

AQUI = Path(__file__).parent
SALIDA = AQUI / "Laboratorio-de-estrategias.pdf"
# paleta categorica de referencia (dataviz/references/palette.md), en orden fijo
COLORES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]
NOMBRES = {"carver_ewmac": "Carver (4 cruces de EMA)", "clenow_tendencia": "Clenow (tendencia 50/100)",
           "tortugas_55_20": "Tortugas (canal 55/20)", "connors_rsi2": "Connors (RSI 2)",
           "comprar_y_mantener": "Comprar y mantener"}


def _pct(x):
    return f"{x:.0%}" if pd.notna(x) else "-"


def _num(x, d=2):
    return f"{x:+.{d}f}".replace(".", ",") if pd.notna(x) else "-"


def figura(carteras: dict, corte) -> Path:
    fig, ax = plt.subplots(figsize=(10, 4.2), dpi=160)
    for (nombre, r), color in zip(carteras.items(), COLORES):
        eq = (1 + r).cumprod()
        ax.plot(eq.index, eq.values, color=color, lw=2 if nombre != "comprar_y_mantener" else 1.4,
                ls="-" if nombre != "comprar_y_mantener" else "--", label=NOMBRES[nombre])
        ax.annotate(NOMBRES[nombre].split(" (")[0], (eq.index[-1], eq.iloc[-1]), xytext=(6, 0),
                    textcoords="offset points", va="center", fontsize=8, color="#3d3d3a")
    ax.axvline(pd.Timestamp(corte), color="#8a8a85", lw=1, ls=":")
    ax.text(pd.Timestamp(corte), ax.get_ylim()[1], "  fuera de muestra →", va="top", fontsize=8, color="#5d5d58")
    ax.axhline(1, color="#c9c8c2", lw=0.8)
    ax.set_yscale("log")
    ax.set_ylabel("capital (inicio = 1, escala log)", fontsize=9, color="#3d3d3a")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.spines["left"].set_color("#c9c8c2")
    ax.spines["bottom"].set_color("#c9c8c2")
    ax.tick_params(labelsize=8, colors="#5d5d58")
    ax.grid(axis="y", color="#ecebe6", lw=0.6)
    ax.legend(fontsize=8, frameon=False, loc="upper left", ncol=3)
    fig.tight_layout()
    ruta = AQUI / "resultados" / "curvas.png"
    fig.savefig(ruta)
    plt.close(fig)
    return ruta


def reporte(datos: dict, por_mercado: pd.DataFrame, resumen: pd.DataFrame, carteras: dict) -> str:
    hoy = dt.date.today()
    res = resumen.sort_values("sharpe_fuera", ascending=False)
    corte = res["corte"].iloc[0]
    ref = res[res["tipo"] == "referencia"].iloc[0]
    aprobadas = res[res["veredicto"].str.startswith("APRUEBA")]
    duda = res[res["veredicto"] == "EN DUDA"]
    mejor = res[res["tipo"] != "referencia"].iloc[0]

    inf = Informe("Laboratorio de estrategias",
                  "Las estrategias publicadas por traders profesionales, probadas con el mismo proceso, "
                  f"en {len(datos)} mercados de MT5", str(SALIDA))
    if len(aprobadas):
        frase = (f"<b>{len(aprobadas)} estrategia(s) pasan</b> todas las pruebas: "
                 + ", ".join(NOMBRES[n] for n in aprobadas["estrategia"]) + ". Pasan a papel, no a dinero.")
    elif len(duda):
        frase = ("<b>Ninguna pasa todas las pruebas</b>, pero " + ", ".join(NOMBRES[n] for n in duda["estrategia"])
                 + " gana dentro y fuera de muestra con menos fuerza de la exigida: quedan en observación.")
    else:
        frase = "<b>Ninguna pasa.</b> Ninguna regla de los profesionales gana con estos datos y costos."
    inf.portada(
        resumen=f"{frase} La mejor fuera de muestra es <b>{NOMBRES[mejor['estrategia']]}</b>, con un Sharpe de "
                f"{_num(mejor['sharpe_fuera'])} (comprar y mantener: {_num(ref['sharpe_fuera'])}). Se prueban las reglas "
                "originales de cada autor, con los <b>mismos parámetros en todos los mercados</b> y sin optimizar nada: "
                "así trabajan Carver, Clenow y Radge. Las reglas del veredicto se escribieron antes de ver resultados.",
        fuente=f"Datos: MT5 MetaQuotes-Demo, velas diarias {res['desde'].min()} a {hoy}. Dentro de muestra hasta "
               f"{corte}; fuera de muestra después. Código: backtester-mt5/laboratorio. Se regenera con "
               "python -m laboratorio.")

    inf.lamina(
        "1 · El veredicto",
        tabla=[["Estrategia", "Sharpe dentro", "Sharpe fuera", "Retorno anual fuera", "Mercados que ganan",
                "Veredicto"]] +
              [[NOMBRES[f.estrategia], _num(f.sharpe_dentro), _num(f.sharpe_fuera), _pct(f.retorno_anual_fuera),
                _pct(f.mercados_positivos_fuera), f"<b>{f.veredicto}</b>"] for f in res.itertuples()],
        nota="Sharpe = ganancia por unidad de riesgo, por año. Un fondo de tendencia bueno ronda 0,5 a 0,8; "
             "más de 2 sostenido es casi imposible. Retorno con la cartera llevada a 15 % de volatilidad anual. "
             "Para aprobar: Sharpe mayor a 0,3 dentro y fuera, gana en 60 % de los mercados y ninguna alarma.")

    inf.lamina("2 · Cómo le fue a cada una", figura=str(figura({n: carteras[n] for n in NOMBRES if n in carteras}, corte)),
               nota="Cartera de cada estrategia: todos los mercados con el mismo riesgo. La línea punteada vertical "
                    "separa los datos con los que se juzga (izquierda) de los que nunca se miraron (derecha).")

    inf.lamina(
        "3 · Las pruebas de los profesionales",
        tabla=[["Estrategia", "Operaciones", "Acierto medio", "Peor caída histórica", "Prob. de perder en un año",
                "Prob. de caer 20 %", "Alarmas de Radge"]] +
              [[NOMBRES[f.estrategia], f"{f.operaciones:,}".replace(",", "."), _pct(f.acierto_medio), _pct(f.max_dd),
                _pct(f.prob_perder_1_ano), _pct(f.prob_dd_20), f.alarmas] for f in res.itertuples()],
        nota="Monte Carlo (Davey): 5.000 años simulados barajando bloques de 20 días de la historia real. "
             "Las estrategias de tendencia aciertan 30-45 %: ganan porque las ganancias son más grandes que las pérdidas.")

    tabla_m = por_mercado.pivot(index="mercado", columns="estrategia", values="sharpe_fuera")[
        [n for n in NOMBRES if n in por_mercado["estrategia"].unique()]]
    inf.lamina(
        "4 · Mercado por mercado (Sharpe fuera de muestra)",
        tabla=[["Mercado"] + [NOMBRES[c].split(" (")[0] for c in tabla_m.columns]] +
              [[m] + [_num(v) for v in fila] for m, fila in tabla_m.iterrows()],
        nota="Si una estrategia gana solo en uno o dos mercados, es suerte (Radge). Lo robusto gana en la mayoría "
             "con las mismas reglas.")

    candidatas = aprobadas if len(aprobadas) else duda
    if len(candidatas):
        filas = [["Estrategia", "Mercado", "Posición de hoy", "Qué significa"]]
        for n in candidatas["estrategia"]:
            for f in por_mercado[por_mercado["estrategia"] == n].itertuples():
                p = f.pos_hoy
                que = ("comprado" if p > 0 else "vendido" if p < 0 else "fuera") + \
                      (f" (fuerza {abs(p):.1f} de 2)" if n == "carver_ewmac" and p else "")
                filas.append([NOMBRES[n], f.mercado, _num(p, 1), que])
        inf.lamina(f"5 · Posiciones de hoy ({hoy:%d/%m/%Y}), solo para el papel", tabla=filas,
                   aviso="Esto es para anotar en papel y comparar dentro de 6 meses, como pide Davey. "
                         "No es una recomendación de inversión ni una señal para operar con dinero.")

    inf.lamina(
        "6 · Cómo se usa",
        tabla=[["Quién", "Paso"],
               ["la máquina", "[   ]  Cada domingo corre sola: baja los datos de MT5, prueba todo y rehace este PDF"],
               ["vos", "[   ]  Mirar la lámina 1: si una estrategia pasa a APRUEBA, anotar sus posiciones en papel"],
               ["vos", "[   ]  En MT5, gráfico diario + plantilla «Profesionales»: ver lo mismo que prueba el laboratorio"],
               ["Claude", "[   ]  Agregar estrategias nuevas a estrategias.py: pasan por las mismas pruebas"],
               ["los dos", "[   ]  Después de 6 meses en papel, comparar contra el backtest antes de un solo dólar"]])
    return inf.guardar()
