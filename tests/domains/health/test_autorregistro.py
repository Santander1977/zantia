"""
Recado 098 — autorregistro de pacientes nuevos por el chat.

hrmm-backend simulado (`FakeHttpClient`) que implementa EXACTAMENTE el
contrato propuesto en el recado 098 §3 (endpoints que hrmm todavía no
tiene). Los tests afirman además los payloads exactos que ZANTIA envía:
son la prueba de contrato del lado consumidor (`.claude/rules/testing.md`)
— si hrmm implementa otra forma, estos tests son la referencia.

Datos 100% ficticios, sin red.
"""
import hashlib
from datetime import date, timedelta

import pytest

from domains.health import MockActivitySource, MockActivityResultSink, ReminderManager
from domains.health.gateway import build_health_gateway, handle_inbound_message
from domains.health.hrmm_appointment_service import HrmmAppointmentService
from domains.health.hrmm_catalog import CatalogMirror
from domains.health.hrmm_http import FakeHttpClient, HttpResponse
from domains.health.institutional_info import INFORMACION_HOSPITAL
from domains.health.registro import interpretar_autorizacion

_TEXTO_AUTORIZACION = (
    "[BORRADOR SIN REVISIÓN LEGAL] Texto de autorización ficticio para pruebas "
    "(Ley 1581): finalidad, derechos y canal [PENDIENTE]."
)
_SHA = hashlib.sha256(_TEXTO_AUTORIZACION.encode("utf-8")).hexdigest()
_EPS = ["Nueva EPS", "Sura", "Otra", "Pendiente"]
_DOC_NUEVO = "10000098"
_DOC_EXISTENTE = "10000099"
_SESION = "sesion-web-098"
_CODIGO_OK = "123456"
_NACIMIENTO_ADULTO = "07/03/1985"


@pytest.fixture(autouse=True)
def _secreto_de_prueba(monkeypatch):
    monkeypatch.setenv("HRMM_BACKEND_SECRET", "secreto-de-prueba-no-real")


class _HrmmFalso:
    def __init__(self, *, sha=_SHA, eps_disponible=True, registro_status=201, enviado=True):
        self.llamadas = []
        self.pacientes = {_DOC_EXISTENTE: {"nombre_paciente": "Paciente Existente"}}
        self._sha = sha
        self._eps_disponible = eps_disponible
        self._registro_status = registro_status
        self._enviado = enviado

    def __call__(self, method, path, params, json_body, headers):
        self.llamadas.append((method, path, json_body))
        if method == "GET" and path == "/api/agenda/servicios":
            return HttpResponse(200, [{"servicio_id": "S1", "nombre": "odontologia"}])
        if method == "GET" and path == "/api/agenda/medicos":
            return HttpResponse(200, [{"medico_id": "M1", "nombre_completo": "Dr. Ficticio", "servicio_id": "S1", "consultorio": "Consultorio 4"}])
        if method == "GET" and path == "/api/agenda/citas/buscar-paciente":
            doc = params.get("documento")
            if doc in self.pacientes:
                return HttpResponse(200, {"nombre_paciente": self.pacientes[doc]["nombre_paciente"], "telefono": "300"})
            return HttpResponse(404, {"detail": "no encontrado"})
        if method == "GET" and path == "/api/agenda/citas":
            return HttpResponse(200, [])
        if method == "GET" and path == "/api/agenda/autorizacion-datos/vigente":
            return HttpResponse(200, {"version": "borrador-v0", "texto": _TEXTO_AUTORIZACION, "sha256": self._sha})
        if method == "GET" and path == "/api/agenda/eps":
            return HttpResponse(200, _EPS) if self._eps_disponible else HttpResponse(503, {})
        if method == "POST" and path == "/api/agenda/autorizacion-datos":
            return HttpResponse(201, {"autorizacion_id": "AUT-1"})
        if method == "POST" and path == "/api/agenda/pacientes/registro":
            if self._registro_status == 201:
                self.pacientes[json_body["documento_paciente"]] = dict(json_body)
            return HttpResponse(self._registro_status, {})
        if method == "POST" and path == "/api/agenda/verificacion/enviar":
            if self._enviado:
                return HttpResponse(200, {"enviado": True, "correo_parcial": "f***@ejemplo.com"})
            return HttpResponse(200, {"enviado": False, "mensaje": "No pudimos enviar el código — intenta de nuevo en un momento."})
        if method == "POST" and path == "/api/agenda/verificacion/confirmar":
            return HttpResponse(200 if json_body["codigo"] == _CODIGO_OK else 401, {})
        raise AssertionError(f"no programado: {method} {path}")

    def posts(self, path=None):
        return [(p, b) for m, p, b in self.llamadas if m == "POST" and (path is None or p == path)]


def _gateway(hrmm):
    http = FakeHttpClient(generador=hrmm)
    catalog = CatalogMirror()
    catalog.sync(http)
    return build_health_gateway(
        MockActivitySource(), HrmmAppointmentService(http, catalog), ReminderManager(), MockActivityResultSink()
    )


def _enviar(gateway, texto, sesion=_SESION, canal="web", _n=[0]):
    _n[0] += 1
    return handle_inbound_message(gateway, sesion, canal, f"m{_n[0]}", texto)


def _hasta_autorizacion(gateway, sesion=_SESION, canal="web", documento=_DOC_NUEVO):
    _enviar(gateway, "hola", sesion, canal)
    opciones = _enviar(gateway, documento, sesion, canal)
    assert "no encontré a nadie registrado" in opciones.lower()
    assert "2. registrarme como paciente nuevo" in opciones.lower()
    return _enviar(gateway, "2", sesion, canal)


def _hasta_resumen(gateway, sesion=_SESION, canal="web"):
    autorizacion = _hasta_autorizacion(gateway, sesion, canal)
    assert _TEXTO_AUTORIZACION in autorizacion
    for texto in ("1", "1", "Ana María Ficticia Pérez", _NACIMIENTO_ADULTO, "Ficticia@Ejemplo.com", "300 123 4567", "2", "1"):
        respuesta = _enviar(gateway, texto, sesion, canal)
    assert "revisa tus datos" in respuesta.lower()
    return respuesta


# ---------------------------------------------------------------------
# Camino completo + contrato exacto con hrmm
# ---------------------------------------------------------------------
def test_registro_completo_crea_pendiente_verifica_correo_y_resuelve_identidad():
    hrmm = _HrmmFalso()
    gateway = _gateway(hrmm)
    resumen = _hasta_resumen(gateway)
    assert "Cédula de ciudadanía 10000098" in resumen
    assert "EPS: Sura" in resumen and "Régimen: Contributivo" in resumen
    assert hrmm.posts() == [], "nada se envía a hrmm antes de confirmar el resumen"

    r_codigo = _enviar(gateway, "1")
    assert "creé tu registro" in r_codigo.lower()
    r_final = _enviar(gateway, _CODIGO_OK)

    assert "quedaste registrado" in r_final.lower()
    assert gateway._identidad_resuelta[_SESION] == _DOC_NUEVO
    assert _SESION not in gateway._pending_registro

    [(_, autorizacion)] = hrmm.posts("/api/agenda/autorizacion-datos")
    assert set(autorizacion) == {"documento_paciente", "tipo_documento", "version", "sha256", "canal", "aceptado_en"}
    assert (autorizacion["documento_paciente"], autorizacion["tipo_documento"]) == (_DOC_NUEVO, "CC")
    assert (autorizacion["version"], autorizacion["sha256"], autorizacion["canal"]) == ("borrador-v0", _SHA, "web")

    [(_, registro)] = hrmm.posts("/api/agenda/pacientes/registro")
    assert registro == {
        "documento_paciente": _DOC_NUEVO, "tipo_documento": "CC", "nombre_paciente": "Ana María Ficticia Pérez",
        "fecha_nacimiento": "1985-03-07", "correo": "ficticia@ejemplo.com", "telefono": "3001234567",
        "eps": "Sura", "tipo_afiliacion": "Contributivo", "autorizacion_id": "AUT-1", "canal": "web",
    }
    assert not hrmm.posts("/api/agenda/pacientes"), "nunca el upsert que sobrescribe correos (recado 097, E1)"
    orden = [p for p, _ in hrmm.posts()]
    assert orden == [
        "/api/agenda/autorizacion-datos", "/api/agenda/pacientes/registro",
        "/api/agenda/verificacion/enviar", "/api/agenda/verificacion/confirmar",
    ]


# ---------------------------------------------------------------------
# Autorización explícita (Ley 1581)
# ---------------------------------------------------------------------
@pytest.mark.parametrize("texto", ["1", "acepto", "Acepto.", "Sí, acepto", "si acepto"])
def test_aceptaciones_explicitas_reconocidas(texto):
    assert interpretar_autorizacion(texto) is True


@pytest.mark.parametrize("texto", ["sí", "si", "ok", "dale", "de acuerdo", "claro", "listo", "1 2"])
def test_respuestas_ambiguas_nunca_cuentan_como_aceptacion(texto):
    assert interpretar_autorizacion(texto) is None


def test_si_suelto_vuelve_a_preguntar_y_no_avanza():
    gateway = _gateway(_HrmmFalso())
    _hasta_autorizacion(gateway)
    respuesta = _enviar(gateway, "sí")
    assert "1 (acepto)" in respuesta.lower()
    assert gateway._pending_registro[_SESION]["stage"] == "autorizacion"


def test_rechazar_autorizacion_no_guarda_nada_y_deriva_al_hospital():
    hrmm = _HrmmFalso()
    gateway = _gateway(hrmm)
    _hasta_autorizacion(gateway)
    respuesta = _enviar(gateway, "2")
    assert "no guardé ningún dato" in respuesta.lower()
    assert INFORMACION_HOSPITAL.telefono_citas in respuesta
    assert hrmm.posts() == []
    assert _SESION not in gateway._pending_registro


def test_texto_de_autorizacion_con_hash_que_no_coincide_no_se_muestra():
    hrmm = _HrmmFalso(sha="0" * 64)
    gateway = _gateway(hrmm)
    respuesta = _hasta_autorizacion(gateway)
    assert _TEXTO_AUTORIZACION not in respuesta
    assert _SESION not in gateway._pending_registro


# ---------------------------------------------------------------------
# Menores (fuera de la v1), documento existente, salir
# ---------------------------------------------------------------------
@pytest.mark.parametrize("tipo", ["5", "6"])  # Tarjeta de identidad, Registro civil
def test_documento_de_menor_no_se_registra(tipo):
    hrmm = _HrmmFalso()
    gateway = _gateway(hrmm)
    _hasta_autorizacion(gateway)
    _enviar(gateway, "1")
    respuesta = _enviar(gateway, tipo)
    assert "menores de edad" in respuesta.lower()
    assert hrmm.posts() == []


def test_fecha_de_nacimiento_de_menor_no_se_registra():
    hrmm = _HrmmFalso()
    gateway = _gateway(hrmm)
    _hasta_autorizacion(gateway)
    for texto in ("1", "1", "Ana María Ficticia"):
        _enviar(gateway, texto)
    fecha_menor = (date.today() - timedelta(days=365 * 10)).strftime("%d/%m/%Y")
    respuesta = _enviar(gateway, fecha_menor)
    assert "menores de edad" in respuesta.lower()
    assert hrmm.posts() == []


def test_documento_ya_existente_o_en_curso_no_modifica_nada():
    hrmm = _HrmmFalso(registro_status=409)
    gateway = _gateway(hrmm)
    _hasta_resumen(gateway)
    respuesta = _enviar(gateway, "1")
    assert "ya existe un registro" in respuesta.lower()
    assert not hrmm.posts("/api/agenda/verificacion/enviar")
    assert _SESION not in gateway._pending_registro


def test_documento_existente_nunca_ofrece_registro():
    gateway = _gateway(_HrmmFalso(enviado=True))
    _enviar(gateway, "hola")
    respuesta = _enviar(gateway, _DOC_EXISTENTE)
    assert "registrarme" not in respuesta.lower()
    assert "código" in respuesta.lower()


def test_salir_a_mitad_del_registro_no_guarda_nada():
    hrmm = _HrmmFalso()
    gateway = _gateway(hrmm)
    _hasta_autorizacion(gateway)
    _enviar(gateway, "1")
    _enviar(gateway, "1")
    respuesta = _enviar(gateway, "quiero salir")
    assert "cancelé el registro" in respuesta.lower()
    assert hrmm.posts() == []


def test_escribir_otro_numero_en_las_opciones_es_una_correccion():
    hrmm = _HrmmFalso(enviado=True)
    gateway = _gateway(hrmm)
    _enviar(gateway, "hola")
    _enviar(gateway, _DOC_NUEVO)
    respuesta = _enviar(gateway, _DOC_EXISTENTE)
    assert "código" in respuesta.lower()
    assert _SESION not in gateway._pending_registro


# ---------------------------------------------------------------------
# Código de verificación
# ---------------------------------------------------------------------
def test_texto_que_no_es_un_codigo_nunca_viaja_a_hrmm():
    hrmm = _HrmmFalso()
    gateway = _gateway(hrmm)
    _hasta_resumen(gateway)
    _enviar(gateway, "1")
    respuesta = _enviar(gateway, "ficticia@ejemplo.com")
    assert "6 dígitos" in respuesta
    assert not hrmm.posts("/api/agenda/verificacion/confirmar")


def test_tres_codigos_invalidos_terminan_el_registro_sin_bucle():
    hrmm = _HrmmFalso()
    gateway = _gateway(hrmm)
    _hasta_resumen(gateway)
    _enviar(gateway, "1")
    _enviar(gateway, "000000")
    _enviar(gateway, "000001")
    respuesta = _enviar(gateway, "000002")
    assert "no terminé el registro" in respuesta.lower()
    assert _SESION not in gateway._pending_registro
    assert _SESION not in gateway._identidad_resuelta


def test_codigo_no_enviado_no_deja_nada_esperando_un_codigo():
    hrmm = _HrmmFalso(enviado=False)
    gateway = _gateway(hrmm)
    _hasta_resumen(gateway)
    respuesta = _enviar(gateway, "1")
    assert "no te envié ningún código" in respuesta.lower()
    assert _SESION not in gateway._pending_registro


# ---------------------------------------------------------------------
# EPS opcional
# ---------------------------------------------------------------------
def test_no_sabe_eps_ni_regimen_queda_pendiente():
    hrmm = _HrmmFalso()
    gateway = _gateway(hrmm)
    _hasta_autorizacion(gateway)
    for texto in ("1", "1", "Ana María Ficticia", _NACIMIENTO_ADULTO, "ficticia@ejemplo.com", "3001234567"):
        respuesta = _enviar(gateway, texto)
    assert "opcional" in respuesta.lower()
    assert "Pendiente" not in respuesta  # nunca se muestra como EPS elegible
    _enviar(gateway, str(len(_EPS)))  # última opción: "No sé / prefiero no decir"
    _enviar(gateway, "5")
    _enviar(gateway, "1")
    [(_, registro)] = hrmm.posts("/api/agenda/pacientes/registro")
    assert (registro["eps"], registro["tipo_afiliacion"]) == ("Pendiente", "Pendiente")


def test_sin_lista_de_eps_disponible_no_bloquea_y_queda_pendiente():
    hrmm = _HrmmFalso(eps_disponible=False)
    gateway = _gateway(hrmm)
    _hasta_autorizacion(gateway)
    for texto in ("1", "1", "Ana María Ficticia", _NACIMIENTO_ADULTO, "ficticia@ejemplo.com", "3001234567"):
        respuesta = _enviar(gateway, texto)
    assert "régimen" in respuesta.lower()
    _enviar(gateway, "1")
    _enviar(gateway, "1")
    [(_, registro)] = hrmm.posts("/api/agenda/pacientes/registro")
    assert registro["eps"] == "Pendiente"


# ---------------------------------------------------------------------
# Límites de abuso
# ---------------------------------------------------------------------
def test_una_misma_identidad_no_puede_crear_dos_registros_en_24_horas():
    """Abuso realista: crear un registro pendiente, abandonarlo (código
    nunca confirmado) e intentar crear otro desde la misma identidad."""
    hrmm = _HrmmFalso()
    gateway = _gateway(hrmm)
    _hasta_resumen(gateway)
    _enviar(gateway, "1")
    for codigo in ("000000", "000001", "000002"):
        _enviar(gateway, codigo)
    assert _SESION not in gateway._identidad_resuelta

    _enviar(gateway, "hola")
    _enviar(gateway, "10000097")
    respuesta = _enviar(gateway, "2")
    assert "no puedo iniciar un registro nuevo" in respuesta.lower()
    assert len(hrmm.posts("/api/agenda/pacientes/registro")) == 1


def test_tope_global_por_hora_del_chat_web():
    hrmm = _HrmmFalso()
    gateway = _gateway(hrmm)
    for i in range(10):
        gateway._limites_registro.registrar_creacion("web", f"otra-sesion-{i}")
    respuesta = _hasta_autorizacion(gateway)
    assert "no puedo iniciar un registro nuevo" in respuesta.lower()
    assert _SESION not in gateway._pending_registro
