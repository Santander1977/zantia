"""
Recado 041 — corrige un hallazgo real del recado 040: `DatoInventadoGuardrail`
comparaba valores permitidos por igualdad EXACTA de string, pero un LLM
real varía mayúsculas/minúsculas de un dato correcto por razones
puramente gramaticales (ej. "martes" en minúscula a mitad de oración,
nunca "Martes") — la comparación ahora es case-insensitive (decisión
explícita, documentada en el docstring de `DatoInventadoGuardrail`).
"""
from guardrails.base import GuardrailContext, GuardrailDecision, VerificacionDeDatos
from guardrails.rules import DatoInventadoGuardrail
from state.models import ConversationState


def _ctx(texto_redactado, verificaciones):
    return GuardrailContext(
        state=ConversationState(canal="demo"),
        proposed_state_changes={},
        proposed_tool=None,
        proposed_response=texto_redactado,
        verificaciones_de_datos=verificaciones,
    )


def test_permite_un_valor_real_mencionado_con_distinto_casing():
    guardrail = DatoInventadoGuardrail()
    verificacion = VerificacionDeDatos(
        nombre_categoria="fecha",
        patron=r"(?i)(?:Martes) \d de septiembre",
        valores_permitidos=["Martes 8 de septiembre"],
    )
    ctx = _ctx("para el martes 8 de septiembre...", [verificacion])
    assert guardrail.evaluate(ctx).decision == GuardrailDecision.ALLOW


def test_bloquea_un_valor_inventado_sin_importar_el_casing():
    guardrail = DatoInventadoGuardrail()
    verificacion = VerificacionDeDatos(
        nombre_categoria="fecha",
        patron=r"(?i)(?:Martes|Miércoles) \d de septiembre",
        valores_permitidos=["Martes 8 de septiembre"],
    )
    ctx = _ctx("para el miércoles 9 de septiembre...", [verificacion])
    resultado = guardrail.evaluate(ctx)
    assert resultado.decision == GuardrailDecision.BLOCK
    assert "miércoles 9 de septiembre" in resultado.reason.lower()
