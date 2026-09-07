"""
Orchestrator — el único componente con autoridad para escribir el
ConversationState (004, sección 8). Implementa el principio de
autoridad del prompt maestro (sección 4):

    LLM PROPONE -> GUARDRAILS VALIDAN -> ORQUESTADOR DECIDE/EJECUTA
    -> ESTADO SE PERSISTE -> RESPUESTA SE GENERA

Y la prioridad de interrupciones (prompt maestro, sección 6 / 004,
sección 7):

    RIESGO > ESCALAMIENTO SOLICITADO > DATO FALTANTE > ACCIÓN
    > CONVERSACIÓN NORMAL
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from core.brain import Brain, RISK_KEYWORDS_DEMO
from guardrails import (
    GuardrailContext,
    GuardrailDecision,
    GuardrailEngine,
    reglas_core_por_defecto,
)
from memory.conversation_memory import ConversationMemoryProtocol
from observability.events import EventLogProtocol, EventType
from state.machine import VALID_TRANSITIONS, InvalidTransitionError, is_terminal, validate_transition
from state.models import ConversationState, FaseActual, Modo, NivelConfianza, NivelRiesgo, OrigenCambio
from state.store import ConcurrencyConflictError, StateStore
from tools.base import ToolCategory, ToolError
from tools.registry import ToolRegistry

# Frases fijas de escalación — deliberadamente NO prometen contacto ni
# tiempo, lección directa de Dani (002, sección "Escalación humana").
_MENSAJE_ESCALADO_URGENTE = (
    "Esto necesita atención de una persona ahora mismo. Voy a registrar "
    "tu caso como prioritario."
)
_MENSAJE_ESCALADO_ESTANDAR = (
    "Voy a pasar tu caso al equipo para que lo revise. No puedo "
    "garantizarte un contacto ni un tiempo específico."
)
_MENSAJE_CONVERSACION_CERRADA = (
    "Esta conversación ya fue escalada y no puede continuar de forma "
    "automática. Un humano debe intervenir."
)

_MAX_MENSAJES_SIN_LINK_TIPO = 8  # no usado todavía; ver recado 006 (pendientes)


def detect_risk_keywords(text: str) -> bool:
    """Detección determinista de riesgo — a propósito, NO delegada al
    Brain (004, sección 2.3: 'toda condición de seguridad crítica se
    evalúa con código determinista, nunca solo con generalización
    semántica de un LLM'). Lista de ejemplo, no clínica — ver docstring
    de RISK_KEYWORDS_DEMO en core/brain.py."""
    texto = text.lower()
    return any(k in texto for k in RISK_KEYWORDS_DEMO)


@dataclass
class OrchestratorResult:
    response: str
    state: ConversationState
    escalated: bool


class Orchestrator:
    def __init__(
        self,
        state_store: StateStore,
        memory: ConversationMemoryProtocol,
        brain: Brain,
        tool_registry: ToolRegistry,
        event_log: EventLogProtocol,
        guardrail_engine: Optional[GuardrailEngine] = None,
    ) -> None:
        self._store = state_store
        self._memory = memory
        self._brain = brain
        self._tools = tool_registry
        self._events = event_log
        self._guardrails = guardrail_engine or GuardrailEngine(
            reglas_core_por_defecto(tool_registry.categories_by_name())
        )
        # Deduplicación de mensajes (004, sección 10). Simplificación de
        # MVP: vive en memoria de proceso, no en el StateStore — ver
        # pendientes en recado 006.
        self._respuestas_por_mensaje: Dict[str, str] = {}

    # --- accesores de solo lectura, para tests/observabilidad externa ---
    @property
    def tools(self) -> ToolRegistry:
        return self._tools

    @property
    def events(self) -> EventLogProtocol:
        return self._events

    @property
    def brain(self) -> Brain:
        # Recado 050 — expone el `Brain` ya construido (solo lectura,
        # mismo criterio que `tools`/`events`/`store` arriba) para que
        # `domains/health/gateway.py` pueda reevaluar el detector
        # centralizado de interrupciones de contexto
        # (`HealthBrain._detectar_interrupcion_de_contexto`) sobre una
        # Activity YA CERRADA, durante la ventana de gracia de un turno
        # — sin duplicar esa lógica de detección fuera del Brain.
        return self._brain

    @property
    def store(self) -> StateStore:
        return self._store

    # ------------------------------------------------------------------
    def handle_message(
        self, conversation_id: str, canal: str, message_id: str, text: str
    ) -> OrchestratorResult:
        dedup_key = f"{conversation_id}:{message_id}"
        if dedup_key in self._respuestas_por_mensaje:
            state = self._store.get(conversation_id)
            return OrchestratorResult(
                response=self._respuestas_por_mensaje[dedup_key],
                state=state,
                escalated=is_terminal(state.fase_actual) if state else False,
            )

        state = self._store.get(conversation_id) or self._store.create(conversation_id, canal)
        self._memory.add_turn(conversation_id, "user", text)

        if is_terminal(state.fase_actual):
            self._events.record(
                conversation_id, EventType.ERROR,
                detalle="mensaje recibido tras estado terminal, no se reprocesa",
                fase=state.fase_actual.value,
            )
            return OrchestratorResult(response=_MENSAJE_CONVERSACION_CERRADA, state=state, escalated=True)

        if state.fase_actual == FaseActual.CIERRE:
            state = self._reabrir_ciclo(state)

        # Recado 037, Parte 4: la detección de riesgo se calcula ANTES
        # de invocar al Brain, y NUNCA depende de que el Brain responda
        # con éxito — un Brain basado en LLM real (network/API, todavía
        # no conectado) puede fallar (timeout, error de red, JSON
        # inválido) de formas que un Brain determinista por palabras
        # clave nunca falla. Antes de este cambio, `detect_risk_keywords`
        # se calculaba DESPUÉS de `self._brain.interpret(...)` — si el
        # Brain hubiera lanzado una excepción, la detección de riesgo
        # nunca se habría ejecutado, y un mensaje genuinamente urgente
        # se habría perdido en un crash en vez de escalarse. Con el
        # FakeBrain/HealthBrain deterministas de hoy esto nunca ocurría
        # en la práctica (nunca lanzan), pero es exactamente el tipo de
        # suposición implícita que hay que corregir ANTES de conectar
        # un LLM real (ver docstring del módulo).
        riesgo_detectado = detect_risk_keywords(text)

        try:
            brain_output = self._brain.interpret(text, state, self._memory.get_recent(conversation_id))
        except Exception as exc:  # noqa: BLE001 — un Brain real puede fallar de formas no anticipadas
            self._events.record(
                conversation_id, EventType.ERROR,
                detalle=f"Brain.interpret() lanzó una excepción: {exc}",
            )
            return self._escalar(
                state, conversation_id, urgente=riesgo_detectado,
                motivo=(
                    "posible urgencia detectada (palabra clave) durante un fallo del Brain"
                    if riesgo_detectado
                    else f"error irrecuperable del Brain: {exc}"
                ),
            )

        cambios_propuestos: Dict[str, Any] = dict(brain_output.propuesta_de_actualizacion_de_estado)

        # --- Regla determinista de máxima prioridad: riesgo (sección 6/7) ---
        if riesgo_detectado:
            cambios_propuestos["senal_de_urgencia"] = True
            cambios_propuestos["nivel_de_riesgo"] = NivelRiesgo.ALTO
            cambios_propuestos["necesidad_de_escalar"] = True
            cambios_propuestos["motivo_escalamiento"] = "posible urgencia detectada (palabra clave)"

        tool_propuesta = brain_output.tool_requerida["name"] if brain_output.tool_requerida else None

        contexto_guardrail = GuardrailContext(
            state=state,
            proposed_state_changes=cambios_propuestos,
            proposed_tool=tool_propuesta,
            proposed_response=brain_output.respuesta_propuesta,
            mensaje_entrante=text,
            verificaciones_de_datos=brain_output.verificaciones_de_datos,
            confirmacion_estructurada_para_write=brain_output.confirmacion_estructurada_para_write,
            texto_base_para_comparacion=brain_output.texto_base_para_comparacion,
        )
        veredicto = self._guardrails.evaluate(contexto_guardrail)
        self._events.record(
            conversation_id,
            EventType.GUARDRAIL_DECISION,
            decision=veredicto.decision.value,
            razon=veredicto.reason,
        )

        if veredicto.decision == GuardrailDecision.ESCALATE:
            return self._escalar(state, conversation_id, urgente=True, motivo=veredicto.reason)

        if veredicto.decision == GuardrailDecision.BLOCK:
            return self._responder_sin_avanzar(
                state, conversation_id, mensaje=(
                    "No puedo continuar con esa acción todavía: " + veredicto.reason
                ),
            )

        respuesta_final = veredicto.modified_response or brain_output.respuesta_propuesta
        cambios_propuestos.update(veredicto.forced_state_changes)

        # --- Escalamiento solicitado explícitamente (segunda prioridad) ---
        if cambios_propuestos.get("necesidad_de_escalar") and not riesgo_detectado:
            return self._escalar(
                state, conversation_id, urgente=False,
                motivo=cambios_propuestos.get("motivo_escalamiento", "solicitado"),
            )

        if riesgo_detectado:
            return self._escalar(
                state, conversation_id, urgente=True,
                motivo=cambios_propuestos.get("motivo_escalamiento", "posible urgencia"),
            )

        # --- Ejecutar tool si el Brain la propuso y guardrails no bloqueó ---
        resultado_tool = None
        if brain_output.tool_requerida:
            resultado_tool = self._ejecutar_tool(
                state, conversation_id, brain_output.tool_requerida
            )
            if resultado_tool is None:
                # Error irrecuperable de la tool (excepción/no encontrada):
                # se escala de verdad (no solo se declara escalado) — antes
                # esta rama devolvía escalated=True sin transicionar
                # fase_actual, dejando la conversación en un estado
                # inconsistente. Corregido al construir el dominio salud
                # (prompt 007, sección 14) — ver recado 007.
                return self._escalar(
                    state, conversation_id, urgente=False, motivo="error irrecuperable de herramienta"
                )
            cambios_propuestos.setdefault("herramientas_utilizadas", list(state.herramientas_utilizadas))
            cambios_propuestos["herramientas_utilizadas"].append(
                {"tool": brain_output.tool_requerida["name"], "exito": resultado_tool.success}
            )
            cambios_propuestos.setdefault("resultado_de_herramientas", dict(state.resultado_de_herramientas))
            cambios_propuestos["resultado_de_herramientas"][brain_output.tool_requerida["name"]] = (
                resultado_tool.data
            )
            if not resultado_tool.success:
                # La tool respondió (no lanzó excepción) pero NO tuvo éxito
                # (p.ej. un turno ya no disponible). No se debe dejar pasar
                # el texto optimista que el Brain propuso ANTES de conocer
                # este resultado — corrección encontrada al construir el
                # dominio salud (prompt 007, sección 14: "no declarar
                # confirmado si el sistema no confirmó"). Ver recado 007.
                respuesta_final = (
                    "No pude completar esa acción "
                    f"({resultado_tool.error or 'sin más detalle'}). ¿Lo intentamos de nuevo?"
                )

        siguiente_fase = self._determinar_siguiente_fase(state.fase_actual, brain_output, resultado_tool)
        try:
            validate_transition(state.fase_actual, siguiente_fase)
        except InvalidTransitionError as exc:
            self._events.record(conversation_id, EventType.ERROR, detalle=str(exc))
            return self._escalar(state, conversation_id, urgente=False, motivo=f"error de transición: {exc}")

        cambios_propuestos["fase_actual"] = siguiente_fase
        cambios_propuestos["proxima_accion"] = brain_output.proxima_accion_propuesta
        try:
            cambios_propuestos["nivel_de_confianza"] = NivelConfianza(brain_output.nivel_de_confianza)
        except ValueError:
            cambios_propuestos["nivel_de_confianza"] = NivelConfianza.BAJO
        cambios_propuestos["origen_del_ultimo_cambio"] = OrigenCambio.LLM_PROPUESTA_APROBADA
        cambios_propuestos["ultimo_mensaje_id_procesado"] = message_id
        if siguiente_fase == FaseActual.SEGUIMIENTO:
            cambios_propuestos["modo"] = Modo.SEGUIMIENTO_POST_OBJETIVO

        estado_final = self._guardar_con_reintento(state, cambios_propuestos, conversation_id, siguiente_fase)

        self._memory.add_turn(conversation_id, "agent", respuesta_final)
        self._respuestas_por_mensaje[dedup_key] = respuesta_final
        return OrchestratorResult(response=respuesta_final, state=estado_final, escalated=False)

    # ------------------------------------------------------------------
    def _reabrir_ciclo(self, state: ConversationState) -> ConversationState:
        """CIERRE -> IDENTIFICACION_DE_INTENCION: un mensaje nuevo reabre
        el ciclo (004, sección 9); se limpian los campos del objetivo
        anterior, no el historial de riesgo/consentimiento."""
        return state.model_copy(
            update={
                "fase_actual": FaseActual.IDENTIFICACION_DE_INTENCION,
                "intencion": None,
                "objetivo_de_conversacion": None,
                "datos_recopilados": {},
                "herramientas_utilizadas": [],
                "resultado_de_herramientas": {},
            }
        )

    def _determinar_siguiente_fase(self, fase_actual, brain_output, resultado_tool) -> FaseActual:
        accion = brain_output.proxima_accion_propuesta
        if fase_actual == FaseActual.INICIO:
            return FaseActual.IDENTIFICACION_DE_INTENCION
        if accion == "preguntar_intencion":
            # Hallazgo real del recado 047: un Brain de dominio (ej.
            # HealthBrain) puede proponer "preguntar_intencion" desde
            # CUALQUIER etapa suya — no solo la primera — cuando una
            # interrupción de contexto (pide info/info no autorizada) se
            # detecta a mitad de flujo (ver `_detectar_interrupcion_de_
            # contexto`, domains/health/brain.py). Antes, esta rama
            # siempre apuntaba a IDENTIFICACION_DE_INTENCION sin
            # importar la fase de origen — válido solo desde INICIO o la
            # propia IDENTIFICACION_DE_INTENCION (VALID_TRANSITIONS);
            # desde una fase más avanzada (ej. RECOPILACION_DE_DATOS)
            # `validate_transition` lo rechazaba con
            # `InvalidTransitionError`, y el manejo de ese error
            # ESCALABA la conversación de verdad (mensaje genérico,
            # `management_status=ESCALATED`) — una consecuencia grave y
            # nunca intencional de una pregunta aclaratoria inocua.
            # Ahora: si la fase actual no permite volver a
            # IDENTIFICACION_DE_INTENCION, la conversación simplemente
            # se queda en su fase actual (auto-bucle) — la etapa de
            # dominio (`datos_recopilados["etapa"]`) es la que de verdad
            # gobierna el flujo del paciente; `fase_actual` es la
            # clasificación genérica del Core y no debe forzar un
            # retroceso inválido solo por una pregunta de contexto.
            if fase_actual == FaseActual.IDENTIFICACION_DE_INTENCION or (
                FaseActual.IDENTIFICACION_DE_INTENCION in VALID_TRANSITIONS.get(fase_actual, set())
            ):
                return FaseActual.IDENTIFICACION_DE_INTENCION
            return fase_actual
        if accion == "preguntar_dato_faltante":
            if fase_actual in (FaseActual.INICIO, FaseActual.IDENTIFICACION_DE_INTENCION):
                return FaseActual.RECOPILACION_DE_DATOS
            return FaseActual.RECOPILACION_DE_DATOS
        if accion == "ejecutar_tool":
            if resultado_tool is not None and resultado_tool.success:
                return FaseActual.RESPUESTA
            return FaseActual.RAZONAMIENTO_DECISION
        return FaseActual.RESPUESTA

    def _ejecutar_tool(self, state, conversation_id, tool_requerida):
        nombre = tool_requerida["name"]
        params = tool_requerida.get("params", {})
        try:
            tool = self._tools.get(nombre)
        except KeyError as exc:
            self._events.record(conversation_id, EventType.ERROR, detalle=str(exc))
            return None
        try:
            resultado = tool.run(params, context={"conversation_id": conversation_id})
        except ToolError as exc:
            self._events.record(
                conversation_id, EventType.ERROR, detalle=f"ToolError en '{nombre}': {exc}"
            )
            return None
        self._events.record(
            conversation_id, EventType.TOOL_INVOKED,
            tool=nombre, categoria=tool.category.value, exito=resultado.success,
        )
        return resultado

    def _responder_sin_avanzar(self, state, conversation_id, mensaje: str) -> OrchestratorResult:
        return OrchestratorResult(response=mensaje, state=state, escalated=False)

    def _escalar(self, state, conversation_id, urgente: bool, motivo: str) -> OrchestratorResult:
        siguiente_fase = FaseActual.ESCALADO_URGENTE if urgente else FaseActual.ESCALADO_ESTANDAR
        # Aunque las interrupciones globales están siempre permitidas
        # (state/machine.py: GLOBAL_INTERRUPTION_TARGETS), se valida
        # igual por consistencia y para dejar traza si alguna vez se
        # invoca _escalar desde un estado ya terminal (no debería ocurrir:
        # handle_message ya filtra ese caso antes).
        validate_transition(state.fase_actual, siguiente_fase)
        cambios = {
            "fase_actual": siguiente_fase,
            "modo": Modo.ESCALADO,
            "necesidad_de_escalar": True,
            "motivo_escalamiento": motivo,
            "origen_del_ultimo_cambio": (
                OrigenCambio.GUARDRAIL_CORRECCION if urgente else OrigenCambio.ORQUESTADOR_REGLA
            ),
        }
        if urgente:
            cambios["senal_de_urgencia"] = True
            cambios["nivel_de_riesgo"] = NivelRiesgo.ALTO
        estado_final = self._guardar_con_reintento(state, cambios, conversation_id, siguiente_fase)
        self._events.record(
            conversation_id, EventType.STATE_TRANSITION,
            de=state.fase_actual.value, a=siguiente_fase.value, motivo=motivo,
        )
        mensaje = _MENSAJE_ESCALADO_URGENTE if urgente else _MENSAJE_ESCALADO_ESTANDAR
        self._memory.add_turn(conversation_id, "agent", mensaje)
        return OrchestratorResult(response=mensaje, state=estado_final, escalated=True)

    def _guardar_con_reintento(self, state, cambios: Dict[str, Any], conversation_id, siguiente_fase):
        """Concurrencia optimista con un reintento (004, sección 11)."""
        estado_propuesto = state.model_copy(update=cambios)
        try:
            guardado = self._store.save(estado_propuesto, expected_version=state.version)
        except ConcurrencyConflictError:
            actual = self._store.get(conversation_id)
            estado_propuesto = actual.model_copy(update=cambios)
            guardado = self._store.save(estado_propuesto, expected_version=actual.version)
        self._events.record(
            conversation_id, EventType.STATE_TRANSITION,
            de=state.fase_actual.value, a=siguiente_fase.value,
        )
        return guardado
