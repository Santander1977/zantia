"""
Sexto hallazgo real de la misma conversación de Telegram (recado 032):
tras elegir un horario real ("La 2") y que el sistema dijera "¡Perfecto!
Voy a reservarlo — dame un momento", la conversación quedaba en un
estado indefinido — ningún mensaje siguiente reportaba el resultado.

Causa raíz confirmada leyendo el código Y reproduciendo con
`FakeHttpClient` simulando una respuesta REAL de hrmm-backend:
`agent.py:_tool_exitosa` exigía `status == "CONFIRMED"` literal para
considerar exitosa la reserva — ese mapeo
(`hrmm_appointment_service.py:_MAPA_ESTADO_HRMM`) traduce el `estado`
real de una `Cita` de hrmm-backend, y sigue siendo INFERENCIA NUNCA
CONFIRMADA contra una cita real (riesgo R-9, abierto desde el recado
009). Si el `estado` real de una cita recién creada no está en ese
mapa (ej. "pendiente"), cae al default `AppointmentStatus.REQUESTED` —
la reserva se completa de verdad contra hrmm-backend (POST
/api/agenda/citas exitoso, sin ninguna excepción), pero el chequeo de
"éxito" nunca lo reconoce. Consecuencia, TODO en el mismo turno
silencioso:
- Nunca se agrega el texto de confirmación ("¡Listo! Quedó
  confirmado...").
- `Activity.management_status` nunca pasa a `APPOINTMENT_CONFIRMED`,
  ni se guarda `appointment_id` en la Activity.
- Nunca se programan los recordatorios de la cita.
- La Activity nunca se cierra (`_cerrar_si_definitivo` depende de
  `management_status`).
- El siguiente mensaje del paciente ("Ok") reabre el ciclo desde cero
  (`CIERRE` -> `_reabrir_ciclo`, mecanismo YA EXISTENTE) — perdiendo
  toda memoria de la reserva YA LOGRADA — y cae al fallback genérico de
  sí/no (recado 030), exactamente como se reportó. Un "Si" después
  vuelve a ofrecer disponibilidad DESDE CERO (nueva consulta real,
  turnos distintos a los ya vistos) e intentar reservar de nuevo NO
  crea una cita duplicada solo porque la idempotency_key
  (`{activity_id}:booking`) es la misma en la MISMA Activity — pero es
  una coincidencia del diseño existente, no una garantía pensada para
  este escenario.

Corrección: `BookAppointmentTool.run()` (tools.py, sin tocar) YA es la
autoridad real de éxito/fracaso de la escritura (`ToolResult.data` es
`None` en cualquier falla, no vacío solo si book+confirm respondieron
sin excepción) — se retira la exigencia adicional de una palabra de
estado específica, frágil y nunca confirmada, SOLO para
`book_appointment` (`agent.py:_book_appointment_exitoso`).
"""
from domains.health import (
    MockActivitySource, MockActivityResultSink, ReminderManager,
    build_health_gateway, handle_inbound_message,
)
from domains.health.hrmm_appointment_service import HrmmAppointmentService
from domains.health.hrmm_catalog import CatalogMirror
from domains.health.hrmm_http import FakeHttpClient, HttpResponse
from domains.health.models import ManagementStatus


def _gateway_con_estado_no_mapeado(monkeypatch, estado_real_de_la_cita: str):
    """Construye un gateway real (HrmmAppointmentService + CatalogMirror,
    vía FakeHttpClient) donde la cita recién creada tiene el `estado`
    indicado — para simular tanto un valor real NO contemplado en
    `_MAPA_ESTADO_HRMM` ("pendiente") como uno sí mapeado ("reservada",
    control positivo)."""
    monkeypatch.setenv("HRMM_BACKEND_SECRET", "secreto-de-prueba-no-real")
    citas_creadas = {}

    def generador(method, path, params, json_body, headers):
        if method == "GET" and path == "/api/agenda/servicios":
            return HttpResponse(200, [{"servicio_id": "S1", "nombre": "medicina general"}])
        if method == "GET" and path == "/api/agenda/medicos":
            return HttpResponse(200, [{"medico_id": "M1", "nombre_completo": "Dra. Ana Pérez", "servicio_id": "S1", "consultorio": "Consultorio 3"}])
        if method == "GET" and path == "/api/agenda/disponibilidad":
            return HttpResponse(200, [
                {"slot_id": "SLOT1", "medico_id": "M1", "servicio_id": "S1", "fecha": "2026-09-10", "hora_inicio": "09:00", "hora_fin": "09:30", "estado": "Libre"},
            ])
        if method == "POST" and path == "/api/agenda/citas":
            cita_id = "C-REAL-1"
            citas_creadas[cita_id] = {
                "cita_id": cita_id, "slot_id": json_body["slot_id"], "medico_id": "M1", "servicio_id": "S1",
                "fecha": "2026-09-10", "hora_inicio": "09:00",
                "documento_paciente": json_body["documento_paciente"], "nombre_paciente": "", "telefono": "",
                "estado": estado_real_de_la_cita,
                "created_at": "x", "updated_at": "x",
            }
            return HttpResponse(201, citas_creadas[cita_id])
        if method == "GET" and path.startswith("/api/agenda/citas/"):
            cita_id = path.rsplit("/", 1)[-1]
            return HttpResponse(200, citas_creadas[cita_id])
        if method == "GET" and path == "/api/agenda/citas":
            doc = params.get("documento_paciente")
            return HttpResponse(200, [c for c in citas_creadas.values() if c["documento_paciente"] == doc])
        raise AssertionError(f"no programado en este test: {method} {path} {params}")

    http = FakeHttpClient(generador=generador)
    catalog = CatalogMirror()
    catalog.sync(http)
    service = HrmmAppointmentService(http, catalog)
    gateway = build_health_gateway(MockActivitySource(), service, ReminderManager(), MockActivityResultSink())
    return gateway, citas_creadas


def test_reserva_real_con_estado_no_mapeado_se_confirma_de_todas_formas(monkeypatch):
    """Reproduce EXACTAMENTE la conversación real reportada: la cita se
    crea de verdad contra hrmm-backend, con un `estado` real que
    `_MAPA_ESTADO_HRMM` no contempla ("pendiente") — antes del fix,
    esto dejaba al paciente sin ninguna confirmación."""
    gateway, citas_creadas = _gateway_con_estado_no_mapeado(monkeypatch, "pendiente")

    r1 = handle_inbound_message(gateway, "999", "demo", "m1", "necesito una cita")
    assert "opciones disponibles" in r1.lower()

    r2 = handle_inbound_message(gateway, "999", "demo", "m2", "la primera")
    assert "confirmado" in r2.lower(), (
        "la reserva se completó de verdad contra hrmm-backend pero el paciente "
        "nunca recibió confirmación (bug real, recado 032)"
    )

    # El siguiente mensaje NUNCA debe reabrir un intento de reserva
    # nuevo ni caer en el fallback de sí/no — la cita ya quedó resuelta.
    r3 = handle_inbound_message(gateway, "999", "demo", "m3", "Ok")
    assert "no logré entender si es un sí o un no" not in r3.lower()
    assert "voy a reservarlo" not in r3.lower()

    assert len(citas_creadas) == 1, "no debió crearse una segunda cita real"


def test_reserva_real_actualiza_management_status_y_appointment_id(monkeypatch):
    gateway, _ = _gateway_con_estado_no_mapeado(monkeypatch, "pendiente")
    handle_inbound_message(gateway, "999", "demo", "m1", "necesito una cita")
    handle_inbound_message(gateway, "999", "demo", "m2", "la primera")

    actividades = [
        a for a in gateway.activity_source._activities.values() if a.patient_reference == "999"
    ]
    assert actividades
    activity = actividades[0]
    assert activity.management_status == ManagementStatus.APPOINTMENT_CONFIRMED, (
        "sin esto, _cerrar_si_definitivo nunca cierra la Activity ni se "
        "programan recordatorios — la reserva real queda invisible del "
        "lado del dominio, aunque exista de verdad en hrmm-backend"
    )
    assert activity.appointment_id == "C-REAL-1"


def test_reserva_real_con_estado_ya_mapeado_sigue_funcionando_como_antes(monkeypatch):
    """Control: con un `estado` real que SÍ está en `_MAPA_ESTADO_HRMM`
    ("reservada"), el comportamiento es idéntico al de antes del fix —
    la corrección no depende de que el estado esté mal mapeado."""
    gateway, _ = _gateway_con_estado_no_mapeado(monkeypatch, "reservada")
    handle_inbound_message(gateway, "999", "demo", "m1", "necesito una cita")
    r2 = handle_inbound_message(gateway, "999", "demo", "m2", "la primera")
    assert "confirmado" in r2.lower()
