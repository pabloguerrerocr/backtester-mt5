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

## Señales de binarias (para operar a mano en IQ Option)

Lee el precio real de MT5 al cierre de cada vela de 1 minuto y te tira
`SUBE` / `BAJA` con vencimiento. Cada señal **se anota sola en papel** con el
precio de entrada y, al vencer, con el precio real: así medís la regla contra el
54.05 % sin arriesgar plata.

```bash
python -m asesor binarias-prueba     # primero: qué dice el histórico de cada regla
python -m asesor binarias            # en vivo (deja MT5 abierto)
python -m asesor stats --papel       # acierto en papel por regla, con IC
```

Ejemplo de alerta:

```
BAJA EURUSD | vence 1 min | entrada ~1.08149 | 08:04:00 | regla mom:3
  Historico: SIN VENTAJA PROBADA | 72 senales a 1 min: acierto 47.2% [IC 36.1%, 58.6%] ...
  En papel: 0 senales
  -> Sin ventaja demostrada: miralo en papel o demo, no con plata real.
RESULTADO BAJA EURUSD mom:3 60s: GANA (entrada 1.08149, salida 1.08146) | en papel: 1/1 ...
```

Reglas (en `binarias.vigilar` del config): `rsi:14:30:70` (rebote desde
sobrecompra/sobreventa, la lógica de casi todas las flechas COMPRA/VENDE),
`ma:5:20` (cruce de medias), `mom:3` (tres cierres seguidos en la misma dirección).
Vencimientos de 60, 120, 300 s... se prueban en el histórico de velas M1; 30 s
solo se puede medir en papel.

Fin de semana: el par real no cotiza, el bot lo detecta y no da señales (en
IQ Option a esa hora solo hay OTC).

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
| `binarias.py` | reglas SUBE/BAJA, backtest por vencimiento, registro en papel |
| `noticias.py` | calendario de Forex Factory (JSON público) y ventanas de alto impacto |
| `ia.py` | explicación con la API de Claude; no predice ni decide |
| `alertas.py` | consola y Telegram |
| `__main__.py` | comandos |
| `pruebas_asesor.py`, `pruebas_binarias.py` | 50 pruebas, sin terminal ni internet (el precio en vivo se simula) |

```bash
python -m unittest asesor.pruebas_asesor asesor.pruebas_binarias -v
```

No es asesoría financiera: es aritmética sobre tus propios datos.
