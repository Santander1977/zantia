"""
Recado 052 — `SeleccionAsistidaPorLLMNoVerificadaGuardrail`: segunda
capa de defensa, independiente de la verificación que ya hace
`core.selection.interpret_selection` (ver `tests/core/test_selection.py`)
antes de devolver cualquier propuesta del LLM al dominio.

Aquí se prueba el GUARDRAIL en sí, construyendo un `GuardrailContext` a
mano con una `VerificacionDeSeleccion` deliberadamente inconsistente
(simula que, pese a la verificación interna del mecanismo, un Brain
futuro declarara una selección que no corresponde a ninguna opción
real) — mismo estilo de prueba ya usado para `DatoInventadoGuardrail`
en `tests/guardrails/test_guardrails_pre_llm.py`. Ejemplo
deliberadamente NO relacionado con salud.
"""
from guardrails.base import GuardrailContext, GuardrailDecision, VerificacionDeSeleccion
from guardrails.rules import SeleccionAsistidaPorLLMNoVerificadaGuardrail
from state.models import ConversationState


def _state(**overrides):
    return ConversationState(canal="demo", **overrides)


def _ctx(verificacion_de_seleccion):
    return GuardrailContext(
        state=_state(),
        proposed_state_changes={},
        proposed_tool=None,
        proposed_response="Listo, continuamos.",
        verificacion_de_seleccion=verificacion_de_seleccion,
    )


def test_bloquea_una_seleccion_alucinada_que_no_corresponde_a_ninguna_opcion_real():
    guardrail = SeleccionAsistidaPorLLMNoVerificadaGuardrail()
    verificacion = VerificacionDeSeleccion(
        opciones_reales_ids=["TRAMITE-A", "TRAMITE-B"],
        id_seleccionado_via_llm="TRAMITE-INVENTADO-999",
    )
    resultado = guardrail.evaluate(_ctx(verificacion))
    assert resultado.decision == GuardrailDecision.BLOCK
    assert "TRAMITE-INVENTADO-999" in resultado.reason
    assert "TRAMITE-A" in resultado.reason and "TRAMITE-B" in resultado.reason


def test_permite_una_seleccion_verificada_que_si_corresponde_a_una_opcion_real():
    guardrail = SeleccionAsistidaPorLLMNoVerificadaGuardrail()
    verificacion = VerificacionDeSeleccion(
        opciones_reales_ids=["TRAMITE-A", "TRAMITE-B"],
        id_seleccionado_via_llm="TRAMITE-B",
    )
    resultado = guardrail.evaluate(_ctx(verificacion))
    assert resultado.decision == GuardrailDecision.ALLOW


def test_permite_cuando_no_hubo_seleccion_asistida_por_llm_este_turno():
    """El caso normal (ordinal/texto exacto, sin LLM de por medio) —
    `id_seleccionado_via_llm=None` — nunca debe bloquear nada."""
    guardrail = SeleccionAsistidaPorLLMNoVerificadaGuardrail()
    verificacion = VerificacionDeSeleccion(opciones_reales_ids=["TRAMITE-A", "TRAMITE-B"])
    resultado = guardrail.evaluate(_ctx(verificacion))
    assert resultado.decision == GuardrailDecision.ALLOW


def test_permite_cuando_no_hay_verificacion_de_seleccion_en_absoluto():
    guardrail = SeleccionAsistidaPorLLMNoVerificadaGuardrail()
    resultado = guardrail.evaluate(_ctx(None))
    assert resultado.decision == GuardrailDecision.ALLOW
