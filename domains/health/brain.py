"""
HealthBrain — Brain de dominio para demanda inducida (prompt 007,
secciones 9-10).

Implementa el mismo Protocol `core.brain.Brain` del Core (sin tocarlo)
— construido con un PROVEEDOR de la Activity (una función sin
argumentos que devuelve la Activity vigente), no con la Activity misma,
porque `Activity` es un modelo pydantic inmutable: cada actualización
de dominio crea una copia nueva (`model_copy`), así que guardar una
referencia fija en el constructor congelaría al Brain con la primera
versión para siempre (p. ej. nunca vería el `appointment_id` una vez
reservado). Corrección encontrada al construir este dominio — ver
recado 007. Tampoco recibe la Activity como parámetro de `interpret()`
(así no hace falta ampliar el contrato del Core: 004, sección 15).

Simplificación deliberada y documentada: para componer una respuesta en
lenguaje natural con opciones REALES (nunca inventadas — sección 13),
este Brain consulta `AppointmentService.get_availability()` (una tool
READ) directamente, además de proponer el `tool_requerida` formal para
que el Core la ejecute y audite igual. Nunca hace lo mismo con una
operación WRITE (reservar/reprogramar/cancelar) — esas SIEMPRE se
proponen solo como `tool_requerida`, nunca se ejecutan desde el Brain
(mismo principio de autoridad del Core: el LLM propone, nunca escribe).
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from core.brain import BrainOutput
from memory.conversation_memory import Turn
from state.models import ConversationState

from .appointment_service import AppointmentService

_ACEPTA = ("sí", "si,", " si ", "acepto", "me interesa", "claro que", "dale", "vale", "de acuerdo", "está bien")
_DECLINA = ("no me interesa", "no gracias", "no quiero", "no estoy interesado", "no, gracias")
_HUMANO = ("hablar con alguien", "persona real", "un humano", "un asesor", "quiero hablar con")
_NO_PUEDE_AHORA = ("no puedo ahora", "ahora no puedo", "en otro momento", "llámame después", "más tarde no")
_PIDE_INFO = ("qué es", "más información", "cuéntame más", "por qué me contactan", "explícame", "de qué se trata")
_INFO_NO_AUTORIZADA = ("mi diagnóstico", "diagnostico", "resultado de mis examenes", "resultado de mis exámenes", "qué enfermedad tengo", "qué tengo")
_REPROGRAMAR = ("no puedo asistir", "reprogramar", "cambiar la cita", "otro día", "otra fecha")
_CANCELAR = ("cancelar la cita", "ya no quiero la cita", "cancela mi cita")
_CONFIRMA = ("confirmo", "sí, confirmo", "asistiré", "voy a asistir", "ahí estaré", "ahí voy a estar", "confirmado", "ahí llego")
# Gestión "en nombre de otro paciente" (recado 013, extensión de R-15):
# el titular del canal (ya verificado) declara que la gestión es para
# un beneficiario distinto. Solo relevante con un AppointmentService que
# expone `buscar_paciente` (HrmmAppointmentService) — con
# MockAppointmentService esta frase se ignora, comportamiento idéntico
# al de antes de esta extensión (requisito #5).
_PARA_OTRO = (
    "es para mi mamá", "es para mi mama", "es para mi papá", "es para mi papa",
    "para mi mamá", "para mi mama", "para mi papá", "para mi papa",
    "para mi hijo", "para mi hija", "para mi esposa", "para mi esposo",
    "para otra persona", "no es para mí", "no es para mi",
)


def _contains_any(texto: str, opciones: tuple) -> bool:
    return any(o in texto for o in opciones)


class HealthBrain:
    def __init__(self, activity_provider: Callable[[], Any], appointment_service: AppointmentService) -> None:
        self._activity_provider = activity_provider
        self._appointment_service = appointment_service

    @property
    def _activity(self):
        """Siempre la Activity VIGENTE — nunca una copia congelada del
        momento de construcción (ver docstring del módulo)."""
        return self._activity_provider()

    # ------------------------------------------------------------------
    def interpret(
        self,
        message: str,
        state: ConversationState,
        recent_turns: List[Turn],
    ) -> BrainOutput:
        texto = message.lower().strip()
        datos = dict(state.datos_recopilados)
        etapa = datos.get("etapa", "esperando_decision")

        # Reprogramar/cancelar/confirmar se reconocen en cualquier etapa
        # posterior a una cita ya reservada (equivalente sano a la
        # interrupción global del Core, pero de dominio: secciones
        # 19-23) — independiente de `etapa`, que el Core puede haber
        # reiniciado al reabrir la conversación desde CIERRE (un
        # recordatorio llega días después de la reserva original: 004,
        # sección 9, "un mensaje nuevo reabre el ciclo").
        if self._activity.appointment_id and _contains_any(texto, _REPROGRAMAR):
            return self._iniciar_reprogramacion(datos)
        if self._activity.appointment_id and _contains_any(texto, _CANCELAR):
            return self._cancelar(datos)
        if self._activity.appointment_id and _contains_any(texto, _CONFIRMA):
            return BrainOutput(
                senales_detectadas=["asistencia_confirmada"],
                respuesta_propuesta="¡Perfecto, ahí te esperamos!",
                # marca la etapa para que la capa de dominio (agent.py)
                # pueda devolver management_status a APPOINTMENT_CONFIRMED
                # — `fire_reminder` lo había dejado en REMINDER_72H/24H/8H
                # (sección 6: ambos son management_status válidos, mutuamente
                # excluyentes en el momento, no acumulables).
                propuesta_de_actualizacion_de_estado={
                    "datos_recopilados": {**datos, "etapa": "asistencia_confirmada"}
                },
            )

        if etapa == "esperando_decision":
            return self._interpretar_decision(texto, datos)
        if etapa == "esperando_documento_beneficiario":
            # Usa `message` SIN lowercase (no `texto`): un documento de
            # identidad es un identificador crudo, no una palabra clave
            # — lowercasearlo antes de compararlo contra buscar_paciente
            # podría corromper un documento con letras (encontrado
            # probando este flujo, ver recado 013).
            return self._interpretar_documento_beneficiario(message.strip(), datos)
        if etapa == "esperando_confirmacion_beneficiario":
            return self._interpretar_confirmacion_beneficiario(texto, datos)
        if etapa == "esperando_seleccion":
            return self._interpretar_seleccion(texto, datos)
        if etapa == "esperando_seleccion_reprogramacion":
            return self._interpretar_seleccion_reprogramacion(texto, datos)

        # Fallback defensivo: no debería alcanzarse en el flujo normal.
        return BrainOutput(
            respuesta_propuesta="Cuéntame en qué te puedo ayudar.",
            proxima_accion_propuesta="preguntar_intencion",
        )

    # ------------------------------------------------------------------
    def _interpretar_decision(self, texto: str, datos: Dict[str, Any]) -> BrainOutput:
        if _contains_any(texto, _INFO_NO_AUTORIZADA):
            return BrainOutput(
                senales_detectadas=["informacion_no_autorizada"],
                respuesta_propuesta=(
                    "Eso no lo tengo disponible por este canal — no puedo darte información "
                    "clínica que no esté autorizada aquí. Si quieres, puedo poner en contacto "
                    "al equipo para resolver esa duda."
                ),
                proxima_accion_propuesta="preguntar_intencion",
                propuesta_de_actualizacion_de_estado={"datos_recopilados": datos},
            )

        if _contains_any(texto, _DECLINA):
            nuevos = {**datos, "etapa": "finalizada", "decision": "DECLINED"}
            return BrainOutput(
                senales_detectadas=["paciente_declina"],
                respuesta_propuesta="Entiendo, gracias por tu tiempo. Si cambias de opinión, aquí estamos.",
                propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos},
            )

        if _contains_any(texto, _HUMANO):
            nuevos = {**datos, "etapa": "escalada"}
            return BrainOutput(
                senales_detectadas=["solicita_humano"],
                respuesta_propuesta="Claro, voy a poner tu caso en manos de una persona del equipo.",
                propuesta_de_actualizacion_de_estado={
                    "datos_recopilados": nuevos,
                    "necesidad_de_escalar": True,
                    "motivo_escalamiento": "paciente solicitó hablar con una persona",
                },
            )

        if _contains_any(texto, _NO_PUEDE_AHORA):
            nuevos = {**datos, "etapa": "finalizada", "decision": "NO_PUEDE_AHORA"}
            return BrainOutput(
                respuesta_propuesta="Sin problema, lo intentamos en otro momento. Gracias por tu tiempo.",
                propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos},
            )

        if _contains_any(texto, _PIDE_INFO):
            motivo = self._activity.reason or self._activity.program or "una atención pendiente"
            return BrainOutput(
                respuesta_propuesta=(
                    f"Te contactamos por {motivo}. La idea es ayudarte a programar tu atención "
                    "cuando te quede cómodo. ¿Te gustaría revisar opciones de horario?"
                ),
                proxima_accion_propuesta="preguntar_intencion",
                propuesta_de_actualizacion_de_estado={"datos_recopilados": datos},
            )

        # Gestión para un beneficiario (recado 013) — solo si el
        # AppointmentService activo puede verificar identidad real
        # (mismo duck-typing que `resolve_patient_identity` en
        # gateway.py, sin importar nada de ahí para no acoplar capas).
        if _contains_any(texto, _PARA_OTRO) and getattr(self._appointment_service, "buscar_paciente", None) is not None:
            nuevos = {**datos, "etapa": "esperando_documento_beneficiario"}
            return BrainOutput(
                senales_detectadas=["gestion_para_beneficiario_declarada"],
                respuesta_propuesta=(
                    "Claro, ¿me confirmas el número de documento de identidad "
                    "de la persona para quien es la cita?"
                ),
                proxima_accion_propuesta="preguntar_dato_faltante",
                propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos},
            )

        if _contains_any(texto, _ACEPTA):
            return self._ofrecer_disponibilidad(datos)

        return BrainOutput(
            respuesta_propuesta="¿Te gustaría que te ayude a programar tu atención? Puedes responder sí o no.",
            proxima_accion_propuesta="preguntar_intencion",
            propuesta_de_actualizacion_de_estado={"datos_recopilados": datos},
        )

    # ------------------------------------------------------------------
    def _ofrecer_disponibilidad(self, datos: Dict[str, Any]) -> BrainOutput:
        """Extraído de la rama `_ACEPTA` de `_interpretar_decision`
        (recado 013) para que también lo use el flujo de confirmación de
        beneficiario, sin duplicar la lógica de ofrecer disponibilidad."""
        servicio = self._activity.service or "medicina general"
        opciones = self._appointment_service.get_availability(servicio)[:3]
        nuevos = {
            **datos,
            "etapa": "esperando_seleccion",
            "opciones_ofrecidas": [o.slot_id for o in opciones],
        }
        if not opciones:
            return BrainOutput(
                respuesta_propuesta="Por ahora no tengo horarios disponibles, te contactamos pronto.",
                propuesta_de_actualizacion_de_estado={"datos_recopilados": {**datos, "etapa": "finalizada"}},
            )
        texto_opciones = "; ".join(
            f"{i+1}) {o.date} {o.time} en {o.location}" for i, o in enumerate(opciones)
        )
        return BrainOutput(
            respuesta_propuesta=f"Perfecto, estas son las opciones disponibles: {texto_opciones}. ¿Cuál prefieres?",
            # "preguntar_dato_faltante" (no "ejecutar_tool"): todavía
            # falta la SELECCIÓN del paciente antes de poder reservar
            # — la tool que se ejecuta aquí es de lectura
            # (get_availability), no la acción final.
            proxima_accion_propuesta="preguntar_dato_faltante",
            tool_requerida={"name": "get_availability", "params": {"service": servicio}},
            propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos},
        )

    # ------------------------------------------------------------------
    def _interpretar_documento_beneficiario(self, texto: str, datos: Dict[str, Any]) -> BrainOutput:
        """Segundo paso del flujo de beneficiario (recado 013): valida
        el documento contra `buscar_paciente` (mismo endpoint público
        009, GET /citas/buscar-paciente) ANTES de aceptar el nombre —
        nunca inventa ni continúa si no hay match real."""
        documento = texto.strip()
        buscar = getattr(self._appointment_service, "buscar_paciente", None)
        identidad = buscar(documento) if buscar and documento else None
        if identidad is None:
            return BrainOutput(
                respuesta_propuesta=(
                    "No encontré ningún paciente registrado con ese documento. "
                    "¿Puedes verificarlo y escribirlo de nuevo?"
                ),
                proxima_accion_propuesta="preguntar_dato_faltante",
                propuesta_de_actualizacion_de_estado={"datos_recopilados": datos},
            )
        nombre = identidad.get("nombre_paciente") or "esa persona"
        nuevos = {
            **datos,
            "etapa": "esperando_confirmacion_beneficiario",
            "beneficiario_documento_candidato": documento,
            "beneficiario_nombre_candidato": nombre,
        }
        return BrainOutput(
            senales_detectadas=["beneficiario_encontrado"],
            respuesta_propuesta=f"Vamos a agendar para {nombre} — ¿es correcto?",
            proxima_accion_propuesta="preguntar_dato_faltante",
            propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos},
        )

    def _interpretar_confirmacion_beneficiario(self, texto: str, datos: Dict[str, Any]) -> BrainOutput:
        """Tercer paso: el titular confirma explícitamente el nombre
        antes de continuar (requisito #2, "para que el titular confirme
        explícitamente... antes de continuar") — cualquier respuesta que
        no sea una aceptación clara vuelve a pedir el documento, nunca
        asume un "sí" implícito."""
        if not _contains_any(texto, _ACEPTA):
            nuevos = {**datos, "etapa": "esperando_documento_beneficiario"}
            return BrainOutput(
                respuesta_propuesta=(
                    "Entendido, ¿me confirmas el documento correcto de la "
                    "persona para quien es la cita?"
                ),
                proxima_accion_propuesta="preguntar_dato_faltante",
                propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos},
            )
        nuevos = {
            **datos,
            "beneficiario_documento": datos["beneficiario_documento_candidato"],
            "beneficiario_nombre": datos["beneficiario_nombre_candidato"],
        }
        return self._ofrecer_disponibilidad(nuevos)

    # ------------------------------------------------------------------
    def _elegir_opcion(self, texto: str, opciones: List[str]) -> Optional[str]:
        mapa_ordinal = {"1": 0, "primera": 0, "2": 1, "segunda": 1, "3": 2, "tercera": 2}
        for clave, indice in mapa_ordinal.items():
            if clave in texto and indice < len(opciones):
                return opciones[indice]
        return None

    def _interpretar_seleccion(self, texto: str, datos: Dict[str, Any]) -> BrainOutput:
        opciones = datos.get("opciones_ofrecidas", [])
        elegida = self._elegir_opcion(texto, opciones)
        if elegida is None:
            return BrainOutput(
                respuesta_propuesta="No identifiqué cuál prefieres — ¿me confirmas 1, 2 o 3?",
                proxima_accion_propuesta="preguntar_dato_faltante",
                propuesta_de_actualizacion_de_estado={"datos_recopilados": datos},
            )
        nuevos = {**datos, "etapa": "reservando", "slot_seleccionado": elegida}
        # Recado 013: si el titular declaró y confirmó un beneficiario,
        # la reserva se hace a nombre del BENEFICIARIO, nunca del
        # titular del canal (requisito #3) — `self._activity.patient_reference`
        # solo se usa cuando no hay beneficiario (comportamiento por
        # defecto, requisito #5, sin cambios frente a antes de esta extensión).
        patient_reference_reserva = datos.get("beneficiario_documento") or self._activity.patient_reference
        return BrainOutput(
            respuesta_propuesta="Perfecto, voy a reservarlo — un momento.",
            proxima_accion_propuesta="ejecutar_tool",
            tool_requerida={
                "name": "book_appointment",
                "params": {
                    "slot_id": elegida,
                    "patient_reference": patient_reference_reserva,
                    "idempotency_key": f"{self._activity.activity_id}:booking",
                },
            },
            propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos},
        )

    # ------------------------------------------------------------------
    def _iniciar_reprogramacion(self, datos: Dict[str, Any]) -> BrainOutput:
        servicio = self._activity.service or "medicina general"
        opciones = self._appointment_service.get_availability(servicio)[:3]
        nuevos = {
            **datos,
            "etapa": "esperando_seleccion_reprogramacion",
            "opciones_reprogramacion": [o.slot_id for o in opciones],
        }
        if not opciones:
            return BrainOutput(
                senales_detectadas=["reprogramacion_solicitada"],
                respuesta_propuesta="Por ahora no tengo otros horarios disponibles, te contactamos pronto.",
                propuesta_de_actualizacion_de_estado={"datos_recopilados": {**datos, "etapa": "finalizada"}},
            )
        texto_opciones = "; ".join(
            f"{i+1}) {o.date} {o.time} en {o.location}" for i, o in enumerate(opciones)
        )
        return BrainOutput(
            senales_detectadas=["reprogramacion_solicitada"],
            respuesta_propuesta=f"Claro, aquí tienes otras opciones: {texto_opciones}. ¿Cuál prefieres?",
            proxima_accion_propuesta="preguntar_dato_faltante",  # ver comentario equivalente arriba
            tool_requerida={"name": "get_availability", "params": {"service": servicio}},
            propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos},
        )

    def _interpretar_seleccion_reprogramacion(self, texto: str, datos: Dict[str, Any]) -> BrainOutput:
        opciones = datos.get("opciones_reprogramacion", [])
        elegida = self._elegir_opcion(texto, opciones)
        if elegida is None:
            return BrainOutput(
                respuesta_propuesta="¿Me confirmas cuál opción prefieres: 1, 2 o 3?",
                proxima_accion_propuesta="preguntar_dato_faltante",
                propuesta_de_actualizacion_de_estado={"datos_recopilados": datos},
            )
        nuevos = {**datos, "etapa": "reprogramando"}
        return BrainOutput(
            respuesta_propuesta="Voy a reprogramar tu cita — un momento.",
            proxima_accion_propuesta="ejecutar_tool",
            tool_requerida={
                "name": "reschedule_appointment",
                "params": {
                    "appointment_id": self._activity.appointment_id,
                    "new_slot_id": elegida,
                    "idempotency_key": f"{self._activity.activity_id}:reschedule:{elegida}",
                },
            },
            propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos},
        )

    # ------------------------------------------------------------------
    def _cancelar(self, datos: Dict[str, Any]) -> BrainOutput:
        nuevos = {**datos, "etapa": "cancelando"}
        return BrainOutput(
            senales_detectadas=["cancelacion_solicitada"],
            respuesta_propuesta="Entendido, voy a cancelar tu cita.",
            proxima_accion_propuesta="ejecutar_tool",
            tool_requerida={
                "name": "cancel_appointment",
                "params": {"appointment_id": self._activity.appointment_id},
            },
            propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos},
        )
