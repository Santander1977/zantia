"""
Recado 064 — generalización del mecanismo de selección/clasificación
asistida por LLM (`core/selection.py`, recado 052) a CUALQUIER punto de
la conversación donde el sistema espera una respuesta específica y el
matching determinista ya existente (recados 026/036/041/043/047/048/
058/059/062/063) no reconoció nada.

Reutiliza `core.selection.interpret_selection` TAL CUAL — cero cambios
en ese archivo. La generalización vive en `domains/health/gateway.py`
(`_clasificar_interrupcion_wizard_o_llm`, `_clasificar_solicitud_nueva_via_llm`)
y en `domains/health/config.py` (`build_selection_proposer`, extraído
de `build_health_brain` para que `HealthGateway` use el MISMO gate,
nunca una decisión de activación separada).

Este archivo verifica los 4 puntos pedidos explícitamente:
1. Lenguaje libre y variado en AL MENOS 5 puntos distintos de la
   conversación: (a) menú/fallback general, (b) selección de servicio
   [ya cubierto por recado 036, no se duplica acá], (c) selección de
   fecha/horario [ya cubierto por `test_seleccion_asistida_por_llm.py`,
   recado 052, no se duplica acá], (d) wizard de código de verificación
   (recado 062), (e) wizard de identidad de canal (recado 063).
2. Ninguna acción real (reservar/cancelar/confirmar identidad) se
   ejecuta sin la verificación estructurada YA existente — el cambio es
   de INTERPRETACIÓN, nunca de EJECUCIÓN.
3. Al menos 3 pruebas reales contra la API de Anthropic, en distintos
   puntos (menú, wizard de código, wizard de identidad) — gateadas,
   mismo patrón que `test_llm_brain.py`/`test_seleccion_asistida_por_llm.py`.
4. Comportamiento IDÉNTICO al de antes de este recado cuando no hay
   `selection_proposer` configurado (default de hoy, cero llamadas de
   red) — ya confirmado por el resto de la suite completa (498 tests
   sin cambios), reforzado acá con casos explícitos.
"""
import os

import pytest

from domains.health import MockActivitySource, MockActivityResultSink, ReminderManager
from domains.health.gateway import build_health_gateway, find_open_context, handle_inbound_message
from domains.health.hrmm_appointment_service import HrmmAppointmentService
from domains.health.hrmm_catalog import CatalogMirror
from domains.health.hrmm_http import FakeHttpClient, HttpResponse

_CITA_BASE = {
    "cita_id": "C1", "slot_id": "SLOT1", "medico_id": "M1", "servicio_id": "S1",
    "fecha": "2026-09-10", "hora_inicio": "09:00", "documento_paciente": "999",
    "nombre_paciente": "Ana", "telefono": "300", "estado": "reservada",
    "created_at": "x", "updated_at": "x",
}
_TELEFONO = "573001112233"
_DOCUMENTO_VALIDO = "123456789"
_CODIGO_VALIDO = "654321"


class _ProposerLibreGenerico:
    """Simula un LLM real y bien portado (mismo criterio que
    `_ProposerRealistaLenguajeNatural` de
    `test_seleccion_asistida_por_llm.py`): decide por fragmentos de
    texto simples presentes en el mensaje libre, nunca vocabulario de
    dominio hardcodeado — y SOLO propone un id que de verdad está en
    `options` (igual que exige `AnthropicSelectionProposer` real vía su
    prompt), simulando también el caso de "ninguna coincidencia clara"
    devolviendo `None`."""

    def __init__(self, mapa):
        self._mapa = mapa  # fragmento_de_texto -> id_esperado

    def propose(self, free_text, options):
        texto = free_text.lower()
        ids_reales = {o.id for o in options}
        for fragmento, id_esperado in self._mapa.items():
            if fragmento in texto and id_esperado in ids_reales:
                return id_esperado
        return None


class _ProposerQueAlucina:
    def propose(self, free_text, options):
        return "ID-QUE-NUNCA-EXISTIO"


def _hrmm_gateway(citas_por_documento=None, extra=None, selection_proposer=None):
    citas_por_documento = citas_por_documento or {}
    extra = extra or {}

    def generador(method, path, params, json_body, headers):
        if method == "GET" and path == "/api/agenda/servicios":
            return HttpResponse(200, [{"servicio_id": "S1", "nombre": "medicina general"}])
        if method == "GET" and path == "/api/agenda/medicos":
            return HttpResponse(200, [{"medico_id": "M1", "nombre_completo": "Dra. Ana Pérez", "servicio_id": "S1", "consultorio": "Consultorio 3"}])
        if method == "GET" and path == "/api/agenda/citas":
            documento = params.get("documento_paciente")
            return HttpResponse(200, citas_por_documento.get(documento, []))
        if method == "GET" and path == "/api/agenda/citas/buscar-paciente":
            documento = params.get("documento")
            if documento == _DOCUMENTO_VALIDO:
                return HttpResponse(200, {"nombre_paciente": "Paciente de Prueba", "telefono": _TELEFONO})
            return HttpResponse(404, {"detail": "no encontrado"})
        if method == "POST" and path == "/api/agenda/verificacion/enviar":
            return HttpResponse(200, {"enviado": True, "correo_parcial": "a***@dominio.com"})
        if method == "POST" and path == "/api/agenda/verificacion/confirmar":
            if json_body.get("codigo") == _CODIGO_VALIDO:
                return HttpResponse(200, {"valido": True})
            return HttpResponse(401, {"detail": "codigo invalido o vencido"})
        if (method, path) in extra:
            return extra[(method, path)](params, json_body)
        raise AssertionError(f"no programado en este test: {method} {path} {params}")

    http = FakeHttpClient(generador=generador)
    catalog = CatalogMirror()
    catalog.sync(http)
    service = HrmmAppointmentService(http, catalog)
    gateway = build_health_gateway(
        MockActivitySource(), service, ReminderManager(), MockActivityResultSink(),
        selection_proposer=selection_proposer,
    )
    return gateway, http


@pytest.fixture(autouse=True)
def _secreto_de_prueba(monkeypatch):
    monkeypatch.setenv("HRMM_BACKEND_SECRET", "secreto-de-prueba-no-real")


# ---------------------------------------------------------------------
# 1(a). Menú / fallback general — lenguaje libre variado, SIN conversación
#       abierta, que ninguna regla determinista (_interpretar_opcion_menu,
#       classify_intent_or_none, _es_despedida) reconoce.
# ---------------------------------------------------------------------
_FRASE_CANCELAR_SIN_SENAL = "oye la verdad ya no me late lo de esa cita que tenia agendada"
_FRASE_EMOCIONAL_SIN_SENAL = "estoy destrozado"


def test_menu_reconoce_lenguaje_libre_variado_via_llm():
    # Verificado antes de escribir este test (`classify_intent_or_none`
    # directo): ambas frases devuelven `None` determinista — ninguna
    # contiene palabra clave de ningún RequestIntent ni ninguna señal
    # de "_tiene_senal_de_intencion" (recado 056, el fallback genérico a
    # PROGRAMAR_CITA) — solo así se llega de verdad al último recurso
    # de este recado, nunca a un fallback determinista más temprano.
    proposer = _ProposerLibreGenerico({
        _FRASE_CANCELAR_SIN_SENAL: "3",
        _FRASE_EMOCIONAL_SIN_SENAL: "emocional",
    })
    gateway, http = _hrmm_gateway(
        citas_por_documento={"999": [_CITA_BASE]},
        extra={
            ("POST", "/api/agenda/verificacion/enviar"): lambda p, j: HttpResponse(
                200, {"enviado": True, "correo_parcial": "a***@dominio.com"}
            ),
        },
        selection_proposer=proposer,
    )
    handle_inbound_message(gateway, "999", "demo", "m1", "hola")

    r_cancelar = handle_inbound_message(gateway, "999", "demo", "m2", _FRASE_CANCELAR_SIN_SENAL)
    assert "no logré identificar" not in r_cancelar.lower()
    assert "código" in r_cancelar.lower()  # arrancó el flujo real de cancelar (con código, HrmmAppointmentService)
    assert "999" in gateway._pending_verifications

    # Cancela ese wizard para probar la categoría emocional desde cero.
    handle_inbound_message(gateway, "999", "demo", "m3", "salir")

    r_emocional = handle_inbound_message(gateway, "999", "demo", "m4", _FRASE_EMOCIONAL_SIN_SENAL)
    assert "no logré identificar" not in r_emocional.lower()
    assert "lamento" in r_emocional.lower()
    assert "1. reservar una cita" in r_emocional.lower()  # vuelve naturalmente al menú


def test_menu_sin_selection_proposer_mantiene_comportamiento_de_siempre():
    """Punto 4 — sin proposer (default de hoy), el fallback genérico
    sigue siendo exactamente el de antes de este recado."""
    gateway, http = _hrmm_gateway(citas_por_documento={"999": []})
    handle_inbound_message(gateway, "999", "demo", "m1", "hola")
    r = handle_inbound_message(gateway, "999", "demo", "m2", _FRASE_CANCELAR_SIN_SENAL)
    assert "no logré identificar" in r.lower()


def test_menu_rechaza_propuesta_alucinada_del_llm():
    gateway, http = _hrmm_gateway(citas_por_documento={"999": []}, selection_proposer=_ProposerQueAlucina())
    handle_inbound_message(gateway, "999", "demo", "m1", "hola")
    r = handle_inbound_message(gateway, "999", "demo", "m2", "algo que ninguna regla determinista reconoce")
    assert "no logré identificar" in r.lower()  # el id inventado se rechaza, cae al fallback de siempre


# ---------------------------------------------------------------------
# 1(d). Wizard de código de verificación (recado 062) — lenguaje libre
#       que el matching determinista/fuzzy NO reconoce.
# ---------------------------------------------------------------------
def test_wizard_codigo_reconoce_lenguaje_libre_via_llm():
    proposer = _ProposerLibreGenerico({
        "oye no me ha caído nada a la bandeja": "reenviar",
        "ya no quiero seguir con esto mejor otro día": "salir",
    })
    gateway, http = _hrmm_gateway(
        citas_por_documento={"999": [_CITA_BASE]},
        extra={
            ("POST", "/api/agenda/citas/C1/cancelar"): lambda p, j: HttpResponse(
                200, dict(_CITA_BASE, estado="cancelada")
            ),
        },
        selection_proposer=proposer,
    )
    handle_inbound_message(gateway, "999", "demo", "m1", "quiero cancelar mi cita")
    assert gateway._pending_verifications["999"]["stage"] == "esperando_codigo"

    r_reenvio = handle_inbound_message(gateway, "999", "demo", "m2", "oye no me ha caído nada a la bandeja")
    assert "no es válido" not in r_reenvio.lower() and "no válido" not in r_reenvio.lower()
    assert "reenviamos" in r_reenvio.lower()
    assert sum(1 for c in http.llamadas if c["path"] == "/api/agenda/verificacion/enviar") == 2

    r_salir = handle_inbound_message(gateway, "999", "demo", "m3", "ya no quiero seguir con esto mejor otro día")
    assert "999" not in gateway._pending_verifications
    # Nunca se ejecutó la cancelación real por esto — ver sección 2 (anti-bypass) abajo.
    assert not any(c["path"] == "/api/agenda/citas/C1/cancelar" for c in http.llamadas)


# ---------------------------------------------------------------------
# 1(e). Wizard de identidad de canal (recado 063) — lenguaje libre.
# ---------------------------------------------------------------------
def test_wizard_identidad_reconoce_lenguaje_libre_via_llm():
    proposer = _ProposerLibreGenerico({
        "oye no me ha caído nada a la bandeja": "reenviar",
        "mejor dejemoslo asi por ahora": "salir",
    })
    gateway, http = _hrmm_gateway(citas_por_documento={_DOCUMENTO_VALIDO: []}, selection_proposer=proposer)
    handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m1", "hola")
    handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m2", _DOCUMENTO_VALIDO)
    assert gateway._pending_identity[_TELEFONO]["stage"] == "esperando_codigo"

    r_reenvio = handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m3", "oye no me ha caído nada a la bandeja")
    assert "no es válido" not in r_reenvio.lower() and "no válido" not in r_reenvio.lower()
    assert "reenviamos" in r_reenvio.lower()

    r_salir = handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m4", "mejor dejemoslo asi por ahora")
    assert _TELEFONO not in gateway._pending_identity
    assert _TELEFONO not in gateway._identidad_resuelta  # nunca quedó "medio identificado"


# ---------------------------------------------------------------------
# 2. Anti-bypass: ninguna acción real se ejecuta sin la verificación
#    estructurada ya existente, sin importar lo que el LLM clasifique.
# ---------------------------------------------------------------------
def test_llm_nunca_ejecuta_una_accion_real_sin_el_codigo_verificado():
    """El proposer clasifica CUALQUIER mensaje como si fuera el dato
    esperado ("es_el_dato") — el resultado NUNCA debe cambiar: la
    verificación real sigue dependiendo 100% del código real contra
    hrmm-backend, nunca de la clasificación del LLM."""

    class _ProposerQueSiempreDiceEsElDato:
        def propose(self, free_text, options):
            for o in options:
                if o.id == "es_el_dato":
                    return "es_el_dato"
            return None

    def cancelar_valida_codigo(params, json_body):
        # SIEMPRE se valida contra el código real del backend — nunca
        # contra lo que el LLM haya clasificado.
        if params["codigo"] != _CODIGO_VALIDO:
            return HttpResponse(401, {"detail": "codigo invalido o vencido"})
        return HttpResponse(200, dict(_CITA_BASE, estado="cancelada"))

    gateway, http = _hrmm_gateway(
        citas_por_documento={"999": [_CITA_BASE]},
        extra={("POST", "/api/agenda/citas/C1/cancelar"): cancelar_valida_codigo},
        selection_proposer=_ProposerQueSiempreDiceEsElDato(),
    )
    handle_inbound_message(gateway, "999", "demo", "m1", "quiero cancelar mi cita")

    # Un código INCORRECTO, aunque el LLM lo clasifique como "es_el_dato"
    # (comportamiento sin cambios: cae al matching determinista de
    # siempre), sigue rechazándose contra el backend real.
    r_incorrecto = handle_inbound_message(gateway, "999", "demo", "m2", "000000")
    assert "no es válido" in r_incorrecto.lower() or "no válido" in r_incorrecto.lower()
    assert "999" in gateway._pending_verifications  # nada se ejecutó

    r_correcto = handle_inbound_message(gateway, "999", "demo", "m3", _CODIGO_VALIDO)
    assert "cancelada" in r_correcto.lower()


def test_llm_nunca_confirma_identidad_sin_el_codigo_real():
    gateway, http = _hrmm_gateway(citas_por_documento={_DOCUMENTO_VALIDO: []}, selection_proposer=_ProposerQueAlucina())
    handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m1", "hola")
    handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m2", _DOCUMENTO_VALIDO)

    r_incorrecto = handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m3", "000000")
    assert "no es válido" in r_incorrecto.lower()
    assert _TELEFONO not in gateway._identidad_resuelta

    r_correcto = handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m4", _CODIGO_VALIDO)
    assert "confirmé tu identidad" in r_correcto.lower()
    assert gateway._identidad_resuelta[_TELEFONO] == _DOCUMENTO_VALIDO


# ---------------------------------------------------------------------
# 3. Pruebas de integración REALES — DESHABILITADAS por defecto (mismo
#    patrón que test_llm_brain.py/test_seleccion_asistida_por_llm.py,
#    recado 038/052). 3 puntos distintos: wizard de código, wizard de
#    identidad, fallback de menú.
# ---------------------------------------------------------------------
_SKIP_REAL = pytest.mark.skipif(
    os.environ.get("ZANTIA_RUN_REAL_LLM_TESTS") != "1",
    reason="Pruebas de red real contra la API de Anthropic deshabilitadas por defecto — ver recado 038.",
)


@_SKIP_REAL
def test_real_wizard_codigo_reconoce_lenguaje_libre():
    from core.selection import AnthropicSelectionProposer

    gateway, http = _hrmm_gateway(
        citas_por_documento={"999": [_CITA_BASE]},
        selection_proposer=AnthropicSelectionProposer(),
    )
    handle_inbound_message(gateway, "999", "demo", "m1", "quiero cancelar mi cita")
    respuesta = handle_inbound_message(
        gateway, "999", "demo", "m2", "oye disculpa, se me hizo tarde y ya ni sé si quiero seguir con esto, mejor no"
    )
    assert "999" not in gateway._pending_verifications, (
        f"Claude real no reconoció la intención de salir: {respuesta!r}"
    )


@_SKIP_REAL
def test_real_wizard_identidad_reconoce_lenguaje_libre():
    from core.selection import AnthropicSelectionProposer

    gateway, http = _hrmm_gateway(
        citas_por_documento={_DOCUMENTO_VALIDO: []},
        selection_proposer=AnthropicSelectionProposer(),
    )
    handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m1", "hola")
    handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m2", _DOCUMENTO_VALIDO)
    respuesta = handle_inbound_message(
        gateway, _TELEFONO, "chatwoot", "m3", "perdón, ¿a qué dirección de correo me mandaron eso?"
    )
    assert "a***@dominio.com" in respuesta, f"Claude real no reconoció la pregunta sobre el correo: {respuesta!r}"


@_SKIP_REAL
def test_real_menu_reconoce_lenguaje_libre():
    from core.selection import AnthropicSelectionProposer

    gateway, http = _hrmm_gateway(
        citas_por_documento={"999": []},
        selection_proposer=AnthropicSelectionProposer(),
    )
    handle_inbound_message(gateway, "999", "demo", "m1", "hola")
    # Verificado antes de escribir este test (`classify_intent_or_none`
    # directo) que esta frase, a diferencia de una formulación más
    # típica ("me gustaría saber..."), no dispara NINGÚN fallback
    # determinista (ni por palabra clave, ni por "_tiene_senal_de_intencion",
    # recado 056) — solo así se ejerce de verdad la llamada real al LLM.
    respuesta = handle_inbound_message(
        gateway, "999", "demo", "m2", "oye cuentame que tengo agendado por ahi"
    )
    assert "no logré identificar" not in respuesta.lower(), (
        f"Claude real no clasificó la intención de consultar citas: {respuesta!r}"
    )
    assert "no tienes ninguna cita" in respuesta.lower()
