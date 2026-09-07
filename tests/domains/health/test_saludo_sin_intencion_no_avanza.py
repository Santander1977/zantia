"""
Recado 048 — hallazgo real de producción: un paciente YA reconocido
(identidad resuelta) que escribe solo "hola" (sin ninguna intención
reconocible) recibía el saludo institucional + menú numerado (recado
046) PERO, en el MISMO turno, el sistema TAMBIÉN avanzaba de inmediato
al flujo de reserva (creaba una Activity sintética, preguntaba
"¿para cuál servicio te gustaría agendar?") — sin esperar a que el
paciente respondiera al menú.

Causa raíz (`domains/health/intent.py:classify_intent`): al no
reconocer ninguna palabra clave, SIEMPRE devolvía `RequestIntent.
PROGRAMAR_CITA` por defecto (decisión válida para un mensaje ambiguo
CON contenido, ej. "Sí, claro, ayúdame" — recado 030) — pero un saludo
puro no tiene ningún contenido que clasificar, y `_enrutar_solicitud_
nueva` (gateway.py) no distinguía ambos casos.

Corregido con `classify_intent_or_none` (nueva función en intent.py):
devuelve `None` quando el mensaje es ÚNICAMENTE un saludo — en ese caso
`_enrutar_solicitud_nueva` no crea ninguna PatientRequest/Activity, y
`handle_inbound_message` devuelve SOLO el saludo + menú. `classify_
intent` (usada por cualquier otro llamador) no cambia su contrato:
sigue defaulteando a PROGRAMAR_CITA para un saludo puro también,
preservando el comportamiento de siempre para quien lo necesite.
"""
import pytest

from domains.health import (
    MockActivitySource, MockActivityResultSink, ReminderManager,
    build_health_gateway, handle_inbound_message,
)
from domains.health.gateway import find_open_context
from domains.health.hrmm_appointment_service import HrmmAppointmentService
from domains.health.hrmm_catalog import CatalogMirror
from domains.health.hrmm_http import FakeHttpClient, HttpResponse
from domains.health.identity_store import SQLiteIdentidadCanalStore
from domains.health.intent import classify_intent, classify_intent_or_none
from domains.health.models import RequestIntent


# ---------------------------------------------------------------------
# 0. Unidad: `classify_intent_or_none` distingue "saludo puro" de
#    "ambiguo con contenido" — `classify_intent` no cambia su contrato.
# ---------------------------------------------------------------------
@pytest.mark.parametrize("saludo", ["hola", "Hola!", "buenas tardes", "¿Que tal?", "hey", "buenos dias"])
def test_classify_intent_or_none_saludo_puro_devuelve_none(saludo):
    assert classify_intent_or_none(saludo) is None
    # `classify_intent` (contrato de siempre) sigue defaulteando igual —
    # cero cambio de comportamiento para cualquier otro llamador.
    assert classify_intent(saludo) == RequestIntent.PROGRAMAR_CITA


def test_classify_intent_or_none_ambiguo_con_contenido_sigue_programando():
    """Regresión explícita del recado 030 — NO debe convertirse en
    `None` solo por no matchear ninguna palabra clave exacta."""
    assert classify_intent_or_none("Si claro ayudame puedes orientarme mejor") == RequestIntent.PROGRAMAR_CITA
    assert classify_intent_or_none("Si claro necesito tu ayuda") == RequestIntent.PROGRAMAR_CITA


def test_classify_intent_or_none_saludo_con_intencion_no_es_solo_saludo():
    """"hola, necesito una cita" SÍ tiene contenido — nunca debe
    tratarse como saludo puro."""
    assert classify_intent_or_none("hola, necesito una cita") == RequestIntent.PROGRAMAR_CITA


# ---------------------------------------------------------------------
# Fixture: HrmmAppointmentService real con 2 servicios (reproduce el
# catálogo real de producción, donde SÍ existe la pregunta "¿para cuál
# servicio?" — con un solo servicio, `_determinar_servicio_inicial`
# nunca pregunta, así que el hallazgo no sería observable).
# ---------------------------------------------------------------------
def _gateway_dos_servicios(monkeypatch):
    monkeypatch.setenv("HRMM_BACKEND_SECRET", "secreto-de-prueba-no-real")

    def generador(method, path, params, json_body, headers):
        if method == "GET" and path == "/api/agenda/servicios":
            return HttpResponse(200, [
                {"servicio_id": "S1", "nombre": "Medicina General"},
                {"servicio_id": "S2", "nombre": "Odontologia"},
            ])
        if method == "GET" and path == "/api/agenda/medicos":
            return HttpResponse(200, [])
        raise AssertionError(f"no programado en este test: {method} {path}")

    http = FakeHttpClient(generador=generador)
    catalog = CatalogMirror()
    catalog.sync(http)
    service = HrmmAppointmentService(http, catalog)
    identity_store = SQLiteIdentidadCanalStore(":memory:")
    gateway = build_health_gateway(
        MockActivitySource(), service, ReminderManager(), MockActivityResultSink(),
        identity_store=identity_store,
    )
    # Paciente YA reconocido (mismo escenario real reportado) — se salta
    # el gate de identidad, llega directo a `_enrutar_solicitud_nueva`.
    identity_store.marcar_verificado("chat-ya-conocido", "72302972", "Enzo")
    return gateway


# ---------------------------------------------------------------------
# 1. "hola" -> SOLO saludo + menú. Nunca avanza a preguntar servicio en
#    el mismo turno. Nada se crea todavía (ni PatientRequest ni Activity).
# ---------------------------------------------------------------------
def test_hola_sin_intencion_muestra_solo_saludo_y_menu(monkeypatch):
    gateway = _gateway_dos_servicios(monkeypatch)

    respuesta = handle_inbound_message(gateway, "chat-ya-conocido", "telegram", "m1", "hola")

    assert "1. reservar" in respuesta.lower() and "4. consultar" in respuesta.lower()
    assert "¿qué desea hacer hoy?" in respuesta.lower()
    assert "servicio" not in respuesta.lower(), f"no debía preguntar servicio en el mismo turno: {respuesta!r}"
    assert "fechas disponibles" not in respuesta.lower()

    assert gateway.patient_request_source.list_for_patient("chat-ya-conocido") == []
    assert find_open_context(gateway, "chat-ya-conocido") is None


# ---------------------------------------------------------------------
# 2. Tras "hola", responder "1" (o "reservar") SÍ avanza — en el turno
#    SIGUIENTE, nunca en el mismo. El saludo completo NO se repite.
# ---------------------------------------------------------------------
@pytest.mark.parametrize("respuesta_al_menu", ["1", "reservar"])
def test_tras_hola_responder_al_menu_avanza_a_pregunta_de_servicio(monkeypatch, respuesta_al_menu):
    gateway = _gateway_dos_servicios(monkeypatch)

    r1 = handle_inbound_message(gateway, "chat-ya-conocido", "telegram", "m1", "hola")
    assert "servicio" not in r1.lower()

    r2 = handle_inbound_message(gateway, "chat-ya-conocido", "telegram", "m2", respuesta_al_menu)
    assert "servicio" in r2.lower(), f"debía avanzar a preguntar servicio: {r2!r}"
    assert "medicina general" in r2.lower() and "odontologia" in r2.lower()
    # El saludo completo (presentación institucional) NO se repite en
    # este segundo turno — ya se mostró en el primero.
    assert "hospital regional del magdalena medio" not in r2.lower()
    assert "¿qué desea hacer hoy?" not in r2.lower()

    # Ahora sí existe una PatientRequest/Activity real.
    assert len(gateway.patient_request_source.list_for_patient("chat-ya-conocido")) == 1
    assert find_open_context(gateway, "chat-ya-conocido") is not None


# ---------------------------------------------------------------------
# 3. Un mensaje con intención CLARA en el primer turno sigue funcionando
#    de una vez (diseño no bloqueante, recado 046) — no pasa por el menú.
# ---------------------------------------------------------------------
def test_mensaje_con_intencion_clara_sigue_avanzando_de_una_vez(monkeypatch):
    gateway = _gateway_dos_servicios(monkeypatch)

    respuesta = handle_inbound_message(
        gateway, "chat-ya-conocido", "telegram", "m1", "necesito una cita de pediatría",
    )

    # Saludo + menú se antepone igual (guía visible siempre)...
    assert "1. reservar" in respuesta.lower() and "4. consultar" in respuesta.lower()
    # ...pero YA avanzó en el MISMO turno, sin esperar al menú.
    assert "servicio" in respuesta.lower()
    assert len(gateway.patient_request_source.list_for_patient("chat-ya-conocido")) == 1
    assert find_open_context(gateway, "chat-ya-conocido") is not None


# ---------------------------------------------------------------------
# 4. Un segundo "hola" (todavía sin intención) NO repite la presentación
#    completa — solo un recordatorio corto del menú.
# ---------------------------------------------------------------------
def test_segundo_hola_seguido_no_repite_la_presentacion_completa(monkeypatch):
    gateway = _gateway_dos_servicios(monkeypatch)

    r1 = handle_inbound_message(gateway, "chat-ya-conocido", "telegram", "m1", "hola")
    assert "hospital regional del magdalena medio" not in r1.lower()  # ya reconocido: sin presentación
    r2 = handle_inbound_message(gateway, "chat-ya-conocido", "telegram", "m2", "hola")

    assert "no logré identificar" in r2.lower()
    assert "1. reservar" in r2.lower() and "4. consultar" in r2.lower()
    assert gateway.patient_request_source.list_for_patient("chat-ya-conocido") == []
