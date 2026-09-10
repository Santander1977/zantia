"""
Gate de identidad para el canal real ChatwootChannel (recado 012, R-15):
un identificador de canal (número de WhatsApp) NO es el documento real
del paciente que exige HrmmAppointmentService (D-4). Antes de procesar
cualquier intención, se le pide el documento al paciente y se confirma
contra GET /citas/buscar-paciente (público, sin secreto, 009) — sin
tocar HealthBrain, ChatwootChannel ni HrmmAppointmentService.

Extendido en recado 014: el documento confirmado ya no se acepta como
confiable de inmediato — se exige además un código de verificación
(mismo mecanismo de 009), y el resultado se persiste en
`identity_store` (`domains/health/identity_store.py`) para reconocer al
mismo teléfono en una conversación SIGUIENTE sin repetir el wizard —
ver `test_identidad_persistente.py` para esos casos específicos.

Sin red real — mismo patrón que test_hrmm_gateway_verification.py
(FakeHttpClient con un generador programable).
"""
import pytest

from domains.health import MockActivitySource, MockActivityResultSink, ReminderManager
from domains.health.gateway import (
    build_health_gateway,
    handle_inbound_message,
    require_document_on_activity,
    start_activity_and_register,
)
from domains.health.hrmm_appointment_service import HrmmAppointmentService
from domains.health.hrmm_catalog import CatalogMirror
from domains.health.hrmm_http import FakeHttpClient, HttpResponse
from domains.health.models import Activity, RequestIntent, RequestStatus

_TELEFONO = "573001112233"
_DOCUMENTO_VALIDO = "123456789"
_DOCUMENTO_INVALIDO = "000000000"
_CODIGO_VALIDO = "654321"
_CODIGO_INVALIDO = "000000"


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
            if json_body.get("codigo") == _CODIGO_VALIDO:
                return HttpResponse(200, {"valido": True})
            return HttpResponse(401, {"detail": "codigo invalido o vencido"})
        raise AssertionError(f"no programado en este test: {method} {path} {params}")

    return generador


@pytest.fixture
def hrmm_gateway():
    def _build(citas_por_documento=None, identity_store=None):
        http = FakeHttpClient(generador=_generador(citas_por_documento))
        catalog = CatalogMirror()
        catalog.sync(http)
        service = HrmmAppointmentService(http, catalog)
        gateway = build_health_gateway(
            MockActivitySource(), service, ReminderManager(), MockActivityResultSink(),
            identity_store=identity_store,
        )
        return gateway

    return _build


def test_mensaje_nuevo_por_chatwoot_sin_identidad_pide_documento(hrmm_gateway):
    gateway = hrmm_gateway()
    respuesta = handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m1", "hola quiero una cita")

    assert "documento" in respuesta.lower()
    assert _TELEFONO not in gateway._identidad_resuelta
    assert _TELEFONO in gateway._pending_identity
    # Ninguna otra intención se procesó todavía — ninguna PatientRequest creada.
    assert gateway.patient_request_source._requests == {}


def test_documento_valido_pide_codigo_de_verificacion_antes_de_confiar(hrmm_gateway):
    """Recado 014, requisito #2c: el documento confirmado NO se acepta
    de inmediato — se exige un código de verificación antes de asociar
    la identidad."""
    gateway = hrmm_gateway(citas_por_documento={_DOCUMENTO_VALIDO: []})
    handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m1", "hola quiero una cita")

    respuesta = handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m2", _DOCUMENTO_VALIDO)
    assert "código" in respuesta.lower()
    assert _TELEFONO not in gateway._identidad_resuelta
    assert gateway._pending_identity[_TELEFONO]["stage"] == "esperando_codigo"
    # Fila PENDIENTE_VERIFICACION ya escrita (requisito #1) — todavía no confiable.
    registro = gateway.identity_store.get(_TELEFONO)
    assert registro.estado.value == "PENDIENTE_VERIFICACION"


def test_codigo_invalido_no_resuelve_identidad_y_permite_reintentar(hrmm_gateway):
    gateway = hrmm_gateway(citas_por_documento={_DOCUMENTO_VALIDO: []})
    handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m1", "hola")
    handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m2", _DOCUMENTO_VALIDO)

    respuesta = handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m3", _CODIGO_INVALIDO)
    assert "no es válido" in respuesta.lower()
    assert _TELEFONO not in gateway._identidad_resuelta
    assert gateway._pending_identity[_TELEFONO]["stage"] == "esperando_codigo"  # puede reintentar

    respuesta2 = handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m4", _CODIGO_VALIDO)
    assert "confirmé tu identidad" in respuesta2.lower()
    assert gateway._identidad_resuelta[_TELEFONO] == _DOCUMENTO_VALIDO


def test_codigo_valido_resuelve_identidad_persiste_y_continua(hrmm_gateway):
    gateway = hrmm_gateway(citas_por_documento={_DOCUMENTO_VALIDO: []})
    handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m1", "hola quiero una cita")
    handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m2", _DOCUMENTO_VALIDO)

    respuesta = handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m3", _CODIGO_VALIDO)
    assert "confirmé tu identidad" in respuesta.lower()
    assert gateway._identidad_resuelta[_TELEFONO] == _DOCUMENTO_VALIDO
    assert _TELEFONO not in gateway._pending_identity

    # Persistido en identidad_canal como VERIFICADO (requisito #2d).
    registro = gateway.identity_store.get(_TELEFONO)
    assert registro.estado.value == "VERIFICADO"
    assert registro.documento == _DOCUMENTO_VALIDO
    assert registro.verificado_en is not None

    # La conversación continúa normalmente después — sin volver a pedir
    # documento ni código — y usa el documento real (no el teléfono)
    # contra AppointmentService (ver _MENSAJE_SIN_CITA_ACTIVA: solo
    # llega ahí si get_patient_appointments(_DOCUMENTO_VALIDO) se consultó).
    respuesta2 = handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m4", "quiero consultar mi cita")
    assert "documento" not in respuesta2.lower()
    assert "no tienes ninguna cita" in respuesta2.lower()


def test_documento_no_encontrado_no_resuelve_identidad(hrmm_gateway):
    gateway = hrmm_gateway()
    handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m1", "hola")

    respuesta = handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m2", _DOCUMENTO_INVALIDO)
    assert "no encontré" in respuesta.lower()
    assert _TELEFONO not in gateway._identidad_resuelta
    assert _TELEFONO in gateway._pending_identity  # sigue pendiente, puede reintentar


def test_segundo_mensaje_ya_identificado_no_vuelve_a_pedir_documento(hrmm_gateway):
    gateway = hrmm_gateway(citas_por_documento={_DOCUMENTO_VALIDO: []})
    # Identidad ya resuelta de una conversación anterior (mismo número).
    gateway._identidad_resuelta[_TELEFONO] = _DOCUMENTO_VALIDO

    respuesta = handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m1", "quiero consultar mi cita")
    assert "documento" not in respuesta.lower()
    assert "no tienes ninguna cita" in respuesta.lower()


def test_camino_activity_outbound_no_se_ve_afectado(hrmm_gateway):
    """El camino Activity (outbound, demanda inducida) sigue exigiendo
    el documento explícito en el payload (require_document_on_activity,
    009) — nunca pasa por handle_inbound_message ni por este gate."""
    gateway = hrmm_gateway()
    activity_sin_documento = Activity(
        activity_id="ACT-1", source_system="IPS-DEMO", objective="Seguimiento",
        patient_reference=_TELEFONO, patient_contact={}, service="medicina general",
    )
    with pytest.raises(ValueError, match="documento"):
        require_document_on_activity(activity_sin_documento)

    activity_con_documento = activity_sin_documento.model_copy(
        update={"patient_contact": {"documento": _DOCUMENTO_VALIDO}}
    )
    assert require_document_on_activity(activity_con_documento) == _DOCUMENTO_VALIDO

    # Y arrancar la Activity real (start_activity_and_register) no pide
    # ningún documento por chat — nunca invoca el gate de identidad.
    contexto = start_activity_and_register(gateway, activity_con_documento)
    assert contexto.activity.patient_reference == _TELEFONO
    assert gateway._pending_identity == {}


def test_limite_de_intentos_fallidos_escala(hrmm_gateway):
    gateway = hrmm_gateway()
    handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m1", "hola")

    r1 = handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m2", _DOCUMENTO_INVALIDO)
    assert "no encontré" in r1.lower()
    r2 = handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m3", _DOCUMENTO_INVALIDO)
    assert "no encontré" in r2.lower()
    r3 = handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m4", _DOCUMENTO_INVALIDO)

    assert "pasar tu caso al equipo" in r3.lower()
    assert _TELEFONO not in gateway._pending_identity  # nunca se queda en limbo
    assert _TELEFONO not in gateway._identidad_resuelta

    solicitudes_escaladas = [
        r for r in gateway.patient_request_source._requests.values()
        if r.patient_reference == _TELEFONO and r.status == RequestStatus.ESCALADA
    ]
    assert len(solicitudes_escaladas) == 1
    assert solicitudes_escaladas[0].intent == RequestIntent.ESCALAMIENTO

    # Un mensaje posterior arranca el gate de nuevo desde cero — nunca
    # queda atascado sin salida.
    r4 = handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m5", "hola de nuevo")
    assert "documento" in r4.lower()


# ---------------------------------------------------------------------
# Recado 063 — mismo hallazgo urgente del recado 062, encontrado esta
# vez en el gate de identidad de canal (la puerta de entrada de
# CUALQUIER paciente nuevo por un canal sin documento explícito, ej.
# WhatsApp/Chatwoot). Reutiliza el MISMO clasificador compartido
# (`_clasificar_interrupcion_wizard`, gateway.py) — no una copia.
# ---------------------------------------------------------------------
def _gateway_con_http(citas_por_documento=None):
    http = FakeHttpClient(generador=_generador(citas_por_documento))
    catalog = CatalogMirror()
    catalog.sync(http)
    service = HrmmAppointmentService(http, catalog)
    gateway = build_health_gateway(MockActivitySource(), service, ReminderManager(), MockActivityResultSink())
    return gateway, http


def test_wizard_identidad_no_queda_atrapado_esperando_codigo(monkeypatch):
    monkeypatch.setenv("HRMM_BACKEND_SECRET", "secreto-de-prueba-no-real")
    gateway, http = _gateway_con_http(citas_por_documento={_DOCUMENTO_VALIDO: []})
    handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m1", "hola quiero una cita")
    handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m2", _DOCUMENTO_VALIDO)
    assert gateway._pending_identity[_TELEFONO]["stage"] == "esperando_codigo"

    r_correo = handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m3", "¿a cuál correo lo enviaron?")
    assert "no es válido" not in r_correo.lower() and "no válido" not in r_correo.lower()
    assert "p***@dominio.com" in r_correo
    assert _TELEFONO in gateway._pending_identity  # sigue esperando el código

    r_reenvio = handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m4", "no me llegó, reenviarme otro")
    assert "no es válido" not in r_reenvio.lower() and "no válido" not in r_reenvio.lower()
    assert "reenviamos" in r_reenvio.lower()
    assert sum(1 for c in http.llamadas if c["path"] == "/api/agenda/verificacion/enviar") == 2

    # Seguridad (requisito #4/decisión explícita, ver docstring de
    # `_MENSAJE_CITAS_ANTES_DE_VERIFICAR`): NO revela ninguna cita real
    # antes de confirmar el segundo factor — solo redirige.
    r_citas = handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m5", "cuales tengo reservadas")
    assert "no es válido" not in r_citas.lower() and "no válido" not in r_citas.lower()
    assert "cita activa" not in r_citas.lower()
    assert "confirmemos tu identidad" in r_citas.lower()
    assert _TELEFONO not in gateway._identidad_resuelta  # sigue sin identidad real

    r_salir = handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m6", "salir")
    assert "no es válido" not in r_salir.lower() and "no válido" not in r_salir.lower()
    assert _TELEFONO not in gateway._pending_identity  # sin estado residual
    assert _TELEFONO not in gateway._identidad_resuelta  # nunca quedó "medio identificado"


def test_salir_durante_gate_de_identidad_vuelve_al_punto_de_partida(monkeypatch):
    monkeypatch.setenv("HRMM_BACKEND_SECRET", "secreto-de-prueba-no-real")
    gateway, http = _gateway_con_http(citas_por_documento={_DOCUMENTO_VALIDO: []})

    # "salir" incluso ANTES de escribir ningún documento (stage
    # esperando_documento) — no debe tratarse como un documento inválido.
    handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m1", "hola")
    r_salir_temprano = handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m2", "exit")
    assert "no encontré" not in r_salir_temprano.lower()
    assert _TELEFONO not in gateway._pending_identity
    assert _TELEFONO not in gateway._identidad_resuelta

    # Reintentar desde cero: vuelve a pedir documento, limpio.
    respuesta_reintento = handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m3", "hola de nuevo")
    assert "documento" in respuesta_reintento.lower()
    assert gateway._pending_identity[_TELEFONO]["stage"] == "esperando_documento"

    # Y "salir" también funciona en esperando_codigo (documento ya
    # validado, código enviado) — mismo resultado: sin estado residual.
    handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m4", _DOCUMENTO_VALIDO)
    assert gateway._pending_identity[_TELEFONO]["stage"] == "esperando_codigo"
    r_salir_tardio = handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m5", "cancelar esto")
    assert _TELEFONO not in gateway._pending_identity
    assert _TELEFONO not in gateway._identidad_resuelta
    registro = gateway.identity_store.get(_TELEFONO)
    # La fila PENDIENTE_VERIFICACION puede quedar huérfana en
    # identity_store (inofensiva, nunca otorga acceso) — lo que importa
    # es que NUNCA quede VERIFICADO sin el segundo factor.
    assert registro is None or registro.estado.value != "VERIFICADO"


def test_wizard_identidad_reconoce_expresiones_con_errores_de_tipeo(monkeypatch):
    monkeypatch.setenv("HRMM_BACKEND_SECRET", "secreto-de-prueba-no-real")
    gateway, http = _gateway_con_http(citas_por_documento={_DOCUMENTO_VALIDO: []})

    handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m1", "hola")
    r_emocional_sin_documento = handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m2", "Estoy tristw")
    assert "no encontré" not in r_emocional_sin_documento.lower()
    assert "lamento" in r_emocional_sin_documento.lower()
    assert gateway._pending_identity[_TELEFONO]["stage"] == "esperando_documento"  # no perdió el progreso

    handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m3", _DOCUMENTO_VALIDO)
    r_emocional_con_codigo = handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m4", "Estoy tristw")
    assert "no es válido" not in r_emocional_con_codigo.lower() and "no válido" not in r_emocional_con_codigo.lower()
    assert "lamento" in r_emocional_con_codigo.lower()
    assert gateway._pending_identity[_TELEFONO]["stage"] == "esperando_codigo"


def test_codigo_y_documento_reales_siguen_funcionando_sin_confundirse_con_un_comando(monkeypatch):
    """Control anti-regresión: un documento/código real (numérico)
    nunca puntúa alto contra ninguna frase de las listas nuevas (ver
    recado 062 para la verificación empírica del umbral)."""
    monkeypatch.setenv("HRMM_BACKEND_SECRET", "secreto-de-prueba-no-real")
    gateway, http = _gateway_con_http(citas_por_documento={_DOCUMENTO_VALIDO: []})
    handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m1", "hola")
    handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m2", _DOCUMENTO_VALIDO)
    respuesta = handle_inbound_message(gateway, _TELEFONO, "chatwoot", "m3", _CODIGO_VALIDO)
    assert "confirmé tu identidad" in respuesta.lower()
