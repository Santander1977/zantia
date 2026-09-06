"""
Clasificador de intención para mensajes INBOUND sin conversación previa
(prompt de evolución bidireccional, catálogo mínimo). Deliberadamente
NO vive dentro de `HealthBrain` (protegido, sin tocar) — es una capa de
enrutamiento previa, propia de `domains/health/gateway.py`, con el
mismo estilo determinista por palabras clave que el resto del dominio.
"""
from __future__ import annotations

from .models import RequestIntent

_PROGRAMAR = ("programar", "agendar", "sacar una cita", "quiero una cita", "necesito una cita", "pedir cita")
_REPROGRAMAR = ("reprogramar", "cambiar mi cita", "cambiar la cita", "mover mi cita", "otra fecha")
_CANCELAR = ("cancelar mi cita", "cancelar la cita", "anular mi cita", "ya no quiero la cita")
_CONSULTAR = ("consultar mi cita", "qué cita tengo", "cuándo es mi cita", "tengo alguna cita", "mis citas")
_CONFIRMAR = ("confirmo mi cita", "confirmo la cita", "sí voy a mi cita", "asistiré a mi cita")
_ESCALAMIENTO = ("hablar con alguien", "persona real", "un humano", "un asesor", "quiero hablar con")
# Bug real de producción (recado 027): "Programar cuál servicios tienes
# disponible" se clasificaba como PROGRAMAR_CITA (por la palabra suelta
# "programar") en vez de como una pregunta por el catálogo — el paciente
# nunca nombró un servicio, pero el flujo de reserva asume uno por
# defecto igual (`_nueva_activity_sintetica`, "medicina general"
# hardcodeado) y termina en "sin disponibilidad" para un servicio que el
# paciente ni pidió. Frases de catálogo ampliadas a formas "tú" reales
# (antes solo existía la forma "tienen"/tercera persona) — deliberadamente
# ANTES de `_PROGRAMAR` en el orden de chequeo de abajo, para que una
# pregunta de catálogo nunca caiga en la rama de reserva solo por
# contener la palabra "programar".
_INFORMACION = (
    "qué servicios tienen", "qué servicios tienes", "qué servicios ofrecen",
    "cuáles servicios", "cuál servicios", "cuál servicio", "qué servicios hay",
    "servicios disponibles", "qué tienes disponible", "qué tienen disponible",
    "cuál tienes", "cuáles tienes",
    "qué información", "cómo funciona", "más información",
)


def classify_intent(text: str) -> RequestIntent:
    """Determinista por palabras clave — mismo espíritu que
    `domains/health/brain.py`, pero para decidir CÓMO enrutar una
    solicitud nueva, no para conducir la conversación en sí."""
    texto = text.lower().strip()

    if any(k in texto for k in _REPROGRAMAR):
        return RequestIntent.REPROGRAMAR_CITA
    if any(k in texto for k in _CANCELAR):
        return RequestIntent.CANCELAR_CITA
    if any(k in texto for k in _CONFIRMAR):
        return RequestIntent.CONFIRMAR_CITA
    if any(k in texto for k in _CONSULTAR):
        return RequestIntent.CONSULTAR_CITA
    if any(k in texto for k in _ESCALAMIENTO):
        return RequestIntent.ESCALAMIENTO
    if any(k in texto for k in _INFORMACION):
        return RequestIntent.INFORMACION_SERVICIO
    if any(k in texto for k in _PROGRAMAR):
        return RequestIntent.PROGRAMAR_CITA

    # Sin coincidencia clara: se trata como intención de programar,
    # dado que es el punto de entrada más seguro (ofrece ayuda en vez
    # de asumir que el paciente ya tiene una cita que gestionar).
    return RequestIntent.PROGRAMAR_CITA
