"""
Recado 043 — `OpinionPersonalGuardrail` (Core, agnóstico de dominio y
de TEMA): red de seguridad de código para el caso encontrado en el
recado 042 (Caso 6) — una presión sostenida y cortés, SIN ninguna
frase de manipulación explícita, en teoría podría lograr que un LLM
ceda y dé una opinión personal. Complementa a `FueraDeAlcanceGuardrail`
(que revisa el mensaje ENTRANTE), revisando el texto YA REDACTADO.
"""
from guardrails.base import GuardrailContext, GuardrailDecision
from guardrails.rules import OpinionPersonalGuardrail
from state.models import ConversationState


def _ctx(texto_redactado):
    return GuardrailContext(
        state=ConversationState(canal="demo"),
        proposed_state_changes={},
        proposed_tool=None,
        proposed_response=texto_redactado,
    )


# ---------------------------------------------------------------------
# 1. CRÍTICO — fuerza deliberadamente el caso de falla (requisito
#    explícito del pedido): un drafter que SÍ da una opinión política.
# ---------------------------------------------------------------------
def test_bloquea_una_opinion_politica_forzada():
    guardrail = OpinionPersonalGuardrail()
    texto = (
        "Yo creo que el presidente está haciendo un buen trabajo, pero volviendo a tu cita, "
        "estas son las fechas disponibles: 1) Lunes 7 de septiembre. ¿Cuál te queda mejor?"
    )
    resultado = guardrail.evaluate(_ctx(texto))
    assert resultado.decision == GuardrailDecision.MODIFY
    assert "presidente" not in resultado.modified_response.lower()
    assert "solo puedo ayudarte con la gestión de tu cita" in resultado.modified_response.lower()


def test_bloquea_otras_formas_de_opinion_personal():
    guardrail = OpinionPersonalGuardrail()
    casos = [
        "En mi opinión, ese equipo de fútbol es el mejor. Ahora, tus fechas disponibles son...",
        "Personalmente pienso que deberían cambiar esa ley. Volviendo a tu cita...",
        "Estoy a favor de esa medida, la verdad. Pero bueno, tus horarios son...",
    ]
    for texto in casos:
        resultado = guardrail.evaluate(_ctx(texto))
        assert resultado.decision == GuardrailDecision.MODIFY, f"no bloqueó: {texto!r}"


# ---------------------------------------------------------------------
# 2. Ningún falso positivo sobre reconocimiento empático (requisito
#    explícito #3 del pedido) — texto REAL del recado 042, Caso 6,
#    turno 1 (nunca tipeado a mano para este test).
# ---------------------------------------------------------------------
def test_no_bloquea_el_reconocimiento_empatico_real_del_recado_042():
    guardrail = OpinionPersonalGuardrail()
    texto_real = (
        "¡Entiendo la frustración! Volviendo a lo tuyo, tengo estas fechas disponibles para tu "
        "cita: sábado 5 de septiembre, domingo 6 de septiembre o lunes 7 de septiembre. "
        "¿Cuál te queda mejor?"
    )
    resultado = guardrail.evaluate(_ctx(texto_real))
    assert resultado.decision == GuardrailDecision.ALLOW


def test_no_bloquea_respuestas_normales_sin_ninguna_opinion():
    guardrail = OpinionPersonalGuardrail()
    textos = [
        "¡Claro que sí! Tengo estas fechas disponibles: 1) Lunes 7 de septiembre. ¿Cuál te queda mejor?",
        "Entiendo tu angustia y de verdad lamento que sea así. Por ahora no tengo horarios disponibles.",
        "¡Perfecto! Dame un segundo, voy a dejarlo reservado.",
    ]
    for texto in textos:
        resultado = guardrail.evaluate(_ctx(texto))
        assert resultado.decision == GuardrailDecision.ALLOW, f"falso positivo en: {texto!r}"
