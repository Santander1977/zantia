"""
Entidades del dominio de salud — demanda inducida y gestión de citas.

Decisión documentada explícitamente (prompt 007, sección 6): existen
TRES capas de estado distintas, que NO se mezclan:

1. `ConversationState.fase_actual` (Core, `state/models.py`) — el
   micro-estado de UN turno conversacional (INICIO,
   IDENTIFICACION_DE_INTENCION, ...). No cambia entre este dominio y
   cualquier otro.
2. `Activity.status` (este archivo) — el ciclo de vida GRUESO de la
   unidad de trabajo completa (PENDING -> ACCEPTED -> IN_PROGRESS ->
   COMPLETED / FAILED / CANCELLED / EXPIRED). Puede abarcar múltiples
   conversaciones a lo largo de varios días (contacto inicial +
   recordatorios).
3. `Activity.management_status` (este archivo) — el progreso GRANULAR
   de la gestión dentro de la fase IN_PROGRESS (NOT_CONTACTED ->
   CONTACTING -> ... -> ATTENDED/NO_SHOW/DECLINED/ESCALATED). Es
   específico del dominio salud, vive en la Activity, nunca en el
   ConversationState del Core.

Ninguna de las tres capas se infiere de las otras — cada una se
actualiza explícitamente por la capa de orquestación de dominio
(`domains/health/agent.py`), nunca por el Brain directamente (mismo
principio de autoridad que el Core: 004, sección 8).
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------
# Activity
# ---------------------------------------------------------------------
class ActivityStatus(str, Enum):
    """Ciclo de vida grueso de la Activity (prompt 007, sección 5)."""

    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class ManagementStatus(str, Enum):
    """Progreso granular de la gestión (prompt 007, sección 6) —
    deliberadamente NO es parte de ConversationState."""

    NOT_CONTACTED = "NOT_CONTACTED"
    CONTACTING = "CONTACTING"
    CONTACTED = "CONTACTED"
    ENGAGED = "ENGAGED"
    APPOINTMENT_PENDING = "APPOINTMENT_PENDING"
    APPOINTMENT_CONFIRMED = "APPOINTMENT_CONFIRMED"
    REMINDER_72H = "REMINDER_72H"
    REMINDER_24H = "REMINDER_24H"
    REMINDER_8H = "REMINDER_8H"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"
    RESCHEDULE_REQUESTED = "RESCHEDULE_REQUESTED"
    RESCHEDULED = "RESCHEDULED"
    DECLINED = "DECLINED"
    ESCALATED = "ESCALATED"


class Activity(BaseModel):
    """Unidad de trabajo asignada a ZANTIA por el sistema originador
    (prompt 007, secciones 3-4). Minimización de datos deliberada: solo
    los campos de paciente/contexto estrictamente necesarios para
    ejecutar la gestión — no se almacena información clínica adicional."""

    model_config = {"validate_assignment": True}

    # --- identidad ---
    activity_id: str
    source_system: str
    campaign_id: Optional[str] = None
    correlation_id: Optional[str] = None

    # --- objetivo ---
    activity_type: str = "DEMANDA_INDUCIDA"
    objective: str
    priority: str = "NORMAL"
    start_at: datetime = Field(default_factory=_utcnow)
    expires_at: Optional[datetime] = None

    # --- paciente (referencia + datos ficticios mínimos autorizados) ---
    patient_reference: str
    patient_contact: Dict[str, Any] = Field(default_factory=dict)  # p.ej. {"nombre":..., "telefono":...}

    # --- contexto autorizado (nunca datos clínicos no autorizados) ---
    program: Optional[str] = None
    reason: Optional[str] = None
    service_need: Optional[str] = None
    previous_care_context: Optional[str] = None

    # --- gestión ---
    permitted_channels: List[str] = Field(default_factory=lambda: ["demo"])
    max_attempts: int = 3
    allowed_actions: List[str] = Field(
        default_factory=lambda: ["contact", "inform", "schedule", "reschedule", "cancel"]
    )
    contact_attempts: int = 0

    # --- agenda ---
    appointment_required: bool = True
    service: Optional[str] = None
    specialty: Optional[str] = None
    location_constraints: Optional[Dict[str, Any]] = None
    appointment_id: Optional[str] = None

    # --- control ---
    status: ActivityStatus = ActivityStatus.PENDING
    management_status: ManagementStatus = ManagementStatus.NOT_CONTACTED
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------
# Appointment — ZANTIA solo guarda la REFERENCIA; la agenda real es el
# sistema maestro (prompt 007, secciones 2 y 15).
# ---------------------------------------------------------------------
class AppointmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    RESCHEDULED = "RESCHEDULED"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"


class Appointment(BaseModel):
    appointment_id: str
    patient_reference: str
    service: str
    specialty: Optional[str] = None
    professional: Optional[str] = None
    location: str
    date: str
    time: str
    status: AppointmentStatus = AppointmentStatus.REQUESTED
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    # Recado 054/058 — estado REAL del intento de enviar el correo de
    # confirmación (nunca una promesa a ciegas): `None` = no se intentó
    # (no había ningún correo del paciente disponible en este turno),
    # `True` = hrmm-backend confirmó el envío real, `False` = se
    # intentó y falló (nunca revierte la acción principal ya exitosa —
    # ver `HrmmAppointmentService._intentar_enviar_confirmacion`).
    correo_confirmacion_enviado: Optional[bool] = None


def sufijo_confirmacion_correo(correo_confirmacion_enviado: Optional[bool]) -> str:
    """Recado 054/058 — texto OPCIONAL a concatenar tras confirmar una
    reserva/cancelación/reprogramación exitosa (`agent.py`/`gateway.py`)
    — NUNCA la promesa ciega de antes ("Te enviamos un correo de
    confirmación...", sin haber verificado nada). `None` (nunca se
    intentó — hoy, el caso más común: ZANTIA no captura el correo del
    paciente en ningún punto de la conversación) devuelve cadena VACÍA
    a propósito: omitir el tema es más honesto que forzar una frase
    sobre algo que no ocurrió en absoluto, y no agrega ruido a cada
    confirmación mientras esa capacidad no exista."""
    if correo_confirmacion_enviado is True:
        return " Te enviamos un correo de confirmación con todos los detalles."
    if correo_confirmacion_enviado is False:
        return (
            " Intentamos enviarte un correo de confirmación, pero no pudimos verificar que "
            "llegara — si no te llega, avísame y lo revisamos con el equipo."
        )
    return ""


def respuesta_pregunta_sobre_correo(correo_confirmacion_enviado: Optional[bool]) -> str:
    """Recado 058 — respuesta HONESTA cuando el paciente pregunta
    explícitamente si se envió el correo (a diferencia de
    `sufijo_confirmacion_correo`, aquí SÍ contesta algo en el caso
    `None` — el paciente hizo una pregunta directa, omitir el tema no
    es una opción)."""
    if correo_confirmacion_enviado is True:
        return "Sí — te enviamos la confirmación por correo, deberías tenerla en tu bandeja."
    if correo_confirmacion_enviado is False:
        return (
            "Intentamos enviarte la confirmación por correo, pero no pudimos verificar que llegara. "
            "Si no te llegó, avísame y lo revisamos con el equipo."
        )
    return (
        "Buena pregunta — hoy no tenemos un correo tuyo registrado en este canal, así que no se "
        "envió ninguna confirmación por ese medio."
    )


class AvailabilitySlot(BaseModel):
    """Un turno disponible, devuelto por AppointmentService.get_availability()
    — estructurado, nunca inventado por el Brain (prompt 007, sección 13)."""

    slot_id: str
    service: str
    specialty: Optional[str] = None
    professional: str
    location: str
    date: str
    time: str


# ---------------------------------------------------------------------
# Reminder
# ---------------------------------------------------------------------
class ReminderType(str, Enum):
    REMINDER_72H = "REMINDER_72H"
    REMINDER_24H = "REMINDER_24H"
    REMINDER_8H = "REMINDER_8H"


class ReminderStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    READY = "READY"
    SENT = "SENT"
    RESPONDED = "RESPONDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class Reminder(BaseModel):
    reminder_id: str
    appointment_id: str
    activity_id: str
    type: ReminderType
    scheduled_at: datetime
    status: ReminderStatus = ReminderStatus.SCHEDULED
    attempt: int = 0
    sent_at: Optional[datetime] = None
    response: Optional[str] = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------
# ActivityResult — lo que se devuelve al sistema originador
# ---------------------------------------------------------------------
class ActivityResultType(str, Enum):
    CONTACTED = "CONTACTED"
    NO_CONTACT = "NO_CONTACT"
    APPOINTMENT_CONFIRMED = "APPOINTMENT_CONFIRMED"
    RESCHEDULED = "RESCHEDULED"
    DECLINED = "DECLINED"
    ESCALATED = "ESCALATED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"
    ATTENDED = "ATTENDED"
    DATA_INSUFFICIENT = "DATA_INSUFFICIENT"


class ActivityResult(BaseModel):
    activity_id: str
    result: ActivityResultType
    appointment_id: Optional[str] = None
    patient_decision: Optional[str] = None
    barriers: List[str] = Field(default_factory=list)
    timestamps: Dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    next_action: Optional[str] = None
    correlation_id: Optional[str] = None


# =======================================================================
# Extensión: acceso bidireccional (ZANTIA Health — Agente de Acceso y
# Gestión de Atención). Añadido sobre el diseño de demanda inducida ya
# construido (recado 007), sin tocar nada de lo anterior en este archivo.
# =======================================================================


class RequestIntent(str, Enum):
    """Catálogo mínimo de intenciones de una solicitud iniciada por el
    paciente (distinto de `Activity.activity_type`, que es del sistema
    originador)."""

    PROGRAMAR_CITA = "PROGRAMAR_CITA"
    REPROGRAMAR_CITA = "REPROGRAMAR_CITA"
    CANCELAR_CITA = "CANCELAR_CITA"
    CONSULTAR_CITA = "CONSULTAR_CITA"
    CONFIRMAR_CITA = "CONFIRMAR_CITA"
    DEMANDA_INDUCIDA = "DEMANDA_INDUCIDA"
    INFORMACION_SERVICIO = "INFORMACION_SERVICIO"
    ESCALAMIENTO = "ESCALAMIENTO"
    # Mensaje urgente posterior al recado 058 — 5ta opción fija del menú
    # numerado (`gateway.py:_MENU_NUMERADO`), reconocida por el MISMO
    # mecanismo ya existente (`_interpretar_opcion_menu`/`_resolver_por_intent`)
    # que las otras 4, nunca un camino nuevo y paralelo. Solo alcanzable
    # SIN conversación abierta todavía (ver `_enrutar_solicitud_nueva`) —
    # la despedida DENTRO de una conversación en curso ya la reconoce
    # `HealthBrain._es_despedida`/`_DESPEDIDA` (recado 058), un mecanismo
    # distinto y ya existente para ese otro caso.
    SALIR = "SALIR"


class RequestStatus(str, Enum):
    RECIBIDA = "RECIBIDA"
    EN_PROCESO = "EN_PROCESO"
    RESUELTA = "RESUELTA"
    ESCALADA = "ESCALADA"


class PatientRequest(BaseModel):
    """Solicitud iniciada por el PACIENTE — distinta de `Activity`
    (trabajo asignado por el sistema IPS). Una `PatientRequest` puede
    dar lugar, internamente, a una `Activity` sintética que reutiliza el
    mismo motor conversacional ya construido (ver `domains/health/gateway.py`),
    pero como registro de dominio son conceptos separados: `Activity` =
    "la IPS decidió que había que contactar a este paciente";
    `PatientRequest` = "el paciente decidió escribir por su cuenta"."""

    model_config = {"validate_assignment": True}

    request_id: str
    patient_reference: str
    intent: RequestIntent
    channel: str
    created_at: datetime = Field(default_factory=_utcnow)
    status: RequestStatus = RequestStatus.RECIBIDA


class PatientConfirmationStatus(str, Enum):
    """Confirmación de ASISTENCIA declarada por el paciente — campo
    deliberadamente separado de `AppointmentStatus` (la agenda sigue
    siendo la única fuente de verdad del estado REAL de la cita; esto
    es solo lo que el paciente dijo, nunca se sobreescriben entre sí)."""

    SIN_CONFIRMAR = "SIN_CONFIRMAR"
    CONFIRMADO = "CONFIRMADO"
    RECHAZADO = "RECHAZADO"
