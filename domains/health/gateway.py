"""
HealthGateway — punto de entrada BIDIRECCIONAL del dominio salud.

Evolución explícita del diseño de demanda inducida (recado 007): antes,
`domains/health/agent.py` asumía que cada conversación nacía de una
Activity creada por la IPS (contact_patient = siempre outbound). Este
módulo añade el camino INBOUND — un mensaje que llega sin que el
sistema sepa de antemano si es una respuesta a algo ya en curso o una
solicitud nueva del paciente — y el mecanismo de CORRELACIÓN que el
documento fuente no especificaba.

Principio de diseño: este archivo es NUEVO, no una modificación de
`agent.py`. Reutiliza `build_health_agent_context` y
`handle_patient_message` tal cual (import directo, cero copias) —
exactamente lo que exige la regla de "no duplicar" del prompt de
evolución (sección 15 del documento fuente original, sección
"Reutilización explícita" de este pedido). `HealthBrain`, `Activity`,
`AppointmentService`/`MockAppointmentService`, `ReminderManager`,
`ActivityResultSink` y `MockChannel` no se tocan.

La responsabilidad de correlación vive aquí (a nivel de dominio) y no
en el Core, porque el Core no sabe qué es una Activity ni un
patient_reference (003, principio 12: el Core es agnóstico de dominio).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .activity_source import ActivitySource
from .agent import HealthAgentContext, build_health_agent_context, handle_patient_message
from .appointment_service import AppointmentService, AppointmentStatus
from .confirmation import ConfirmationTracker
from .identity_store import EstadoIdentidadCanal, IdentidadCanalStore, SQLiteIdentidadCanalStore
from .intent import classify_intent
from .models import Activity, ActivityStatus, PatientRequest, RequestIntent, RequestStatus
from .patient_request_source import MockPatientRequestSource, PatientRequestSource
from .reminder_manager import ReminderManager
from .result_sink import ActivityResultSink
from state.models import FaseActual

# Estados de Activity que se consideran "conversación cerrada" para
# efectos de correlación (una vez ahí, un mensaje nuevo del mismo
# paciente debe generar una solicitud/Activity nueva, no reabrir esta).
_ACTIVITY_ESTADOS_CERRADOS = {
    ActivityStatus.COMPLETED,
    ActivityStatus.FAILED,
    ActivityStatus.CANCELLED,
    ActivityStatus.EXPIRED,
}

_MENSAJE_SIN_CITA_ACTIVA = (
    "No encuentro una cita activa a tu nombre para gestionar. "
    "Si quieres, puedo ayudarte a programar una nueva."
)
_MENSAJE_ESCALAMIENTO_INBOUND = (
    "Voy a pasar tu caso al equipo para que lo revise. "
    "No puedo garantizarte un contacto ni un tiempo específico."
)
_MENSAJE_INFORMACION_GENERICA = (
    "Puedo ayudarte a programar, reprogramar, cancelar o consultar una cita. "
    "¿Qué necesitas?"
)

# Canales cuyo identificador (`patient_reference`) NO es un documento de
# identidad (recado 012, R-15) — hoy solo ChatwootChannel (número de
# WhatsApp, ver `channels/chatwoot_channel.py:ChatwootChannel.canal`).
# Deliberadamente explícito (allowlist), no inferido del nombre del
# canal, para no gatear por accidente un canal futuro que sí entregue
# el documento directamente.
_CANALES_SIN_IDENTIFICADOR_DOCUMENTO = {"chatwoot"}


@dataclass
class HealthGateway:
    """Servicios COMPARTIDOS entre todas las conversaciones del dominio
    salud (a diferencia de `HealthAgentContext`, que es por Activity)."""

    activity_source: ActivitySource
    appointment_service: AppointmentService
    reminder_manager: ReminderManager
    result_sink: ActivityResultSink
    confirmation_tracker: ConfirmationTracker = field(default_factory=ConfirmationTracker)
    patient_request_source: PatientRequestSource = field(default_factory=MockPatientRequestSource)
    # Identidad del CANAL persistente entre conversaciones (recado 014,
    # extensión de R-15) — ver docstring de `domains/health/identity_store.py`
    # sobre por qué es un store propio, independiente del StateStore por
    # Activity. Default seguro (`:memory:`, sin persistencia real) para
    # cuando no se construye explícitamente (tests, demo) — en
    # producción `service/app.py` inyecta uno real vía `build_identity_store()`.
    identity_store: IdentidadCanalStore = field(default_factory=lambda: SQLiteIdentidadCanalStore(":memory:"))
    # Correlación (el mecanismo que el documento fuente no especificaba):
    # patient_reference -> conversation_id de la conversación abierta vigente.
    _open_conversations: Dict[str, str] = field(default_factory=dict)
    # conversation_id -> contexto ya construido, para poder reutilizar
    # handle_patient_message tal cual sin reconstruir nada.
    _contexts: Dict[str, HealthAgentContext] = field(default_factory=dict)
    # Sub-flujo de verificación por código (solo cuando el
    # AppointmentService activo lo exige — ver
    # `requires_verification_code` en HrmmAppointmentService, nunca en
    # MockAppointmentService): patient_reference -> acción pendiente de
    # confirmar con el código que se le envió al paciente.
    _pending_verifications: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # patient_reference -> documento_paciente ya resuelto (identidad
    # real cuando se usa HrmmAppointmentService — ver
    # `resolve_patient_identity`). Declarado en 009, conectado en 012
    # (R-15): mientras un identificador de canal (ej. número de
    # WhatsApp) no tenga entrada aquí, se le pide el documento antes de
    # continuar — ver `_pending_identity` y `_gestionar_identificacion`.
    _identidad_resuelta: Dict[str, str] = field(default_factory=dict)
    # patient_reference -> {"channel": str, "intentos": int}. Solo
    # existe mientras se está pidiendo/validando el documento de un
    # identificador de canal nuevo (recado 012, R-15) — se borra en
    # cuanto se resuelve (éxito) o se escala (máximo de intentos).
    _pending_identity: Dict[str, Dict[str, Any]] = field(default_factory=dict)


def build_health_gateway(
    activity_source: ActivitySource,
    appointment_service: AppointmentService,
    reminder_manager: ReminderManager,
    result_sink: ActivityResultSink,
    identity_store: Optional[IdentidadCanalStore] = None,
) -> HealthGateway:
    kwargs: Dict[str, Any] = {}
    if identity_store is not None:
        kwargs["identity_store"] = identity_store
    return HealthGateway(
        activity_source=activity_source,
        appointment_service=appointment_service,
        reminder_manager=reminder_manager,
        result_sink=result_sink,
        **kwargs,
    )


# ---------------------------------------------------------------------
# Correlación
# ---------------------------------------------------------------------
def register_context(gateway: HealthGateway, patient_reference: str, context: HealthAgentContext) -> None:
    gateway._open_conversations[patient_reference] = context.activity.activity_id
    gateway._contexts[context.activity.activity_id] = context


def find_open_context(gateway: HealthGateway, patient_reference: str) -> Optional[HealthAgentContext]:
    """Busca una conversación abierta para este identificador de canal
    (aquí, `patient_reference`). Verifica frescura en el momento de la
    consulta (en vez de exigir que alguien recuerde "cerrar" la entrada
    explícitamente en cada punto de finalización — menos superficie de
    error)."""
    conversation_id = gateway._open_conversations.get(patient_reference)
    if conversation_id is None:
        return None
    context = gateway._contexts.get(conversation_id)
    if context is None:
        gateway._open_conversations.pop(patient_reference, None)
        return None
    if context.activity.status in _ACTIVITY_ESTADOS_CERRADOS:
        gateway._open_conversations.pop(patient_reference, None)
        gateway._contexts.pop(conversation_id, None)
        return None
    return context


def start_activity_and_register(gateway: HealthGateway, activity: Activity) -> HealthAgentContext:
    """Envoltorio NUEVO para el camino OUTBOUND ya existente (recado 007):
    construye el contexto con las funciones ya construidas, sin tocarlas,
    y además lo registra para que un mensaje INBOUND posterior del mismo
    paciente (p. ej. respondiendo al contacto) se correlacione con esta
    misma conversación en vez de crear una PatientRequest nueva."""
    from .agent import accept_activity, contact_patient

    activity = gateway.activity_source.create(activity)
    context = build_health_agent_context(
        activity, gateway.activity_source, gateway.appointment_service,
        gateway.reminder_manager, gateway.result_sink,
    )
    accept_activity(context)
    contact_patient(context)
    register_context(gateway, activity.patient_reference, context)
    return context


# ---------------------------------------------------------------------
# Construcción de Activities sintéticas para solicitudes del paciente
# (reutilizan el MISMO motor conversacional — HealthBrain, Orchestrator,
# tools — sin duplicar nada; ver docstring del módulo).
# ---------------------------------------------------------------------
def _nueva_activity_sintetica(patient_reference: str, channel: str, objective: str, **overrides) -> Activity:
    datos = {
        "activity_id": f"SYN-{uuid.uuid4().hex[:10]}",
        "source_system": "PATIENT_INITIATED",
        "activity_type": "ACCESO_PACIENTE",
        "objective": objective,
        "patient_reference": patient_reference,
        "patient_contact": {},
        "service": "medicina general",
        "permitted_channels": [channel],
    }
    datos.update(overrides)
    return Activity(**datos)


def _sembrar_conversacion_inbound(context: HealthAgentContext) -> None:
    """Análogo a lo que `contact_patient` siembra para el camino
    outbound, pero sin enviar una plantilla saliente (aquí el paciente
    ya habló primero). Usa las mismas APIs públicas del Core
    (`orchestrator.store`) que ya usa `contact_patient` — no es una
    copia de su lógica de dominio, es el mismo primitivo de Core."""
    estado = context.orchestrator.store.create(context.activity.activity_id, canal="demo")
    actualizado = estado.model_copy(
        update={
            "fase_actual": FaseActual.IDENTIFICACION_DE_INTENCION,
            "datos_recopilados": {"etapa": "esperando_decision"},
            # Consentimiento: cuando es el PACIENTE quien inicia la
            # solicitud sobre su propia cita, el consentimiento para
            # procesar esa solicitud puntual es implícito en el acto de
            # pedirla (a diferencia del camino outbound, donde lo otorgó
            # el sistema originador — ver docstring de
            # agent.py:contact_patient). Documentado, no asumido en
            # silencio.
            "consentimiento_datos": True,
        }
    )
    context.orchestrator.store.save(actualizado, expected_version=estado.version)


# ---------------------------------------------------------------------
# Manejo de mensajes inbound
# ---------------------------------------------------------------------
def handle_inbound_message(gateway: HealthGateway, patient_reference: str, channel: str, message_id: str, text: str) -> str:
    # Sub-flujo de verificación por código: si esperamos un código de
    # este paciente (solo aplica con AppointmentService real, nunca con
    # Mock), este mensaje se trata como el intento de código, ANTES de
    # cualquier otra clasificación — no pasa por HealthBrain en absoluto.
    if patient_reference in gateway._pending_verifications:
        return _procesar_intento_de_codigo(gateway, patient_reference, text)

    contexto_existente = find_open_context(gateway, patient_reference)
    if contexto_existente is not None:
        # CORRELACIÓN: ya hay una conversación abierta (Activity de
        # demanda inducida en curso, o una PatientRequest anterior) —
        # se enruta ahí, con su estado y datos_recopilados intactos.
        # Reutiliza handle_patient_message TAL CUAL (misma función que
        # usa el camino de recordatorios — ver handle_reminder_response
        # en agent.py, sin tocar).
        respuesta = handle_patient_message(contexto_existente, message_id, text)
        _cerrar_si_definitivo(gateway, contexto_existente)
        return respuesta

    # Gate de identidad (recado 012, R-15): solo aplica cuando (a) el
    # AppointmentService activo distingue el identificador de canal del
    # documento real del paciente (HrmmAppointmentService, detectado por
    # duck-typing igual que `resolve_patient_identity` — con
    # MockAppointmentService nunca se activa, cero impacto en el camino
    # Mock/demo ya probado) Y (b) el CANAL concreto es de los que
    # entregan un identificador que NO es un documento (ej. un número de
    # WhatsApp vía ChatwootChannel — requisito explícito del usuario,
    # "ChatwootChannel, específicamente"). Otros canales (ej. "demo",
    # usados por la suite existente con HrmmAppointmentService) siguen
    # asumiendo patient_reference == documento, exactamente como antes
    # de esta extensión — no se generaliza el gate a todos los canales
    # sin evidencia de que lo necesiten. Nunca se llega aquí si YA hay
    # una conversación abierta (ver arriba) — el camino Activity/outbound
    # nunca pasa por `handle_inbound_message` y no se ve afectado
    # (`require_document_on_activity`, sin tocar).
    # Reconocimiento inmediato en un contacto SIGUIENTE (recado 014,
    # extensión de R-15): si este identificador de canal ya tiene una
    # fila VERIFICADO en `identity_store` (persistente — sobrevive a un
    # reinicio del proceso, a diferencia de `_identidad_resuelta`, que
    # es solo caché en memoria de ESTE proceso), se puebla directamente
    # ANTES del gate de abajo — nunca se vuelve a pedir documento ni
    # código. Mismo duck-typing que el resto del gate: solo aplica
    # cuando el AppointmentService activo distingue identificador de
    # canal de documento real.
    if patient_reference not in gateway._identidad_resuelta and _requiere_identidad_real(gateway):
        registro = gateway.identity_store.get(patient_reference)
        if registro is not None and registro.estado == EstadoIdentidadCanal.VERIFICADO:
            gateway._identidad_resuelta[patient_reference] = registro.documento

    if (
        channel in _CANALES_SIN_IDENTIFICADOR_DOCUMENTO
        and _requiere_identidad_real(gateway)
        and patient_reference not in gateway._identidad_resuelta
    ):
        return _gestionar_identificacion(gateway, patient_reference, channel, text)

    # No hay conversación abierta -> es una PatientRequest genuina.
    intent = classify_intent(text)
    request = gateway.patient_request_source.create(
        PatientRequest(
            request_id=f"REQ-{uuid.uuid4().hex[:10]}",
            patient_reference=patient_reference,
            intent=intent,
            channel=channel,
        )
    )

    if intent == RequestIntent.CONSULTAR_CITA:
        return _resolver_consulta(gateway, request)

    if intent == RequestIntent.CONFIRMAR_CITA:
        return _resolver_confirmacion(gateway, request)

    if intent == RequestIntent.ESCALAMIENTO:
        gateway.patient_request_source.update(request.model_copy(update={"status": RequestStatus.ESCALADA}))
        return _MENSAJE_ESCALAMIENTO_INBOUND

    if intent == RequestIntent.INFORMACION_SERVICIO:
        gateway.patient_request_source.update(request.model_copy(update={"status": RequestStatus.RESUELTA}))
        return _MENSAJE_INFORMACION_GENERICA

    if intent in (RequestIntent.REPROGRAMAR_CITA, RequestIntent.CANCELAR_CITA):
        return _resolver_gestion_de_cita_existente(gateway, request, channel, message_id, text)

    # PROGRAMAR_CITA / DEMANDA_INDUCIDA (inbound): reutiliza el mismo
    # flujo de aceptación -> disponibilidad -> reserva ya construido en
    # HealthBrain (sección "esperando_decision"), sin duplicarlo.
    return _resolver_programar_cita(gateway, request, channel, message_id, text)


def _resolver_programar_cita(gateway: HealthGateway, request: PatientRequest, channel: str, message_id: str, text: str) -> str:
    activity = _nueva_activity_sintetica(
        _documento_resuelto(gateway, request.patient_reference), channel,
        objective="Solicitud del paciente: programar cita",
    )
    activity = gateway.activity_source.create(activity)
    context = build_health_agent_context(
        activity, gateway.activity_source, gateway.appointment_service,
        gateway.reminder_manager, gateway.result_sink,
    )
    _sembrar_conversacion_inbound(context)
    register_context(gateway, request.patient_reference, context)
    gateway.patient_request_source.update(request.model_copy(update={"status": RequestStatus.EN_PROCESO}))

    # HealthBrain (sin tocar) espera una señal de aceptación explícita
    # para pasar a ofrecer disponibilidad (ver brain.py:_ACEPTA). Como
    # este gateway YA CLASIFICÓ la intención como "programar", se
    # traduce a la frase canónica que ese flujo ya reconoce — no se
    # duplica la lógica de reserva, solo se elige qué primer mensaje
    # alimentarle al mismo Brain.
    respuesta = handle_patient_message(context, message_id, "sí")
    if _cerrar_si_definitivo(gateway, context):
        gateway.patient_request_source.update(request.model_copy(update={"status": RequestStatus.RESUELTA}))
    return respuesta


def _resolver_gestion_de_cita_existente(
    gateway: HealthGateway, request: PatientRequest, channel: str, message_id: str, text: str
) -> str:
    citas_activas = [
        a
        for a in gateway.appointment_service.get_patient_appointments(_documento_resuelto(gateway, request.patient_reference))
        if a.status in (AppointmentStatus.CONFIRMED, AppointmentStatus.RESCHEDULED)
    ]
    if not citas_activas:
        gateway.patient_request_source.update(
            request.model_copy(update={"status": RequestStatus.RESUELTA})
        )
        return _MENSAJE_SIN_CITA_ACTIVA

    cita = citas_activas[0]

    # Con un AppointmentService que exige verificación por código
    # (HrmmAppointmentService — nunca MockAppointmentService), NO se
    # delega en HealthBrain para reprogramar/cancelar: hrmm-backend
    # exige documento_paciente + codigo, algo que el Protocol
    # AppointmentService/las tools existentes (sin tocar) no transportan.
    # Se envía el código y se pausa el turno — sub-flujo nuevo,
    # completo en este archivo (ver docstring del módulo).
    if getattr(gateway.appointment_service, "requires_verification_code", False):
        return _iniciar_verificacion_para_gestion(gateway, request, cita)

    activity = _nueva_activity_sintetica(
        _documento_resuelto(gateway, request.patient_reference), channel,
        objective="Solicitud del paciente: gestionar cita existente",
        appointment_id=cita.appointment_id,
        service=cita.service,
    )
    activity = gateway.activity_source.create(activity)
    context = build_health_agent_context(
        activity, gateway.activity_source, gateway.appointment_service,
        gateway.reminder_manager, gateway.result_sink,
    )
    _sembrar_conversacion_inbound(context)
    register_context(gateway, request.patient_reference, context)
    gateway.patient_request_source.update(request.model_copy(update={"status": RequestStatus.EN_PROCESO}))

    # Con `appointment_id` ya fijado en la Activity sintética, se
    # dispara la detección de reprogramación/cancelación de HealthBrain
    # (sin tocar), gatillada por sección independiente de la etapa —
    # EXACTAMENTE el mismo camino de código (brain.py:_iniciar_reprogramacion
    # / _cancelar, vía agent.py:handle_patient_message) que usa
    # handle_reminder_response para el mismo caso (ver test que lo
    # verifica explícitamente).
    #
    # El vocabulario de palabras clave de HealthBrain (_REPROGRAMAR /
    # _CANCELAR, sin tocar) es más angosto que el de este clasificador
    # de intención (intent.py) — p. ej. reconoce "cancelar la cita" pero
    # no "cancelar mi cita por favor". En vez de arriesgar que el texto
    # literal del paciente no dispare la detección ya construida (lo que
    # rompería la reutilización, no la evitaría), se traduce la
    # intención YA CLASIFICADA a una frase canónica que ese vocabulario
    # sí reconoce con certeza — el mismo patrón ya usado para
    # PROGRAMAR_CITA (traducido a "sí").
    frase_canonica = "reprogramar la cita" if request.intent == RequestIntent.REPROGRAMAR_CITA else "cancelar la cita"
    respuesta = handle_patient_message(context, message_id, frase_canonica)
    if _cerrar_si_definitivo(gateway, context):
        gateway.patient_request_source.update(request.model_copy(update={"status": RequestStatus.RESUELTA}))
    return respuesta


def _cerrar_si_definitivo(gateway: HealthGateway, context: HealthAgentContext) -> bool:
    """Cierre determinista de una Activity SINTÉTICA (iniciada por el
    paciente, `source_system == 'PATIENT_INITIATED'`) apenas su turno
    llega a un desenlace definitivo — nunca se aplica a una Activity de
    demanda inducida real (esas siguen su propio ciclo de vida a través
    de recordatorios, sin tocar por esta extensión).

    Sin este cierre, cualquier mensaje posterior del paciente sobre otro
    asunto quedaría atrapado en la conversación ya resuelta (encontrado
    manualmente al probar esta extensión — ver recado del dominio
    bidireccional): una solicitud del paciente es, por naturaleza, una
    transacción puntual, a diferencia de una campaña de demanda inducida
    que sigue en curso días después a través de sus propios
    recordatorios. Reutiliza `finalize_and_report` (agent.py) sin
    tocarla."""
    if context.activity.source_system != "PATIENT_INITIATED":
        return False
    if context.activity.status in _ACTIVITY_ESTADOS_CERRADOS:
        return False

    from .agent import finalize_and_report
    from .models import ManagementStatus

    if context.activity.management_status in (
        ManagementStatus.APPOINTMENT_CONFIRMED,
        ManagementStatus.RESCHEDULED,
        ManagementStatus.DECLINED,
    ):
        finalize_and_report(context)
        gateway._open_conversations.pop(context.activity.patient_reference, None)
        return True
    return False


def _resolver_consulta(gateway: HealthGateway, request: PatientRequest) -> str:
    """CONSULTAR_CITA — respuesta determinista, directa desde
    AppointmentService (nunca inventada, sin pasar por el Brain: es una
    consulta de lectura pura, no requiere máquina de estados)."""
    citas = [
        a
        for a in gateway.appointment_service.get_patient_appointments(_documento_resuelto(gateway, request.patient_reference))
        if a.status in (AppointmentStatus.CONFIRMED, AppointmentStatus.RESCHEDULED)
    ]
    gateway.patient_request_source.update(request.model_copy(update={"status": RequestStatus.RESUELTA}))
    if not citas:
        return "No tienes ninguna cita activa registrada por este canal."
    detalles = "; ".join(f"{c.service} el {c.date} a las {c.time} en {c.location}" for c in citas)
    return f"Tienes {len(citas)} cita(s) activa(s): {detalles}."


def _resolver_confirmacion(gateway: HealthGateway, request: PatientRequest) -> str:
    """CONFIRMAR_CITA iniciada sin conversación previa (fuera del flujo
    de recordatorio) — también determinista y directa."""
    citas_activas = [
        a
        for a in gateway.appointment_service.get_patient_appointments(_documento_resuelto(gateway, request.patient_reference))
        if a.status in (AppointmentStatus.CONFIRMED, AppointmentStatus.RESCHEDULED)
    ]
    gateway.patient_request_source.update(request.model_copy(update={"status": RequestStatus.RESUELTA}))
    if not citas_activas:
        return _MENSAJE_SIN_CITA_ACTIVA
    cita = citas_activas[0]
    gateway.confirmation_tracker.set_confirmed(cita.appointment_id)
    return "¡Perfecto, quedó registrada tu confirmación de asistencia!"


# ---------------------------------------------------------------------
# Sub-flujo de verificación por código (solo con AppointmentService que
# declara `requires_verification_code = True` — HrmmAppointmentService).
# Deliberadamente independiente de ConversationState/Orchestrator/
# HealthBrain: es un wizard determinista de 2-3 pasos (opción nueva si
# aplica -> código -> ejecutar), no una conversación abierta que
# necesite razonamiento — mismo criterio que `_resolver_consulta`
# (lectura pura, sin máquina de estados).
# ---------------------------------------------------------------------
_MENSAJE_CODIGO_INVALIDO = (
    "Ese código no es válido o ya venció. Puedes escribir uno nuevo, o pedir que te reenviemos otro."
)


def _elegir_opcion_ordinal(texto: str, opciones: list) -> Optional[str]:
    """Utilidad mínima y genérica ('1'/'primera' -> índice 0) — no es
    una copia de `HealthBrain._elegir_opcion` (privado, ligado a su
    propia máquina de etapas); aquí no hay ninguna lógica de dominio,
    solo interpretar un ordinal de una lista ya ofrecida."""
    texto = texto.lower()
    mapa = {"1": 0, "primera": 0, "2": 1, "segunda": 1, "3": 2, "tercera": 2}
    for clave, indice in mapa.items():
        if clave in texto and indice < len(opciones):
            return opciones[indice]
    return None


def _iniciar_verificacion_para_gestion(gateway: HealthGateway, request: PatientRequest, cita) -> str:
    # Antes de 012/R-15 se asumía patient_reference == documento_paciente
    # siempre; con un canal real (ej. WhatsApp vía ChatwootChannel),
    # patient_reference es el identificador de canal — el documento real
    # ya quedó resuelto por el gate de identidad (`_gestionar_identificacion`)
    # antes de que este código sea alcanzable, y vive en `_identidad_resuelta`.
    documento = _documento_resuelto(gateway, request.patient_reference)
    accion = "cancelar" if request.intent == RequestIntent.CANCELAR_CITA else "reprogramar"

    if accion == "reprogramar":
        opciones = gateway.appointment_service.get_availability(cita.service)[:3]
        if not opciones:
            gateway.patient_request_source.update(request.model_copy(update={"status": RequestStatus.RESUELTA}))
            return "Por ahora no tengo otros horarios disponibles para reprogramar, te contactamos pronto."
        gateway._pending_verifications[request.patient_reference] = {
            "action": accion,
            "appointment_id": cita.appointment_id,
            "documento_paciente": documento,
            "stage": "esperando_seleccion",
            "opciones_slot_id": [o.slot_id for o in opciones],
            "request_id": request.request_id,
            "service": cita.service,
        }
        texto_opciones = "; ".join(
            f"{i+1}) {o.date} {o.time} en {o.location}" for i, o in enumerate(opciones)
        )
        return f"Aquí tienes otras opciones: {texto_opciones}. ¿Cuál prefieres?"

    # Cancelar no necesita elegir nada — directo a enviar el código.
    return _enviar_codigo_y_pausar(gateway, request.patient_reference, accion, cita.appointment_id, documento, request.request_id)


def _enviar_codigo_y_pausar(
    gateway: HealthGateway, patient_reference: str, accion: str, appointment_id: str, documento: str, request_id: str,
    new_slot_id: Optional[str] = None,
) -> str:
    from .appointment_service import AppointmentServiceError

    try:
        resultado_envio = gateway.appointment_service.send_verification_code(documento)
    except AppointmentServiceError as exc:
        return f"No pude enviar el código de verificación ({exc}). Intenta de nuevo en un momento."

    gateway._pending_verifications[patient_reference] = {
        "action": accion,
        "appointment_id": appointment_id,
        "documento_paciente": documento,
        "stage": "esperando_codigo",
        "new_slot_id": new_slot_id,
        "request_id": request_id,
    }
    correo_parcial = resultado_envio.get("correo_parcial")
    pista = f" a tu correo ({correo_parcial})" if correo_parcial else " a tu correo"
    return f"Te enviamos un código{pista} para confirmar. Escríbelo aquí para continuar."


def _procesar_intento_de_codigo(gateway: HealthGateway, patient_reference: str, text: str) -> str:
    pendiente = gateway._pending_verifications[patient_reference]

    if pendiente["stage"] == "esperando_seleccion":
        elegida = _elegir_opcion_ordinal(text, pendiente["opciones_slot_id"])
        if elegida is None:
            return "No identifiqué cuál opción prefieres — ¿me confirmas 1, 2 o 3?"
        return _enviar_codigo_y_pausar(
            gateway, patient_reference, pendiente["action"], pendiente["appointment_id"],
            pendiente["documento_paciente"], pendiente["request_id"], new_slot_id=elegida,
        )

    # stage == "esperando_codigo": este mensaje ES el intento de código.
    codigo = text.strip()
    from .appointment_service import AppointmentServiceError

    try:
        if pendiente["action"] == "cancelar":
            cita_resultado = gateway.appointment_service.cancel_appointment_verified(
                pendiente["appointment_id"], pendiente["documento_paciente"], codigo
            )
        else:
            cita_resultado = gateway.appointment_service.reschedule_appointment_verified(
                pendiente["appointment_id"], pendiente["new_slot_id"],
                pendiente["documento_paciente"], codigo,
            )
    except AppointmentServiceError as exc:
        if "inválido" in str(exc) or "vencido" in str(exc):
            return _MENSAJE_CODIGO_INVALIDO
        del gateway._pending_verifications[patient_reference]
        return f"No pude completar la gestión ({exc}). Por favor intenta de nuevo."

    del gateway._pending_verifications[patient_reference]
    _reportar_resultado_verificado(gateway, pendiente, cita_resultado)

    if pendiente["action"] == "cancelar":
        return "Listo, tu cita quedó cancelada."
    return (
        f"Listo, tu cita quedó reprogramada: {cita_resultado.service} el {cita_resultado.date} "
        f"a las {cita_resultado.time} en {cita_resultado.location}."
    )


def _reportar_resultado_verificado(gateway: HealthGateway, pendiente: Dict[str, Any], cita_resultado) -> None:
    """Reporta el resultado al sistema originador directo vía
    ActivityResultSink (Protocol simple, sin necesitar el Orchestrator
    completo) — este sub-flujo es un wizard determinista, no una
    conversación que pase por Core (ver docstring de esta sección)."""
    from .models import ActivityResult, ActivityResultType

    tipo = ActivityResultType.CANCELLED if pendiente["action"] == "cancelar" else ActivityResultType.RESCHEDULED
    gateway.result_sink.send_result(
        ActivityResult(
            activity_id=f"VERIF-{pendiente['request_id']}",
            result=tipo,
            appointment_id=cita_resultado.appointment_id,
            correlation_id=pendiente["request_id"],
        )
    )
    gateway.patient_request_source.update(
        gateway.patient_request_source.get(pendiente["request_id"]).model_copy(
            update={"status": RequestStatus.RESUELTA}
        )
    )


# ---------------------------------------------------------------------
# Resolución de identidad (documento de identidad real) — solo relevante
# con HrmmAppointmentService; con MockAppointmentService, patient_reference
# ya es el identificador completo y no hace falta nada de esto.
# ---------------------------------------------------------------------
def resolve_patient_identity(gateway: HealthGateway, documento_paciente: str) -> Optional[Dict[str, str]]:
    """Camino PatientRequest (inbound): usa GET /citas/buscar-paciente
    (público, sin autenticación — mismo patrón ya usado por el
    webchat/portal de este ecosistema, confirmado leyendo el código
    real de hrmm-backend) para confirmar identidad antes de continuar.
    Devuelve None si no hay ningún registro previo con ese documento
    (paciente nuevo para hrmm-backend) — en ese caso, quien llama debe
    seguir sin nombre/teléfono confirmados, nunca inventarlos."""
    buscar = getattr(gateway.appointment_service, "buscar_paciente", None)
    if buscar is None:
        return None  # MockAppointmentService no tiene este concepto
    return buscar(documento_paciente)


# ---------------------------------------------------------------------
# Gate de identidad para el camino INBOUND por canal real (recado 012,
# R-15). Brecha encontrada al conectar ChatwootChannel: patient_reference
# ahí es el número de WhatsApp, pero el resto de este archivo (y
# HrmmAppointmentService, D-4) asume patient_reference == documento_paciente.
# Decisión de producto YA TOMADA por el usuario para esta fase: pedir el
# documento explícitamente en el primer turno de una conversación nueva
# por un canal así, ANTES de procesar cualquier intención — nunca inventar
# ni asumir.
#
# EXTENDIDO en recado 014 (2026-09-02): el resultado de este gate ya no
# se guarda solo en memoria del proceso (`_identidad_resuelta`) — se
# confirma con un código de verificación (`_iniciar_verificacion_de_identidad`
# / `_procesar_codigo_de_identificacion`) y se persiste en
# `identity_store` (`domains/health/identity_store.py`), para que un
# contacto SIGUIENTE del mismo teléfono (otro día, u otro proceso) sea
# reconocido de inmediato sin repetir el wizard — ver la hidratación al
# inicio de `handle_inbound_message`. Esto SÍ negocia un endpoint nuevo
# con hrmm-backend (`POST /api/agenda/verificacion/confirmar`), pero
# como contrato PROPUESTO/coordinado, nunca inventado en silencio — ver
# docstring de `HrmmAppointmentService.confirm_verification_code` y
# `.ai/RISKS.md`.
# ---------------------------------------------------------------------
_MAX_INTENTOS_IDENTIFICACION = 3

_MENSAJE_PEDIR_DOCUMENTO = (
    "Antes de continuar, ¿me confirmas tu número de documento de identidad? "
    "Lo necesito para consultar tus datos de forma segura."
)
_MENSAJE_IDENTIDAD_CONFIRMADA = (
    "Gracias, ya confirmé tu identidad. ¿En qué te puedo ayudar? "
    "Puedo programar, reprogramar, cancelar o consultar una cita."
)
_MENSAJE_DOCUMENTO_NO_ENCONTRADO = (
    "No encontré ningún paciente registrado con ese documento. "
    "¿Puedes verificarlo y escribirlo de nuevo?"
)


def _requiere_identidad_real(gateway: HealthGateway) -> bool:
    """Mismo duck-typing que `resolve_patient_identity`: solo los
    AppointmentService que distinguen identificador de canal de
    documento real (HrmmAppointmentService, vía `buscar_paciente`)
    necesitan este gate — con MockAppointmentService nunca se activa,
    cero cambio de comportamiento para toda la suite existente."""
    return getattr(gateway.appointment_service, "buscar_paciente", None) is not None


def _documento_resuelto(gateway: HealthGateway, patient_reference: str) -> str:
    """El documento real ya asociado a este identificador de canal, si
    se resolvió (ver `_gestionar_identificacion`) — o `patient_reference`
    tal cual si no hace falta resolución (MockAppointmentService, o un
    AppointmentService donde patient_reference YA es el documento,
    comportamiento idéntico al de antes de esta extensión)."""
    return gateway._identidad_resuelta.get(patient_reference, patient_reference)


def _gestionar_identificacion(gateway: HealthGateway, patient_reference: str, channel: str, text: str) -> str:
    """Wizard determinista de 3 pasos (pedir documento -> validar contra
    buscar-paciente -> confirmar con código de verificación, recado
    014), mismo criterio que el sub-flujo de verificación por código:
    independiente de ConversationState/Orchestrator/HealthBrain, con
    estado propio en `HealthGateway` (mismo patrón que
    `_pending_verifications`, para no duplicar un mecanismo de
    persistencia nuevo — `ConversationState` no existe todavía en este
    punto, la identidad se resuelve ANTES de crear cualquier
    Activity/PatientRequest). El resultado FINAL (paso 3, código
    válido) es lo único que se escribe en `identity_store` como
    VERIFICADO — ver `_iniciar_verificacion_de_identidad` y
    `_procesar_codigo_de_identificacion`."""
    pendiente = gateway._pending_identity.get(patient_reference)
    if pendiente is None:
        gateway._pending_identity[patient_reference] = {
            "channel": channel, "intentos": 0, "stage": "esperando_documento",
        }
        return _MENSAJE_PEDIR_DOCUMENTO

    if pendiente.get("stage") == "esperando_codigo":
        return _procesar_codigo_de_identificacion(gateway, patient_reference, pendiente, text)

    documento = text.strip()
    identidad = resolve_patient_identity(gateway, documento) if documento else None
    if identidad is not None:
        return _iniciar_verificacion_de_identidad(gateway, patient_reference, documento)

    pendiente["intentos"] += 1
    if pendiente["intentos"] >= _MAX_INTENTOS_IDENTIFICACION:
        del gateway._pending_identity[patient_reference]
        # Mecanismo de escalamiento YA EXISTENTE en este archivo (el
        # mismo que usa RequestIntent.ESCALAMIENTO más abajo) — nunca se
        # deja la conversación en un limbo sin salida.
        gateway.patient_request_source.create(
            PatientRequest(
                request_id=f"REQ-{uuid.uuid4().hex[:10]}",
                patient_reference=patient_reference,
                intent=RequestIntent.ESCALAMIENTO,
                channel=channel,
                status=RequestStatus.ESCALADA,
            )
        )
        return _MENSAJE_ESCALAMIENTO_INBOUND

    return _MENSAJE_DOCUMENTO_NO_ENCONTRADO


def _iniciar_verificacion_de_identidad(gateway: HealthGateway, patient_reference: str, documento: str) -> str:
    """Documento confirmado contra buscar-paciente — antes de asociarlo
    como confiable (recado 014, requisito #2c), se exige un segundo
    factor: código de 6 dígitos al correo del paciente (mismo mecanismo
    ya construido en 009 para cancelar/reprogramar,
    `send_verification_code` — sin inventar uno nuevo). Se registra la
    fila PENDIENTE_VERIFICACION en `identity_store` desde ya (requisito
    #1: la tabla debe reflejar el estado intermedio, no solo el final)."""
    from .appointment_service import AppointmentServiceError

    gateway.identity_store.guardar_pendiente(patient_reference, documento)
    try:
        resultado_envio = gateway.appointment_service.send_verification_code(documento)
    except AppointmentServiceError as exc:
        # No se pierde el progreso (documento ya validado, sigue en
        # `_pending_identity` en etapa "esperando_documento") — el
        # paciente puede simplemente reintentar el mismo documento.
        return f"No pude enviarte el código de verificación ({exc}). Intenta de nuevo en un momento."

    canal_original = gateway._pending_identity[patient_reference]["channel"]
    gateway._pending_identity[patient_reference] = {
        "channel": canal_original,
        "intentos": 0,
        "stage": "esperando_codigo",
        "documento_candidato": documento,
    }
    correo_parcial = resultado_envio.get("correo_parcial")
    pista = f" a tu correo ({correo_parcial})" if correo_parcial else " a tu correo"
    return f"Te enviamos un código{pista} para confirmar tu identidad. Escríbelo aquí para continuar."


def _procesar_codigo_de_identificacion(
    gateway: HealthGateway, patient_reference: str, pendiente: Dict[str, Any], text: str
) -> str:
    """Último paso del wizard (recado 014, requisito #2d): código
    correcto -> `identity_store.marcar_verificado` (única escritura de
    estado=VERIFICADO en todo el archivo) + puebla `_identidad_resuelta`
    para el resto de esta conversación, igual que antes de esta
    extensión. Código incorrecto/vencido -> se permite reintentar, SIN
    inventar un contador propio de intentos encima del que ya exige
    `send_verification_code`/`recovery_codes.py` del lado de
    hrmm-backend (5 intentos, TTL 10 min) — ese mecanismo ya decide
    cuándo un código deja de ser válido; este código solo refleja su
    resultado."""
    from .appointment_service import AppointmentServiceError

    documento = pendiente["documento_candidato"]
    codigo = text.strip()
    try:
        valido = gateway.appointment_service.confirm_verification_code(documento, codigo)
    except AppointmentServiceError as exc:
        return f"No pude confirmar el código ({exc}). Intenta de nuevo en un momento."

    if not valido:
        return _MENSAJE_CODIGO_INVALIDO

    del gateway._pending_identity[patient_reference]
    gateway.identity_store.marcar_verificado(patient_reference, documento)
    gateway._identidad_resuelta[patient_reference] = documento
    return _MENSAJE_IDENTIDAD_CONFIRMADA


def require_document_on_activity(activity: Activity) -> str:
    """Camino Activity (outbound, demanda inducida): con
    HrmmAppointmentService activo, el documento real del paciente es
    OBLIGATORIO en `Activity.patient_contact['documento']` — nunca se
    inventa ni se asume. Falla de forma clara y explícita si falta."""
    documento = (activity.patient_contact or {}).get("documento")
    if not documento:
        raise ValueError(
            f"Activity '{activity.activity_id}' no trae 'documento' en patient_contact — "
            "obligatorio para operar con HrmmAppointmentService (identidad real del paciente)."
        )
    return documento
