"""
Recado 050 — corrige el hallazgo del recado 049: apenas
`gateway.py:_cerrar_si_definitivo` cierra una Activity (reserva
confirmada/reprogramada/declinada), el mensaje SIGUIENTE del paciente ya
no encuentra `find_open_context` y se enruta por `_enrutar_solicitud_
nueva` — un camino que NUNCA conoció el detector centralizado de las 5
categorías de interrupción de contexto del recado 047 (`_PARA_OTRO`,
`_INFO_NO_AUTORIZADA`, `_HUMANO`, `_NO_PUEDE_AHORA`, `_PIDE_INFO`),
porque ese detector vive únicamente dentro de `HealthBrain.interpret()`,
solo alcanzable con una conversación abierta.

Este archivo verifica los 5 puntos pedidos explícitamente:
1. Reproducción EXACTA del caso real del recado 049, punto 1: reserva
   confirmada -> "necesito una cita para mi hija" -> activa el wizard
   de beneficiario en vez de preguntar servicio directo.
2. Reproducción EXACTA del caso real del recado 049, punto 3: reserva
   confirmada -> reclamo tipo "pero es para mi hija y no me
   preguntaste su documento" -> comportamiento diseñado explícitamente
   (informa + remite al flujo de cancelación YA EXISTENTE y protegido
   por código de verificación, nunca una escritura nueva).
3. Una solicitud genuinamente nueva tras el cierre ("necesito otra
   cita de urgencias") sigue funcionando normal, sin verse afectada.
4. Pasada la ventana de gracia (consumida por el primer mensaje
   posterior al cierre), un segundo mensaje que SÍ hubiera calzado con
   una interrupción ya NO la activa — mismo comportamiento de antes.
5. Suite completa sin regresiones (ver comando aparte, no en este
   archivo).
"""
import pytest

from domains.health import (
    MockActivitySource, MockActivityResultSink, ReminderManager,
    build_health_gateway, handle_inbound_message,
)
from domains.health.gateway import find_open_context
from domains.health.hrmm_appointment_service import HrmmAppointmentService
from domains.health.hrmm_catalog import CatalogMirror
from domains.health.hrmm_http import FakeHttpClient, HttpResponse
from domains.health.identity_store import SQLiteIdentidadCanalStore

_TITULAR = "TITULAR-050"
_HIJA_VALIDA = "HIJA-050"
_PACIENTE = "chat-050"


# ---------------------------------------------------------------------
# Fixture: catálogo real de 4 servicios (mismo HRMM real: Medicina
# General, Pediatría, Odontología, Urgencias) — con más de un servicio,
# `_determinar_servicio_inicial` SIEMPRE pregunta primero (recado 030),
# igual que en producción.
# ---------------------------------------------------------------------
def _gateway_multiservicio(monkeypatch):
    monkeypatch.setenv("HRMM_BACKEND_SECRET", "secreto-de-prueba-no-real")
    citas: dict = {}
    codigos_enviados: list = []

    def generador(method, path, params, json_body, headers):
        if method == "GET" and path == "/api/agenda/servicios":
            return HttpResponse(200, [
                {"servicio_id": "S1", "nombre": "Medicina General"},
                {"servicio_id": "S2", "nombre": "Pediatria"},
                {"servicio_id": "S3", "nombre": "Odontologia"},
                {"servicio_id": "S4", "nombre": "Urgencias"},
            ])
        if method == "GET" and path == "/api/agenda/medicos":
            return HttpResponse(200, [
                {"medico_id": "M1", "nombre_completo": "Dra. Medicina", "servicio_id": "S1", "consultorio": "C1"},
                {"medico_id": "M2", "nombre_completo": "Dr. Pediatra", "servicio_id": "S2", "consultorio": "C2"},
                {"medico_id": "M3", "nombre_completo": "Dra. Odonto", "servicio_id": "S3", "consultorio": "C3"},
                {"medico_id": "M4", "nombre_completo": "Dr. Urgencias", "servicio_id": "S4", "consultorio": "C4"},
            ])
        if method == "GET" and path == "/api/agenda/disponibilidad":
            return HttpResponse(200, [
                {"slot_id": "SLOT-S1-1", "medico_id": "M1", "servicio_id": "S1", "fecha": "2026-09-08", "hora_inicio": "08:00", "hora_fin": "08:30", "estado": "Libre"},
                {"slot_id": "SLOT-S2-1", "medico_id": "M2", "servicio_id": "S2", "fecha": "2026-09-08", "hora_inicio": "09:00", "hora_fin": "09:30", "estado": "Libre"},
                {"slot_id": "SLOT-S3-1", "medico_id": "M3", "servicio_id": "S3", "fecha": "2026-09-08", "hora_inicio": "10:00", "hora_fin": "10:30", "estado": "Libre"},
                {"slot_id": "SLOT-S4-1", "medico_id": "M4", "servicio_id": "S4", "fecha": "2026-09-08", "hora_inicio": "11:00", "hora_fin": "11:30", "estado": "Libre"},
            ])
        if method == "GET" and path == "/api/agenda/citas/buscar-paciente":
            documento = params.get("documento")
            if documento == _HIJA_VALIDA:
                return HttpResponse(200, {"nombre_paciente": "Hija de Prueba 050", "telefono": "3000000050"})
            return HttpResponse(404, {"detail": "no encontrado"})
        if method == "POST" and path == "/api/agenda/citas":
            cita_id = f"CITA-050-{len(citas) + 1}"
            citas[cita_id] = {
                "cita_id": cita_id, "slot_id": json_body["slot_id"],
                "medico_id": json_body.get("medico_id", "M2"), "servicio_id": json_body.get("servicio_id", "S2"),
                "fecha": "2026-09-08", "hora_inicio": "09:00",
                "documento_paciente": json_body["documento_paciente"],
                "nombre_paciente": json_body.get("nombre_paciente", ""), "telefono": json_body.get("telefono", ""),
                "estado": "reservada", "created_at": "x", "updated_at": "x",
            }
            return HttpResponse(201, citas[cita_id])
        if method == "GET" and path.startswith("/api/agenda/citas/") and path != "/api/agenda/citas/buscar-paciente":
            cita_id = path.rsplit("/", 1)[-1]
            return HttpResponse(200, citas[cita_id])
        if method == "GET" and path == "/api/agenda/citas":
            doc = params.get("documento_paciente")
            return HttpResponse(200, [c for c in citas.values() if c["documento_paciente"] == doc])
        if method == "POST" and path == "/api/agenda/verificacion/enviar":
            codigos_enviados.append(json_body["documento_paciente"])
            return HttpResponse(200, {"correo_parcial": "t***@ejemplo.com"})
        raise AssertionError(f"no programado en este test: {method} {path} {params} {json_body}")

    http = FakeHttpClient(generador=generador)
    catalog = CatalogMirror()
    catalog.sync(http)
    service = HrmmAppointmentService(http, catalog)
    identity_store = SQLiteIdentidadCanalStore(":memory:")
    gateway = build_health_gateway(
        MockActivitySource(), service, ReminderManager(), MockActivityResultSink(),
        identity_store=identity_store,
    )
    # Paciente ya reconocido (mismo criterio que test_saludo_sin_intencion):
    # se salta el gate de identidad, va directo a `_enrutar_solicitud_nueva`.
    identity_store.marcar_verificado(_PACIENTE, _TITULAR, "Titular Cincuenta")
    return gateway, citas, codigos_enviados


def _reservar_pediatria_para_titular(gateway):
    """Lleva una conversación completa hasta reservar Pediatría para el
    TITULAR (comportamiento por defecto, sin beneficiario) — reproduce
    el estado real ANTES del mensaje problemático del recado 049."""
    r1 = handle_inbound_message(gateway, _PACIENTE, "telegram", "m1", "necesito una cita")
    assert "servicio" in r1.lower()
    r2 = handle_inbound_message(gateway, _PACIENTE, "telegram", "m2", "Pediatria")
    assert "fechas disponibles" in r2.lower()
    r3 = handle_inbound_message(gateway, _PACIENTE, "telegram", "m3", "1")
    assert "horarios disponibles" in r3.lower()
    r4 = handle_inbound_message(gateway, _PACIENTE, "telegram", "m4", "1")
    assert "confirmado" in r4.lower()
    # La Activity ya cerró en este mismo turno (management_status
    # APPOINTMENT_CONFIRMED) — sin la corrección de este recado, la
    # conversación ya no existe para efectos de correlación.
    assert find_open_context(gateway, _PACIENTE) is None
    return r4


# ---------------------------------------------------------------------
# 1. Reproducción EXACTA del caso real, punto 1 del recado 049.
# ---------------------------------------------------------------------
def test_beneficiario_declarado_en_solicitud_nueva_tras_cierre_activa_wizard(monkeypatch):
    gateway, citas, _ = _gateway_multiservicio(monkeypatch)
    _reservar_pediatria_para_titular(gateway)
    assert len(citas) == 1
    assert next(iter(citas.values()))["documento_paciente"] == _TITULAR

    # Mensaje real exacto del recado 049 (parafraseado con el mismo
    # contenido): saludo/cierre + "necesito una cita" (SÍ clasifica
    # también como PROGRAMAR_CITA, no solo como beneficiario) + "para
    # mi hija".
    r5 = handle_inbound_message(gateway, _PACIENTE, "telegram", "m5", "dale gracias, necesito una cita para mi hija")

    assert "documento" in r5.lower(), f"debía activar el wizard de beneficiario; respuesta real: {r5!r}"
    assert "cancelar la cita" not in r5.lower(), (
        f"NO debía tomar la rama de 'reserva ya ejecutada' — este mensaje es sobre una cita NUEVA: {r5!r}"
    )
    # No creó una PatientRequest/Activity de PROGRAMAR_CITA normal
    # (nunca llegó a `_enrutar_solicitud_nueva`) — la respuesta vino
    # del wizard de beneficiario reabierto sobre la Activity cerrada.
    assert len(gateway.patient_request_source.list_for_patient(_PACIENTE)) == 1  # solo la de Pediatría

    # El wizard reabierto SÍ es funcional en el turno siguiente — no es
    # un callejón sin salida de un solo mensaje.
    r6 = handle_inbound_message(gateway, _PACIENTE, "telegram", "m6", _HIJA_VALIDA)
    assert "hija de prueba 050" in r6.lower() and "correcto" in r6.lower()


# ---------------------------------------------------------------------
# 2. Reproducción EXACTA del caso real, punto 3 del recado 049 — el
#    reclamo post-reserva, y la decisión de diseño documentada.
# ---------------------------------------------------------------------
def test_reclamo_sobre_reserva_ya_ejecutada_informa_y_remite_a_cancelar_protegido(monkeypatch):
    gateway, citas, codigos_enviados = _gateway_multiservicio(monkeypatch)
    _reservar_pediatria_para_titular(gateway)
    cita_id_original = next(iter(citas.keys()))

    # Mensaje real exacto del recado 049: reclamo, sin ninguna palabra
    # de "solicitud nueva" (nunca dice "necesito"/"quiero"/"agendar").
    r5 = handle_inbound_message(
        gateway, _PACIENTE, "telegram", "m5",
        "pero es para mi hija y no me pregustastes su documento de identidad",
    )

    assert "cancelar la cita" in r5.lower(), f"debía remitir al flujo de cancelación existente: {r5!r}"
    assert "código de verificación" in r5.lower()
    assert "documento de identidad de la persona" not in r5.lower(), (
        "NO debía arrancar el wizard normal de beneficiario (reservaría una segunda cita "
        f"sin cancelar la primera): {r5!r}"
    )
    # Decisión de diseño clave: NINGUNA escritura nueva contra
    # producción en este turno — la cita original sigue exactamente
    # igual que antes de este mensaje.
    assert citas[cita_id_original]["estado"] == "reservada"
    assert len(citas) == 1
    assert codigos_enviados == []

    # No reabrió ningún wizard — la Activity sigue cerrada.
    assert find_open_context(gateway, _PACIENTE) is None

    # Bonus: la frase exacta que la respuesta le sugiere al paciente
    # ("cancelar la cita") SÍ dispara el flujo real y ya protegido de
    # cancelación (código de verificación) — confirma que el mensaje no
    # remite a un callejón sin salida.
    r6 = handle_inbound_message(gateway, _PACIENTE, "telegram", "m6", "cancelar la cita")
    assert "código" in r6.lower()
    assert codigos_enviados == [_TITULAR]
    # Tampoco esto canceló nada todavía por sí solo — falta el código
    # real que el paciente debería escribir a continuación (fuera de
    # alcance de este test: mismo sub-flujo ya cubierto por otros tests
    # de `_procesar_intento_de_codigo`, sin tocar en este recado).
    assert citas[cita_id_original]["estado"] == "reservada"


# ---------------------------------------------------------------------
# 3. Solicitud genuinamente NUEVA tras el cierre — sin ninguna de las 5
#    categorías — sigue funcionando exactamente igual que siempre.
# ---------------------------------------------------------------------
def test_solicitud_genuinamente_nueva_tras_cierre_no_se_ve_afectada(monkeypatch):
    gateway, citas, _ = _gateway_multiservicio(monkeypatch)
    _reservar_pediatria_para_titular(gateway)
    assert len(gateway.patient_request_source.list_for_patient(_PACIENTE)) == 1

    r5 = handle_inbound_message(gateway, _PACIENTE, "telegram", "m5", "necesito otra cita de urgencias")

    assert "servicio" in r5.lower(), f"debía preguntar servicio, como cualquier solicitud nueva: {r5!r}"
    assert "documento" not in r5.lower()
    assert "cancelar la cita" not in r5.lower()
    # SÍ creó una PatientRequest/Activity nueva — comportamiento normal,
    # sin ningún cambio.
    assert len(gateway.patient_request_source.list_for_patient(_PACIENTE)) == 2
    assert find_open_context(gateway, _PACIENTE) is not None


# ---------------------------------------------------------------------
# 4. Pasada la ventana de gracia (consumida por el primer mensaje
#    posterior, que no coincidió con ninguna interrupción), un segundo
#    mensaje que SÍ hubiera calzado ya NO la activa.
# ---------------------------------------------------------------------
def test_ventana_de_gracia_no_dura_mas_de_un_turno(monkeypatch):
    gateway, citas, _ = _gateway_multiservicio(monkeypatch)
    _reservar_pediatria_para_titular(gateway)

    # Primer mensaje posterior al cierre: saludo puro, sin ninguna de
    # las 5 categorías (consume la ventana de gracia sin activar nada)
    # y sin ninguna intención reconocible tampoco (recado 048:
    # `classify_intent_or_none` devuelve `None` para un saludo puro, así
    # que ni siquiera crea una Activity nueva — a diferencia de un
    # mensaje ambiguo CON contenido, que sí defaultea a PROGRAMAR_CITA).
    r5 = handle_inbound_message(gateway, _PACIENTE, "telegram", "m5", "hola")
    assert "documento" not in r5.lower()
    assert find_open_context(gateway, _PACIENTE) is None

    # Segundo mensaje: AHORA SÍ menciona beneficiario — pero la ventana
    # de gracia ya se consumió en el turno anterior, así que se trata
    # como una solicitud nueva cualquiera (mismo comportamiento de
    # SIEMPRE, el mismo hallazgo original del recado 049 — este
    # recado NUNCA prometió corregirlo más allá del turno inmediato).
    r6 = handle_inbound_message(gateway, _PACIENTE, "telegram", "m6", "es para mi hija")
    assert "documento" not in r6.lower(), (
        f"la ventana de gracia ya debía estar consumida por el turno anterior: {r6!r}"
    )
