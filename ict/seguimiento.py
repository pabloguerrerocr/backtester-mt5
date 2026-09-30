"""Prueba en vivo de Silver Bullet en el Nasdaq: baja velas nuevas, aplica las reglas
congeladas y actualiza el PDF de seguimiento.

    python seguimiento.py

Corre solo cada día hábil (Programador de tareas, "JP - Silver Bullet en vivo").
Si la máquina estuvo apagada, al correr de nuevo se pone al día con el historial.

Por qué es paper trading y no órdenes en la demo: en MetaQuotes-Demo el USTEC
tiene trading deshabilitado (trade_mode = 0, solo cotiza). Las reglas se
aplican a su precio real, vela a vela, con el mismo simulador conservador del
backtest. Las operaciones se anotan una sola vez y nunca se reescriben.
"""
from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "..", "_informe"))
from informe import Informe  # noqa: E402

import modelos as M  # noqa: E402
import reglas_congeladas as C  # noqa: E402
from smc import a_nueva_york, cargar, dias_danados  # noqa: E402

VIVO = os.path.join(AQUI, "vivo")
REGISTRO = os.path.join(VIVO, "operaciones_vivo.csv")
SALIDA = os.path.join(AQUI, "Prueba-en-vivo-Silver-Bullet.pdf")
AZUL, GRIS, TINTA2 = "#2a78d6", "#9a9993", "#52514e"


def actualizar_datos() -> str:
    """Agrega las velas nuevas a datos/USTEC_M5.csv sin tocar las viejas."""
    import MetaTrader5 as mt5
    if not mt5.initialize():
        return f"sin terminal MT5: {mt5.last_error()}"
    try:
        ruta = os.path.join(AQUI, "datos", f"{C.SIMBOLO}_M5.csv")
        viejo = pd.read_csv(ruta, parse_dates=["time"])
        mt5.symbol_select(C.SIMBOLO, True)
        # Pedir por posición y no por rango de fechas: copy_rates_range solo devuelve
        # lo que el terminal ya tiene guardado (se quedó en el 24-set aunque había
        # velas nuevas); copy_rates_from_pos obliga a sincronizar.
        dias = (pd.Timestamp.now() - viejo["time"].iloc[-1]).days + 4
        crudo = mt5.copy_rates_from_pos(C.SIMBOLO, mt5.TIMEFRAME_M5, 0,
                                        min(99_000, dias * 288 + 500))
    finally:
        mt5.shutdown()
    if crudo is None or not len(crudo):
        return "sin velas nuevas"
    nuevo = pd.DataFrame(crudo)
    nuevo["time"] = pd.to_datetime(nuevo["time"], unit="s")
    nuevo = nuevo[["time", "open", "high", "low", "close", "tick_volume", "spread"]]
    # la última vela puede estar en formación: se descarta
    nuevo = nuevo.iloc[:-1]
    todo = (pd.concat([viejo[viejo["time"] < nuevo["time"].iloc[0]], nuevo])
            .drop_duplicates("time").sort_values("time"))
    todo.to_csv(ruta, index=False)
    return f"{len(todo) - len(viejo)} velas nuevas, hasta {todo['time'].iloc[-1]}"


def operaciones_nuevas() -> pd.DataFrame:
    m5 = cargar(C.SIMBOLO, "M5")
    ops = M.barrido_mss_fvg(m5, C.COSTO, **C.REGLAS)
    ny = a_nueva_york(m5.index)
    ultima_ny = ny[-1]
    filas = []
    for o in ops:
        entrada_ny = ny[o.t_entrada]
        if entrada_ny < pd.Timestamp(C.INICIO_NY):
            continue
        # solo días cerrados: el simulador cierra por tiempo a las 16:00 NY
        if ultima_ny < entrada_ny.normalize() + pd.Timedelta(hours=16):
            continue
        filas.append(dict(entrada_ny=entrada_ny, salida_ny=ny[o.t_salida],
                          direccion="largo" if o.direccion > 0 else "corto",
                          entrada=round(o.entrada, 2), stop=round(o.sl, 2),
                          objetivo=round(o.tp, 2), r=round(o.r, 4), motivo=o.motivo,
                          visto_en=dt.datetime.now().strftime("%Y-%m-%d %H:%M")))
    return pd.DataFrame(filas)


def registrar(nuevas: pd.DataFrame) -> pd.DataFrame:
    os.makedirs(VIVO, exist_ok=True)
    if os.path.exists(REGISTRO):
        reg = pd.read_csv(REGISTRO, parse_dates=["entrada_ny", "salida_ny"])
    else:
        reg = pd.DataFrame(columns=nuevas.columns if len(nuevas) else
                           ["entrada_ny", "salida_ny", "direccion", "entrada", "stop",
                            "objetivo", "r", "motivo", "visto_en"])
    if len(nuevas):
        ya = set(pd.to_datetime(reg["entrada_ny"]))
        nuevas = nuevas[~nuevas["entrada_ny"].isin(ya)]
        reg = pd.concat([reg, nuevas], ignore_index=True)   # nunca se reescribe lo anotado
    reg = reg.sort_values("entrada_ny")
    reg.to_csv(REGISTRO, index=False)
    return reg


def estado(reg: pd.DataFrame) -> tuple[str, str]:
    n = len(reg)
    if n == 0:
        return "EN ESPERA", "Todavía no hay operaciones cerradas desde el inicio."
    cum = reg["r"].sum()
    piso = C.BACKTEST_E * n - C.Z * C.BACKTEST_DE * np.sqrt(n)
    if n >= C.MIN_OPS_PARA_DETENER and cum < piso:
        return "DETENER", (f"El acumulado ({cum:+.1f} R) cayó bajo el piso de la banda "
                           f"({piso:+.1f} R): el resultado en vivo no es compatible con el "
                           "backtest. La prueba termina aquí.")
    if n >= C.META_OPS:
        if reg["r"].mean() > 0:
            return "PASA", (f"{n} operaciones con {reg['r'].mean():+.3f} R de promedio y dentro "
                            "de la banda. Recién ahora tiene sentido hablar de dinero.")
        return "NO PASA", (f"{n} operaciones y el promedio es {reg['r'].mean():+.3f} R. "
                           "No hay ventaja en vivo.")
    if n < C.MIN_OPS_PARA_DETENER:
        return "MUY PRONTO", (f"{n} de {C.META_OPS} operaciones. Con menos de "
                              f"{C.MIN_OPS_PARA_DETENER} el resultado es puro ruido: no se "
                              "juzga todavía.")
    return "SEGUIR", (f"{n} de {C.META_OPS} operaciones, dentro de la banda del backtest.")


def figura(reg: pd.DataFrame) -> str:
    os.makedirs(os.path.join(VIVO, "figuras"), exist_ok=True)
    ruta = os.path.join(VIVO, "figuras", "acumulado.png")
    n_max = max(C.META_OPS, len(reg))
    x = np.arange(0, n_max + 1)
    esperado = C.BACKTEST_E * x
    banda = C.Z * C.BACKTEST_DE * np.sqrt(x)
    fig, ax = plt.subplots(figsize=(10, 3.3))
    ax.fill_between(x, esperado - banda, esperado + banda, color="#e7eef9", lw=0,
                    label=f"banda del backtest (±{C.Z:g} desv.)")
    ax.plot(x, esperado, color=GRIS, lw=1, ls="--", label=f"esperado: {C.BACKTEST_E:+.2f} R/op")
    if len(reg):
        ax.plot(np.arange(0, len(reg) + 1), np.r_[0, reg["r"].cumsum()], color=AZUL, lw=2,
                marker="o", ms=3.5, label="en vivo")
    ax.axhline(0, color=TINTA2, lw=0.8)
    ax.axvline(C.META_OPS, color=GRIS, lw=0.8, ls=":")
    ax.set_xlabel("Operaciones"); ax.set_ylabel("R acumulados")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.grid(color="#ecebe6", lw=0.7); ax.set_axisbelow(True)
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    fig.tight_layout(); fig.savefig(ruta, dpi=200); plt.close(fig)
    return ruta


def pdf(reg: pd.DataFrame, nota_datos: str):
    veredicto, detalle = estado(reg)
    n = len(reg)
    malos = [d for d in dias_danados(C.SIMBOLO) if d >= pd.Timestamp(C.INICIO_NY)]
    inf = Informe("Prueba en vivo: Silver Bullet en el Nasdaq",
                  f"Reglas congeladas el {C.CONGELADA} · paper trading sobre el precio de "
                  f"{C.SIMBOLO} en la demo de MT5 · actualizado "
                  f"{dt.datetime.now():%d-%m-%Y %H:%M}", SALIDA)
    inf.portada(resumen=f"<b>{veredicto}.</b> {detalle}",
                fuente=(f"Datos: {nota_datos}. Días con precio congelado en la demo desde el "
                        f"inicio (excluidos): {len(malos)}."))
    inf.lamina(
        f"1 · {n} de {C.META_OPS} operaciones",
        cifras=[(f"{n}", "operaciones cerradas"),
                (f"{reg['r'].sum():+.1f} R" if n else "—", "acumulado en vivo"),
                (f"{reg['r'].mean():+.2f} R" if n else "—",
                 f"promedio (backtest: {C.BACKTEST_E:+.2f})"),
                (f"{(reg['r'] > 0).mean():.0%}" if n else "—", "operaciones ganadoras")],
        figura=figura(reg),
        nota=("Si la línea azul cae bajo la banda con 20 operaciones o más, la prueba se "
              "detiene. A 1 % de riesgo por operación, 1 R = 1 % de la cuenta."))
    ult = reg.tail(14).iloc[::-1]
    tabla = [["Entrada (hora NY)", "Lado", "Entrada", "Stop", "Objetivo", "Salida", "R"]]
    for _, x in ult.iterrows():
        tabla.append([f"{pd.Timestamp(x.entrada_ny):%a %d-%m %H:%M}", x.direccion,
                      f"{x.entrada:,.2f}", f"{x.stop:,.2f}", f"{x.objetivo:,.2f}", x.motivo,
                      f"{x.r:+.2f}"])
    inf.lamina("2 · Las operaciones (más recientes primero)",
               tabla=tabla if n else [["Sin operaciones todavía"]],
               nota="La tabla completa está en vivo\\operaciones_vivo.csv.")
    inf.lamina(
        "3 · Las reglas, congeladas",
        tabla=[["Pieza", "Regla"],
               ["Mercado y hora", f"{C.SIMBOLO}, velas de 5 min, solo de 10:00 a 11:00 de Nueva York"],
               ["Liquidez", "el precio toma un swing de 3 velas aún intacto (hasta 1 h antes)"],
               ["Confirmación", "una vela cierra más allá del último swing opuesto y el "
                                "movimiento deja un FVG"],
               ["Entrada", "orden límite al 50 % del FVG; vence a las 11:00"],
               ["Stop y objetivo", "stop tras el extremo del barrido; objetivo 2R; cierre "
                                   "forzado a las 16:00"],
               ["Frecuencia", "máximo una operación por día"],
               ["Costo", f"{C.COSTO} puntos por operación"],
               ["Decisión", f"meta {C.META_OPS} operaciones; pasa si el promedio es positivo "
                            f"y nunca cayó bajo la banda; se detiene si cae bajo la banda "
                            f"con {C.MIN_OPS_PARA_DETENER}+ operaciones"]],
        aviso=("No se cambia ninguna regla a mitad de la prueba, aunque venga una mala racha. "
               "Cambiarla es volver a ajustar mirando los resultados."))
    inf.guardar()
    return veredicto


def main():
    try:
        nota = actualizar_datos()
    except Exception as e:     # sin terminal: igual se regenera con lo que haya
        nota = f"no se pudieron bajar velas ({e})"
    reg = registrar(operaciones_nuevas())
    try:
        veredicto = pdf(reg, nota)
    except PermissionError:
        # el PDF estaba abierto en el visor: el registro ya quedó guardado, y el PDF
        # se regenera en la próxima corrida
        veredicto = "PDF abierto, no se pudo regenerar (se reintenta mañana)"
    print(f"{dt.datetime.now():%Y-%m-%d %H:%M} | {nota} | {len(reg)} ops | {veredicto}")
    # copia al índice del escritorio, si existe en esta máquina (no es parte del repo)
    escritorio = os.path.join(AQUI, "..", "..", "escritorio.py")
    if os.path.exists(escritorio):
        subprocess.run([sys.executable, escritorio], capture_output=True)


if __name__ == "__main__":
    main()
