"""
Modelo formal de ConversationState.

Traduce a código real el contrato conceptual diseñado en
/Users/enzoalfonso/recado/004-contrato-estado-icaco.md (sección 2).

No es una copia 1:1 del documento: donde el documento marcó un campo
como "derivado, no se persiste" (datos_faltantes) o como "transitorio"
(proxima_accion, nivel_de_confianza), este modelo lo respeta.

Principio de autoridad (004, sección 8): el LLM (Brain) nunca instancia
ni escribe directamente este modelo. Solo el Orchestrator puede crear
o actualizar un ConversationState, y solo después de que el
GuardrailEngine apruebe los cambios propuestos (ver guardrails/).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FaseActual(str, Enum):
    """Estados de la máquina de estados (004, sección 6)."""

    INICIO = "INICIO"
    IDENTIFICACION_DE_INTENCION = "IDENTIFICACION_DE_INTENCION"
    RECOPILACION_DE_DATOS = "RECOPILACION_DE_DATOS"
    RAZONAMIENTO_DECISION = "RAZONAMIENTO_DECISION"
    ACCION = "ACCION"
    RESPUESTA = "RESPUESTA"
    MANEJO_DE_DUDA = "MANEJO_DE_DUDA"
    SEGUIMIENTO = "SEGUIMIENTO"
    PAUSA_POR_DATOS_FALTANTES = "PAUSA_POR_DATOS_FALTANTES"
    CIERRE = "CIERRE"
    ESCALADO_URGENTE = "ESCALADO_URGENTE"
    ESCALADO_ESTANDAR = "ESCALADO_ESTANDAR"
    # Propuesto en 004 sección 6, ausente en 003: desenlace real y
    # frecuente (el usuario deja de responder) que necesita su propio
    # estado terminal para no distorsionar métricas de cierre/escalamiento.
    ABANDONADA = "ABANDONADA"


class Modo(str, Enum):
    """Régimen de comportamiento activo (equivalente sano al
    'venta/postventa' de Dani — 002/004 sección 2.2, Grupo B)."""

    ATENCION_GENERAL = "ATENCION_GENERAL"
    SEGUIMIENTO_POST_OBJETIVO = "SEGUIMIENTO_POST_OBJETIVO"
    ESCALADO = "ESCALADO"


class NivelRiesgo(str, Enum):
    """Escala gradual — separada de `senal_de_urgencia` a propósito
    (004, sección 2.3): esto sube/baja sin disparar necesariamente
    una interrupción; `senal_de_urgencia` es el disparador booleano."""

    BAJO = "BAJO"
    MEDIO = "MEDIO"
    ALTO = "ALTO"


class NivelConfianza(str, Enum):
    BAJO = "BAJO"
    MEDIO = "MEDIO"
    ALTO = "ALTO"


class OrigenCambio(str, Enum):
    """Quién originó la última escritura del estado (004, sección 12) —
    necesario para poder auditar después 'por qué el estado dice esto'."""

    CREACION = "CREACION"
    LLM_PROPUESTA_APROBADA = "LLM_PROPUESTA_APROBADA"
    ORQUESTADOR_REGLA = "ORQUESTADOR_REGLA"
    GUARDRAIL_CORRECCION = "GUARDRAIL_CORRECCION"
    TOOL_RESULTADO = "TOOL_RESULTADO"


class ConversationState(BaseModel):
    """
    ConversationState — fuente única de verdad para decisiones de flujo
    (004, sección 3). NUNCA se reconstruye leyendo el historial crudo;
    se lee y se escribe como una entidad persistida.

    Grupos (004, sección 2.2): identidad/control técnico, núcleo
    conversacional, datos del objetivo, riesgo y cumplimiento.
    """

    model_config = {"validate_assignment": True}

    # --- Grupo A: identidad y control técnico ---
    conversation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    canal: str
    version: int = 0
    origen_del_ultimo_cambio: OrigenCambio = OrigenCambio.CREACION
    creado_en: datetime = Field(default_factory=_utcnow)
    ultima_actualizacion: datetime = Field(default_factory=_utcnow)
    ultimo_mensaje_id_procesado: Optional[str] = None

    # --- Grupo B: núcleo conversacional ---
    fase_actual: FaseActual = FaseActual.INICIO
    intencion: Optional[str] = None
    objetivo_de_conversacion: Optional[str] = None
    modo: Modo = Modo.ATENCION_GENERAL
    resumen_ref: Optional[str] = None
    proxima_accion: Optional[str] = None  # transitorio: se sobreescribe cada turno
    nivel_de_confianza: Optional[NivelConfianza] = None  # último valor conocido

    # --- Grupo C: datos del objetivo ---
    datos_recopilados: Dict[str, Any] = Field(default_factory=dict)
    herramientas_utilizadas: List[Dict[str, Any]] = Field(default_factory=list)
    resultado_de_herramientas: Dict[str, Any] = Field(default_factory=dict)

    # --- Grupo D: riesgo y cumplimiento (nunca los escribe el LLM directo) ---
    nivel_de_riesgo: NivelRiesgo = NivelRiesgo.BAJO
    senal_de_urgencia: bool = False
    necesidad_de_escalar: bool = False
    motivo_escalamiento: Optional[str] = None
    consentimiento_datos: bool = False
    consentimiento_datos_timestamp: Optional[datetime] = None

    # ------------------------------------------------------------------
    # `datos_faltantes` NO es un campo de este modelo a propósito:
    # 004 sección 2.1 lo redefine como *derivado*, calculado comparando
    # el esquema de datos requeridos del objetivo contra
    # `datos_recopilados`, para que nunca pueda desincronizarse.
    # ------------------------------------------------------------------
    def datos_faltantes(self, campos_requeridos: List[str]) -> List[str]:
        """Calcula, sin persistir, qué campos requeridos aún faltan."""
        return [c for c in campos_requeridos if c not in self.datos_recopilados]
