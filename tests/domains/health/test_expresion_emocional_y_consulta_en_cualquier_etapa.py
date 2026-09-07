"""
Recado 053, Partes 2 y 3 — hallazgo real de producción: tras una
reserva exitosa (Activity cerrada, `_cerrar_si_definitivo`), el
paciente escribió "sabes que me deprime ir al medico". El sistema (a)
repitió el saludo institucional COMPLETO (violando el recado 048) y (b)
quedó en loop de "no logré identificar el servicio" durante varios
turnos, incluso al escribir literalmente "consultar mis citas" (opción
4 del menú).

Causa raíz confirmada con código: `classify_intent_or_none` (recado
048) solo trata como "sin intención" un mensaje que es ÚNICAMENTE un
saludo — cualquier otro texto sin palabra clave reconocida (incluida
una expresión emocional real) sigue cayendo al default histórico
(PROGRAMAR_CITA, recado 030), creando una Activity sintética nueva con
etapa "esperando_servicio". Una vez ahí, `_interpretar_opcion_menu`
(gateway.py) — el único lugar que reconocía "consultar mis citas" —
nunca se reevalúa: `HealthBrain._interpretar_servicio` solo sabe
comparar contra nombres de servicio reales, sin ningún conocimiento del
menú global (mismo patrón estructural que los recados 047/049/050: un
detector que solo vive en un camino de código).

Corregido con DOS categorías nuevas en el detector CENTRALIZADO ya
existente (`HealthBrain._detectar_interrupcion_de_contexto`, recado
047) — se revisan en CUALQUIER etapa, y además las hereda gratis la
ventana de gracia de un turno (recado 050, que ya reutiliza ese mismo
detector sobre una Activity recién cerrada):
- `_CONSULTA_CITAS_EXISTENTES` ("consultar mis citas", etc.) — lista
  las citas reales del paciente sin salir de la etapa vigente.
- `_EXPRESION_EMOCIONAL` ("me deprime", "estoy triste", etc.) —
  validación humana breve (nunca diagnóstico/consejo) + recordatorio
  BREVE de la pregunta vigente (`_RECORDATORIO_BREVE_POR_ETAPA`), sin
  repetir la presentación institucional completa ni reiniciar el flujo.

Este archivo verifica los 5 puntos pedidos explícitamente para las
Partes 2 y 3 (la Parte 1 — integridad de datos en la confirmación — se
verifica en `test_elegir_opcion_no_confunde_digito_con_ordinal.py`).
"""
import pytest

from domains.health import (
    MockActivitySource, MockActivityResultSink, ReminderManager,
    build_health_gateway, handle_inbound_message,
)
from domains.health.brain import HealthBrain
from domains.health.gateway import find_open_context
from domains.health.hrmm_appointment_service import HrmmAppointmentService
from domains.health.hrmm_catalog import CatalogMirror
from domains.health.hrmm_http import FakeHttpClient, HttpResponse
from domains.health.identity_store import SQLiteIdentidadCanalStore
from domains.health.models import Activity

_TITULAR = "TITULAR-053"
_PACIENTE = "chat-053"


def _gateway_multiservicio(monkeypatch):
    monkeypatch.setenv("HRMM_BACKEND_SECRET", "secreto-de-prueba-no-real")
    citas: dict = {}

    def generador(method, path, params, json_body, headers):
        if method == "GET" and path == "/api/agenda/servicios":
            return HttpResponse(200, [
                {"servicio_id": "S1", "nombre": "Medicina General"},
                {"servicio_id": "S2", "nombre": "Pediatria"},
                {"servicio_id": "S3", "nombre": "Odontologia"},
            ])
        if method == "GET" and path == "/api/agenda/medicos":
            return HttpResponse(200, [
                {"medico_id": "M1", "nombre_completo": "Dra. Medicina", "servicio_id": "S1", "consultorio": "C1"},
                {"medico_id": "M2", "nombre_completo": "Dr. Pediatra", "servicio_id": "S2", "consultorio": "C2"},
                {"medico_id": "M3", "nombre_completo": "Dra. Odonto", "servicio_id": "S3", "consultorio": "C3"},
            ])
        if method == "GET" and path == "/api/agenda/disponibilidad":
            return HttpResponse(200, [
                {"slot_id": "SLOT-S2-1", "medico_id": "M2", "servicio_id": "S2", "fecha": "2026-09-08", "hora_inicio": "09:00", "hora_fin": "09:30", "estado": "Libre"},
            ])
        if method == "POST" and path == "/api/agenda/citas":
            cita_id = f"CITA-053-{len(citas) + 1}"
            citas[cita_id] = {
                "cita_id": cita_id, "slot_id": json_body["slot_id"], "medico_id": "M2", "servicio_id": "S2",
                "fecha": "2026-09-08", "hora_inicio": "09:00",
                "documento_paciente": json_body["documento_paciente"],
                "nombre_paciente": json_body.get("nombre_paciente", ""), "telefono": "",
                "estado": "reservada", "created_at": "x", "updated_at": "x",
            }
            return HttpResponse(201, citas[cita_id])
        if method == "GET" and path.startswith("/api/agenda/citas/") and path != "/api/agenda/citas/buscar-paciente":
            cita_id = path.rsplit("/", 1)[-1]
            return HttpResponse(200, citas[cita_id])
        if method == "GET" and path == "/api/agenda/citas":
            doc = params.get("documento_paciente")
            return HttpResponse(200, [c for c in citas.values() if c["documento_paciente"] == doc])
        raise AssertionError(f"no programado en este test: {method} {path} {params} {json_body}")

    http = FakeHttpClient(generador=generador)
    catalog = CatalogMirror()
    catalog.sync(http)
    service = HrmmAppointmentService(http, catalog)
    identity_store = SQLiteIdentidadCanalStore(":memory:")
    gateway = build_health_gateway(
        MockActivitySource(), service, ReminderManager(), MockActivityResultSink(),
        identity_store=identity_store,
    )
    identity_store.marcar_verificado(_PACIENTE, _TITULAR, "Titular Cincuentaytres")
    return gateway, citas


def _reservar_pediatria(gateway):
    r1 = handle_inbound_message(gateway, _PACIENTE, "telegram", "m1", "necesito una cita")
    assert "servicio" in r1.lower()
    r2 = handle_inbound_message(gateway, _PACIENTE, "telegram", "m2", "Pediatria")
    assert "fechas disponibles" in r2.lower()
    r3 = handle_inbound_message(gateway, _PACIENTE, "telegram", "m3", "1")  # elige fecha
    assert "horarios disponibles" in r3.lower()
    r4 = handle_inbound_message(gateway, _PACIENTE, "telegram", "m4", "1")  # elige horario -> reserva
    assert "confirmado" in r4.lower()
    assert find_open_context(gateway, _PACIENTE) is None  # cerrada en este mismo turno
    return r4


# ---------------------------------------------------------------------
# 1. Reproducción EXACTA del caso real: reserva -> mensaje emocional ->
#    "consultar mis citas".
# ---------------------------------------------------------------------
def test_reproduce_el_bucle_real_mensaje_emocional_tras_reserva_luego_consultar_citas(monkeypatch):
    gateway, citas = _gateway_multiservicio(monkeypatch)
    _reservar_pediatria(gateway)
    assert len(citas) == 1

    # Mensaje real exacto (ventana de gracia, recado 050, hereda las
    # categorías nuevas del detector centralizado).
    r_emocional = handle_inbound_message(gateway, _PACIENTE, "telegram", "m5", "sabes que me deprime ir al medico")

    assert "hospital regional del magdalena medio" not in r_emocional.lower(), (
        f"no debía repetir la presentación institucional completa: {r_emocional!r}"
    )
    assert "entiendo" in r_emocional.lower()
    assert "servicio" not in r_emocional.lower()  # no reabrió el flujo de reserva
    # No creó ninguna Activity/PatientRequest NUEVA a raíz del mensaje
    # emocional — sigue habiendo exactamente la UNA de la reserva
    # legítima anterior, ninguna adicional.
    assert find_open_context(gateway, _PACIENTE) is None
    assert len(gateway.patient_request_source.list_for_patient(_PACIENTE)) == 1

    # Turno siguiente: la opción 4 del menú, texto EXACTO reportado —
    # ya no debe quedar en loop pidiendo el servicio.
    r_consulta = handle_inbound_message(gateway, _PACIENTE, "telegram", "m6", "consultar mis citas")
    assert "no logré identificar" not in r_consulta.lower(), f"quedó en el loop real: {r_consulta!r}"
    # Recado 054: fecha en formato humano en la lista, no ISO cruda.
    assert "pediatria" in r_consulta.lower() and "martes 8 de septiembre" in r_consulta.lower()


# ---------------------------------------------------------------------
# 2. Mensaje emocional MID-FLUJO (conversación abierta, no ligado al
#    cierre) — cualquier etapa, sin reiniciar ni repetir presentación.
# ---------------------------------------------------------------------
def test_mensaje_emocional_mid_flujo_en_esperando_fecha_no_reinicia(monkeypatch):
    gateway, _ = _gateway_multiservicio(monkeypatch)
    r1 = handle_inbound_message(gateway, _PACIENTE, "telegram", "m1", "necesito una cita")
    handle_inbound_message(gateway, _PACIENTE, "telegram", "m2", "Pediatria")  # -> esperando_fecha

    r_emocional = handle_inbound_message(gateway, _PACIENTE, "telegram", "m3", "estoy deprimido con todo esto")
    assert "entiendo" in r_emocional.lower()
    assert "fechas que te compartí" in r_emocional.lower()
    # Sigue exactamente en la misma etapa — la fecha real sigue vigente.
    r_retoma = handle_inbound_message(gateway, _PACIENTE, "telegram", "m4", "1")
    assert "horarios disponibles" in r_retoma.lower()


# ---------------------------------------------------------------------
# 3. Unidad — validación breve + recordatorio correcto por etapa, sin
#    diagnosticar/aconsejar, y consulta de citas reales en cualquier etapa.
# ---------------------------------------------------------------------
def _estado(datos):
    from state.models import ConversationState

    return ConversationState(canal="demo", datos_recopilados=datos)


def _brain():
    activity = Activity(
        activity_id="ACT-053-UNIT", source_system="IPS-DEMO", objective="Seguimiento",
        patient_reference=_TITULAR, patient_contact={"nombre": "Prueba"}, service="medicina general",
    )
    from domains.health.appointment_service import MockAppointmentService

    servicio = MockAppointmentService()
    return HealthBrain(lambda: activity, servicio), servicio


@pytest.mark.parametrize(
    "etapa,fragmento_esperado",
    [
        ("esperando_decision", "ayude a agendar"),
        ("esperando_servicio", "cuál servicio"),
        ("esperando_fecha", "fechas que te compartí"),
        ("esperando_horario", "horarios que te compartí"),
        ("esperando_seleccion_reprogramacion", "reprogramar te queda mejor"),
    ],
)
def test_respuesta_emocional_recuerda_la_pregunta_correcta_por_etapa(etapa, fragmento_esperado):
    brain, _ = _brain()
    datos = {"etapa": etapa}
    salida = brain.interpret("me deprime todo esto", _estado(datos), [])

    assert "entiendo" in salida.respuesta_propuesta.lower()
    assert fragmento_esperado in salida.respuesta_propuesta.lower()
    # Nunca diagnostica ni aconseja — solo la validación fija + el
    # recordatorio; ningún consejo/pregunta de seguimiento sobre cómo
    # se siente.
    assert "deberías" not in salida.respuesta_propuesta.lower()
    assert "te recomiendo" not in salida.respuesta_propuesta.lower()
    # No reinicia ni avanza: la etapa se preserva íntegra.
    assert salida.propuesta_de_actualizacion_de_estado["datos_recopilados"]["etapa"] == etapa


def test_consultar_mis_citas_funciona_en_cualquier_etapa_no_solo_primer_contacto():
    activity = Activity(
        activity_id="ACT-053-CONSULTA", source_system="IPS-DEMO", objective="Seguimiento",
        patient_reference=_TITULAR, patient_contact={"nombre": "Prueba"}, service="medicina general",
    )
    from domains.health.appointment_service import MockAppointmentService

    servicio = MockAppointmentService()
    slot_real = servicio.get_availability("medicina general")[0]
    cita = servicio.book_appointment(slot_real.slot_id, _TITULAR, "idem-053")
    servicio.confirm_appointment(cita.appointment_id)  # asegura al menos 1 cita real CONFIRMADA
    brain = HealthBrain(lambda: activity, servicio)

    salida = brain.interpret("mis citas", _estado({"etapa": "esperando_servicio"}), [])
    assert "medicina general" in salida.respuesta_propuesta.lower() or "cita(s) activa(s)" in salida.respuesta_propuesta.lower()
    assert salida.propuesta_de_actualizacion_de_estado["datos_recopilados"]["etapa"] == "esperando_servicio"


# ---------------------------------------------------------------------
# 4. El detector de riesgo real SIEMPRE gana — un mensaje de riesgo
#    genuino nunca se trata como "solo emocional".
# ---------------------------------------------------------------------
def test_mensaje_de_riesgo_real_sigue_escalando_pese_a_sonar_tambien_emocional(monkeypatch):
    gateway, _ = _gateway_multiservicio(monkeypatch)
    handle_inbound_message(gateway, _PACIENTE, "telegram", "m1", "necesito una cita")
    handle_inbound_message(gateway, _PACIENTE, "telegram", "m2", "Pediatria")  # -> esperando_fecha

    from domains.health.models import ManagementStatus

    respuesta = handle_inbound_message(
        gateway, _PACIENTE, "telegram", "m3", "esto es una emergencia, me siento muy mal y no doy más",
    )
    # Mensaje genérico de escalamiento del Core (riesgo, máxima
    # prioridad) — nunca la validación empática de "solo emocional".
    assert "voy a" in respuesta.lower() or "prioritario" in respuesta.lower()
    assert "fechas que te compartí" not in respuesta.lower()


# ---------------------------------------------------------------------
# 5. Compatibilidad con HealthAnthropicBrain — la decisión (etapa,
#    ausencia de tool_requerida) no cambia; el LLM puede variar la
#    calidez del texto sin alterar el recordatorio de contexto.
# ---------------------------------------------------------------------
class _DrafterQueVariaCalidezSinDiagnosticar:
    def draft(self, mensaje_paciente: str, texto_base: str) -> str:
        return texto_base.replace("Entiendo, y lamento que te sientas así.", "Te escucho, de verdad.")


def test_expresion_emocional_funciona_igual_con_llm_activo():
    from domains.health.llm_brain import HealthAnthropicBrain

    activity = Activity(
        activity_id="ACT-053-LLM", source_system="IPS-DEMO", objective="Seguimiento",
        patient_reference=_TITULAR, patient_contact={"nombre": "Prueba"}, service="medicina general",
    )
    from domains.health.appointment_service import MockAppointmentService

    brain_determinista = HealthBrain(lambda: activity, MockAppointmentService())
    brain_llm = HealthAnthropicBrain(brain_determinista, _DrafterQueVariaCalidezSinDiagnosticar())

    datos = {"etapa": "esperando_servicio"}
    estado = _estado(datos)
    salida_determinista = brain_determinista.interpret("estoy angustiada con esto", estado, [])
    salida_llm = brain_llm.interpret("estoy angustiada con esto", estado, [])

    assert salida_llm.propuesta_de_actualizacion_de_estado == salida_determinista.propuesta_de_actualizacion_de_estado
    assert salida_llm.tool_requerida is None
    assert "te escucho" in salida_llm.respuesta_propuesta.lower()
    assert "cuál servicio" in salida_llm.respuesta_propuesta.lower()
