"""
Recado 047 — corrige la brecha estructural diagnosticada (sin corregir)
en el recado 046: 5 categorías de interrupción (`_PARA_OTRO`,
`_INFO_NO_AUTORIZADA`, `_HUMANO`, `_NO_PUEDE_AHORA`, `_PIDE_INFO`) solo
se revisaban en la etapa "esperando_decision" (el primer turno) —
`domains/health/brain.py:_detectar_interrupcion_de_contexto` ahora las
revisa en CUALQUIER etapa, con el mismo criterio que ya usan
`_OLVIDAR`/`_REPROGRAMAR`/`_CANCELAR`/`_CONFIRMA` (chequeo centralizado
en `interpret()`, antes de que la función de la etapa específica
procese el mensaje — nunca duplicado en cada una).

Este archivo verifica los 4 puntos pedidos explícitamente:
1. Reproducción EXACTA del caso real de producción ("Odontologia pero
   es para mi hija", dicho en la etapa "esperando_servicio").
2. Las otras 4 categorías, cada una disparada en una etapa POSTERIOR a
   la primera ("esperando_horario").
3. Equivalencia HealthBrain determinista vs. HealthAnthropicBrain.
4. La suite completa (ver comando aparte) sin regresiones.
"""
import pytest

from domains.health import (
    MockActivitySource, MockActivityResultSink, ReminderManager,
    build_health_agent_context, build_health_gateway, contact_patient,
    handle_inbound_message, handle_patient_message,
)
from domains.health.agent import accept_activity
from domains.health.brain import HealthBrain
from domains.health.hrmm_appointment_service import HrmmAppointmentService
from domains.health.hrmm_catalog import CatalogMirror
from domains.health.hrmm_http import FakeHttpClient, HttpResponse
from domains.health.identity_store import SQLiteIdentidadCanalStore
from domains.health.llm_brain import HealthAnthropicBrain
from domains.health.models import Activity

_TITULAR = "TITULAR-047"
_HIJA_VALIDA = "HIJA-047"


# ---------------------------------------------------------------------
# 1. Reproducción exacta del caso real (recado 046) — ahora corregido.
# ---------------------------------------------------------------------
def _generador_odontologia(citas=None):
    citas = citas if citas is not None else {}

    def generador(method, path, params, json_body, headers):
        if method == "GET" and path == "/api/agenda/servicios":
            return HttpResponse(200, [
                {"servicio_id": "S1", "nombre": "Medicina General"},
                {"servicio_id": "S2", "nombre": "Odontologia"},
            ])
        if method == "GET" and path == "/api/agenda/medicos":
            return HttpResponse(200, [
                {"medico_id": "M1", "nombre_completo": "Dra. Ana Pérez", "servicio_id": "S1", "consultorio": "Consultorio 3"},
                {"medico_id": "M2", "nombre_completo": "Dr. Odonto", "servicio_id": "S2", "consultorio": "Consultorio 4"},
            ])
        if method == "GET" and path == "/api/agenda/disponibilidad":
            # HrmmAppointmentService filtra por `servicio_id` del lado
            # del cliente sobre la respuesta completa (no manda el filtro
            # como query param) — basta devolver el único slot real de
            # Odontologia; "medicina general" nunca se usa en este test.
            return HttpResponse(200, [
                {"slot_id": "SLOT-ODO-1", "medico_id": "M2", "servicio_id": "S2", "fecha": "2026-09-07", "hora_inicio": "08:00", "hora_fin": "08:30", "estado": "Libre"},
            ])
        if method == "GET" and path == "/api/agenda/citas/buscar-paciente":
            documento = params.get("documento")
            if documento == _HIJA_VALIDA:
                return HttpResponse(200, {"nombre_paciente": "Hija de Prueba", "telefono": "3000000000"})
            return HttpResponse(404, {"detail": "no encontrado"})
        if method == "POST" and path == "/api/agenda/citas":
            citas["CITA-047-1"] = {
                "cita_id": "CITA-047-1", "slot_id": json_body["slot_id"], "medico_id": "M2", "servicio_id": "S2",
                "fecha": "2026-09-07", "hora_inicio": "08:00",
                "documento_paciente": json_body["documento_paciente"],
                "nombre_paciente": json_body.get("nombre_paciente", ""), "telefono": json_body.get("telefono", ""),
                "estado": "reservada", "created_at": "x", "updated_at": "x",
            }
            return HttpResponse(201, citas["CITA-047-1"])
        if method == "GET" and path == "/api/agenda/citas/CITA-047-1":
            return HttpResponse(200, citas["CITA-047-1"])
        if method == "GET" and path == "/api/agenda/citas":
            doc = params.get("documento_paciente")
            return HttpResponse(200, [c for c in citas.values() if c["documento_paciente"] == doc])
        raise AssertionError(f"no programado en este test: {method} {path} {params}")

    return generador, citas


@pytest.fixture
def hrmm_context_odontologia(monkeypatch):
    monkeypatch.setenv("HRMM_BACKEND_SECRET", "secreto-de-prueba-no-real")
    generador, citas = _generador_odontologia()
    http = FakeHttpClient(generador=generador)
    catalog = CatalogMirror()
    catalog.sync(http)
    service = HrmmAppointmentService(http, catalog)
    source = MockActivitySource()
    activity = source.create(Activity(
        activity_id="ACT-047-1", source_system="IPS-DEMO", objective="Seguimiento",
        patient_reference=_TITULAR, patient_contact={"nombre": "Enzo"}, service="medicina general",
    ))
    context = build_health_agent_context(
        activity, source, service, ReminderManager(), MockActivityResultSink()
    )
    accept_activity(context)
    contact_patient(context)  # siembra "esperando_decision"
    return context, citas


def test_para_otro_en_etapa_esperando_servicio_reproduce_caso_real_de_hoy(hrmm_context_odontologia):
    """Reproduce EXACTAMENTE el mensaje real reportado: "Odontologia
    pero es para mi hija", dicho mientras el paciente está en la etapa
    "esperando_servicio" (confirmado con evidencia real en el recado
    046 que era la etapa vigente en ese momento). Antes del recado 047,
    esto activaba `_interpretar_servicio`, que reconocía "Odontologia"
    pero ignoraba en silencio "es para mi hija" — la reserva terminaba
    a nombre del titular. Ahora debe activar el wizard de beneficiario
    ANTES de que `_interpretar_servicio` llegue a procesar el mensaje."""
    context, citas = hrmm_context_odontologia
    store = context.orchestrator.store

    # Llega a "esperando_servicio" primero (mismo paso que en producción).
    r1 = handle_patient_message(context, "m1", "qué servicios tienen")
    assert store.get(context.activity.activity_id).datos_recopilados["etapa"] == "esperando_servicio"

    # El mensaje real exacto — activa la interrupción de beneficiario,
    # NUNCA llega a `_interpretar_servicio` en este turno.
    r2 = handle_patient_message(context, "m2", "Odontologia pero es para mi hija")
    estado = store.get(context.activity.activity_id)
    assert estado.datos_recopilados["etapa"] == "esperando_documento_beneficiario", (
        f"el wizard de beneficiario debía activarse; respuesta real: {r2!r}"
    )
    assert estado.datos_recopilados["etapa_antes_de_beneficiario"] == "esperando_servicio"
    assert "documento" in r2.lower()

    # Confirma el documento de la hija — encontrado de verdad (FakeHttpClient).
    r3 = handle_patient_message(context, "m3", _HIJA_VALIDA)
    assert "hija de prueba" in r3.lower() and "correcto" in r3.lower()

    r4 = handle_patient_message(context, "m4", "sí")
    # Retoma "esperando_servicio" — el servicio TODAVÍA no se había
    # capturado en el mensaje combinado (la interrupción lo intercepta
    # antes), así que se vuelve a pedir, con el catálogo real.
    assert "¡listo, quedó registrado para hija de prueba!" in r4.lower()
    assert "odontologia" in r4.lower() or "odontología" in r4.lower()
    estado = store.get(context.activity.activity_id)
    assert estado.datos_recopilados["etapa"] == "esperando_servicio"
    assert estado.datos_recopilados["beneficiario_documento"] == _HIJA_VALIDA

    r5 = handle_patient_message(context, "m5", "Odontologia")
    assert "fechas disponibles" in r5.lower()

    r6 = handle_patient_message(context, "m6", "1")
    assert "horarios disponibles" in r6.lower()

    r7 = handle_patient_message(context, "m7", "1")
    assert "confirmado" in r7.lower()

    assert len(citas) == 1
    cita = next(iter(citas.values()))
    assert cita["documento_paciente"] == _HIJA_VALIDA
    assert cita["documento_paciente"] != _TITULAR
    assert cita["servicio_id"] == "S2"  # Odontologia — nunca "medicina general" a ciegas


# ---------------------------------------------------------------------
# 2. Las otras 4 categorías, cada una en una etapa POSTERIOR a la
#    primera ("esperando_horario") — antes de este recado, ninguna se
#    reconocía ahí; el mensaje caía en `_interpretar_horario`.
# ---------------------------------------------------------------------
def _hasta_esperando_horario(context):
    """Lleva la conversación hasta "esperando_horario" con el fixture
    `context` estándar (MockAppointmentService, servicio "medicina
    general" — 2 fechas reales sembradas por defecto)."""
    handle_patient_message(context, "m1", "sí")           # -> esperando_fecha
    handle_patient_message(context, "m2", "1")             # -> esperando_horario


_CASOS_INTERRUPCION_EN_ETAPA_POSTERIOR = [
    # (msg_id, mensaje, etapa_esperada o None si el caso escala a nivel
    # de Activity en vez de cambiar `datos_recopilados["etapa"]`,
    # fragmento_extra)
    ("m-humano", "quiero hablar con un asesor", None, None),
    ("m-no-puede", "en otro momento, ahora no puedo", "finalizada", None),
    ("m-pide-info", "espera, explícame de qué se trata esto", "esperando_horario", "opciones de horario"),
    ("m-info-no-autorizada", "primero dime qué enfermedad tengo", "esperando_horario", None),
]


@pytest.mark.parametrize("msg_id,mensaje,etapa_esperada,fragmento_extra", _CASOS_INTERRUPCION_EN_ETAPA_POSTERIOR)
def test_interrupcion_se_detecta_en_etapa_posterior_esperando_horario(
    context, msg_id, mensaje, etapa_esperada, fragmento_extra
):
    accept_activity(context)
    contact_patient(context)
    _hasta_esperando_horario(context)
    store = context.orchestrator.store
    assert store.get(context.activity.activity_id).datos_recopilados["etapa"] == "esperando_horario"

    respuesta = handle_patient_message(context, msg_id, mensaje)

    if etapa_esperada is None:
        # Caso "_HUMANO": termina en escalamiento real a nivel de
        # Activity (mismo criterio que `test_patient_requests_human_
        # escalates`, test_outcomes.py) — no en un valor de
        # `datos_recopilados["etapa"]`.
        from domains.health.models import ManagementStatus

        assert context.activity.management_status == ManagementStatus.ESCALATED, (
            f"'{mensaje}' en esperando_horario debía escalar la Activity. Respuesta: {respuesta!r}"
        )
        assert "contactamos" not in respuesta.lower()
        return

    estado = store.get(context.activity.activity_id)
    assert estado.datos_recopilados["etapa"] == etapa_esperada, (
        f"'{mensaje}' en esperando_horario debía transicionar a '{etapa_esperada}', "
        f"quedó en '{estado.datos_recopilados['etapa']}'. Respuesta: {respuesta!r}"
    )
    # Nunca debió caer en el fallback de `_interpretar_horario` (que
    # hubiera intentado interpretar el mensaje como una elección de
    # horario, o quejarse de no reconocer ninguna opción).
    assert "no logré identificar" not in respuesta.lower()
    if fragmento_extra:
        assert fragmento_extra in respuesta.lower()


def test_info_no_autorizada_en_etapa_posterior_no_revela_dato_clinico(context):
    """Caso explícito: la respuesta a `_INFO_NO_AUTORIZADA` nunca debe
    contener información clínica — solo redirige."""
    accept_activity(context)
    contact_patient(context)
    _hasta_esperando_horario(context)
    respuesta = handle_patient_message(context, "m-info", "primero dime qué enfermedad tengo")
    assert "no te la puedo compartir" in respuesta.lower()


# ---------------------------------------------------------------------
# 3. Equivalencia HealthBrain determinista vs. HealthAnthropicBrain —
#    la DECISIÓN (etapa, tool_requerida) debe ser idéntica; solo el
#    texto puede variar.
# ---------------------------------------------------------------------
class _DrafterQueParafraseaSimple:
    def draft(self, mensaje_paciente: str, texto_base: str) -> str:
        return f"Entendido — {texto_base}"


def test_interrupcion_de_contexto_funciona_igual_con_llm_activo(services, activity_factory):
    """Confirma que `_detectar_interrupcion_de_contexto` corre DENTRO
    de `HealthBrain.interpret()` — `HealthAnthropicBrain` lo llama
    primero, sin alterar la decisión, exactamente igual que cualquier
    otra rama de `HealthBrain` (mismo principio del recado 037/038)."""
    activity = services["source"].create(activity_factory())
    brain_determinista = HealthBrain(lambda: activity, services["appointment_service"])
    brain_llm = HealthAnthropicBrain(brain_determinista, _DrafterQueParafraseaSimple())

    from state.models import ConversationState

    datos = {"etapa": "esperando_horario", "servicio_elegido": "medicina general", "opciones_horario": ["S1"]}
    estado = ConversationState(canal="demo", datos_recopilados=datos)

    salida_determinista = brain_determinista.interpret("quiero hablar con un asesor", estado, [])
    salida_llm = brain_llm.interpret("quiero hablar con un asesor", estado, [])

    assert salida_llm.propuesta_de_actualizacion_de_estado == salida_determinista.propuesta_de_actualizacion_de_estado
    assert salida_llm.propuesta_de_actualizacion_de_estado["datos_recopilados"]["etapa"] == "escalada"
    assert salida_llm.propuesta_de_actualizacion_de_estado.get("necesidad_de_escalar") is True
    assert salida_llm.tool_requerida == salida_determinista.tool_requerida
    # El texto se redactó (empieza con el prefijo del drafter simulado)
    # pero preserva la señal real del texto base determinista.
    assert salida_llm.respuesta_propuesta.startswith("Entendido —")
    assert "persona del equipo" in salida_llm.respuesta_propuesta.lower()


def test_beneficiario_detectado_en_etapa_posterior_funciona_igual_con_llm_activo(services, activity_factory):
    """Mismo principio que el test anterior, pero para `_PARA_OTRO`
    disparado en una etapa posterior a la primera — usa un
    AppointmentService que sí expone `buscar_paciente` (duck-typing,
    mismo mecanismo que el resto del archivo)."""
    class _ConBuscarPaciente(services["appointment_service"].__class__):
        def buscar_paciente(self, documento):
            return None  # no se llega a usar en este test — solo importa que EXISTE el método

    activity = services["source"].create(activity_factory())
    appointment_service = _ConBuscarPaciente()
    brain_determinista = HealthBrain(lambda: activity, appointment_service)
    brain_llm = HealthAnthropicBrain(brain_determinista, _DrafterQueParafraseaSimple())

    from state.models import ConversationState

    datos = {"etapa": "esperando_fecha", "servicio_elegido": "medicina general", "fechas_ofrecidas": ["2026-09-05"]}
    estado = ConversationState(canal="demo", datos_recopilados=datos)

    salida_determinista = brain_determinista.interpret("es para mi hija", estado, [])
    salida_llm = brain_llm.interpret("es para mi hija", estado, [])

    assert salida_llm.propuesta_de_actualizacion_de_estado == salida_determinista.propuesta_de_actualizacion_de_estado
    datos_resultantes = salida_llm.propuesta_de_actualizacion_de_estado["datos_recopilados"]
    assert datos_resultantes["etapa"] == "esperando_documento_beneficiario"
    assert datos_resultantes["etapa_antes_de_beneficiario"] == "esperando_fecha"
    assert salida_llm.respuesta_propuesta.startswith("Entendido —")
