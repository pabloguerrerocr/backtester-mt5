"""Backtester sobre datos reales del terminal MetaTrader 5.

Uso:
    python main.py                          # EURUSD H1, 5000 velas
    python main.py --simbolo XAUUSD --tf D1 --velas 2000
    python main.py --sin-autopsia
"""
from __future__ import annotations

import argparse
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import datos
import estrategias
import metricas
import motor


def parsear() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Backtester MT5")
    p.add_argument("--simbolo", default="EURUSD")
    p.add_argument("--tf", default="H1", choices=list(datos.TIMEFRAMES))
    p.add_argument("--velas", type=int, default=5000)
    p.add_argument("--comision-bp", type=float, default=0.0,
                   help="comision en puntos basicos, sobre el spread observado")
    p.add_argument("--piso-bp", type=float, default=0.5,
                   help="costo minimo por operacion; el spread de la demo suele ser 0")
    p.add_argument("--sin-autopsia", action="store_true",
                   help="omite el analisis de sobreajuste y sensibilidad a costos")
    return p.parse_args()


def autopsia(df, costo, tf) -> None:
    print("\n=== AUTOPSIA: ¿cuanto del resultado es senal? ===\n")

    print("1. Sensibilidad a los parametros (cruce de medias, retorno total)")
    print("   Si el resultado solo funciona en una celda, es sobreajuste.\n")
    rejilla, mejor = [], None
    lentas = [50, 100, 200]
    print("        " + "".join(f"lenta={l}".rjust(12) for l in lentas))
    for rapida in (5, 10, 20, 50):
        fila = [f"rapida={rapida}".ljust(8)]
        for lenta in lentas:
            if rapida >= lenta:
                fila.append("-".rjust(12))
                continue
            s = estrategias.cruce_medias(df, rapida, lenta)
            r = motor.correr(df, s, costo)
            tot = float(r.equity.iloc[-1] - 1)
            rejilla.append(tot)
            if mejor is None or tot > mejor[0]:
                mejor = (tot, rapida, lenta)
            fila.append(f"{tot * 100:+.2f}%".rjust(12))
        print("   " + "".join(fila))

    positivas = sum(1 for x in rejilla if x > 0)
    print(f"\n   Combinaciones probadas: {len(rejilla)} | con retorno positivo: {positivas}")
    print(f"   Mejor celda: MA{mejor[1]}/{mejor[2]} con {mejor[0] * 100:+.2f}%")
    print("   Esa 'mejor' es el numero que se suele mostrar. Es el maximo de "
          f"{len(rejilla)} intentos,\n   no una prediccion: elegir el maximo de una rejilla "
          "garantiza un resultado bonito.")
    if positivas <= len(rejilla) / 2:
        print("   Advertencia: la mayoria de las combinaciones pierde dinero.")

    print("\n2. Sensibilidad a los costos (MA20/50, retorno total)")
    print("   Muchas estrategias solo sobreviven si se ignora el costo de operar.\n")
    s = estrategias.cruce_medias(df, 20, 50)
    for etiqueta, c in [("sin costo", 0.0), ("costo aplicado", costo),
                        ("costo x2", costo * 2), ("costo x5", costo * 5)]:
        r = motor.correr(df, s, c)
        print(f"   {etiqueta.ljust(14)} costo={c * 10_000:5.2f} bp -> "
              f"{float(r.equity.iloc[-1] - 1) * 100:+.2f}%  ({r.operaciones} ops)")

    print("\n3. Sesgos que este backtest SI controla")
    print("   - Look-ahead: la senal de la barra t se ejecuta en t+1 (motor.correr, retraso=1).")
    print("   - Vela en formacion: se descarta la ultima vela sin cerrar (datos.velas).")
    print("   - Costos: se descuentan en cada cambio de posicion, con un piso obligatorio\n"
          "     porque el spread del broker llega en cero gran parte del tiempo.")
    print("\n   Lo que NO controla: slippage real, horario de ejecucion, swap por "
          "mantener\n   posiciones de un dia a otro, y que los datos de una cuenta demo "
          "no son\n   los de una cuenta real.")


def main() -> int:
    args = parsear()

    try:
        datos.conectar()
    except datos.ErrorMT5 as e:
        print(f"Error: {e}\nAbri MetaTrader 5 e inicia sesion antes de correr esto.")
        return 1

    try:
        cuenta = datos.info_cuenta()
        print(f"Terminal MT5 conectado | cuenta {cuenta['login']} @ {cuenta['servidor']} "
              f"| balance {cuenta['balance']:,.2f} {cuenta['moneda']}")

        df = datos.velas(args.simbolo, args.tf, args.velas)
        punto = datos.punto(args.simbolo)
    except datos.ErrorMT5 as e:
        print(f"Error: {e}")
        return 1
    finally:
        datos.desconectar()

    minimo = 60  # la media lenta de 50 mas el retraso de ejecucion
    if len(df) < minimo:
        print(f"Error: {len(df)} velas no alcanzan. Se necesitan al menos {minimo}.")
        return 1

    c = motor.costo_desde_spread(df, punto, args.comision_bp, args.piso_bp)
    costo = c.fraccion
    print(f"\n{args.simbolo} {args.tf} | {len(df)} velas cerradas | "
          f"{df.index[0]:%Y-%m-%d} a {df.index[-1]:%Y-%m-%d} (hora del broker)")
    print(f"Costo por operacion: {c.bp:.2f} bp "
          f"(spread historico {c.spread_bp:.2f} bp + {args.comision_bp:.1f} bp comision)")
    if c.pct_velas_sin_spread > 0.1:
        print(f"  Aviso: el {c.pct_velas_sin_spread:.0%} de las velas trae spread = 0. "
              f"El dato del broker subestima el costo real.")
    if c.piso_aplicado:
        print(f"  Se aplica el piso de {args.piso_bp:.2f} bp en lugar del spread historico.")
    print()

    filas = {}
    for nombre, fn in [("MA 20/50", lambda d: estrategias.cruce_medias(d, 20, 50)),
                       ("RSI 14 30/70", estrategias.rsi),
                       ("Buy & hold", estrategias.comprar_y_mantener)]:
        senal = fn(df)
        # comprar y mantener es una sola entrada: se mide sin costo, como referencia
        r = motor.correr(df, senal, 0.0 if nombre == "Buy & hold" else costo)
        m = metricas.resumen(r.equity, r.retornos, args.tf)
        m["operaciones"] = r.operaciones
        filas[nombre] = m

    print(metricas.tabla(filas))

    bh = filas["Buy & hold"]["retorno_total"]
    ganan = [n for n, m in filas.items() if n != "Buy & hold" and m["retorno_total"] > bh]
    print()
    if ganan:
        print(f"  Le ganan a no hacer nada: {', '.join(ganan)}")
    else:
        print("  Ninguna estrategia le gana a comprar y mantener.")

    if not args.sin_autopsia:
        autopsia(df, costo, args.tf)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
