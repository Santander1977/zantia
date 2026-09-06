"""
Bug real de producción (recado 027) — misma conversación real de
Telegram del recado 026, ya con identidad confirmada: el paciente
preguntó por el catálogo de servicios ("Programar cuál servicios
tienes disponible", "Cuál tienes") sin nombrar ninguno específico.

Causa raíz confirmada leyendo el código Y reproduciendo la conversación
completa con un script (`domains/health/gateway.py`, `intent.py`,
`brain.py`):

1. `domains/health/intent.py:classify_intent` no reconocía "qué
   servicios tienes"/"cuál(es) servicio(s)"/"cuál tienes" (solo existía
   la forma "tienen", tercera persona) — un mensaje con la palabra
   suelta "programar" en cualquier parte (ej. "Programar cuál servicios
   tienes disponible") se clasificaba como `PROGRAMAR_CITA` en vez de
   como pregunta de catálogo.
2. `_nueva_activity_sintetica` (`gateway.py`) siempre asigna
   `service="medicina general"` de forma HARDCODEADA, sin que el
   paciente lo haya confirmado nunca — NO fue que "cuál servicios tienes
   disponible" se usara como nombre de servicio buscado (esa hipótesis
   inicial no se confirmó); el servicio por defecto es fijo, independiente
   del texto real del paciente.
3. Con `HealthBrain._ofrecer_disponibilidad` sin turnos para ese
   servicio por defecto, la respuesta quedaba en "sin disponibilidad", y
   NINGUNA capa (ni `intent.py` para mensajes nuevos, ni `HealthBrain`
   para una conversación ya abierta) reconocía una pregunta de catálogo
   reformulada — así que cualquier mensaje no reconocido rebotaba entre
   la pregunta fija de sí/no y el mismo "sin disponibilidad".

Corrección: `intent.py`/`brain.py` reconocen la pregunta de catálogo
(antes de que cualquier otra cosa la clasifique como reserva) y
responden con `AppointmentService.list_services()` — el catálogo REAL,
nunca inventado.
"""
from domains.health import (
    MockActivitySource, MockActivityResultSink, ReminderManager,
    build_health_gateway, handle_inbound_message,
)
from domains.health.appointment_service import MockAppointmentService
from domains.health.gateway import find_open_context


class _AppointmentServiceSinCatalogo(MockAppointmentService):
    """Mismo comportamiento que MockAppointmentService, pero SIN
    `list_services()` — para probar que su ausencia (duck-typing, mismo
    criterio que `buscar_paciente`) cae al mensaje genérico en vez de
    fallar o inventar un catálogo."""

    list_services = None


def test_pregunta_por_catalogo_sin_servicio_especifico_lista_catalogo_real(gateway):
    """Reproduce el mensaje real reportado: 'programar' no debe ganarle
    a una pregunta de catálogo solo por contener esa palabra."""
    respuesta = handle_inbound_message(
        gateway, "TG-CATALOGO-1", "telegram", "m1",
        "Programar cuál servicios tienes disponible",
    )
    assert "medicina general" in respuesta.lower()
    assert "sin disponibilidad" not in respuesta.lower()
    assert "por ahora no tengo horarios" not in respuesta.lower()


def test_pregunta_cual_tienes_tambien_lista_catalogo_real(gateway):
    respuesta = handle_inbound_message(gateway, "TG-CATALOGO-2", "telegram", "m1", "Cuál tienes")
    assert "medicina general" in respuesta.lower()


def test_catalogo_no_crea_ni_registra_una_conversacion_abierta(gateway):
    """La pregunta de catálogo es una respuesta directa (como
    CONSULTAR_CITA/ESCALAMIENTO) — no debe abrir una Activity de
    reserva sintética con un servicio jamás confirmado por el paciente."""
    handle_inbound_message(gateway, "TG-CATALOGO-3", "telegram", "m1", "qué servicios tienen")
    assert find_open_context(gateway, "TG-CATALOGO-3") is None


def test_reformular_dentro_de_una_conversacion_ya_atascada_sale_del_mensaje_fijo(gateway, services):
    """Reproduce el escenario completo real: sin disponibilidad para el
    servicio por defecto (aquí, drenado a propósito), el paciente
    reformula preguntando por el catálogo — antes de este fix, recibía
    el mismo mensaje fijo de 'sin disponibilidad' sin importar qué
    escribiera; ahora debe recibir el catálogo real."""
    appointment_service = services["appointment_service"]
    for slot in appointment_service.get_availability("medicina general"):
        appointment_service.book_appointment(slot.slot_id, "PAC-DRENAR", f"drain-{slot.slot_id}")
    assert appointment_service.get_availability("medicina general") == []

    pref = "TG-CATALOGO-4"
    r1 = handle_inbound_message(gateway, pref, "telegram", "m1", "Necesito una cita")
    assert "por ahora no tengo horarios disponibles" in r1.lower()

    r2 = handle_inbound_message(gateway, pref, "telegram", "m2", "Cuál tienes")
    assert "medicina general" in r2.lower()
    assert r2 != r1, "la conversación seguía devolviendo el mismo mensaje fijo tras reformular"


def test_lista_de_servicios_cae_a_mensaje_generico_si_appointment_service_no_lo_soporta():
    """Un `AppointmentService` que no implementa `list_services()`
    (duck-typing, igual que `buscar_paciente`) no debe fallar — cae al
    mensaje genérico existente, nunca inventa un catálogo."""
    gateway_sin_catalogo = build_health_gateway(
        MockActivitySource(), _AppointmentServiceSinCatalogo(),
        ReminderManager(), MockActivityResultSink(),
    )
    respuesta = handle_inbound_message(
        gateway_sin_catalogo, "TG-SIN-CATALOGO", "telegram", "m1", "qué servicios tienen",
    )
    assert "programar, reprogramar, cancelar" in respuesta.lower()
