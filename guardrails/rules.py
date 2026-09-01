"""
Reglas concretas de Guardrails.

Solo 3 reglas reales para el MVP (a propósito — no sobrearquitectura,
sección 29/31 del prompt maestro), cada una trazable a una lección
concreta ya documentada:

- SenalDeUrgenciaNoSePuedeBajarGuardrail: 004, sección 2.2 (Grupo D) —
  `senal_de_urgencia` solo la escribe una regla determinista, nunca el LLM.
- ConsentimientoRequeridoParaWriteGuardrail: 004, sección 17 — toda tool
  WRITE exige `consentimiento_datos` ya capturado.
- NoPrometerContactoGuardrail: 002 — lección directa de Dani ("nunca
  prometas contacto humano en un tiempo específico").
"""
from __future__ import annotations

from .base import Guardrail, GuardrailContext, GuardrailDecision, GuardrailResult

# Frases que Dani tenía explícitamente prohibidas por prompt, sin ningún
# guardrail real detrás (002, sección "Escalación humana"). Aquí sí hay
# código que lo verifica.
_PROMESAS_PROHIBIDAS = (
    "te contactamos",
    "te contactan",
    "te llamamos",
    "te llaman",
    "en breve te",
    "en unos minutos te",
)


class SenalDeUrgenciaNoSePuedeBajarGuardrail:
    name = "senal_de_urgencia_no_se_puede_bajar"

    def evaluate(self, context: GuardrailContext) -> GuardrailResult:
        intenta_bajarla = (
            context.state.senal_de_urgencia is True
            and context.proposed_state_changes.get("senal_de_urgencia") is False
        )
        if intenta_bajarla:
            return GuardrailResult(
                decision=GuardrailDecision.ESCALATE,
                reason=(
                    "Se intentó bajar senal_de_urgencia sin una regla "
                    "determinista explícita que lo autorice (004, sección 2.2)."
                ),
                guardrail_name=self.name,
            )
        return GuardrailResult(
            decision=GuardrailDecision.ALLOW, reason="sin conflicto", guardrail_name=self.name
        )


class ConsentimientoRequeridoParaWriteGuardrail:
    name = "consentimiento_requerido_para_write"

    def __init__(self, tool_categories: dict) -> None:
        # tool_categories: nombre_tool -> ToolCategory, inyectado por el
        # Orchestrator para no acoplar guardrails a tools/ directamente.
        self._tool_categories = tool_categories

    def evaluate(self, context: GuardrailContext) -> GuardrailResult:
        if context.proposed_tool is None:
            return GuardrailResult(
                decision=GuardrailDecision.ALLOW, reason="sin tool propuesta", guardrail_name=self.name
            )
        categoria = self._tool_categories.get(context.proposed_tool)
        es_write = categoria is not None and categoria.value == "WRITE"
        consentimiento_final = context.proposed_state_changes.get(
            "consentimiento_datos", context.state.consentimiento_datos
        )
        if es_write and not consentimiento_final:
            return GuardrailResult(
                decision=GuardrailDecision.BLOCK,
                reason=(
                    f"La tool '{context.proposed_tool}' es WRITE y "
                    "consentimiento_datos no está en true (004, sección 17)."
                ),
                guardrail_name=self.name,
            )
        return GuardrailResult(
            decision=GuardrailDecision.ALLOW, reason="consentimiento presente o no aplica", guardrail_name=self.name
        )


class NoPrometerContactoGuardrail:
    name = "no_prometer_contacto"

    def evaluate(self, context: GuardrailContext) -> GuardrailResult:
        texto = (context.proposed_response or "").lower()
        for frase in _PROMESAS_PROHIBIDAS:
            if frase in texto:
                return GuardrailResult(
                    decision=GuardrailDecision.MODIFY,
                    reason=f"Respuesta contenía una promesa prohibida ('{frase}') — lección de Dani (002).",
                    modified_response=(
                        "Voy a registrar tu caso para que el equipo lo revise. "
                        "No puedo garantizar un contacto ni un tiempo específico."
                    ),
                    guardrail_name=self.name,
                )
        return GuardrailResult(
            decision=GuardrailDecision.ALLOW, reason="sin promesas prohibidas", guardrail_name=self.name
        )
