# Backtester MT5 — autopsia de una estrategia retail

*[English version](README.en.md)*

**Pregunta.** ¿Cuánto del retorno de una estrategia de trading popular sobrevive
cuando se descuentan costos reales, sobreajuste e información futura?

**Respuesta corta: nada.** Con datos reales del terminal MetaTrader 5, ninguna de las
estrategias comunes (cruce de medias, RSI) le gana a comprar y mantener, y en el
estudio de modelos de «smart money» **0 de 25** configuraciones de autor tienen
ventaja estadística después de costos. No es un bot que gana dinero: es una
auditoría de por qué los backtests mienten.

## Tres hallazgos

**1. Ninguna estrategia le gana a no hacer nada.** En EURUSD H1 (5.000 velas), el
cruce de medias pierde 3,47 %, el RSI 1,33 % y comprar y mantener 0,72 %; 9 de las 11
combinaciones de medias pierden dinero. En XAUUSD D1 el cruce gana +83 %, pero comprar
y mantener gana +142 % con mejor Sharpe (0,93 contra 0,80).

**2. Los datos de la demo engañan.** El campo `spread` llega en cero en el 88 % de las
velas de EURUSD H1: tomarlo al pie de la letra es suponer que operar es gratis. Por
eso hay un piso de costo obligatorio. Y la demo congeló el precio de USTEC y US500
durante tres meses de 2024-2025, detectado y excluido con una regla objetiva.

**3. Lo que gana dentro de muestra no predice lo que gana fuera.** En el estudio ICT,
entre 1.120 variantes, la correlación entre los resultados antes y después de julio
de 2024 es de **+0,09**. Solo 7 variantes tienen t > 2, contra unas 26 esperables por
azar.

Las cifras salen de corridas contra el terminal; el detalle está en
[«Resultado observado»](#resultado-observado) y en [`ict/`](ict/).

## Cómo correrlo

Los backtests necesitan MetaTrader 5 instalado y con sesión iniciada (basta una
cuenta demo), y el terminal solo existe para Windows. Las pruebas unitarias corren en
cualquier sistema:

```bash
git clone https://github.com/pabloguerrerocr/backtester-mt5.git
cd backtester-mt5
pip install -r requirements.txt      # en Mac y Linux omite MetaTrader5 solo
python -m unittest pruebas -v        # 32 pruebas; las de terminal se saltan sin MT5
cd ict && python -m unittest pruebas_ict -v   # 12 pruebas más
```

Con el terminal abierto:

```bash
python main.py                                        # EURUSD H1, 5000 velas
python main.py --simbolo XAUUSD --tf D1 --velas 1500
python main.py --comision-bp 2 --piso-bp 1.0 --sin-autopsia
```

Timeframes: `M15 H1 H4 D1 W1`. Los símbolos disponibles dependen del broker
(en la demo de MetaQuotes hay divisas y metales, no cripto).

## Qué controla

| Sesgo | Cómo se controla |
|---|---|
| Look-ahead | la señal de la barra `t` se ejecuta en `t+1` (`motor.correr`, `retraso=1`); `retraso=0` lanza error |
| Vela en formación | se descarta la última vela sin cerrar (`datos.velas`) |
| Costos de transacción | se descuentan en cada cambio de posición, **con piso obligatorio** |
| Sobreajuste | rejilla de 11 combinaciones de parámetros, para ver si el resultado depende de una sola celda |

**Lo que no controla:** slippage real, horario de ejecución, swap por mantener
posiciones entre días, y que los precios de una demo no son los de una cuenta real.

### Por qué hay un piso de costo

El campo `spread` de las velas **llega en cero en buena parte del histórico**:
88 % de las velas en EURUSD H1, 100 % en las últimas 1000, 95 % en W1. Tomarlo
al pie de la letra equivale a suponer que operar es gratis — justo el sesgo que
este proyecto mide. Por eso nunca se asume un costo menor a `--piso-bp`
(0.5 bp por defecto), y el programa avisa cuándo lo aplicó.

El spread que sí reporta la demo también es irreal: 0.087 bp en EURUSD, cuando
un bróker retail cobra cerca de 1 pip (~0.85 bp).

## Archivos

| Archivo | Qué hace |
|---|---|
| `datos.py` | conexión al terminal, descarga de velas, hora del bróker |
| `estrategias.py` | señales (cruce de medias, RSI, buy & hold) |
| `motor.py` | backtest vectorizado con retraso de ejecución y costos |
| `metricas.py` | retorno, CAGR, volatilidad, Sharpe, máximo drawdown |
| `main.py` | CLI y sección de autopsia |
| `pruebas.py` | 32 pruebas: invariantes, casos límite e integración contra el terminal |

## Pruebas

```bash
python -m unittest pruebas -v
```

Las de integración se saltan solas si el terminal no está abierto. Sin MetaTrader 5
(por ejemplo, en Mac o Linux) pasan las 23 unitarias y se saltan las 9 de
integración; en `ict/` pasan 6 y se saltan las 6 que necesitan las velas. Las más
relevantes:

- **`test_motor_vectorizado_igual_a_simulacion_barra_a_barra`** — reproduce
  1500 barras reales de EURUSD con un bucle explícito; las dos curvas de
  capital coinciden con `rtol=1e-12`. Si el motor se desalineara un índice,
  esta prueba lo detecta.
- **`test_ejecucion_retrasada_una_barra`** — sobre una serie de resultado
  calculable a mano (100 → 110 → 99 → 108.9), comprueba que la señal de `t`
  se aplica al retorno de `t+1`.
- **`test_ninguna_estrategia_usa_el_futuro`** — truncar la serie no cambia
  ninguna señal ya emitida.
- **`test_spread_cero_no_significa_operar_gratis`** — el piso de costo se
  aplica cuando el bróker reporta spread 0.
- **`test_sharpe_sin_volatilidad_es_nan_y_no_un_numero_absurdo`** — `std()` de
  una serie constante da `2e-19`, no `0`; sin tolerancia el Sharpe salía `7e16`.

## Resultado observado

EURUSD H1, 5000 velas (2025-11-28 a 2026-09-21, hora del bróker), costo 0.50 bp:

| Estrategia | Retorno | Sharpe | Max DD | Ops |
|---|---|---|---|---|
| MA 20/50 | −3.47 % | −1.10 | −8.11 % | 111 |
| RSI 14 30/70 | −1.33 % | −0.38 | −3.15 % | 35 |
| Buy & hold | −0.72 % | −0.13 | −5.92 % | 1 |

Ninguna le gana a no hacer nada, y 9 de las 11 combinaciones de medias pierden
dinero. Ese es el hallazgo.

En XAUUSD D1 (2020-2026) el cruce de medias sí gana +83 %, pero comprar y
mantener gana +142 % con mejor Sharpe (0.93 contra 0.80) — la estrategia cobra
por destruir retorno.

## Estudio aparte: ICT, CRT + TBS e iFVG

En [`ict/`](ict/) se prueban cinco modelos de "smart money" (Silver Bullet, modelo
2022, iFVG, CRT clásico y CRT + TBS) con las reglas de sus autores, en cinco
mercados y 1 120 variantes. Ninguna configuración de autor muestra ventaja
estadística después de costos; la única pista sobrevive fuera de muestra y se
está probando en vivo con reglas congeladas.
