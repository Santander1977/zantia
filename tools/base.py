"""
Contrato uniforme para Tools (004, sección 17; prompt maestro sección 12).

Distinción READ / WRITE / NOTIFY con nivel de control diferenciado:
- READ: bajo control, el Orchestrator solo verifica disponibilidad.
- WRITE: alto control — exige `consentimiento_datos` (ver guardrails/rules.py)
  y se trata como potencialmente no-idempotente por defecto (004, sección 10).
- NOTIFY: control medio — se audita, nunca "promete" nada (lección de Dani).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Protocol


class ToolCategory(str, Enum):
    READ = "READ"
    WRITE = "WRITE"
    NOTIFY = "NOTIFY"


class ToolError(Exception):
    """Error de ejecución de una tool — el Orchestrator lo captura
    siempre (004, sección 17: 'error' es un caso de primera clase, nunca
    se propaga como una excepción no manejada)."""


@dataclass
class ToolResult:
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class Tool(Protocol):
    name: str
    description: str
    category: ToolCategory
    idempotent: bool

    def run(self, params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> ToolResult: ...
