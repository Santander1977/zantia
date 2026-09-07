"""
Recado 046, Parte 2 — saludo institucional consistente en el primer
contacto de una conversación nueva: guion FIJO por hora del día
(America/Bogota), presentación institucional ("Andrés", Hospital
Regional del Magdalena Medio) y un menú NUMERADO de 4 opciones
(reservar/reprogramar/cancelar/consultar) para un paciente nuevo;
saludo personalizado y formal (señor/señora + nombre real) + el mismo
menú para un paciente ya reconocido.

Diseño NO BLOQUEANTE (decisión explícita, ver recado 046): el saludo +
menú se antepone SIEMPRE como guía visible al primer mensaje de una
conversación nueva, pero si ese mismo mensaje ya expresa una intención
clara (ej. "necesito una cita"), se procesa de una vez — nunca se hace
esperar al paciente a que responda al menú antes de continuar.

Construido enteramente en `domains/health/gateway.py`, FUERA de
cualquier llamada a `HealthBrain.interpret()`/`HealthAnthropicBrain` —
estructuralmente imposible que el LLM lo altere, con o sin
`HEALTH_BRAIN_TYPE=llm` activo (verificado explícitamente más abajo,
incluyendo con una llamada real).
"""
from datetime import datetime

import pytest

from domains.health import handle_inbound_message
from domains.health.gateway import (
    _interpretar_opcion_menu,
    _saludo_primer_contacto,
    _saludo_segun_hora_bogota,
    _tratamiento_formal,
)
from domains.health.hrmm_appointment_service import HrmmAppointmentService
from domains.health.hrmm_catalog import CatalogMirror
from domains.health.hrmm_http import FakeHttpClient, HttpResponse
from domains.health.identity_store import SQLiteIdentidadCanalStore
from domains.health.models import RequestIntent


def _gateway_real(monkeypatch, citas_reales=None):
    """Mismo helper que `test_nombre_y_tono_humano.py` — duplicado
    deliberadamente (sin import cruzado entre módulos de test, mismo
    criterio ya usado en el resto de la suite) para un catálogo de UN
    servicio, con `HrmmAppointmentService` real vía `FakeHttpClient`."""
    monkeypatch.setenv("HRMM_BACKEND_SECRET", "secreto-de-prueba-no-real")
    citas_reales = citas_reales if citas_reales is not None else {}

    def generador(method, path, params, json_body, headers):
        if method == "GET" and path == "/api/agenda/servicios":
            return HttpResponse(200, [{"servicio_id": "S1", "nombre": "medicina general"}])
        if method == "GET" and path == "/api/agenda/medicos":
            return HttpResponse(200, [{"medico_id": "M1", "nombre_completo": "Dra. Ana Pérez", "servicio_id": "S1", "consultorio": "Consultorio 3"}])
        if method == "GET" and path == "/api/agenda/disponibilidad":
            return HttpResponse(200, [
                {"slot_id": "SLOT1", "medico_id": "M1", "servicio_id": "S1", "fecha": "2026-09-10", "hora_inicio": "09:00", "hora_fin": "09:30", "estado": "Libre"},
            ])
        if method == "GET" and path == "/api/agenda/citas":
            doc = params.get("documento_paciente")
            return HttpResponse(200, [c for c in citas_reales.values() if c["documento_paciente"] == doc])
        raise AssertionError(f"no programado en este test: {method} {path} {params}")

    http = FakeHttpClient(generador=generador)
    catalog = CatalogMirror()
    catalog.sync(http)
    service = HrmmAppointmentService(http, catalog)
    identity_store = SQLiteIdentidadCanalStore(":memory:")
    from domains.health import MockActivitySource, MockActivityResultSink, ReminderManager, build_health_gateway

    gateway = build_health_gateway(
        MockActivitySource(), service, ReminderManager(), MockActivityResultSink(),
        identity_store=identity_store,
    )
    return gateway, identity_store


# ---------------------------------------------------------------------
# 1. `_saludo_segun_hora_bogota` — las 3 franjas horarias.
# ---------------------------------------------------------------------
@pytest.mark.parametrize(
    "hora, esperado",
    [
        (6, "Buenos días"),
        (11, "Buenos días"),
        (12, "Buenas tardes"),
        (18, "Buenas tardes"),
        (19, "Buenas noches"),
        (2, "Buenas noches"),
    ],
)
def test_saludo_segun_hora_bogota_las_3_franjas(hora, esperado):
    momento = datetime(2026, 9, 6, hora, 0)
    assert _saludo_segun_hora_bogota(momento) == esperado


# ---------------------------------------------------------------------
# 2. `_tratamiento_formal` — heurística documentada.
# ---------------------------------------------------------------------
def test_tratamiento_formal_nombre_terminado_en_a_es_senora():
    assert _tratamiento_formal("María") == "señora"


def test_tratamiento_formal_otro_caso_es_senor():
    assert _tratamiento_formal("Enzo") == "señor"
    assert _tratamiento_formal("Santander") == "señor"


# ---------------------------------------------------------------------
# 3. `_interpretar_opcion_menu` — acepta AMBAS formas (número o palabra)
#    para las 4 opciones, y `None` si no reconoce nada.
# ---------------------------------------------------------------------
@pytest.mark.parametrize(
    "texto, intent_esperado",
    [
        ("1", RequestIntent.PROGRAMAR_CITA),
        ("reservar", RequestIntent.PROGRAMAR_CITA),
        ("2", RequestIntent.REPROGRAMAR_CITA),
        ("3", RequestIntent.CANCELAR_CITA),
        ("quiero cancelar", RequestIntent.CANCELAR_CITA),
        ("4", RequestIntent.CONSULTAR_CITA),
        ("consultar mis citas", RequestIntent.CONSULTAR_CITA),
    ],
)
def test_interpretar_opcion_menu_acepta_numero_o_palabra(texto, intent_esperado):
    assert _interpretar_opcion_menu(texto) == intent_esperado


def test_interpretar_opcion_menu_no_reconocido_devuelve_none():
    assert _interpretar_opcion_menu("no sé, tal vez") is None


def test_reprogramar_como_palabra_se_reconoce_via_classify_intent_no_via_menu(monkeypatch):
    """'reprogramar' como palabra suelta NO está en `_interpretar_opcion_menu`
    (deliberado, ver comentario de `_MENU_OPCIONES` en gateway.py) —
    ya la reconoce `classify_intent` con su propio orden de prioridad
    correcto (`_REPROGRAMAR`). La combinación completa
    (`_interpretar_opcion_menu(text) or classify_intent(text)`, usada
    en `_enrutar_solicitud_nueva`) sigue funcionando igual de bien —
    verificado de extremo a extremo, no solo a nivel de unidad."""
    gateway, identity_store = _gateway_real(monkeypatch)
    identity_store.marcar_verificado("chat-reprog", "999", None)
    respuesta = handle_inbound_message(gateway, "chat-reprog", "telegram", "m1", "necesito reprogramar mi cita")
    assert "no encuentro ninguna cita activa" in respuesta.lower()  # sin citas activas, mensaje correcto — no cayó a "reservar"


def test_interpretar_opcion_menu_reprogramar_no_colisiona_con_programar():
    """Hallazgo real (recado 046): 'programar' es substring literal de
    'reprogramar' — sin límite de palabra, un `in` simple habría hecho
    que CUALQUIER mensaje de reprogramar matcheara la opción 1
    (reservar) por error. Verificado sobre la palabra sola: no debe
    reconocerla como PROGRAMAR_CITA (ninguna opción, ya que 'reprogramar'
    no está en absoluto en `_MENU_OPCIONES` — se delega a classify_intent)."""
    assert _interpretar_opcion_menu("necesito reprogramar mi cita") != RequestIntent.PROGRAMAR_CITA


# ---------------------------------------------------------------------
# 4. Saludo completo — paciente NUEVO (sin identidad persistida),
#    en las 3 franjas horarias, vía el gate real de identidad
#    (Telegram + HrmmAppointmentService, mismo camino de producción).
#    Diseño NO bloqueante: el mensaje YA dice "necesito una cita", así
#    que la sustancia (pedir el documento) sigue en el MISMO turno,
#    con el guion antepuesto.
# ---------------------------------------------------------------------
def _gateway_hrmm_sin_identidad(monkeypatch):
    monkeypatch.setenv("HRMM_BACKEND_SECRET", "secreto-de-prueba-no-real")

    def generador(method, path, params, json_body, headers):
        if method == "GET" and path == "/api/agenda/servicios":
            return HttpResponse(200, [{"servicio_id": "S1", "nombre": "medicina general"}])
        if method == "GET" and path == "/api/agenda/medicos":
            return HttpResponse(200, [])
        if method == "GET" and path == "/api/agenda/citas/buscar-paciente":
            return HttpResponse(200, {"nombre_paciente": "Paciente Nuevo", "telefono": "3000000000"})
        if method == "POST" and path == "/api/agenda/verificacion/enviar":
            return HttpResponse(200, {"enviado": True, "mensaje": "Código enviado.", "correo_parcial": "p***@x.com"})
        raise AssertionError(f"no programado en este test: {method} {path}")

    http = FakeHttpClient(generador=generador)
    catalog = CatalogMirror()
    catalog.sync(http)
    service = HrmmAppointmentService(http, catalog)
    identity_store = SQLiteIdentidadCanalStore(":memory:")
    from domains.health import MockActivitySource, MockActivityResultSink, ReminderManager, build_health_gateway

    return build_health_gateway(
        MockActivitySource(), service, ReminderManager(), MockActivityResultSink(),
        identity_store=identity_store,
    )


@pytest.mark.parametrize(
    "hora, saludo_esperado",
    [(8, "Buenos días"), (15, "Buenas tardes"), (22, "Buenas noches")],
)
def test_saludo_completo_paciente_nuevo_3_franjas_horarias(monkeypatch, hora, saludo_esperado):
    monkeypatch.setattr(
        "domains.health.gateway._saludo_segun_hora_bogota",
        lambda *a, **k: saludo_esperado,
    )
    gateway = _gateway_hrmm_sin_identidad(monkeypatch)
    respuesta = handle_inbound_message(gateway, f"chat-nuevo-{hora}", "telegram", "m1", "necesito una cita")

    assert respuesta.startswith(saludo_esperado)
    assert "Andrés" in respuesta
    assert "Hospital Regional del Magdalena Medio" in respuesta
    assert "1. Reservar" in respuesta and "2. Reprogramar" in respuesta
    assert "3. Cancelar" in respuesta and "4. Consultar" in respuesta
    # El saludo llega ANTES de pedir el documento (requisito explícito) —
    # ambos en el MISMO turno (diseño no bloqueante).
    assert "documento" in respuesta.lower()


def test_saludo_no_se_repite_en_turnos_siguientes_del_wizard(monkeypatch):
    monkeypatch.setattr("domains.health.gateway._saludo_segun_hora_bogota", lambda *a, **k: "Buenas tardes")
    gateway = _gateway_hrmm_sin_identidad(monkeypatch)
    pref = "chat-reintento"
    r1 = handle_inbound_message(gateway, pref, "telegram", "m1", "necesito una cita")
    assert "Andrés" in r1

    r2 = handle_inbound_message(gateway, pref, "telegram", "m2", "72302972")
    assert "Andrés" not in r2


# ---------------------------------------------------------------------
# 5. Saludo personalizado — paciente YA reconocido, con el mismo menú.
# ---------------------------------------------------------------------
def test_saludo_personalizado_paciente_reconocido(monkeypatch):
    monkeypatch.setattr("domains.health.gateway._saludo_segun_hora_bogota", lambda *a, **k: "Buenas tardes")
    gateway, identity_store = _gateway_real(monkeypatch)
    identity_store.marcar_verificado("chat-reconocido", "999", "Santander")

    respuesta = handle_inbound_message(gateway, "chat-reconocido", "telegram", "m1", "necesito una cita")
    assert respuesta.startswith("¡Buenas tardes, señor Santander! ¿Qué desea hacer hoy?")
    assert "1. Reservar" in respuesta and "4. Consultar" in respuesta
    # No repite la presentación completa para un paciente ya reconocido.
    assert "Andrés" not in respuesta


# ---------------------------------------------------------------------
# 6. El contenido esencial del saludo NUNCA pasa por el LLM — ni con
#    HEALTH_BRAIN_TYPE=llm activo. Verificado con un drafter simulado
#    (rápido) y con UNA llamada REAL a Anthropic (evidencia fuerte).
# ---------------------------------------------------------------------
class _DrafterQueIntentaReescribirTodo:
    """Simula el peor caso: un LLM que reescribe agresivamente
    cualquier texto que se le entregue, incluso a prosa corrida sin
    números — si el saludo/menú llegara a pasar por acá, se alteraría.
    Sirve para confirmar que estructuralmente NUNCA llega a este punto."""

    def draft(self, mensaje_paciente: str, texto_base: str) -> str:
        return "Mensaje completamente reescrito por el LLM, sin ningún parecido al original, sin números."


def test_saludo_y_menu_nunca_pasan_por_el_llm_ni_con_health_brain_type_llm(monkeypatch):
    monkeypatch.setenv("HEALTH_BRAIN_TYPE", "llm")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "clave-de-prueba-nunca-usada-en-red-real")
    monkeypatch.setattr(
        "domains.health.llm_brain.AnthropicResponseDrafter",
        lambda **kwargs: _DrafterQueIntentaReescribirTodo(),
    )
    monkeypatch.setattr("domains.health.gateway._saludo_segun_hora_bogota", lambda *a, **k: "Buenas tardes")

    gateway = _gateway_hrmm_sin_identidad(monkeypatch)
    respuesta = handle_inbound_message(gateway, "chat-llm-activo", "telegram", "m1", "necesito una cita")

    assert "Andrés" in respuesta
    assert "Hospital Regional del Magdalena Medio" in respuesta
    assert "1. Reservar" in respuesta and "4. Consultar" in respuesta
    assert "Mensaje completamente reescrito" not in respuesta


@pytest.mark.skipif(
    __import__("os").environ.get("ZANTIA_RUN_REAL_LLM_TESTS") != "1",
    reason="Pruebas de red real contra la API de Anthropic deshabilitadas por defecto — ver recado 038/046.",
)
def test_saludo_y_menu_nunca_pasan_por_el_llm_con_llamada_real(monkeypatch):
    monkeypatch.setenv("HEALTH_BRAIN_TYPE", "llm")
    monkeypatch.setattr("domains.health.gateway._saludo_segun_hora_bogota", lambda *a, **k: "Buenas tardes")
    gateway = _gateway_hrmm_sin_identidad(monkeypatch)
    respuesta = handle_inbound_message(gateway, "chat-llm-real", "telegram", "m1", "necesito una cita")
    assert "Andrés" in respuesta
    assert "Hospital Regional del Magdalena Medio" in respuesta
    assert "1. Reservar" in respuesta and "4. Consultar" in respuesta
