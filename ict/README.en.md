# ICT / CRT + TBS / iFVG study

*[Versión en español](README.md)*

Are the "smart money" models taught on YouTube and in trading courses profitable
when traded with their authors' own rules and realistic costs? Five models are
tested on five markets from the MetaTrader 5 demo server.

**Finding:** with their authors' rules, **0 of 25** model × market combinations show
a statistical edge after costs; across 1,120 variants, what won before July 2024
does not predict what wins afterwards (correlation +0.09).
Full report (in Spanish): [`Backtest-ICT-CRT-iFVG.pdf`](Backtest-ICT-CRT-iFVG.pdf).

## Run

```bash
python descargar.py USTEC US500 EURUSD GBPUSD XAUUSD   # candles into datos/ (terminal open)
python -m unittest pruebas_ict -v                      # 12 tests
python estudio.py                                      # ~1,145 runs into resultados/
python informe_ict.py                                  # PDF
```

`descargar.py` needs the terminal to allow more than 100,000 bars per chart
(Tools → Options → Charts → Max bars, or `MaxBars` in `config\common.ini` with
the terminal closed). 5,000,000 was used here.

`informe_ict.py` and `seguimiento.py` build their PDFs with a shared formatting
module (`informe.py`) that lives outside this repository; the report PDF is
included. Candles (`datos/`), results and the live log are not committed: they
weigh ~200 MB and are rebuilt by the commands above.

## Files

| File | What it does |
|---|---|
| `smc.py` | New York time, swings, liquidity sweeps, session levels, trade simulator |
| `modelos.py` | Silver Bullet / 2022 model, iFVG, classic CRT and CRT + TBS |
| `estudio.py` | each model's "author" configuration + a grid of 224 variants, on 5 symbols |
| `informe_ict.py` | metrics, in/out of sample, prop-firm simulation and PDF |
| `reglas_congeladas.py` | the live-test rule, fixed before seeing a single result |
| `seguimiento.py` | live test: pulls new candles, applies the rule, appends to the log |
| `pruebas_ict.py` | conservative simulator, New York clock, zero look-ahead |

## Decisions that change the result

- **Broker clock.** MetaQuotes-Demo runs on UTC+2/+3 with *European* daylight
  saving. A fixed 7-hour offset shifts the killzones by one hour for about four
  weeks a year. Timestamps are converted `Europe/Athens` → `America/New_York`.
- **Ambiguous candle.** If an M5 candle touches both stop and target, the stop
  counts. On the candle where a limit order fills, only the stop is checked.
- **Costs** (`smc.COSTO`): retail spread + slippage, not the demo's spread.
- **Minimum risk:** trades whose stop is smaller than 3× the cost are skipped;
  no author trades a 1-pip stop.
- **CRT + TBS does not wait for C2 to close:** it decides on M15 with what has
  already happened. The first version filtered on C2's final shape (future
  information); it was fixed and `test_crt_tbs_no_mira_el_futuro` guards it.
- **In/out of sample:** variants are chosen with data before July 2024 and
  evaluated afterwards.

## Damaged demo data

The MetaQuotes demo **froze USTEC and US500 prices from 2024-10-04 to
2025-01-05**: 5-minute candles 0.25 points tall at the New York open. It was
caught because the intraday models stopped trading in those months.
`smc.dias_danados` flags a day when the median relative range of its M5 candles
is below 15 % of the whole series' median, and `cargar` drops it from every
timeframe (78 days in USTEC, 69 in US500, 0 in FX and gold). The indices also
have no candles from 2025-07-16 to 2025-09-09.

## Result (2026-09-23)

- Author configurations: **0 of 25** model × market combinations with t > 2.
  CRT and CRT + TBS win 54-60 % of trades and still lose in all 5 markets; so
  does iFVG.
- Grid of 1,120 variants: 7 with t > 2 versus ~26 expected by chance; the
  correlation between before and after July 2024 is +0.09.
- The only lead: **Silver Bullet on USTEC, 10-11 AM, 3-candle swings, entry at
  50 % of the FVG, 2R**: +0.15 R per trade (557 trades, t = 2.7), positive in
  all 5 years and with 3× costs. But it fails on US500, disappears with a
  9:30-11 window, and nearly all of it comes from longs. A hypothesis to test
  live.

## Live test (since 2026-09-24)

`seguimiento.py` applies the rule in `reglas_congeladas.py` to the real USTEC
price every weekday after the New York close, logs new trades and regenerates a
tracking PDF. If the machine was off, the next run catches up.

- **Paper trading, not demo orders:** on MetaQuotes-Demo, USTEC and US500 have
  trading disabled (`trade_mode = 0`, quotes only).
- Candles are requested with `copy_rates_from_pos`, not `copy_rates_range`: the
  latter only returns what the terminal already has stored and falls behind.
- The log is append-only; recorded trades are never rewritten.
- Decision rule fixed in advance: target of 60 trades; stop early if the
  cumulative result falls below the backtest band (E ± 2 sd · √n) after 20+.
- `test_reglas_congeladas_reproducen_el_backtest` fails if an engine change
  alters what is being measured.
