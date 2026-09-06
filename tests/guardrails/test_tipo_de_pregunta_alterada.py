"""
Recado 039 — `TipoDePreguntaAlteradaGuardrail` (Core, agnóstico de
dominio): corrige un hallazgo real de la primera llamada real a Claude
(recado 038, "Caso 2") — el LLM convirtió una pregunta de selección
("¿Cuál prefieres?", con opciones ya enumeradas) en una pregunta de
sí/no ("¿Confirmamos esa cita?"), sin inventar ningún dato falso (por
eso `DatoInventadoGuardrail` no lo detecta — no es su trabajo).
"""
from guardrails.base import GuardrailContext, GuardrailDecision
from guardrails.rules import TipoDePreguntaAlteradaGuardrail
from state.models import ConversationState

# Textos reales, exactos, del recado 038 — reproducidos aquí como test
# de regresión, no reescritos ni parafraseados.
_CASO_2_TEXTO_BASE = (
    "Para el Martes 8 de septiembre, estos son los horarios disponibles: "
    "1) 09:00 en Sede Norte; 2) 10:30 en Consultorio 2. ¿Cuál prefieres?"
)
_CASO_2_TEXTO_REDACTADO_REAL = (
    "¡Perfecto! Entonces quedarías agendado el martes 8 de septiembre a las "
    "10:30 en Consultorio 2. ¿Confirmamos esa cita?"
)

_CASO_1_TEXTO_BASE = (
    "Estas son las fechas disponibles: 1) Lunes 7 de septiembre; "
    "2) Martes 8 de septiembre. ¿Cuál te queda mejor?"
)
_CASO_1_TEXTO_REDACTADO_REAL = (
    "¡Hola! Claro que sí, con gusto. Tengo estas fechas disponibles: el lunes 7 de "
    "septiembre o el martes 8 de septiembre. ¿Cuál se te acomoda mejor?"
)


def _state(**overrides):
    return ConversationState(canal="demo", **overrides)


def _ctx(texto_base, texto_redactado):
    return GuardrailContext(
        state=_state(),
        proposed_state_changes={},
        proposed_tool=None,
        proposed_response=texto_redactado,
        texto_base_para_comparacion=texto_base,
    )


# ---------------------------------------------------------------------
# 1. Reproduce el Caso 2 real EXACTO — debe bloquear.
# ---------------------------------------------------------------------
def test_caso_2_real_queda_bloqueado_y_se_restaura_el_texto_base():
    guardrail = TipoDePreguntaAlteradaGuardrail()
    ctx = _ctx(_CASO_2_TEXTO_BASE, _CASO_2_TEXTO_REDACTADO_REAL)
    resultado = guardrail.evaluate(ctx)
    assert resultado.decision == GuardrailDecision.MODIFY
    assert resultado.modified_response == _CASO_2_TEXTO_BASE


# ---------------------------------------------------------------------
# 2. Reproduce el Caso 1 real EXACTO (reformulación válida) — nunca
#    debe bloquearse, mismo tipo de pregunta preservado.
# ---------------------------------------------------------------------
def test_caso_1_real_reformulacion_valida_no_se_bloquea():
    guardrail = TipoDePreguntaAlteradaGuardrail()
    ctx = _ctx(_CASO_1_TEXTO_BASE, _CASO_1_TEXTO_REDACTADO_REAL)
    resultado = guardrail.evaluate(ctx)
    assert resultado.decision == GuardrailDecision.ALLOW


# ---------------------------------------------------------------------
# 3. Sin texto_base_para_comparacion (Brain 100% determinista, caso de
#    hoy sin LLM) — nunca interfiere.
# ---------------------------------------------------------------------
def test_sin_texto_base_para_comparacion_nunca_interfiere():
    guardrail = TipoDePreguntaAlteradaGuardrail()
    ctx = GuardrailContext(
        state=_state(), proposed_state_changes={}, proposed_tool=None,
        proposed_response="cualquier cosa, ¿confirmamos?",
    )
    assert guardrail.evaluate(ctx).decision == GuardrailDecision.ALLOW


# ---------------------------------------------------------------------
# 4. Texto base que NO es una pregunta de selección — no debe
#    interferir aunque el redactado sea distinto (evita falsos
#    positivos sobre mensajes que nunca tuvieron este patrón).
# ---------------------------------------------------------------------
def test_texto_base_sin_pregunta_de_seleccion_no_interfiere():
    guardrail = TipoDePreguntaAlteradaGuardrail()
    ctx = _ctx("¡Perfecto! Dame un segundo, voy a dejarlo reservado.", "¡Perfecto! Un momento, ya lo reservo.")
    assert guardrail.evaluate(ctx).decision == GuardrailDecision.ALLOW


def test_pregunta_de_seleccion_preservada_con_lista_numerada_en_ambos():
    guardrail = TipoDePreguntaAlteradaGuardrail()
    base = "Opciones: 1) A; 2) B. ¿Cuál eliges?"
    redactado = "Aquí tienes: 1) A o 2) B. ¿Cuál prefieres?"
    ctx = _ctx(base, redactado)
    assert guardrail.evaluate(ctx).decision == GuardrailDecision.ALLOW
