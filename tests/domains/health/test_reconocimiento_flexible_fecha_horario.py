"""
Recado 051 — reconocimiento flexible de fecha/horario, pedido explícito
del usuario, mismo principio que la tolerancia a errores de tipeo de
servicio (recado 036): antes de esto, `_interpretar_fecha`/
`_interpretar_horario` SOLO reconocían el ordinal de la opción ofrecida
("1"/"primera") — un paciente real que repitiera la fecha/hora TAL CUAL
se la mostraron ("7 de septiembre", "el lunes", "lunes 7", "7 am") se
quedaba atascado repitiendo el mismo mensaje de aclaración sin poder
avanzar (bug real confirmado en producción).

Este archivo verifica los 5 puntos pedidos explícitamente:
1. Las 3 fechas reales del catálogo, cada una respondida de 4 formas:
   ordinal, día de semana solo, número de día solo, fecha completa tal
   cual se mostró.
2. Mismo test para horarios: texto completo ("07:00"), hora sola ("8"),
   forma con meridiano ("7 am").
3. Caso ambiguo forzado (dos horarios de la misma hora, minutos
   distintos, respondidos con la hora sola) — confirma que pide
   aclaración en vez de adivinar. Para fecha, un caso ambiguo
   construido a nivel de unidad (dos fechas reales del mismo día de
   semana) — no se pudo reproducir a través del flujo completo con el
   catálogo real de 3 fechas consecutivas (nunca ambiguo hoy, tal como
   advirtió el propio pedido), así que se prueba `_emparejar_fecha_por_
   texto` directo, mismo criterio que otros tests de este archivo que
   llaman funciones internas directo (ver `test_interrupciones_en_
   cualquier_etapa.py`).
4. El fallback normal (texto no reconocido en ninguna forma) sigue
   funcionando igual — variantes rotativas del recado 034, sin cambios.
5. Suite completa sin regresiones (ver comando aparte, no en este
   archivo).
"""
import pytest

from domains.health import (
    MockActivitySource, MockActivityResultSink, ReminderManager,
    build_health_agent_context, contact_patient, handle_patient_message,
)
from domains.health.agent import accept_activity
from domains.health.brain import _emparejar_fecha_por_texto, _formatear_fecha_humana
from domains.health.hrmm_appointment_service import HrmmAppointmentService
from domains.health.hrmm_catalog import CatalogMirror
from domains.health.hrmm_http import FakeHttpClient, HttpResponse
from domains.health.models import Activity

_TITULAR = "TITULAR-051"

# Catálogo controlado: 3 fechas reales, días de semana distintos
# (Lunes/Martes/Miércoles) — el mismo tipo de catálogo que ya ofrece
# producción (máximo 3 fechas, `_ofrecer_fechas`). El Lunes tiene DOS
# horarios de la misma hora con minutos distintos (08:00/08:30) —
# construido a propósito para poder probar el caso ambiguo real del
# punto 3 (responder "8" sola) sin afectar los otros tests (que usan
# "08:00" completo, siempre inequívoco).
_FECHA_LUNES = "2026-09-07"
_FECHA_MARTES = "2026-09-08"
_FECHA_MIERCOLES = "2026-09-09"


def _generador(citas=None):
    citas = citas if citas is not None else {}

    def generador(method, path, params, json_body, headers):
        if method == "GET" and path == "/api/agenda/servicios":
            return HttpResponse(200, [{"servicio_id": "S1", "nombre": "Pediatria"}])
        if method == "GET" and path == "/api/agenda/medicos":
            return HttpResponse(200, [
                {"medico_id": "M1", "nombre_completo": "Dr. Pediatra", "servicio_id": "S1", "consultorio": "Consultorio 1"},
            ])
        if method == "GET" and path == "/api/agenda/disponibilidad":
            return HttpResponse(200, [
                {"slot_id": "SLOT-LUN-0800", "medico_id": "M1", "servicio_id": "S1", "fecha": _FECHA_LUNES, "hora_inicio": "08:00", "hora_fin": "08:30", "estado": "Libre"},
                {"slot_id": "SLOT-LUN-0830", "medico_id": "M1", "servicio_id": "S1", "fecha": _FECHA_LUNES, "hora_inicio": "08:30", "hora_fin": "09:00", "estado": "Libre"},
                {"slot_id": "SLOT-MAR-0900", "medico_id": "M1", "servicio_id": "S1", "fecha": _FECHA_MARTES, "hora_inicio": "09:00", "hora_fin": "09:30", "estado": "Libre"},
                {"slot_id": "SLOT-MIE-1000", "medico_id": "M1", "servicio_id": "S1", "fecha": _FECHA_MIERCOLES, "hora_inicio": "10:00", "hora_fin": "10:30", "estado": "Libre"},
            ])
        if method == "GET" and path == "/api/agenda/citas/buscar-paciente":
            return HttpResponse(404, {"detail": "no encontrado"})
        if method == "POST" and path == "/api/agenda/citas":
            cita_id = f"CITA-051-{len(citas) + 1}"
            citas[cita_id] = {
                "cita_id": cita_id, "slot_id": json_body["slot_id"], "medico_id": "M1", "servicio_id": "S1",
                "fecha": _FECHA_LUNES, "hora_inicio": "08:00",
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
        raise AssertionError(f"no programado en este test: {method} {path} {params}")

    return generador, citas


def _nuevo_contexto(monkeypatch):
    monkeypatch.setenv("HRMM_BACKEND_SECRET", "secreto-de-prueba-no-real")
    generador, citas = _generador()
    http = FakeHttpClient(generador=generador)
    catalog = CatalogMirror()
    catalog.sync(http)
    service = HrmmAppointmentService(http, catalog)
    source = MockActivitySource()
    activity = source.create(Activity(
        activity_id=f"ACT-051-{id(http)}", source_system="IPS-DEMO", objective="Seguimiento",
        patient_reference=_TITULAR, patient_contact={"nombre": "Prueba 051"}, service="pediatria",
    ))
    context = build_health_agent_context(
        activity, source, service, ReminderManager(), MockActivityResultSink()
    )
    accept_activity(context)
    contact_patient(context)  # siembra "esperando_decision"
    return context, citas


def _hasta_esperando_fecha(monkeypatch):
    """Nueva conversación, llevada hasta "esperando_fecha" (mismas 3
    fechas reales siempre, único servicio en el catálogo — no pasa por
    "esperando_servicio")."""
    context, citas = _nuevo_contexto(monkeypatch)
    store = context.orchestrator.store
    r1 = handle_patient_message(context, "m1", "sí")
    assert store.get(context.activity.activity_id).datos_recopilados["etapa"] == "esperando_fecha"
    assert "lunes 7 de septiembre" in r1.lower()
    return context, citas


# ---------------------------------------------------------------------
# 1. Las 3 fechas reales, cada una con las 4 formas de responder.
# ---------------------------------------------------------------------
@pytest.mark.parametrize(
    "forma,fecha_esperada,fragmento_horarios_esperado",
    [
        # Lunes (opción 1) — las 4 formas.
        ("1", "2026-09-07", "08:00"),
        ("lunes", "2026-09-07", "08:00"),
        ("el lunes", "2026-09-07", "08:00"),
        ("7", "2026-09-07", "08:00"),
        ("el 7", "2026-09-07", "08:00"),
        ("día 7", "2026-09-07", "08:00"),
        ("7 de septiembre", "2026-09-07", "08:00"),
        ("lunes 7", "2026-09-07", "08:00"),
        ("lunes 7 de septiembre", "2026-09-07", "08:00"),
        # Martes (opción 2).
        ("2", "2026-09-08", "09:00"),
        ("martes", "2026-09-08", "09:00"),
        ("8", "2026-09-08", "09:00"),
        ("8 de septiembre", "2026-09-08", "09:00"),
        ("martes 8 de septiembre", "2026-09-08", "09:00"),
        # Miércoles (opción 3) — incluye tilde y sin tilde.
        ("3", "2026-09-09", "10:00"),
        ("miercoles", "2026-09-09", "10:00"),
        ("miércoles", "2026-09-09", "10:00"),
        ("9", "2026-09-09", "10:00"),
        ("9 de septiembre", "2026-09-09", "10:00"),
        ("miercoles 9 de septiembre", "2026-09-09", "10:00"),
    ],
)
def test_fecha_reconocida_en_las_4_formas(monkeypatch, forma, fecha_esperada, fragmento_horarios_esperado):
    context, _ = _hasta_esperando_fecha(monkeypatch)
    store = context.orchestrator.store
    respuesta = handle_patient_message(context, "m2", forma)
    estado = store.get(context.activity.activity_id)
    assert estado.datos_recopilados["etapa"] == "esperando_horario", (
        f"'{forma}' debía reconocer una fecha y avanzar a horario; respuesta real: {respuesta!r}"
    )
    assert estado.datos_recopilados["fecha_elegida"] == fecha_esperada, (
        f"'{forma}' debía elegir {fecha_esperada}, eligió {estado.datos_recopilados['fecha_elegida']}"
    )
    assert fragmento_horarios_esperado in respuesta


# ---------------------------------------------------------------------
# 2. Horarios: texto completo, hora sola (inequívoca), y con meridiano.
# ---------------------------------------------------------------------
@pytest.mark.parametrize(
    "forma_fecha,forma_horario,slot_esperado",
    [
        # Martes solo tiene UN horario (09:00) — "9" sola es inequívoca ahí.
        ("martes", "1", "SLOT-MAR-0900"),
        ("martes", "09:00", "SLOT-MAR-0900"),
        ("martes", "9:00", "SLOT-MAR-0900"),
        ("martes", "9", "SLOT-MAR-0900"),
        ("martes", "9 am", "SLOT-MAR-0900"),
        ("martes", "9:00 am", "SLOT-MAR-0900"),
        ("martes", "9 de la mañana", "SLOT-MAR-0900"),
        # Miércoles (10:00) — variantes con "de la mañana" ya cubiertas
        # arriba; acá se prueba una hora de dos dígitos.
        ("miercoles", "10:00", "SLOT-MIE-1000"),
        ("miercoles", "10", "SLOT-MIE-1000"),
        # Lunes: DOS horarios (08:00/08:30) — "08:00" completo sigue
        # siendo inequívoco aunque haya otro horario cerca.
        ("lunes", "08:00", "SLOT-LUN-0800"),
        ("lunes", "8:00 am", "SLOT-LUN-0800"),
        ("lunes", "08:30", "SLOT-LUN-0830"),
    ],
)
def test_horario_reconocido_en_multiples_formas(monkeypatch, forma_fecha, forma_horario, slot_esperado):
    context, citas = _hasta_esperando_fecha(monkeypatch)
    store = context.orchestrator.store
    handle_patient_message(context, "m2", forma_fecha)
    respuesta = handle_patient_message(context, "m3", forma_horario)
    estado = store.get(context.activity.activity_id)
    # La reserva se ejecuta sincrónicamente en este mismo turno
    # (MockActivitySource/HrmmAppointmentService de prueba, sin
    # verificación por código) — `etapa` avanza más allá de
    # "reservando" hacia su desenlace final; lo que confirma que SE
    # ELIGIÓ correctamente el horario esperado es el `slot_id` real con
    # el que se creó la cita, no un valor intermedio de `etapa`.
    assert estado.datos_recopilados.get("slot_seleccionado") == slot_esperado, (
        f"'{forma_horario}' debía reconocer el horario {slot_esperado}; respuesta real: {respuesta!r}"
    )
    assert "confirmado" in respuesta.lower()
    assert len(citas) == 1
    assert next(iter(citas.values()))["slot_id"] == slot_esperado


# ---------------------------------------------------------------------
# 3. Caso ambiguo — nunca se adivina, se pide aclaración con las
#    opciones reales.
# ---------------------------------------------------------------------
def test_horario_ambiguo_pide_aclaracion_en_vez_de_adivinar(monkeypatch):
    """El Lunes tiene 08:00 Y 08:30 — responder solo "8" (la hora, sin
    minutos) coincide con las DOS por igual. Caso real: un paciente que
    solo recuerda la hora, no los minutos exactos."""
    context, _ = _hasta_esperando_fecha(monkeypatch)
    store = context.orchestrator.store
    handle_patient_message(context, "m2", "lunes")
    respuesta = handle_patient_message(context, "m3", "8")
    estado = store.get(context.activity.activity_id)
    assert estado.datos_recopilados["etapa"] == "esperando_horario", (
        f"'8' es ambiguo entre 08:00 y 08:30 — no debía avanzar a reservar: {respuesta!r}"
    )
    assert "08:00" in respuesta and "08:30" in respuesta
    assert "slot_seleccionado" not in estado.datos_recopilados

    # El paciente aclara con la hora completa — SÍ avanza, sin repetir
    # la fecha ni perder el contexto ya elegido.
    respuesta2 = handle_patient_message(context, "m4", "08:30")
    estado2 = store.get(context.activity.activity_id)
    assert estado2.datos_recopilados.get("slot_seleccionado") == "SLOT-LUN-0830"
    assert "confirmado" in respuesta2.lower()


def test_fecha_ambigua_a_nivel_de_unidad_pide_aclaracion():
    """No se pudo reproducir un caso ambiguo de FECHA a través del
    flujo completo con el catálogo real de 3 fechas consecutivas (nunca
    dos fechas ofrecidas caen el mismo día de semana con esa ventana) —
    se prueba `_emparejar_fecha_por_texto` directo con dos fechas reales
    que SÍ caen el mismo día de semana (dos lunes, en semanas
    distintas) — escenario posible con la ventana de disponibilidad de
    prueba extendida a 90 días (recado 050)."""
    dos_lunes = ["2026-09-07", "2026-09-14"]  # ambos Lunes
    elegida, candidatos = _emparejar_fecha_por_texto("lunes", dos_lunes)
    assert elegida is None
    assert sorted(candidatos) == sorted(dos_lunes)

    # Con más contexto (el día del mes), deja de ser ambiguo — nivel 1
    # (día + mes/día de semana) desambigua sin necesitar el nivel 2.
    elegida_1, candidatos_1 = _emparejar_fecha_por_texto("7 de septiembre", dos_lunes)
    assert elegida_1 == "2026-09-07"
    assert candidatos_1 == []

    elegida_2, candidatos_2 = _emparejar_fecha_por_texto("14 de septiembre", dos_lunes)
    assert elegida_2 == "2026-09-14"
    assert candidatos_2 == []


# ---------------------------------------------------------------------
# 4. Fallback normal (texto no reconocido en ninguna forma) — sin
#    cambios frente al recado 034.
# ---------------------------------------------------------------------
def test_fecha_no_reconocida_usa_fallback_normal(monkeypatch):
    context, _ = _hasta_esperando_fecha(monkeypatch)
    store = context.orchestrator.store
    respuesta = handle_patient_message(context, "m2", "no sé, cualquiera está bien")
    estado = store.get(context.activity.activity_id)
    assert estado.datos_recopilados["etapa"] == "esperando_fecha"
    assert "no logré identificar" in respuesta.lower() or "no reconocí" in respuesta.lower()
    assert "fecha_elegida" not in estado.datos_recopilados


def test_horario_no_reconocido_usa_fallback_normal(monkeypatch):
    context, _ = _hasta_esperando_fecha(monkeypatch)
    store = context.orchestrator.store
    handle_patient_message(context, "m2", "martes")
    respuesta = handle_patient_message(context, "m3", "no sé, lo que sea")
    estado = store.get(context.activity.activity_id)
    assert estado.datos_recopilados["etapa"] == "esperando_horario"
    assert "no logré identificar" in respuesta.lower() or "no estoy seguro" in respuesta.lower()
    assert "slot_seleccionado" not in estado.datos_recopilados
