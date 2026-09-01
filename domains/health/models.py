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
