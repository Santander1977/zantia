"""
Autorregistro de pacientes nuevos por el chat (recados 097/098, diseño
aprobado por el usuario el 2026-09-30).

Wizard determinista, con el mismo patrón que el gate de identidad
(`gateway._pending_identity`): estado propio en `HealthGateway._pending_registro`,
independiente de ConversationState/Orchestrator (todavía no existe
ninguna Activity: el paciente ni siquiera está registrado).

Flujo:
    autorización (Ley 1581, aceptación EXPLÍCITA y determinista)
    → tipo de documento → nombre → fecha de nacimiento → correo → teléfono
    → EPS → régimen → resumen "¿Confirmas?"
    → hrmm: guarda la autorización y crea el registro PENDIENTE
    → código al correo (verificacion/enviar) → verificacion/confirmar
    → identidad de canal VERIFICADA (igual que un paciente existente).

Diferencia con el orden del recado 097 §2.5 (el código iba antes de
teléfono/EPS/régimen): con el contrato del recado 098 §3, hrmm envía el
código al correo de un registro que YA existe como pendiente (cambio
3), así que el registro pendiente se crea antes del código. Si el código
nunca se confirma, hrmm borra el pendiente a los 30 min (cambio 6).

Nada de esta información se guarda antes de la aceptación. Si el
paciente no acepta, no se persiste ningún dato personal.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Deque, Dict, List, Optional, Tuple

from core.timed_state import ModoVentana, TimedStateStore, VentanaDeTiempo

from .appointment_service import AppointmentServiceError
from .brain import _es_solicitud_de_salir
from .institutional_info import texto_contacto_hospital

if TYPE_CHECKING:  # pragma: no cover
    from .gateway import HealthGateway

logger = logging.getLogger("zantia.health.registro")

# ---------------------------------------------------------------------
# Catálogos cerrados (recado 098 §3, cambio 5). La lista de EPS NO vive
# aquí: se consulta a hrmm (`listar_eps`), para que nunca haya dos listas.
# ---------------------------------------------------------------------
TIPOS_DOCUMENTO: List[Tuple[str, str]] = [
    ("CC", "Cédula de ciudadanía"),
    ("CE", "Cédula de extranjería"),
    ("PPT", "Permiso por protección temporal"),
    ("PA", "Pasaporte"),
    ("TI", "Tarjeta de identidad"),
    ("RC", "Registro civil"),
]
_TIPOS_MENORES = {"TI", "RC"}  # menores: fuera de la v1 (decisión del usuario, 2026-09-30)

VALOR_PENDIENTE = "Pendiente"
REGIMENES: List[str] = ["Contributivo", "Subsidiado", "Especial o de excepción", "No afiliado (particular)"]
_OPCION_NO_SABE = "No sé / prefiero no decir"

# ---------------------------------------------------------------------
# Límites de abuso (recado 097 §6, D-14). En memoria de proceso, mismo
# límite ya aceptado para el resto del estado conversacional (R-11).
# ---------------------------------------------------------------------
_VENTANA_UN_REGISTRO_POR_IDENTIDAD = VentanaDeTiempo(
    duracion=timedelta(hours=24), modo=ModoVentana.BLOQUEO, nombre="registro_por_identidad"
)
_TOPE_GLOBAL_POR_HORA: Dict[str, int] = {"web": 10}  # el chat web es anónimo: tope propio más estricto
_TOPE_GLOBAL_POR_HORA_DEFAULT = 30
_MAX_INTENTOS_CODIGO = 3


@dataclass
class LimitesRegistro:
    """Un registro creado por identidad de canal cada 24 h, y un tope
    global por hora y por canal. Se cuenta al CREAR el registro en hrmm
    (no al empezar el wizard), que es lo que ocupa recursos reales."""

    por_identidad: TimedStateStore = field(default_factory=TimedStateStore)
    creaciones_por_canal: Dict[str, Deque[datetime]] = field(default_factory=dict)

    def puede_registrar(self, channel: str, patient_reference: str, *, ahora: Optional[datetime] = None) -> bool:
        ahora = ahora or datetime.now(timezone.utc)
        if self.por_identidad.dentro_de_ventana(f"{channel}:{patient_reference}", _VENTANA_UN_REGISTRO_POR_IDENTIDAD, ahora=ahora):
            return False
        creaciones = self.creaciones_por_canal.setdefault(channel, deque())
        while creaciones and ahora - creaciones[0] >= timedelta(hours=1):
            creaciones.popleft()
        tope = _TOPE_GLOBAL_POR_HORA.get(channel, _TOPE_GLOBAL_POR_HORA_DEFAULT)
        if len(creaciones) >= tope:
            logger.warning("Tope global de autorregistros por hora alcanzado en el canal %s (%d).", channel, tope)
            return False
        return True

    def registrar_creacion(self, channel: str, patient_reference: str, *, ahora: Optional[datetime] = None) -> None:
        ahora = ahora or datetime.now(timezone.utc)
        self.por_identidad.registrar(f"{channel}:{patient_reference}", ahora=ahora)
        self.creaciones_por_canal.setdefault(channel, deque()).append(ahora)


# ---------------------------------------------------------------------
# Textos
# ---------------------------------------------------------------------
def _mensaje_derivar(motivo: str) -> str:
    return f"{motivo} Puedes gestionarlo {texto_contacto_hospital()}."


MENSAJE_OPCIONES_DOCUMENTO_NO_ENCONTRADO = (
    "No encontré a nadie registrado con el documento {documento}. ¿Qué quieres hacer?\n"
    "1. Corregir el número\n"
    "2. Registrarme como paciente nuevo\n"
    "3. Contactar al hospital"
)
_MENSAJE_AUTORIZACION_RECHAZADA = (
    "Entendido, no guardé ningún dato tuyo. Sin tu autorización no puedo registrarte por este chat."
)
_MENSAJE_AUTORIZACION_NO_RECONOCIDA = "Para continuar necesito una respuesta explícita: escribe 1 (Acepto) o 2 (No acepto)."
_MENSAJE_SALIR = "De acuerdo, cancelé el registro y no guardé ningún dato tuyo. Cuando quieras retomarlo, escríbeme de nuevo."
_MENSAJE_MENOR = (
    "Por ahora el registro de menores de edad no está disponible por este chat: debe hacerlo su acudiente."
)
_MENSAJE_LIMITE = "Por ahora no puedo iniciar un registro nuevo desde esta conversación."
_MENSAJE_SERVICIO_NO_DISPONIBLE = "En este momento no puedo completar registros por este chat."
_MENSAJE_YA_EXISTE = (
    "Ya existe un registro (o uno en curso) con ese documento, así que no creé uno nuevo. "
    "Escríbeme de nuevo para verificar tu identidad con ese documento."
)


def _lista(opciones: List[str]) -> str:
    return "\n".join(f"{i}. {o}" for i, o in enumerate(opciones, start=1))


def _pregunta_tipo_documento() -> str:
    return "¿Qué tipo de documento tienes?\n" + _lista([nombre for _, nombre in TIPOS_DOCUMENTO])


def _texto_autorizacion(autorizacion: Dict[str, str]) -> str:
    return f"{autorizacion['texto']}\n1. Acepto\n2. No acepto"


# ---------------------------------------------------------------------
# Interpretación determinista de cada respuesta
# ---------------------------------------------------------------------
def _normalizar(texto: str) -> str:
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s@.+-]", " ", sin_tildes)).strip()


def interpretar_autorizacion(texto: str) -> Optional[bool]:
    """`True` SOLO ante "1", "acepto" o "sí acepto"; `False` ante "2",
    "no acepto" o "no"; `None` ante cualquier otra cosa (se vuelve a
    preguntar). Nunca un "sí"/"ok" suelto, nunca un LLM: la autorización
    de la Ley 1581 tiene que ser explícita e inequívoca (recado 098 §1.2)."""
    t = re.sub(r"[^\w\s]", " ", _normalizar(texto)).split()
    t = " ".join(t)
    if t in ("1", "acepto", "si acepto", "yo acepto"):
        return True
    if t in ("2", "no acepto", "no"):
        return False
    return None


def _elegir_de_lista(texto: str, opciones: List[str]) -> Optional[int]:
    """Índice por ordinal ("2") o por coincidencia exacta normalizada
    con el texto de una opción. Nunca aproxima."""
    t = _normalizar(texto)
    if t.isdigit() and 1 <= int(t) <= len(opciones):
        return int(t) - 1
    for i, opcion in enumerate(opciones):
        if t == _normalizar(opcion):
            return i
    return None


def _interpretar_tipo_documento(texto: str) -> Optional[str]:
    indice = _elegir_de_lista(texto, [nombre for _, nombre in TIPOS_DOCUMENTO])
    if indice is not None:
        return TIPOS_DOCUMENTO[indice][0]
    t = _normalizar(texto).replace(".", "").upper()
    return t if t in {codigo for codigo, _ in TIPOS_DOCUMENTO} else None


_RE_NOMBRE = re.compile(r"^[A-Za-zÁÉÍÓÚÜÑáéíóúüñ' -]+$")


def _interpretar_nombre(texto: str) -> Optional[str]:
    nombre = re.sub(r"\s+", " ", texto.strip())
    if not (5 <= len(nombre) <= 80) or not _RE_NOMBRE.match(nombre) or len(nombre.split()) < 2:
        return None
    return nombre


def _interpretar_fecha(texto: str, hoy: date) -> Optional[date]:
    m = re.fullmatch(r"\s*(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\s*", texto)
    if not m:
        return None
    try:
        fecha = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None
    if fecha > hoy or fecha.year < hoy.year - 120:
        return None
    return fecha


def _edad(nacimiento: date, hoy: date) -> int:
    return hoy.year - nacimiento.year - ((hoy.month, hoy.day) < (nacimiento.month, nacimiento.day))


_RE_CORREO = re.compile(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$")


def _interpretar_correo(texto: str) -> Optional[str]:
    correo = texto.strip().lower()
    return correo if _RE_CORREO.match(correo) else None


def _interpretar_telefono(texto: str) -> Optional[str]:
    digitos = re.sub(r"[\s().-]", "", texto.strip())
    if digitos.startswith("+57"):
        digitos = digitos[3:]
    if re.fullmatch(r"3\d{9}|60\d{8}", digitos):  # celular colombiano, o fijo nacional 60X
        return digitos
    return None


# ---------------------------------------------------------------------
# Entrada / salida del wizard
# ---------------------------------------------------------------------
def registro_disponible(gateway: "HealthGateway") -> bool:
    return getattr(gateway.appointment_service, "registrar_paciente", None) is not None


def iniciar_registro(gateway: "HealthGateway", patient_reference: str, channel: str, documento: str) -> str:
    """El paciente eligió "Registrarme" con un documento que no existe.
    Primer paso SIEMPRE la autorización: todavía no se guarda nada."""
    if not gateway._limites_registro.puede_registrar(channel, patient_reference):
        return _mensaje_derivar(_MENSAJE_LIMITE)
    try:
        autorizacion = gateway.appointment_service.obtener_autorizacion_vigente()
    except AppointmentServiceError as exc:
        logger.warning("Autorregistro sin texto de autorización vigente: %s", exc)
        return _mensaje_derivar(_MENSAJE_SERVICIO_NO_DISPONIBLE)
    gateway._pending_registro[patient_reference] = {
        "channel": channel,
        "stage": "autorizacion",
        "documento": documento,
        "autorizacion": autorizacion,
        "intentos_codigo": 0,
    }
    return _texto_autorizacion(autorizacion)


def _terminar(gateway: "HealthGateway", patient_reference: str, mensaje: str) -> str:
    gateway._pending_registro.pop(patient_reference, None)
    return mensaje


def procesar_mensaje_registro(gateway: "HealthGateway", patient_reference: str, text: str) -> str:
    pendiente = gateway._pending_registro[patient_reference]
    stage = pendiente["stage"]
    hoy = datetime.now(timezone.utc).date()

    if stage != "codigo" and _es_solicitud_de_salir(text):
        return _terminar(gateway, patient_reference, _MENSAJE_SALIR)

    if stage == "autorizacion":
        decision = interpretar_autorizacion(text)
        if decision is None:
            return _MENSAJE_AUTORIZACION_NO_RECONOCIDA
        if decision is False:
            logger.info("Autorregistro: autorización rechazada (sin datos personales guardados).")
            return _terminar(gateway, patient_reference, _mensaje_derivar(_MENSAJE_AUTORIZACION_RECHAZADA))
        pendiente["aceptado_en"] = datetime.now(timezone.utc).isoformat()
        pendiente["stage"] = "tipo_documento"
        return "Gracias. " + _pregunta_tipo_documento()

    if stage == "tipo_documento":
        tipo = _interpretar_tipo_documento(text)
        if tipo is None:
            return "No reconocí esa opción. " + _pregunta_tipo_documento()
        if tipo in _TIPOS_MENORES:
            return _terminar(gateway, patient_reference, _mensaje_derivar(_MENSAJE_MENOR))
        pendiente["tipo_documento"] = tipo
        pendiente["stage"] = "nombre"
        return "¿Cuál es tu nombre completo (nombres y apellidos)?"

    if stage == "nombre":
        nombre = _interpretar_nombre(text)
        if nombre is None:
            return "Escríbeme tu nombre completo, con nombres y apellidos (solo letras)."
        pendiente["nombre"] = nombre
        pendiente["stage"] = "fecha_nacimiento"
        return "¿Cuál es tu fecha de nacimiento? Escríbela como DD/MM/AAAA."

    if stage == "fecha_nacimiento":
        fecha = _interpretar_fecha(text, hoy)
        if fecha is None:
            return "No reconocí esa fecha. Escríbela como DD/MM/AAAA, por ejemplo 07/03/1985."
        if _edad(fecha, hoy) < 18:
            return _terminar(gateway, patient_reference, _mensaje_derivar(_MENSAJE_MENOR))
        pendiente["fecha_nacimiento"] = fecha.isoformat()
        pendiente["stage"] = "correo"
        return "¿Cuál es tu correo electrónico? Te enviaré ahí un código para verificarlo."

    if stage == "correo":
        correo = _interpretar_correo(text)
        if correo is None:
            return "Ese correo no parece válido. Escríbelo completo, por ejemplo nombre@dominio.com."
        pendiente["correo"] = correo
        pendiente["stage"] = "telefono"
        return "¿Cuál es tu número de teléfono? (celular de 10 dígitos)"

    if stage == "telefono":
        telefono = _interpretar_telefono(text)
        if telefono is None:
            return "No reconocí ese número. Escribe un celular de 10 dígitos, por ejemplo 3001234567."
        pendiente["telefono"] = telefono
        return _preguntar_eps(gateway, pendiente)

    if stage == "eps":
        opciones = pendiente["opciones_eps"]
        indice = _elegir_de_lista(text, opciones)
        if indice is None:
            return "No reconocí esa opción. Escribe el número de tu EPS:\n" + _lista(opciones)
        pendiente["eps"] = VALOR_PENDIENTE if opciones[indice] == _OPCION_NO_SABE else opciones[indice]
        pendiente["stage"] = "regimen"
        return (
            "¿A qué régimen perteneces? Esta respuesta también es opcional.\n"
            + _lista(REGIMENES + [_OPCION_NO_SABE])
        )

    if stage == "regimen":
        opciones = REGIMENES + [_OPCION_NO_SABE]
        indice = _elegir_de_lista(text, opciones)
        if indice is None:
            return "No reconocí esa opción. Escribe el número:\n" + _lista(opciones)
        pendiente["tipo_afiliacion"] = VALOR_PENDIENTE if indice == len(REGIMENES) else REGIMENES[indice]
        pendiente["stage"] = "confirmacion"
        return _resumen(pendiente)

    if stage == "confirmacion":
        indice = _elegir_de_lista(text, ["Confirmo", "Empezar de nuevo", "Cancelar"])
        if indice is None:
            return "Escribe 1 para confirmar, 2 para empezar de nuevo o 3 para cancelar."
        if indice == 2:
            return _terminar(gateway, patient_reference, _MENSAJE_SALIR)
        if indice == 1:
            for clave in ("tipo_documento", "nombre", "fecha_nacimiento", "correo", "telefono", "eps", "tipo_afiliacion"):
                pendiente.pop(clave, None)
            pendiente["stage"] = "tipo_documento"
            return "De acuerdo, empecemos de nuevo. " + _pregunta_tipo_documento()
        return _crear_registro_y_enviar_codigo(gateway, patient_reference, pendiente)

    if stage == "codigo":
        return _confirmar_codigo(gateway, patient_reference, pendiente, text)

    return _terminar(gateway, patient_reference, _MENSAJE_SALIR)  # etapa desconocida: nunca un limbo


def _preguntar_eps(gateway: "HealthGateway", pendiente: Dict[str, Any]) -> str:
    try:
        eps = [e for e in gateway.appointment_service.listar_eps() if e != VALOR_PENDIENTE]
    except AppointmentServiceError as exc:
        # La EPS es de respuesta facultativa (dato sensible, recado 098
        # §1.3): sin lista disponible queda Pendiente, nunca bloquea.
        logger.warning("Autorregistro sin lista de EPS (%s): queda Pendiente.", exc)
        pendiente["eps"] = VALOR_PENDIENTE
        pendiente["stage"] = "regimen"
        return "¿A qué régimen perteneces? Esta respuesta es opcional.\n" + _lista(REGIMENES + [_OPCION_NO_SABE])
    pendiente["opciones_eps"] = eps + [_OPCION_NO_SABE]
    pendiente["stage"] = "eps"
    return (
        "¿A qué EPS estás afiliado? Esta respuesta es opcional (es un dato sensible).\n"
        + _lista(pendiente["opciones_eps"])
    )


def _resumen(p: Dict[str, Any]) -> str:
    tipo = dict(TIPOS_DOCUMENTO)[p["tipo_documento"]]
    fecha = date.fromisoformat(p["fecha_nacimiento"]).strftime("%d/%m/%Y")
    eps = "No indicada" if p["eps"] == VALOR_PENDIENTE else p["eps"]
    regimen = "No indicado" if p["tipo_afiliacion"] == VALOR_PENDIENTE else p["tipo_afiliacion"]
    return (
        "Revisa tus datos:\n"
        f"- Documento: {tipo} {p['documento']}\n"
        f"- Nombre: {p['nombre']}\n"
        f"- Fecha de nacimiento: {fecha}\n"
        f"- Correo: {p['correo']}\n"
        f"- Teléfono: {p['telefono']}\n"
        f"- EPS: {eps}\n"
        f"- Régimen: {regimen}\n"
        "¿Están correctos?\n1. Confirmo\n2. Empezar de nuevo\n3. Cancelar"
    )


def _crear_registro_y_enviar_codigo(gateway: "HealthGateway", patient_reference: str, p: Dict[str, Any]) -> str:
    from .gateway import _mensaje_verificacion_no_disponible

    servicio = gateway.appointment_service
    canal = p["channel"]
    if not gateway._limites_registro.puede_registrar(canal, patient_reference):
        return _terminar(gateway, patient_reference, _mensaje_derivar(_MENSAJE_LIMITE))
    try:
        autorizacion_id = servicio.registrar_autorizacion(
            p["documento"], p["tipo_documento"], p["autorizacion"]["version"], p["autorizacion"]["sha256"],
            canal, p["aceptado_en"],
        )
        resultado = servicio.registrar_paciente({
            "documento_paciente": p["documento"],
            "tipo_documento": p["tipo_documento"],
            "nombre_paciente": p["nombre"],
            "fecha_nacimiento": p["fecha_nacimiento"],
            "correo": p["correo"],
            "telefono": p["telefono"],
            "eps": p["eps"],
            "tipo_afiliacion": p["tipo_afiliacion"],
            "autorizacion_id": autorizacion_id,
            "canal": canal,
        })
    except AppointmentServiceError as exc:
        logger.warning("Autorregistro: fallo al crear el registro (%s).", exc)
        return _terminar(gateway, patient_reference, _mensaje_derivar(_MENSAJE_SERVICIO_NO_DISPONIBLE))

    if resultado == "ya_existe":
        return _terminar(gateway, patient_reference, _MENSAJE_YA_EXISTE)

    gateway._limites_registro.registrar_creacion(canal, patient_reference)
    try:
        envio = servicio.send_verification_code(p["documento"])
    except AppointmentServiceError as exc:
        envio = {"enviado": False, "mensaje": f"No pude enviarte el código ({exc})."}
    if not envio.get("enviado", False):
        # Recado 096: sin código enviado, nada queda esperando un código.
        # El registro pendiente lo borra hrmm a los 30 min (cambio 6).
        return _terminar(gateway, patient_reference, _mensaje_verificacion_no_disponible(envio))

    p["stage"] = "codigo"
    destino = envio.get("correo_parcial") or p["correo"]
    return (
        f"Listo, creé tu registro. Te envié un código de 6 dígitos a {destino}: "
        "escríbelo aquí para confirmar tu correo y terminar."
    )


def _confirmar_codigo(gateway: "HealthGateway", patient_reference: str, p: Dict[str, Any], text: str) -> str:
    codigo = text.strip()
    if not re.fullmatch(r"\d{6}", codigo):
        # Nunca se envía a hrmm un texto que no es un código (recado 094):
        # ni gasta intentos ni viaja como dato.
        return "El código son 6 dígitos. Escríbelo tal cual te llegó al correo."
    try:
        valido = gateway.appointment_service.confirm_verification_code(p["documento"], codigo)
    except AppointmentServiceError as exc:
        return f"No pude confirmar el código ({exc}). Intenta de nuevo en un momento."
    if not valido:
        p["intentos_codigo"] += 1
        if p["intentos_codigo"] >= _MAX_INTENTOS_CODIGO:
            return _terminar(
                gateway, patient_reference,
                _mensaje_derivar("No pude confirmar tu correo después de varios intentos, así que no terminé el registro."),
            )
        return "Ese código no es válido o ya venció. Revisa el correo y escríbelo de nuevo."

    gateway._pending_registro.pop(patient_reference, None)
    gateway.identity_store.marcar_verificado(patient_reference, p["documento"], p["nombre"], p["correo"])
    gateway._identidad_resuelta[patient_reference] = p["documento"]
    logger.info("Autorregistro completado y correo verificado (canal %s).", p["channel"])
    nombre_corto = p["nombre"].split()[0]
    return (
        f"¡Listo, {nombre_corto}! Quedaste registrado y verifiqué tu correo. "
        "¿En qué te puedo ayudar hoy? Puedo programar, reprogramar, cancelar o consultar tus citas."
    )
