"""Laboratorio de estrategias: corre todas las estrategias de profesionales sobre
todos los mercados de MT5, da un veredicto y deja el PDF con las senales de hoy.

    python -W ignore -m laboratorio            # todo: datos, evaluacion, CSV y PDF
    python -W ignore -m laboratorio --sin-pdf  # solo la tabla en la consola

Para probar una estrategia nueva: agregala a ESTRATEGIAS en estrategias.py.
"""
import sys
from pathlib import Path

import pandas as pd

from laboratorio.datos import diarias
from laboratorio.estrategias import ESTRATEGIAS
from laboratorio.evaluar import evaluar

AQUI = Path(__file__).parent

if __name__ == "__main__":
    datos = diarias()
    por_mercado, resumen, carteras = evaluar(datos, ESTRATEGIAS)
    (AQUI / "resultados").mkdir(exist_ok=True)
    por_mercado.to_csv(AQUI / "resultados" / "por_mercado.csv", index=False)
    resumen.to_csv(AQUI / "resultados" / "resumen.csv", index=False)
    pd.DataFrame(carteras).to_csv(AQUI / "resultados" / "carteras.csv")
    pd.set_option("display.width", 250)
    cols = ["estrategia", "desde", "corte", "sharpe_dentro", "sharpe_fuera", "retorno_anual_fuera", "max_dd",
            "mercados_positivos_fuera", "operaciones", "acierto_medio", "prob_perder_1_ano", "prob_dd_20",
            "alarmas", "veredicto"]
    print(resumen[cols].round(2).to_string(index=False))
    if "--sin-pdf" not in sys.argv:
        from laboratorio.reporte import reporte
        print(reporte(datos, por_mercado, resumen, carteras))
