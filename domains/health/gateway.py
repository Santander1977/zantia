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

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from observability.events import EventType

from .activity_source import ActivitySource
from .agent import HealthAgentContext, build_health_agent_context, handle_patient_message
from .appointment_service import AppointmentService, AppointmentStatus
from .brain import _formatear_fecha_humana, _lista_numerada
from .confirmation import ConfirmationTracker
from .identity_store import IdentidadCanalStore, SQLiteIdentidadCanalStore
from .intent import _PROGRAMAR as _PALABRAS_PROGRAMAR_CITA
from .intent import _sin_tildes as _sin_tildes_menu
from .intent import classify_intent_or_none
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
    "No encuentro ninguna cita activa a tu nombre para gestionar. "
    "Si quieres, con gusto te ayudo a programar una nueva."
)
# Mensaje de escalamiento (recado 002, lección de Dani) — deliberadamente
# SIN cambios de redacción en el pase de tono del recado 027: es la
# frase exacta que varios tests verifican como garantía de seguridad
# ("pasar tu caso al equipo", nunca "contactamos"/"te llaman"), y un
# mensaje de escalamiento prioriza claridad sobre calidez — el paciente
# necesita saber con precisión qué va a pasar, no que suene amigable.
_MENSAJE_ESCALAMIENTO_INBOUND = (
    "Voy a pasar tu caso al equipo para que lo revise. "
    "No puedo garantizarte un contacto ni un tiempo específico."
)
_MENSAJE_INFORMACION_GENERICA = (
    "¡Claro! Puedo ayudarte a programar, reprogramar, cancelar o consultar una cita. "
    "¿Qué necesitas?"
)

# Saludo institucional de primer contacto (recado 046, pedido explícito
# del usuario): guion FIJO, construido enteramente en este archivo
# (gateway.py) — nunca pasa por `HealthBrain.interpret()`/
# `HealthAnthropicBrain` en absoluto, así que es estructuralmente
# imposible que el LLM lo redacte o altere, aunque `HEALTH_BRAIN_TYPE=llm`
# esté activo (se concatena AFUERA de cualquier llamada al Brain — ver
# `handle_inbound_message`). No hizo falta reforzar el prompt de
# sistema del LLM para "proteger" este texto: nunca se le muestra.
_PRESENTACION_ANDRES = (
    "Soy Andrés, tu asistente virtual para la gestión de tus citas médicas "
    "del Hospital Regional del Magdalena Medio."
)


def _saludo_segun_hora_bogota(ahora: Optional[datetime] = None) -> str:
    """Franja horaria real del servidor, SIEMPRE en zona horaria
    America/Bogota (pedido explícito — el proceso puede correr en
    cualquier zona horaria de infraestructura, ej. UTC en EasyPanel).
    Convención elegida (no hay un estándar único en español, se
    documenta la elegida): 05:00-11:59 "Buenos días", 12:00-18:59
    "Buenas tardes", el resto "Buenas noches". `zoneinfo` es de la
    librería estándar (sin dependencia nueva) — confirmado con una
    prueba real dentro del contenedor Docker real (recado 046) que la
    base de datos de zonas horarias SÍ está disponible en la imagen
    `python:3.11-slim` usada por este proyecto, sin necesitar el
    paquete `tzdata` adicional.

    `ahora` es un punto de inyección SOLO para tests (permite fijar una
    hora exacta sin depender del reloj real de la máquina que corre la
    suite) — en uso real siempre se omite y se usa la hora real."""
    momento = ahora if ahora is not None else datetime.now(ZoneInfo("America/Bogota"))
    hora = momento.hour
    if 5 <= hora < 12:
        return "Buenos días"
    if 12 <= hora < 19:
        return "Buenas tardes"
    return "Buenas noches"


def _tratamiento_formal(nombre: str) -> str:
    """Heurística SIMPLE y declaradamente imperfecta (decisión explícita
    del recado 046, pedido del usuario de "decidir y documentar"):
    ningún dato de género real existe hoy — ni `identity_store.py`
    (recado 034) ni `buscar-paciente` de hrmm-backend lo capturan — así
    que no hay ninguna fuente de verdad que consultar, solo inferir.
    Se usa la convención mayoritaria en español (nombre termina en "a"
    -> "señora", cualquier otro caso -> "señor") sobre el PRIMER nombre
    ya capturado. Riesgo aceptado y documentado: falla con nombres
    unisex o con terminaciones atípicas (ej. "Nicolás" no termina en
    "a", correcto; pero un nombre femenino que no termine en "a" -ej.
    "Carmen", "Soledad"- se trataría erróneamente como "señor"). No se
    implementó ninguna forma neutra como default porque el pedido
    explícito de tono (mismo criterio que "señor/señora" en el ejemplo
    dado) prioriza sonar formal y personalizado sobre evitar por
    completo el riesgo de un error ocasional — queda documentado como
    mejora pendiente si se decide capturar una preferencia real."""
    primer_nombre = nombre.strip().split()[0] if nombre.strip() else ""
    return "señora" if primer_nombre.lower().endswith("a") else "señor"


# Menú numerado de 4 opciones (recado 046, requisito explícito: SIEMPRE
# número + palabra, nunca texto corrido) — texto FIJO, nunca redactado
# por el LLM (misma razón que el resto de este bloque: se construye
# aquí, jamás se le pasa a HealthBrain/HealthAnthropicBrain).
_MENU_NUMERADO = (
    "1. Reservar una cita\n"
    "2. Reprogramar una cita\n"
    "3. Cancelar una cita\n"
    "4. Consultar mis citas"
)

# Recado 048 — para el turno AMBIGUO que llega DESPUÉS de que ya se le
# mostró el saludo institucional completo una vez (ver `_saludo_mostrado`
# en HealthGateway): un recordatorio corto del menú, nunca la
# presentación completa de nuevo (esa ya se mostró).
_MENSAJE_INTENCION_NO_RECONOCIDA = (
    f"No logré identificar qué necesitas — puedes responder con el número o la palabra "
    f"de una de estas opciones:\n{_MENU_NUMERADO}"
)

# (ordinal, palabras/frases clave) -> RequestIntent — reutiliza el
# VOCABULARIO ya existente en `intent.py` (_PROGRAMAR/_REPROGRAMAR/
# _CANCELAR/_CONSULTAR) más las palabras sueltas típicas de una
# respuesta a ESTE menú puntual ("reservar", "cancelar" a secas, que
# `intent.py:classify_intent` no reconoce por sí solas porque su
# vocabulario exige frases más largas como "cancelar mi cita" — acá SÍ
# basta la palabra sola, porque el contexto ya es inequívoco: se le
# acaba de mostrar un menú de 4 opciones). Deliberadamente una función
# NUEVA, no una reutilización directa de `classify_intent` — esa
# función SIEMPRE cae a `PROGRAMAR_CITA` por defecto si no reconoce
# nada (correcto para un mensaje libre inicial), lo cual sería
# INCORRECTO acá: si la respuesta al menú no se reconoce, hay que
# volver a preguntar, nunca asumir "reservar".
# Deliberadamente NO se incluyen aquí los tuples completos de
# `intent.py` (`_PROGRAMAR`/`_REPROGRAMAR`/`_CANCELAR`/`_CONSULTAR`) —
# hallazgo real al migrar los tests existentes (recado 046): esas listas
# ya las reconoce `classify_intent` con un ORDEN DE PRIORIDAD específico
# y ya probado (`_INFORMACION` se revisa ANTES que `_PROGRAMAR`,
# recado 027, precisamente para que "Programar cuál servicios tienes
# disponible" se clasifique como pregunta de catálogo, no como reserva,
# solo por contener la palabra "programar"). Si esta función revisara
# esas mismas listas ANTES de `classify_intent` (que es como se usa,
# ver `_enrutar_solicitud_nueva`), se saltaría esa prioridad ya
# establecida. Acá solo se agregan las formas BARE (palabra sola) que
# `classify_intent` NUNCA reconocía por sí solo — "reservar"/"cancelar"/
# "consultar" no aparecen en ninguna de sus listas — y el ordinal
# "reprogramar" YA está en `_REPROGRAMAR` así que no hace falta
# repetirlo aquí.
_MENU_OPCIONES: tuple = (
    ("1", RequestIntent.PROGRAMAR_CITA, ("reservar",)),
    ("2", RequestIntent.REPROGRAMAR_CITA, ()),
    ("3", RequestIntent.CANCELAR_CITA, ("cancelar",)),
    ("4", RequestIntent.CONSULTAR_CITA, ("consultar", "consultar mis citas")),
)


def _interpretar_opcion_menu(texto: str) -> Optional[RequestIntent]:
    """Acepta AMBAS formas de respuesta al menú numerado (requisito
    explícito): el ordinal exacto ("1"-"4") o cualquiera de las
    palabras/frases clave de esa opción, en cualquier parte del
    mensaje (mismo criterio de `_contains_any` de `brain.py` — sin
    tildes, para el mismo tipo de error de tipeo real ya documentado en
    los recados 026/030). Devuelve `None` si no reconoce nada — quien
    llama debe volver a preguntar, nunca asumir una opción por
    default."""
    # Límite de palabra (`\b`) en TODOS los chequeos, no solo el
    # ordinal — hallazgo real al migrar los tests existentes (recado
    # 046): "programar" es substring literal de "reprogramar" ("re" +
    # "programar"), así que un `in` simple habría matcheado SIEMPRE la
    # opción 1 (reservar) para cualquier mensaje de reprogramar. `\b`
    # exige un límite real de palabra en ambos lados, evitando este
    # falso positivo sin perder el resto de la tolerancia ya construida
    # (sin tildes, en cualquier parte del mensaje).
    texto_norm = _sin_tildes_menu(texto.strip().lower())
    for ordinal, intent, palabras_clave in _MENU_OPCIONES:
        if re.search(rf"\b{ordinal}\b", texto_norm):
            return intent
        if any(
            re.search(rf"\b{re.escape(_sin_tildes_menu(palabra.lower()))}\b", texto_norm)
            for palabra in palabras_clave
        ):
            return intent
    return None


def _saludo_primer_contacto(nombre_conocido: Optional[str]) -> str:
    """Construye el guion institucional fijo de primer contacto (recado
    046) — SIEMPRE con la franja horaria real, nunca inventada, y
    SIEMPRE con el menú numerado de 4 opciones al final.

    - Paciente YA reconocido (identidad persistida y vigente, recados
      014/034): saludo personalizado y formal, con tratamiento
      señor/señora + nombre real + pregunta abierta — sin repetir la
      presentación completa ("soy Andrés..."), pero sí el menú.
    - Paciente nuevo (sin identidad persistida todavía): saludo
      genérico + presentación institucional completa + el mismo menú —
      ANTES de pedir cualquier documento (se antepone al mensaje que
      sea, incluyendo el que pide el documento de identidad, ver
      `handle_inbound_message`)."""
    saludo_hora = _saludo_segun_hora_bogota()
    if nombre_conocido:
        tratamiento = _tratamiento_formal(nombre_conocido)
        return f"¡{saludo_hora}, {tratamiento} {nombre_conocido}! ¿Qué desea hacer hoy?\n{_MENU_NUMERADO}"
    return f"{saludo_hora}. {_PRESENTACION_ANDRES} ¿Qué deseas hacer?\n{_MENU_NUMERADO}"


# Recado 056, Punto 3 — pedido explícito del usuario: si el paciente
# escribe de nuevo poco tiempo después de que su interacción anterior
# cerró efectivamente (reserva confirmada/reprogramada/declinada), no
# tiene sentido repetirle la presentación institucional completa ni el
# menú extenso — ya la vio hace un momento. Umbral decidido de forma
# autónoma (pedido explícito del usuario, "decide tú"): 30 minutos —
# suficientemente corto para significar "la misma sesión de uso", lo
# bastante largo para cubrir que el paciente se distraiga un momento
# antes de escribir de nuevo. Pasado ese umbral, se trata como un
# regreso genuinamente nuevo (saludo completo de siempre).
_VENTANA_SALUDO_CORTO = timedelta(minutes=30)


def _saludo_corto_de_regreso(nombre_conocido: Optional[str]) -> str:
    """SIN presentación institucional ("Soy Andrés...") ni menú
    numerado — solo el saludo corto + una pregunta abierta. Si no se
    conoce el nombre (caso raro: se cerró una Activity sin
    `patient_contact.nombre`), usa una forma neutra sin tratamiento
    formal en vez de inventar un nombre."""
    saludo_hora = _saludo_segun_hora_bogota()
    if nombre_conocido:
        tratamiento = _tratamiento_formal(nombre_conocido)
        return f"¡{saludo_hora}, {tratamiento} {nombre_conocido}! ¿Puedo ayudarlo en algo más?"
    return f"¡{saludo_hora}! ¿Puedo ayudarte en algo más?"


def _resolver_consulta_catalogo(gateway: "HealthGateway", request: PatientRequest, channel: str) -> str:
    """RequestIntent.INFORMACION_SERVICIO — responde "qué servicios
    tienen" con el catálogo REAL ya sincronizado (recado 027), nunca
    inventado. `list_services()` es duck-typed (mismo criterio que
    `buscar_paciente`), así que un `AppointmentService` que no lo
    implemente, o un catálogo que todavía no sincronizó (lista vacía),
    cae al mensaje genérico existente.

    Bug real corregido (recado 031): ANTES esta rama solo informaba el
    catálogo sin abrir ninguna conversación — si el paciente respondía
    justo después nombrando un servicio real, esa respuesta no tenía
    NINGÚN estado "esperando_servicio" que la reconociera (`find_open_context`
    devolvía `None`), así que se reprocesaba desde cero como un mensaje
    nuevo sin relación, y terminaba cayendo al fallback genérico de
    sí/no de `HealthBrain` — el paciente sentía que "responder bien" no
    servía de nada. Ahora se abre una Activity sintética y se deja la
    conversación en `esperando_servicio` (MISMO mecanismo que
    `_resolver_programar_cita` usa cuando detecta más de un servicio
    real, ver `_determinar_servicio_inicial`) — el paciente puede
    nombrar el servicio a continuación y el flujo sigue con normalidad
    hacia disponibilidad real."""
    gateway.patient_request_source.update(request.model_copy(update={"status": RequestStatus.RESUELTA}))
    listar = getattr(gateway.appointment_service, "list_services", None)
    servicios = listar() if listar else []
    if not servicios:
        return _MENSAJE_INFORMACION_GENERICA

    nombre = _nombre_conocido(gateway, request.patient_reference)
    activity = _nueva_activity_sintetica(
        _documento_resuelto(gateway, request.patient_reference), channel,
        objective="Solicitud del paciente: consultar catálogo de servicios",
        service=None,
        patient_contact={"nombre": nombre} if nombre else {},
    )
    activity = gateway.activity_source.create(activity)
    context = build_health_agent_context(
        activity, gateway.activity_source, gateway.appointment_service,
        gateway.reminder_manager, gateway.result_sink,
    )
    _sembrar_conversacion_inbound(context)
    register_context(gateway, request.patient_reference, context)

    estado = context.orchestrator.store.get(context.activity.activity_id)
    nuevos_datos = {**estado.datos_recopilados, "etapa": "esperando_servicio"}
    context.orchestrator.store.save(
        estado.model_copy(update={"datos_recopilados": nuevos_datos}), expected_version=estado.version
    )

    lista_servicios = _lista_numerada(servicios)
    return f"Estos son los servicios que tenemos disponibles:\n{lista_servicios}\n¿Para cuál te gustaría agendar?"

# Canales cuyo identificador (`patient_reference`) NO es un documento de
# identidad (recado 012, R-15) — ChatwootChannel (número de WhatsApp) y,
# desde recado 022, TelegramChannel (chat.id de Telegram — ver
# `channels/telegram_channel.py:TelegramChannel.canal`), tampoco un
# documento. Deliberadamente explícito (allowlist), no inferido del
# nombre del canal, para no gatear por accidente un canal futuro que sí
# entregue el documento directamente. Requisito #3 del pedido de
# recado 022: un usuario de Telegram nuevo pasa por el MISMO wizard de
# identificación de 012/014/016 (documento -> código -> identidad_canal,
# con vencimiento a 180 días y olvido a pedido) — cero código nuevo
# hizo falta para esto, solo agregar "telegram" acá.
_CANALES_SIN_IDENTIFICADOR_DOCUMENTO = {"chatwoot", "telegram"}


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
    # patient_reference -> ya se le mostró el saludo institucional
    # completo (recado 048) MIENTRAS todavía no existe ninguna
    # conversación abierta para él (`_open_conversations`) — cubre el
    # tramo entre "hola" (sin intención reconocible, no crea nada
    # todavía) y el turno en que sí da una intención clara. Se limpia en
    # `_cerrar_si_definitivo` (mismo momento en que se libera
    # `_open_conversations`) para que un ciclo de conversación
    # GENUINAMENTE nuevo, más adelante, sí vuelva a ver el saludo
    # completo — igual que ya pasa hoy para el camino de intención clara.
    _saludo_mostrado: set = field(default_factory=set)
    # Recado 050 — ventana de gracia de UN turno: patient_reference ->
    # activity_id de la Activity que se acaba de cerrar en
    # `_cerrar_si_definitivo` (reserva confirmada, reprogramada o
    # declinada). El SIGUIENTE mensaje de ese paciente se reevalúa
    # contra el detector centralizado de interrupciones de contexto
    # (`HealthBrain._detectar_interrupcion_de_contexto`, recado 047)
    # ANTES de tratarse como una solicitud 100% nueva — ver
    # `_evaluar_ventana_de_gracia`. Se consume (se hace `pop`) en esa
    # misma evaluación, coincida o no con ninguna interrupción: nunca
    # dura más de un turno, sin necesidad de tiempo real ni TTL (mismo
    # criterio "más simple posible" que el resto de los flags de este
    # dataclass, ej. `_saludo_mostrado`).
    _recien_cerrada: Dict[str, str] = field(default_factory=dict)
    # Recado 056, Punto 3 — patient_reference -> (momento real del
    # cierre, nombre conocido del paciente o None). A diferencia de
    # `_recien_cerrada` (arriba, ventana de UN turno, siempre se
    # consume), esta SÍ necesita tiempo real (`_VENTANA_SALUDO_CORTO`)
    # porque cubre un caso distinto: no "¿este mensaje es sobre lo que
    # se acaba de cerrar?" (ya resuelto por la ventana de gracia), sino
    # "¿ya lo saludé hace un momento?" — se consulta (nunca se hace
    # `pop`) cada vez que se necesita decidir el saludo; expira sola por
    # tiempo, no por uso.
    _cierre_reciente: Dict[str, "tuple[datetime, Optional[str]]"] = field(default_factory=dict)


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
    """`service` YA NO tiene un default hardcodeado aquí (recado 030 —
    antes era "medicina general" a ciegas, causa raíz de los recados 027
    y 030): cada llamador decide explícitamente qué `service` pasar —
    `_resolver_gestion_de_cita_existente` ya pasaba el real de la cita
    existente (`cita.service`, sin cambios); `_resolver_programar_cita`
    ahora decide el suyo vía `_determinar_servicio_inicial`. Sin
    override, `Activity.service` queda en su default real (`None`) —
    nunca una adivinanza."""
    datos = {
        "activity_id": f"SYN-{uuid.uuid4().hex[:10]}",
        "source_system": "PATIENT_INITIATED",
        "activity_type": "ACCESO_PACIENTE",
        "objective": objective,
        "patient_reference": patient_reference,
        "patient_contact": {},
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
        _procesar_olvido_si_corresponde(gateway, patient_reference, contexto_existente)
        _cerrar_si_definitivo(gateway, patient_reference, contexto_existente)
        return respuesta

    # Ventana de gracia de un turno (recado 050, corrige el hallazgo del
    # recado 049): NO hay conversación abierta — puede ser porque nunca
    # existió, o porque una Activity de este paciente ACABA de cerrarse
    # en el turno anterior (`_cerrar_si_definitivo`). En ese segundo
    # caso, antes de tratar este mensaje como una solicitud 100% nueva,
    # se reevalúa contra las 5 categorías de interrupción de contexto
    # del recado 047. Se consume en la misma llamada (nunca dura más de
    # este turno) y no interfiere con el gate de identidad de abajo: si
    # el paciente ya tenía identidad resuelta (la tenía, si llegó a
    # cerrar una conversación), sigue resuelta igual.
    respuesta_ventana_de_gracia = _evaluar_ventana_de_gracia(gateway, patient_reference, message_id, text)
    if respuesta_ventana_de_gracia is not None:
        return respuesta_ventana_de_gracia

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
    # fila VERIFICADO y VIGENTE en `identity_store` (persistente —
    # sobrevive a un reinicio del proceso, a diferencia de
    # `_identidad_resuelta`, que es solo caché en memoria de ESTE
    # proceso), se puebla directamente ANTES del gate de abajo — nunca
    # se vuelve a pedir documento ni código. Mismo duck-typing que el
    # resto del gate: solo aplica cuando el AppointmentService activo
    # distingue identificador de canal de documento real.
    #
    # `registro.vigente()` (recado 016, extensión de R-20): además de
    # VERIFICADO, exige que `verificado_en` esté dentro de
    # `RETENCION_IDENTIDAD_DIAS` (180) — una fila vencida se trata como
    # si no existiera, SIN ningún mensaje especial ("tu identidad
    # venció"): simplemente no se hidrata, y el gate de abajo dispara el
    # wizard completo de nuevo, exactamente igual que un teléfono nuevo
    # (requisito #1.2, deliberadamente sin UX dedicada para este caso).
    nombre_para_saludo = None
    if patient_reference not in gateway._identidad_resuelta and _requiere_identidad_real(gateway):
        registro = gateway.identity_store.get(patient_reference)
        if registro is not None and registro.vigente():
            gateway._identidad_resuelta[patient_reference] = registro.documento
            # Recado 034, pedido explícito: un paciente reconocido
            # automáticamente (fila ya VERIFICADA y vigente de una
            # conversación anterior — nunca repite el wizard) debe
            # escuchar su nombre en el saludo, no solo quedar
            # identificado en silencio. Se calcula acá, ANTES de
            # enrutar el mensaje, y se antepone al resultado abajo —
            # nunca se repite en turnos siguientes de la MISMA
            # conversación, porque `patient_reference` ya queda en
            # `_identidad_resuelta` (esta rama no se vuelve a alcanzar).
            nombre_para_saludo = registro.nombre

    if (
        channel in _CANALES_SIN_IDENTIFICADOR_DOCUMENTO
        and _requiere_identidad_real(gateway)
        and patient_reference not in gateway._identidad_resuelta
    ):
        # Recado 046: el saludo institucional (con el menú numerado) se
        # antepone SOLO en el primer mensaje real de la conversación —
        # `_pending_identity` todavía no tiene entrada para este
        # `patient_reference` en ese momento exacto (se crea DENTRO de
        # `_gestionar_identificacion`). En los turnos siguientes del
        # mismo wizard (reintentos de documento, código) ya existe la
        # entrada, así que el saludo no se repite. DISEÑO NO BLOQUEANTE
        # (decisión explícita tras encontrar que la versión bloqueante
        # rompía 84 tests — ver recado 046): el menú es una guía visible
        # que se antepone, nunca una pregunta que hace esperar al
        # paciente antes de seguir con el wizard de documento.
        es_primer_mensaje_del_wizard = patient_reference not in gateway._pending_identity
        respuesta_identificacion = _gestionar_identificacion(gateway, patient_reference, channel, text)
        if es_primer_mensaje_del_wizard:
            return f"{_saludo_primer_contacto(None)} {respuesta_identificacion}"
        return respuesta_identificacion

    # Recado 048 — hallazgo real de producción: un mensaje SIN ninguna
    # intención reconocible (ej. "hola") no debe crear ninguna
    # PatientRequest/Activity ni avanzar ningún flujo — el turno debe
    # terminar mostrando SOLO el saludo institucional + menú, en espera
    # de que el paciente responda al menú. `_enrutar_solicitud_nueva`
    # ahora devuelve `None` en ese caso exacto (ver docstring abajo).
    saludo_ya_mostrado = patient_reference in gateway._saludo_mostrado
    gateway._saludo_mostrado.add(patient_reference)
    respuesta = _enrutar_solicitud_nueva(gateway, patient_reference, channel, message_id, text)

    # Recado 056, Punto 3 — si este paciente cerró una interacción hace
    # POCO tiempo (`_VENTANA_SALUDO_CORTO`), el saludo de apertura de
    # este ciclo nuevo es CORTO (sin presentación institucional ni menú
    # extenso) en vez del guion completo de siempre — ya lo vio hace un
    # momento. Nombre: preferir el ya resuelto por identidad real
    # (`nombre_para_saludo`); si no hay (canal sin gate de identidad,
    # ej. "demo"), usar el que quedó guardado al cerrar la Activity
    # anterior.
    cierre = gateway._cierre_reciente.get(patient_reference)
    saludo_corto_aplica = cierre is not None and (datetime.now(timezone.utc) - cierre[0]) < _VENTANA_SALUDO_CORTO
    if saludo_corto_aplica:
        nombre_efectivo = nombre_para_saludo or cierre[1]
        saludo_apertura = _saludo_corto_de_regreso(nombre_efectivo)
    else:
        saludo_apertura = _saludo_primer_contacto(nombre_para_saludo)

    if respuesta is None:
        # Ninguna intención reconocible en este mensaje — nada se creó.
        # Recado 046: guion completo (o corto, ver arriba) SOLO la
        # primera vez; turnos ambiguos siguientes (`saludo_ya_mostrado`)
        # reciben un recordatorio corto del menú, nunca la presentación
        # de nuevo.
        return _MENSAJE_INTENCION_NO_RECONOCIDA if saludo_ya_mostrado else saludo_apertura

    if saludo_ya_mostrado:
        # Ya se le mostró el saludo en un turno ambiguo anterior de esta
        # misma "pre-conversación" (sin contexto todavía) — no se repite.
        return respuesta

    # Recado 046: guion de apertura (completo, o corto tras un cierre
    # reciente — recado 056) antepuesto al primer turno real —
    # personalizado para un paciente reconocido automáticamente,
    # genérico para uno nuevo en un canal sin gate de identidad. Mismo
    # criterio de "solo en el primer turno" que ya tenía el saludo
    # anterior — este punto solo se alcanza cuando no hay conversación
    # abierta todavía.
    return f"{saludo_apertura} {respuesta}"


def _enrutar_solicitud_nueva(
    gateway: "HealthGateway", patient_reference: str, channel: str, message_id: str, text: str
) -> Optional[str]:
    """Clasifica y resuelve un mensaje SIN conversación previa abierta —
    extraído de `handle_inbound_message` (recado 034) para poder
    anteponerle un saludo con nombre cuando corresponde, sin repetir
    esta lógica de enrutamiento en cada rama.

    Recado 048: devuelve `None` (en vez de defaultear a PROGRAMAR_CITA)
    cuando el mensaje no contiene NINGUNA intención reconocible —
    `classify_intent_or_none` (a diferencia de `classify_intent`, que
    sigue existiendo tal cual para todo lo demás) permite distinguir
    ese caso. Antes, un mensaje ambiguo como "hola" caía al fallback de
    `classify_intent` (PROGRAMAR_CITA) y disparaba de inmediato el
    flujo completo de reserva (creaba Activity, preguntaba servicio) en
    el MISMO turno que el saludo — hallazgo real de producción.

    Recado 046 (diseño NO bloqueante, ver docstring del módulo/recado):
    `_interpretar_opcion_menu` se prueba PRIMERO — reconoce el ordinal
    exacto ("1"-"4") o la palabra sola de una opción del menú
    ("reservar", "cancelar", etc.), casos que `classify_intent` NUNCA
    reconocía por sí solo (exige frases más largas como "cancelar mi
    cita") y siempre defaulteaba a `PROGRAMAR_CITA` sin importar cuál
    número/palabra bare haya escrito el paciente. Estrictamente una
    MEJORA de precisión, nunca una regresión: solo agrega
    interpretaciones nuevas para mensajes que antes caían al default
    incorrecto, no cambia ninguna clasificación que ya funcionaba."""
    intent = _interpretar_opcion_menu(text) or classify_intent_or_none(text)
    if intent is None:
        return None
    return _resolver_por_intent(gateway, patient_reference, channel, message_id, text, intent)


def _resolver_por_intent(
    gateway: "HealthGateway", patient_reference: str, channel: str, message_id: str, text: str,
    intent: RequestIntent,
) -> str:
    """Dispatch por `RequestIntent` YA CONOCIDO — extraído de
    `_enrutar_solicitud_nueva` (recado 046) para no duplicar la lista de
    ramas en dos lugares."""
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
        return _resolver_consulta_catalogo(gateway, request, channel)

    if intent in (RequestIntent.REPROGRAMAR_CITA, RequestIntent.CANCELAR_CITA):
        return _resolver_gestion_de_cita_existente(gateway, request, channel, message_id, text)

    # PROGRAMAR_CITA / DEMANDA_INDUCIDA (inbound): reutiliza el mismo
    # flujo de aceptación -> disponibilidad -> reserva ya construido en
    # HealthBrain (sección "esperando_decision"), sin duplicarlo.
    return _resolver_programar_cita(gateway, request, channel, message_id, text)




def _determinar_servicio_inicial(gateway: "HealthGateway"):
    """Decide el `service` inicial de una Activity sintética de
    PROGRAMAR_CITA (recado 030): `intent.py` no extrae ningún servicio
    del texto libre del paciente (fuera de alcance, ver recado 027), así
    que este punto NUNCA sabe de verdad qué servicio quiere — asumir
    "medicina general" a ciegas fue la causa raíz de dos bugs reales de
    producción (recados 027 y 030: el paciente terminaba viendo "sin
    disponibilidad" para un servicio que nunca pidió). Con el catálogo
    real teniendo MÁS DE UNO, no se asume ninguno — se devuelve el
    mensaje para preguntar primero (`(None, mensaje)`). Con 0 o 1
    servicio real no hay nada que desambiguar, así que se sigue sin
    preguntar (`(servicio, None)`) — mismo comportamiento de siempre
    para `MockAppointmentService`, que solo tiene uno.

    Duck-typed (`list_services`, mismo criterio que `buscar_paciente`):
    un `AppointmentService` que no lo implemente cae al fallback
    histórico "medicina general", nunca falla."""
    listar = getattr(gateway.appointment_service, "list_services", None)
    servicios = listar() if listar else []
    if len(servicios) == 1:
        return servicios[0], None
    if not servicios:
        return "medicina general", None
    lista_servicios = _lista_numerada(servicios)
    mensaje = f"Antes de seguir, ¿para cuál servicio te gustaría agendar?\n{lista_servicios}"
    return None, mensaje


def _resolver_programar_cita(gateway: HealthGateway, request: PatientRequest, channel: str, message_id: str, text: str) -> str:
    servicio_inicial, mensaje_preguntar_servicio = _determinar_servicio_inicial(gateway)
    nombre = _nombre_conocido(gateway, request.patient_reference)
    activity = _nueva_activity_sintetica(
        _documento_resuelto(gateway, request.patient_reference), channel,
        objective="Solicitud del paciente: programar cita",
        service=servicio_inicial,
        patient_contact={"nombre": nombre} if nombre else {},
    )
    activity = gateway.activity_source.create(activity)
    context = build_health_agent_context(
        activity, gateway.activity_source, gateway.appointment_service,
        gateway.reminder_manager, gateway.result_sink,
    )
    _sembrar_conversacion_inbound(context)
    register_context(gateway, request.patient_reference, context)
    gateway.patient_request_source.update(request.model_copy(update={"status": RequestStatus.EN_PROCESO}))

    if mensaje_preguntar_servicio is not None:
        # Catálogo real con más de un servicio (recado 030): nunca se
        # asume cuál quiere el paciente — se pregunta ANTES de mirar
        # disponibilidad de algo que nunca confirmó. `etapa` se escribe
        # directo (mismo patrón que `_sembrar_conversacion_inbound`):
        # todavía no hay ninguna respuesta del paciente que interpretar
        # en este primer turno, así que no hace falta pasar por
        # `HealthBrain.interpret()` para componerlo.
        estado = context.orchestrator.store.get(context.activity.activity_id)
        nuevos_datos = {**estado.datos_recopilados, "etapa": "esperando_servicio"}
        context.orchestrator.store.save(
            estado.model_copy(update={"datos_recopilados": nuevos_datos}), expected_version=estado.version
        )
        return mensaje_preguntar_servicio

    # HealthBrain (sin tocar) espera una señal de aceptación explícita
    # para pasar a ofrecer disponibilidad (ver brain.py:_ACEPTA). Como
    # este gateway YA CLASIFICÓ la intención como "programar", se
    # traduce a la frase canónica que ese flujo ya reconoce — no se
    # duplica la lógica de reserva, solo se elige qué primer mensaje
    # alimentarle al mismo Brain.
    respuesta = handle_patient_message(context, message_id, "sí")
    if _cerrar_si_definitivo(gateway, request.patient_reference, context):
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

    nombre = _nombre_conocido(gateway, request.patient_reference)
    activity = _nueva_activity_sintetica(
        _documento_resuelto(gateway, request.patient_reference), channel,
        objective="Solicitud del paciente: gestionar cita existente",
        appointment_id=cita.appointment_id,
        service=cita.service,
        patient_contact={"nombre": nombre} if nombre else {},
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
    if _cerrar_si_definitivo(gateway, request.patient_reference, context):
        gateway.patient_request_source.update(request.model_copy(update={"status": RequestStatus.RESUELTA}))
    return respuesta


def _procesar_olvido_si_corresponde(gateway: HealthGateway, patient_reference: str, context: HealthAgentContext) -> None:
    """Ejecuta el borrado REAL de `identidad_canal` cuando `HealthBrain`
    detectó Y confirmó la solicitud del paciente de olvidar su identidad
    de canal (recado 016, extensión de R-20 — requisito de
    `.claude/rules/proteccion-datos-personales.md`: "el usuario final
    tiene siempre disponible... la forma de... pedir su eliminación").

    Vive en `gateway.py`, no en `agent.py`, porque `identity_store` es un
    servicio de `HealthGateway` (compartido por el proceso), no de
    `HealthAgentContext` (por Activity) — mismo criterio que la
    hidratación de identidad al inicio de `handle_inbound_message`.
    `HealthBrain` (`brain.py:_iniciar_olvido`/`_interpretar_confirmacion_olvido`)
    solo PROPONE el cambio de etapa a `"olvido_confirmado"` — nunca borra
    nada directamente (mismo principio de autoridad de todo el proyecto:
    el Brain propone, esta capa decide/ejecuta).

    Deliberadamente independiente del mecanismo de beneficiario (013,
    requisito #5): no toca `datos["beneficiario_documento"]` ni ninguna
    de sus etapas, y no se dispara desde el camino Activity (outbound)
    puro — solo desde una conversación que YA pasa por
    `handle_patient_message` vía este archivo (ver el único call site,
    en la rama `contexto_existente` de `handle_inbound_message`)."""
    estado = context.orchestrator.store.get(context.activity.activity_id)
    if estado is None or estado.datos_recopilados.get("etapa") != "olvido_confirmado":
        return

    documento_eliminado = gateway._identidad_resuelta.pop(patient_reference, None)
    gateway.identity_store.eliminar(patient_reference)
    gateway._pending_identity.pop(patient_reference, None)

    context.orchestrator.events.record(
        context.activity.activity_id, EventType.STATE_TRANSITION,
        evento="IDENTIDAD_ELIMINADA_A_PEDIDO",
        telefono=patient_reference,
        documento=documento_eliminado,
    )

    # Consume la etapa "de un solo disparo" (mismo criterio que
    # _ETAPAS_DE_UN_DISPARO en agent.py, aunque esta no está atada a un
    # resultado de tool): sin esto, un mensaje futuro del paciente en la
    # MISMA conversación volvería a intentar borrar (ya nada que borrar,
    # pero seguiría registrando el evento de nuevo, sin sentido). Vuelve
    # a "esperando_decision" — el paciente puede seguir la conversación
    # con normalidad, solo que su identidad de canal ya no es confiable.
    nuevos_datos = dict(estado.datos_recopilados)
    nuevos_datos["etapa"] = "esperando_decision"
    context.orchestrator.store.save(
        estado.model_copy(update={"datos_recopilados": nuevos_datos}), expected_version=estado.version
    )


def _cerrar_si_definitivo(gateway: HealthGateway, patient_reference: str, context: HealthAgentContext) -> bool:
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
    tocarla.

    `patient_reference` (recado 050, parámetro NUEVO, antes se usaba
    `context.activity.patient_reference` directo): con el gate de
    identidad activo (012/R-15, canales cuyo identificador NO es el
    documento — ej. WhatsApp), `context.activity.patient_reference` es
    el DOCUMENTO ya resuelto, distinto del identificador de CANAL con el
    que `_open_conversations`/`_saludo_mostrado`/`_recien_cerrada` están
    indexados en cualquier otro punto de este archivo (`register_context`
    los indexa explícitamente por el `patient_reference` de canal que le
    pasa el llamador). Usar `context.activity.patient_reference` acá
    hacía que estos `pop`/`discard` fueran, en ese escenario, un no-op
    silencioso (`find_open_context` igual se autocorregía en la
    siguiente consulta) — inofensivo hasta ahora, pero la ventana de
    gracia nueva (`_recien_cerrada`, abajo) si necesita la clave
    correcta para que `_evaluar_ventana_de_gracia` la encuentre."""
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
        gateway._open_conversations.pop(patient_reference, None)
        # Recado 048: libera también la marca de "saludo ya mostrado" —
        # un ciclo de conversación GENUINAMENTE nuevo, más adelante,
        # debe volver a ver el saludo institucional completo, igual que
        # ya pasaba para el camino de intención clara (arriba).
        gateway._saludo_mostrado.discard(patient_reference)
        # Recado 050 — ventana de gracia: registra esta Activity como
        # "recién cerrada" para que el PRÓXIMO mensaje de este mismo
        # paciente se reevalúe contra las 5 categorías de interrupción
        # de contexto antes de tratarse como una solicitud nueva (ver
        # `_evaluar_ventana_de_gracia`). Deliberadamente NO se hace
        # `gateway._contexts.pop(...)` acá — a diferencia de
        # `_open_conversations`, el contexto sigue vivo en `_contexts`
        # (ya lo estaba antes de este recado, sin cambios) precisamente
        # para que la ventana de gracia pueda recuperarlo.
        gateway._recien_cerrada[patient_reference] = context.activity.activity_id
        # Recado 056, Punto 3 — registra el momento real del cierre (hora
        # real, no simulada) + el nombre conocido de la Activity que se
        # acaba de cerrar, para que un regreso poco después reciba un
        # saludo corto en vez de la presentación institucional completa.
        nombre_conocido = (context.activity.patient_contact or {}).get("nombre")
        gateway._cierre_reciente[patient_reference] = (datetime.now(timezone.utc), nombre_conocido)
        return True
    return False


def _evaluar_ventana_de_gracia(
    gateway: HealthGateway, patient_reference: str, message_id: str, text: str
) -> Optional[str]:
    """Recado 050 — hallazgo real de producción (recado 049): apenas
    `_cerrar_si_definitivo` cierra una Activity, el siguiente mensaje
    del paciente ya no encuentra `find_open_context` y se enruta por
    `_enrutar_solicitud_nueva`, que NUNCA conoce el detector de las 5
    categorías de interrupción de contexto (`_PARA_OTRO`,
    `_INFO_NO_AUTORIZADA`, `_HUMANO`, `_NO_PUEDE_AHORA`, `_PIDE_INFO`,
    recado 047) — vive únicamente dentro de `HealthBrain.interpret()`,
    solo alcanzable con una conversación abierta. Esta función
    reevalúa ESE MISMO detector (reutilizado tal cual vía
    `Orchestrator.brain`, nunca duplicado) sobre la Activity que se
    acaba de cerrar, UNA sola vez (`pop`, nunca dura más de este turno).

    Devuelve `None` si no aplica ventana de gracia, o si el mensaje NO
    coincide con ninguna de las 5 categorías — en ambos casos el
    llamador (`handle_inbound_message`) sigue con el enrutamiento
    normal de una solicitud nueva, SIN NINGÚN cambio de comportamiento
    (requisito explícito: una solicitud genuinamente nueva nunca se ve
    afectada). Si SÍ coincide, devuelve la respuesta ya lista — este
    turno termina ahí, sin crear ninguna Activity/PatientRequest nueva.

    No reabre `_open_conversations`: el detector de estas 5 categorías
    nunca propone `tool_requerida` (confirmado leyendo
    `_detectar_interrupcion_de_contexto` — ninguna de sus 5 ramas
    escribe contra `AppointmentService`), así que no hace falta
    volver a ejecutar la maquinaria completa de `handle_patient_message`
    (tools, recordatorios, etc.) — alcanza con actualizar el estado
    guardado y devolver la respuesta, igual de real que si hubiera
    pasado por el camino completo."""
    activity_id = gateway._recien_cerrada.pop(patient_reference, None)
    if activity_id is None:
        return None
    contexto_cerrado = gateway._contexts.get(activity_id)
    if contexto_cerrado is None or contexto_cerrado.orchestrator is None:
        return None
    estado = contexto_cerrado.orchestrator.store.get(activity_id)
    if estado is None:
        return None

    from .brain import _ETAPAS_SIN_INTERRUPCION_DE_CONTEXTO

    datos = dict(estado.datos_recopilados)
    etapa = datos.get("etapa", "esperando_decision")
    if etapa in _ETAPAS_SIN_INTERRUPCION_DE_CONTEXTO:
        return None

    texto = text.lower().strip()
    interrupcion = contexto_cerrado.orchestrator.brain._detectar_interrupcion_de_contexto(  # noqa: SLF001 — mismo paquete, ver docstring
        texto, datos, etapa
    )
    if interrupcion is None:
        return None

    senales = interrupcion.senales_detectadas or []
    texto_tiene_intencion_de_cita_nueva = any(k in texto for k in _PALABRAS_PROGRAMAR_CITA)
    if (
        "gestion_para_beneficiario_declarada" in senales
        and contexto_cerrado.activity.appointment_id is not None
        and not texto_tiene_intencion_de_cita_nueva
    ):
        # Recado 050, decisión de diseño explícita (pedida por el
        # usuario, no improvisada — ver recado 050 para el análisis
        # completo): distingue dos situaciones que el detector del
        # Brain, por sí solo, no puede diferenciar (no tiene forma de
        # saber si "para mi hija" es sobre una cita NUEVA o sobre la que
        # se ACABA de reservar en esta misma Activity).
        #
        # Chequeo DIRECTO contra `intent.py:_PROGRAMAR` (las frases
        # explícitas: "programar", "agendar", "necesito una cita", etc.)
        # — DELIBERADAMENTE no se usa `classify_intent_or_none(text)`
        # para esto: esa función solo devuelve `None` para un saludo
        # PURO (recado 048); para cualquier otro texto sin ninguna
        # palabra clave específica, sigue defaulteando a
        # `PROGRAMAR_CITA` igual (recado 030, "el punto de entrada más
        # seguro") — con ese default, AMBOS mensajes de ejemplo abajo
        # clasificarían como PROGRAMAR_CITA, sin distinguir nada.
        #
        # - "dale gracias, necesito una cita para mi hija" (caso real
        #   del recado 049, punto 1): SÍ contiene una frase explícita de
        #   `_PROGRAMAR` ("necesito una cita") además de mencionar
        #   beneficiario — es una solicitud nueva, separada de lo que se
        #   acaba de cerrar. Acá NO se aplica este `if`, la respuesta
        #   normal del Brain (wizard de beneficiario) sigue de largo,
        #   sin cambios.
        # - "pero es para mi hija y no me preguntaste su documento"
        #   (caso real del recado 049, punto 3): NO contiene ninguna
        #   frase de `_PROGRAMAR` — es una corrección/reclamo sobre la
        #   reserva que la Activity recién cerrada ya ejecutó de verdad
        #   contra hrmm-backend (`appointment_id` real).
        #
        # Para el segundo caso, arrancar el wizard normal de beneficiario
        # reservaría una SEGUNDA cita sin cancelar la primera —
        # quedarían dos citas, una a nombre equivocado y libre, peor que
        # el bug original. Tampoco se reasigna `documento_paciente` de
        # la cita ya creada en silencio: no existe ningún endpoint de
        # hrmm-backend para eso. Y con `HrmmAppointmentService` real,
        # cancelar SIEMPRE exige el código de verificación —
        # `HealthBrain._cancelar` ya documenta que ese camino es
        # inalcanzable con un servicio real; el paciente real cancela
        # exclusivamente por `_procesar_intento_de_codigo`, más abajo en
        # este archivo. Escribir contra producción sin pasar por esa
        # verificación saltaría la misma protección que ya existe para
        # cualquier otra cancelación real.
        #
        # Por eso, en este caso, se DESCARTA la respuesta del Brain
        # (que habría arrancado el wizard) y se sustituye por un mensaje
        # que informa con claridad y remite al mismo camino de
        # cancelación ya existente y ya protegido (la frase exacta
        # "cancelar la cita", reconocida tanto por `HealthBrain._CANCELAR`
        # como por `intent.py:RequestIntent.CANCELAR_CITA`) — nunca se
        # ejecuta ni se propone ninguna escritura nueva acá. `etapa`
        # queda en "finalizada": es una respuesta de un solo turno, no
        # abre ningún wizard.
        nuevos_datos = {**datos, "etapa": "finalizada"}
        respuesta = (
            "Entiendo — la cita que se acabó de confirmar quedó reservada a tu nombre, no al de "
            "la persona para quien es. Para corregirlo hay que cancelar esa cita y reservar una "
            "nueva a nombre de la persona correcta; por seguridad, cancelar requiere el mismo "
            "código de verificación que te pedimos siempre. Si quieres, dime \"cancelar la cita\" "
            "y seguimos con eso."
        )
        estado_actualizado = estado.model_copy(update={"datos_recopilados": nuevos_datos})
        contexto_cerrado.orchestrator.store.save(estado_actualizado, expected_version=estado.version)
        contexto_cerrado.orchestrator.events.record(
            activity_id, EventType.STATE_TRANSITION,
            evento="BENEFICIARIO_DECLARADO_TRAS_RESERVA_YA_EJECUTADA",
        )
        return respuesta

    actualizacion = interrupcion.propuesta_de_actualizacion_de_estado or {}
    nuevos_datos = actualizacion.get("datos_recopilados", datos)
    reabre_wizard_de_beneficiario = nuevos_datos.get("etapa") == "esperando_documento_beneficiario"
    cambios_estado: Dict[str, Any] = {"datos_recopilados": nuevos_datos}
    if reabre_wizard_de_beneficiario:
        # `estado.fase_actual` sigue en `FaseActual.CIERRE` (así quedó
        # al cerrarse la Activity) — sin corregirlo acá, el turno
        # SIGUIENTE (el documento del beneficiario, procesado por el
        # camino normal `handle_patient_message` -> `Orchestrator.
        # handle_message`) encontraría `fase_actual == CIERRE` y
        # `_reabrir_ciclo` (core/orchestrator.py) BORRARÍA por completo
        # `datos_recopilados` de vuelta a `{}` antes de que
        # `HealthBrain.interpret()` llegue a verlo — perdiendo el
        # "esperando_documento_beneficiario"/`etapa_antes_de_beneficiario`
        # que se acaba de guardar acá (encontrado probando este mismo
        # caso, no supuesto). `RECOPILACION_DE_DATOS` es la fase real en
        # la que ya vive cualquier etapa "esperando_X" en curso — no una
        # fase inventada para este caso.
        cambios_estado["fase_actual"] = FaseActual.RECOPILACION_DE_DATOS
    estado_actualizado = estado.model_copy(update=cambios_estado)
    contexto_cerrado.orchestrator.store.save(estado_actualizado, expected_version=estado.version)
    # Nota: deliberadamente NO se toca `orchestrator.memory` acá —
    # `Orchestrator` no expone un accesor de solo lectura para ella
    # (a diferencia de `store`/`tools`/`events`/`brain`, recado 050) y
    # agregar uno solo para este registro secundario ampliaría el
    # alcance sin necesidad real: ninguna de las 5 categorías de
    # interrupción vuelve a leer `recent_turns`, así que no hace falta
    # para que esta respuesta sea correcta.
    contexto_cerrado.orchestrator.events.record(
        activity_id, EventType.STATE_TRANSITION, evento="INTERRUPCION_EN_VENTANA_DE_GRACIA",
        senales=list(interrupcion.senales_detectadas or []),
    )
    if reabre_wizard_de_beneficiario:
        # Único de las 5 categorías cuya respuesta arranca un wizard de
        # VARIOS turnos (documento -> confirmación -> retomar) — las
        # otras 4 terminan en un desenlace de un solo turno (escalada,
        # finalizada, o sin cambio de etapa). Sin re-registrar acá, el
        # turno SIGUIENTE del paciente (el documento del beneficiario)
        # ya no encontraría conversación abierta (la ventana de gracia
        # ya se consumió arriba, es de un solo uso) y se malinterpretaría
        # como una solicitud nueva. Mismo mecanismo de correlación de
        # siempre (`register_context`), nada nuevo.
        #
        # No alcanza con re-registrar `_open_conversations`/`_contexts`:
        # `find_open_context` ADEMÁS exige que `activity.status` no esté
        # en `_ACTIVITY_ESTADOS_CERRADOS` — `finalize_and_report` ya lo
        # había dejado en `COMPLETED` al cerrar. Sin revertirlo acá, el
        # turno siguiente encontraría la entrada recién re-registrada
        # pero la vería "vieja" de nuevo (mismo camino de autolimpieza
        # que usa `find_open_context` para cualquier Activity realmente
        # abandonada) y la volvería a descartar. `IN_PROGRESS` es el
        # mismo estado que `accept_activity` deja al aceptar cualquier
        # Activity nueva — no es un estado inventado para este caso.
        contexto_cerrado.activity = contexto_cerrado.activity.model_copy(
            update={"status": ActivityStatus.IN_PROGRESS}
        )
        contexto_cerrado.activity_source.update(contexto_cerrado.activity)
        register_context(gateway, patient_reference, contexto_cerrado)
    return interrupcion.respuesta_propuesta


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
        return "Revisé y no tienes ninguna cita activa registrada por este canal por ahora."
    # Recado 054 — mismo formato de lista numerada que
    # `HealthBrain._detectar_interrupcion_de_contexto` (misma categoría
    # "consultar mis citas", alcanzada desde una etapa DISTINTA — primer
    # contacto, sin conversación abierta todavía — pero debe verse
    # idéntica al paciente sin importar por cuál camino llegó).
    plural = len(citas) != 1
    intro = (
        f"Aquí tienes tu{'s' if plural else ''} {len(citas)} "
        f"cita{'s' if plural else ''} activa{'s' if plural else ''}:"
    )
    lista_citas = _lista_numerada([
        f"{c.service} — {_formatear_fecha_humana(c.date)}, {c.time}, {c.location}" for c in citas
    ])
    return f"{intro}\n{lista_citas}"


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
    "Ese código no es válido o ya venció. Sin problema — puedes escribir uno nuevo, "
    "o pedirme que te reenviemos otro."
)


def _elegir_opcion_ordinal(texto: str, opciones: list) -> Optional[str]:
    """Utilidad mínima y genérica ('1'/'primera' -> índice 0) — no es
    una copia de `HealthBrain._elegir_opcion` (privado, ligado a su
    propia máquina de etapas); aquí no hay ninguna lógica de dominio,
    solo interpretar un ordinal de una lista ya ofrecida.

    Recado 056 — mismo bug real de `HealthBrain._elegir_opcion` (recado
    053, caso Giselle Tornay): un `in` simple sobre "1"/"2"/"3" hacía que
    CUALQUIER texto que contuviera esos dígitos en cualquier posición
    (una hora tipo "7:30", por ejemplo) se malinterpretara como ordinal.
    Encontrado al revisar este archivo buscando el mismo patrón de bug
    en otros lugares — esta copia local nunca se había corregido.
    `\\b...\\b` exige que el dígito sea un token propio."""
    texto = texto.lower()
    mapa = {"1": 0, "primera": 0, "2": 1, "segunda": 1, "3": 2, "tercera": 2}
    for clave, indice in mapa.items():
        if re.search(rf"\b{re.escape(clave)}\b", texto) and indice < len(opciones):
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
        # Recado 056 — mismo fix de `HealthBrain._ofrecer_horarios`:
        # ordena antes de recortar a 3, nunca depende del orden de
        # `get_availability`.
        opciones = sorted(
            gateway.appointment_service.get_availability(cita.service), key=lambda o: (o.date, o.time)
        )[:3]
        if not opciones:
            # NUNCA "te contactamos" (recado 027, hallazgo real — mismo
            # patrón que recado 026, pero esta rama es TODAVÍA más
            # delicada: este sub-flujo de verificación por código vive
            # completo en este archivo, fuera del Orchestrator/Core, así
            # que `NoPrometerContactoGuardrail` nunca llega a verla —
            # esta frase se le habría enviado al paciente TAL CUAL, sin
            # ninguna red de seguridad).
            gateway.patient_request_source.update(request.model_copy(update={"status": RequestStatus.RESUELTA}))
            return (
                "Lamento decirte que por ahora no tengo otros horarios disponibles para reprogramar. "
                "Escríbeme más tarde y lo revisamos de nuevo con gusto."
            )
        gateway._pending_verifications[request.patient_reference] = {
            "action": accion,
            "appointment_id": cita.appointment_id,
            "documento_paciente": documento,
            "stage": "esperando_seleccion",
            "opciones_slot_id": [o.slot_id for o in opciones],
            "request_id": request.request_id,
            "service": cita.service,
        }
        lista_opciones = _lista_numerada(
            [f"{_formatear_fecha_humana(o.date)}, {o.time}, {o.location}" for o in opciones]
        )
        return f"Aquí tienes otras opciones:\n{lista_opciones}\n¿Cuál prefieres?"

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
    return f"Listo, te enviamos un código{pista} para confirmar. Escríbelo aquí para continuar cuando lo tengas."


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

    # Nombre real (recado 034) y correo de confirmación (recado 035,
    # misma frase que `agent.py` — hrmm-backend ya lo envía de forma
    # NATIVA al ejecutar el POST real de cancelar/reprogramar, ZANTIA
    # nunca lo duplica).
    nombre = _nombre_conocido(gateway, patient_reference)
    saludo_nombre = f", {nombre}" if nombre else ""
    if pendiente["action"] == "cancelar":
        return f"Listo{saludo_nombre}, tu cita quedó cancelada. Te enviamos un correo de confirmación con todos los detalles."
    return (
        f"Listo{saludo_nombre}, tu cita quedó reprogramada: {cita_resultado.service} el {cita_resultado.date} "
        f"a las {cita_resultado.time} en {cita_resultado.location}. Te enviamos un correo de confirmación con todos los detalles."
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
    "¡Hola! Antes de seguir, ¿me confirmas tu número de documento de identidad? "
    "Lo necesito para consultar tus datos con seguridad."
)
_MENSAJE_IDENTIDAD_CONFIRMADA = (
    "¡Gracias! Ya confirmé tu identidad. ¿En qué te puedo ayudar hoy? "
    "Puedo programar, reprogramar, cancelar o consultar tus citas."
)
_MENSAJE_DOCUMENTO_NO_ENCONTRADO = (
    "No encontré ningún paciente registrado con ese documento — "
    "¿puedes revisarlo y escribírmelo de nuevo?"
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


def _nombre_conocido(gateway: "HealthGateway", patient_reference: str) -> Optional[str]:
    """Nombre real ya persistido en `identity_store` (recado 034) para
    este identificador de canal — `None` si nunca se verificó por este
    mecanismo (MockAppointmentService, o un paciente todavía sin
    identidad resuelta). Se usa para poblar `Activity.patient_contact`
    al crear una Activity sintética, así `HealthBrain`/`agent.py` pueden
    referenciarlo (confirmar una reserva, despedirse) sin volver a
    consultar `buscar_paciente`."""
    registro = gateway.identity_store.get(patient_reference)
    return registro.nombre if registro is not None else None


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
        # Recado 034: el nombre real ya viene en la respuesta de
        # buscar-paciente — se lleva hasta `marcar_verificado` para
        # persistirlo UNA SOLA VEZ (nunca se vuelve a pedir a
        # hrmm-backend solo para saludar).
        nombre = identidad.get("nombre_paciente")
        return _iniciar_verificacion_de_identidad(gateway, patient_reference, documento, nombre)

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


def _iniciar_verificacion_de_identidad(
    gateway: HealthGateway, patient_reference: str, documento: str, nombre: Optional[str] = None
) -> str:
    """Documento confirmado contra buscar-paciente — antes de asociarlo
    como confiable (recado 014, requisito #2c), se exige un segundo
    factor: código de 6 dígitos al correo del paciente (mismo mecanismo
    ya construido en 009 para cancelar/reprogramar,
    `send_verification_code` — sin inventar uno nuevo). Se registra la
    fila PENDIENTE_VERIFICACION en `identity_store` desde ya (requisito
    #1: la tabla debe reflejar el estado intermedio, no solo el final).
    `nombre` (recado 034) viaja en `_pending_identity` hasta el paso
    final (`_procesar_codigo_de_identificacion`), donde recién se
    persiste — nunca antes de que la identidad quede VERIFICADA de
    verdad."""
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
        "nombre_candidato": nombre,
    }
    correo_parcial = resultado_envio.get("correo_parcial")
    pista = f" a tu correo ({correo_parcial})" if correo_parcial else " a tu correo"
    return f"Listo, te enviamos un código{pista} para confirmar tu identidad. Escríbelo aquí cuando lo tengas."


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

    nombre = pendiente.get("nombre_candidato")
    del gateway._pending_identity[patient_reference]
    gateway.identity_store.marcar_verificado(patient_reference, documento, nombre)
    gateway._identidad_resuelta[patient_reference] = documento
    if nombre:
        return f"¡Gracias, {nombre}! Ya confirmé tu identidad. ¿En qué te puedo ayudar hoy? Puedo programar, reprogramar, cancelar o consultar tus citas."
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
