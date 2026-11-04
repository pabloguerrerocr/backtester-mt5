# MT5 Backtester — autopsy of a retail strategy

*[Versión en español](README.md)*

**Question.** How much of a popular trading strategy's return survives once real
costs, overfitting and look-ahead are accounted for?

**Short answer: none.** On real data from the MetaTrader 5 terminal, none of the common
strategies (moving-average crossover, RSI) beats buy and hold, and in the study of
"smart money" models **0 of 25** author configurations have a statistical edge after
costs. It is not a bot that makes money: it is an audit of why backtests lie.

## Three findings

**1. No strategy beats doing nothing.** On EURUSD H1 (5,000 candles) the
moving-average crossover loses 3.47%, RSI 1.33% and buy and hold 0.72%; 9 of the 11
moving-average combinations lose money. On XAUUSD D1 the crossover makes +83%, but buy
and hold makes +142% with a better Sharpe ratio (0.93 versus 0.80).

**2. The demo data is misleading.** The `spread` field arrives as zero in 88% of
EURUSD H1 candles: taking it literally assumes trading is free. That is why there is a
mandatory cost floor. And the demo froze the price of USTEC and US500 for three months
in 2024-2025, which was detected and excluded with an objective rule.

**3. What wins in sample does not predict what wins out of sample.** In the ICT study,
across 1,120 variants, the correlation between results before and after July 2024 is
**+0.09**. Only 7 variants have t > 2, against about 26 expected by chance.

The figures come from runs against the terminal; details are in
["Observed result"](#observed-result) and in [`ict/`](ict/).

## Run it

The backtests need MetaTrader 5 installed and logged in (a demo account is enough),
and the terminal only exists for Windows. The unit tests run on any system:

```bash
git clone https://github.com/pabloguerrerocr/backtester-mt5.git
cd backtester-mt5
pip install -r requirements.txt      # on Mac and Linux it skips MetaTrader5 by itself
python -m unittest pruebas -v        # 32 tests; the terminal ones skip without MT5
cd ict && python -m unittest pruebas_ict -v   # 12 more tests
```

With the terminal open:

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

Integration tests skip themselves if the terminal is not open. Without MetaTrader 5
(on Mac or Linux, for example) the 23 unit tests pass and the 9 integration tests are
skipped; in `ict/`, 6 pass and the 6 that need the candles are skipped. The most
relevant:

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

## Separate study: ICT, CRT + TBS and iFVG

[`ict/`](ict/) tests five "smart money" models (Silver Bullet, 2022 model, iFVG,
classic CRT and CRT + TBS) with their authors' own rules, on five markets and
1,120 variants. No author configuration shows a statistical edge after costs;
the only lead survives out of sample and is being tested live with frozen rules.
