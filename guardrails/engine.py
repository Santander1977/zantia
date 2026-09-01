"""
GuardrailEngine — ejecuta todas las reglas registradas y consolida un
único veredicto (004, sección 16: permitir / modificar / bloquear / escalar).

Orden de severidad: ESCALATE > BLOCK > MODIFY > ALLOW. Si dos reglas
disparan MODIFY, se aplican en orden de registro (la última modificación
gana sobre el texto, ambas quedan en el registro de razones).
"""
from __future__ import annotations

from typing import List

from .base import Guardrail, GuardrailContext, GuardrailDecision, GuardrailResult

_SEVERIDAD = {
    GuardrailDecision.ALLOW: 0,
    GuardrailDecision.MODIFY: 1,
    GuardrailDecision.BLOCK: 2,
    GuardrailDecision.ESCALATE: 3,
}


class GuardrailEngine:
    def __init__(self, rules: List[Guardrail]) -> None:
        self._rules = rules

    def evaluate(self, context: GuardrailContext) -> GuardrailResult:
        peor: GuardrailResult = GuardrailResult(
            decision=GuardrailDecision.ALLOW, reason="sin reglas activadas"
        )
        respuesta_modificada = None
        cambios_forzados: dict = {}
        razones: List[str] = []

        for regla in self._rules:
            resultado = regla.evaluate(context)
            razones.append(f"[{resultado.guardrail_name}] {resultado.reason}")
            if resultado.modified_response:
                respuesta_modificada = resultado.modified_response
            if resultado.forced_state_changes:
                cambios_forzados.update(resultado.forced_state_changes)
            if _SEVERIDAD[resultado.decision] > _SEVERIDAD[peor.decision]:
                peor = resultado

        return GuardrailResult(
            decision=peor.decision,
            reason=" | ".join(razones),
            modified_response=respuesta_modificada,
            forced_state_changes=cambios_forzados,
            guardrail_name=peor.guardrail_name,
        )
