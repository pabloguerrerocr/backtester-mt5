"""Envio de alertas: consola siempre, Telegram si esta configurado.

Telegram sirve para recibir el aviso en el celular sin dejar la consola a la
vista. Variables: TELEGRAM_TOKEN (de @BotFather) y TELEGRAM_CHAT_ID.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request


def telegram_configurado() -> bool:
    return bool(os.environ.get("TELEGRAM_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))


def enviar(texto: str) -> None:
    print(texto, flush=True)
    if not telegram_configurado():
        return
    url = f"https://api.telegram.org/bot{os.environ['TELEGRAM_TOKEN']}/sendMessage"
    datos = urllib.parse.urlencode({"chat_id": os.environ["TELEGRAM_CHAT_ID"],
                                    "text": texto[:4000]}).encode()
    try:
        with urllib.request.urlopen(url, data=datos, timeout=10) as r:
            if not json.loads(r.read().decode()).get("ok"):
                print("  (Telegram rechazo el mensaje)")
    except Exception as e:
        print(f"  (no se pudo enviar a Telegram: {e})")
