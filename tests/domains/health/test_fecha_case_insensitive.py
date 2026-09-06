"""
Recado 041 — corrige el hallazgo real del recado 040: `_RE_FECHA`
(`domains/health/llm_brain.py`) no reconocía fechas en minúscula
("el martes 8 de septiembre", como Claude las escribe siempre dentro
de una oración) — sin esto, `DatoInventadoGuardrail` nunca encontraba
NADA que verificar en el texto ya redactado por el LLM en ninguno de
los 5 casos reales del recado 040 (falsa sensación de cobertura, no
una alucinación real todavía).

Este archivo reproduce, con los textos REALES y literales del recado
040 (nunca gastando llamadas reales de nuevo — ya las tenemos), la
confirmación de que las fechas ahora SÍ se extraen correctamente, más
un test crítico que fuerza una alucinación en minúscula y confirma que
ahora SÍ queda bloqueada.
"""
from domains.health.llm_brain import _RE_FECHA, _construir_verificaciones_de_datos
from guardrails.base import GuardrailContext, GuardrailDecision
from guardrails.rules import DatoInventadoGuardrail
from state.models import ConversationState


def _ctx(texto_base, texto_redactado):
    return GuardrailContext(
        state=ConversationState(canal="demo"),
        proposed_state_changes={},
        proposed_tool=None,
        proposed_response=texto_redactado,
        verificaciones_de_datos=_construir_verificaciones_de_datos(texto_base),
    )


# ---------------------------------------------------------------------
# 1. `_RE_FECHA` ahora SÍ encuentra la fecha en minúscula.
# ---------------------------------------------------------------------
def test_re_fecha_encuentra_fecha_en_minuscula_como_claude_la_escribe():
    assert _RE_FECHA.findall("para el martes 8 de septiembre tengo...") == ["martes 8 de septiembre"]


# ---------------------------------------------------------------------
# 2. Los 5 casos reales del recado 040 — textos literales, reproducidos
#    como test de regresión (no llamadas reales de nuevo).
# ---------------------------------------------------------------------
def test_caso_1_recado_040_la_fecha_se_extrae_y_se_permite():
    base = "Estas son las fechas disponibles: 1) Jueves 10 de septiembre; 2) Viernes 11 de septiembre. ¿Cuál te queda mejor?"
    redactado = (
        "¡Claro que sí! Para tu cita de pediatría tengo estas fechas disponibles: "
        "el jueves 10 de septiembre o el viernes 11 de septiembre. ¿Cuál te queda mejor?"
    )
    assert _RE_FECHA.findall(redactado) == ["jueves 10 de septiembre", "viernes 11 de septiembre"]
    assert DatoInventadoGuardrail().evaluate(_ctx(base, redactado)).decision == GuardrailDecision.ALLOW


def test_caso_2_recado_040_sin_fecha_mencionada_sigue_funcionando():
    base = "Lamento decirte que por ahora no tengo horarios disponibles para ese servicio. Escríbeme más tarde y lo revisamos de nuevo con gusto."
    redactado = (
        "Entiendo tu angustia y de verdad lamento que sea así. Por ahora no tengo horarios "
        "disponibles para ese servicio, pero si me escribes más tarde, con gusto lo revisamos de nuevo."
    )
    assert DatoInventadoGuardrail().evaluate(_ctx(base, redactado)).decision == GuardrailDecision.ALLOW


def test_caso_3_recado_040_la_fecha_se_extrae_y_se_permite():
    base = "Estas son las fechas disponibles: 1) Sábado 5 de septiembre; 2) Domingo 6 de septiembre; 3) Lunes 7 de septiembre. ¿Cuál te queda mejor?"
    redactado = (
        "¡Claro! Tengo estas fechas disponibles para tu cita: sábado 5 de septiembre, "
        "domingo 6 de septiembre o lunes 7 de septiembre. ¿Cuál te queda mejor?"
    )
    assert _RE_FECHA.findall(redactado) == ["sábado 5 de septiembre", "domingo 6 de septiembre", "lunes 7 de septiembre"]
    assert DatoInventadoGuardrail().evaluate(_ctx(base, redactado)).decision == GuardrailDecision.ALLOW


def test_caso_4_recado_040_la_fecha_se_extrae_y_se_permite():
    base = "Para el Martes 8 de septiembre, estos son los horarios disponibles: 1) 09:00 en Sede Norte; 2) 10:30 en Consultorio 2. ¿Cuál prefieres?"
    redactado = (
        "Para el martes 8 de septiembre tengo estos horarios disponibles: "
        "09:00 en Sede Norte o 10:30 en Consultorio 2. ¿Cuál prefieres?"
    )
    assert _RE_FECHA.findall(redactado) == ["martes 8 de septiembre"]
    assert DatoInventadoGuardrail().evaluate(_ctx(base, redactado)).decision == GuardrailDecision.ALLOW


def test_caso_5_recado_040_la_fecha_se_extrae_y_se_permite():
    base = "Estas son las fechas disponibles: 1) Jueves 10 de septiembre; 2) Viernes 11 de septiembre. ¿Cuál te queda mejor?"
    redactado = (
        "¡Claro! Para pediatría tengo disponibles estas fechas: el jueves 10 de septiembre "
        "o el viernes 11 de septiembre. ¿Cuál te queda mejor?"
    )
    assert _RE_FECHA.findall(redactado) == ["jueves 10 de septiembre", "viernes 11 de septiembre"]
    assert DatoInventadoGuardrail().evaluate(_ctx(base, redactado)).decision == GuardrailDecision.ALLOW


# ---------------------------------------------------------------------
# 3. CRÍTICO: alucinación de fecha en minúscula — antes del fix del
#    recado 041, esto NO se bloqueaba (el guardrail no encontraba
#    ninguna fecha que verificar). Ahora SÍ debe bloquearse.
# ---------------------------------------------------------------------
def test_alucinacion_de_fecha_en_minuscula_ahora_queda_bloqueada():
    base = "Estas son las fechas disponibles: 1) Jueves 10 de septiembre; 2) Viernes 11 de septiembre. ¿Cuál te queda mejor?"
    redactado_alucinado = (
        "¡Claro! También tengo un cupo el miércoles 9 de septiembre si te viene mejor. "
        "¿Cuál te queda mejor?"
    )
    resultado = DatoInventadoGuardrail().evaluate(_ctx(base, redactado_alucinado))
    assert resultado.decision == GuardrailDecision.BLOCK
    assert "miércoles 9 de septiembre" in resultado.reason.lower()
