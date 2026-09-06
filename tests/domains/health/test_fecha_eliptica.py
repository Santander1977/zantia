"""
Recado 043 — corrige un hallazgo real del recado 042: `_RE_FECHA`
(recados 040/041) solo reconocía la ÚLTIMA fecha de una lista cuando
Claude agrupa el mes una sola vez al final ("sábado 5, domingo 6 o
lunes 7 de septiembre", gramática elíptica natural en español) —
"sábado 5" y "domingo 6" quedaban invisibles para `DatoInventadoGuardrail`,
no por ser inventadas, sino porque el patrón nunca las reconocía como
candidatas.

Alternativa SIMPLE elegida (documentada en `domains/health/llm_brain.py`):
en vez de "recordar" el mes de la fecha más cercana, se acepta la forma
CORTA (día de la semana + número, sin mes) como una representación
válida ADICIONAL de cada fecha real ya confirmada — nunca se inventa
ni se asume ningún mes nuevo.
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
# 1. `_RE_FECHA` ahora reconoce la forma corta (sin mes) como candidata.
# ---------------------------------------------------------------------
def test_re_fecha_reconoce_dia_y_numero_sin_mes_en_una_lista():
    texto = "sábado 5, domingo 6 o lunes 7 de septiembre"
    assert _RE_FECHA.findall(texto) == ["sábado 5", "domingo 6", "lunes 7 de septiembre"]


def test_re_fecha_sigue_reconociendo_la_forma_completa_normal():
    """Control: el caso normal (cada fecha con su propio mes) no cambia."""
    texto = "Estas son las fechas disponibles: 1) Lunes 14 de septiembre; 2) Martes 15 de septiembre."
    assert _RE_FECHA.findall(texto) == ["Lunes 14 de septiembre", "Martes 15 de septiembre"]


# ---------------------------------------------------------------------
# 2. Fechas elípticas REALES (recado 042) ahora se permiten — antes de
#    este fix, ya se permitían mal (por no encontrarse), pero ahora se
#    permiten por la razón CORRECTA (se verificaron de verdad).
# ---------------------------------------------------------------------
def test_reproduce_el_hallazgo_del_recado_042_fechas_elipticas_reales_se_permiten():
    base = "Estas son las fechas disponibles: 1) Sábado 5 de septiembre; 2) Domingo 6 de septiembre; 3) Lunes 7 de septiembre. ¿Cuál te queda mejor?"
    redactado_real = (
        "¡Hola! Tengo estas fechas disponibles para tu cita: sábado 5, domingo 6 o lunes 7 "
        "de septiembre. ¿Cuál te queda mejor?"
    )
    assert DatoInventadoGuardrail().evaluate(_ctx(base, redactado_real)).decision == GuardrailDecision.ALLOW


# ---------------------------------------------------------------------
# 3. CRÍTICO: alucinación en formato elíptico — antes de este fix no se
#    habría detectado en absoluto (el patrón viejo ni encontraba
#    "miércoles 9" como candidata). Ahora SÍ debe bloquearse.
# ---------------------------------------------------------------------
def test_alucinacion_en_formato_eliptico_ahora_queda_bloqueada():
    base = "Estas son las fechas disponibles: 1) Jueves 10 de septiembre; 2) Viernes 11 de septiembre. ¿Cuál te queda mejor?"
    redactado_alucinado = (
        "¡Claro! También tengo el miércoles 9, jueves 10 o viernes 11 de septiembre. "
        "¿Cuál te queda mejor?"
    )
    resultado = DatoInventadoGuardrail().evaluate(_ctx(base, redactado_alucinado))
    assert resultado.decision == GuardrailDecision.BLOCK
    assert "miércoles 9" in resultado.reason.lower()


def test_alucinacion_eliptica_no_marca_las_fechas_reales_de_la_misma_lista_como_invalidas():
    """Las 2 fechas REALES de la lista (jueves 10, viernes 11) no deben
    figurar como inválidas en la razón del bloqueo — solo la inventada."""
    base = "Estas son las fechas disponibles: 1) Jueves 10 de septiembre; 2) Viernes 11 de septiembre. ¿Cuál te queda mejor?"
    redactado_alucinado = (
        "¡Claro! También tengo el miércoles 9, jueves 10 o viernes 11 de septiembre. ¿Cuál te queda mejor?"
    )
    resultado = DatoInventadoGuardrail().evaluate(_ctx(base, redactado_alucinado))
    assert resultado.decision == GuardrailDecision.BLOCK
    assert "['miércoles 9']" in resultado.reason
