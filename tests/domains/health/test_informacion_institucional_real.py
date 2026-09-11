"""
Recado 066 — información institucional REAL del hospital (teléfono,
correo, dirección), confirmada por el usuario — única fuente de verdad
en `domains/health/institutional_info.py`. Cierra el hueco señalado
explícitamente como pendiente en el recado 064: `DatoInventadoGuardrail`
ahora también verifica teléfono/correo/dirección, con el MISMO
mecanismo ya usado para fecha/hora (recado 037/041).

Este archivo verifica los 4 puntos pedidos explícitamente:
1. La pregunta sobre el hospital incluye los 3 datos reales, exactos.
2. Una alucinación forzada (un dígito cambiado en la dirección o el
   teléfono) es bloqueada por el guardrail — mismo patrón de prueba que
   el recado 041 usó para fecha.
3. Al menos 1 prueba real contra la API de Anthropic.
4. Suite completa sin regresiones — confirmado por separado (ver
   recado 066).
"""
import os

import pytest

from domains.health import accept_activity, contact_patient, handle_patient_message
from domains.health.appointment_service import MockAppointmentService
from domains.health.brain import HealthBrain
from domains.health.institutional_info import INFORMACION_HOSPITAL
from domains.health.models import Activity

_SKIP_REAL = pytest.mark.skipif(
    os.environ.get("ZANTIA_RUN_REAL_LLM_TESTS") != "1",
    reason="Pruebas de red real contra la API de Anthropic deshabilitadas por defecto — ver recado 038.",
)


# ---------------------------------------------------------------------
# 1. Contenido determinista — sin ningún LLM de por medio.
# ---------------------------------------------------------------------
def test_pregunta_sobre_hospital_incluye_los_3_datos_reales_exactos():
    activity = Activity(
        activity_id="ACT-066", source_system="IPS-DEMO", objective="o",
        patient_reference="P", patient_contact={}, service="medicina general",
    )
    brain = HealthBrain(lambda: activity, MockAppointmentService())
    from state.models import ConversationState

    estado = ConversationState(canal="demo", datos_recopilados={"etapa": "esperando_fecha"})
    salida = brain.interpret("¿dónde queda el hospital?", estado, [])

    assert INFORMACION_HOSPITAL.direccion in salida.respuesta_propuesta
    assert INFORMACION_HOSPITAL.telefono_citas in salida.respuesta_propuesta
    assert INFORMACION_HOSPITAL.correo_citas in salida.respuesta_propuesta
    # Nunca cambia la etapa — mismo criterio que el resto del detector centralizado.
    assert salida.propuesta_de_actualizacion_de_estado["datos_recopilados"]["etapa"] == "esperando_fecha"


def test_pregunta_directa_por_telefono_o_correo_tambien_se_reconoce():
    """Recado 066 — la categoría se amplió para reconocer preguntas
    directas de contacto, no solo de ubicación."""
    activity = Activity(
        activity_id="ACT-066B", source_system="IPS-DEMO", objective="o",
        patient_reference="P", patient_contact={}, service="medicina general",
    )
    brain = HealthBrain(lambda: activity, MockAppointmentService())
    from state.models import ConversationState

    estado = ConversationState(canal="demo", datos_recopilados={"etapa": "esperando_servicio"})
    salida = brain.interpret("¿cuál es el teléfono para llamar?", estado, [])
    assert INFORMACION_HOSPITAL.telefono_citas in salida.respuesta_propuesta


# ---------------------------------------------------------------------
# 2. Guardrail anti-alucinación — mismo patrón exacto del recado 041
#    (fecha), aplicado ahora a dirección/teléfono.
# ---------------------------------------------------------------------
class _DrafterQueAlteraLaDireccion:
    """Cambia UN dígito de la dirección real ("119" -> "190") — el caso
    de alucinación más peligroso: casi correcto, fácil de no notar."""

    def draft(self, mensaje_paciente: str, texto_base: str) -> str:
        return texto_base.replace("57-119", "57-190")


class _DrafterQueAlteraElTelefono:
    def draft(self, mensaje_paciente: str, texto_base: str) -> str:
        return texto_base.replace(INFORMACION_HOSPITAL.telefono_citas, "607-6010199")


def _contexto_con_drafter(monkeypatch, drafter):
    monkeypatch.setenv("HEALTH_BRAIN_TYPE", "llm")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "clave-de-prueba-nunca-usada-en-red-real")
    monkeypatch.setattr("domains.health.llm_brain.AnthropicResponseDrafter", lambda **kwargs: drafter)

    from domains.health import (
        MockActivitySource, MockActivityResultSink, ReminderManager, build_health_agent_context,
    )

    source = MockActivitySource()
    activity = source.create(Activity(
        activity_id="ACT-066C", source_system="IPS-DEMO", correlation_id="corr-066c",
        objective="Facilitar programación de atención", patient_reference="PAC-066C",
        patient_contact={"nombre": "Paciente Ficticio"}, program="Programa de seguimiento cardiovascular",
        reason="Atención de seguimiento pendiente", service="medicina general",
    ))
    return build_health_agent_context(
        activity, source, MockAppointmentService(), ReminderManager(), MockActivityResultSink(),
    )


def test_guardrail_bloquea_direccion_alucinada_con_un_solo_digito_cambiado(monkeypatch):
    context = _contexto_con_drafter(monkeypatch, _DrafterQueAlteraLaDireccion())
    accept_activity(context)
    contact_patient(context)

    r1 = handle_patient_message(context, "m1", "¿dónde queda el hospital?")
    # Mismo criterio que `test_llm_brain.py` (recado 037/041): el
    # mensaje de BLOQUEO sí puede CITAR el valor detectado con fines de
    # auditoría — eso es esperado, no una filtración. Lo que importa es
    # que la acción se bloqueó de verdad, nunca que la cadena alterada
    # esté ausente del mensaje de auditoría.
    assert "no puedo continuar con esa acción todavía" in r1.lower()
    assert "dato_inventado" in r1.lower()
    assert "direccion' no confirmado" in r1.lower() or "direccion’ no confirmado" in r1.lower()


def test_guardrail_bloquea_telefono_alucinado(monkeypatch):
    context = _contexto_con_drafter(monkeypatch, _DrafterQueAlteraElTelefono())
    accept_activity(context)
    contact_patient(context)

    r1 = handle_patient_message(context, "m1", "¿cuál es el teléfono del hospital?")
    assert "no puedo continuar con esa acción todavía" in r1.lower()
    assert "dato_inventado" in r1.lower()
    assert "telefono' no confirmado" in r1.lower() or "telefono’ no confirmado" in r1.lower()


def test_control_positivo_direccion_real_sin_alterar_no_se_bloquea(monkeypatch):
    """Control: un drafter bien portado (reproduce el dato tal cual)
    NO debe activar el guardrail — evita falsos positivos."""

    class _DrafterQueParafraseaBien:
        def draft(self, mensaje_paciente: str, texto_base: str) -> str:
            return f"¡Claro que sí! {texto_base}"

    context = _contexto_con_drafter(monkeypatch, _DrafterQueParafraseaBien())
    accept_activity(context)
    contact_patient(context)

    r1 = handle_patient_message(context, "m1", "¿dónde queda el hospital?")
    assert INFORMACION_HOSPITAL.direccion in r1
    assert "no puedo continuar" not in r1.lower()


# ---------------------------------------------------------------------
# 3. Prueba REAL — DESHABILITADA por defecto (mismo patrón que
#    test_llm_brain.py, recado 038).
# ---------------------------------------------------------------------
@_SKIP_REAL
def test_real_pregunta_sobre_hospital_menciona_los_3_datos_reales_sin_alteracion(monkeypatch):
    monkeypatch.setenv("HEALTH_BRAIN_TYPE", "llm")

    from domains.health import (
        MockActivitySource, MockActivityResultSink, ReminderManager, build_health_agent_context,
    )

    source = MockActivitySource()
    activity = source.create(Activity(
        activity_id="ACT-066-REAL", source_system="IPS-DEMO", correlation_id="corr-066-real",
        objective="Facilitar programación de atención", patient_reference="PAC-066-REAL",
        patient_contact={"nombre": "Paciente Ficticio"}, program="Programa de seguimiento cardiovascular",
        reason="Atención de seguimiento pendiente", service="medicina general",
    ))
    context = build_health_agent_context(
        activity, source, MockAppointmentService(), ReminderManager(), MockActivityResultSink(),
    )
    accept_activity(context)
    contact_patient(context)

    r1 = handle_patient_message(context, "m1", "oye, y a todas estas ¿dónde queda el hospital exactamente?")
    assert INFORMACION_HOSPITAL.direccion in r1, f"Claude real alteró o no incluyó la dirección real: {r1!r}"
    assert INFORMACION_HOSPITAL.telefono_citas in r1, f"Claude real alteró o no incluyó el teléfono real: {r1!r}"
    assert INFORMACION_HOSPITAL.correo_citas in r1, f"Claude real alteró o no incluyó el correo real: {r1!r}"
