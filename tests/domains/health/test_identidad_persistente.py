"""
Persistencia de identidad de canal ENTRE conversaciones (recado 014,
extensión de R-15): `domains/health/identity_store.py` +
requisito #3 del pedido — un teléfono ya VERIFICADO se reconoce de
inmediato en un contacto siguiente, sin repetir el wizard de
documento/código. El wizard en sí (pedir documento -> validar ->
verificar código) está cubierto en `test_identity_gate_chatwoot.py`;
este archivo cubre específicamente el store nuevo y la hidratación
entre "conversaciones"/"procesos" distintos.

Incluye también la política de retención (recado 016, extensión de
R-20): vencimiento automático a `RETENCION_IDENTIDAD_DIAS` (180) días —
la eliminación A PEDIDO del paciente ("olvida mi información") vive en
`test_identidad_olvido.py`, no acá (requiere una conversación abierta y
`HealthBrain`, un escenario distinto del de este archivo).

Sin red real — mismo patrón de FakeHttpClient que el resto de
`tests/domains/health/test_hrmm_*.py` — EXCEPTO `test_identidad_canal_real_e2e`
al final de este archivo, deshabilitada por defecto (mismo patrón que
`test_get_availability_contra_hrmm_backend_real`), gateada por
`ZANTIA_RUN_REAL_HRMM_TESTS`.
"""
import os
import time
from datetime import datetime, timedelta, timezone

import pytest

from domains.health import MockActivitySource, MockActivityResultSink, ReminderManager
from domains.health.gateway import build_health_gateway, handle_inbound_message
from domains.health.hrmm_appointment_service import HrmmAppointmentService
from domains.health.hrmm_catalog import CatalogMirror
from domains.health.hrmm_http import FakeHttpClient, HttpResponse
from domains.health.identity_store import (
    RETENCION_IDENTIDAD_DIAS,
    EstadoIdentidadCanal,
    IdentidadCanal,
    SQLiteIdentidadCanalStore,
    build_identity_store,
)

_TELEFONO = "573001112233"
_DOCUMENTO_VALIDO = "123456789"


@pytest.fixture(autouse=True)
def _secreto_de_prueba(monkeypatch):
    monkeypatch.setenv("HRMM_BACKEND_SECRET", "secreto-de-prueba-no-real")


def _generador(citas_por_documento=None):
    citas_por_documento = citas_por_documento or {}

    def generador(method, path, params, json_body, headers):
        if method == "GET" and path == "/api/agenda/servicios":
            return HttpResponse(200, [{"servicio_id": "S1", "nombre": "medicina general"}])
        if method == "GET" and path == "/api/agenda/medicos":
            return HttpResponse(200, [{"medico_id": "M1", "nombre_completo": "Dra. Ana Pérez", "servicio_id": "S1", "consultorio": "Consultorio 3"}])
        if method == "GET" and path == "/api/agenda/citas/buscar-paciente":
            documento = params.get("documento")
            if documento == _DOCUMENTO_VALIDO:
                return HttpResponse(200, {"nombre_paciente": "Paciente de Prueba", "telefono": _TELEFONO})
            return HttpResponse(404, {"detail": "no encontrado"})
        if method == "GET" and path == "/api/agenda/citas":
            documento = params.get("documento_paciente")
            return HttpResponse(200, citas_por_documento.get(documento, []))
        if method == "POST" and path == "/api/agenda/verificacion/enviar":
            return HttpResponse(200, {"enviado": True, "mensaje": "ok", "correo_parcial": "p***@dominio.com"})
        if method == "POST" and path == "/api/agenda/verificacion/confirmar":
            if json_body.get("codigo") == "654321":
                return HttpResponse(200, {"valido": True})
            return HttpResponse(401, {"detail": "codigo invalido o vencido"})
        raise AssertionError(f"no programado en este test: {method} {path} {params}")

    return generador


def _build_gateway(identity_store, citas_por_documento=None):
    http = FakeHttpClient(generador=_generador(citas_por_documento))
    catalog = CatalogMirror()
    catalog.sync(http)
    service = HrmmAppointmentService(http, catalog)
    return build_health_gateway(
        MockActivitySource(), service, ReminderManager(), MockActivityResultSink(),
        identity_store=identity_store,
    )


# ---------------------------------------------------------------------
# Smoke test del store en sí (regla obligatoria de testing.md: todo
# componente nuevo nace con al menos un smoke test).
# ---------------------------------------------------------------------
def test_sqlite_identidad_canal_store_smoke():
    store = SQLiteIdentidadCanalStore(":memory:")
    assert store.get(_TELEFONO) is None

    pendiente = store.guardar_pendiente(_TELEFONO, _DOCUMENTO_VALIDO)
    assert pendiente.estado == EstadoIdentidadCanal.PENDIENTE_VERIFICACION
    assert pendiente.verificado_en is None
    assert store.get(_TELEFONO).estado == EstadoIdentidadCanal.PENDIENTE_VERIFICACION

    verificado = store.marcar_verificado(_TELEFONO, _DOCUMENTO_VALIDO)
    assert verificado.estado == EstadoIdentidadCanal.VERIFICADO
    assert verificado.verificado_en is not None
    registro = store.get(_TELEFONO)
    assert registro.estado == EstadoIdentidadCanal.VERIFICADO
    assert registro.documento == _DOCUMENTO_VALIDO
    assert registro.verificado_en is not None


def test_build_identity_store_usa_env_var_o_cae_a_memoria(monkeypatch, tmp_path):
    monkeypatch.delenv("ZANTIA_IDENTIDAD_DB_PATH", raising=False)
    store_memoria = build_identity_store()
    assert store_memoria._db_path == ":memory:"

    ruta = str(tmp_path / "identidad.db")
    monkeypatch.setenv("ZANTIA_IDENTIDAD_DB_PATH", ruta)
    store_archivo = build_identity_store()
    assert store_archivo._db_path == ruta
    # Sobrevive un "reinicio" real: nueva instancia, mismo archivo.
    store_archivo.marcar_verificado(_TELEFONO, _DOCUMENTO_VALIDO)
    store_archivo.close()
    reabierto = build_identity_store()
    assert reabierto.get(_TELEFONO).estado == EstadoIdentidadCanal.VERIFICADO


def test_sqlite_identidad_canal_store_crea_el_directorio_padre_si_falta(tmp_path):
    """Recado 029 (preparación para un volumen persistente real en
    EasyPanel): mismo criterio que `state/store.py:SQLiteStateStore`
    (recado 021, R-22) — `sqlite3.connect` NO crea directorios
    intermedios por sí solo. Sin este `mkdir`, apuntar
    `ZANTIA_IDENTIDAD_DB_PATH` a una carpeta que todavía no existe
    (ej. un subdirectorio dentro del volumen recién montado) revienta
    con un error críptico en el primer arranque real."""
    ruta = tmp_path / "carpeta_nueva" / "identidad.db"
    assert not ruta.parent.exists()

    store = SQLiteIdentidadCanalStore(str(ruta))
    try:
        assert ruta.parent.is_dir()
        store.marcar_verificado(_TELEFONO, _DOCUMENTO_VALIDO)
        assert ruta.exists()
    finally:
        store.close()


# ---------------------------------------------------------------------
# Hidratación en handle_inbound_message (requisito #3 del pedido).
# ---------------------------------------------------------------------
def test_contacto_siguiente_con_identidad_verificada_no_pide_nada():
    store = SQLiteIdentidadCanalStore(":memory:")
    store.marcar_verificado(_TELEFONO, _DOCUMENTO_VALIDO)

    # Gateway "nuevo" (simula un proceso recién levantado) que solo
    # comparte el store persistente, nunca el estado en memoria.
    gateway = _build_gateway(store, citas_por_documento={_DOCUMENTO_VALIDO: []})
    assert _TELEFONO not in gateway._identidad_resuelta  # nada en memoria todavía

    respuesta = handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m1", "quiero consultar mi cita")

    assert "documento" not in respuesta.lower()
    assert "código" not in respuesta.lower()
    assert "no tienes ninguna cita" in respuesta.lower()
    assert gateway._identidad_resuelta[_TELEFONO] == _DOCUMENTO_VALIDO
    assert _TELEFONO not in gateway._pending_identity


def test_dos_gateways_distintos_comparten_identidad_via_store(tmp_path, monkeypatch):
    """Simula dos "procesos" (dos instancias de HealthGateway) contra el
    MISMO archivo SQLite — la identidad verificada en el primero debe
    reconocerse en el segundo sin repetir el wizard."""
    ruta = str(tmp_path / "identidad.db")
    monkeypatch.setenv("ZANTIA_IDENTIDAD_DB_PATH", ruta)

    proceso_1 = _build_gateway(build_identity_store(), citas_por_documento={_DOCUMENTO_VALIDO: []})
    handle_inbound_message(proceso_1, _TELEFONO, "chatwoot", "m1", "hola quiero una cita")
    handle_inbound_message(proceso_1, _TELEFONO, "chatwoot", "m2", _DOCUMENTO_VALIDO)
    respuesta_codigo = handle_inbound_message(proceso_1, _TELEFONO, "chatwoot", "m3", "654321")
    assert "confirmé tu identidad" in respuesta_codigo.lower()

    # "Reinicio del proceso": store nuevo apuntando al mismo archivo,
    # gateway nuevo, CERO estado en memoria compartido con proceso_1.
    proceso_2 = _build_gateway(build_identity_store(), citas_por_documento={_DOCUMENTO_VALIDO: []})
    respuesta_final = handle_inbound_message(proceso_2, _TELEFONO, "chatwoot", "m4", "quiero consultar mi cita")

    assert "documento" not in respuesta_final.lower()
    assert "no tienes ninguna cita" in respuesta_final.lower()
    assert proceso_2._identidad_resuelta[_TELEFONO] == _DOCUMENTO_VALIDO


# ---------------------------------------------------------------------
# Recado 085/R-21 — hallazgo real GRAVE: una reserva confirmada por chat
# NUNCA disparaba el correo real de confirmación, porque `buscar_paciente`
# (el único dato de contacto que el wizard consultaba) no expone
# `correo` (`PacienteBuscado`, schema real de hrmm-backend — solo
# nombre_paciente/telefono, por privacidad). El correo SÍ existe del
# lado de hrmm-backend y SÍ se expone vía `GET /api/agenda/citas`
# (`Cita.correo`, trusted) — mismo endpoint que `get_patient_appointments`
# ya usa. `HrmmAppointmentService.correo_conocido` replica la MISMA
# técnica que hrmm-backend usa internamente para `enviar_codigo_verificacion`
# (`next((c.correo for c in citas if c.correo), None)`) del lado de
# ZANTIA. Estos 2 tests confirman: (1) el correo se captura y persiste
# en `identity_store` al verificar identidad, igual que `nombre`
# (recado 034); (2) `book_appointment` incluye ese correo en el payload
# real hacia hrmm-backend — tanto en la creación de la cita
# (`CitaCreate.correo`, antes SIEMPRE ausente) como en el segundo paso
# de envío de confirmación (`enviar_confirmacion_email`).
# ---------------------------------------------------------------------
def test_correo_real_se_captura_y_persiste_tras_verificar_identidad():
    store = SQLiteIdentidadCanalStore(":memory:")
    cita_previa = {
        "cita_id": "CITA-PREVIA-1", "documento_paciente": _DOCUMENTO_VALIDO,
        "nombre_paciente": "Paciente de Prueba", "telefono": _TELEFONO,
        "correo": "paciente.real@example.com", "estado": "atendida",
        "servicio_id": "S1", "medico_id": "M1", "fecha": "2026-01-01", "hora_inicio": "08:00",
    }
    gateway = _build_gateway(store, citas_por_documento={_DOCUMENTO_VALIDO: [cita_previa]})

    handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m1", "hola")
    handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m2", _DOCUMENTO_VALIDO)
    respuesta_codigo = handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m3", "654321")
    assert "confirmé tu identidad" in respuesta_codigo.lower()

    registro = store.get(_TELEFONO)
    assert registro is not None
    assert registro.correo == "paciente.real@example.com"


def test_book_appointment_incluye_el_correo_conocido_en_el_payload_real():
    store = SQLiteIdentidadCanalStore(":memory:")
    cita_previa = {
        "cita_id": "CITA-PREVIA-2", "documento_paciente": _DOCUMENTO_VALIDO,
        "nombre_paciente": "Paciente de Prueba", "telefono": _TELEFONO,
        "correo": "paciente.real@example.com", "estado": "atendida",
        "servicio_id": "S1", "medico_id": "M1", "fecha": "2026-01-01", "hora_inicio": "08:00",
    }

    payloads_creacion = []

    def generador(method, path, params, json_body, headers):
        if method == "GET" and path == "/api/agenda/servicios":
            return HttpResponse(200, [{"servicio_id": "S1", "nombre": "medicina general"}])
        if method == "GET" and path == "/api/agenda/medicos":
            return HttpResponse(200, [{"medico_id": "M1", "nombre_completo": "Dra. Ana Pérez", "servicio_id": "S1", "consultorio": "Consultorio 3"}])
        if method == "GET" and path == "/api/agenda/citas/buscar-paciente":
            if params.get("documento") == _DOCUMENTO_VALIDO:
                return HttpResponse(200, {"nombre_paciente": "Paciente de Prueba", "telefono": _TELEFONO})
            return HttpResponse(404, {"detail": "no encontrado"})
        if method == "GET" and path == "/api/agenda/citas":
            documento = params.get("documento_paciente")
            return HttpResponse(200, [cita_previa] if documento == _DOCUMENTO_VALIDO else [])
        if method == "POST" and path == "/api/agenda/verificacion/enviar":
            return HttpResponse(200, {"enviado": True, "mensaje": "ok", "correo_parcial": "p***@dominio.com"})
        if method == "POST" and path == "/api/agenda/verificacion/confirmar":
            return HttpResponse(200, {"valido": json_body.get("codigo") == "654321"})
        if method == "GET" and path == "/api/agenda/disponibilidad":
            return HttpResponse(200, [
                {"slot_id": "SLOT1", "medico_id": "M1", "servicio_id": "S1", "fecha": "2026-09-20", "hora_inicio": "09:00", "hora_fin": "09:30", "estado": "Libre"},
            ])
        if method == "POST" and path == "/api/agenda/citas":
            payloads_creacion.append(json_body)
            return HttpResponse(201, {
                "cita_id": "CITA-NUEVA-1", "slot_id": json_body["slot_id"], "medico_id": "M1",
                "servicio_id": "S1", "fecha": "2026-09-20", "hora_inicio": "09:00",
                "documento_paciente": json_body["documento_paciente"], "nombre_paciente": "Paciente de Prueba",
                "telefono": _TELEFONO, "correo": json_body.get("correo"), "estado": "agendada",
            })
        if method == "POST" and path.endswith("/enviar-confirmacion"):
            return HttpResponse(200, {"exito": True, "estado": "enviado", "mensaje": "ok"})
        if method == "GET" and path == "/api/agenda/citas/CITA-NUEVA-1":
            return HttpResponse(200, {
                "cita_id": "CITA-NUEVA-1", "slot_id": "SLOT1", "medico_id": "M1",
                "servicio_id": "S1", "fecha": "2026-09-20", "hora_inicio": "09:00",
                "documento_paciente": _DOCUMENTO_VALIDO, "nombre_paciente": "Paciente de Prueba",
                "telefono": _TELEFONO, "correo": "paciente.real@example.com", "estado": "confirmada",
            })
        raise AssertionError(f"no programado en este test: {method} {path} {params}")

    http = FakeHttpClient(generador=generador)
    catalog = CatalogMirror()
    catalog.sync(http)
    service = HrmmAppointmentService(http, catalog)
    gateway = build_health_gateway(
        MockActivitySource(), service, ReminderManager(), MockActivityResultSink(), identity_store=store,
    )

    handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m1", "necesito una cita")
    handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m2", _DOCUMENTO_VALIDO)
    handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m3", "654321")
    handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m4", "1")  # elige la fecha (único día disponible)
    handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m5", "1")  # elige el horario
    respuesta_reserva = handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m6", "1")  # confirma

    assert "confirmado" in respuesta_reserva.lower()
    assert len(payloads_creacion) == 1, f"debía crear exactamente 1 cita: {payloads_creacion!r}"
    assert payloads_creacion[0]["correo"] == "paciente.real@example.com", (
        f"el correo real conocido no llegó al payload de creación de la cita: {payloads_creacion[0]!r}"
    )


# ---------------------------------------------------------------------
# Recado 086 — hallazgo real GRAVE, reportado por un paciente real
# (documento 72302972): una identidad ya VERIFICADA de ANTES del recado
# 085 (wizard completo, sin `correo`) nunca vuelve a pasar por
# `marcar_verificado` mientras siga vigente (reconocimiento automático,
# `registro.vigente()`) — quedaba con `correo: None` PARA SIEMPRE, sin
# importar que el fix del recado 085 ya estuviera desplegado. Corregido
# con backfill transparente en `_correo_conocido`: si el registro existe
# pero sin correo, se intenta obtener AHORA (mismo `correo_conocido` de
# siempre) y se persiste vía el nuevo `identity_store.actualizar_correo`
# — sin ningún paso conversacional de más para el paciente.
# ---------------------------------------------------------------------
def test_actualizar_correo_solo_toca_la_columna_correo():
    """Smoke test del método nuevo — a diferencia de `marcar_verificado`,
    NUNCA toca `estado`/`verificado_en`/`nombre` (no reinicia la
    ventana de retención de 180 días solo porque se hizo backfill)."""
    store = SQLiteIdentidadCanalStore(":memory:")
    store.marcar_verificado(_TELEFONO, _DOCUMENTO_VALIDO, "Paciente de Prueba")
    antes = store.get(_TELEFONO)
    assert antes.correo is None

    store.actualizar_correo(_TELEFONO, "backfill@example.com")

    despues = store.get(_TELEFONO)
    assert despues.correo == "backfill@example.com"
    assert despues.nombre == antes.nombre
    assert despues.estado == antes.estado
    assert despues.verificado_en == antes.verificado_en  # ventana de 180 días intacta


def test_actualizar_correo_es_no_op_si_la_fila_no_existe():
    store = SQLiteIdentidadCanalStore(":memory:")
    store.actualizar_correo("nunca-registrado", "x@example.com")  # no debe lanzar
    assert store.get("nunca-registrado") is None


def test_correo_conocido_gateway_hace_backfill_transparente_sobre_identidad_ya_verificada():
    """Reproduce EXACTO el hallazgo real: identidad marcada VERIFICADO
    SIN correo (simula una fila persistida antes del recado 085) — un
    paciente reconocido automáticamente (sin wizard) reserva de una,
    el correo se completa solo y queda persistido para la próxima vez."""
    store = SQLiteIdentidadCanalStore(":memory:")
    store.marcar_verificado(_TELEFONO, _DOCUMENTO_VALIDO, "Paciente de Prueba")  # SIN correo, a propósito
    assert store.get(_TELEFONO).correo is None

    cita_previa = {
        "cita_id": "CITA-PREVIA-3", "documento_paciente": _DOCUMENTO_VALIDO,
        "nombre_paciente": "Paciente de Prueba", "telefono": _TELEFONO,
        "correo": "backfill.real@example.com", "estado": "atendida",
        "servicio_id": "S1", "medico_id": "M1", "fecha": "2026-01-01", "hora_inicio": "08:00",
    }
    payloads_creacion = []

    def generador(method, path, params, json_body, headers):
        if method == "GET" and path == "/api/agenda/servicios":
            return HttpResponse(200, [{"servicio_id": "S1", "nombre": "medicina general"}])
        if method == "GET" and path == "/api/agenda/medicos":
            return HttpResponse(200, [{"medico_id": "M1", "nombre_completo": "Dra. Ana Pérez", "servicio_id": "S1", "consultorio": "Consultorio 3"}])
        if method == "GET" and path == "/api/agenda/citas":
            documento = params.get("documento_paciente")
            return HttpResponse(200, [cita_previa] if documento == _DOCUMENTO_VALIDO else [])
        if method == "GET" and path == "/api/agenda/disponibilidad":
            return HttpResponse(200, [
                {"slot_id": "SLOT1", "medico_id": "M1", "servicio_id": "S1", "fecha": "2026-09-20", "hora_inicio": "09:00", "hora_fin": "09:30", "estado": "Libre"},
            ])
        if method == "POST" and path == "/api/agenda/citas":
            payloads_creacion.append(json_body)
            return HttpResponse(201, {
                "cita_id": "CITA-NUEVA-BF", "slot_id": json_body["slot_id"], "medico_id": "M1",
                "servicio_id": "S1", "fecha": "2026-09-20", "hora_inicio": "09:00",
                "documento_paciente": json_body["documento_paciente"], "nombre_paciente": "Paciente de Prueba",
                "telefono": _TELEFONO, "correo": json_body.get("correo"), "estado": "agendada",
            })
        if method == "GET" and path == "/api/agenda/citas/CITA-NUEVA-BF":
            return HttpResponse(200, {
                "cita_id": "CITA-NUEVA-BF", "slot_id": "SLOT1", "medico_id": "M1", "servicio_id": "S1",
                "fecha": "2026-09-20", "hora_inicio": "09:00", "documento_paciente": _DOCUMENTO_VALIDO,
                "nombre_paciente": "Paciente de Prueba", "telefono": _TELEFONO,
                "correo": "backfill.real@example.com", "estado": "confirmada",
            })
        if method == "POST" and path == "/api/agenda/citas/CITA-NUEVA-BF/enviar-confirmacion":
            return HttpResponse(200, {"exito": True, "estado": "enviado", "mensaje": "ok"})
        raise AssertionError(f"no programado en este test: {method} {path} {params}")

    http = FakeHttpClient(generador=generador)
    catalog = CatalogMirror()
    catalog.sync(http)
    service = HrmmAppointmentService(http, catalog)
    gateway = build_health_gateway(
        MockActivitySource(), service, ReminderManager(), MockActivityResultSink(), identity_store=store,
    )

    # Reconocido de una — SIN wizard, SIN preguntarle nada de más al
    # paciente (transparente, requisito explícito del usuario).
    respuesta = handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m1", "reservar")
    respuesta = handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m2", "1")
    respuesta = handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m3", "1")

    assert "documento" not in respuesta.lower(), "no debía pedir el wizard de nuevo — identidad ya vigente"
    assert "confirmado" in respuesta.lower()
    assert payloads_creacion[0]["correo"] == "backfill.real@example.com"
    assert "el correo de reserva fue enviado a tu correo" in respuesta.lower()

    # El backfill quedó persistido — la PRÓXIMA vez ya no hace falta
    # ninguna llamada extra a `correo_conocido`.
    assert store.get(_TELEFONO).correo == "backfill.real@example.com"


def test_identidad_pendiente_no_verificada_no_se_reconoce():
    """Una fila PENDIENTE_VERIFICACION (wizard interrumpido antes del
    código) nunca se trata como confiable — solo VERIFICADO hidrata
    `_identidad_resuelta`."""
    store = SQLiteIdentidadCanalStore(":memory:")
    store.guardar_pendiente(_TELEFONO, _DOCUMENTO_VALIDO)

    gateway = _build_gateway(store, citas_por_documento={_DOCUMENTO_VALIDO: []})
    respuesta = handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m1", "hola quiero una cita")

    assert "documento" in respuesta.lower()
    assert _TELEFONO not in gateway._identidad_resuelta


# ---------------------------------------------------------------------
# Retención (recado 016, extensión de R-20, requisito #1) — vencimiento
# automático a RETENCION_IDENTIDAD_DIAS (180) días.
# ---------------------------------------------------------------------
def _insertar_fila_con_antiguedad(store: SQLiteIdentidadCanalStore, telefono: str, documento: str, dias: int) -> None:
    """Escribe directamente en la tabla con un `verificado_en` en el
    pasado — `marcar_verificado` siempre usa "ahora", así que simular
    una fila VIEJA requiere ir al `_conn` interno (aceptable en un test,
    mismo criterio que otros tests que llegan a atributos internos del
    store/gateway, ej. `gateway._pending_identity`)."""
    verificado_en = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()
    store._conn.execute(
        "INSERT INTO identidad_canal (telefono, documento, estado, verificado_en) VALUES (?, ?, ?, ?)",
        (telefono, documento, EstadoIdentidadCanal.VERIFICADO.value, verificado_en),
    )
    store._conn.commit()


def test_identidad_dentro_de_la_ventana_es_vigente():
    ahora = datetime.now(timezone.utc)
    reciente = IdentidadCanal(_TELEFONO, _DOCUMENTO_VALIDO, EstadoIdentidadCanal.VERIFICADO, ahora - timedelta(days=100))
    assert reciente.vigente(ahora=ahora) is True


def test_identidad_vencida_no_es_vigente():
    ahora = datetime.now(timezone.utc)
    vencida = IdentidadCanal(
        _TELEFONO, _DOCUMENTO_VALIDO, EstadoIdentidadCanal.VERIFICADO,
        ahora - timedelta(days=RETENCION_IDENTIDAD_DIAS + 1),
    )
    assert vencida.vigente(ahora=ahora) is False


def test_pendiente_verificacion_nunca_es_vigente():
    pendiente = IdentidadCanal(_TELEFONO, _DOCUMENTO_VALIDO, EstadoIdentidadCanal.PENDIENTE_VERIFICACION, None)
    assert pendiente.vigente() is False


def test_identidad_reciente_se_reconoce_automaticamente_via_gateway():
    """Verificación #1 del pedido: dentro de la ventana, se reconoce sin
    pedir nada de nuevo."""
    store = SQLiteIdentidadCanalStore(":memory:")
    _insertar_fila_con_antiguedad(store, _TELEFONO, _DOCUMENTO_VALIDO, dias=100)

    gateway = _build_gateway(store, citas_por_documento={_DOCUMENTO_VALIDO: []})
    respuesta = handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m1", "quiero consultar mi cita")

    assert "documento" not in respuesta.lower()
    assert "no tienes ninguna cita" in respuesta.lower()
    assert gateway._identidad_resuelta[_TELEFONO] == _DOCUMENTO_VALIDO


def test_identidad_vencida_dispara_wizard_completo_de_nuevo():
    """Verificación #2 del pedido: vencida, se trata como si no
    existiera — wizard completo, SIN mensaje especial de "tu identidad
    venció" (requisito #1.2, deliberadamente simple)."""
    store = SQLiteIdentidadCanalStore(":memory:")
    _insertar_fila_con_antiguedad(store, _TELEFONO, _DOCUMENTO_VALIDO, dias=RETENCION_IDENTIDAD_DIAS + 1)

    gateway = _build_gateway(store, citas_por_documento={_DOCUMENTO_VALIDO: []})
    respuesta = handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m1", "hola quiero una cita")

    assert "documento" in respuesta.lower()
    assert "venció" not in respuesta.lower() and "vencio" not in respuesta.lower()
    assert _TELEFONO not in gateway._identidad_resuelta


def test_reverificacion_tras_vencimiento_actualiza_sin_duplicar_fila():
    """Verificación #3 del pedido: re-verificación exitosa tras
    vencimiento actualiza `verificado_en` (UPSERT), no crea una fila
    duplicada."""
    store = SQLiteIdentidadCanalStore(":memory:")
    _insertar_fila_con_antiguedad(store, _TELEFONO, _DOCUMENTO_VALIDO, dias=RETENCION_IDENTIDAD_DIAS + 1)

    gateway = _build_gateway(store, citas_por_documento={_DOCUMENTO_VALIDO: []})
    handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m1", "hola quiero una cita")
    handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m2", _DOCUMENTO_VALIDO)
    respuesta = handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m3", "654321")

    assert "confirmé tu identidad" in respuesta.lower()
    registro = store.get(_TELEFONO)
    assert registro.estado == EstadoIdentidadCanal.VERIFICADO
    assert registro.vigente()

    cur = store._conn.execute("SELECT COUNT(*) FROM identidad_canal WHERE telefono = ?", (_TELEFONO,))
    assert cur.fetchone()[0] == 1


# ---------------------------------------------------------------------
# Prueba real de extremo a extremo (recado 015, 2026-09-02) — contra la
# ÚNICA red disponible de hrmm-backend (producción, sin staging — R-7).
# Deshabilitada por defecto, mismo patrón que
# test_get_availability_contra_hrmm_backend_real
# (tests/domains/health/test_hrmm_appointment_service.py). MANUAL e
# INTERACTIVA a propósito: el código de verificación se envía por correo
# REAL y ningún agente puede leerlo por sí mismo — se pide con `input()`,
# dos veces (identidad + limpieza), a quien corra `pytest -s` a mano.
# ---------------------------------------------------------------------
@pytest.mark.skipif(
    os.environ.get("ZANTIA_RUN_REAL_HRMM_TESTS") != "1",
    reason="Prueba de red real contra hrmm-backend deshabilitada por defecto — ver recado 015.",
)
def test_identidad_canal_real_e2e():
    """Extremo a extremo, contra producción real de hrmm-backend: envía un
    código real por correo, lo confirma vía `POST /api/agenda/verificacion/confirmar`
    (recado 015), verifica que `identity_store` queda VERIFICADO, y confirma
    que un segundo `HealthGateway` ("otro proceso") reconoce la identidad de
    inmediato sin repetir el wizard (requisito #3, recado 014) — todo contra
    infraestructura real, no `FakeHttpClient`.

    Variables de entorno requeridas (nunca hardcodeadas, ver `.env.example`):
    - `ZANTIA_RUN_REAL_HRMM_TESTS=1` (gate explícito).
    - `HRMM_BACKEND_URL`, `HRMM_BACKEND_SECRET` (reales).
    - `ZANTIA_TEST_CORREO_REAL`: un correo que la persona que corre el test
      pueda revisar EN VIVO — recibe 2 códigos reales durante esta prueba.

    Correr con `pytest -s` (sin `-s`, `input()` no puede leer del teclado).

    Documento de prueba: `ZANTIA-TEST-IDENTIDAD-<epoch>` — claramente
    marcado, nunca un paciente real. Requiere una cita real mínima para que
    `verificacion/enviar` tenga un correo a dónde mandar el código — creada
    con una llamada HTTP directa (no `HrmmAppointmentService.book_appointment`,
    que NO envía `correo` en el body — hallazgo de esta sesión, ver
    `.ai/RISKS.md` R-21) y CANCELADA al final (limpieza real, mismo rigor
    que `_cancelar_trusted` en la suite de hrmm-backend)."""
    from domains.health.hrmm_http import RealHttpClient
    from domains.health.models import AppointmentStatus

    correo_real = os.environ.get("ZANTIA_TEST_CORREO_REAL")
    if not correo_real:
        pytest.skip("ZANTIA_TEST_CORREO_REAL no configurado — requerido para recibir los códigos reales.")

    base_url = os.environ["HRMM_BACKEND_URL"]
    http_real = RealHttpClient(base_url)
    catalog_real = CatalogMirror()
    catalog_real.sync(http_real)
    servicio_real = next(iter(catalog_real._servicios.values())).nombre

    documento = f"ZANTIA-TEST-IDENTIDAD-{int(time.time())}"
    telefono = f"5730000{int(time.time()) % 10000:04d}"

    service = HrmmAppointmentService(http_real, catalog_real)

    opciones = service.get_availability(servicio_real)
    assert opciones, "Sin disponibilidad real para el servicio elegido — no se puede montar la prueba."
    slot = opciones[0]
    respuesta_cita = http_real.request(
        "POST", "/api/agenda/citas",
        json_body={
            "slot_id": slot.slot_id, "documento_paciente": documento,
            "nombre_paciente": "ZANTIA TEST IDENTIDAD", "telefono": telefono,
            "correo": correo_real, "canal": "zantia-test",
        },
    )
    assert respuesta_cita.status == 201, respuesta_cita.body
    cita_id = respuesta_cita.body["cita_id"]

    identity_store = SQLiteIdentidadCanalStore(":memory:")
    gateway = build_health_gateway(
        MockActivitySource(), service, ReminderManager(), MockActivityResultSink(),
        identity_store=identity_store,
    )

    try:
        r1 = handle_inbound_message(gateway, telefono, "chatwoot", "m1", "hola")
        assert "documento" in r1.lower()

        r2 = handle_inbound_message(gateway, telefono, "chatwoot", "m2", documento)
        assert "código" in r2.lower(), r2
        assert identity_store.get(telefono).estado == EstadoIdentidadCanal.PENDIENTE_VERIFICACION

        codigo_real = input(
            f"\n>>> Revisa {correo_real} y escribe el código de 6 dígitos recibido: "
        ).strip()

        r3 = handle_inbound_message(gateway, telefono, "chatwoot", "m3", codigo_real)
        assert "confirmé tu identidad" in r3.lower(), r3

        registro = identity_store.get(telefono)
        assert registro is not None
        assert registro.estado == EstadoIdentidadCanal.VERIFICADO
        assert registro.documento == documento
        assert registro.verificado_en is not None

        # Segundo gateway ("otro proceso"), mismo identity_store — confirma
        # reconocimiento inmediato contra infraestructura real (requisito
        # #3 del pedido original, recado 014), no solo con FakeHttpClient.
        gateway_2 = build_health_gateway(
            MockActivitySource(), service, ReminderManager(), MockActivityResultSink(),
            identity_store=identity_store,
        )
        r4 = handle_inbound_message(gateway_2, telefono, "chatwoot", "m4", "quiero consultar mi cita")
        assert "documento" not in r4.lower(), r4
    finally:
        # Limpieza real (mismo rigor que el resto de la suite de
        # hrmm-backend): cancela la cita de prueba. Requiere OTRO código
        # real — el usado arriba ya está consumido (un solo uso).
        service.send_verification_code(documento)
        codigo_limpieza = input(
            f"\n>>> LIMPIEZA: revisa {correo_real} de nuevo y escribe el código para "
            f"cancelar la cita de prueba {cita_id}: "
        ).strip()
        cancelada = service.cancel_appointment_verified(cita_id, documento, codigo_limpieza)
        assert cancelada.status == AppointmentStatus.CANCELLED, cancelada
