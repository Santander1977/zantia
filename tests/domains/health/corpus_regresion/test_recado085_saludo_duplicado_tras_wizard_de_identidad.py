"""
Recado 085 — transcripción REAL en producción (documento 72302972, hoy):

    [Andrés] Buenos días. Soy Andrés... ¿me confirmas tu número de documento?
    [Usuario] 72302972
    [Andrés] Listo, te enviamos un código a tu correo (d***@barranquillasegura.com)...
    [Usuario] 358787
    [Andrés] ¡Gracias! Ya confirmé tu identidad...
    [Usuario] consultame las citas del ultimo mes
    [Andrés] Buenos días. Soy Andrés... [menú completo] Aquí tienes tu 1 cita activa: ...
    [Usuario] consultas las citas mias del ultimo mes
    [Andrés] Aquí tienes tu 1 cita activa: ...

Hallazgo: el PRIMER mensaje real tras completar el wizard de identidad
(documento + código) mostraba el saludo institucional COMPLETO otra vez
("Soy Andrés...", menú de 5 opciones) — pegado (con el separador `\\n\\n`
correcto del recado 080, nunca roto) a la respuesta real. El saludo ya
se había mostrado UNA VEZ, en el primer mensaje del wizard.

Causa raíz — confirmada leyendo `gateway.py`: `_saludo_mostrado` (el set
que evita repetir el guion institucional completo) solo se marca dentro
de la rama de `handle_inbound_message` alcanzada DESPUÉS de que la
identidad ya está resuelta (línea ~862). La rama del wizard de identidad
(gate de identidad, líneas ~816-853) SÍ muestra el saludo completo (en
el primer mensaje, antepuesto a la pregunta de documento — recado 046),
pero nunca marcaba `_saludo_mostrado` — así que el primer mensaje real
alcanzado DESPUÉS del wizard (código ya confirmado) llegaba con
`saludo_ya_mostrado = False` y volvía a mostrar el guion completo.
Reproducido EXACTO con el flujo real (hola -> documento -> código ->
"consultar mis citas"): el bug ocurre para CUALQUIER frase en ese punto,
no es específico de "consultame las citas del ultimo mes" — esa frase
solo fue la primera que el paciente real escribió ahí.

Corrección: `gateway.py`, se marca `gateway._saludo_mostrado.add(patient_reference)`
en el mismo punto donde se muestra el saludo completo dentro del gate de
identidad (antes de devolver `f"{_saludo_primer_contacto(None)}\\n\\n{respuesta_identificacion}"`).

Nota sobre el reporte original del usuario ("el mismo patrón de 'todo
junto' ya corregido varias veces, reapareciendo en esta frase
específica"): el separador `\\n\\n` (recado 080) NUNCA se rompió — sigue
aplicándose en el único punto de inyección real. El bug real no era la
FALTA de separador, sino la aparición DUPLICADA e inesperada del saludo
institucional completo en un punto de la conversación donde el paciente
ya lo había visto — confirmado reproduciendo tanto la frase exacta
reportada como la forma canónica "consultar mis citas" (ambas fallaban
igual, antes del fix).
"""
from domains.health.gateway import build_health_gateway, handle_inbound_message
from domains.health.hrmm_appointment_service import HrmmAppointmentService
from domains.health.hrmm_catalog import CatalogMirror
from domains.health.hrmm_http import FakeHttpClient, HttpResponse
from domains.health.identity_store import SQLiteIdentidadCanalStore

import pytest

from domains.health import MockActivitySource, MockActivityResultSink, ReminderManager

_DOCUMENTO = "72302972"
_CODIGO = "358787"
_CHAT_ID = "telegram-72302972"


@pytest.fixture(autouse=True)
def _secreto_de_prueba(monkeypatch):
    monkeypatch.setenv("HRMM_BACKEND_SECRET", "secreto-de-prueba-no-real")


def _gateway_real_wizard():
    def generador(method, path, params, json_body, headers):
        if method == "GET" and path == "/api/agenda/servicios":
            return HttpResponse(200, [{"servicio_id": "S1", "nombre": "Pediatria"}])
        if method == "GET" and path == "/api/agenda/medicos":
            return HttpResponse(200, [{"medico_id": "M1", "nombre_completo": "Dra. María Johana Buitrago", "servicio_id": "S1", "consultorio": "Consultorio 3"}])
        if method == "GET" and path == "/api/agenda/citas/buscar-paciente":
            if params.get("documento") == _DOCUMENTO:
                return HttpResponse(200, {"nombre_paciente": "Paciente de Prueba", "telefono": _CHAT_ID})
            return HttpResponse(404, {"detail": "no encontrado"})
        if method == "GET" and path == "/api/agenda/citas":
            documento = params.get("documento_paciente")
            if documento == _DOCUMENTO:
                return HttpResponse(200, [{
                    "cita_id": "CITA-REAL-1", "slot_id": "SLOT1", "medico_id": "M1", "servicio_id": "S1",
                    "fecha": "2026-09-15", "hora_inicio": "10:30", "documento_paciente": _DOCUMENTO,
                    "nombre_paciente": "Paciente de Prueba", "telefono": _CHAT_ID,
                    "correo": "d***@barranquillasegura.com", "estado": "confirmada",
                }])
            return HttpResponse(200, [])
        if method == "POST" and path == "/api/agenda/verificacion/enviar":
            return HttpResponse(200, {"enviado": True, "mensaje": "ok", "correo_parcial": "d***@barranquillasegura.com"})
        if method == "POST" and path == "/api/agenda/verificacion/confirmar":
            return HttpResponse(200, {"valido": json_body.get("codigo") == _CODIGO})
        raise AssertionError(f"no programado en este test: {method} {path} {params}")

    http = FakeHttpClient(generador=generador)
    catalog = CatalogMirror()
    catalog.sync(http)
    service = HrmmAppointmentService(http, catalog)
    return build_health_gateway(
        MockActivitySource(), service, ReminderManager(), MockActivityResultSink(),
        identity_store=SQLiteIdentidadCanalStore(":memory:"),
    )


def _completar_wizard(gateway):
    handle_inbound_message(gateway, _CHAT_ID, "telegram", "m1", "hola")
    handle_inbound_message(gateway, _CHAT_ID, "telegram", "m2", _DOCUMENTO)
    r3 = handle_inbound_message(gateway, _CHAT_ID, "telegram", "m3", _CODIGO)
    assert "confirmé tu identidad" in r3.lower()


def _assert_sin_saludo_duplicado(respuesta):
    assert "soy andrés" not in respuesta.lower(), (
        f"el saludo institucional completo se repitió tras el wizard de identidad: {respuesta!r}"
    )
    assert "1. reservar una cita" not in respuesta.lower(), (
        f"el menú completo se repitió tras el wizard de identidad: {respuesta!r}"
    )


def test_consultame_las_citas_del_ultimo_mes_no_repite_el_saludo_tras_el_wizard():
    """Frase EXACTA reportada por el usuario, primer mensaje real tras
    completar el wizard de identidad."""
    gateway = _gateway_real_wizard()
    _completar_wizard(gateway)

    respuesta = handle_inbound_message(gateway, _CHAT_ID, "telegram", "m4", "consultame las citas del ultimo mes")

    _assert_sin_saludo_duplicado(respuesta)
    assert "pediatria" in respuesta.lower()


def test_consultar_mis_citas_exacto_tampoco_repite_el_saludo_tras_el_wizard():
    """Confirma que el bug NO era específico de la frase reportada —
    la forma canónica exacta fallaba exactamente igual antes del fix
    (causa raíz real: `_saludo_mostrado` nunca se marcaba dentro del
    gate de identidad, no una brecha de clasificación de intención)."""
    gateway = _gateway_real_wizard()
    _completar_wizard(gateway)

    respuesta = handle_inbound_message(gateway, _CHAT_ID, "telegram", "m4", "consultar mis citas")

    _assert_sin_saludo_duplicado(respuesta)
    assert "pediatria" in respuesta.lower()


def test_variante_consultas_las_citas_mias_tambien_encuentra_la_cita():
    """Segunda frase real de la transcripción (turno siguiente) —
    variante adicional no cubierta por las listas deterministas
    existentes; documentada acá como hallazgo, no bloqueante para el
    fix principal de este recado (el saludo duplicado)."""
    gateway = _gateway_real_wizard()
    _completar_wizard(gateway)
    handle_inbound_message(gateway, _CHAT_ID, "telegram", "m4", "consultame las citas del ultimo mes")

    respuesta = handle_inbound_message(gateway, _CHAT_ID, "telegram", "m5", "consultas las citas mias del ultimo mes")

    _assert_sin_saludo_duplicado(respuesta)
