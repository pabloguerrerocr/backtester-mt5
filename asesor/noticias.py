"""Calendario economico: avisa cuando hay un dato de alto impacto cerca.

No intenta adivinar la direccion del dato. Sirve para una sola cosa: no abrir
operaciones justo antes de NFP, CPI o una decision de tasas, cuando el spread
se abre y el precio salta sin respetar ninguna senal tecnica.

Fuente por defecto: el JSON semanal publico de Forex Factory (faireconomy).
Si no responde, el asesor sigue funcionando sin filtro de noticias y lo avisa.
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass

import pandas as pd

URL_CALENDARIO = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

# Que monedas mueven cada simbolo. Indices de EE.UU. y oro -> USD.
MONEDAS = {
    "USTEC": ["USD"], "US500": ["USD"], "US30": ["USD"], "XAUUSD": ["USD"],
    "XAGUSD": ["USD"], "BTCUSD": ["USD"],
}


def monedas_de(simbolo: str) -> list[str]:
    """Monedas cuyo calendario mueve el simbolo. Un activo OTC devuelve [] porque
    su precio lo genera el broker fuera de mercado: ninguna noticia real aplica."""
    s = simbolo.upper().strip()
    if "OTC" in s:
        return []
    if s in MONEDAS:
        return MONEDAS[s]
    if len(s) == 6 and s.isalpha():
        return [s[:3], s[3:]]
    return ["USD"]


@dataclass
class Evento:
    hora_utc: pd.Timestamp
    moneda: str
    titulo: str
    impacto: str
    pronostico: str
    previo: str

    def texto(self, zona: str = "America/Costa_Rica") -> str:
        local = self.hora_utc.tz_convert(zona)
        extra = f" (pron. {self.pronostico}, prev. {self.previo})" if self.pronostico else ""
        return f"{local:%a %d %H:%M} {self.moneda} {self.titulo} [{self.impacto}]{extra}"


def parsear(crudo: list[dict]) -> list[Evento]:
    eventos = []
    for e in crudo:
        try:
            hora = pd.Timestamp(e["date"])
            hora = hora.tz_localize("UTC") if hora.tzinfo is None else hora.tz_convert("UTC")
        except (KeyError, ValueError):
            continue
        eventos.append(Evento(hora, str(e.get("country", "")).upper(), str(e.get("title", "")),
                              str(e.get("impact", "")), str(e.get("forecast", "") or ""),
                              str(e.get("previous", "") or "")))
    return sorted(eventos, key=lambda x: x.hora_utc)


def descargar(url: str = URL_CALENDARIO, timeout: float = 10.0) -> list[Evento]:
    req = urllib.request.Request(url, headers={"User-Agent": "backtester-mt5-asesor"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return parsear(json.loads(r.read().decode("utf-8")))


def proximos(eventos: list[Evento], simbolo: str, ahora: pd.Timestamp,
             horas: float = 24, impactos=("High",)) -> list[Evento]:
    monedas = set(monedas_de(simbolo))
    fin = ahora + pd.Timedelta(hours=horas)
    return [e for e in eventos
            if e.moneda in monedas and e.impacto in impactos and ahora <= e.hora_utc <= fin]


def en_ventana(eventos: list[Evento], simbolo: str, ahora: pd.Timestamp,
               antes_min: int = 30, despues_min: int = 30) -> list[Evento]:
    """Eventos de alto impacto a menos de `antes_min` antes o `despues_min` despues."""
    monedas = set(monedas_de(simbolo))
    ini, fin = ahora - pd.Timedelta(minutes=despues_min), ahora + pd.Timedelta(minutes=antes_min)
    return [e for e in eventos
            if e.moneda in monedas and e.impacto == "High" and ini <= e.hora_utc <= fin]
