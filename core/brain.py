"""
Contrato Cerebro <-> Orquestador (004, sección 15).

El Brain SIEMPRE propone, NUNCA escribe el ConversationState directo
(004, sección 8) — devuelve un `BrainOutput`, nunca un ConversationState.

`FakeBrain` es una implementación determinista, basada en palabras clave,
usada como Brain por defecto del agente de demostración y de toda la
suite de tests (sin costo, sin red, sin credenciales). `AnthropicBrain`
es la implementación real, documentada pero NO ejercida por los tests de
este MVP (ver docstring de la clase).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol

from pydantic import BaseModel, Field

from state.models import ConversationState
from memory.conversation_memory import Turn

# Lista de palabras clave de riesgo deliberadamente genérica (no médica)
# para el demo del Core (prompt maestro, sección 27: no convertir el
# demo en un sistema médico). El protocolo real de riesgo/urgencia por
# dominio sigue PENDIENTE DE VALIDACIÓN CLÍNICA/LEGAL (003 sección 19,
# 004 sección 22) — esto NO es ese protocolo, es un placeholder de Core.
RISK_KEYWORDS_DEMO = ("urgente", "emergencia", "ayuda inmediata", "muy grave")


class BrainOutput(BaseModel):
    intencion: Optional[str] = None
    nivel_de_confianza: str = "MEDIO"  # BAJO | MEDIO | ALTO
    proxima_accion_propuesta: Optional[str] = None
    propuesta_de_actualizacion_de_estado: Dict[str, Any] = Field(default_factory=dict)
    tool_requerida: Optional[Dict[str, Any]] = None  # {"name": ..., "params": {...}}
    respuesta_propuesta: str = ""
    senales_detectadas: List[str] = Field(default_factory=list)


class Brain(Protocol):
    def interpret(
        self,
        message: str,
        state: ConversationState,
        recent_turns: List[Turn],
    ) -> BrainOutput: ...


class FakeBrain:
    """Brain determinista por palabras clave. No es NLU real — es un
    doble de prueba honesto (no pretende ser inteligente), suficiente
    para validar que el Core completo funciona de extremo a extremo
    (sección 26)."""

    def interpret(
        self,
        message: str,
        state: ConversationState,
        recent_turns: List[Turn],
    ) -> BrainOutput:
        texto = message.lower()
        senales = []
        if any(k in texto for k in RISK_KEYWORDS_DEMO):
            senales.append("posible_urgencia")

        # Nótese: el Brain SOLO reporta la señal. La decisión de forzar
        # ESCALADO_URGENTE es del Orchestrator + Guardrails (004, sección
        # 16) — el Brain no tiene autoridad para decidirlo por sí mismo.

        if state.objetivo_de_conversacion is None and (
            "programar" in texto or "agendar" in texto or "evento" in texto
        ):
            return BrainOutput(
                intencion="programar_evento",
                nivel_de_confianza="ALTO",
                proxima_accion_propuesta="preguntar_dato_faltante",
                propuesta_de_actualizacion_de_estado={
                    "intencion": "programar_evento",
                    "objetivo_de_conversacion": "programar_evento",
                },
                respuesta_propuesta="Claro, ¿qué evento quieres programar y para cuándo?",
                senales_detectadas=senales,
            )

        if state.objetivo_de_conversacion == "programar_evento":
            faltan = state.datos_faltantes(["evento", "fecha"])
            nuevos_datos = dict(state.datos_recopilados)
            if "evento" in faltan and texto.strip():
                nuevos_datos["evento"] = message.strip()
            elif "fecha" in faltan and texto.strip():
                nuevos_datos["fecha"] = message.strip()

            sigue_faltando = [c for c in ("evento", "fecha") if c not in nuevos_datos]
            if sigue_faltando:
                return BrainOutput(
                    intencion="programar_evento",
                    nivel_de_confianza="ALTO",
                    proxima_accion_propuesta="preguntar_dato_faltante",
                    propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos_datos},
                    respuesta_propuesta=f"¿Me confirmas {sigue_faltando[0]}?",
                    senales_detectadas=senales,
                )

            return BrainOutput(
                intencion="programar_evento",
                nivel_de_confianza="ALTO",
                proxima_accion_propuesta="ejecutar_tool",
                propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos_datos},
                tool_requerida={
                    "name": "schedule_event",
                    "params": {
                        "evento": nuevos_datos.get("evento"),
                        "fecha": nuevos_datos.get("fecha"),
                        "idempotency_key": f"{state.conversation_id}:programar_evento",
                    },
                },
                respuesta_propuesta="Listo, lo programo.",
                senales_detectadas=senales,
            )

        return BrainOutput(
            intencion=None,
            nivel_de_confianza="BAJO",
            proxima_accion_propuesta="preguntar_intencion",
            respuesta_propuesta="Cuéntame en qué te ayudo.",
            senales_detectadas=senales,
        )


class AnthropicBrain:
    """Implementación real, pensada para producción — NO ejercida por la
    suite de tests de este MVP (no hay ANTHROPIC_API_KEY configurada en
    esta sesión, y los tests deben ser deterministas y sin red/costo).

    Documentado explícitamente como PENDIENTE de prueba en vivo — ver
    /Users/enzoalfonso/recado/006-construccion-zantia.md.
    """

    def __init__(self, model: str = "claude-sonnet-5", api_key_env_var: str = "ANTHROPIC_API_KEY") -> None:
        self._model = model
        self._api_key_env_var = api_key_env_var

    def interpret(
        self,
        message: str,
        state: ConversationState,
        recent_turns: List[Turn],
    ) -> BrainOutput:
        import os

        api_key = os.environ.get(self._api_key_env_var)
        if not api_key:
            raise RuntimeError(
                f"AnthropicBrain requiere la variable de entorno {self._api_key_env_var} "
                "(ver .env.example) — no configurada en esta sesión."
            )
        # Import perezoso: el paquete `anthropic` es una dependencia
        # opcional del MVP (requirements.txt), no instalada por defecto,
        # para no forzarla en la suite de tests determinista.
        import anthropic  # type: ignore

        client = anthropic.Anthropic(api_key=api_key)
        respuesta = client.messages.create(
            model=self._model,
            max_tokens=800,
            system=(
                "Eres el Brain de un agente ZANTIA. Responde SOLO con un "
                "JSON válido que cumpla el esquema BrainOutput de "
                "core/brain.py. No incluyas texto fuera del JSON."
            ),
            messages=[{"role": "user", "content": message}],
        )
        contenido = respuesta.content[0].text  # type: ignore[union-attr]
        return BrainOutput.model_validate_json(contenido)
