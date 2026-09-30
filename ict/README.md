# Estudio ICT / CRT + TBS / iFVG

*[English version](README.en.md)*

¿Son rentables los modelos de "smart money" que se enseñan en YouTube y cursos,
si se operan con las reglas de sus autores y costos reales? Se miden cinco
modelos en cinco mercados de la demo de MetaTrader 5.

**Hallazgo:** con las reglas de sus autores, **0 de 25** combinaciones modelo × mercado
tienen ventaja estadística después de costos; entre 1 120 variantes, lo que ganaba
antes de julio de 2024 no predice lo que gana después (correlación +0,09).
Informe completo: [`Backtest-ICT-CRT-iFVG.pdf`](Backtest-ICT-CRT-iFVG.pdf).

## Correr

```bash
python descargar.py USTEC US500 EURUSD GBPUSD XAUUSD   # velas a datos/ (terminal abierto)
python -m unittest pruebas_ict -v                      # 12 pruebas
python estudio.py                                      # ~1 145 corridas, resultados/
python informe_ict.py                                  # PDF
```

`descargar.py` necesita que el terminal permita más de 100 000 velas por gráfico
(Herramientas → Opciones → Gráficos → Máx. barras, o `MaxBars` en
`config\common.ini` con el terminal cerrado). Aquí se usó 5 000 000.

`informe_ict.py` y `seguimiento.py` arman el PDF con un módulo de formato
compartido (`informe.py`) que vive fuera de este repositorio; el PDF del informe
sí está incluido. Las velas (`datos/`), los resultados y el registro en vivo no
se suben: pesan ~200 MB y se regeneran con los comandos de arriba.

## Archivos

| Archivo | Qué hace |
|---|---|
| `smc.py` | hora de NY, swings, barridos de liquidez, niveles de sesión, simulador de operaciones |
| `modelos.py` | Silver Bullet / modelo 2022, iFVG, CRT clásico y CRT + TBS |
| `estudio.py` | configuración "pro" de cada modelo + rejilla de 224 variantes, en 5 símbolos |
| `informe_ict.py` | métricas, dentro/fuera de muestra, simulación de prop firm y PDF |
| `reglas_congeladas.py` | la regla de la prueba en vivo, fijada antes de ver un solo resultado |
| `seguimiento.py` | prueba en vivo: baja velas nuevas, aplica la regla y actualiza el registro |
| `pruebas_ict.py` | simulador conservador, horario de NY, cero información futura |

## Decisiones que cambian el resultado

- **Hora del bróker.** MetaQuotes-Demo usa UTC+2/+3 con el cambio de hora
  europeo. Un desfase fijo de 7 h corre las killzones una hora durante unas
  cuatro semanas al año. Se convierte con `Europe/Athens` → `America/New_York`.
- **Vela ambigua.** Si una vela M5 toca stop y objetivo, cuenta el stop. En la
  vela en que se llena una límite solo se revisa el stop.
- **Costos** (`smc.COSTO`): spread retail + deslizamiento, no el de la demo.
- **Riesgo mínimo**: se descartan operaciones cuyo stop mide menos de 3 veces el
  costo; ningún autor opera un stop de 1 pip.
- **CRT + TBS no espera el cierre de C2**: decide en M15 con lo que ya pasó. La
  primera versión filtraba con la forma final de C2 (información futura) y se
  corrigió; `test_crt_tbs_no_mira_el_futuro` lo cuida.
- **Dentro/fuera de muestra**: las variantes se eligen con datos anteriores a
  julio de 2024 y se evalúan después.

## Datos dañados de la demo

La demo de MetaQuotes **congeló el precio de USTEC y US500 del 4-oct-2024 al
5-ene-2025**: velas de 5 minutos de 0,25 puntos en plena apertura de Nueva York.
Se detectó porque los modelos intradía dejaban de operar esos meses. `smc.dias_danados`
marca un día como dañado si la mediana del rango relativo de sus velas M5 es
menor al 15 % de la mediana de toda la serie, y `cargar` lo excluye de todos los
timeframes (78 días en USTEC, 69 en US500, 0 en divisas y oro). Además, los
índices no tienen velas del 16-jul al 9-set-2025.

## Resultado (23-set-2026)

- Configuración de autor: **0 de 25** combinaciones modelo × mercado con t > 2.
  CRT y CRT + TBS aciertan 54-60 % y pierden en los 5 mercados; iFVG también.
- Rejilla de 1 120 variantes: 7 con t > 2 contra ~26 esperadas por azar; la
  correlación entre el antes y el después de jul-2024 es +0,09.
- La única pista: **Silver Bullet en USTEC, 10-11 AM, swing de 3 velas, entrada
  al 50 % del FVG, 2R**: +0,15 R por operación (557 ops, t = 2,7), positiva los
  5 años y con costos ×3. Pero no funciona en US500, desaparece con ventana
  9:30-11 y casi todo viene de los largos. Hipótesis para probar en vivo.

## Prueba en vivo (desde el 24-set-2026)

`seguimiento.py` aplica las reglas de `reglas_congeladas.py` al precio real del
USTEC cada día hábil después del cierre de Nueva York, anota las operaciones
nuevas y regenera un PDF de seguimiento. Si la máquina estuvo apagada, la
siguiente corrida se pone al día.

- **Es paper trading, no órdenes en la demo:** en MetaQuotes-Demo el USTEC y el
  US500 tienen trading deshabilitado (`trade_mode = 0`, solo cotizan).
- Las velas se piden con `copy_rates_from_pos`, no con `copy_rates_range`: esta
  última solo devuelve lo que el terminal ya tiene guardado y se queda atrás.
- El registro solo agrega filas; lo ya anotado no se reescribe.
- Decisión fijada antes de empezar: meta de 60 operaciones; se detiene si el
  acumulado cae bajo la banda del backtest (E ± 2 desv. · √n) con 20 o más.
- `test_reglas_congeladas_reproducen_el_backtest` avisa si un cambio en el motor
  altera lo que se está midiendo.
