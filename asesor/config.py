"""Carga la configuracion del asesor. Copia config.ejemplo.json a config.json y editala."""
from __future__ import annotations

import json
import os

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
RUTA = os.path.join(AQUI, "config.json")
EJEMPLO = os.path.join(AQUI, "config.ejemplo.json")


def cargar(ruta: str | None = None) -> dict:
    ruta = ruta or (RUTA if os.path.exists(RUTA) else EJEMPLO)
    with open(ruta, encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["_origen"] = ruta
    if not os.path.isabs(cfg["diario"]):
        cfg["diario"] = os.path.join(RAIZ, cfg["diario"])
    b = cfg.setdefault("binarias", {})
    b.setdefault("pago_por_defecto", 0.85)
    b.setdefault("velas_m1_historial", 20000)
    b.setdefault("vigilar", [])
    b.setdefault("papel", "asesor/registro/papel_binarias.csv")
    if not os.path.isabs(b["papel"]):
        b["papel"] = os.path.join(RAIZ, b["papel"])
    return cfg
