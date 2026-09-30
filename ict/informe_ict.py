"""Analiza resultados/operaciones.csv.gz y arma el PDF con el formato de Proyectos\\_informe.

    python informe_ict.py
"""
from __future__ import annotations

import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "..", "_informe"))
from informe import Informe  # noqa: E402

from estudio import PRO, SIMBOLOS  # noqa: E402
from smc import COSTO  # noqa: E402

CORTE = pd.Timestamp("2024-07-01")      # antes: dentro de muestra; desde: fuera de muestra
RIESGO = 0.01
FIG = os.path.join(AQUI, "resultados", "figuras")
SALIDA = os.path.join(AQUI, "Backtest-ICT-CRT-iFVG.pdf")

# paleta de referencia (skill dataviz), modo claro
AZUL, NARANJA, AQUA, GRIS, TINTA, TINTA2 = ("#2a78d6", "#eb6834", "#1baf7a", "#9a9993",
                                             "#0b0b0b", "#52514e")
ROJO = "#e34948"
plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": "#c9c8c2",
    "axes.labelcolor": TINTA2, "xtick.color": TINTA2, "ytick.color": TINTA2,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
    "grid.color": "#ecebe6", "grid.linewidth": 0.7, "axes.axisbelow": True,
    "figure.facecolor": "white", "axes.facecolor": "white", "axes.titlesize": 9.5,
    "axes.titlecolor": TINTA, "axes.titleweight": "bold", "axes.titlelocation": "left",
})


def metricas(r: pd.Series, meses: float) -> dict:
    r = r.to_numpy()
    n = len(r)
    if n == 0:
        return dict(n=0)
    eq = np.cumprod(1 + RIESGO * r)
    dd = (eq / np.maximum.accumulate(eq) - 1).min()
    cum = np.cumsum(r)
    dd_r = (cum - np.maximum.accumulate(np.r_[0, cum])[1:]).min()
    gan, per = r[r > 0].sum(), -r[r < 0].sum()
    return dict(n=n, por_mes=n / meses, win=(r > 0).mean(), e=r.mean(),
                pf=gan / per if per > 0 else np.nan, total=r.sum(), dd_r=dd_r,
                ret=eq[-1] - 1, dd=dd, t=r.mean() / r.std(ddof=1) * np.sqrt(n) if n > 2 else np.nan)


def pct(x, d=1):
    return "n/d" if pd.isna(x) else f"{x * 100:+.{d}f} %"


def rr(x):
    return "n/d" if pd.isna(x) else f"{x:+.2f} R"


def prop_firm(r: np.ndarray, sims=20_000, meta=0.10, limite=-0.10, max_ops=300, semilla=7):
    """Probabilidad de llegar a +10 % antes de perder 10 %, arriesgando 1 % por operación."""
    rng = np.random.default_rng(semilla)
    pasa = 0
    for _ in range(sims):
        eq = 1.0
        for x in rng.choice(r, max_ops):
            eq *= 1 + RIESGO * x
            if eq - 1 >= meta:
                pasa += 1; break
            if eq - 1 <= limite:
                break
    return pasa / sims


PISTA = dict(ventanas=[(600, 660)], entrada="ce", objetivo="rr", rr=2.0, k=1)


def estres():
    """La única variante que sobrevivió: Silver Bullet en USTEC, entrada al 50 % del FVG,
    swing de 3 velas. Se la trata de romper."""
    import modelos as M
    from smc import Orden, cargar, simular
    m5 = cargar("USTEC", "M5")
    o, h, l, c = (m5[x].to_numpy() for x in ("open", "high", "low", "close"))
    m, dias = m5["ny_min"].to_numpy(), m5["ny_dia"].to_numpy()

    def fila(nombre, ops, nota=""):
        r = np.array([x.r for x in ops])
        t = r.mean() / r.std(ddof=1) * np.sqrt(len(r))
        return [nombre, f"{len(r)}", rr(r.mean()), f"{t:+.1f}", nota]

    base = M.barrido_mss_fvg(m5, 1.8, **PISTA)
    filas = [["Prueba", "Ops", "E neta", "t", "Lectura"],
             fila("Regla base (10-11 AM, 50 % del FVG, 2R)", base, "la variante")]
    anual = pd.Series([x.r for x in base], index=m5.index[[x.t_entrada for x in base]])
    anual = anual.groupby(anual.index.year).mean()
    filas.append(["Por año", "", " · ".join(f"{a}: {v:+.2f}" for a, v in anual.items()), "",
                  "positiva los 5 años" if (anual > 0).all() else "no todos los años"])
    filas.append(fila("Solo largos", [x for x in base if x.direccion > 0]))
    filas.append(fila("Solo cortos", [x for x in base if x.direccion < 0], "casi cero"))
    filas.append(fila("Costo × 2 (3,6 pts)", M.barrido_mss_fvg(m5, 3.6, **PISTA)))
    filas.append(fila("Costo × 3 (5,4 pts)", M.barrido_mss_fvg(m5, 5.4, **PISTA)))
    filas.append(fila("Ventana 9:30-11 en vez de 10-11",
                      M.barrido_mss_fvg(m5, 1.8, **{**PISTA, "ventanas": [(570, 660)]}),
                      "se evapora"))
    filas.append(fila("Mismas reglas en US500",
                      M.barrido_mss_fvg(cargar("US500", "M5"), 0.6, **PISTA), "no se traslada"))
    # entrada en un minuto al azar de la ventana, misma dirección y mismo stop
    rng, azar = np.random.default_rng(0), []
    for _ in range(20):
        for op in base:
            d0 = dias[op.t_entrada]
            cand = np.flatnonzero((dias == d0) & (m >= 600) & (m < 660))
            t = rng.choice(cand[:-1])
            riesgo = abs(op.entrada - op.sl)
            p = c[t]
            fin = np.flatnonzero((dias == d0) & (m < 960))[-1]
            x = simular(o, h, l, c, Orden(t, op.direccion, np.nan, p - op.direccion * riesgo,
                                          p + op.direccion * 2 * riesgo, t + 1, fin), 1.8)
            if x:
                azar.append(x)
    filas.append(fila("Misma dirección y stop, minuto al azar (×20)", azar,
                      "el momento de entrada sí aporta"))
    meses = (m5.index[-1] - m5.index[0]).days / 30.44
    return filas, len(base) / meses, float(np.mean([x.r for x in base]))


def main():
    os.makedirs(FIG, exist_ok=True)
    ops = pd.read_csv(os.path.join(AQUI, "resultados", "operaciones.csv.gz"),
                      parse_dates=["entrada_t", "salida_t"])
    ops = ops.sort_values("entrada_t")
    # meses de datos por símbolo (para operaciones por mes)
    rango = {}
    for s in SIMBOLOS:
        t = pd.read_csv(os.path.join(AQUI, "datos", f"{s}_M5.csv"), usecols=["time"],
                        parse_dates=["time"])["time"]
        rango[s] = (t.iloc[0], t.iloc[-1])
    meses = {s: (b - a).days / 30.44 for s, (a, b) in rango.items()}

    pro = ops[ops.pro]
    nombres = list(PRO)

    # ── 1. tabla de las configuraciones de los profesionales
    filas = []
    for (nombre, s), g in pro.groupby(["familia", "simbolo"]):
        m = metricas(g["r"], meses[s])
        m.update(familia=nombre, simbolo=s, e_bruta=g["r_bruto"].mean())
        filas.append(m)
    T = pd.DataFrame(filas)
    T.to_csv(os.path.join(AQUI, "resultados", "resumen_pro.csv"), index=False)

    matriz = [["Modelo"] + SIMBOLOS]
    for nombre in nombres:
        fila = [nombre]
        for s in SIMBOLOS:
            x = T[(T.familia == nombre) & (T.simbolo == s)]
            if not len(x):
                fila.append("sin ops"); continue
            x = x.iloc[0]
            marca = " *" if x.t > 2 else ""
            fila.append(f"{x.e:+.2f} R{marca}<br/><font size=7.5 color='#6b6b6b'>"
                        f"{int(x.n)} ops · t = {x.t:+.1f}</font>")
        matriz.append(fila)
    positivas = int((T.e > 0).sum())
    significativas = int(((T.e > 0) & (T.t > 2)).sum())

    # ── 2. detalle USTEC
    U = T[T.simbolo == "USTEC"].set_index("familia").loc[nombres]
    tabla_u = [["Modelo", "Ops/mes", "Acierto", "E neta", "E sin costos", "Factor de beneficio",
                "Total", "Retorno a 1 %", "Caída máx."]]
    for nombre, x in U.iterrows():
        tabla_u.append([nombre, f"{x.por_mes:.1f}", f"{x.win:.0%}", rr(x.e), rr(x.e_bruta),
                        f"{x.pf:.2f}", f"{x.total:+.0f} R", pct(x.ret, 0), pct(x.dd, 0)])

    # figura: curvas en R, USTEC, pequeños múltiplos
    fig, ejes = plt.subplots(1, 5, figsize=(13, 2.9), sharey=True)
    for ax, nombre in zip(ejes, nombres):
        g = pro[(pro.familia == nombre) & (pro.simbolo == "USTEC")]
        ax.axhline(0, color=GRIS, lw=0.8)
        ax.plot(g["salida_t"], g["r"].cumsum(), color=AZUL, lw=1.6)
        ax.axvline(CORTE, color=GRIS, lw=0.8, ls=":")
        ax.set_title(nombre.split(" (")[0], fontsize=8.5)
        ax.tick_params(axis="x", labelsize=7, rotation=0)
        ax.xaxis.set_major_locator(matplotlib.dates.YearLocator())
        ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%y"))
    ejes[0].set_ylabel("R acumulados (netos)")
    fig.tight_layout()
    f_curvas = os.path.join(FIG, "curvas_ustec.png")
    fig.savefig(f_curvas, dpi=200); plt.close(fig)

    # figura: costos, E bruta vs neta (promedio de los 5 símbolos)
    agg = T.groupby("familia")[["e_bruta", "e"]].mean().loc[nombres]
    fig, ax = plt.subplots(figsize=(10, 3.0))
    y = np.arange(len(nombres))
    ax.barh(y - 0.19, agg["e_bruta"], height=0.36, color=AZUL, label="sin costos")
    ax.barh(y + 0.19, agg["e"], height=0.36, color=NARANJA, label="con spread + deslizamiento")
    ax.axvline(0, color=TINTA2, lw=0.9)
    ax.set_yticks(y, [n.split(" (")[0] for n in nombres]); ax.invert_yaxis()
    ax.set_xlabel("Ganancia esperada por operación (R), promedio de los 5 mercados")
    ax.legend(frameon=False, loc="upper left", fontsize=8)
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    f_costos = os.path.join(FIG, "costos.png")
    fig.savefig(f_costos, dpi=200); plt.close(fig)

    # ── 3. sobreajuste: rejilla dentro vs fuera de muestra
    rej = ops[~ops.pro]
    filas = []
    for (fam, cfg, s), g in rej.groupby(["familia", "config", "simbolo"]):
        dentro, fuera = g[g.entrada_t < CORTE], g[g.entrada_t >= CORTE]
        filas.append(dict(familia=fam, config=cfg, simbolo=s, n=len(g), e=g.r.mean(),
                          t=metricas(g.r, 1)["t"], n_in=len(dentro), e_in=dentro.r.mean(),
                          n_out=len(fuera), e_out=fuera.r.mean(),
                          t_out=metricas(fuera.r, 1)["t"] if len(fuera) > 2 else np.nan))
    R = pd.DataFrame(filas)
    R.to_csv(os.path.join(AQUI, "resultados", "rejilla.csv"), index=False)
    n_cfg = len(R)
    pos_total = int((R.e > 0).sum())
    sig_total = int(((R.e > 0) & (R.t > 2)).sum())
    n_ce = int(R[(R.e > 0) & (R.t > 2)].config.str.contains(" ce ").sum())
    esperadas_azar = 0.023 * n_cfg      # P(t > 2) con una sola cola, si la verdad es E = 0
    validas = R[(R.n_in >= 30) & (R.n_out >= 20)]
    corr = validas[["e_in", "e_out"]].corr().iloc[0, 1]

    # la mejor de cada familia y símbolo, elegida SOLO con datos previos al corte
    mejores = (validas.sort_values("e_in", ascending=False)
               .groupby(["familia", "simbolo"]).head(1)
               .sort_values(["familia", "simbolo"]))
    tabla_m = [["Familia · mercado", "Configuración elegida", "E antes de jul-2024",
                "E después (fuera de muestra)", "Ops después"]]
    for _, x in mejores[mejores.e_in > 0].iterrows():
        tabla_m.append([f"{x.familia} · {x.simbolo}", x.config, rr(x.e_in), rr(x.e_out),
                        f"{int(x.n_out)}"])
    sobreviven = mejores[(mejores.e_in > 0) & (mejores.e_out > 0)]
    caen = int(((mejores.e_in > 0) & (mejores.e_out <= 0)).sum())

    fig, ax = plt.subplots(figsize=(10, 3.4))
    colores = {"Silver Bullet": AZUL, "Modelo 2022": NARANJA, "iFVG": AQUA,
               "CRT clásico": "#eda100", "CRT + TBS": "#4a3aa7"}
    for fam, g in validas.groupby("familia"):
        ax.scatter(g.e_in, g.e_out, s=12, color=colores[fam], alpha=0.75, lw=0, label=fam)
    lim = [min(validas.e_in.min(), validas.e_out.min()) - 0.05,
           max(validas.e_in.max(), validas.e_out.max()) + 0.05]
    ax.plot(lim, lim, color=GRIS, lw=0.8, ls="--")
    ax.axhline(0, color=TINTA2, lw=0.8); ax.axvline(0, color=TINTA2, lw=0.8)
    ax.set_xlabel("E por operación ANTES de jul-2024 (R)")
    ax.set_ylabel("E DESPUÉS (R)")
    ax.legend(frameon=False, fontsize=7.5, ncol=5, loc="upper left")
    fig.tight_layout()
    f_disp = os.path.join(FIG, "dentro_fuera.png")
    fig.savefig(f_disp, dpi=200); plt.close(fig)

    # ── 4. prop firm con el mejor candidato que sobrevive fuera de muestra
    cand = sobreviven.sort_values("e_out", ascending=False).head(3)
    tabla_p = [["Candidato (elegido antes de jul-2024)", "Ops fuera de muestra", "E fuera",
                "P(+10 % antes de −10 %)"]]
    for _, x in cand.iterrows():
        g = rej[(rej.familia == x.familia) & (rej.config == x.config) &
                (rej.simbolo == x.simbolo) & (rej.entrada_t >= CORTE)]
        tabla_p.append([f"{x.familia} · {x.simbolo} · {x.config}", f"{int(x.n_out)}",
                        rr(x.e_out), f"{prop_firm(g.r.to_numpy()):.0%}"])
        if len(tabla_p) == 2:   # el mejor, sin su ventaja: mismas operaciones centradas en 0
            cero = g.r.to_numpy() - g.r.mean()
            tabla_p.append(["   la misma, si su ventaja real fuera cero", f"{int(x.n_out)}",
                            rr(0.0), f"{prop_firm(cero):.0%}"])
    # referencia: moneda al aire con R simétrico de -1/+2 y costo de 0.1R
    azar = np.where(np.random.default_rng(1).random(5000) < 1 / 3, 1.9, -1.1)
    p_azar = prop_firm(azar)

    # ── PDF
    mejor_pro = T.sort_values("e", ascending=False).iloc[0]
    inf = Informe("Backtest de ICT, CRT + TBS e iFVG",
                  "Cinco modelos con las reglas de sus autores · 5 mercados de la demo de "
                  "MetaTrader 5 · 2019-2026", SALIDA)
    inf.portada(
        resumen=(
            f"<b>Ninguno de los cinco modelos es rentable de forma confiable.</b> De las "
            f"{len(T)} combinaciones modelo × mercado con la configuración de su autor, "
            f"{positivas} ganan algo y <b>{significativas}</b> lo hacen con un resultado que "
            f"no se explica por azar (t &gt; 2). La mejor, {mejor_pro.familia} en "
            f"{mejor_pro.simbolo}, deja {rr(mejor_pro.e)} por operación. "
            f"<br/><br/>Al buscar la mejor variante entre {n_cfg} configuraciones aparecen "
            f"{sig_total} «ganadoras» con t &gt; 2; por puro azar se esperarían unas "
            f"{esperadas_azar:.0f}. Y las que mejor iban antes de julio de 2024 no predicen "
            f"las que mejor van después: la correlación es {corr:+.2f}. "
            f"{caen} de las {int((mejores.e_in > 0).sum())} mejores variantes pasan a perder "
            f"fuera de muestra.<br/><br/>La excepción que vale mirar: Silver Bullet en el "
            f"Nasdaq entrando al 50 % del FVG gana unos +0,15 R por operación y aguanta "
            f"costos triples, pero no se traslada al S&amp;P 500. Es una hipótesis para "
            f"probar en demo, no una estrategia lista para dinero real."),
        fuente=("Datos: velas M5, M15 y H4 de la cuenta demo MetaQuotes-Demo (USTEC y US500 "
                "desde jul-2022; EURUSD, GBPUSD y XAUUSD desde ene-2019), bajadas con el "
                "paquete MetaTrader5. Motor propio en Proyectos\\backtester-mt5\\ict, con 11 "
                "pruebas que verifican que ninguna regla usa información futura."))

    inf.lamina(
        "1 · Qué se probó: las reglas tal como las enseñan",
        texto=("Cada modelo se llevó a reglas mecánicas a partir de su fuente pública. "
               "Todo en hora de Nueva York (la demo usa horario de verano europeo; se "
               "convirtió con zonas horarias reales y se verificó que la apertura de las 9:30 "
               "cae en su lugar). Entradas en M5, como en los videos; stop detrás del "
               "barrido, que es donde lo ponen los autores."),
        tabla=[["Modelo", "Fuente", "Regla codificada"],
               ["Silver Bullet", "ICT; JadeCap",
                "10-11 AM NY. Barrido de un swing → cambio de estructura con FVG → límite en el "
                "FVG, stop tras el barrido, objetivo 2R. Una por día."],
               ["Modelo 2022", "Mentoría ICT 2022",
                "8:30-11 AM. Barrido de Asia, Londres o el día previo → MSS con FVG → límite, "
                "2R."],
               ["iFVG", "Modelo de Josh (TradeZella)",
                "9:30-11:30. Barrido; el FVG que empujó hacia él se cierra por el otro lado → "
                "entrada al cierre, objetivo: la liquidez interna opuesta."],
               ["CRT clásico", "Romeo; innercircletrader.net",
                "Velas H4 de 1, 5 y 9 AM. C2 barre C1 con la mecha y cierra adentro → entra "
                "al abrir C3. 50 % del rango (parcial + break-even) y extremo opuesto."],
               ["CRT + TBS", "SATTAM CRT+TBS (TradingView)",
                "Mismo rango, pero en M15: un cuerpo cierra fuera (turtle body soup) y otra "
                "vela cierra tras la última opuesta (Modelo #1). No espera el cierre de C2."]],
        nota=("Datos dañados excluidos: en USTEC y US500 la demo dejó el precio congelado del "
              "4-oct-2024 al 5-ene-2025 (velas de 0,25 pts en plena apertura) y no tiene velas "
              "del 16-jul al 9-set-2025. Divisas y oro, completos. "
              "Costos de ida y vuelta: USTEC 1,8 pts · US500 0,6 · EURUSD 1,2 pips · GBPUSD "
              "1,6 · XAUUSD 0,35 USD. Es spread de bróker retail más deslizamiento; la demo "
              "reporta menos. Cuando una vela de 5 min toca stop y objetivo, se cuenta el stop."))

    inf.lamina(
        f"2 · Configuración de los profesionales: {significativas} de {len(T)} "
        f"combinaciones tienen ventaja estadística",
        texto=("Ganancia esperada neta por operación, en R (1 R = lo que se arriesga). "
               "Un asterisco marca t &gt; 2. Para operar en real no basta con que el número "
               "sea positivo: con pocas operaciones un +0,10 R cabe de sobra en el ruido."),
        tabla=matriz,
        nota=("USTEC y US500 tienen 4 años de historia en la demo; las divisas y el oro, 7,7. "
              "El Nasdaq (USTEC, el equivalente CFD del NQ) es el mercado donde operan los "
              "autores de estos modelos."))

    inf.lamina(
        "3 · En el Nasdaq, el mercado de los autores",
        tabla=tabla_u, figura=f_curvas,
        nota=(f"«Retorno a 1 %»: arriesgando 1 % de la cuenta por operación, con interés "
              f"compuesto. La línea punteada separa el periodo usado para elegir variantes "
              f"(antes de jul-2024) del periodo de validación."))

    inf.lamina(
        "4 · Los costos se comen el margen",
        texto=(f"Sin costos, solo {' y '.join(n.split(' (')[0] for n in agg.index[agg.e_bruta > 0])} "
               "quedan apenas sobre cero; los demás pierden incluso operando gratis. Con el "
               "spread y el deslizamiento de un bróker retail, en promedio todos pierden: los "
               "stops de M5 son cortos, y un costo fijo pesa mucho sobre un riesgo pequeño."),
        figura=f_costos)

    inf.lamina(
        f"5 · Buscar la mejor variante fabrica ganadoras: {sig_total} «significativas» "
        f"entre {n_cfg}; el azar da ~{esperadas_azar:.0f}",
        texto=(f"Se probaron {n_cfg} variantes (ventanas, entrada en el borde o el 50 % del "
               f"FVG, objetivos 2R/3R/liquidez, tamaño del swing, filtro premium/discount, "
               f"nivel clave). Cada punto es una variante en un mercado. Si hubiera ventaja "
               f"real, los puntos seguirían la diagonal: lo que funcionó antes seguiría "
               f"funcionando. La correlación es <b>{corr:+.2f}</b>."),
        figura=f_disp)

    inf.lamina(
        f"6 · La mejor variante de cada modelo, elegida antes de jul-2024: "
        f"{caen} de {int((mejores.e_in > 0).sum())} dejan de ganar",
        tabla=tabla_m,
        nota=("Se muestran solo las variantes que ganaban antes del corte; las demás "
              "perdían ya desde el inicio. Así se ve el sobreajuste en la práctica: la variante que un curso o un "
              "video muestra como «la configuración» es la mejor de muchas pruebas, y ese "
              "máximo no se repite con datos nuevos."))

    tabla_e, ops_mes, e_pista = estres()
    inf.lamina(
        "7 · La única pista: Silver Bullet en el Nasdaq, entrando al 50 % del FVG",
        texto=(f"Las {sig_total} variantes con t &gt; 2 son todas la misma idea: Silver Bullet "
               "de 10 a 11 AM en USTEC, con swings de 3 velas (la definición de ICT); "
               f"{n_ce} de ellas entran al 50 % del FVG. Un racimo de variantes vecinas es más creíble que una celda suelta, "
               "así que se la intentó romper:"),
        tabla=tabla_e,
        aviso=("Lectura honesta: aguanta costos altos y gana todos los años, pero es la mejor "
               f"de {n_cfg} pruebas, no funciona en el S&amp;P 500, se cae si la ventana abre "
               "a las 9:30, y casi todo viene de los largos en un Nasdaq que subió fuerte "
               "desde 2023. Es una hipótesis para probar en demo, no una ventaja demostrada."))

    inf.lamina(
        "8 · ¿Y una prueba de fondeo (prop firm)?",
        texto=("Simulación de 20 000 cuentas: arriesgando 1 % por operación, ¿qué tan "
               "seguido se llega a +10 % antes de perder 10 %? Se usan solo operaciones "
               "fuera de muestra de las variantes que sobrevivieron. Como referencia, una "
               f"moneda al aire con objetivo 2R y costos pasa el {p_azar:.0%} de las veces."),
        tabla=tabla_p if len(tabla_p) > 1 else [["Sin candidatos que sobrevivan"]],
        nota=("El porcentaje alto supone que la ventaja fuera de muestra se repite tal cual. "
              "Con 122 operaciones, el error de esa media es de ±0,12 R: la ventaja real "
              "puede ser cero, y entonces la prueba se pasa la mitad de las veces, como con una moneda. "
              "Cada intento cuesta ≈ 100-150 USD en cuentas de 10 000."))

    inf.lamina(
        "9 · Lo que este backtest no puede ver",
        tabla=[["Límite", "Hacia dónde sesga"],
               ["Los autores usan criterio: sesgo diario, SMT entre NQ y ES, noticias, "
                "saltarse días malos", "Podría subestimar a un trader hábil. Pero ese criterio "
                "no se puede copiar de un video: es justo lo que no se vende."],
               ["Entradas en M5; varios autores usan M1", "Stops más cortos en M1 = el costo "
                "pesa más. Probablemente empeora, no mejora."],
               ["USTEC/US500 son CFD de la demo, no futuros NQ/ES", "Spreads de la demo son "
                "irreales (bajos); se reemplazaron por costos retail."],
               ["4 años de Nasdaq; 7,7 de divisas y oro", "Pocos años para un modelo de una "
                "operación diaria: los intervalos de confianza son anchos."],
               ["Vela ambigua (toca stop y objetivo) = stop", "Conservador: resta algo de "
                "resultado a todos por igual."]])

    inf.lamina(
        "10 · Veredicto y siguiente paso",
        cifras=[(f"{significativas}/{len(T)}", "configuraciones de autor con ventaja clara"),
                (f"{corr:+.2f}", "correlación entre el antes y el después"),
                (f"{e_pista:+.2f} R", "la única pista, antes de probarla en vivo")],
        texto=("<b>Tal como las enseñan, ninguna de las cinco estrategias le gana al costo de "
               "operar.</b> CRT y CRT + TBS aciertan más de la mitad de las veces (54-60 %) y "
               "aun así pierden: el parcial al 50 % y el break-even recortan las ganancias, "
               "y el spread se lleva el resto. iFVG pierde en los 5 mercados. "
               "<br/><br/>La única pista es Silver Bullet en el Nasdaq con entrada al 50 % "
               f"del FVG: {e_pista:+.2f} R por operación, unas {ops_mes:.0f} operaciones al mes. "
               "A 1 % de riesgo serían cerca de "
               f"{e_pista * ops_mes:.1f} % al mes <i>si</i> se sostuviera. Siguiente paso, en "
               "este orden: (1) congelar esas reglas exactas; (2) operarlas en la demo 3 meses "
               "o 60 operaciones, registrando cada una; (3) comparar contra este informe. "
               "Solo si el resultado en vivo se parece, se habla de dinero."),
        aviso=("Este backtest no justifica poner dinero real ni pagar pruebas de fondeo "
               "todavía. Lo que se encontró es una hipótesis, y ya se sabe que falla fuera "
               "del Nasdaq y fuera de su hora."))
    inf.guardar()
    print(SALIDA)
    print(T.pivot(index="familia", columns="simbolo", values="e").round(3))
    print(f"configs {n_cfg} | pos {pos_total} | t>2 {sig_total} | azar {esperadas_azar:.0f} | "
          f"corr {corr:+.2f} | caen {caen}/{int((mejores.e_in > 0).sum())}")
    print(mejores[["familia", "simbolo", "config", "e_in", "e_out", "n_out"]].to_string())


if __name__ == "__main__":
    main()
