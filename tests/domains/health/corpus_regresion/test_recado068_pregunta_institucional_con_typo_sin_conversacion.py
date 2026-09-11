"""
Recado 068, Parte 2 — hallazgo real:

  "Quiero saber dónde está el hospital" (con typo real, sin conversación
  abierta todavía) cayó en el mensaje genérico de menú ("No logré
  identificar qué necesitas...") en vez de responder con la
  información institucional real del hospital (recado 066).

CAUSA RAÍZ (confirmada leyendo `gateway.py:_enrutar_solicitud_nueva`):
la categoría "pregunta sobre información institucional" del recado 066
solo se conectó al detector centralizado DENTRO de una conversación ya
abierta (`HealthBrain._detectar_interrupcion_de_contexto`) — nunca al
fallback de menú principal (`_enrutar_solicitud_nueva`, sin
conversación abierta), el mismo hueco estructural que ya motivó los
recados 062/063 (un mecanismo construido en un lugar, nunca conectado
a todos los que lo necesitaban).

CORREGIDO: `_enrutar_solicitud_nueva` ahora reconoce la pregunta
institucional en dos niveles — coincidencia EXACTA (gratis, reutiliza
las MISMAS listas de brain.py) primero; si no matchea (ej. por un
typo), la interpretación asistida por LLM del recado 064
(`_clasificar_solicitud_nueva_via_llm`) ahora incluye
"informacion_institucional" como una categoría real más.
"""
import os

import pytest

from domains.health import MockActivitySource, MockActivityResultSink, ReminderManager
from domains.health.appointment_service import MockAppointmentService
from domains.health.gateway import build_health_gateway, handle_inbound_message
from domains.health.institutional_info import INFORMACION_HOSPITAL

_SKIP_REAL = pytest.mark.skipif(
    os.environ.get("ZANTIA_RUN_REAL_LLM_TESTS") != "1",
    reason="Pruebas de red real contra la API de Anthropic deshabilitadas por defecto — ver recado 038.",
)


class _ProposerLibreGenerico:
    """Mismo doble ya usado en `test_interpretacion_asistida_generalizada.py`
    (recado 064) — decide por fragmentos de texto simples, nunca
    vocabulario de dominio hardcodeado."""

    def __init__(self, mapa):
        self._mapa = mapa

    def propose(self, free_text, options):
        texto = free_text.lower()
        ids_reales = {o.id for o in options}
        for fragmento, id_esperado in self._mapa.items():
            if fragmento in texto and id_esperado in ids_reales:
                return id_esperado
        return None


def test_pregunta_institucional_exacta_responde_sin_necesitar_llm():
    """La forma SIN typo ya funciona de forma determinista, gratis
    (sin ningún `selection_proposer` configurado) — confirma que el
    camino exacto también quedó conectado, no solo el asistido por LLM."""
    gateway = build_health_gateway(MockActivitySource(), MockAppointmentService(), ReminderManager(), MockActivityResultSink())
    ref = "PAC-INST-EXACTO"
    handle_inbound_message(gateway, ref, "demo", "m1", "hola")
    r = handle_inbound_message(gateway, ref, "demo", "m2", "quiero saber donde queda el hospital")
    assert INFORMACION_HOSPITAL.direccion in r
    assert INFORMACION_HOSPITAL.telefono_citas in r


def test_pregunta_institucional_con_typo_via_llm_asistido():
    """Reproduce el hallazgo real: CON un typo real ('esta' por 'está'
    no cuenta como typo real de matching — se usa un typo genuino que
    de verdad rompe la coincidencia exacta), sin conversación abierta,
    con un LLM configurado (recado 064)."""
    proposer = _ProposerLibreGenerico({"ospital": "informacion_institucional"})
    gateway = build_health_gateway(
        MockActivitySource(), MockAppointmentService(), ReminderManager(), MockActivityResultSink(),
        selection_proposer=proposer,
    )
    ref = "PAC-INST-TYPO"
    handle_inbound_message(gateway, ref, "demo", "m1", "hola")
    r = handle_inbound_message(gateway, ref, "demo", "m2", "Kiero saber donde keda el ospital")
    assert "no logré identificar" not in r.lower(), f"debía reconocer la pregunta institucional pese al typo: {r!r}"
    assert INFORMACION_HOSPITAL.direccion in r
    assert INFORMACION_HOSPITAL.telefono_citas in r
    assert INFORMACION_HOSPITAL.correo_citas in r


def test_pregunta_institucional_con_typo_sin_llm_sigue_cayendo_al_fallback_generico():
    """Punto 4 del recado 064 (comportamiento sin cambios sin
    proposer): sin LLM configurado, un typo real que rompe la
    coincidencia exacta sigue sin reconocerse — comportamiento
    IDÉNTICO al de antes de este recado, no una regresión nueva."""
    gateway = build_health_gateway(MockActivitySource(), MockAppointmentService(), ReminderManager(), MockActivityResultSink())
    ref = "PAC-INST-TYPO-SIN-LLM"
    handle_inbound_message(gateway, ref, "demo", "m1", "hola")
    r = handle_inbound_message(gateway, ref, "demo", "m2", "Kiero saber donde keda el ospital")
    assert "no logré identificar" in r.lower()


@_SKIP_REAL
def test_real_pregunta_institucional_con_typo_via_llm_asistido():
    from core.selection import AnthropicSelectionProposer

    gateway = build_health_gateway(
        MockActivitySource(), MockAppointmentService(), ReminderManager(), MockActivityResultSink(),
        selection_proposer=AnthropicSelectionProposer(),
    )
    ref = "PAC-INST-TYPO-REAL"
    handle_inbound_message(gateway, ref, "demo", "m1", "hola")
    r = handle_inbound_message(gateway, ref, "demo", "m2", "Kiero saber donde keda el ospital, porfa")
    assert "no logré identificar" not in r.lower(), f"Claude real no reconoció la pregunta institucional: {r!r}"
    assert INFORMACION_HOSPITAL.direccion in r, f"Claude real no incluyó la dirección real: {r!r}"
