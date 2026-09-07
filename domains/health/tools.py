"""
Tools del dominio salud — envuelven AppointmentService/ActivityResultSink
con el mismo contrato `tools.base.Tool` del Core (prompt 007: "implementa
el primer agente real SOBRE el core existente", no un mecanismo paralelo).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from tools.base import ToolCategory, ToolError, ToolResult

from .appointment_service import AppointmentService, AppointmentServiceError
from .result_sink import ActivityResultSink
from .models import ActivityResult, ActivityResultType


class GetAvailabilityTool:
    name = "get_availability"
    description = "Tool READ: consulta disponibilidad real (estructurada) en AppointmentService."
    category = ToolCategory.READ
    idempotent = True

    def __init__(self, appointment_service: AppointmentService) -> None:
        self._service = appointment_service

    def run(self, params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> ToolResult:
        service = params.get("service")
        if not service:
            return ToolResult(success=False, error="falta 'service'")
        slots = self._service.get_availability(service, location=params.get("location"))
        return ToolResult(
            success=True,
            data={"slots": [s.model_dump(mode="json") for s in slots]},
        )


class BookAppointmentTool:
    """WRITE — reserva Y confirma (dos pasos reales, sección 14: no se
    declara éxito si `confirm_appointment` no responde con éxito)."""

    name = "book_appointment"
    description = "Tool WRITE: reserva y confirma un turno, idempotente por clave."
    category = ToolCategory.WRITE
    idempotent = True

    def __init__(self, appointment_service: AppointmentService) -> None:
        self._service = appointment_service

    def run(self, params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> ToolResult:
        idempotency_key = params.get("idempotency_key")
        if not idempotency_key:
            raise ToolError("book_appointment requiere 'idempotency_key'")
        slot_id = params.get("slot_id")
        patient_reference = params.get("patient_reference")
        try:
            reservada = self._service.book_appointment(slot_id, patient_reference, idempotency_key)
        except AppointmentServiceError as exc:
            return ToolResult(success=False, error=str(exc))
        try:
            confirmada = self._service.confirm_appointment(reservada.appointment_id)
        except AppointmentServiceError as exc:
            return ToolResult(success=False, error=f"reservado pero no confirmado: {exc}")
        # Recado 054/058 — `confirm_appointment` es una RELECTURA contra
        # hrmm-backend (ver `HrmmAppointmentService.confirm_appointment`)
        # que no sabe nada de `correo_confirmacion_enviado` (anotación
        # puramente del lado de ZANTIA, nunca almacenada en hrmm-backend)
        # — sin este merge, el resultado de `book_appointment` (que SÍ
        # intentó el envío real) se perdía en silencio al sobreescribirse
        # con la relectura.
        datos_finales = confirmada.model_copy(
            update={"correo_confirmacion_enviado": reservada.correo_confirmacion_enviado}
        )
        return ToolResult(success=True, data=datos_finales.model_dump(mode="json"))


class RescheduleAppointmentTool:
    name = "reschedule_appointment"
    description = "Tool WRITE: reprograma una cita existente a un nuevo turno, idempotente."
    category = ToolCategory.WRITE
    idempotent = True

    def __init__(self, appointment_service: AppointmentService) -> None:
        self._service = appointment_service

    def run(self, params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> ToolResult:
        idempotency_key = params.get("idempotency_key")
        if not idempotency_key:
            raise ToolError("reschedule_appointment requiere 'idempotency_key'")
        try:
            reprogramada = self._service.reschedule_appointment(
                params.get("appointment_id"), params.get("new_slot_id"), idempotency_key
            )
        except AppointmentServiceError as exc:
            return ToolResult(success=False, error=str(exc))
        return ToolResult(success=True, data=reprogramada.model_dump(mode="json"))


class CancelAppointmentTool:
    name = "cancel_appointment"
    description = "Tool WRITE: cancela una cita existente."
    category = ToolCategory.WRITE
    idempotent = False

    def __init__(self, appointment_service: AppointmentService) -> None:
        self._service = appointment_service

    def run(self, params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> ToolResult:
        try:
            cancelada = self._service.cancel_appointment(params.get("appointment_id"))
        except AppointmentServiceError as exc:
            return ToolResult(success=False, error=str(exc))
        return ToolResult(success=True, data=cancelada.model_dump(mode="json"))


class RecordActivityResultTool:
    """NOTIFY — envía el resultado al sistema originador vía
    ActivityResultSink (prompt 007, sección 26)."""

    name = "record_activity_result"
    description = "Tool NOTIFY: reporta el resultado de la Activity al sistema IPS (mock)."
    category = ToolCategory.NOTIFY
    idempotent = True

    def __init__(self, result_sink: ActivityResultSink) -> None:
        self._sink = result_sink

    def run(self, params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> ToolResult:
        result = ActivityResult(
            activity_id=params["activity_id"],
            result=ActivityResultType(params["result"]),
            appointment_id=params.get("appointment_id"),
            patient_decision=params.get("patient_decision"),
            barriers=params.get("barriers", []),
            summary=params.get("summary", ""),
            next_action=params.get("next_action"),
            correlation_id=params.get("correlation_id"),
        )
        enviado = self._sink.send_result(result)
        return ToolResult(success=enviado, data={"result": result.model_dump(mode="json")})
