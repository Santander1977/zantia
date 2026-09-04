"""
Olvido de identidad de canal a pedido del paciente (recado 016,
extensión de R-20 — requisito de `.claude/rules/proteccion-datos-personales.md`:
"el usuario final tiene siempre disponible... la forma de... pedir su
eliminación"). `HealthBrain` (`domains/health/brain.py:_OLVIDAR`)
detecta la intención en CUALQUIER etapa de una conversación ya abierta,
pide confirmación explícita, y solo entonces `gateway.py`
(`_procesar_olvido_si_corresponde`) borra la fila real de
`identidad_canal` y registra `IDENTIDAD_ELIMINADA_A_PEDIDO` en EventLog.

Deliberadamente probado a través de `handle_inbound_message`
(`gateway.py`), NO directo contra `handle_patient_message` (`agent.py`,
como hace `test_beneficiario_gestion.py`) — el borrado real vive en
`gateway.py` (`identity_store` es un servicio del Gateway, no del
Context); un test que no pase por ahí nunca ejercitaría el borrado de
verdad, solo la propuesta del Brain.

Sin red real — mismo patrón de FakeHttpClient que el resto de
`tests/domains/health/test_hrmm_*.py`.
"""
import pytest

from domains.health import MockActivitySource, MockActivityResultSink, ReminderManager
from domains.health.gateway import build_health_gateway, handle_inbound_message, start_activity_and_register
from domains.health.hrmm_appointment_service import HrmmAppointmentService
from domains.health.hrmm_catalog import CatalogMirror
from domains.health.hrmm_http import FakeHttpClient, HttpResponse
from domains.health.identity_store import SQLiteIdentidadCanalStore
from domains.health.models import Activity

_TELEFONO = "573001112233"
_DOCUMENTO_VALIDO = "123456789"
_BENEFICIARIO_VALIDO = "BENEF-002"


@pytest.fixture(autouse=True)
def _secreto_de_prueba(monkeypatch):
    monkeypatch.setenv("HRMM_BACKEND_SECRET", "secreto-de-prueba-no-real")


def _generador(citas_por_documento=None):
    citas_por_documento = citas_por_documento or {}
    llamadas_reserva = []

    def generador(method, path, params, json_body, headers):
        if method == "GET" and path == "/api/agenda/servicios":
            return HttpResponse(200, [{"servicio_id": "S1", "nombre": "medicina general"}])
        if method == "GET" and path == "/api/agenda/medicos":
            return HttpResponse(200, [{"medico_id": "M1", "nombre_completo": "Dra. Ana Pérez", "servicio_id": "S1", "consultorio": "Consultorio 3"}])
        if method == "GET" and path == "/api/agenda/disponibilidad":
            return HttpResponse(200, [
                {"slot_id": "SLOT1", "medico_id": "M1", "servicio_id": "S1", "fecha": "2026-09-10", "hora_inicio": "09:00", "hora_fin": "09:30", "estado": "Libre"},
            ])
        if method == "GET" and path == "/api/agenda/citas/buscar-paciente":
            documento = params.get("documento")
            if documento in (_DOCUMENTO_VALIDO,):
                return HttpResponse(200, {"nombre_paciente": "Paciente de Prueba", "telefono": _TELEFONO})
            if documento == _BENEFICIARIO_VALIDO:
                return HttpResponse(200, {"nombre_paciente": "Rosa Pérez", "telefono": "3009999999"})
            return HttpResponse(404, {"detail": "no encontrado"})
        if method == "GET" and path == "/api/agenda/citas":
            documento = params.get("documento_paciente")
            return HttpResponse(200, citas_por_documento.get(documento, []))
        if method == "POST" and path == "/api/agenda/citas":
            llamadas_reserva.append(json_body)
            return HttpResponse(201, {
                "cita_id": "C1", "slot_id": json_body["slot_id"], "medico_id": "M1", "servicio_id": "S1",
                "fecha": "2026-09-10", "hora_inicio": "09:00",
                "documento_paciente": json_body["documento_paciente"],
                "nombre_paciente": json_body.get("nombre_paciente", ""), "telefono": json_body.get("telefono", ""),
                "estado": "reservada", "created_at": "x", "updated_at": "x",
            })
        if method == "GET" and path == "/api/agenda/citas/C1":
            documento = llamadas_reserva[-1]["documento_paciente"] if llamadas_reserva else ""
            return HttpResponse(200, {
                "cita_id": "C1", "slot_id": "SLOT1", "medico_id": "M1", "servicio_id": "S1",
                "fecha": "2026-09-10", "hora_inicio": "09:00", "documento_paciente": documento,
                "nombre_paciente": "", "telefono": "", "estado": "reservada",
                "created_at": "x", "updated_at": "x",
            })
        raise AssertionError(f"no programado en este test: {method} {path} {params}")

    return generador, llamadas_reserva


def _gateway_con_identidad_ya_verificada(citas_por_documento=None):
    store = SQLiteIdentidadCanalStore(":memory:")
    store.marcar_verificado(_TELEFONO, _DOCUMENTO_VALIDO)
    generador, llamadas_reserva = _generador(citas_por_documento)
    http = FakeHttpClient(generador=generador)
    catalog = CatalogMirror()
    catalog.sync(http)
    service = HrmmAppointmentService(http, catalog)
    gateway = build_health_gateway(
        MockActivitySource(), service, ReminderManager(), MockActivityResultSink(),
        identity_store=store,
    )
    return gateway, store, llamadas_reserva


def _abrir_conversacion(gateway):
    """Identidad ya resuelta (fixture) — un primer mensaje de intención
    abre una Activity sintética (PROGRAMAR_CITA, vía
    `_resolver_programar_cita`), dejando `find_open_context` disponible
    para el resto de la conversación — mismo mecanismo de correlación de
    007/008, sin tocar."""
    handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m1", "hola quiero una cita")


def _eventos_de_olvido(gateway):
    activity_id = gateway._open_conversations[_TELEFONO]
    context = gateway._contexts[activity_id]
    return [
        e for e in context.orchestrator.events.for_conversation(activity_id)
        if e.payload.get("evento") == "IDENTIDAD_ELIMINADA_A_PEDIDO"
    ]


# ---------------------------------------------------------------------
# Requisito #3: pide confirmación antes de ejecutar cualquier borrado.
# ---------------------------------------------------------------------
def test_pide_confirmacion_antes_de_borrar():
    gateway, store, _ = _gateway_con_identidad_ya_verificada(citas_por_documento={_DOCUMENTO_VALIDO: []})
    _abrir_conversacion(gateway)

    respuesta = handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m2", "olvida mi información")

    assert "confirmas" in respuesta.lower()
    registro = store.get(_TELEFONO)
    assert registro is not None  # nada se borró todavía
    assert registro.estado.value == "VERIFICADO"
    assert _eventos_de_olvido(gateway) == []


# ---------------------------------------------------------------------
# Requisitos #4/#6: confirmado -> borra de verdad y registra el evento.
# ---------------------------------------------------------------------
def test_confirmado_borra_la_fila_y_registra_evento():
    gateway, store, _ = _gateway_con_identidad_ya_verificada(citas_por_documento={_DOCUMENTO_VALIDO: []})
    _abrir_conversacion(gateway)
    handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m2", "olvida mi información")

    respuesta = handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m3", "sí, confirmo")

    assert "olvidé" in respuesta.lower()
    assert store.get(_TELEFONO) is None  # borrado REAL, no un cambio de estado
    assert _TELEFONO not in gateway._identidad_resuelta

    eventos = _eventos_de_olvido(gateway)
    assert len(eventos) == 1
    assert eventos[0].payload["telefono"] == _TELEFONO
    assert eventos[0].payload["documento"] == _DOCUMENTO_VALIDO


# ---------------------------------------------------------------------
# Requisito #6 (variante "dice que no"): NO confirma -> la fila NO se borra.
# ---------------------------------------------------------------------
def test_declina_no_borra_nada():
    gateway, store, _ = _gateway_con_identidad_ya_verificada(citas_por_documento={_DOCUMENTO_VALIDO: []})
    _abrir_conversacion(gateway)
    handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m2", "olvida mi información")

    respuesta = handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m3", "no, mejor no")

    assert "no voy a borrar" in respuesta.lower()
    registro = store.get(_TELEFONO)
    assert registro is not None
    assert registro.estado.value == "VERIFICADO"
    assert gateway._identidad_resuelta[_TELEFONO] == _DOCUMENTO_VALIDO
    assert _eventos_de_olvido(gateway) == []


def test_declina_restaura_la_etapa_anterior_y_la_conversacion_continua():
    """La solicitud de olvido interrumpida sin confirmar no debe perder
    el lugar del paciente en la conversación — mismo criterio que el
    resto del dominio (nunca dejar una conversación en un limbo)."""
    gateway, store, llamadas_reserva = _gateway_con_identidad_ya_verificada(citas_por_documento={_DOCUMENTO_VALIDO: []})
    _abrir_conversacion(gateway)  # etapa: esperando_decision

    handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m2", "olvida mi información")
    handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m3", "no")

    # La conversación sigue exactamente donde estaba tras `_abrir_conversacion`
    # (que ya avanzó a "esperando_seleccion", ofreciendo opciones) — elegir
    # la opción 1 ahora completa la reserva con normalidad, prueba de que
    # el interrupt de olvido no dejó nada corrompido.
    r3 = handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m4", "1")
    assert "confirmado" in r3.lower()
    assert len(llamadas_reserva) == 1
    assert llamadas_reserva[0]["documento_paciente"] == _DOCUMENTO_VALIDO


# ---------------------------------------------------------------------
# Requisito #5: no interfiere con la gestión de beneficiario (013).
#
# Usa el camino OUTBOUND (`build_health_agent_context`/`contact_patient`,
# mismo fixture que `test_beneficiario_gestion.py`) en vez de
# `_abrir_conversacion`: la declaración de beneficiario ("es para mi
# mamá") solo se reconoce en la etapa "esperando_decision"
# (`brain.py:_interpretar_decision`), y el camino INBOUND vía
# `_resolver_programar_cita` la salta automáticamente (traduce el primer
# mensaje a "sí" — ver su docstring), aterrizando directo en
# "esperando_seleccion". Sin relación con `identity_store`: este test
# es sobre `HealthBrain` en sí, no sobre persistencia de canal.
# ---------------------------------------------------------------------
def test_no_interfiere_con_flujo_de_beneficiario():
    from domains.health.agent import accept_activity, build_health_agent_context, contact_patient
    from domains.health.agent import handle_patient_message as hpm

    generador, llamadas_reserva = _generador()
    http = FakeHttpClient(generador=generador)
    catalog = CatalogMirror()
    catalog.sync(http)
    service = HrmmAppointmentService(http, catalog)
    source = MockActivitySource()
    activity = source.create(Activity(
        activity_id="ACT-OLVIDO-BENEF", source_system="IPS-DEMO", objective="Seguimiento",
        patient_reference=_DOCUMENTO_VALIDO, patient_contact={"nombre": "Juan"}, service="medicina general",
    ))
    context = build_health_agent_context(activity, source, service, ReminderManager(), MockActivityResultSink())
    accept_activity(context)
    contact_patient(context)  # siembra "esperando_decision"

    r1 = hpm(context, "m1", "es para mi mamá")
    assert "documento" in r1.lower()
    r2 = hpm(context, "m2", _BENEFICIARIO_VALIDO)
    assert "rosa pérez" in r2.lower()

    # Se arrepiente a mitad de la confirmación de beneficiario y pide
    # olvidar su identidad — no debe corromper `beneficiario_documento_candidato`.
    r3 = hpm(context, "m3", "olvida mi información")
    assert "confirmas" in r3.lower()
    estado_pendiente = context.orchestrator.store.get(context.activity.activity_id)
    assert estado_pendiente.datos_recopilados.get("beneficiario_documento_candidato") == _BENEFICIARIO_VALIDO
    hpm(context, "m4", "no")

    # El flujo de beneficiario sigue intacto, exactamente donde estaba
    # (etapa restaurada a "esperando_confirmacion_beneficiario").
    estado_restaurado = context.orchestrator.store.get(context.activity.activity_id)
    assert estado_restaurado.datos_recopilados.get("etapa") == "esperando_confirmacion_beneficiario"
    assert estado_restaurado.datos_recopilados.get("beneficiario_documento_candidato") == _BENEFICIARIO_VALIDO

    r4 = hpm(context, "m5", "sí")
    assert "opciones disponibles" in r4.lower()
    r5 = hpm(context, "m6", "1")
    assert "confirmado" in r5.lower()
    assert llamadas_reserva[0]["documento_paciente"] == _BENEFICIARIO_VALIDO


# ---------------------------------------------------------------------
# Requisito #5: no interfiere con el camino Activity (outbound), y el
# olvido en sí también funciona ahí (mismo mecanismo, canal distinto).
# ---------------------------------------------------------------------
def test_camino_activity_outbound_sigue_funcionando_igual():
    """Demanda inducida (outbound) completa, sin mencionar olvido en
    ningún momento — confirma que la sola EXISTENCIA de esta extensión
    no cambia el comportamiento ya probado del camino outbound."""
    store = SQLiteIdentidadCanalStore(":memory:")
    store.marcar_verificado(_TELEFONO, _DOCUMENTO_VALIDO)
    generador, llamadas_reserva = _generador(citas_por_documento={_DOCUMENTO_VALIDO: []})
    http = FakeHttpClient(generador=generador)
    catalog = CatalogMirror()
    catalog.sync(http)
    service = HrmmAppointmentService(http, catalog)
    gateway = build_health_gateway(
        MockActivitySource(), service, ReminderManager(), MockActivityResultSink(),
        identity_store=store,
    )

    activity = Activity(
        activity_id="ACT-OLVIDO-OUTBOUND", source_system="IPS-DEMO", objective="Seguimiento",
        patient_reference=_DOCUMENTO_VALIDO, patient_contact={"nombre": "Juan", "documento": _DOCUMENTO_VALIDO},
        service="medicina general",
    )
    start_activity_and_register(gateway, activity)

    r1 = handle_inbound_message(gateway, _DOCUMENTO_VALIDO, "demo", "m1", "sí")
    assert "opciones disponibles" in r1.lower()
    r2 = handle_inbound_message(gateway, _DOCUMENTO_VALIDO, "demo", "m2", "1")
    assert "confirmado" in r2.lower()
    assert len(llamadas_reserva) == 1

    # La fila de identidad de canal de OTRO teléfono (_TELEFONO, sin
    # relación con esta Activity outbound) queda intacta — el camino
    # outbound nunca la toca.
    assert store.get(_TELEFONO) is not None
