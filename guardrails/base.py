"""
Contrato Orquestador <-> Guardrails (004, sección 16).

NO depende de instrucciones de prompt (a diferencia de Dani, donde las
14 secciones del system prompt eran, salvo el formato, puras
instrucciones de texto sin verificación de código — 002,
"Hallazgo transversal más importante"). Aquí cada regla es código real,
ejecutado después de que el Brain propone, antes de que el Orchestrator
escriba nada.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol

from state.models import ConversationState


class GuardrailDecision(str, Enum):
    ALLOW = "ALLOW"
    MODIFY = "MODIFY"
    BLOCK = "BLOCK"
    ESCALATE = "ESCALATE"


@dataclass
class VerificacionDeDatos:
    """Una categoría de dato verificable en la respuesta propuesta por
    el Brain (recado 037, preparación de guardrails antes de conectar
    un LLM real) — declarada SIEMPRE por el dominio/Brain, nunca por el
    Core: el Core no sabe qué es una "fecha", un "servicio" o un
    "consultorio", solo sabe aplicar un patrón de texto libre sobre
    `proposed_response` y comparar cada coincidencia contra una lista
    de valores confirmados como reales EN ESTE TURNO. Esto es lo que
    hace a `DatoInventadoGuardrail` (guardrails/rules.py) agnóstico de
    dominio y reutilizable por cualquier dominio futuro (no solo salud).

    `patron` es una expresión regular (aplicada con `re.findall` sobre
    `proposed_response`); cada coincidencia se compara por igualdad
    exacta contra `valores_permitidos`. `nombre_categoria` es solo para
    el mensaje de bloqueo (ej. "fecha", "número de pedido")."""

    nombre_categoria: str
    patron: str
    valores_permitidos: List[str]


@dataclass
class GuardrailContext:
    """Lo que el Orchestrator le entrega a Guardrails: la propuesta
    completa del Brain, más el estado vigente (004, sección 16)."""

    state: ConversationState
    proposed_state_changes: Dict[str, Any]
    proposed_tool: Optional[str]
    proposed_response: str
    # --- Campos agregados en el recado 037 (preparación pre-LLM) ---
    # Todos con default seguro para no romper ninguna construcción
    # existente de GuardrailContext (tests que arman el contexto a mano).
    mensaje_entrante: str = ""
    verificaciones_de_datos: List[VerificacionDeDatos] = field(default_factory=list)
    confirmacion_estructurada_para_write: bool = False
    # Recado 039 — ver `core.brain.BrainOutput.texto_base_para_comparacion`.
    texto_base_para_comparacion: Optional[str] = None


@dataclass
class GuardrailResult:
    decision: GuardrailDecision
    reason: str
    modified_response: Optional[str] = None
    forced_state_changes: Dict[str, Any] = field(default_factory=dict)
    guardrail_name: str = ""


class Guardrail(Protocol):
    name: str

    def evaluate(self, context: GuardrailContext) -> GuardrailResult: ...
