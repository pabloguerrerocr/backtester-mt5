"""Capa de IA: explica el contexto de una senal en lenguaje claro.

El modelo NO decide ni predice. Recibe los numeros que ya calculo el asesor
(senal, evidencia del backtest, estado del diario, frenos, noticias) y los
traduce a una explicacion corta. Si falta la clave de la API, el asesor
funciona igual sin esta parte.

Requiere:  pip install anthropic   y la variable ANTHROPIC_API_KEY.
"""
from __future__ import annotations

import json
import os

MODELO = os.environ.get("ASESOR_MODELO", "claude-sonnet-5-5")

SISTEMA = """Sos el asesor de riesgo de un trader retail en Costa Rica. Hablás en español \
informal (vos), directo y con números. Recibís un JSON con una señal técnica, la evidencia \
histórica de esa regla después de costos, las estadísticas del diario de operaciones en vivo, \
el estado de los frenos de riesgo y las noticias de alto impacto cercanas.

Reglas:
- Nunca predigas la dirección del precio ni inventes niveles, datos o noticias que no estén en el JSON.
- Si la evidencia dice SIN VENTAJA PROBADA, decilo en la primera línea: la señal no justifica arriesgar plata.
- Si hay un freno activo o una noticia en ventana, la recomendación es no operar, sin matices.
- Si el diario tiene menos de 30 operaciones, recordá que el acierto observado todavía no significa nada.
- Máximo 6 líneas. Terminá con una acción concreta (operar en demo, registrar, esperar, no operar).
- No sos asesor financiero licenciado; no lo digas en cada mensaje, pero no des órdenes de inversión."""


def disponible() -> bool:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def explicar(contexto: dict, max_tokens: int = 400) -> str | None:
    """Devuelve la explicacion del modelo, o None si la IA no esta configurada o falla."""
    if not disponible():
        return None
    import anthropic
    try:
        cliente = anthropic.Anthropic()
        r = cliente.messages.create(
            model=MODELO, max_tokens=max_tokens, system=SISTEMA,
            messages=[{"role": "user",
                       "content": json.dumps(contexto, ensure_ascii=False, default=str)}],
        )
    except Exception as e:  # red, cuota, clave invalida: el asesor sigue sin IA
        return f"(IA no disponible: {type(e).__name__}: {e})"
    return "".join(b.text for b in r.content if getattr(b, "type", "") == "text").strip()
