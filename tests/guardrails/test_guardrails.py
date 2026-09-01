"""Guardrail bloqueando acción (sección 28)."""
from guardrails.base import GuardrailContext, GuardrailDecision
from guardrails.rules import (
    ConsentimientoRequeridoParaWriteGuardrail,
    NoPrometerContactoGuardrail,
    SenalDeUrgenciaNoSePuedeBajarGuardrail,
)
from state.models import ConversationState
from tools.base import ToolCategory


def _state(**overrides):
    return ConversationState(canal="demo", **overrides)


def test_bloquea_write_sin_consentimiento():
    guardrail = ConsentimientoRequeridoParaWriteGuardrail({"schedule_event": ToolCategory.WRITE})
    ctx = GuardrailContext(
        state=_state(consentimiento_datos=False),
        proposed_state_changes={},
        proposed_tool="schedule_event",
        proposed_response="listo",
    )
    resultado = guardrail.evaluate(ctx)
    assert resultado.decision == GuardrailDecision.BLOCK


def test_permite_write_con_consentimiento():
    guardrail = ConsentimientoRequeridoParaWriteGuardrail({"schedule_event": ToolCategory.WRITE})
    ctx = GuardrailContext(
        state=_state(consentimiento_datos=True),
        proposed_state_changes={},
        proposed_tool="schedule_event",
        proposed_response="listo",
    )
    resultado = guardrail.evaluate(ctx)
    assert resultado.decision == GuardrailDecision.ALLOW


def test_permite_read_sin_consentimiento():
    guardrail = ConsentimientoRequeridoParaWriteGuardrail({"get_demo_info": ToolCategory.READ})
    ctx = GuardrailContext(
        state=_state(consentimiento_datos=False),
        proposed_state_changes={},
        proposed_tool="get_demo_info",
        proposed_response="listo",
    )
    resultado = guardrail.evaluate(ctx)
    assert resultado.decision == GuardrailDecision.ALLOW


def test_escala_si_se_intenta_bajar_senal_de_urgencia():
    guardrail = SenalDeUrgenciaNoSePuedeBajarGuardrail()
    ctx = GuardrailContext(
        state=_state(senal_de_urgencia=True),
        proposed_state_changes={"senal_de_urgencia": False},
        proposed_tool=None,
        proposed_response="ya pasó, seguimos con la venta",
    )
    resultado = guardrail.evaluate(ctx)
    assert resultado.decision == GuardrailDecision.ESCALATE


def test_modifica_respuesta_con_promesa_prohibida():
    guardrail = NoPrometerContactoGuardrail()
    ctx = GuardrailContext(
        state=_state(),
        proposed_state_changes={},
        proposed_tool=None,
        proposed_response="tranquilo, te contactamos en 10 minutos",
    )
    resultado = guardrail.evaluate(ctx)
    assert resultado.decision == GuardrailDecision.MODIFY
    assert "contactamos" not in resultado.modified_response
