# Asesor de trading local

Capa en vivo sobre el backtester. **Solo alerta, nunca envía órdenes.**

Hace cuatro cosas, y ninguna es adivinar el precio:

1. **Señales con evidencia**: cada alerta sale con lo que esa misma regla hizo en el
   histórico reciente, después de costos y ejecutada en la vela siguiente (mismo
   `motor.py`). Si no le gana a comprar y mantener con t > 2, la alerta lo dice en la
   primera línea: `SIN VENTAJA PROBADA`.
2. **Riesgo**: tamaño de posición en MT5, equilibrio y Kelly en binarias, y frenos
   (stop diario, pérdidas seguidas, operaciones por día) que se fijan antes de operar.
3. **Diario**: registro que solo agrega filas, con intervalo de confianza del acierto.
   Es lo que decide si una estrategia sirve, no la gráfica.
4. **Noticias + IA**: avisa cuando hay un dato de alto impacto cerca y, si hay clave
   de API, Claude explica el contexto con los números ya calculados.

## Instalación

```bash
pip install MetaTrader5 pandas numpy
pip install anthropic            # opcional: explicaciones con IA
copy asesor\config.ejemplo.json asesor\config.json   # y editá balance, símbolos, frenos
```

Variables opcionales:

| Variable | Para qué |
|---|---|
| `ANTHROPIC_API_KEY` | explicaciones con `--ia` |
| `ASESOR_MODELO` | otro modelo (por defecto `claude-sonnet-5-5`) |
| `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID` | recibir las alertas en el celular |

## Uso (desde la raíz del repo)

```bash
python -m asesor estado                      # freno, config, IA, Telegram
python -m asesor escanear --ia               # una pasada por los símbolos del config
python -m asesor vigilar --cada 15 --ia      # bucle: alerta solo cambios de señal
python -m asesor noticias --simbolo EURUSD   # alto impacto en las próximas 24 h
python -m asesor lotes --simbolo EURUSD --stop 0.0020

# Binarias (IQ Option): se registra a mano cada operación cerrada
python -m asesor registrar --mercado iqoption --simbolo CAFE-OTC --direccion sube \
    --monto 10 --resultado pierde --pago 0.85 --senal GRINGO
python -m asesor stats --mercado iqoption --senal GRINGO
python -m asesor binaria                     # usa el peor caso del IC de tu diario
```

Estrategias en el config: `ma:20:50` (cruce de medias), `rsi:14:30:70`, `bh`.

## IQ Option: qué se puede y qué no

- **No hay API oficial.** Las librerías que existen son ingeniería inversa y violan
  los términos del bróker, así que el asesor no se conecta a IQ Option.
- **Los activos OTC no tienen precio de mercado**: los genera el bróker fuera de
  horario. Por eso el asesor no les calcula señales ni les aplica noticias
  (`monedas_de("CAFE-OTC") == []`).
- Lo que sí hace con binarias: diario, equilibrio, expectativa, Kelly, rachas y
  frenos. Si operás un par de divisas normal (no OTC) en IQ Option, la señal y el
  filtro de noticias salen de MT5 con el mismo símbolo.

## Cuándo una estrategia "sirve" según el asesor

| Mercado | Criterio |
|---|---|
| Binarias | ≥ 30 operaciones y el **límite inferior** del IC 95 % del acierto sobre el equilibrio (54.05 % con pago 85 %) |
| MT5 | ≥ 30 operaciones y t > 2 sobre el pnl por operación |
| Señal del backtest | t > 2, retorno neto positivo y mayor que comprar y mantener |

Ejemplo: 55 % de acierto en 100 binarias parece ganador, pero el IC es [45 %, 64 %]
e incluye el equilibrio. El asesor responde "sin evidencia de ventaja".

## Archivos

| Archivo | Qué hace |
|---|---|
| `riesgo.py` | equilibrio, Kelly, lotes, probabilidad de rachas, frenos |
| `diario.py` | registro append-only, intervalo de Wilson, veredicto |
| `senales.py` | señal de la última vela cerrada + evidencia del backtest |
| `noticias.py` | calendario de Forex Factory (JSON público) y ventanas de alto impacto |
| `ia.py` | explicación con la API de Claude; no predice ni decide |
| `alertas.py` | consola y Telegram |
| `__main__.py` | comandos |
| `pruebas_asesor.py` | 35 pruebas, sin terminal ni internet |

```bash
python -m unittest asesor.pruebas_asesor -v
```

No es asesoría financiera: es aritmética sobre tus propios datos.
