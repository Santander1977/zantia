"""
Recado 056, Punto 2 — hallazgo real de producción reaparecido: la
secuencia "hola" -> "consultar" (resuelta, sin citas) -> "listamelas"
(mensaje sin ninguna intención reconocible) volvía a mostrar el saludo
institucional completo + menú + pregunta de servicio "pegados" — en
realidad, la causa era que "listamelas" (como cualquier palabra sin
sentido/typo grave) caía al default histórico de `classify_intent_or_
none` (PROGRAMAR_CITA, recado 030), arrancando el flujo de reserva
completo en silencio.

Corregido: el fallback a PROGRAMAR_CITA ahora exige una señal mínima de
intención (afirmación tipo "sí"/"claro", o un verbo de pedido típico
"necesito"/"quiero"/"ayuda"/etc.) — sin ninguna de esas señales, se
trata como "sin intención" (`None`), igual que un saludo puro (recado
048), mostrando el menú en vez de arrancar la reserva.
"""
import pytest

from domains.health import (
    MockActivitySource, MockActivityResultSink, ReminderManager,
    build_health_gateway, handle_inbound_message,
)
from domains.health.appointment_service import MockAppointmentService
from domains.health.intent import RequestIntent, classify_intent_or_none


def test_reproduce_secuencia_real_hola_consultar_listamelas():
    gateway = build_health_gateway(
        MockActivitySource(), MockAppointmentService(), ReminderManager(), MockActivityResultSink()
    )
    r1 = handle_inbound_message(gateway, "PAC-X", "demo", "m1", "hola")
    assert "1. reservar" in r1.lower()

    r2 = handle_inbound_message(gateway, "PAC-X", "demo", "m2", "consultar")
    assert "no tienes ninguna cita activa" in r2.lower()

    r3 = handle_inbound_message(gateway, "PAC-X", "demo", "m3", "listamelas")
    assert "fechas disponibles" not in r3.lower(), f"no debía arrancar la reserva en silencio: {r3!r}"
    assert "no logré identificar" in r3.lower()
    assert "1. reservar" in r3.lower()  # menú de nuevo, nunca la presentación completa
    assert "hospital regional" not in r3.lower()


@pytest.mark.parametrize("texto", ["listamelas", "asdkjhasd", "no se que decir", "eh", "mmm"])
def test_texto_sin_ninguna_senal_de_intencion_es_none(texto):
    assert classify_intent_or_none(texto) is None


@pytest.mark.parametrize(
    "texto",
    [
        "necesito otra cita de urgencias",  # recado 049/050 — no debe romperse
        "Si claro ayudame puedes orientarme mejor",  # recado 030 — no debe romperse
        "quiero agendar algo",
        "ayudame porfa",
        "quisiera saber mas",
    ],
)
def test_texto_con_senal_de_intencion_sigue_siendo_programar_cita(texto):
    assert classify_intent_or_none(texto) == RequestIntent.PROGRAMAR_CITA
