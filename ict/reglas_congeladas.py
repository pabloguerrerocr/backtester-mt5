"""Las reglas de la prueba en vivo. CONGELADAS el 23-set-2026: no se tocan.

Cambiar cualquier número de este archivo invalida la prueba: se volvería a
elegir la regla mirando resultados, que es justo el sobreajuste que el informe
midió. Si hay que cambiar algo, se empieza una prueba nueva con otra fecha.
"""

CONGELADA = "2026-09-23"
INICIO_NY = "2026-09-24"          # solo cuentan operaciones desde este día (hora de NY)
SIMBOLO = "USTEC"
COSTO = 1.8                       # puntos, ida y vuelta (spread retail + deslizamiento)

# Silver Bullet, 10-11 AM NY, swing de 3 velas, límite al 50 % del FVG, objetivo 2R
REGLAS = dict(ventanas=[(600, 660)], entrada="ce", objetivo="rr", rr=2.0, k=1)

# Lo que dijo el backtest (jul-2022 a set-2026, 557 operaciones)
BACKTEST_OPS = 557
BACKTEST_E = 0.151                # R por operación, neto
BACKTEST_DE = 1.33                # desviación estándar de R por operación

# Regla de decisión, fijada ANTES de ver un solo resultado
META_OPS = 60
MIN_OPS_PARA_DETENER = 20
Z = 2.0                           # banda: E esperada ± Z · DE · √n
