"""Pruebas del estudio ICT: simulador conservador, horario de NY y cero look-ahead.

    python -m unittest pruebas_ict -v
"""
import os
import unittest

import numpy as np
import pandas as pd

import modelos as M
from smc import COSTO, Orden, cargar, simular, swings

HAY_DATOS = os.path.exists(os.path.join(os.path.dirname(__file__), "datos", "USTEC_M5.csv"))


def barras(filas):
    a = np.array(filas, dtype=float)
    return a[:, 0], a[:, 1], a[:, 2], a[:, 3]


class Simulador(unittest.TestCase):
    def test_barra_que_toca_stop_y_objetivo_cuenta_stop(self):
        o, h, l, c = barras([[100, 100, 100, 100], [100, 103, 97, 100]])
        op = simular(o, h, l, c, Orden(0, 1, np.nan, 98, 102, 1, 1), costo=0.0,
                     riesgo_min_costos=0)
        self.assertEqual(op.motivo, "stop")
        self.assertAlmostEqual(op.r, -1.0)

    def test_costo_se_descuenta_en_r(self):
        o, h, l, c = barras([[100, 100, 100, 100], [100, 100.5, 99.5, 100],
                             [100, 104.5, 100, 104]])
        op = simular(o, h, l, c, Orden(0, 1, np.nan, 98, 104, 1, 2), costo=0.5,
                     riesgo_min_costos=0)
        self.assertEqual(op.motivo, "objetivo")
        self.assertAlmostEqual(op.r, (4 - 0.5) / 2)

    def test_limite_se_cancela_si_el_objetivo_llega_antes(self):
        o, h, l, c = barras([[100, 100, 100, 100], [101, 106, 100.5, 105],
                             [105, 105, 98.5, 99]])
        op = simular(o, h, l, c, Orden(0, 1, 99.0, 97, 105, 2, 2), costo=0.0,
                     riesgo_min_costos=0)
        self.assertIsNone(op)

    def test_parcial_y_break_even(self):
        # entra en 100, stop 98, TP1 102 (medio), TP2 106; toca 102 y vuelve a 100
        o, h, l, c = barras([[100, 100, 100, 100], [100, 100.5, 99.5, 100],
                             [100, 102.5, 100.5, 102], [102, 102, 99.8, 100]])
        op = simular(o, h, l, c, Orden(0, 1, np.nan, 98, 106, 1, 3, tp1=102),
                     costo=0.0, riesgo_min_costos=0)
        self.assertEqual(op.motivo, "break-even")
        self.assertAlmostEqual(op.r, 0.5)     # mitad a +1R, mitad a 0

    def test_hueco_sale_a_la_apertura(self):
        o, h, l, c = barras([[100, 100, 100, 100], [100, 100.5, 99.5, 100],
                             [95, 96, 94, 95]])
        op = simular(o, h, l, c, Orden(0, 1, np.nan, 98, 104, 1, 2), costo=0.0,
                     riesgo_min_costos=0)
        self.assertAlmostEqual(op.r, -2.5)

    def test_swing_no_se_confirma_antes_de_k_barras(self):
        h = np.array([1, 2, 5, 3, 2, 1, 1.0])
        l = h - 0.5
        ia, _ = swings(h, l, 2)
        self.assertEqual(list(ia), [2])   # se conoce recién al cierre de la barra 4


@unittest.skipUnless(HAY_DATOS, "sin datos descargados")
class ConDatos(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m5 = cargar("USTEC", "M5")
        cls.m15 = cargar("USTEC", "M15")
        cls.h4 = cargar("USTEC", "H4")

    def test_apertura_de_nueva_york_cae_a_las_930(self):
        df = self.m5.assign(rng=self.m5.high - self.m5.low)
        for meses in ([1, 2], [3], [7], [11]):
            sub = df[df.index.month.isin(meses)]
            sub = sub[(sub.ny_min >= 480) & (sub.ny_min < 720)]
            self.assertEqual(sub.groupby("ny_min").rng.mean().idxmax(), 570, meses)

    def test_se_excluyen_los_dias_con_precio_congelado(self):
        from smc import dias_danados
        malos = dias_danados("USTEC")
        self.assertTrue(pd.Timestamp("2024-11-12") in malos)
        self.assertFalse(pd.Timestamp("2024-09-12") in malos)
        self.assertFalse((self.m5["ny_dia"] == pd.Timestamp("2024-11-12")).any())
        self.assertFalse(len(dias_danados("EURUSD")))

    def test_reglas_congeladas_reproducen_el_backtest(self):
        """Si el motor cambia, la prueba en vivo deja de medir lo que dijo el informe."""
        import reglas_congeladas as C
        ops = [o for o in M.barrido_mss_fvg(self.m5, C.COSTO, **C.REGLAS)
               if self.m5.index[o.t_entrada] < pd.Timestamp("2026-09-24")]
        self.assertEqual(len(ops), C.BACKTEST_OPS)
        self.assertAlmostEqual(np.mean([o.r for o in ops]), C.BACKTEST_E, places=3)

    def _sin_futuro(self, correr, df, corte):
        """Las operaciones cerradas antes del corte no cambian si se borra el futuro."""
        completo = [(x.t_entrada, x.direccion, round(x.r, 9)) for x in correr(df)
                    if x.t_salida < corte - 400]
        truncado = [(x.t_entrada, x.direccion, round(x.r, 9)) for x in correr(df.iloc[:corte])
                    if x.t_salida < corte - 400]
        self.assertGreater(len(completo), 20)
        self.assertEqual(completo, truncado)

    def test_silver_bullet_no_mira_el_futuro(self):
        self._sin_futuro(lambda d: M.barrido_mss_fvg(d, COSTO["USTEC"], [(600, 660)]),
                         self.m5, 150_000)

    def test_ifvg_no_mira_el_futuro(self):
        self._sin_futuro(lambda d: M.ifvg(d, COSTO["USTEC"]), self.m5, 150_000)

    def test_crt_tbs_no_mira_el_futuro(self):
        corte = 150_000
        fin = self.m5.index[corte]
        completo = [(x.t_entrada, round(x.r, 9)) for x in
                    M.crt(self.h4, self.m5, COSTO["USTEC"], entrada="tbs", ltf=self.m15)
                    if x.t_salida < corte - 400]
        truncado = [(x.t_entrada, round(x.r, 9)) for x in
                    M.crt(self.h4[self.h4.index < fin], self.m5.iloc[:corte], COSTO["USTEC"],
                          entrada="tbs", ltf=self.m15[self.m15.index < fin])
                    if x.t_salida < corte - 400]
        self.assertGreater(len(completo), 20)
        self.assertEqual(completo, truncado)


if __name__ == "__main__":
    unittest.main()
