"""
Orquestación de dominio salud (prompt 007, secciones 8-9, 16-26).

Capa de "pegamento" ENTRE la Activity y el Core existente — no
reemplaza al `core.Orchestrator`, lo reutiliza tal cual (prompt 007:
"AHORA VAMOS A CONSTRUIR EL PRIMER AGENTE REAL SOBRE EL CORE
EXISTENTE"). Es la única capa con autoridad para actualizar
`Activity.status`/`Activity.management_status` — igual principio que
el Core: el Brain solo propone (vía `BrainOutput` y `senales_detectadas`),
esta capa decide de forma determinista qué implica cada señal para el
dominio.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from core.agent_contract import AgentDefinition, build_orchestrator
from core.orchestrator import Orchestrator, OrchestratorResult
from observability.events import EventType
from state.machine import validate_transition
from state.models import FaseActual

from .activity_source import ActivitySource
from .appointment_service import AppointmentService
from .brain import HealthBrain
from .models import Activity, ActivityStatus, ManagementStatus
from .reminder_manager import ReminderManager
from .result_sink import ActivityResultSink
from .tools import (
    BookAppointmentTool,
    CancelAppointmentTool,
    GetAvailabilityTool,
    RecordActivityResultTool,
    RescheduleAppointmentTool,
)

_MENSAJE_CONTACTO = (
    "Hola {nombre}, te escribimos de {programa} para ayudarte a programar tu atención "
    "({motivo}). ¿Te gustaría que te ayude a programar?"
)


@dataclass
class HealthAgentContext:
    activity: Activity
    activity_source: ActivitySource
    appointment_service: AppointmentService
    reminder_manager: ReminderManager
    result_sink: ActivityResultSink
    orchestrator: Optional[Orchestrator] = None


def build_health_agent_context(
    activity: Activity,
    activity_source: ActivitySource,
    appointment_service: AppointmentService,
    reminder_manager: ReminderManager,
    result_sink: ActivityResultSink,
) -> HealthAgentContext:
    # `context` se crea ANTES que el Brain para poder pasarle un
    # proveedor perezoso (`lambda: context.activity`) — así el Brain
    # siempre lee la Activity vigente, nunca la copia congelada del
    # momento de construcción (ver docstring de HealthBrain).
    context = HealthAgentContext(
        activity=activity,
        activity_source=activity_source,
        appointment_service=appointment_service,
        reminder_manager=reminder_manager,
        result_sink=result_sink,
    )
    tools = [
        GetAvailabilityTool(appointment_service),
        BookAppointmentTool(appointment_service),
        RescheduleAppointmentTool(appointment_service),
        CancelAppointmentTool(appointment_service),
        RecordActivityResultTool(result_sink),
    ]
    definition = AgentDefinition(
        name=f"health-{activity.activity_id}",
        domain="health",
        brain=HealthBrain(lambda: context.activity, appointment_service),
        tools=tools,
        memory_window=12,
    )
    # El consentimiento de datos ya lo otorgó el paciente al ser incluido
    # en el programa por el sistema originador (fuera de este canal) —
    # se registra explícitamente en el estado de la conversación al
    # iniciar el contacto, no se asume implícitamente en ningún guardrail.
    context.orchestrator = build_orchestrator(definition)
    return context


def _touch(activity: Activity, **cambios) -> Activity:
    return activity.model_copy(update={**cambios, "updated_at": datetime.now(timezone.utc)})


def accept_activity(context: HealthAgentContext) -> Activity:
    """Activity: PENDING/ACCEPTED -> IN_PROGRESS (sección 5)."""
    activity = _touch(context.activity, status=ActivityStatus.IN_PROGRESS)
    context.activity = context.activity_source.update(activity)
    context.orchestrator.events.record(
        activity.activity_id, EventType.STATE_TRANSITION, evento="ACTIVITY_STARTED"
    )
    return context.activity


def contact_patient(context: HealthAgentContext) -> str:
    """Contacto inicial — mensaje DETERMINISTA (plantilla), no generado
    por el Brain (mismo principio que ReminderManager: sección 17).
    Seed del ConversationState para que el primer mensaje del paciente
    ya encuentre `etapa='esperando_decision'`."""
    activity = context.activity
    nombre = activity.patient_contact.get("nombre", "")
    mensaje = _MENSAJE_CONTACTO.format(
        nombre=nombre, programa=activity.program or "tu programa de salud", motivo=activity.reason or "una atención pendiente"
    )

    estado = context.orchestrator.store.create(activity.activity_id, canal="demo")
    estado_inicial = estado.model_copy(
        update={
            "fase_actual": FaseActual.IDENTIFICACION_DE_INTENCION,
            "objetivo_de_conversacion": "gestion_demanda_inducida",
            "datos_recopilados": {"etapa": "esperando_decision"},
            "consentimiento_datos": True,  # autorizado por el sistema originador, ver docstring de build_health_agent_context
        }
    )
    context.orchestrator.store.save(estado_inicial, expected_version=estado.version)

    context.activity = _touch(
        activity,
        management_status=ManagementStatus.CONTACTING,
        contact_attempts=activity.contact_attempts + 1,
    )
    context.activity_source.update(context.activity)
    context.orchestrator.events.record(activity.activity_id, EventType.STATE_TRANSITION, evento="CONTACT_ATTEMPTED")
    context.activity = _touch(context.activity, management_status=ManagementStatus.CONTACTED)
    context.activity_source.update(context.activity)
    context.orchestrator.events.record(activity.activity_id, EventType.STATE_TRANSITION, evento="CONTACT_ESTABLISHED")
    return mensaje


#: Etapas "de un solo disparo": la acción (reservar/reprogramar/cancelar)
#: se propone y se ejecuta en el MISMO turno en el que el Brain fija esta
#: etapa (no en el turno siguiente). Por eso la sincronización usa la
#: etapa ACTUAL (no la anterior) para detectarlas, y las "consume"
#: (las mueve a su forma "_completado") para que no se re-disparen en
#: turnos futuros, dado que `resultado_de_herramientas` es acumulativo
#: entre turnos (004, sección 2.1) — corrección encontrada al construir
#: este dominio, ver recado 007.
_ETAPAS_DE_UN_DISPARO = {
    "reservando": ("book_appointment", "CONFIRMED"),
    "reprogramando": ("reschedule_appointment", "RESCHEDULED"),
    "cancelando": ("cancel_appointment", "CANCELLED"),
}


def handle_patient_message(context: HealthAgentContext, message_id: str, text: str) -> str:
    """Delega en el Orchestrator del Core (sin modificarlo, salvo la
    corrección de sección 14) y sincroniza la Activity de forma
    determinista según lo ocurrido en el turno."""
    resultado: OrchestratorResult = context.orchestrator.handle_message(
        context.activity.activity_id, "demo", message_id, text
    )
    respuesta = resultado.response
    etapa_actual = resultado.state.datos_recopilados.get("etapa")
    resultados_tools = resultado.state.resultado_de_herramientas

    context.activity = _sincronizar_activity(context, resultado)
    context.activity_source.update(context.activity)

    just_booked = etapa_actual == "reservando" and _tool_exitosa(resultados_tools, "book_appointment", "CONFIRMED")
    just_rescheduled = etapa_actual == "reprogramando" and _tool_exitosa(
        resultados_tools, "reschedule_appointment", "RESCHEDULED"
    )
    if just_booked or just_rescheduled:
        # Ambos casos terminan en una cita CONFIRMADA con appointment_id
        # nuevo — en ambos hace falta programar sus propios recordatorios
        # (para reprogramación, los de la cita anterior ya se cancelaron
        # dentro de `_sincronizar_activity`).
        cita = context.appointment_service.get_appointment(context.activity.appointment_id)
        if cita is not None:
            fecha_hora = _parse_fecha_hora(cita.date, cita.time)
            context.reminder_manager.schedule_for_appointment(
                context.activity.activity_id, cita.appointment_id, fecha_hora
            )
            verbo = "confirmado" if just_booked else "reprogramado"
            respuesta = (
                respuesta
                + f" Quedó {verbo}: {cita.service} el {cita.date} a las {cita.time} en {cita.location}."
            )
            evento = "APPOINTMENT_CONFIRMED" if just_booked else "APPOINTMENT_RESCHEDULED"
            context.orchestrator.events.record(context.activity.activity_id, EventType.STATE_TRANSITION, evento=evento)

    if etapa_actual == "cancelando" and _tool_exitosa(resultados_tools, "cancel_appointment", "CANCELLED"):
        context.orchestrator.events.record(
            context.activity.activity_id, EventType.STATE_TRANSITION, evento="APPOINTMENT_CANCELLED"
        )

    _normalizar_tras_turno(context, etapa_actual, resultados_tools)
    return respuesta


def _tool_exitosa(resultados_tools: dict, nombre_tool: str, status_esperado: str) -> bool:
    datos = resultados_tools.get(nombre_tool)
    return bool(datos) and datos.get("status") == status_esperado


def _normalizar_tras_turno(context: HealthAgentContext, etapa_actual, resultados_tools: dict) -> None:
    """Tras cada turno: (1) si la conversación quedó en RESPUESTA —un
    'waypoint' de un solo turno en el Core, no pensado para acumular
    varios turnos seguidos (004, sección 9)— se cierra formalmente a
    CIERRE; (2) si la etapa era una "de un solo disparo" ya resuelta,
    se consume (evita que un turno futuro la vuelva a detectar como si
    acabara de ocurrir)."""
    estado = context.orchestrator.store.get(context.activity.activity_id)
    if estado is None:
        return

    cambios: Dict[str, Any] = {}
    if estado.fase_actual == FaseActual.RESPUESTA:
        validate_transition(estado.fase_actual, FaseActual.CIERRE)
        cambios["fase_actual"] = FaseActual.CIERRE

    if etapa_actual in _ETAPAS_DE_UN_DISPARO:
        nombre_tool, status_esperado = _ETAPAS_DE_UN_DISPARO[etapa_actual]
        if _tool_exitosa(resultados_tools, nombre_tool, status_esperado):
            nuevos_datos = dict(estado.datos_recopilados)
            nuevos_datos["etapa"] = f"{etapa_actual}_completado"
            cambios["datos_recopilados"] = nuevos_datos

    if cambios:
        context.orchestrator.store.save(estado.model_copy(update=cambios), expected_version=estado.version)


def _parse_fecha_hora(date: str, time: str) -> datetime:
    return datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)


def _sincronizar_activity(context: HealthAgentContext, resultado: OrchestratorResult) -> Activity:
    """Determinista, basada en la etapa ACTUAL de este turno (la acción
    se propone y se ejecuta en el MISMO turno en que el Brain fija la
    etapa "de un solo disparo" — ver `_ETAPAS_DE_UN_DISPARO`). No se usa
    solo "¿existe la clave en resultado_de_herramientas?" porque ese
    diccionario es acumulativo entre turnos (004, sección 2.1) — mirar
    solo eso habría hecho que, tras una reprogramación, el chequeo de
    `book_appointment` de la reserva ORIGINAL siguiera "ganando" para
    siempre. Corrección encontrada al construir este dominio (recado 007)."""
    activity = context.activity
    estado = resultado.state
    datos = estado.datos_recopilados
    etapa = datos.get("etapa")
    resultados_tools = estado.resultado_de_herramientas

    if resultado.escalated:
        return _touch(activity, management_status=ManagementStatus.ESCALATED)

    if datos.get("decision") == "DECLINED":
        return _touch(activity, management_status=ManagementStatus.DECLINED)

    if etapa == "esperando_seleccion":
        return _touch(activity, management_status=ManagementStatus.ENGAGED)

    if etapa == "esperando_seleccion_reprogramacion":
        return _touch(activity, management_status=ManagementStatus.RESCHEDULE_REQUESTED)

    if etapa == "asistencia_confirmada":
        # El paciente confirmó tras un recordatorio — `fire_reminder` había
        # dejado management_status en REMINDER_72H/24H/8H; se restaura a
        # APPOINTMENT_CONFIRMED (sigue con cita vigente, ya reconfirmada).
        return _touch(activity, management_status=ManagementStatus.APPOINTMENT_CONFIRMED)

    if etapa == "reservando" and _tool_exitosa(resultados_tools, "book_appointment", "CONFIRMED"):
        appointment_id = resultados_tools["book_appointment"].get("appointment_id")
        return _touch(
            activity, management_status=ManagementStatus.APPOINTMENT_CONFIRMED, appointment_id=appointment_id
        )

    if etapa == "reprogramando" and _tool_exitosa(resultados_tools, "reschedule_appointment", "RESCHEDULED"):
        nuevo_appointment_id = resultados_tools["reschedule_appointment"].get("appointment_id")
        if activity.appointment_id:
            context.reminder_manager.cancel_for_appointment(activity.appointment_id)
        return _touch(
            activity, management_status=ManagementStatus.RESCHEDULED, appointment_id=nuevo_appointment_id
        )

    if etapa == "cancelando" and _tool_exitosa(resultados_tools, "cancel_appointment", "CANCELLED"):
        if activity.appointment_id:
            context.reminder_manager.cancel_for_appointment(activity.appointment_id)
        return _touch(activity, status=ActivityStatus.CANCELLED)

    return activity


def fire_reminder(context: HealthAgentContext, reminder) -> str:
    """Envío determinista de un recordatorio (sección 17) — nunca
    generado por el Brain."""
    appointment = context.appointment_service.get_appointment(reminder.appointment_id)
    mensaje = context.reminder_manager.render_message(reminder, appointment)
    context.reminder_manager.mark_sent(reminder.reminder_id)

    mapa_status = {
        "REMINDER_72H": ManagementStatus.REMINDER_72H,
        "REMINDER_24H": ManagementStatus.REMINDER_24H,
        "REMINDER_8H": ManagementStatus.REMINDER_8H,
    }
    context.activity = _touch(context.activity, management_status=mapa_status[reminder.type.value])
    context.activity_source.update(context.activity)
    context.orchestrator.events.record(
        context.activity.activity_id, EventType.STATE_TRANSITION, evento=f"REMINDER_SENT:{reminder.type.value}"
    )
    return mensaje


def handle_reminder_response(context: HealthAgentContext, reminder, message_id: str, text: str) -> str:
    context.reminder_manager.mark_responded(reminder.reminder_id, text)
    context.orchestrator.events.record(
        context.activity.activity_id, EventType.STATE_TRANSITION, evento="REMINDER_CONFIRMED"
    )
    return handle_patient_message(context, message_id, text)


def handle_no_show(context: HealthAgentContext) -> None:
    """El sistema de agenda informa NO_SHOW (sección 24) — señal
    externa, no un mensaje del paciente. ZANTIA registra el hecho y
    prepara el resultado; NO crea automáticamente una nueva cita ni una
    nueva Activity de recuperación — eso lo decide después el sistema
    originador."""
    if context.activity.appointment_id:
        context.appointment_service.mark_no_show(context.activity.appointment_id)
        context.reminder_manager.cancel_for_appointment(context.activity.appointment_id)
    context.activity = _touch(context.activity, management_status=ManagementStatus.NO_SHOW)
    context.activity_source.update(context.activity)
    context.orchestrator.events.record(context.activity.activity_id, EventType.STATE_TRANSITION, evento="NO_SHOW")


def handle_attended(context: HealthAgentContext) -> None:
    """El sistema de agenda informa asistencia — misma naturaleza de
    señal externa que `handle_no_show`."""
    if context.activity.appointment_id:
        context.appointment_service.mark_attended(context.activity.appointment_id)
    context.activity = _touch(context.activity, management_status=ManagementStatus.ATTENDED)
    context.activity_source.update(context.activity)
    context.orchestrator.events.record(context.activity.activity_id, EventType.STATE_TRANSITION, evento="ATTENDED")


def finalize_and_report(context: HealthAgentContext, next_action: Optional[str] = None) -> None:
    """Cierra la Activity y reporta el resultado al sistema originador
    (secciones 25-26) — vía la misma tool NOTIFY que usa el Orchestrator,
    invocada aquí directamente porque es un evento de sistema, no una
    respuesta a un mensaje del paciente."""
    activity = context.activity
    resultado_map = {
        ManagementStatus.APPOINTMENT_CONFIRMED: "APPOINTMENT_CONFIRMED",
        ManagementStatus.RESCHEDULED: "RESCHEDULED",
        ManagementStatus.DECLINED: "DECLINED",
        ManagementStatus.ESCALATED: "ESCALATED",
        ManagementStatus.ATTENDED: "ATTENDED",
        ManagementStatus.NO_SHOW: "NO_SHOW",
    }
    if activity.status == ActivityStatus.CANCELLED:
        resultado_tipo = "CANCELLED"
    else:
        resultado_tipo = resultado_map.get(activity.management_status, "DATA_INSUFFICIENT")

    tool = context.orchestrator.tools.get("record_activity_result")
    tool.run(
        {
            "activity_id": activity.activity_id,
            "result": resultado_tipo,
            "appointment_id": activity.appointment_id,
            "correlation_id": activity.correlation_id,
            "next_action": next_action,
        }
    )
    nuevo_status = (
        ActivityStatus.CANCELLED if activity.status == ActivityStatus.CANCELLED else ActivityStatus.COMPLETED
    )
    context.activity = _touch(activity, status=nuevo_status)
    context.activity_source.update(context.activity)
    context.orchestrator.events.record(
        activity.activity_id, EventType.STATE_TRANSITION, evento="ACTIVITY_COMPLETED"
    )
