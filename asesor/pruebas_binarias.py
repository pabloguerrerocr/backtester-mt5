"""Pruebas del modo binarias. Sin terminal MT5: el precio en vivo se simula.

Uso (desde la raiz del repo):  python -m unittest asesor.pruebas_binarias -v
"""
from __future__ import annotations

import io
import json
import os
import re
import tempfile
import unittest
from contextlib import redirect_stdout

import numpy as np
import pandas as pd

from asesor import binarias, config, diario
from asesor import __main__ as cli


def m1(precios, inicio="2026-10-20 10:00") -> pd.DataFrame:
    idx = pd.date_range(inicio, periods=len(precios), freq="min")
    p = np.asarray(precios, dtype=float)
    return pd.DataFrame({"open": p, "high": p, "low": p, "close": p}, index=idx)


def paseo(n=3000, semilla=3) -> pd.DataFrame:
    rng = np.random.default_rng(semilla)
    return m1(1.08 * np.exp(np.cumsum(rng.normal(0, 0.0002, n))))


class PruebasReglas(unittest.TestCase):
    def test_ninguna_regla_mira_el_futuro(self):
        df = paseo()
        for spec in ["rsi:14:30:70", "ma:5:20", "mom:3"]:
            fn, _ = binarias.resolver_regla(spec)
            completa = fn(df)
            for corte in (200, 1000, 2500):
                self.assertTrue(fn(df.iloc[:corte]).equals(completa.iloc[:corte]), spec)

    def test_cruce_de_medias_dispara_una_sola_vez(self):
        df = m1(list(range(40, 10, -1)) + list(range(11, 60)))   # baja y despues sube
        s = binarias.cruce_medias(df, 3, 8)
        self.assertEqual(int((s == 1).sum()), 1)
        self.assertEqual(int((s == -1).sum()), 0)

    def test_momentum_solo_en_la_vela_que_completa_la_racha(self):
        df = m1([10, 11, 12, 13, 14, 15, 14, 13, 12])
        s = binarias.momentum(df, 3)
        self.assertEqual(s.tolist(), [0, 0, 0, 1, 0, 0, 0, 0, -1])

    def test_rsi_solo_en_el_cruce_de_vuelta(self):
        df = paseo(5000, 11)
        s = binarias.rsi_reversion(df)
        v = binarias._rsi(df["close"], 14)
        for t in np.flatnonzero(s.to_numpy() == 1):
            self.assertLess(v.iloc[t - 1], 30)
            self.assertGreaterEqual(v.iloc[t], 30)

    def test_regla_desconocida(self):
        with self.assertRaises(ValueError):
            binarias.resolver_regla("gringo")


class PruebasBacktest(unittest.TestCase):
    def test_liquidacion(self):
        self.assertEqual(binarias.resultado(1, 1.0, 1.1), "gana")
        self.assertEqual(binarias.resultado(-1, 1.0, 1.1), "pierde")
        self.assertEqual(binarias.resultado(-1, 1.0, 0.9), "gana")
        self.assertEqual(binarias.resultado(1, 1.0, 1.0), "empate")

    def test_resultado_calculable_a_mano(self):
        df = m1([1, 2, 3, 2, 2])
        senal = pd.Series([1, 0, -1, 1, -1], index=df.index)
        p = binarias.backtest(df, senal, 1, 0.85)
        # t0 sube 1->2 gana | t2 baja 3->2 gana | t3 sube 2->2 empate | t4 sin salida
        self.assertEqual((p.ganadas, p.perdidas, p.empates), (2, 0, 1))
        self.assertEqual(p.senales, 2)
        self.assertIn("MUESTRA CHICA", p.resumen())

    def test_paseo_aleatorio_queda_cerca_del_50(self):
        df = paseo(20000, 5)
        fn, nombre = binarias.resolver_regla("mom:2")
        p = binarias.backtest(df, fn(df), 1, 0.85, nombre)
        self.assertGreater(p.senales, 1000)
        self.assertLess(abs(p.acierto - 0.5), 0.05)
        self.assertFalse(p.tiene_ventaja)

    def test_vencimientos(self):
        self.assertEqual(binarias.vence_en_velas(60), 1)
        self.assertEqual(binarias.vence_en_velas(300), 5)
        self.assertIsNone(binarias.vence_en_velas(30))
        self.assertIsNone(binarias.vence_en_velas(90))

    def test_mercado_cerrado(self):
        v = pd.Timestamp("2026-10-23 23:59")
        self.assertFalse(binarias.mercado_cerrado(v, v + pd.Timedelta(minutes=1, seconds=30)))
        self.assertTrue(binarias.mercado_cerrado(v, v + pd.Timedelta(hours=30)))


# --------------------------------------------------------------------------
class FuenteFalsa:
    """Mercado simulado: el minuto actual avanza con el reloj de la prueba."""

    def __init__(self, df: pd.DataFrame, reloj):
        self.df, self.reloj = df, reloj
        self.inicio_real = reloj()
        self.inicio_mercado = df.index[600]

    def _ahora(self):
        return self.inicio_mercado + (self.reloj() - self.inicio_real)

    def velas(self, simbolo, n):
        cerradas = self.df[self.df.index + pd.Timedelta(minutes=1) <= self._ahora()]
        return cerradas.iloc[-n:]

    def precio(self, simbolo):
        return float(self.df["close"].asof(self._ahora()))

    def hora_servidor(self, simbolo):
        return self._ahora()


class PruebasEnVivo(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        with open(config.EJEMPLO, encoding="utf-8") as f:
            base = json.load(f)
        base["diario"] = os.path.join(self.dir.name, "diario.csv")
        base["binarias"]["papel"] = os.path.join(self.dir.name, "papel.csv")
        base["binarias"]["velas_m1_historial"] = 600
        base["binarias"]["vigilar"] = [
            {"simbolo": "EURUSD", "reglas": ["mom:2", "ma:3:8"], "vence_seg": 60}]
        self.ruta = os.path.join(self.dir.name, "config.json")
        with open(self.ruta, "w", encoding="utf-8") as f:
            json.dump(base, f)
        self.cfg = config.cargar(self.ruta)

        self.t = [pd.Timestamp("2026-10-22 08:00:00")]
        self.reloj = lambda: self.t[0]
        self.fuente = FuenteFalsa(paseo(1200, 9), self.reloj)
        self._eventos_real = cli._eventos
        cli._eventos = lambda: ([], "")     # sin internet en las pruebas

    def tearDown(self):
        cli._eventos = self._eventos_real
        self.dir.cleanup()

    def avanzar(self, seg):
        self.t[0] += pd.Timedelta(seconds=seg)

    def test_cada_senal_se_liquida_con_el_precio_real_al_vencer(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli.binarias_vivo(self.cfg, False, self.fuente, cada_seg=10, reloj=self.reloj,
                              dormir=self.avanzar, max_vueltas=6 * 60)   # una hora
        out = buf.getvalue()
        papel = diario.cargar(self.cfg["binarias"]["papel"])

        self.assertGreater(len(papel), 10)
        self.assertRegex(out, r"(SUBE|BAJA) EURUSD \| vence 1 min")
        self.assertIn("RESULTADO", out)
        for _, f in papel.iterrows():
            ent, sal = map(float, re.findall(r"entrada (\S+) salida (\S+)", f["nota"])[0])
            d = 1 if f["direccion"] == "sube" else -1
            self.assertEqual(f["resultado"], binarias.resultado(d, ent, sal))
            self.assertIn("EURUSD", f["senal"])

    def test_no_alerta_sobre_la_vela_vieja_al_arrancar(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli.binarias_vivo(self.cfg, False, self.fuente, cada_seg=10, reloj=self.reloj,
                              dormir=self.avanzar, max_vueltas=1)
        self.assertNotIn("| vence", buf.getvalue())

    def test_cada_alerta_trae_el_historico_y_el_aviso(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli.binarias_vivo(self.cfg, False, self.fuente, cada_seg=10, reloj=self.reloj,
                              dormir=self.avanzar, max_vueltas=6 * 30)
        bloques = [b for b in buf.getvalue().split("\n") if "| vence 1 min |" in b]
        self.assertTrue(bloques)
        self.assertIn("Historico:", buf.getvalue())
        self.assertIn("Sin ventaja demostrada", buf.getvalue())

    def test_stats_papel(self):
        with redirect_stdout(io.StringIO()):
            cli.binarias_vivo(self.cfg, False, self.fuente, cada_seg=10, reloj=self.reloj,
                              dormir=self.avanzar, max_vueltas=6 * 60)
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(cli.main(["--config", self.ruta, "stats", "--papel"]), 0)
        self.assertIn("EURUSD mom:2 60s", buf.getvalue())

    def test_prueba_historica_por_comando(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli.cmd_binarias_prueba(self.cfg, self.fuente)
        self.assertIn("equilibrio 54.05%", buf.getvalue())
        self.assertIn("EURUSD ma:3:8 60s", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
