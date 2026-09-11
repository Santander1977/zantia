"""
Recado 068, Parte 1 — hallazgo real GRAVE, transcripción real:

  21:37 — Conversación 1: se ofrecen horarios "07:00, 07:30, 08:00"
  para Urgencias/lunes 14 de septiembre de 2026. El paciente elige "2"
  — se confirma "07:30". Correcto.

  21:41 — Conversación 2 (nueva, minutos después): se ofrecen horarios
  "07:00, 08:00, 08:30" (07:30 ya no está disponible — lo tomó la
  primera reserva) para el MISMO servicio/fecha. El paciente elige "1"
  (que en ESTA oferta corresponde a 07:00) — pero la confirmación dijo
  "07:30": un valor que NUNCA apareció en la segunda oferta, e idéntico
  a la reserva anterior.

CAUSA RAÍZ (confirmada leyendo `HrmmAppointmentService.book_appointment`,
`domains/health/hrmm_appointment_service.py`): el mecanismo de
"idempotencia adicional" (pensado para el camino OUTBOUND, donde un
reintento del sistema IPS podría disparar la misma gestión dos veces
con una `idempotency_key` distinta) comparaba solo `mismo_servicio` +
`misma_fecha` — NUNCA la hora/slot exacto. Cualquier cita activa
existente para ese servicio+fecha, sin importar el horario, se
devolvía tal cual como si fuera el resultado de la nueva selección —
sin llamar siquiera a `POST /api/agenda/citas` la segunda vez. No crea
una cita duplicada en la base real (por eso no hay "citas repetidas"
que limpiar), pero el sistema afirmó haber reservado algo que nunca
ocurrió.

CORREGIDO: se agregó `misma_hora` a la comparación — el mecanismo
sigue funcionando para su propósito original (mismo slot exacto, dos
`idempotency_key` distintas), pero ya no intercepta una selección de
horario genuinamente distinta el mismo día.

Ver también `tests/domains/health/test_hrmm_appointment_service.py`
(`test_book_appointment_en_conversacion_nueva_con_otro_horario_no_reutiliza_la_vieja`)
para la versión aislada, a nivel de `HrmmAppointmentService`, de este
mismo hallazgo.
"""
import os

import pytest

from domains.health import MockActivitySource, MockActivityResultSink, ReminderManager
from domains.health.gateway import build_health_gateway, handle_inbound_message
from domains.health.hrmm_appointment_service import HrmmAppointmentService
from domains.health.hrmm_catalog import CatalogMirror
from domains.health.hrmm_http import FakeHttpClient, HttpResponse

_FECHA_REAL = "2026-09-14"  # lunes, tal como en la transcripción real
_DOCUMENTO = "99999999"


@pytest.fixture(autouse=True)
def _secreto_de_prueba(monkeypatch):
    monkeypatch.setenv("HRMM_BACKEND_SECRET", "secreto-de-prueba-no-real")


def _construir_service():
    citas_creadas = []

    def generador(method, path, params, json_body, headers):
        if method == "GET" and path == "/api/agenda/servicios":
            return HttpResponse(200, [{"servicio_id": "S1", "nombre": "Urgencias"}])
        if method == "GET" and path == "/api/agenda/medicos":
            return HttpResponse(200, [{"medico_id": "M1", "nombre_completo": "Dr. Prueba", "servicio_id": "S1", "consultorio": "Urgencias"}])
        if method == "GET" and path == "/api/agenda/disponibilidad":
            # Ofrece SIEMPRE los slots reales que quedan libres — los ya
            # reservados desaparecen, igual que en producción real.
            slots_base = [("SLOT-0700", "07:00"), ("SLOT-0730", "07:30"), ("SLOT-0800", "08:00"), ("SLOT-0830", "08:30")]
            ocupados = {c["slot_id"] for c in citas_creadas}
            return HttpResponse(200, [
                {"slot_id": sid, "medico_id": "M1", "servicio_id": "S1", "fecha": _FECHA_REAL, "hora_inicio": hora, "hora_fin": hora, "estado": "Libre"}
                for sid, hora in slots_base if sid not in ocupados
            ])
        if method == "GET" and path == "/api/agenda/citas":
            documento = params.get("documento_paciente")
            return HttpResponse(200, [c for c in citas_creadas if c["documento_paciente"] == documento])
        if method == "GET" and path.startswith("/api/agenda/citas/"):
            cita_id = path.rsplit("/", 1)[-1]
            for c in citas_creadas:
                if c["cita_id"] == cita_id:
                    return HttpResponse(200, c)
            return HttpResponse(404, {"detail": "no encontrada"})
        if method == "POST" and path == "/api/agenda/citas":
            horas = {"SLOT-0700": "07:00", "SLOT-0730": "07:30", "SLOT-0800": "08:00", "SLOT-0830": "08:30"}
            nueva = {
                "cita_id": f"C{len(citas_creadas) + 1}",
                "slot_id": json_body["slot_id"],
                "medico_id": "M1", "servicio_id": "S1",
                "fecha": _FECHA_REAL, "hora_inicio": horas[json_body["slot_id"]],
                "documento_paciente": json_body["documento_paciente"],
                "nombre_paciente": json_body.get("nombre_paciente", ""),
                "telefono": json_body.get("telefono", ""),
                "estado": "reservada",
                "created_at": "2026-09-11T21:37:00Z", "updated_at": "2026-09-11T21:37:00Z",
            }
            citas_creadas.append(nueva)
            return HttpResponse(201, nueva)
        raise AssertionError(f"no programado en este escenario: {method} {path} {params}")

    http = FakeHttpClient(generador=generador)
    catalog = CatalogMirror()
    catalog.sync(http)
    return HrmmAppointmentService(http, catalog), citas_creadas


def test_segunda_conversacion_reserva_el_horario_realmente_elegido():
    service, citas_creadas = _construir_service()
    gateway = build_health_gateway(MockActivitySource(), service, ReminderManager(), MockActivityResultSink())

    # --- Conversación 1 (21:37 real): elige "2" -> 07:30 ---
    handle_inbound_message(gateway, _DOCUMENTO, "demo", "c1-m1", "necesito una cita de urgencias")
    r_fecha1 = handle_inbound_message(gateway, _DOCUMENTO, "demo", "c1-m2", "1")  # única fecha real
    assert "07:00" in r_fecha1 and "07:30" in r_fecha1 and "08:00" in r_fecha1
    r_conf1 = handle_inbound_message(gateway, _DOCUMENTO, "demo", "c1-m3", "2")
    assert "07:30" in r_conf1 and "confirmado" in r_conf1.lower()

    # --- Conversación 2 (21:41 real, patient_reference distinto por
    #     ser una Activity/conversación NUEVA — misma persona) ---
    handle_inbound_message(gateway, _DOCUMENTO, "demo", "c2-m1", "necesito otra cita de urgencias")
    r_fecha2 = handle_inbound_message(gateway, _DOCUMENTO, "demo", "c2-m2", "1")
    # 07:30 ya no debe ofrecerse (la tomó la conversación 1) — mismo
    # patrón real reportado ("07:00, 08:00, 08:30").
    assert "07:30" not in r_fecha2
    assert "07:00" in r_fecha2 and "08:00" in r_fecha2 and "08:30" in r_fecha2

    r_conf2 = handle_inbound_message(gateway, _DOCUMENTO, "demo", "c2-m3", "1")
    assert "07:00" in r_conf2, f"debía confirmar la hora REALMENTE elegida (07:00): {r_conf2!r}"
    assert "07:30" not in r_conf2, f"NUNCA debía reaparecer la hora de la reserva anterior: {r_conf2!r}"

    # Confirma también contra el estado real (no solo el texto): 2
    # citas reales y distintas, con las horas correctas cada una.
    assert len(citas_creadas) == 2
    horas_reales = sorted(c["hora_inicio"] for c in citas_creadas)
    assert horas_reales == ["07:00", "07:30"]
