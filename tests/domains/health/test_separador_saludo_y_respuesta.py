"""
Recado 080 — regresión real encontrada con una prueba end-to-end vía
WebChannel (curl -> eis-chat-hrmm local -> ZANTIA real en EasyPanel): el
saludo institucional/menú (recado 046) y el mensaje siguiente (pregunta
de documento, o la primera respuesta real) llegaban PEGADOS con un
espacio simple en `domains/health/gateway.py` — "5. Salir / terminar
¡Hola! Antes de seguir..." — ilegible en cualquier canal, no solo en Web.

Investigación (recado 080): `handle_inbound_message` SIEMPRE devuelve un
único string — no existe, en ningún punto del código, un mecanismo que
separe esto en 2 envíos reales por canal. `TelegramChannel`/`ChatwootChannel`
mandan ese mismo string ya concatenado en UN solo `send()`, igual que
`WebChannel` — el hallazgo de este recado corrige la causa raíz
compartida (el separador en `gateway.py`), no un comportamiento
específico de un canal. Confirmado con `git log -S` que la línea nació
con un espacio simple en el commit `f37e24d` (recado 046 Parte 2, que su
propio encabezado documenta como "no se probó Telegram") — es un hueco
desde el origen de la funcionalidad, nunca una regresión posterior.

Este archivo NO repite la cobertura funcional ya existente en
`test_saludo_institucional.py`/`test_identity_gate_telegram.py`/
`test_identity_gate_web.py` — solo verifica el SEPARADOR exacto entre
los 2 mensajes lógicos, en los 2 puntos reales de concatenación
(`gateway.py`, identificados por búsqueda exhaustiva de todo patrón
`f"{...} {...}"` en `gateway.py`/`brain.py` — únicos 2 casos reales de
"dos mensajes independientes pegados", el resto de coincidencias son
una sola frase con variables interpoladas, no un bug), y que el mismo
fix aplica igual a Telegram y a Web (ningún canal queda distinto)."""
import pytest

from domains.health import MockActivitySource, MockActivityResultSink, ReminderManager
from domains.health.gateway import build_health_gateway, handle_inbound_message
from domains.health.hrmm_appointment_service import HrmmAppointmentService
from domains.health.hrmm_catalog import CatalogMirror
from domains.health.hrmm_http import FakeHttpClient, HttpResponse
from domains.health.identity_store import SQLiteIdentidadCanalStore


@pytest.fixture(autouse=True)
def _secreto_de_prueba(monkeypatch):
    monkeypatch.setenv("HRMM_BACKEND_SECRET", "secreto-de-prueba-no-real")


def _gateway_hrmm_sin_identidad():
    def generador(method, path, params, json_body, headers):
        if method == "GET" and path == "/api/agenda/servicios":
            return HttpResponse(200, [{"servicio_id": "S1", "nombre": "medicina general"}])
        if method == "GET" and path == "/api/agenda/medicos":
            return HttpResponse(200, [])
        if method == "GET" and path == "/api/agenda/citas/buscar-paciente":
            return HttpResponse(200, {"nombre_paciente": "Paciente Nuevo", "telefono": "3000000000"})
        if method == "POST" and path == "/api/agenda/verificacion/enviar":
            return HttpResponse(200, {"enviado": True, "mensaje": "Código enviado.", "correo_parcial": "p***@x.com"})
        raise AssertionError(f"no programado en este test: {method} {path}")

    http = FakeHttpClient(generador=generador)
    catalog = CatalogMirror()
    catalog.sync(http)
    service = HrmmAppointmentService(http, catalog)
    return build_health_gateway(
        MockActivitySource(), service, ReminderManager(), MockActivityResultSink(),
        identity_store=SQLiteIdentidadCanalStore(":memory:"),
    )


# ---------------------------------------------------------------------
# Punto 1 (gateway.py, gate de identidad): saludo/menú + pregunta de
# documento — reproduce EXACTO el caso real reportado (curl vía
# WebChannel), confirmado también para "telegram" (mismo código, mismo
# bug, nunca antes probado ahí — ver docstring del módulo).
# ---------------------------------------------------------------------
@pytest.mark.parametrize("canal", ["telegram", "web", "chatwoot"])
def test_saludo_y_pregunta_de_documento_separados_por_doble_salto_de_linea(canal):
    gateway = _gateway_hrmm_sin_identidad()
    respuesta = handle_inbound_message(gateway, f"id-nuevo-{canal}", canal, "m1", "necesito una cita")

    assert "\n\n" in respuesta, f"[{canal}] el saludo y la pregunta de documento siguen pegados: {respuesta!r}"
    saludo, _, resto = respuesta.partition("\n\n")
    assert saludo.rstrip().endswith("5. Salir / terminar"), f"[{canal}] el menú no termina justo antes del separador: {saludo!r}"
    assert resto.lstrip().startswith("¡Hola!"), f"[{canal}] la pregunta de documento no empieza limpia tras el separador: {resto!r}"
    assert "documento" in resto.lower()
    # Nunca un triple salto ni espacios sueltos alrededor del separador —
    # `\n\n` limpio, ni más ni menos.
    assert "\n\n\n" not in respuesta
    assert " \n\n" not in respuesta and "\n\n " not in respuesta


# ---------------------------------------------------------------------
# Punto 2 (gateway.py, apertura de conversación sin gate de identidad):
# saludo/menú + primera respuesta real (ej. catálogo de servicios) —
# mismo separador, mismo criterio, canal SIN identity gate (Mock).
# ---------------------------------------------------------------------
def test_saludo_y_primera_respuesta_real_separados_por_doble_salto_de_linea():
    from domains.health.appointment_service import MockAppointmentService

    gateway = build_health_gateway(
        MockActivitySource(), MockAppointmentService(), ReminderManager(), MockActivityResultSink(),
    )
    respuesta = handle_inbound_message(gateway, "demo-nuevo-1", "demo", "m1", "que servicios tienen")

    assert "\n\n" in respuesta, f"el saludo y la respuesta del catálogo siguen pegados: {respuesta!r}"
    saludo, _, resto = respuesta.partition("\n\n")
    assert saludo.rstrip().endswith("5. Salir / terminar")
    assert len(resto.strip()) > 0
    assert "\n\n\n" not in respuesta


# ---------------------------------------------------------------------
# Confirma que el MISMO string (con el separador ya correcto) es
# exactamente lo que cada canal manda en su único `send()` — ningún
# canal transforma ni vuelve a concatenar nada por su cuenta.
# ---------------------------------------------------------------------
def test_telegram_channel_envia_el_string_ya_separado_sin_tocarlo(monkeypatch):
    from channels.contract import OutboundMessage
    from channels.telegram_channel import TelegramChannel

    chat_id = "987654321"  # TelegramChannel.send exige un chat_id numérico real
    gateway = _gateway_hrmm_sin_identidad()
    respuesta = handle_inbound_message(gateway, chat_id, "telegram", "m1", "necesito una cita")
    assert "\n\n" in respuesta

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token-de-prueba-no-real")
    llamadas = []
    canal = TelegramChannel(http_post=lambda url, body: (llamadas.append(body), {"ok": True, "result": {}})[1])
    canal.send(OutboundMessage(conversation_id=chat_id, text=respuesta))

    assert llamadas[0]["text"] == respuesta
    assert "\n\n" in llamadas[0]["text"]


def test_web_channel_envia_el_string_ya_separado_sin_tocarlo():
    from channels.contract import OutboundMessage
    from channels.web_channel import WebChannel

    gateway = _gateway_hrmm_sin_identidad()
    respuesta = handle_inbound_message(gateway, "session-web-1", "web", "m1", "necesito una cita")
    assert "\n\n" in respuesta

    canal = WebChannel()
    canal.send(OutboundMessage(conversation_id="session-web-1", text=respuesta))

    assert canal.sent[-1].text == respuesta
    assert "\n\n" in canal.sent[-1].text
