"""
Recado 035 — dos pedidos en un mismo trabajo:

1. Flujo de selección en 3 etapas separadas (servicio -> fecha ->
   horario), en vez de un solo bloque combinado
   ("1) 2026-09-07 07:00 en Consultorio 2"). Cada paso consulta
   disponibilidad REAL (nunca inventada) y filtra correctamente sobre
   lo ya elegido en el paso anterior.

2. Mensaje de confirmación por correo tras cualquiera de las 3 acciones
   reales (reservar, cancelar, reprogramar).

   ACTUALIZADO (recado 054, corrige una suposición del 035 nunca
   verificada contra el código real): la decisión de producto original
   ("hrmm-backend ya envía ese correo de forma NATIVA al ejecutar el
   POST real") resultó ser FALSA — confirmado leyendo el código real
   del repo hermano hrmm: ni `crear_cita` ni `cancelar_cita`/
   `reprogramar_cita_endpoint` disparan ningún correo; existe un
   endpoint aparte (`POST /citas/{id}/enviar-confirmacion`) que hay que
   llamar explícitamente. Antes de este hallazgo, ZANTIA prometía en
   texto un correo que NUNCA se enviaba de verdad. Los tests de la
   sección 2 (abajo) ahora verifican la versión honesta: la frase de
   correo solo aparece cuando `HrmmAppointmentService` de verdad
   disparó `enviar_confirmacion_email` y tiene un correo real para
   hacerlo — hoy ZANTIA no captura el correo del paciente en ningún
   punto de la conversación, así que en estos tests (sin correo
   conocido) el sufijo queda vacío, nunca una promesa en falso.
"""
from domains.health import (
    MockActivitySource, MockActivityResultSink, ReminderManager,
    build_health_gateway, handle_inbound_message,
)
from domains.health.hrmm_appointment_service import HrmmAppointmentService
from domains.health.hrmm_catalog import CatalogMirror
from domains.health.hrmm_http import FakeHttpClient, HttpResponse


def _gateway_real(monkeypatch, citas_reales=None, extra_slots=None):
    monkeypatch.setenv("HRMM_BACKEND_SECRET", "secreto-de-prueba-no-real")
    citas_reales = citas_reales if citas_reales is not None else {}
    slots_disponibilidad = [
        {"slot_id": "SLOT-A1", "medico_id": "M1", "servicio_id": "S1", "fecha": "2026-09-07", "hora_inicio": "07:00", "hora_fin": "07:30", "estado": "Libre"},
        {"slot_id": "SLOT-A2", "medico_id": "M1", "servicio_id": "S1", "fecha": "2026-09-07", "hora_inicio": "07:30", "hora_fin": "08:00", "estado": "Libre"},
        {"slot_id": "SLOT-B1", "medico_id": "M1", "servicio_id": "S1", "fecha": "2026-09-08", "hora_inicio": "09:00", "hora_fin": "09:30", "estado": "Libre"},
    ]
    if extra_slots:
        slots_disponibilidad = extra_slots

    def generador(method, path, params, json_body, headers):
        if method == "GET" and path == "/api/agenda/servicios":
            return HttpResponse(200, [{"servicio_id": "S1", "nombre": "medicina general"}])
        if method == "GET" and path == "/api/agenda/medicos":
            return HttpResponse(200, [{"medico_id": "M1", "nombre_completo": "Dra. Ana Pérez", "servicio_id": "S1", "consultorio": "Consultorio 3"}])
        if method == "GET" and path == "/api/agenda/disponibilidad":
            return HttpResponse(200, slots_disponibilidad)
        if method == "POST" and path == "/api/agenda/citas":
            cita_id = "C-REAL-1"
            citas_reales[cita_id] = {
                "cita_id": cita_id, "slot_id": json_body["slot_id"], "medico_id": "M1", "servicio_id": "S1",
                "fecha": next(s["fecha"] for s in slots_disponibilidad if s["slot_id"] == json_body["slot_id"]),
                "hora_inicio": next(s["hora_inicio"] for s in slots_disponibilidad if s["slot_id"] == json_body["slot_id"]),
                "documento_paciente": json_body["documento_paciente"], "nombre_paciente": "", "telefono": "",
                "estado": "agendada", "created_at": "x", "updated_at": "x",
            }
            return HttpResponse(201, citas_reales[cita_id])
        if method == "GET" and path.startswith("/api/agenda/citas/"):
            return HttpResponse(200, citas_reales[path.rsplit("/", 1)[-1]])
        if method == "GET" and path == "/api/agenda/citas":
            doc = params.get("documento_paciente")
            return HttpResponse(200, [c for c in citas_reales.values() if c["documento_paciente"] == doc])
        raise AssertionError(f"no programado en este test: {method} {path} {params}")

    http = FakeHttpClient(generador=generador)
    catalog = CatalogMirror()
    catalog.sync(http)
    service = HrmmAppointmentService(http, catalog)
    gateway = build_health_gateway(MockActivitySource(), service, ReminderManager(), MockActivityResultSink())
    return gateway, citas_reales


# ---------------------------------------------------------------------
# 1. Flujo completo en 3 etapas, filtrando correctamente sobre lo ya
#    elegido — con FakeHttpClient (real HrmmAppointmentService/CatalogMirror).
# ---------------------------------------------------------------------
def test_flujo_en_3_etapas_filtra_correctamente_sobre_lo_ya_elegido(monkeypatch):
    gateway, citas_reales = _gateway_real(monkeypatch)

    # PASO 1: servicio único -> se ofrecen fechas directo (sin preguntar
    # cuál servicio, ya que solo hay uno real en este catálogo).
    r1 = handle_inbound_message(gateway, "999", "demo", "m1", "necesito una cita")
    assert "fechas disponibles" in r1.lower()
    assert "07:00" not in r1 and "07:30" not in r1 and "09:00" not in r1, (
        "el Paso 1 (fechas) no debe mostrar horarios todavía"
    )
    # Dos fechas reales distintas, ambas presentes.
    assert "lunes 7 de septiembre" in r1.lower()
    assert "martes 8 de septiembre" in r1.lower()

    # PASO 2: elige la PRIMERA fecha (2026-09-07) -> horarios SOLO de
    # esa fecha (dos turnos reales: 07:00 y 07:30) — NUNCA el de la
    # otra fecha (09:00, que pertenece al 2026-09-08).
    r2 = handle_inbound_message(gateway, "999", "demo", "m2", "1")
    assert "horarios disponibles" in r2.lower()
    assert "07:00" in r2 and "07:30" in r2
    assert "09:00" not in r2, "no debe filtrarse mal — 09:00 pertenece a la OTRA fecha"

    # PASO 3: elige el SEGUNDO horario de esa fecha (07:30) -> reserva
    # el slot REAL correcto (SLOT-A2, no SLOT-A1 ni SLOT-B1).
    r3 = handle_inbound_message(gateway, "999", "demo", "m3", "2")
    assert "confirmado" in r3.lower()
    assert len(citas_reales) == 1
    cita = next(iter(citas_reales.values()))
    assert cita["slot_id"] == "SLOT-A2"
    assert cita["fecha"] == "2026-09-07"
    assert cita["hora_inicio"] == "07:30"


def test_elegir_la_segunda_fecha_ofrece_horarios_de_esa_fecha_no_de_la_primera(monkeypatch):
    gateway, citas_reales = _gateway_real(monkeypatch)

    handle_inbound_message(gateway, "888", "demo", "m1", "necesito una cita")
    r2 = handle_inbound_message(gateway, "888", "demo", "m2", "2")  # segunda fecha: 2026-09-08
    assert "09:00" in r2
    assert "07:00" not in r2 and "07:30" not in r2

    r3 = handle_inbound_message(gateway, "888", "demo", "m3", "1")
    assert "confirmado" in r3.lower()
    cita = next(iter(citas_reales.values()))
    assert cita["slot_id"] == "SLOT-B1"
    assert cita["fecha"] == "2026-09-08"


def test_fecha_no_identificada_no_asume_ninguna_y_permite_reintentar(monkeypatch):
    gateway, _ = _gateway_real(monkeypatch)
    handle_inbound_message(gateway, "777", "demo", "m1", "necesito una cita")
    r2 = handle_inbound_message(gateway, "777", "demo", "m2", "no sé, cualquiera")
    assert "no logré identificar cuál fecha" in r2.lower() or "no reconocí cuál de esas fechas" in r2.lower()
    # Puede reintentar con normalidad:
    r3 = handle_inbound_message(gateway, "777", "demo", "m3", "1")
    assert "horarios disponibles" in r3.lower()


# ---------------------------------------------------------------------
# 2. Correo de confirmación tras las 3 acciones reales.
# ---------------------------------------------------------------------
def test_correo_de_confirmacion_tras_reserva_real(monkeypatch):
    gateway, citas_reales = _gateway_real(monkeypatch)
    handle_inbound_message(gateway, "999", "demo", "m1", "necesito una cita")
    handle_inbound_message(gateway, "999", "demo", "m2", "1")
    r3 = handle_inbound_message(gateway, "999", "demo", "m3", "1")

    assert "confirmado" in r3.lower()
    # Recado 054 — sin correo conocido (ZANTIA no lo captura hoy), NUNCA
    # se promete un envío que no ocurrió (ver docstring del módulo).
    assert "te enviamos un correo de confirmación" not in r3.lower()
    assert len(citas_reales) == 1


def test_correo_de_confirmacion_tras_cancelacion_real(monkeypatch):
    monkeypatch.setenv("HRMM_BACKEND_SECRET", "secreto-de-prueba-no-real")
    from domains.health.models import Activity

    cita_base = {
        "cita_id": "C1", "slot_id": "SLOT1", "medico_id": "M1", "servicio_id": "S1",
        "fecha": "2026-09-10", "hora_inicio": "09:00", "documento_paciente": "999",
        "nombre_paciente": "", "telefono": "", "estado": "agendada",
        "created_at": "x", "updated_at": "x",
    }

    def generador(method, path, params, json_body, headers):
        if method == "GET" and path == "/api/agenda/servicios":
            return HttpResponse(200, [{"servicio_id": "S1", "nombre": "medicina general"}])
        if method == "GET" and path == "/api/agenda/medicos":
            return HttpResponse(200, [{"medico_id": "M1", "nombre_completo": "Dra. Ana Pérez", "servicio_id": "S1", "consultorio": "Consultorio 3"}])
        if method == "GET" and path == "/api/agenda/citas":
            return HttpResponse(200, [cita_base])
        if method == "POST" and path == "/api/agenda/verificacion/enviar":
            return HttpResponse(200, {"enviado": True, "correo_parcial": "a***@dominio.com"})
        if method == "POST" and path == "/api/agenda/citas/C1/cancelar":
            assert params["codigo"] == "654321"
            return HttpResponse(200, dict(cita_base, estado="cancelada"))
        raise AssertionError(f"no programado en este test: {method} {path} {params}")

    http = FakeHttpClient(generador=generador)
    catalog = CatalogMirror()
    catalog.sync(http)
    service = HrmmAppointmentService(http, catalog)
    identity_store_module = __import__("domains.health.identity_store", fromlist=["SQLiteIdentidadCanalStore"])
    identity_store = identity_store_module.SQLiteIdentidadCanalStore(":memory:")
    identity_store.marcar_verificado("999", "999", "Enzo")
    gateway = build_health_gateway(
        MockActivitySource(), service, ReminderManager(), MockActivityResultSink(),
        identity_store=identity_store,
    )

    r1 = handle_inbound_message(gateway, "999", "demo", "m1", "cancelar mi cita")
    assert "código" in r1.lower()
    r2 = handle_inbound_message(gateway, "999", "demo", "m2", "654321")

    assert "cancelada" in r2.lower()
    # Recado 054 — sin correo conocido, mismo criterio que arriba.
    assert "te enviamos un correo de confirmación" not in r2.lower()
    assert "enzo" in r2.lower(), "el nombre debe aparecer también en la confirmación de cancelación"


def test_correo_de_confirmacion_tras_reprogramacion_real(monkeypatch):
    monkeypatch.setenv("HRMM_BACKEND_SECRET", "secreto-de-prueba-no-real")
    cita_base = {
        "cita_id": "C1", "slot_id": "SLOT1", "medico_id": "M1", "servicio_id": "S1",
        "fecha": "2026-09-10", "hora_inicio": "09:00", "documento_paciente": "999",
        "nombre_paciente": "", "telefono": "", "estado": "agendada",
        "created_at": "x", "updated_at": "x",
    }

    def generador(method, path, params, json_body, headers):
        if method == "GET" and path == "/api/agenda/servicios":
            return HttpResponse(200, [{"servicio_id": "S1", "nombre": "medicina general"}])
        if method == "GET" and path == "/api/agenda/medicos":
            return HttpResponse(200, [{"medico_id": "M1", "nombre_completo": "Dra. Ana Pérez", "servicio_id": "S1", "consultorio": "Consultorio 3"}])
        if method == "GET" and path == "/api/agenda/disponibilidad":
            return HttpResponse(200, [
                {"slot_id": "SLOT2", "medico_id": "M1", "servicio_id": "S1", "fecha": "2026-09-11", "hora_inicio": "10:00", "hora_fin": "10:30", "estado": "Libre"},
            ])
        if method == "GET" and path == "/api/agenda/citas":
            return HttpResponse(200, [cita_base])
        if method == "POST" and path == "/api/agenda/verificacion/enviar":
            return HttpResponse(200, {"enviado": True, "correo_parcial": "a***@dominio.com"})
        if method == "POST" and path == "/api/agenda/citas/C1/reprogramar":
            assert params["codigo"] == "111222"
            return HttpResponse(200, dict(cita_base, slot_id="SLOT2", fecha="2026-09-11", hora_inicio="10:00", estado="agendada"))
        raise AssertionError(f"no programado en este test: {method} {path} {params}")

    http = FakeHttpClient(generador=generador)
    catalog = CatalogMirror()
    catalog.sync(http)
    service = HrmmAppointmentService(http, catalog)
    gateway = build_health_gateway(MockActivitySource(), service, ReminderManager(), MockActivityResultSink())

    handle_inbound_message(gateway, "999", "demo", "m1", "quiero reprogramar mi cita")
    handle_inbound_message(gateway, "999", "demo", "m2", "la primera")
    r3 = handle_inbound_message(gateway, "999", "demo", "m3", "111222")

    assert "reprogramada" in r3.lower()
    # Recado 054 — sin correo conocido, mismo criterio que arriba.
    assert "te enviamos un correo de confirmación" not in r3.lower()
