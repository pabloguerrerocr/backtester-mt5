"""Pruebas del asesor. No necesitan el terminal MT5 ni conexion a internet.

Uso (desde la raiz del repo):  python -m unittest asesor.pruebas_asesor -v
"""
from __future__ import annotations

import io
import itertools
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout

import numpy as np
import pandas as pd

from asesor import diario, noticias, riesgo, senales
from asesor import __main__ as cli


def serie(precios, freq="h") -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=len(precios), freq=freq)
    p = np.asarray(precios, dtype=float)
    return pd.DataFrame({"open": p, "high": p, "low": p, "close": p,
                         "tick_volume": 1, "spread": 0}, index=idx)


# --------------------------------------------------------------------------
class PruebasBinarias(unittest.TestCase):
    def test_equilibrio_con_pago_85(self):
        self.assertAlmostEqual(riesgo.equilibrio_binaria(0.85), 10 / 18.5, places=12)

    def test_en_el_equilibrio_la_expectativa_y_kelly_son_cero(self):
        p = riesgo.equilibrio_binaria(0.85)
        self.assertAlmostEqual(riesgo.expectativa_binaria(p, 0.85), 0.0, places=12)
        self.assertAlmostEqual(riesgo.kelly_binaria(p, 0.85), 0.0, places=12)

    def test_sin_ventaja_el_monto_es_cero(self):
        self.assertEqual(riesgo.monto_binaria(1000, 0.50, 0.85), 0.0)

    def test_monto_respeta_el_tope_del_balance(self):
        # p = 0.70 con pago 0.85: Kelly = 0.347, un cuarto = 8.7 %, tope 1 %
        self.assertEqual(riesgo.monto_binaria(1000, 0.70, 0.85, riesgo_max_pct=0.01), 10.0)

    def test_pago_invalido(self):
        with self.assertRaises(ValueError):
            riesgo.equilibrio_binaria(0)


class PruebasLotes(unittest.TestCase):
    def test_eurusd_20_pips_1_por_ciento_de_10000(self):
        # 20 pips = 200 ticks de 0.00001, a 1 USD por tick y lote -> 200 USD por lote
        r = riesgo.lotes_forex(10_000, 0.01, 0.0020, 0.00001, 1.0)
        self.assertAlmostEqual(r.lotes, 0.5)
        self.assertAlmostEqual(r.riesgo_dinero, 100.0)

    def test_redondea_hacia_abajo(self):
        r = riesgo.lotes_forex(10_000, 0.01, 0.0030, 0.00001, 1.0)  # 0.333... lotes
        self.assertAlmostEqual(r.lotes, 0.33)
        self.assertLessEqual(r.riesgo_dinero, r.riesgo_objetivo)

    def test_cuenta_chica_no_alcanza_el_lote_minimo(self):
        r = riesgo.lotes_forex(164.59, 0.01, 0.0020, 0.00001, 1.0)
        self.assertEqual(r.lotes, 0.0)
        self.assertIn("lote minimo", r.aviso)


class PruebasRachas(unittest.TestCase):
    def fuerza_bruta(self, p, n, largo):
        total = 0.0
        for combo in itertools.product([0, 1], repeat=n):   # 1 = gana
            racha = peor = 0
            for x in combo:
                racha = 0 if x else racha + 1
                peor = max(peor, racha)
            if peor >= largo:
                g = sum(combo)
                total += p ** g * (1 - p) ** (n - g)
        return total

    def test_coincide_con_enumerar_todas_las_secuencias(self):
        for p, n, largo in [(0.5, 10, 3), (0.54, 12, 4), (0.6, 8, 2), (0.3, 9, 5)]:
            self.assertAlmostEqual(riesgo.prob_racha_perdedora(p, n, largo),
                                   self.fuerza_bruta(p, n, largo), places=12)

    def test_casos_limite(self):
        self.assertEqual(riesgo.prob_racha_perdedora(0.5, 10, 0), 1.0)
        self.assertAlmostEqual(riesgo.prob_racha_perdedora(0.5, 1, 1), 0.5)
        self.assertAlmostEqual(riesgo.prob_racha_perdedora(1.0, 100, 1), 0.0)


# --------------------------------------------------------------------------
class PruebasDiario(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.ruta = os.path.join(self.dir.name, "sub", "diario.csv")

    def tearDown(self):
        self.dir.cleanup()

    def anotar(self, resultado, monto=10, **kw):
        return diario.registrar(self.ruta, mercado="iqoption", simbolo="cafe-otc",
                                direccion="sube", monto=monto, resultado=resultado,
                                pago=kw.pop("pago", 0.85), **kw)

    def test_pnl_de_binaria_se_calcula_solo(self):
        self.assertAlmostEqual(self.anotar("gana")["pnl"], 8.5)
        self.assertAlmostEqual(self.anotar("pierde")["pnl"], -10.0)
        self.assertAlmostEqual(self.anotar("empate")["pnl"], 0.0)

    def test_solo_agrega_filas_y_una_sola_cabecera(self):
        self.anotar("gana")
        with open(self.ruta, encoding="utf-8") as f:
            primera = f.read()
        self.anotar("pierde")
        with open(self.ruta, encoding="utf-8") as f:
            despues = f.read()
        self.assertTrue(despues.startswith(primera))
        self.assertEqual(despues.count("fecha,mercado"), 1)
        self.assertEqual(len(diario.cargar(self.ruta)), 2)

    def test_valida_entradas(self):
        with self.assertRaises(ValueError):
            self.anotar("talvez")
        with self.assertRaises(ValueError):
            diario.registrar(self.ruta, mercado="mt5", simbolo="EURUSD", direccion="compra",
                             monto=10, resultado="gana")  # sin pnl ni pago

    def test_wilson_valores_conocidos(self):
        bajo, alto = diario.wilson(50, 100)
        self.assertAlmostEqual(bajo, 0.4038, places=4)
        self.assertAlmostEqual(alto, 0.5962, places=4)
        self.assertEqual(diario.wilson(0, 0), (0.0, 1.0))

    def test_muestra_chica_no_concluye(self):
        for _ in range(10):
            self.anotar("gana")
        st = diario.estadisticas(diario.cargar(self.ruta))
        self.assertEqual(st.acierto, 1.0)
        self.assertIn("insuficiente", st.veredicto)

    def test_55_por_ciento_en_100_ops_no_prueba_ventaja(self):
        # 55 % supera el equilibrio de 54.05 %, pero el IC es [45 %, 64 %]
        for r in ["gana"] * 55 + ["pierde"] * 45:
            self.anotar(r)
        st = diario.estadisticas(diario.cargar(self.ruta))
        self.assertAlmostEqual(st.acierto, 0.55)
        self.assertIn("sin evidencia", st.veredicto)

    def test_veredicto_pierde_y_ventaja(self):
        for r in ["gana"] * 35 + ["pierde"] * 65:
            self.anotar(r)
        self.assertIn("pierde dinero", diario.estadisticas(diario.cargar(self.ruta)).veredicto)
        os.remove(self.ruta)
        for r in ["gana"] * 140 + ["pierde"] * 60:
            self.anotar(r)
        self.assertIn("ventaja probable", diario.estadisticas(diario.cargar(self.ruta)).veredicto)

    def test_drawdown_y_racha(self):
        for r in ["gana", "pierde", "pierde", "pierde", "gana"]:
            self.anotar(r)
        st = diario.estadisticas(diario.cargar(self.ruta))
        # +8.5 -> -1.5 -> -11.5 -> -21.5 : caida de 30 desde el pico de 8.5
        self.assertAlmostEqual(st.max_drawdown, -30.0)
        self.assertEqual(st.peor_racha, 3)

    def test_empates_no_cuentan_en_el_acierto(self):
        for r in ["gana", "empate", "pierde"]:
            self.anotar(r)
        st = diario.estadisticas(diario.cargar(self.ruta))
        self.assertEqual(st.n, 2)
        self.assertAlmostEqual(st.acierto, 0.5)


class PruebasFreno(unittest.TestCase):
    HOY = pd.Timestamp("2026-10-22 23:00")

    def diario_de(self, resultados, pnl):
        return pd.DataFrame({"fecha": [self.HOY] * len(resultados),
                             "resultado": resultados, "pnl": pnl})

    def test_tres_perdidas_seguidas_bloquean(self):
        d = self.diario_de(["gana", "pierde", "pierde", "pierde"], [8.5, -1, -1, -1])
        f = riesgo.evaluar_freno(d, 1000, riesgo.ReglasFreno(), hoy=self.HOY)
        self.assertTrue(f.bloqueado)
        self.assertEqual(f.perdidas_seguidas, 3)

    def test_una_ganancia_corta_la_racha(self):
        d = self.diario_de(["pierde", "pierde", "gana", "pierde"], [-1, -1, 1, -1])
        f = riesgo.evaluar_freno(d, 1000, riesgo.ReglasFreno(), hoy=self.HOY)
        self.assertFalse(f.bloqueado)

    def test_stop_diario(self):
        d = self.diario_de(["pierde", "gana"], [-10, 4])   # -6 de 164.59 = 3.6 %
        f = riesgo.evaluar_freno(d, 164.59, riesgo.ReglasFreno(), hoy=self.HOY)
        self.assertTrue(f.bloqueado)
        self.assertIn("stop diario", f.motivos[0])

    def test_ayer_no_cuenta(self):
        d = self.diario_de(["pierde"] * 5, [-10] * 5)
        d["fecha"] = self.HOY - pd.Timedelta(days=1)
        self.assertFalse(riesgo.evaluar_freno(d, 164.59, riesgo.ReglasFreno(),
                                              hoy=self.HOY).bloqueado)


# --------------------------------------------------------------------------
class PruebasSenales(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(7)
        self.df = serie(100 * np.exp(np.cumsum(rng.normal(0, 0.002, 1500))))

    def test_senal_sale_de_la_ultima_vela_cerrada(self):
        fn, nombre = senales.resolver_estrategia("ma:20:50")
        s = senales.evaluar(self.df, "EURUSD", "H1", nombre, fn, 0.0001)
        esperado = float(self.df["close"].rolling(20).mean().iloc[-1]
                         > self.df["close"].rolling(50).mean().iloc[-1])
        self.assertEqual(s.actual, esperado)
        self.assertEqual(s.vela, self.df.index[-1])
        self.assertEqual(s.precio, self.df["close"].iloc[-1])

    def test_truncar_no_cambia_senales_pasadas(self):
        for spec in ["ma:20:50", "rsi:14:30:70"]:
            fn, nombre = senales.resolver_estrategia(spec)
            for corte in (300, 800, 1200):
                a = senales.evaluar(self.df.iloc[:corte], "X", "H1", nombre, fn, 0.0)
                completa = fn(self.df)
                self.assertEqual(a.actual, completa.iloc[corte - 1], spec)

    def test_paseo_aleatorio_no_tiene_ventaja(self):
        fn, nombre = senales.resolver_estrategia("ma:20:50")
        s = senales.evaluar(self.df, "X", "H1", nombre, fn, 0.0001)
        self.assertFalse(s.evidencia.tiene_ventaja)
        self.assertIn("SIN VENTAJA PROBADA", s.texto())

    def test_ventaja_exige_ganarle_a_comprar_y_mantener(self):
        e = senales.Evidencia(retorno=0.10, retorno_bh=0.20, sharpe=1.0, max_drawdown=-0.05,
                              operaciones=10, t=3.0, velas=1000)
        self.assertFalse(e.tiene_ventaja)
        e.retorno_bh = 0.05
        self.assertTrue(e.tiene_ventaja)

    def test_estrategia_desconocida(self):
        with self.assertRaises(ValueError):
            senales.resolver_estrategia("gringo")


# --------------------------------------------------------------------------
class PruebasNoticias(unittest.TestCase):
    CRUDO = [
        {"title": "Non-Farm Employment Change", "country": "USD",
         "date": "2026-10-23T08:30:00-04:00", "impact": "High", "forecast": "150K",
         "previous": "142K"},
        {"title": "German Ifo", "country": "EUR", "date": "2026-10-23T04:00:00-04:00",
         "impact": "Medium", "forecast": "", "previous": ""},
        {"title": "roto", "country": "JPY", "date": "no-es-fecha", "impact": "High"},
    ]

    def test_parsea_y_descarta_fechas_rotas(self):
        ev = noticias.parsear(self.CRUDO)
        self.assertEqual(len(ev), 2)
        self.assertEqual(ev[-1].hora_utc, pd.Timestamp("2026-10-23 12:30", tz="UTC"))

    def test_ventana_alrededor_del_dato(self):
        ev = noticias.parsear(self.CRUDO)
        cerca = pd.Timestamp("2026-10-23 12:10", tz="UTC")
        lejos = pd.Timestamp("2026-10-23 10:00", tz="UTC")
        self.assertEqual(len(noticias.en_ventana(ev, "EURUSD", cerca)), 1)
        self.assertEqual(noticias.en_ventana(ev, "EURUSD", lejos), [])
        self.assertEqual(noticias.en_ventana(ev, "GBPJPY", cerca), [])

    def test_monedas(self):
        self.assertEqual(noticias.monedas_de("EURUSD"), ["EUR", "USD"])
        self.assertEqual(noticias.monedas_de("USTEC"), ["USD"])
        self.assertEqual(noticias.monedas_de("CAFE-OTC"), [])

    def test_hora_local_costa_rica(self):
        ev = noticias.parsear(self.CRUDO)
        self.assertIn("06:30", ev[-1].texto())   # 12:30 UTC = 6:30 en Costa Rica


# --------------------------------------------------------------------------
class PruebasCLI(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.cfg = os.path.join(self.dir.name, "config.json")
        with open(os.path.join(os.path.dirname(__file__), "config.ejemplo.json"),
                  encoding="utf-8") as f:
            base = json.load(f)
        base["diario"] = os.path.join(self.dir.name, "diario.csv")
        with open(self.cfg, "w", encoding="utf-8") as f:
            json.dump(base, f)

    def tearDown(self):
        self.dir.cleanup()

    def correr(self, *args) -> str:
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(cli.main(["--config", self.cfg, *args]), 0)
        return buf.getvalue()

    def test_binaria_con_acierto_manual(self):
        out = self.correr("binaria", "--acierto", "0.5")
        self.assertIn("54.05%", out)
        self.assertIn("Monto sugerido: 0", out)

    def test_registrar_hasta_el_freno_y_stats(self):
        for _ in range(3):
            out = self.correr("registrar", "--mercado", "iqoption", "--simbolo", "CAFE-OTC",
                              "--direccion", "sube", "--monto", "2", "--resultado", "pierde",
                              "--pago", "0.85", "--senal", "GRINGO")
        self.assertIn("FRENO ACTIVO", out)
        out = self.correr("stats", "--senal", "GRINGO")
        self.assertIn("Operaciones: 3", out)
        self.assertIn("insuficiente", out)

    def test_lotes_sin_terminal(self):
        out = self.correr("lotes", "--stop", "0.0020", "--tick-size", "0.00001",
                          "--tick-value", "1")
        self.assertIn("No hay tamano valido", out)   # 164.59 USD no alcanza 0.01 lotes


if __name__ == "__main__":
    unittest.main()
