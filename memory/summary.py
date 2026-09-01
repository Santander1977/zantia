"""
Resumen — Capa D de 004 sección 3.

Implementación deliberadamente ingenua para el MVP (concatenar y
truncar): un resumen curado de verdad necesitaría un LLM real. El
ConversationState solo guarda `resumen_ref` (un puntero), nunca este
texto directamente — así se evita la duplicación que 004 sección 2.1
identificó como problema en el diseño original de `contexto`.
"""
from __future__ import annotations

from typing import List

from .conversation_memory import Turn

_MAX_CHARS = 400


def regenerate_summary(recent_turns: List[Turn]) -> str:
    if not recent_turns:
        return ""
    texto = " | ".join(f"{t.role}: {t.text}" for t in recent_turns)
    if len(texto) > _MAX_CHARS:
        texto = "..." + texto[-_MAX_CHARS:]
    return texto
