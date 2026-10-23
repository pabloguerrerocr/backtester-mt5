"""Asesor de trading local: senales con evidencia, riesgo, diario y noticias.

Solo alerta. No envia ordenes a ningun broker.

    python -m asesor escanear [--ia]
    python -m asesor vigilar --cada 15 [--ia]
    python -m asesor registrar --mercado iqoption --simbolo CAFE-OTC --direccion sube --monto 10 --resultado pierde --pago 0.85
    python -m asesor stats [--mercado iqoption] [--senal GRINGO]
    python -m asesor binaria [--pago 0.85] [--acierto 0.55]
    python -m asesor lotes --simbolo EURUSD --stop 0.0020
    python -m asesor noticias [--simbolo EURUSD] [--horas 24]
    python -m asesor estado

Binarias (pares reales de MT5, para operar a mano en IQ Option):
    python -m asesor binarias-prueba              # backtest de las reglas por vencimiento
    python -m asesor binarias [--ia]              # senales SUBE/BAJA en vivo + registro en papel
    python -m asesor stats --papel                # como le fue a cada senal en papel
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd

from . import alertas, binarias, config, diario, ia, noticias, riesgo


# --------------------------------------------------------------------------
# Piezas compartidas
# --------------------------------------------------------------------------
def _reglas(cfg) -> riesgo.ReglasFreno:
    return riesgo.ReglasFreno(**cfg["freno"])


def _freno(cfg) -> riesgo.EstadoFreno:
    return riesgo.evaluar_freno(diario.cargar(cfg["diario"]), cfg["balance"], _reglas(cfg))


def _eventos() -> tuple[list[noticias.Evento], str]:
    try:
        return noticias.descargar(), ""
    except Exception as e:
        return [], f"calendario no disponible ({type(e).__name__}): se opera SIN filtro de noticias"


def _stats_dict(st: diario.Estadisticas) -> dict:
    return {"operaciones": st.n, "acierto": st.acierto, "ic95": [st.ic_bajo, st.ic_alto],
            "pnl_total": st.pnl_total, "equilibrio_binarias": st.equilibrio,
            "veredicto": st.veredicto}


# --------------------------------------------------------------------------
# Comandos
# --------------------------------------------------------------------------
def escanear(cfg, usar_ia: bool, solo_cambios: bool = False, memoria: dict | None = None) -> int:
    from . import senales
    import motor

    freno = _freno(cfg)
    eventos, aviso_cal = _eventos()
    ahora = pd.Timestamp.now(tz="UTC")
    st = diario.estadisticas(diario.cargar(cfg["diario"]), filtro_mercado="mt5")

    if freno.bloqueado:
        alertas.enviar("FRENO ACTIVO — no abras operaciones nuevas hoy:\n  - "
                       + "\n  - ".join(freno.motivos))
    if aviso_cal:
        print(f"  Aviso: {aviso_cal}")

    for item in cfg["vigilar"]:
        sim, tf = item["simbolo"], item["tf"]
        try:
            df, punto = senales.velas_mt5(sim, tf, cfg["velas_historial"])
        except Exception as e:
            print(f"[{sim} {tf}] sin datos: {e}")
            continue
        costo = motor.costo_desde_spread(df, punto, cfg["costo"]["comision_bp"],
                                         cfg["costo"]["piso_bp"]).fraccion
        ventana = noticias.en_ventana(eventos, sim, ahora, cfg["noticias"]["minutos_antes"],
                                      cfg["noticias"]["minutos_despues"])
        for spec in item["estrategias"]:
            fn, nombre = senales.resolver_estrategia(spec)
            try:
                s = senales.evaluar(df, sim, tf, nombre, fn, costo)
            except ValueError as e:
                print(f"[{sim} {tf}] {e}")
                continue

            clave = f"{sim}|{tf}|{nombre}"
            nuevo = memoria is None or memoria.get(clave) != str(s.vela)
            if memoria is not None:
                memoria[clave] = str(s.vela)
            if solo_cambios and not (s.cambio and nuevo):
                continue

            lineas = [s.texto()]
            if s.cambio and not s.evidencia.tiene_ventaja:
                lineas.append("  -> Esta regla no le gano a no hacer nada en el historico. "
                              "Si la queres seguir, que sea en demo y registrada.")
            if ventana:
                lineas.append("  -> NOTICIA EN VENTANA: " + "; ".join(e.texto(cfg["zona_horaria"])
                                                                     for e in ventana))
            if freno.bloqueado and s.cambio:
                lineas.append("  -> Freno activo: no se toma.")

            if usar_ia and s.cambio:
                ctx = {"senal": s.texto(), "evidencia": vars(s.evidencia),
                       "tiene_ventaja": s.evidencia.tiene_ventaja,
                       "diario_mt5": _stats_dict(st),
                       "freno": {"bloqueado": freno.bloqueado, "motivos": freno.motivos},
                       "noticias_en_ventana": [e.texto(cfg["zona_horaria"]) for e in ventana],
                       "balance": cfg["balance"],
                       "riesgo_por_operacion_pct": cfg["riesgo_por_operacion_pct"]}
                texto = ia.explicar(ctx)
                lineas.append("  IA: " + (texto or "no configurada (falta ANTHROPIC_API_KEY "
                                                    "o pip install anthropic)"))
            alertas.enviar("\n".join(lineas))
    return 0


def vigilar(cfg, cada_min: int, usar_ia: bool) -> int:
    print(f"Vigilando {len(cfg['vigilar'])} simbolos cada {cada_min} min. Ctrl+C para salir.")
    memoria: dict = {}
    escanear(cfg, usar_ia=False, memoria=memoria)  # primera pasada: estado actual
    try:
        while True:
            time.sleep(cada_min * 60)
            print(f"--- {pd.Timestamp.now():%H:%M} ---")
            escanear(cfg, usar_ia, solo_cambios=True, memoria=memoria)
    except KeyboardInterrupt:
        print("\nListo.")
    return 0


def cmd_registrar(cfg, a) -> int:
    fila = diario.registrar(cfg["diario"], mercado=a.mercado, simbolo=a.simbolo,
                            direccion=a.direccion, monto=a.monto, resultado=a.resultado,
                            pnl=a.pnl, pago=a.pago, senal=a.senal or "", nota=a.nota or "")
    print(f"Anotado: {fila['fecha']} {fila['simbolo']} {fila['direccion']} "
          f"{fila['resultado']} {fila['pnl']:+.2f}")
    f = _freno(cfg)
    print(f"Hoy: {f.ops_hoy} ops, pnl {f.pnl_hoy:+.2f}, {f.perdidas_seguidas} perdidas seguidas")
    if f.bloqueado:
        alertas.enviar("FRENO ACTIVO — se acabo por hoy:\n  - " + "\n  - ".join(f.motivos))
    return 0


def cmd_stats(cfg, a) -> int:
    ruta = cfg["binarias"]["papel"] if a.papel else cfg["diario"]
    df = diario.cargar(ruta)
    if df.empty:
        print("El registro en papel esta vacio: corre 'python -m asesor binarias'." if a.papel
              else "El diario esta vacio. Registra operaciones con: python -m asesor registrar ...")
        return 0
    if a.papel and not a.senal:
        print("Senales en papel por regla (empates fuera):\n")
        for clave in sorted(df["senal"].dropna().unique()):
            st = diario.estadisticas(df, filtro_senal=clave)
            linea = (f"  {clave:<32} {st.n:>4} ops  acierto "
                     + (f"{st.acierto:6.1%} [{st.ic_bajo:.1%}, {st.ic_alto:.1%}]" if st.n else "  n/d"))
            print(linea)
            print(f"  {'':<32} {st.veredicto}")
        return 0
    st = diario.estadisticas(df, a.mercado, a.senal)
    print(f"Operaciones: {st.n} ({st.ganadas} ganadas, {st.perdidas} perdidas; empates fuera)")
    if st.n:
        print(f"Acierto: {st.acierto:.1%}  IC 95 %: [{st.ic_bajo:.1%}, {st.ic_alto:.1%}]")
    if st.equilibrio is not None:
        print(f"Equilibrio por el pago: {st.equilibrio:.1%}")
    print(f"PnL total: {st.pnl_total:+.2f} | por operacion: {st.expectativa:+.2f}")
    print(f"Max drawdown: {st.max_drawdown:.2f} | peor racha: {st.peor_racha} perdidas")
    print(f"Veredicto: {st.veredicto}")
    return 0


class FuenteMT5:
    """Precio en vivo desde el terminal. Una sola conexion para todo el bucle."""

    def __enter__(self):
        import datos
        self._datos = datos
        datos.conectar()
        return self

    def __exit__(self, *exc):
        self._datos.desconectar()

    def velas(self, simbolo: str, n: int) -> pd.DataFrame:
        return binarias.velas_m1(simbolo, n)

    def precio(self, simbolo: str) -> float:
        return binarias.precio_actual(simbolo)

    def hora_servidor(self, simbolo: str) -> pd.Timestamp:
        return self._datos.hora_servidor(simbolo)


def _clave(simbolo: str, regla: str, vence_seg: int) -> str:
    return f"{simbolo} {regla} {vence_seg}s"


def _fmt_vence(seg: int) -> str:
    return f"{seg // 60} min" if seg % 60 == 0 else f"{seg} s"


def pruebas_binarias(cfg, fuente) -> dict:
    """Backtest de cada (simbolo, regla, vencimiento) del config."""
    b = cfg["binarias"]
    out = {}
    for item in b["vigilar"]:
        sim, vence = item["simbolo"], int(item["vence_seg"])
        try:
            df = fuente.velas(sim, b["velas_m1_historial"])
        except Exception as e:
            print(f"[{sim}] sin velas M1: {e}")
            continue
        for spec in item["reglas"]:
            fn, nombre = binarias.resolver_regla(spec)
            vv = binarias.vence_en_velas(vence)
            out[_clave(sim, nombre, vence)] = (
                binarias.backtest(df, fn(df), vv, b["pago_por_defecto"], nombre) if vv else None)
    return out


def cmd_binarias_prueba(cfg, fuente=None) -> int:
    if fuente is None:
        with FuenteMT5() as f:
            return cmd_binarias_prueba(cfg, f)
    b = cfg["binarias"]
    eq = riesgo.equilibrio_binaria(b["pago_por_defecto"])
    print(f"Backtest en velas de 1 min | pago {b['pago_por_defecto']:.0%} -> equilibrio {eq:.2%}")
    print("Entrada al cierre de la vela de la senal: en vivo vas a entrar segundos tarde.\n")
    for clave, prueba in pruebas_binarias(cfg, fuente).items():
        print(f"  {clave}")
        print("    " + (prueba.resumen() if prueba else
                        "sin historial a menos de 1 min: solo cuenta el registro en papel"))
    return 0


def binarias_vivo(cfg, usar_ia: bool, fuente=None, cada_seg: float = 2.0,
                  reloj=None, dormir=None, max_vueltas: int | None = None) -> int:
    """Bucle de senales SUBE/BAJA. Cada senal se anota sola en papel al vencer."""
    if fuente is None:
        with FuenteMT5() as f:
            return binarias_vivo(cfg, usar_ia, f, cada_seg, reloj, dormir, max_vueltas)
    reloj = reloj or pd.Timestamp.now
    dormir = dormir or time.sleep
    b = cfg["binarias"]
    pago = b["pago_por_defecto"]
    if not b["vigilar"]:
        print("No hay pares en binarias.vigilar del config.")
        return 1

    pruebas = pruebas_binarias(cfg, fuente)
    print("Senales de binarias en vivo (Ctrl+C para salir). Lo que dijo el historico:")
    for clave, p in pruebas.items():
        print(f"  {clave}: " + (p.resumen() if p else "sin historial (< 1 min)"))
    print()

    eventos, aviso = _eventos()
    if aviso:
        print(f"  Aviso: {aviso}")
    eventos_hora = reloj()
    ultima: dict = {}
    cerrado: dict = {}
    pendientes: list[binarias.Pendiente] = []
    vueltas = 0
    try:
        while True:
            ahora = reloj()
            if ahora - eventos_hora > pd.Timedelta(hours=1):
                eventos, _ = _eventos()
                eventos_hora = ahora

            # 1. liquidar en papel las que vencieron
            listas, pendientes = binarias.vencidas(pendientes, ahora)
            for p in listas:
                try:
                    salida = fuente.precio(p.simbolo)
                except Exception as e:
                    print(f"  no se pudo leer {p.simbolo} al vencer: {e}")
                    continue
                fila = binarias.anotar_papel(b["papel"], p, salida, pago,
                                             (ahora - p.vence).total_seconds())
                st = diario.estadisticas(diario.cargar(b["papel"]), filtro_senal=p.regla)
                alertas.enviar(f"RESULTADO {p.texto_direccion} {p.regla}: {fila['resultado'].upper()} "
                               f"(entrada {p.entrada:g}, salida {salida:g}) | en papel: "
                               f"{st.ganadas}/{st.n} = "
                               + (f"{st.acierto:.1%}" if st.n else "n/d")
                               + f" vs {riesgo.equilibrio_binaria(pago):.1%}")

            # 2. senales nuevas al cierre de cada vela de 1 minuto
            freno = _freno(cfg)
            for item in b["vigilar"]:
                sim, vence = item["simbolo"], int(item["vence_seg"])
                try:
                    df = fuente.velas(sim, 300)
                except Exception as e:
                    print(f"[{sim}] sin velas: {e}")
                    continue
                vela = df.index[-1]
                if ultima.get(sim) == vela:
                    continue
                primera = sim not in ultima
                ultima[sim] = vela
                if primera:
                    continue          # al arrancar no se alerta sobre una vela ya vieja
                if binarias.mercado_cerrado(vela, fuente.hora_servidor(sim)):
                    if not cerrado.get(sim):
                        print(f"[{sim}] mercado cerrado: sin senales (en IQ Option solo hay OTC)")
                    cerrado[sim] = True
                    continue
                cerrado[sim] = False
                ventana = noticias.en_ventana(eventos, sim, pd.Timestamp.now(tz="UTC"),
                                              cfg["noticias"]["minutos_antes"],
                                              cfg["noticias"]["minutos_despues"])
                for spec in item["reglas"]:
                    fn, nombre = binarias.resolver_regla(spec)
                    d = int(fn(df).iloc[-1])
                    if d == 0:
                        continue
                    clave = _clave(sim, nombre, vence)
                    entrada = fuente.precio(sim)
                    p = binarias.Pendiente(sim, clave, d, entrada,
                                           ahora + pd.Timedelta(seconds=vence), vela)
                    pendientes.append(p)

                    prueba = pruebas.get(clave)
                    st = diario.estadisticas(diario.cargar(b["papel"]), filtro_senal=clave)
                    lineas = [f"{p.texto_direccion} {sim} | vence {_fmt_vence(vence)} | entrada "
                              f"~{entrada:g} | {ahora:%H:%M:%S} | regla {nombre}",
                              "  Historico: " + (prueba.resumen() if prueba else "sin historial (< 1 min)"),
                              f"  En papel: {st.n} senales" + (f", acierto {st.acierto:.1%} "
                                                              f"[{st.ic_bajo:.1%}, {st.ic_alto:.1%}]"
                                                              if st.n else "")]
                    if not (prueba and prueba.tiene_ventaja):
                        lineas.append("  -> Sin ventaja demostrada: miralo en papel o demo, "
                                      "no con plata real.")
                    if ventana:
                        lineas.append("  -> NOTICIA EN VENTANA: " + "; ".join(
                            e.texto(cfg["zona_horaria"]) for e in ventana))
                    if freno.bloqueado:
                        lineas.append("  -> FRENO ACTIVO hoy: " + "; ".join(freno.motivos))
                    if usar_ia:
                        texto = ia.explicar({
                            "senal": lineas[0], "tipo": "opcion binaria, se opera a mano en IQ Option",
                            "historico": vars(prueba) if prueba else None,
                            "tiene_ventaja": bool(prueba and prueba.tiene_ventaja),
                            "papel": _stats_dict(st), "freno": freno.motivos,
                            "noticias_en_ventana": [e.texto(cfg["zona_horaria"]) for e in ventana],
                            "pago": pago, "balance": cfg["balance"]})
                        lineas.append("  IA: " + (texto or "no configurada"))
                    alertas.enviar("\n".join(lineas))

            vueltas += 1
            if max_vueltas is not None and vueltas >= max_vueltas:
                break
            dormir(cada_seg)
    except KeyboardInterrupt:
        print(f"\nListo. Quedaron {len(pendientes)} senales sin vencer (no se anotan).")
    return 0


def cmd_binaria(cfg, a) -> int:
    pago = a.pago or cfg["binarias"]["pago_por_defecto"]
    eq = riesgo.equilibrio_binaria(pago)
    print(f"Pago {pago:.0%}: ganas {pago:.2f} por cada 1.00 arriesgado, perdes 1.00")
    print(f"Acierto de equilibrio: {eq:.2%}")

    if a.acierto is not None:
        p, origen = a.acierto, "dato manual"
    else:
        st = diario.estadisticas(diario.cargar(cfg["diario"]), "iqoption")
        if st.n == 0:
            print("Sin operaciones de iqoption en el diario. Pasa --acierto o registra operaciones.")
            return 0
        p = st.ic_bajo
        origen = (f"limite inferior del IC de tu diario ({st.n} ops, observado {st.acierto:.1%})")
    e = riesgo.expectativa_binaria(p, pago)
    k = riesgo.kelly_binaria(p, pago)
    monto = riesgo.monto_binaria(cfg["balance"], p, pago, cfg["riesgo_por_operacion_pct"])
    print(f"\nAcierto usado: {p:.2%} ({origen})")
    print(f"Expectativa: {e:+.3f} por cada 1.00  ->  con $10: {e * 10:+.2f} por operacion")
    print(f"Kelly: {k:+.3f}")
    if monto == 0:
        print("Monto sugerido: 0. Con ese acierto la expectativa es negativa: no hay tamano "
              "de posicion que lo arregle.")
    else:
        print(f"Monto sugerido: {monto:.2f} (1/4 de Kelly, tope "
              f"{cfg['riesgo_por_operacion_pct']:.0%} del balance)")
    print("\nRachas que tenes que aguantar con ese acierto:")
    for n, largo in [(100, 6), (100, 8), (300, 8), (300, 10)]:
        print(f"  {largo} perdidas seguidas en {n} ops: "
              f"{riesgo.prob_racha_perdedora(p, n, largo):.0%}")
    return 0


def cmd_lotes(cfg, a) -> int:
    if a.tick_size and a.tick_value:
        ts, tv, paso, mn, mx = a.tick_size, a.tick_value, 0.01, 0.01, 100.0
    else:
        import datos
        import MetaTrader5 as mt5
        datos.conectar()
        try:
            mt5.symbol_select(a.simbolo, True)
            s = mt5.symbol_info(a.simbolo)
            if s is None:
                print(f"simbolo no disponible: {a.simbolo}")
                return 1
            ts, tv = s.trade_tick_size, s.trade_tick_value
            paso, mn, mx = s.volume_step, s.volume_min, s.volume_max
        finally:
            datos.desconectar()
    riesgo_pct = a.riesgo or cfg["riesgo_por_operacion_pct"]
    r = riesgo.lotes_forex(cfg["balance"], riesgo_pct, a.stop, ts, tv, paso, mn, mx)
    print(f"Balance {cfg['balance']:.2f} | riesgo {riesgo_pct:.1%} = {r.riesgo_objetivo:.2f}")
    if r.aviso:
        print(f"No hay tamano valido: {r.aviso}")
    else:
        print(f"Lotes: {r.lotes:g} | si toca el stop perdes {r.riesgo_dinero:.2f}")
    return 0


def cmd_noticias(cfg, a) -> int:
    eventos, aviso = _eventos()
    if aviso:
        print(aviso)
        return 1
    ahora = pd.Timestamp.now(tz="UTC")
    lista = noticias.proximos(eventos, a.simbolo, ahora, a.horas,
                              impactos=("High", "Medium") if a.medio else ("High",))
    print(f"Proximas {a.horas:g} h que mueven {a.simbolo} "
          f"({', '.join(noticias.monedas_de(a.simbolo))}):")
    for e in lista:
        print("  " + e.texto(cfg["zona_horaria"]))
    if not lista:
        print("  nada de alto impacto")
    return 0


def cmd_estado(cfg) -> int:
    f = _freno(cfg)
    print(f"Config: {cfg['_origen']}")
    print(f"Balance: {cfg['balance']:.2f} {cfg['moneda']} | riesgo/op "
          f"{cfg['riesgo_por_operacion_pct']:.1%}")
    print(f"Hoy: {f.ops_hoy} ops, pnl {f.pnl_hoy:+.2f}, {f.perdidas_seguidas} perdidas seguidas")
    print("FRENO ACTIVO: " + "; ".join(f.motivos) if f.bloqueado else "Freno: libre")
    print(f"IA: {'lista' if ia.disponible() else 'no configurada'} | Telegram: "
          f"{'listo' if alertas.telegram_configurado() else 'no configurado'}")
    return 0


# --------------------------------------------------------------------------
def parsear(argv=None):
    p = argparse.ArgumentParser(prog="python -m asesor", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", help="ruta a otro config.json")
    sub = p.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("escanear", help="evalua una vez todos los simbolos del config")
    e.add_argument("--ia", action="store_true")
    v = sub.add_parser("vigilar", help="escanea en bucle y alerta solo cambios de senal")
    v.add_argument("--cada", type=int, default=15, help="minutos entre escaneos")
    v.add_argument("--ia", action="store_true")

    r = sub.add_parser("registrar", help="anota una operacion cerrada en el diario")
    r.add_argument("--mercado", required=True, choices=sorted(diario.MERCADOS))
    r.add_argument("--simbolo", required=True)
    r.add_argument("--direccion", required=True, help="sube/baja, compra/venta")
    r.add_argument("--monto", type=float, required=True)
    r.add_argument("--resultado", required=True, choices=sorted(diario.RESULTADOS))
    r.add_argument("--pnl", type=float, help="ganancia o perdida real (MT5)")
    r.add_argument("--pago", type=float, help="pago de la binaria, 0.85 = 85 %%")
    r.add_argument("--senal", help="que regla o indicador la origino, para medirlo aparte")
    r.add_argument("--nota")

    s = sub.add_parser("stats", help="estadisticas del diario con intervalo de confianza")
    s.add_argument("--mercado", choices=sorted(diario.MERCADOS))
    s.add_argument("--senal")
    s.add_argument("--papel", action="store_true", help="registro en papel de binarias")

    sub.add_parser("binarias-prueba", help="backtest de las reglas de binarias en M1")
    bv = sub.add_parser("binarias", help="senales SUBE/BAJA en vivo + registro en papel")
    bv.add_argument("--ia", action="store_true")
    bv.add_argument("--cada-seg", type=float, default=2.0, help="segundos entre lecturas")

    b = sub.add_parser("binaria", help="equilibrio, expectativa, Kelly y rachas")
    b.add_argument("--pago", type=float)
    b.add_argument("--acierto", type=float, help="si no se pasa, sale del diario")

    lo = sub.add_parser("lotes", help="tamano de posicion para MT5")
    lo.add_argument("--simbolo", default="EURUSD")
    lo.add_argument("--stop", type=float, required=True, help="distancia al stop en precio")
    lo.add_argument("--riesgo", type=float, help="fraccion del balance, 0.01 = 1 %%")
    lo.add_argument("--tick-size", type=float, help="sin terminal: tamano del tick")
    lo.add_argument("--tick-value", type=float, help="sin terminal: valor del tick por lote")

    n = sub.add_parser("noticias", help="calendario de alto impacto")
    n.add_argument("--simbolo", default="EURUSD")
    n.add_argument("--horas", type=float, default=24)
    n.add_argument("--medio", action="store_true", help="incluir impacto medio")

    sub.add_parser("estado", help="freno, config, IA y Telegram")
    return p.parse_args(argv)


def main(argv=None) -> int:
    a = parsear(argv)
    cfg = config.cargar(a.config)
    if a.cmd == "escanear":
        return escanear(cfg, a.ia)
    if a.cmd == "vigilar":
        return vigilar(cfg, a.cada, a.ia)
    if a.cmd == "registrar":
        return cmd_registrar(cfg, a)
    if a.cmd == "stats":
        return cmd_stats(cfg, a)
    if a.cmd == "binaria":
        return cmd_binaria(cfg, a)
    if a.cmd == "binarias-prueba":
        return cmd_binarias_prueba(cfg)
    if a.cmd == "binarias":
        return binarias_vivo(cfg, a.ia, cada_seg=a.cada_seg)
    if a.cmd == "lotes":
        return cmd_lotes(cfg, a)
    if a.cmd == "noticias":
        return cmd_noticias(cfg, a)
    if a.cmd == "estado":
        return cmd_estado(cfg)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
