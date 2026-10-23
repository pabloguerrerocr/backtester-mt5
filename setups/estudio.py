"""Estudio de setups con EMA 20/50/200, RSI 14 y ATR 14 sobre el historial de MT5.

Cada operacion: entrada a la apertura de la vela siguiente a la senal, stop a
1.5 x ATR, objetivo a R x stop, salida por tiempo a las `MAX_VELAS` velas. Si en
una misma vela se tocan stop y objetivo, cuenta como stop (pesimista). El spread
de cada vela se descuenta en la entrada. Una posicion a la vez por combinacion.

Seleccion honesta: las combinaciones se ordenan en el 70 % mas viejo del
historial (dentro de muestra) y solo se aceptan si tambien ganan en el 30 % mas
reciente (fuera de muestra), que no se uso para elegir.

    python -m setups.estudio            # estudio completo + senales actuales
"""
from __future__ import annotations

import itertools
import sys

import numpy as np
import pandas as pd

SIMBOLOS = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"]
TIMEFRAMES = {"M15": 200_000, "H1": 60_000}
RS = [1.0, 1.5, 2.0]
STOP_ATR = 1.5
MAX_VELAS = 24
CORTE = 0.70
SESION_UTC = (7, 16)      # Londres + Nueva York: 1 a.m. a 10 a.m. en Costa Rica


# --------------------------------------------------------------------------
# Indicadores
# --------------------------------------------------------------------------
def ema(c: pd.Series, n: int) -> pd.Series:
    return c.ewm(span=n, adjust=False).mean()


def rsi(c: pd.Series, n: int = 14) -> pd.Series:
    d = c.diff()
    g = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    p = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + g / p.replace(0, np.nan))


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


# --------------------------------------------------------------------------
# Setups: +1 compra, -1 venta, 0 nada, evaluado al cierre de cada vela
# --------------------------------------------------------------------------
def setups(df: pd.DataFrame) -> dict[str, pd.Series]:
    c = df["close"]
    e20, e50, e200, r = ema(c, 20), ema(c, 50), ema(c, 200), rsi(c)
    alcista = (e20 > e50) & (c > e200)
    bajista = (e20 < e50) & (c < e200)
    rp = r.shift(1)

    def s(largo, corto):
        return pd.Series(np.where(largo, 1, np.where(corto, -1, 0)), index=df.index)

    cruce_arriba = (e20 > e50) & (e20.shift(1) <= e50.shift(1))
    cruce_abajo = (e20 < e50) & (e20.shift(1) >= e50.shift(1))
    max20, min20 = df["high"].rolling(20).max().shift(1), df["low"].rolling(20).min().shift(1)
    return {
        # retroceso en tendencia: RSI cae bajo 40 y vuelve a subir (y espejo)
        "retroceso": s(alcista & (rp < 40) & (r >= 40), bajista & (rp > 60) & (r <= 60)),
        # cruce de EMA 20/50 a favor de la EMA 200
        "cruce_ema": s(cruce_arriba & (c > e200), cruce_abajo & (c < e200)),
        # RSI 30/70 de vuelta, solo a favor de la tendencia
        "rsi_tendencia": s(alcista & (rp < 30) & (r >= 30), bajista & (rp > 70) & (r <= 70)),
        # ruptura del maximo/minimo de 20 velas a favor de la tendencia
        "ruptura": s(alcista & (c > max20), bajista & (c < min20)),
    }


# --------------------------------------------------------------------------
# Simulacion por operacion
# --------------------------------------------------------------------------
def simular(df: pd.DataFrame, senal: pd.Series, a: pd.Series, r_obj: float) -> pd.DataFrame:
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    sp = df["spread_precio"].to_numpy()
    s, av = senal.to_numpy(), a.to_numpy()
    n = len(c)
    filas, libre = [], 0
    for t in np.flatnonzero(s):
        if t < libre or t + 1 >= n or not np.isfinite(av[t]) or av[t] <= 0:
            continue
        d = int(s[t])
        ent = o[t + 1] + d * sp[t + 1]            # se paga el spread al entrar
        riesgo = STOP_ATR * av[t]
        stop, obj = ent - d * riesgo, ent + d * r_obj * riesgo
        fin = min(t + 1 + MAX_VELAS, n)
        r, salida = None, fin - 1
        for k in range(t + 1, fin):
            toca_stop = l[k] <= stop if d > 0 else h[k] >= stop
            toca_obj = h[k] >= obj if d > 0 else l[k] <= obj
            if toca_stop:
                r, salida = -1.0, k
                break
            if toca_obj:
                r, salida = r_obj, k
                break
        if r is None:
            r = d * (c[salida] - ent) / riesgo
        filas.append((df.index[t], d, r))
        libre = salida + 1
    return pd.DataFrame(filas, columns=["senal", "dir", "r"])


def metricas(ops: pd.DataFrame) -> dict:
    n = len(ops)
    if n < 2:
        return {"n": n, "acierto": np.nan, "r_medio": np.nan, "t": np.nan, "pf": np.nan}
    r = ops["r"]
    ganado, perdido = r[r > 0].sum(), -r[r < 0].sum()
    return {
        "n": n,
        "acierto": float((r > 0).mean()),
        "r_medio": float(r.mean()),
        "t": float(r.mean() / r.std(ddof=1) * np.sqrt(n)) if r.std(ddof=1) > 0 else np.nan,
        "pf": float(ganado / perdido) if perdido > 0 else np.inf,
    }


# --------------------------------------------------------------------------
# Datos de MT5. Hora del broker MetaQuotes = Europe/Athens (UTC+2/+3 con DST).
# --------------------------------------------------------------------------
def velas(simbolo: str, tf: str, n: int) -> pd.DataFrame:
    import MetaTrader5 as mt5
    mt5.symbol_select(simbolo, True)
    crudo = mt5.copy_rates_from_pos(simbolo, getattr(mt5, f"TIMEFRAME_{tf}"), 0, n + 1)
    if crudo is None or len(crudo) == 0:
        raise RuntimeError(f"sin velas de {simbolo} {tf}: {mt5.last_error()}")
    df = pd.DataFrame(crudo)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df = df.set_index("time").iloc[:-1]                       # la ultima vela sigue abierta
    df["spread_precio"] = df["spread"] * mt5.symbol_info(simbolo).point
    utc = df.index.tz_localize("Europe/Athens", ambiguous="NaT", nonexistent="NaT").tz_convert("UTC")
    df["hora_utc"] = utc.hour
    return df[utc.notna()]


def estudio() -> pd.DataFrame:
    filas = []
    for sim, (tf, n) in itertools.product(SIMBOLOS, TIMEFRAMES.items()):
        df = velas(sim, tf, n)
        a = atr(df)
        en_sesion = df["hora_utc"].between(SESION_UTC[0], SESION_UTC[1] - 1)
        corte = df.index[int(len(df) * CORTE)]
        print(f"{sim} {tf}: {len(df):,} velas, {df.index[0]:%Y-%m-%d} a {df.index[-1]:%Y-%m-%d}, corte {corte:%Y-%m-%d}",
              file=sys.stderr)
        for nombre, sen in setups(df).items():
            for sesion, r_obj in itertools.product((False, True), RS):
                s = sen.where(en_sesion, 0) if sesion else sen
                ops = simular(df, s, a, r_obj)
                dentro = metricas(ops[ops["senal"] < corte])
                fuera = metricas(ops[ops["senal"] >= corte])
                filas.append({"simbolo": sim, "tf": tf, "setup": nombre, "sesion": sesion, "R": r_obj,
                              **{f"in_{k}": v for k, v in dentro.items()},
                              **{f"out_{k}": v for k, v in fuera.items()}})
    return pd.DataFrame(filas)


def senal_actual(sim: str, tf: str, setup: str, sesion: bool, r_obj: float, ventana: int = 3) -> str:
    """Senal en las ultimas `ventana` velas cerradas, con entrada, stop y objetivo."""
    df = velas(sim, tf, 1000)
    a = atr(df)
    s = setups(df)[setup]
    if sesion:
        s = s.where(df["hora_utc"].between(SESION_UTC[0], SESION_UTC[1] - 1), 0)
    recientes = s.iloc[-ventana:]
    nombre = f"{sim} {tf} {setup}{' sesion' if sesion else ''} {r_obj:g}R"
    if not (recientes != 0).any():
        return f"{nombre}: sin senal (ultima vela {df.index[-1]:%Y-%m-%d %H:%M} hora broker)"
    t = recientes[recientes != 0].index[-1]
    d = int(s[t])
    ent = df["close"].iloc[-1]
    riesgo = STOP_ATR * a[t]
    return (f"{nombre}: {'COMPRA' if d > 0 else 'VENTA'} (vela {t:%Y-%m-%d %H:%M}) | entrada ~{ent:.5g} | "
            f"stop {ent - d * riesgo:.5g} | objetivo {ent + d * r_obj * riesgo:.5g} | "
            f"salida por tiempo en {MAX_VELAS} velas")


if __name__ == "__main__":
    import MetaTrader5 as mt5
    if not mt5.initialize(timeout=20000):
        sys.exit(f"MT5 no responde: {mt5.last_error()}")
    try:
        tabla = estudio()
        tabla.to_csv("setups/resultados.csv", index=False)
        pd.set_option("display.width", 220)
        cols = ["simbolo", "tf", "setup", "sesion", "R", "in_n", "in_acierto", "in_r_medio", "in_t",
                "out_n", "out_acierto", "out_r_medio", "out_t", "out_pf"]
        print("\n== Top 15 por acierto dentro de muestra (lo que 'se ve' en un backtest) ==")
        print(tabla.sort_values("in_acierto", ascending=False)[cols].head(15).round(3).to_string(index=False))
        print("\n== Top 15 por R medio dentro de muestra, con n >= 100 ==")
        top = tabla[tabla["in_n"] >= 100].sort_values("in_r_medio", ascending=False)
        print(top[cols].head(15).round(3).to_string(index=False))
        ok = tabla[(tabla["in_n"] >= 100) & (tabla["in_t"] > 2) & (tabla["out_n"] >= 30)
                   & (tabla["out_r_medio"] > 0) & (tabla["out_t"] > 2)]
        print(f"\n== Sobreviven (t > 2 dentro Y t > 2 fuera de muestra): {len(ok)} de {len(tabla)} ==")
        print(ok[cols].round(3).to_string(index=False) if len(ok) else "ninguna")
        for _, f in ok.iterrows():
            print(senal_actual(f["simbolo"], f["tf"], f["setup"], f["sesion"], f["R"]))
    finally:
        mt5.shutdown()
