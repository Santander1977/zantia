"""
Recado 034 — dos pedidos en un mismo trabajo:

1. Saludar y hablar con el nombre real del paciente. `identity_store.py`
   no guardaba el nombre (solo documento/estado/verificado_en) pese a
   que `buscar_paciente` ya lo devuelve durante el wizard de
   verificación — se agregó `IdentidadCanal.nombre`, persistido UNA
   SOLA VEZ en `marcar_verificado` (nunca se vuelve a consultar
   hrmm-backend solo para saludar). Un paciente reconocido
   automáticamente (fila ya VERIFICADA y vigente) ahora escucha su
   nombre en el saludo; el nombre también se usa al confirmar una
   reserva y al despedirse — nunca en cada mensaje.

2. Tono genuinamente humano: los mensajes de aclaración/fallback ahora
   rotan entre 2-3 variantes (determinista, vía un contador en
   `datos_recopilados` — nunca al azar, mismo criterio del resto del
   archivo) para que dos equivocaciones seguidas del paciente no
   reciban literalmente la misma frase.
"""
from domains.health import (
    MockActivitySource, MockActivityResultSink, ReminderManager,
    accept_activity, build_health_agent_context, build_health_gateway, contact_patient,
    handle_inbound_message, handle_patient_message,
)
from domains.health.hrmm_appointment_service import HrmmAppointmentService
from domains.health.hrmm_catalog import CatalogMirror
from domains.health.hrmm_http import FakeHttpClient, HttpResponse
from domains.health.identity_store import SQLiteIdentidadCanalStore
from domains.health.models import Activity


def _gateway_real(monkeypatch, citas_reales=None):
    monkeypatch.setenv("HRMM_BACKEND_SECRET", "secreto-de-prueba-no-real")
    citas_reales = citas_reales if citas_reales is not None else {}

    def generador(method, path, params, json_body, headers):
        if method == "GET" and path == "/api/agenda/servicios":
            return HttpResponse(200, [{"servicio_id": "S1", "nombre": "medicina general"}])
        if method == "GET" and path == "/api/agenda/medicos":
            return HttpResponse(200, [{"medico_id": "M1", "nombre_completo": "Dra. Ana Pérez", "servicio_id": "S1", "consultorio": "Consultorio 3"}])
        if method == "GET" and path == "/api/agenda/disponibilidad":
            return HttpResponse(200, [
                {"slot_id": "SLOT1", "medico_id": "M1", "servicio_id": "S1", "fecha": "2026-09-10", "hora_inicio": "09:00", "hora_fin": "09:30", "estado": "Libre"},
            ])
        if method == "POST" and path == "/api/agenda/citas":
            cita_id = "C-REAL-1"
            citas_reales[cita_id] = {
                "cita_id": cita_id, "slot_id": json_body["slot_id"], "medico_id": "M1", "servicio_id": "S1",
                "fecha": "2026-09-10", "hora_inicio": "09:00",
                "documento_paciente": json_body["documento_paciente"],
                "nombre_paciente": json_body.get("nombre_paciente", ""), "telefono": "",
                "estado": "agendada", "created_at": "x", "updated_at": "x",
            }
            return HttpResponse(201, citas_reales[cita_id])
        if method == "GET" and path.startswith("/api/agenda/citas/"):
            return HttpResponse(200, citas_reales[path.rsplit("/", 1)[-1]])
        if method == "GET" and path == "/api/agenda/citas":
            doc = params.get("documento_paciente")
            return HttpResponse(200, [c for c in citas_reales.values() if c["documento_paciente"] == doc])
        raise AssertionError(f"no programado en este test: {method} {path} {params}")

    http = FakeHttpClient(generador=generador)
    catalog = CatalogMirror()
    catalog.sync(http)
    service = HrmmAppointmentService(http, catalog)
    identity_store = SQLiteIdentidadCanalStore(":memory:")
    gateway = build_health_gateway(
        MockActivitySource(), service, ReminderManager(), MockActivityResultSink(),
        identity_store=identity_store,
    )
    return gateway, identity_store


# ---------------------------------------------------------------------
# 1. Ciclo completo de reserva, de punta a punta, con el nombre real.
# ---------------------------------------------------------------------
def test_ciclo_completo_termina_confirmado_con_nombre_del_paciente(monkeypatch):
    gateway, identity_store = _gateway_real(monkeypatch)
    identity_store.marcar_verificado("chat-Enzo", "999", "Enzo")

    r1 = handle_inbound_message(gateway, "chat-Enzo", "telegram", "m1", "necesito una cita")
    # Recado 046: el saludo simple "¡Hola, Enzo!" del recado 034 fue
    # reemplazado por el guion institucional completo (personalizado
    # para un paciente ya reconocido) — se verifica el contenido
    # esencial (tratamiento + nombre), no la frase literal vieja.
    assert "señor enzo" in r1.lower()
    assert "fechas disponibles" in r1.lower()

    r1b = handle_inbound_message(gateway, "chat-Enzo", "telegram", "m1b", "1")  # elige fecha (recado 035)
    assert "horarios disponibles" in r1b.lower()

    r2 = handle_inbound_message(gateway, "chat-Enzo", "telegram", "m2", "la primera")
    assert "enzo" in r2.lower(), "el nombre debe aparecer en un momento natural (confirmar la reserva)"
    assert "confirmado" in r2.lower()
    assert "no logré entender si es un sí o un no" not in r2.lower()


# ---------------------------------------------------------------------
# 2. Saludo con nombre para un paciente YA persistido — nunca para uno
#    nuevo que todavía no pasó por el wizard.
# ---------------------------------------------------------------------
def test_saludo_con_nombre_solo_para_paciente_ya_persistido(monkeypatch):
    gateway, identity_store = _gateway_real(monkeypatch)
    identity_store.marcar_verificado("chat-conocido", "999", "María")

    respuesta = handle_inbound_message(gateway, "chat-conocido", "telegram", "m1", "qué servicios tienen")
    # Recado 046: guion institucional completo — "señora María"
    # (heurística de tratamiento, ver `_tratamiento_formal`) + menú
    # numerado de 4 opciones.
    assert "señora maría" in respuesta.lower()
    assert "qué desea hacer hoy" in respuesta.lower()
    assert "1. reservar" in respuesta.lower() and "4. consultar" in respuesta.lower()


def test_paciente_nuevo_sigue_el_wizard_normal_sin_ningun_saludo_con_nombre(monkeypatch):
    gateway, _ = _gateway_real(monkeypatch, citas_reales={})
    # Documento nuevo, sin fila en identity_store: pasa por el wizard
    # de documento (buscar_paciente) — no hay ningún registro de él.
    respuesta = handle_inbound_message(gateway, "chat-nuevo", "telegram", "m1", "hola")
    assert "documento" in respuesta.lower()
    assert "¡hola," not in respuesta.lower()


def test_saludo_con_nombre_no_se_repite_en_el_turno_siguiente(monkeypatch):
    """El saludo es de reconocimiento (una sola vez); el turno
    siguiente de la MISMA conversación ya no debe repetirlo — evita
    sobreusar el nombre (pedido explícito del usuario)."""
    gateway, identity_store = _gateway_real(monkeypatch)
    identity_store.marcar_verificado("chat-Enzo2", "999", "Enzo")

    handle_inbound_message(gateway, "chat-Enzo2", "telegram", "m1", "necesito una cita")
    r2 = handle_inbound_message(gateway, "chat-Enzo2", "telegram", "m2", "cuál tienes")
    assert not r2.lower().startswith("¡hola, enzo!")


# ---------------------------------------------------------------------
# 3. Dos fallbacks seguidos en la misma conversación no repiten la
#    misma frase literal.
# ---------------------------------------------------------------------
def _iniciar(context):
    accept_activity(context)
    contact_patient(context)


def test_dos_fallbacks_de_si_no_seguidos_no_repiten_la_misma_frase(context):
    _iniciar(context)
    r1 = handle_patient_message(context, "m1", "Piensa")
    r2 = handle_patient_message(context, "m2", "Otra cosa rara")
    assert r1 != r2, "dos fallbacks seguidos no deben usar literalmente la misma frase"
    # Ambas siguen siendo la MISMA pregunta cerrada de sí/no de fondo.
    for r in (r1, r2):
        assert "sí" in r.lower() and "no" in r.lower()
        assert "agendar" in r.lower()


def test_tercer_fallback_puede_repetir_la_primera_variante_pero_no_la_segunda(context):
    """Con 3 variantes, el rotado es determinista: 1, 2, 3, 1, 2, 3...
    — confirma que la rotación es real (no solo "distinto una vez")."""
    _iniciar(context)
    r1 = handle_patient_message(context, "m1", "Piensa")
    r2 = handle_patient_message(context, "m2", "Otra cosa rara")
    r3 = handle_patient_message(context, "m3", "Ni idea")
    assert len({r1, r2, r3}) == 3, "las 3 primeras variantes deben ser todas distintas entre sí"


def test_variante_reconoce_que_el_paciente_escribio_algo(context):
    """Pedido #2 del usuario: al menos una variante debe reconocer
    explícitamente que hubo un mensaje, en vez de ignorarlo."""
    _iniciar(context)
    handle_patient_message(context, "m1", "Piensa")
    r2 = handle_patient_message(context, "m2", "Otra cosa rara")
    assert "vi tu mensaje" in r2.lower()


# ---------------------------------------------------------------------
# 4. Verificación de guardrails/identidad — sin regresiones.
# ---------------------------------------------------------------------
def test_guardrail_de_promesa_de_contacto_sigue_intacto():
    from guardrails.base import GuardrailContext
    from guardrails.rules import NoPrometerContactoGuardrail
    from state.models import ConversationState

    guardrail = NoPrometerContactoGuardrail()
    estado = ConversationState(conversation_id="c1", canal="demo")
    contexto = GuardrailContext(
        state=estado, proposed_state_changes={}, proposed_tool=None,
        proposed_response="Te contactamos en breve.",
    )
    resultado = guardrail.evaluate(contexto)
    assert resultado.decision.value == "MODIFY"
    assert "contactamos" not in resultado.modified_response.lower()
