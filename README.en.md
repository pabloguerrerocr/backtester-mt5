# MT5 Backtester — autopsy of a retail strategy

*[Versión en español](README.md)*

Measures common strategies (moving-average crossover, RSI) with real data from the
MetaTrader 5 terminal and **shows why their backtest lies**.

It is not a bot that makes money. The interesting result is how much of the return
survives after accounting for costs, overfitting and look-ahead.

## Requirements

- MetaTrader 5 installed and logged in (a demo account is enough)
- `pip install MetaTrader5 pandas numpy`

## Usage

```bash
python main.py                                        # EURUSD H1, 5000 candles
python main.py --simbolo XAUUSD --tf D1 --velas 1500
python main.py --comision-bp 2 --piso-bp 1.0 --sin-autopsia
```

Timeframes: `M15 H1 H4 D1 W1`. Available symbols depend on the broker (the
MetaQuotes demo has currencies and metals, no crypto).

## What it controls

| Bias | How it is controlled |
|---|---|
| Look-ahead | the signal from bar `t` executes at `t+1` (`motor.correr`, `retraso=1`); `retraso=0` raises an error |
| Unfinished candle | the last, still-open candle is dropped (`datos.velas`) |
| Transaction costs | charged on every position change, **with a mandatory floor** |
| Overfitting | a grid of 11 parameter combinations, to see whether the result depends on a single cell |

**What it does not control:** real slippage, execution timing, swap for holding
positions overnight, and the fact that demo prices are not those of a real account.

### Why there is a cost floor

The candles' `spread` field **comes in as zero for much of the history**: 88% of
EURUSD H1 candles, 100% of the last 1000, 95% on W1. Taking it at face value is
the same as assuming trading is free — exactly the bias this project measures.
That is why a cost below `--piso-bp` (0.5 bp by default) is never assumed, and the
program warns when it applied it.

The spread the demo does report is unrealistic too: 0.087 bp on EURUSD, when a
retail broker charges about 1 pip (~0.85 bp).

## Files

| File | What it does |
|---|---|
| `datos.py` | connection to the terminal, candle download, broker time |
| `estrategias.py` | signals (moving-average crossover, RSI, buy & hold) |
| `motor.py` | vectorized backtest with execution delay and costs |
| `metricas.py` | return, CAGR, volatility, Sharpe, maximum drawdown |
| `main.py` | CLI and the autopsy section |
| `pruebas.py` | 32 tests: invariants, edge cases and integration against the terminal |

## Tests

```bash
python -m unittest pruebas -v
```

Integration tests skip themselves if the terminal is not open. The most relevant:

- **`test_motor_vectorizado_igual_a_simulacion_barra_a_barra`** — replays 1500
  real EURUSD bars with an explicit loop; both equity curves match with
  `rtol=1e-12`. If the engine were misaligned by one index, this test catches it.
- **`test_ejecucion_retrasada_una_barra`** — on a series whose result can be
  computed by hand (100 → 110 → 99 → 108.9), checks that the signal from `t` is
  applied to the return of `t+1`.
- **`test_ninguna_estrategia_usa_el_futuro`** — truncating the series does not
  change any signal already issued.
- **`test_spread_cero_no_significa_operar_gratis`** — the cost floor applies when
  the broker reports a zero spread.
- **`test_sharpe_sin_volatilidad_es_nan_y_no_un_numero_absurdo`** — `std()` of a
  constant series gives `2e-19`, not `0`; without a tolerance the Sharpe came out
  as `7e16`.

## Observed result

EURUSD H1, 5000 candles (2025-11-28 to 2026-09-21, broker time), cost 0.50 bp:

| Strategy | Return | Sharpe | Max DD | Trades |
|---|---|---|---|---|
| MA 20/50 | −3.47% | −1.10 | −8.11% | 111 |
| RSI 14 30/70 | −1.33% | −0.38 | −3.15% | 35 |
| Buy & hold | −0.72% | −0.13 | −5.92% | 1 |

None beats doing nothing, and 9 of the 11 moving-average combinations lose money.
That is the finding.

On XAUUSD D1 (2020-2026) the moving-average crossover does gain +83%, but buying
and holding gains +142% with a better Sharpe (0.93 versus 0.80) — the strategy
charges you for destroying return.
