"""
Recado 031 — 10 corridas completas del ciclo de reserva pedidas por el
usuario: catálogo -> elegir servicio -> disponibilidad real -> reserva
-> confirmación. Corren contra `MockAppointmentService` (test doubles,
sin red real) — ver el recado 031 para por qué NO se corrieron contra
`hrmm-backend` real (en este momento, `GET /api/agenda/disponibilidad`
real devuelve una lista vacía: cero cupos para cualquier servicio, así
que un ciclo de RESERVA real no tiene ningún turno que reservar de
verdad hoy).

"Confirmación" aquí significa que la Activity alcanza
`ManagementStatus.APPOINTMENT_CONFIRMED` con un `appointment_id` real
del `AppointmentService` — NO incluye el envío de un correo de
confirmación: `HrmmAppointmentService.book_appointment` no envía
ningún campo `correo` hoy (R-21, `.ai/RISKS.md`, ABIERTO desde el
recado 015) porque `Activity.patient_contact` no tiene ningún mecanismo
para capturarlo en primer lugar — ver recado 031 para el detalle
completo de por qué esto no se resolvió en esta sesión (decisión de
diseño, no una corrección de código).
"""
import pytest

from domains.health import (
    ManagementStatus, MockActivitySource, MockActivityResultSink, ReminderManager,
    build_health_gateway, handle_inbound_message,
)
from domains.health.appointment_service import AvailabilitySlot, MockAppointmentService
from domains.health.gateway import find_open_context

_SERVICIOS = ["medicina general", "pediatria", "odontologia", "psicologia", "urgencias"]


class _CatalogoCompleto(MockAppointmentService):
    """5 servicios reales (mismos nombres que el catálogo real de
    hrmm-backend, confirmado en vivo el 2026-09-06 — sin tildes) — 3
    turnos libres por servicio, suficientes para 10 corridas variadas
    sin agotar disponibilidad entre sí."""

    def _seed_fictional_data(self) -> None:
        super()._seed_fictional_data()
        self._catalogo_servicios = list(_SERVICIOS)
        for servicio in _SERVICIOS:
            for i in range(3):
                slot_id = f"{servicio}-{i}"
                self._slots[slot_id] = AvailabilitySlot(
                    slot_id=slot_id, service=servicio, professional=f"Dr. {servicio.title()} {i}",
                    location="Sede Norte", date=f"2026-09-{10 + i}", time="09:00",
                )


_CASOS = [
    ("TG-CICLO-1", "que servicios tienen", "medicina general", "1"),
    ("TG-CICLO-2", "Que tienes disponible para citas", "Medicina General", "2"),
    ("TG-CICLO-3", "necesito una cita", "pediatria", "primera"),
    ("TG-CICLO-4", "Necesito una cita", "Pediatria", "segunda"),
    ("TG-CICLO-5", "cual tienes", "odontologia", "1"),
    ("TG-CICLO-6", "Cuál tienes", "Odontologia", "tercera"),
    ("TG-CICLO-7", "qué servicios tienen", "psicologia", "1"),
    ("TG-CICLO-8", "quiero agendar una cita", "Psicologia", "segunda"),
    ("TG-CICLO-9", "cuales servicios tienes", "urgencias", "1"),
    ("TG-CICLO-10", "Necesito Una Cita", "Urgencias", "primera"),
]


@pytest.mark.parametrize("patient_reference,mensaje_inicial,servicio_elegido,seleccion", _CASOS)
def test_ciclo_completo_servicio_disponibilidad_reserva_confirmacion(
    patient_reference, mensaje_inicial, servicio_elegido, seleccion,
):
    gateway = build_health_gateway(
        MockActivitySource(), _CatalogoCompleto(), ReminderManager(), MockActivityResultSink(),
    )

    # 1. Catálogo / intención inicial — nunca debe saltar directo a
    #    disponibilidad de un servicio no confirmado (recado 030/031).
    r1 = handle_inbound_message(gateway, patient_reference, "telegram", "m1", mensaje_inicial)
    assert "opciones disponibles" not in r1.lower(), (
        f"[{patient_reference}] asumió disponibilidad antes de que el paciente eligiera servicio"
    )

    # 2. Elegir servicio real del catálogo (recado 031: debe reconocerse
    #    vía 'esperando_servicio', nunca caer al fallback de sí/no).
    r2 = handle_inbound_message(gateway, patient_reference, "telegram", "m2", servicio_elegido)
    assert "no logré entender si es un sí o un no" not in r2.lower(), (
        f"[{patient_reference}] '{servicio_elegido}' no se reconoció como elección de servicio"
    )
    assert "opciones disponibles" in r2.lower(), f"[{patient_reference}] no ofreció disponibilidad real"

    # 3. Reservar una de las opciones reales ofrecidas.
    r3 = handle_inbound_message(gateway, patient_reference, "telegram", "m3", seleccion)
    assert "confirmado" in r3.lower(), f"[{patient_reference}] no confirmó la reserva: {r3!r}"

    # 4. Confirmación real del lado del dominio: Activity + AppointmentService
    #    coinciden en que la cita quedó CONFIRMED — nunca solo un texto
    #    optimista sin respaldo real (principio ya establecido, recado 007).
    contexto = find_open_context(gateway, patient_reference) or gateway._contexts.get(
        next(iter(gateway._open_conversations.values()), None)
    )
    # La Activity pudo cerrarse (CIERRE) tras confirmar — se busca en
    # activity_source directamente si `find_open_context` ya no la ve.
    actividades = [
        a for a in gateway.activity_source._activities.values()
        if a.patient_reference == patient_reference
    ]
    assert actividades, f"[{patient_reference}] no se encontró ninguna Activity"
    activity = actividades[0]
    assert activity.management_status == ManagementStatus.APPOINTMENT_CONFIRMED
    assert activity.appointment_id is not None

    citas_reales = gateway.appointment_service.get_patient_appointments(patient_reference)
    assert len(citas_reales) == 1
    assert citas_reales[0].appointment_id == activity.appointment_id
    assert citas_reales[0].service == servicio_elegido.strip().lower()
