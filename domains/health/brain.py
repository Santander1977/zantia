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
# Respuesta de una sola palabra, mensaje COMPLETO (bug real de producción,
# primera conversación real de un paciente por Telegram, recado 026): un
# paciente que responde literalmente "Si"/"si" (sin tilde ni coma) a
# "¿Te gustaría...? Puedes responder sí o no" no coincidía con NINGÚN
# patrón de `_ACEPTA` — todos exigen tilde, coma o espacios alrededor,
# precisamente para no confundirse con un "si" incrustado en otra palabra
# ("asistir", "sinceramente"). Por eso esto se resuelve con una
# comparación de IGUALDAD sobre el mensaje ya limpiado de puntuación de
# borde, nunca con un substring adicional en `_ACEPTA`/`_DECLINA` (eso sí
# reintroduciría el falso positivo que el diseño original evitaba).
_ACEPTA_PALABRA_UNICA = ("si", "sí")
_DECLINA_PALABRA_UNICA = ("no",)
# Pregunta por el catálogo de servicios SIN nombrar uno específico
# (recado 027, bug real: "Programar cuál servicios tienes disponible" no
# se reconocía como esto — caía a `_PROGRAMAR` en `intent.py` por la
# palabra suelta "programar", y una vez dentro de la conversación
# tampoco había ningún patrón aquí que la reconociera, así que quedaba
# rebotando entre la pregunta fija de sí/no y "sin disponibilidad" para
# el servicio por defecto ("medicina general", nunca confirmado por el
# paciente). Mismas frases que `intent.py:_INFORMACION`, deliberadamente
# duplicadas en vez de importadas: `intent.py` clasifica un mensaje
# ENTRANTE sin conversación previa; esto reconoce la misma pregunta
# DENTRO de una conversación ya abierta — capas distintas, incluso si
# hoy el catálogo de frases coincide.
_CONSULTAR_SERVICIOS = (
    "qué servicios tienen", "qué servicios tienes", "qué servicios ofrecen",
    "cuáles servicios", "cuál servicios", "cuál servicio", "qué servicios hay",
    "servicios disponibles", "qué tienes disponible", "qué tienen disponible",
    "cuál tienes", "cuáles tienes",
)
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
# Olvido de identidad de canal (recado 016, extensión de R-20) — pedido
# explícito del paciente de que se elimine su asociación teléfono↔documento
# (`domains/health/identity_store.py`). Conjunto razonable de frases
# coloquiales en español (requisito #1 del pedido), no exhaustivo — mismo
# criterio que el resto de los conjuntos de este archivo (palabras clave,
# no NLU real, ver `.ai/RISKS.md` R-13).
_OLVIDAR = (
    "olvida mi número", "olvida mi numero", "olvida mi información", "olvida mi informacion",
    "olvida mis datos", "olvídame", "olvidame",
    "borra mi número", "borra mi numero", "borra mi información", "borra mi informacion",
    "borra mis datos",
    "elimina mi información", "elimina mi informacion", "elimina mis datos",
    "no quiero que tengas mis datos", "deja de guardar mis datos",
)


def _contains_any(texto: str, opciones: tuple) -> bool:
    return any(o in texto for o in opciones)


def _es_palabra_unica(texto: str, palabras: tuple) -> bool:
    """Compara por IGUALDAD (no substring) el mensaje completo, ya sin
    puntuación de borde (`"Si."`, `"¡si!"`) — ver comentario de
    `_ACEPTA_PALABRA_UNICA` arriba."""
    return texto.strip(" .!¡¿?,") in palabras


def _es_afirmativo(texto: str) -> bool:
    return _contains_any(texto, _ACEPTA) or _es_palabra_unica(texto, _ACEPTA_PALABRA_UNICA)


def _es_negativo(texto: str) -> bool:
    return _contains_any(texto, _DECLINA) or _es_palabra_unica(texto, _DECLINA_PALABRA_UNICA)


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

        # Olvido de identidad de canal (recado 016, extensión de R-20):
        # se reconoce en CUALQUIER etapa, con la MISMA prioridad que el
        # Core ya le da a una interrupción global (riesgo/escalamiento,
        # 004 sección 9) — ni siquiera depende de que haya una cita
        # reservada, a diferencia de reprogramar/cancelar/confirmar
        # abajo. `datos_recopilados["etapa"] == "confirmando_olvido"` es
        # un wizard de un solo paso PROPIO (no forma parte de ninguna
        # otra máquina de etapas existente) que se resuelve antes que
        # cualquier otra cosa, para no perder la confirmación pendiente
        # si el paciente escribe algo ambiguo mientras tanto.
        if etapa == "confirmando_olvido":
            return self._interpretar_confirmacion_olvido(texto, datos)
        if _contains_any(texto, _OLVIDAR):
            return self._iniciar_olvido(datos, etapa)

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
                    "Uy, esa parte no te la puedo compartir por este canal — no puedo darte información "
                    "clínica que no esté autorizada aquí. Si quieres, con gusto pongo tu duda "
                    "en manos del equipo para que te ayuden con eso."
                ),
                proxima_accion_propuesta="preguntar_intencion",
                propuesta_de_actualizacion_de_estado={"datos_recopilados": datos},
            )

        if _es_negativo(texto):
            nuevos = {**datos, "etapa": "finalizada", "decision": "DECLINED"}
            return BrainOutput(
                senales_detectadas=["paciente_declina"],
                respuesta_propuesta="Entiendo perfectamente, gracias por tu tiempo. Si más adelante cambias de opinión, aquí voy a estar.",
                propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos},
            )

        if _contains_any(texto, _HUMANO):
            nuevos = {**datos, "etapa": "escalada"}
            return BrainOutput(
                senales_detectadas=["solicita_humano"],
                respuesta_propuesta="Claro que sí, voy a poner tu caso en manos de una persona del equipo.",
                propuesta_de_actualizacion_de_estado={
                    "datos_recopilados": nuevos,
                    "necesidad_de_escalar": True,
                    "motivo_escalamiento": "paciente solicitó hablar con una persona",
                },
            )

        if _contains_any(texto, _NO_PUEDE_AHORA):
            nuevos = {**datos, "etapa": "finalizada", "decision": "NO_PUEDE_AHORA"}
            return BrainOutput(
                respuesta_propuesta="Sin problema, lo intentamos en otro momento — gracias por tu tiempo.",
                propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos},
            )

        if _contains_any(texto, _PIDE_INFO):
            # NUNCA "te contactamos" (mismo hallazgo del recado 026,
            # esta rama se había quedado sin corregir): esa frase está en
            # `guardrails/rules.py:_PROMESAS_PROHIBIDAS` y
            # `NoPrometerContactoGuardrail` la reescribe en silencio por
            # el mensaje genérico de escalamiento.
            motivo = self._activity.reason or self._activity.program or "una atención pendiente"
            return BrainOutput(
                respuesta_propuesta=(
                    f"Con gusto te cuento: esto es sobre {motivo}. La idea es ayudarte a "
                    "programar tu atención cuando te quede cómodo. ¿Revisamos juntos las opciones de horario?"
                ),
                proxima_accion_propuesta="preguntar_intencion",
                propuesta_de_actualizacion_de_estado={"datos_recopilados": datos},
            )

        # Pregunta por el catálogo de servicios, sin nombrar uno
        # específico (recado 027) — se responde con el catálogo REAL
        # (`AppointmentService.list_services()`, duck-typed, nunca
        # inventado) y se queda en la MISMA etapa ("esperando_decision")
        # para que el paciente pueda seguir la conversación con
        # normalidad después (p. ej. decir "sí" para ver disponibilidad,
        # o nombrar uno de los servicios listados).
        if _contains_any(texto, _CONSULTAR_SERVICIOS):
            listar = getattr(self._appointment_service, "list_services", None)
            servicios = listar() if listar else []
            if servicios:
                texto_servicios = ", ".join(servicios)
                respuesta = (
                    f"Claro, estos son los servicios que tenemos disponibles: {texto_servicios}. "
                    "¿Te gustaría que te ayude a agendar una cita para alguno?"
                )
            else:
                respuesta = (
                    "Por ahora no tengo el catálogo de servicios a la mano — "
                    "¿me cuentas qué tipo de atención necesitas?"
                )
            return BrainOutput(
                senales_detectadas=["consulta_catalogo_servicios"],
                respuesta_propuesta=respuesta,
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
                    "Con gusto te ayudo con eso — ¿me confirmas el número de documento de identidad "
                    "de la persona para quien es la cita?"
                ),
                proxima_accion_propuesta="preguntar_dato_faltante",
                propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos},
            )

        if _es_afirmativo(texto):
            return self._ofrecer_disponibilidad(datos)

        # Redacción deliberadamente NO fija/memorizada (recado 027):
        # esta es la respuesta que se repite cada vez que el paciente
        # escribe algo que no reconocemos en esta etapa — sonaba
        # robótica al repetirse literalmente turno tras turno en una
        # conversación real. Sigue siendo la MISMA pregunta cerrada de
        # sí/no (ninguna garantía ni guardrail cambia), solo con mejor
        # redacción.
        return BrainOutput(
            respuesta_propuesta="¿Te ayudo a agendar tu atención? Con que me digas sí o no, ya sé cómo seguir.",
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
            # NUNCA "te contactamos" (recado 026, hallazgo real de
            # producción): esa frase está en `guardrails/rules.py:
            # _PROMESAS_PROHIBIDAS` (lección de Dani, 002) y
            # `NoPrometerContactoGuardrail` la reescribe en silencio por
            # el mensaje genérico de escalamiento — el paciente termina
            # leyendo "voy a registrar tu caso... no puedo garantizar
            # contacto" en vez de la razón real (sin turnos disponibles
            # AHORA), sin que se haya escalado nada de verdad
            # (`necesidad_de_escalar` nunca se puso en True aquí).
            return BrainOutput(
                respuesta_propuesta=(
                    "Lamento decirte que por ahora no tengo horarios disponibles para ese servicio. "
                    "Escríbeme más tarde y lo revisamos de nuevo con gusto."
                ),
                propuesta_de_actualizacion_de_estado={"datos_recopilados": {**datos, "etapa": "finalizada"}},
            )
        texto_opciones = "; ".join(
            f"{i+1}) {o.date} {o.time} en {o.location}" for i, o in enumerate(opciones)
        )
        return BrainOutput(
            respuesta_propuesta=f"¡Perfecto! Estas son las opciones disponibles: {texto_opciones}. ¿Cuál te queda mejor?",
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
                    "No encontré ningún paciente registrado con ese documento — "
                    "¿puedes revisarlo y escribírmelo de nuevo?"
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
            respuesta_propuesta=f"Perfecto, vamos a agendar para {nombre} — ¿es correcto?",
            proxima_accion_propuesta="preguntar_dato_faltante",
            propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos},
        )

    def _interpretar_confirmacion_beneficiario(self, texto: str, datos: Dict[str, Any]) -> BrainOutput:
        """Tercer paso: el titular confirma explícitamente el nombre
        antes de continuar (requisito #2, "para que el titular confirme
        explícitamente... antes de continuar") — cualquier respuesta que
        no sea una aceptación clara vuelve a pedir el documento, nunca
        asume un "sí" implícito."""
        if not _es_afirmativo(texto):
            nuevos = {**datos, "etapa": "esperando_documento_beneficiario"}
            return BrainOutput(
                respuesta_propuesta=(
                    "Entendido, ¿me confirmas cuál es el documento correcto de la "
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
                respuesta_propuesta="No logré identificar cuál prefieres — ¿me confirmas si es la 1, la 2 o la 3?",
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
            respuesta_propuesta="¡Perfecto! Voy a reservarlo — dame un momento.",
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
            # Ver comentario equivalente en `_ofrecer_disponibilidad`
            # (recado 026) — misma razón, nunca "te contactamos".
            return BrainOutput(
                senales_detectadas=["reprogramacion_solicitada"],
                respuesta_propuesta=(
                    "Lamento decirte que por ahora no tengo otros horarios disponibles para ese servicio. "
                    "Escríbeme más tarde y lo revisamos de nuevo con gusto."
                ),
                propuesta_de_actualizacion_de_estado={"datos_recopilados": {**datos, "etapa": "finalizada"}},
            )
        texto_opciones = "; ".join(
            f"{i+1}) {o.date} {o.time} en {o.location}" for i, o in enumerate(opciones)
        )
        return BrainOutput(
            senales_detectadas=["reprogramacion_solicitada"],
            respuesta_propuesta=f"Claro que sí, aquí tienes otras opciones: {texto_opciones}. ¿Cuál te queda mejor?",
            proxima_accion_propuesta="preguntar_dato_faltante",  # ver comentario equivalente arriba
            tool_requerida={"name": "get_availability", "params": {"service": servicio}},
            propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos},
        )

    def _interpretar_seleccion_reprogramacion(self, texto: str, datos: Dict[str, Any]) -> BrainOutput:
        opciones = datos.get("opciones_reprogramacion", [])
        elegida = self._elegir_opcion(texto, opciones)
        if elegida is None:
            return BrainOutput(
                respuesta_propuesta="¿Me confirmas cuál opción prefieres — la 1, la 2 o la 3?",
                proxima_accion_propuesta="preguntar_dato_faltante",
                propuesta_de_actualizacion_de_estado={"datos_recopilados": datos},
            )
        nuevos = {**datos, "etapa": "reprogramando"}
        return BrainOutput(
            respuesta_propuesta="Listo, voy a reprogramar tu cita — dame un momento.",
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
            respuesta_propuesta="Entendido, voy a cancelar tu cita ahora mismo.",
            proxima_accion_propuesta="ejecutar_tool",
            tool_requerida={
                "name": "cancel_appointment",
                "params": {"appointment_id": self._activity.appointment_id},
            },
            propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos},
        )

    # ------------------------------------------------------------------
    # Olvido de identidad de canal (recado 016, extensión de R-20).
    # Wizard de 2 pasos, análogo en espíritu al de beneficiario (013)
    # pero deliberadamente SIN tocar ninguno de sus campos/etapas
    # (requisito #5: no debe interferir con la gestión de beneficiario).
    # Nunca propone `tool_requerida`: el borrado real no es una tool del
    # Protocol `AppointmentService` — lo ejecuta `gateway.py` (que sí
    # tiene acceso a `identity_store`) al ver `etapa == "olvido_confirmado"`,
    # ver `_procesar_olvido_si_corresponde`. Este Brain solo PROPONE.
    # ------------------------------------------------------------------
    def _iniciar_olvido(self, datos: Dict[str, Any], etapa_anterior: str) -> BrainOutput:
        nuevos = {**datos, "etapa": "confirmando_olvido", "etapa_antes_de_olvido": etapa_anterior}
        return BrainOutput(
            senales_detectadas=["olvido_de_identidad_solicitado"],
            respuesta_propuesta=(
                "Entendido — ¿confirmas que quieres que olvide tu número? "
                "Ten en cuenta que vas a tener que verificarte de nuevo la próxima vez que escribas."
            ),
            proxima_accion_propuesta="preguntar_dato_faltante",
            propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos},
        )

    def _interpretar_confirmacion_olvido(self, texto: str, datos: Dict[str, Any]) -> BrainOutput:
        """Solo una aceptación CLARA (mismo vocabulario `_ACEPTA` ya
        usado en el resto de este archivo) confirma el borrado —
        cualquier otra respuesta (declina, ambigua, otro tema) cancela
        la solicitud SIN borrar nada (requisito #3: "nunca borres sin
        una confirmación clara") y restaura la etapa en la que estaba
        el paciente antes de pedir el olvido, para no perder su lugar
        en la conversación."""
        etapa_anterior = datos.get("etapa_antes_de_olvido", "esperando_decision")
        if not _es_afirmativo(texto):
            nuevos = {k: v for k, v in datos.items() if k != "etapa_antes_de_olvido"}
            nuevos["etapa"] = etapa_anterior
            return BrainOutput(
                senales_detectadas=["olvido_de_identidad_cancelado"],
                respuesta_propuesta="Entendido, no voy a borrar nada — sigamos. ¿En qué más te ayudo?",
                # "preguntar_dato_faltante" (no "preguntar_intencion"): la
                # etapa restaurada puede venir de una fase_actual distinta
                # de IDENTIFICACION_DE_INTENCION (ej. RECOPILACION_DE_DATOS,
                # si el olvido se pidió a mitad de "esperando_seleccion")
                # — "preguntar_intencion" solo es una transición VÁLIDA
                # desde ciertas fases (state/machine.py:VALID_TRANSITIONS),
                # y usarla aquí sin condición disparaba una escalación real
                # por "error de transición" (bug encontrado con un test de
                # esta misma extensión, recado 016). "preguntar_dato_faltante"
                # es válida desde cualquier fase donde este wizard puede
                # interrumpirse.
                proxima_accion_propuesta="preguntar_dato_faltante",
                propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos},
            )
        nuevos = {k: v for k, v in datos.items() if k != "etapa_antes_de_olvido"}
        nuevos["etapa"] = "olvido_confirmado"
        return BrainOutput(
            senales_detectadas=["olvido_de_identidad_confirmado"],
            respuesta_propuesta="Listo, olvidé tu número — la próxima vez tendrás que verificarte de nuevo.",
            propuesta_de_actualizacion_de_estado={"datos_recopilados": nuevos},
        )
