"""Pruebas del backtester.

Dos bloques:
  - Unitarias: invariantes con series sinteticas de resultado calculable a mano.
  - Integracion: requieren el terminal MT5 abierto. Se saltan si no esta.

Uso:  python -m unittest pruebas -v
"""
from __future__ import annotations

import datetime as dt
import math
import sys
import unittest

import numpy as np
import pandas as pd

import estrategias
import metricas
import motor

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def serie(precios: list[float], spread: float = 1.0) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=len(precios), freq="h")
    return pd.DataFrame(
        {"open": precios, "high": precios, "low": precios, "close": precios,
         "tick_volume": 1, "spread": spread},
        index=idx,
    )


# --------------------------------------------------------------------------
# Motor
# --------------------------------------------------------------------------
class PruebasMotor(unittest.TestCase):
    """Precios 100 -> 110 -> 99 -> 108.9  =>  retornos +10%, -10%, +10%."""

    def setUp(self):
        self.df = serie([100.0, 110.0, 99.0, 108.9])
        self.senal = pd.Series([1.0, 0.0, 1.0, 0.0], index=self.df.index)

    def test_ejecucion_retrasada_una_barra(self):
        """La senal de t se aplica al retorno de t+1, no al de t."""
        r = motor.correr(self.df, self.senal, costo_por_operacion=0.0)
        # pos = [nan, 1, 0, 1] tras el shift; retornos validos = barras 1, 2, 3
        self.assertEqual(list(r.posicion), [1.0, 0.0, 1.0])
        np.testing.assert_allclose(r.retornos.values, [0.10, 0.0, 0.10], atol=1e-12)
        np.testing.assert_allclose(r.equity.values, [1.10, 1.10, 1.21], atol=1e-12)

    def test_sin_retraso_es_look_ahead_y_se_rechaza(self):
        with self.assertRaises(ValueError):
            motor.correr(self.df, self.senal, retraso=0)

    def test_senal_constante_replica_buy_and_hold(self):
        """Invariante: estar siempre dentro, sin costo, == comprar y mantener."""
        s = estrategias.comprar_y_mantener(self.df)
        r = motor.correr(self.df, s, costo_por_operacion=0.0)
        # la primera barra se pierde por el shift, se compara el tramo comun
        pd.testing.assert_series_equal(
            r.equity / r.equity.iloc[0],
            r.equity_bh / r.equity_bh.iloc[0],
            check_names=False,
        )

    def test_costos_se_descuentan_en_cada_cambio(self):
        c = 0.001
        r = motor.correr(self.df, self.senal, costo_por_operacion=c)
        self.assertEqual(r.operaciones, 3)               # entrar, salir, entrar
        self.assertAlmostEqual(r.costo_total, 3 * c, places=12)
        np.testing.assert_allclose(r.retornos.values, [0.099, -0.001, 0.099], atol=1e-12)

    def test_mas_costo_nunca_mejora_el_resultado(self):
        anterior = math.inf
        for c in (0.0, 0.0005, 0.001, 0.005):
            final = float(motor.correr(self.df, self.senal, c).equity.iloc[-1])
            self.assertLessEqual(final, anterior + 1e-12)
            anterior = final

    def test_estar_fuera_del_mercado_deja_el_capital_quieto(self):
        fuera = pd.Series(0.0, index=self.df.index)
        r = motor.correr(self.df, fuera, costo_por_operacion=0.01)
        np.testing.assert_allclose(r.equity.values, 1.0, atol=1e-12)
        self.assertEqual(r.operaciones, 0)
        self.assertEqual(r.costo_total, 0.0)

    def test_warmup_con_nan_no_contamina(self):
        """Una senal con NaN al inicio no genera retornos en esas barras."""
        s = self.senal.copy()
        s.iloc[:2] = np.nan
        r = motor.correr(self.df, s, 0.0)
        self.assertEqual(len(r.retornos), 1)             # solo la ultima barra
        self.assertFalse(r.retornos.isna().any())

    def test_costo_desde_spread(self):
        df = serie([100.0] * 10, spread=2.0)
        c = motor.costo_desde_spread(df, punto=0.01, comision_bp=5.0, piso_bp=0.0)
        # spread 2 puntos * 0.01 = 0.02 sobre precio 100 = 2 bp, mas 5 bp = 7 bp
        self.assertAlmostEqual(c.bp, 7.0, places=9)
        self.assertAlmostEqual(c.spread_bp, 2.0, places=9)
        self.assertFalse(c.piso_aplicado)

    def test_spread_cero_no_significa_operar_gratis(self):
        """El historico de la demo trae spread = 0; sin piso el costo seria nulo."""
        df = serie([100.0] * 10, spread=0.0)
        c = motor.costo_desde_spread(df, punto=0.01, piso_bp=0.5)
        self.assertAlmostEqual(c.spread_bp, 0.0, places=12)
        self.assertAlmostEqual(c.bp, 0.5, places=9)
        self.assertTrue(c.piso_aplicado)
        self.assertAlmostEqual(c.pct_velas_sin_spread, 1.0, places=12)

    def test_el_piso_no_pisa_un_spread_mayor(self):
        df = serie([100.0] * 10, spread=10.0)      # 10 puntos * 0.01 / 100 = 10 bp
        c = motor.costo_desde_spread(df, punto=0.01, piso_bp=0.5)
        self.assertAlmostEqual(c.bp, 10.0, places=9)
        self.assertFalse(c.piso_aplicado)


# --------------------------------------------------------------------------
# Metricas
# --------------------------------------------------------------------------
class PruebasMetricas(unittest.TestCase):
    def test_max_drawdown_calculado_a_mano(self):
        eq = pd.Series([1.0, 1.2, 0.6, 0.9])
        self.assertAlmostEqual(metricas.max_drawdown(eq), -0.5, places=12)

    def test_drawdown_de_curva_siempre_creciente_es_cero(self):
        eq = pd.Series([1.0, 1.1, 1.2, 1.5])
        self.assertAlmostEqual(metricas.max_drawdown(eq), 0.0, places=12)

    def test_cagr_de_duplicar_en_un_anio(self):
        ret = pd.Series([2.0 ** (1 / 252) - 1] * 252)
        eq = (1 + ret).cumprod()
        m = metricas.resumen(eq, ret, "D1")
        self.assertAlmostEqual(m["anios"], 1.0, places=9)
        self.assertAlmostEqual(m["cagr"], 1.0, places=6)
        self.assertAlmostEqual(m["retorno_total"], 1.0, places=6)

    def test_sharpe_sin_volatilidad_es_nan_y_no_un_numero_absurdo(self):
        """std() de una serie constante da ~1e-19, no 0: sin tolerancia da 7e16."""
        ret = pd.Series([0.001] * 100)
        m = metricas.resumen((1 + ret).cumprod(), ret, "D1")
        self.assertTrue(math.isnan(m["sharpe"]), f"sharpe = {m['sharpe']}")
        self.assertAlmostEqual(m["vol_anual"], 0.0, places=12)

    def test_sharpe_negativo_cuando_se_pierde(self):
        rng = np.random.default_rng(7)
        ret = pd.Series(rng.normal(-0.001, 0.01, 500))
        m = metricas.resumen((1 + ret).cumprod(), ret, "D1")
        self.assertLess(m["sharpe"], 0)
        self.assertLess(m["retorno_total"], 0)

    def test_tabla_tolera_valores_faltantes(self):
        salida = metricas.tabla({"X": {"retorno_total": 0.1, "sharpe": float("nan")}})
        self.assertIn("n/d", salida)
        self.assertIn("+10.00%", salida)


# --------------------------------------------------------------------------
# Estrategias
# --------------------------------------------------------------------------
class PruebasEstrategias(unittest.TestCase):
    def test_cruce_medias_warmup_y_valores_binarios(self):
        rng = np.random.default_rng(1)
        df = serie(list(100 + np.cumsum(rng.normal(0, 1, 300))))
        s = estrategias.cruce_medias(df, 20, 50)
        self.assertTrue(s.iloc[:49].isna().all())        # sin media lenta no hay senal
        self.assertFalse(s.iloc[49:].isna().any())
        self.assertTrue(set(s.dropna().unique()) <= {0.0, 1.0})

    def test_cruce_medias_en_tendencia_alcista_se_queda_dentro(self):
        df = serie([100 + i for i in range(200)])
        s = estrategias.cruce_medias(df, 20, 50)
        self.assertEqual(s.dropna().sum(), len(s.dropna()))

    def test_cruce_medias_en_tendencia_bajista_se_queda_fuera(self):
        df = serie([300 - i for i in range(200)])
        s = estrategias.cruce_medias(df, 20, 50)
        self.assertEqual(s.dropna().sum(), 0.0)

    def test_rsi_en_subida_continua_no_compra(self):
        """Subida monotona => RSI 100 => sobrecompra => fuera del mercado."""
        df = serie([100 + i for i in range(120)])
        s = estrategias.rsi(df)
        self.assertEqual(s.dropna().sum(), 0.0)

    def test_rsi_en_caida_continua_compra(self):
        df = serie([300 - i for i in range(120)])
        s = estrategias.rsi(df)
        self.assertEqual(s.dropna().sum(), len(s.dropna()))

    def test_rsi_valores_binarios_y_sin_nan_tras_warmup(self):
        rng = np.random.default_rng(3)
        df = serie(list(100 + np.cumsum(rng.normal(0, 1, 400))))
        s = estrategias.rsi(df)
        self.assertTrue(s.iloc[:15].isna().all())
        self.assertFalse(s.iloc[20:].isna().any())
        self.assertTrue(set(s.dropna().unique()) <= {0.0, 1.0})

    def test_ninguna_estrategia_usa_el_futuro(self):
        """Truncar la serie no puede cambiar las senales ya emitidas."""
        rng = np.random.default_rng(11)
        precios = list(100 + np.cumsum(rng.normal(0, 1, 400)))
        completa, truncada = serie(precios), serie(precios[:300])
        for nombre, fn in estrategias.CATALOGO.items():
            with self.subTest(estrategia=nombre):
                a = fn(completa).iloc[:300]
                b = fn(truncada)
                pd.testing.assert_series_equal(a, b, check_names=False)


# --------------------------------------------------------------------------
# Integracion contra el terminal
# --------------------------------------------------------------------------
def terminal_disponible() -> bool:
    try:
        import datos
        datos.conectar()
        datos.desconectar()
        return True
    except Exception:
        return False


@unittest.skipUnless(terminal_disponible(), "terminal MT5 no disponible")
class PruebasTerminal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import datos
        cls.datos = datos
        datos.conectar()

    @classmethod
    def tearDownClass(cls):
        cls.datos.desconectar()

    def test_timeframe_invalido(self):
        with self.assertRaises(ValueError):
            self.datos.velas("EURUSD", "M3", 10)

    def test_simbolo_inexistente(self):
        with self.assertRaises(self.datos.ErrorMT5):
            self.datos.velas("NOEXISTE123", "H1", 10)

    def test_descarta_la_vela_en_formacion(self):
        """El indice viene en hora del broker (UTC+3 en esta demo), no en UTC."""
        df = self.datos.velas("EURUSD", "H1", 200)
        ahora = self.datos.hora_servidor("EURUSD")
        self.assertLessEqual(len(df), 200)
        # la ultima vela ya cerro: su apertura mas una hora no supera el reloj del broker
        self.assertLessEqual(df.index[-1] + dt.timedelta(hours=1), ahora)

    def test_la_hora_del_broker_no_es_utc(self):
        """Documenta el desfase: comparar el indice contra utcnow da falsos errores."""
        desfase = self.datos.hora_servidor("EURUSD") - pd.Timestamp.utcnow().tz_localize(None)
        self.assertLess(abs(desfase), dt.timedelta(hours=13))

    def test_velas_bien_formadas(self):
        df = self.datos.velas("EURUSD", "D1", 300)
        self.assertFalse(df.isna().any().any())
        self.assertTrue(df.index.is_monotonic_increasing)
        self.assertTrue(df.index.is_unique)
        self.assertTrue((df["high"] >= df["low"]).all())
        self.assertTrue((df["high"] >= df["close"]).all())
        self.assertTrue((df["low"] <= df["close"]).all())
        self.assertTrue((df["close"] > 0).all())

    def test_backtest_completo_sobre_varios_mercados(self):
        for simbolo, tf, n in [("EURUSD", "H1", 1000), ("XAUUSD", "D1", 500),
                               ("USDJPY", "H4", 800)]:
            with self.subTest(simbolo=simbolo, tf=tf):
                df = self.datos.velas(simbolo, tf, n)
                c = motor.costo_desde_spread(df, self.datos.punto(simbolo))
                self.assertGreater(c.fraccion, 0)      # nunca operar gratis
                r = motor.correr(df, estrategias.cruce_medias(df), c.fraccion)
                m = metricas.resumen(r.equity, r.retornos, tf)
                self.assertTrue(np.isfinite(m["sharpe"]))
                self.assertLessEqual(m["max_drawdown"], 0)
                self.assertGreater(m["vol_anual"], 0)
                self.assertTrue((r.equity > 0).all())

    def test_motor_vectorizado_igual_a_simulacion_barra_a_barra(self):
        """Contraste independiente: un bucle ingenuo debe dar la misma curva.

        Si el motor vectorizado se desalineara un indice, esta prueba lo detecta.
        """
        df = self.datos.velas("EURUSD", "H1", 1500)
        senal = estrategias.cruce_medias(df, 20, 50)
        costo = 0.00005
        r = motor.correr(df, senal, costo)

        precios = df["close"].to_numpy()
        senales = senal.to_numpy()
        capital, pos_previa, ops, inicio = 1.0, 0.0, 0, None
        curva = []
        for i in range(1, len(precios)):
            pos = senales[i - 1]                       # decidida con la barra anterior
            if np.isnan(pos):
                continue
            if inicio is None:
                inicio, pos_previa = i, 0.0
            ret = precios[i] / precios[i - 1] - 1
            cambio = abs(pos - pos_previa)
            if cambio > 0:
                ops += 1
            capital *= 1 + pos * ret - cambio * costo
            curva.append(capital)
            pos_previa = pos

        self.assertEqual(len(curva), len(r.equity))
        self.assertEqual(ops, r.operaciones)
        np.testing.assert_allclose(np.array(curva), r.equity.to_numpy(), rtol=1e-12)

    def test_metricas_contra_calculo_independiente(self):
        df = self.datos.velas("XAUUSD", "D1", 600)
        r = motor.correr(df, estrategias.cruce_medias(df), 0.00005)
        m = metricas.resumen(r.equity, r.retornos, "D1")

        ret = r.retornos.to_numpy()
        eq = r.equity.to_numpy()
        self.assertAlmostEqual(m["retorno_total"], eq[-1] - 1, places=12)
        self.assertAlmostEqual(m["vol_anual"], ret.std(ddof=1) * np.sqrt(252), places=12)
        self.assertAlmostEqual(
            m["sharpe"], ret.mean() / ret.std(ddof=1) * np.sqrt(252), places=10)
        peor = min(eq[i] / max(eq[: i + 1]) - 1 for i in range(len(eq)))
        self.assertAlmostEqual(m["max_drawdown"], peor, places=12)

    def test_pocas_velas_no_alcanzan_para_la_media_lenta(self):
        """Caso incomodo: menos datos que el warmup => no hay backtest."""
        df = self.datos.velas("EURUSD", "D1", 30)
        s = estrategias.cruce_medias(df, 20, 50)
        self.assertTrue(s.isna().all())
        r = motor.correr(df, s, 0.0)
        self.assertEqual(len(r.retornos), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
