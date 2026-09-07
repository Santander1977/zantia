"""
HrmmAppointmentService — adaptador REAL que implementa el Protocol
`AppointmentService` (`appointment_service.py`, sin tocar) contra la
API real de hrmm-backend, verificada leyendo su código fuente
(`hrmm/backend/app/api/agenda.py`, `app/schemas/agenda.py`,
`app/trusted_auth.py`, `app/recovery_codes.py` — solo lectura, ningún
archivo de hrmm fue modificado).

Contrato real confirmado (no asumido):
- GET  /api/agenda/disponibilidad      — público, filtra por medico_id/fecha (NO por servicio)
- POST /api/agenda/citas               — público (rate-limited), body {slot_id, documento_paciente, nombre_paciente, telefono, correo?, canal}
- GET  /api/agenda/citas               — requiere X-Backend-Secret, filtra por documento_paciente/desde/hasta/estados[]
- GET  /api/agenda/citas/{id}          — requiere X-Backend-Secret
- POST /api/agenda/citas/{id}/reprogramar — requiere X-Backend-Secret + query params nuevo_slot_id, documento_paciente, codigo
- POST /api/agenda/citas/{id}/cancelar    — requiere X-Backend-Secret + query params documento_paciente, codigo
- GET  /api/agenda/citas/buscar-paciente  — público, ?documento=... -> {nombre_paciente, telefono}
- GET  /api/agenda/servicios, /medicos    — públicos (ver hrmm_catalog.py)
- POST /api/agenda/verificacion/enviar    — requiere X-Backend-Secret, body {documento_paciente} -> código de 6 dígitos por CORREO (vía webhook n8n, TTL 10 min, 5 intentos, un solo uso)
- POST /api/agenda/verificacion/confirmar — [PROPUESTO, NO CONFIRMADO] contrato mínimo que ZANTIA necesita para verificar identidad de canal (recado 014) sin estar atado a cancelar/reprogramar una cita. A diferencia del resto de este archivo (verificado leyendo el código fuente real de hrmm-backend), este endpoint TODAVÍA NO EXISTE ahí: `app/recovery_codes.py:verificar_codigo(documento_paciente, codigo)` es genérico (no depende de ninguna cita), pero hoy solo se invoca dentro de `cancelar_cita`/`reprogramar_cita` (`app/api/agenda.py`), ambos con `cita_id` obligatorio en la URL. Decisión explícita del usuario (2026-09-02): construir el lado ZANTIA contra este contrato documentado, y coordinar el endpoint real como trabajo aparte en el repositorio de hrmm-backend antes de desplegar `confirm_verification_code` contra la red real — ver `.ai/RISKS.md` (riesgo nuevo, bloqueante) y `domains/health/identity_store.py`.

Identidad: hrmm-backend identifica pacientes por `documento_paciente`
(texto libre, sin formato validado). Convención de este adaptador,
documentada explícitamente: cuando `HrmmAppointmentService` está
activo, `patient_reference` (concepto interno de ZANTIA) SIEMPRE es el
documento de identidad real del paciente — resuelto antes de operar
(ver `resolve_patient_identity` y `gateway.py`).
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any, Dict, List, Optional

from .appointment_service import AppointmentNotFoundError, AppointmentServiceError, SlotNotAvailableError
from .hrmm_catalog import CatalogMirror
from .hrmm_http import HttpClient, HttpError
from .models import Appointment, AppointmentStatus, AvailabilitySlot

logger = logging.getLogger("zantia.health")

# PENDIENTE DE VALIDACIÓN (sigue siendo INFERENCIA, no confirmada):
# el código fuente tipa `Cita.estado` como `str` libre, sin enum
# documentado, y `GET /api/agenda/citas` (el único endpoint que
# devuelve este campo) exige `X-Backend-Secret` — no se llamó en esta
# sesión (2026-09-01) por decisión explícita del usuario de no usar el
# secreto de escritura. Confirmado por HTTP real: sin secreto responde
# 401 "No autorizado." (ver recado 010).
#
# Vocabulario real CONFIRMADO (recado 032, 2026-09-06) — llamada real,
# de solo lectura, a `GET /api/agenda/citas?documento_paciente=...`
# para un documento real con historial variado: los 5 valores reales
# observados fueron "agendada", "atendida", "cancelada", "reprogramada",
# "no_show". Esto CIERRA `R-9` (antes "INFERENCIA no confirmada" —
# "reservada"/"confirmada"/"no_asistio" eran adivinanzas razonables que
# resultaron ser INCORRECTAS: una cita recién creada llega en
# "agendada", no "reservada"/"confirmada" — y "no_show" no
# "no_asistio"/"no_asistió"). Causa raíz directa del bug del recado 032
# (la reserva se completaba de verdad pero nunca se reportaba como
# exitosa: "agendada" no estaba en este mapa, caía al default
# `REQUESTED`). Los valores viejos se mantienen como alias adicionales
# (no hacen daño, por si alguna variante interna de hrmm-backend
# todavía los usa en otro contexto no visto en esta muestra).
_MAPA_ESTADO_HRMM: Dict[str, AppointmentStatus] = {
    "agendada": AppointmentStatus.CONFIRMED,
    "reservada": AppointmentStatus.CONFIRMED,
    "confirmada": AppointmentStatus.CONFIRMED,
    "reprogramada": AppointmentStatus.RESCHEDULED,
    "cancelada": AppointmentStatus.CANCELLED,
    "atendida": AppointmentStatus.ATTENDED,
    "no_show": AppointmentStatus.NO_SHOW,
    "no_asistio": AppointmentStatus.NO_SHOW,
    "no_asistió": AppointmentStatus.NO_SHOW,
}


def _mapear_estado(estado_hrmm: str) -> AppointmentStatus:
    return _MAPA_ESTADO_HRMM.get(estado_hrmm.strip().lower(), AppointmentStatus.REQUESTED)


class VerificationRequiredError(AppointmentServiceError):
    """Señala al gateway que esta operación necesita el sub-flujo de
    código de verificación (ver docstring del módulo) — nunca se
    ejecuta cancelar/reprogramar reales sin un código válido."""


class HrmmAppointmentService:
    """`requires_verification_code = True` — marcador que el gateway
    usa para decidir si activar el sub-flujo de código (nunca aplica a
    `MockAppointmentService`, que no lo declara).

    Nota de nombres de variable (para no confundirlas, aunque el VALOR
    es el mismo secreto compartido): del lado de hrmm-backend, esa
    variable se llama internamente `BACKEND_TRUSTED_SECRET` (confirmado
    en su código). Del lado de ZANTIA, se lee de `HRMM_BACKEND_SECRET`
    (ver `.env.example`) — el usuario copia el mismo valor real desde
    EasyPanel a ambos lados; nunca se pasa por chat ni se hardcodea."""

    requires_verification_code = True

    def __init__(
        self,
        http_client: HttpClient,
        catalog_mirror: CatalogMirror,
        trusted_secret_env_var: str = "HRMM_BACKEND_SECRET",
    ) -> None:
        self._http = http_client
        self._catalog = catalog_mirror
        self._trusted_secret_env_var = trusted_secret_env_var
        self._lock = threading.Lock()
        # Cache de contacto por documento, poblada por identidad
        # resuelta (buscar-paciente) o por la conversación — necesaria
        # porque el Protocol `book_appointment` no lleva nombre/teléfono
        # explícitos (ver docstring del módulo y del gateway).
        self._contactos: Dict[str, Dict[str, str]] = {}
        # Cache de bloques crudos por slot_id, poblada en get_availability
        # — usada para el chequeo de idempotencia por fecha/servicio.
        self._slots_crudos: Dict[str, Dict[str, Any]] = {}
        self._idempotencia: Dict[str, str] = {}

    # ------------------------------------------------------------------
    def _headers_confianza(self) -> Dict[str, str]:
        secreto = os.environ.get(self._trusted_secret_env_var)
        if not secreto:
            raise AppointmentServiceError(
                f"Variable de entorno {self._trusted_secret_env_var} no configurada "
                "(ver .env.example) — no se puede autenticar contra hrmm-backend."
            )
        return {"X-Backend-Secret": secreto}

    def register_patient_contact(self, documento_paciente: str, nombre: str, telefono: str) -> None:
        """No es parte del Protocol `AppointmentService` — método propio
        de este adaptador, llamado por el gateway tras resolver
        identidad (buscar-paciente o conversación) antes de reservar."""
        self._contactos[documento_paciente] = {"nombre": nombre, "telefono": telefono}

    def buscar_paciente(self, documento_paciente: str) -> Optional[Dict[str, str]]:
        """GET /api/agenda/citas/buscar-paciente — público, sin auth."""
        respuesta = self._http.request(
            "GET", "/api/agenda/citas/buscar-paciente", params={"documento": documento_paciente}
        )
        if respuesta.status == 404:
            return None
        if respuesta.status != 200:
            raise AppointmentServiceError(f"buscar-paciente respondió {respuesta.status}")
        return respuesta.body  # {"nombre_paciente":..., "telefono":...}

    def list_services(self) -> List[str]:
        """Extensión duck-typed (recado 027, mismo criterio que
        `buscar_paciente`/`requires_verification_code` — no forma parte
        del Protocol `AppointmentService` formal): nombres reales del
        catálogo ya sincronizado (`CatalogMirror`, `GET
        /api/agenda/servicios`), nunca inventados. Si el catálogo
        todavía no sincronizó, devuelve una lista vacía — quien llama
        decide el mensaje de fallback, esto nunca inventa un nombre."""
        return self._catalog.listar_nombres()

    # ------------------------------------------------------------------
    # AppointmentService Protocol
    # ------------------------------------------------------------------
    def get_availability(
        self, service: str, specialty: Optional[str] = None, location: Optional[str] = None
    ) -> List[AvailabilitySlot]:
        servicio_id = self._catalog.servicio_id_por_nombre(service)
        if servicio_id is None:
            # Nunca se inventa un servicio: si no está en el espejo
            # sincronizado, no hay disponibilidad que ofrecer.
            return []

        respuesta = self._http.request("GET", "/api/agenda/disponibilidad")
        if respuesta.status != 200:
            raise AppointmentServiceError(f"disponibilidad respondió {respuesta.status}")

        resultado: List[AvailabilitySlot] = []
        for bloque in respuesta.body:
            if bloque.get("servicio_id") != servicio_id:
                continue
            # HECHO (2026-09-01, ver recado 010): se confirmó por HTTP real
            # contra producción de hrmm-backend (GET /api/agenda/disponibilidad,
            # sin filtros, 10311 bloques) que `BloqueDisponibilidad.estado`
            # SOLO toma dos valores reales: "Libre" y "Reservado". Se usa un
            # allowlist explícito (solo "libre" se ofrece) en vez del denylist
            # anterior por substring — así un valor nuevo/no contemplado se
            # excluye por defecto (conservador) en vez de ofrecerse por error.
            estado = str(bloque.get("estado", "")).strip().lower()
            if estado != "libre":
                continue
            medico = self._catalog.medico(bloque["medico_id"])
            consultorio = medico.consultorio if medico else None
            if location is not None and (consultorio or "").strip().lower() != location.strip().lower():
                continue
            self._slots_crudos[bloque["slot_id"]] = bloque
            resultado.append(
                AvailabilitySlot(
                    slot_id=bloque["slot_id"],
                    service=service,
                    professional=medico.nombre_completo if medico else bloque["medico_id"],
                    location=consultorio or "",
                    date=bloque["fecha"],
                    time=bloque["hora_inicio"],
                )
            )
        return resultado

    def book_appointment(
        self, slot_id: str, patient_reference: str, idempotency_key: str, correo: Optional[str] = None
    ) -> Appointment:
        with self._lock:
            if idempotency_key in self._idempotencia:
                return self._reconstruir_appointment(self._idempotencia[idempotency_key])

        # Idempotencia adicional (sección "problema a resolver: idempotencia"):
        # antes de reservar, se verifica si ya existe una cita activa
        # equivalente (mismo paciente/servicio/fecha) — crítico para el
        # camino Activity, donde un reintento del sistema IPS podría
        # disparar la misma gestión dos veces con una idempotency_key distinta.
        bloque = self._slots_crudos.get(slot_id)
        if bloque is not None:
            medico_del_slot = self._catalog.medico(bloque["medico_id"])
            servicio_id_del_slot = medico_del_slot.servicio_id if medico_del_slot else None
            nombre_servicio_del_slot = (
                self._catalog.nombre_por_servicio_id(servicio_id_del_slot) if servicio_id_del_slot else None
            )
            if nombre_servicio_del_slot is not None:
                existentes = self.get_patient_appointments(patient_reference)
                for cita in existentes:
                    misma_fecha = cita.date == bloque["fecha"]
                    mismo_servicio = cita.service == nombre_servicio_del_slot
                    esta_activa = cita.status in (AppointmentStatus.CONFIRMED, AppointmentStatus.RESCHEDULED)
                    if esta_activa and misma_fecha and mismo_servicio:
                        return cita  # ya existe una equivalente — no se duplica

        contacto = self._contactos.get(patient_reference, {})
        respuesta = self._http.request(
            "POST",
            "/api/agenda/citas",
            json_body={
                "slot_id": slot_id,
                "documento_paciente": patient_reference,
                "nombre_paciente": contacto.get("nombre", ""),
                "telefono": contacto.get("telefono", ""),
                "canal": "zantia",
            },
        )
        if respuesta.status == 409:
            raise SlotNotAvailableError(slot_id)
        if respuesta.status not in (200, 201):
            raise AppointmentServiceError(f"book_appointment respondió {respuesta.status}: {respuesta.body}")

        cita = respuesta.body
        with self._lock:
            self._idempotencia[idempotency_key] = cita["cita_id"]
        creada = self._cita_a_appointment(cita)
        # Recado 054/058 — hallazgo real: `POST /api/agenda/citas` NUNCA
        # dispara ningún correo por sí solo (confirmado leyendo el
        # código real de hrmm-backend) — enviar la confirmación es
        # SIEMPRE un segundo paso explícito y separado
        # (`enviar_confirmacion_email`, abajo). `correo` explícito tiene
        # prioridad; si no se pasó, se usa el que ya estuviera cacheado
        # por `register_patient_contact` (nunca se inventa uno).
        correo_efectivo = correo or contacto.get("correo")
        enviado = self._intentar_enviar_confirmacion(creada.appointment_id, correo_efectivo)
        return creada.model_copy(update={"correo_confirmacion_enviado": enviado})

    def confirm_appointment(self, appointment_id: str) -> Appointment:
        """hrmm-backend confirma la cita de forma atómica dentro del
        propio POST /api/agenda/citas (ver book_appointment) — no existe
        un segundo paso real que llamar. Se implementa como una simple
        relectura, para no cambiar el contrato de dos pasos que ya
        exige `BookAppointmentTool` (tools.py, sin tocar)."""
        cita = self.get_appointment(appointment_id)
        if cita is None:
            raise AppointmentNotFoundError(appointment_id)
        return cita

    def cancel_appointment(self, appointment_id: str) -> Appointment:
        """Firma exigida por el Protocol — pero hrmm-backend exige
        también documento_paciente + codigo (ver
        cancel_appointment_verified). Llamar esto directo SIEMPRE
        lanza VerificationRequiredError: es la señal explícita para que
        el gateway sepa que debe pasar por el sub-flujo de código antes
        de reintentar — nunca se ejecuta una cancelación real sin
        verificación."""
        raise VerificationRequiredError(
            "cancel_appointment requiere documento_paciente + codigo — usar "
            "cancel_appointment_verified tras el sub-flujo de verificación."
        )

    def reschedule_appointment(self, appointment_id: str, new_slot_id: str, idempotency_key: str) -> Appointment:
        raise VerificationRequiredError(
            "reschedule_appointment requiere documento_paciente + codigo — usar "
            "reschedule_appointment_verified tras el sub-flujo de verificación."
        )

    def get_appointment(self, appointment_id: str) -> Optional[Appointment]:
        respuesta = self._http.request(
            "GET", f"/api/agenda/citas/{appointment_id}", headers=self._headers_confianza()
        )
        if respuesta.status == 404:
            return None
        if respuesta.status != 200:
            raise AppointmentServiceError(f"get_appointment respondió {respuesta.status}")
        return self._cita_a_appointment(respuesta.body)

    def get_patient_appointments(self, patient_reference: str) -> List[Appointment]:
        respuesta = self._http.request(
            "GET",
            "/api/agenda/citas",
            params={"documento_paciente": patient_reference},
            headers=self._headers_confianza(),
        )
        if respuesta.status != 200:
            raise AppointmentServiceError(f"get_patient_appointments respondió {respuesta.status}")
        return [self._cita_a_appointment(c) for c in respuesta.body]

    # ------------------------------------------------------------------
    # Métodos propios (fuera del Protocol) para el sub-flujo de verificación
    # ------------------------------------------------------------------
    def send_verification_code(self, documento_paciente: str) -> Dict[str, Any]:
        """POST /api/agenda/verificacion/enviar — código de 6 dígitos
        por correo, TTL 10 min, 5 intentos, un solo uso (confirmado
        leyendo app/recovery_codes.py)."""
        respuesta = self._http.request(
            "POST",
            "/api/agenda/verificacion/enviar",
            json_body={"documento_paciente": documento_paciente},
            headers=self._headers_confianza(),
        )
        if respuesta.status != 200:
            raise AppointmentServiceError(f"verificacion/enviar respondió {respuesta.status}: {respuesta.body}")
        return respuesta.body  # {"enviado": bool, "mensaje": str, "correo_parcial": Optional[str]}

    def confirm_verification_code(self, documento_paciente: str, codigo: str) -> bool:
        """POST /api/agenda/verificacion/confirmar — [PROPUESTO, ver
        docstring del módulo]: confirma (y consume, un solo uso) un
        código de verificación SIN atarlo a cancelar/reprogramar una
        cita — necesario para el gate de identidad de canal (recado
        014, `domains/health/identity_store.py`). Se asume 200 =
        válido, 401 = inválido/vencido/agotado (mismo código que ya
        usan `cancelar`/`reprogramar` para el mismo caso, ver
        `cancel_appointment_verified`) — nunca se inventa un tercer
        estado."""
        respuesta = self._http.request(
            "POST",
            "/api/agenda/verificacion/confirmar",
            json_body={"documento_paciente": documento_paciente, "codigo": codigo},
            headers=self._headers_confianza(),
        )
        if respuesta.status == 200:
            return True
        if respuesta.status == 401:
            return False
        raise AppointmentServiceError(f"verificacion/confirmar respondió {respuesta.status}: {respuesta.body}")

    def cancel_appointment_verified(
        self, appointment_id: str, documento_paciente: str, codigo: str, correo: Optional[str] = None
    ) -> Appointment:
        respuesta = self._http.request(
            "POST",
            f"/api/agenda/citas/{appointment_id}/cancelar",
            params={"documento_paciente": documento_paciente, "codigo": codigo},
            headers=self._headers_confianza(),
        )
        if respuesta.status == 401:
            raise AppointmentServiceError("codigo inválido o vencido")
        if respuesta.status == 404:
            raise AppointmentNotFoundError(appointment_id)
        if respuesta.status != 200:
            raise AppointmentServiceError(f"cancelar respondió {respuesta.status}: {respuesta.body}")
        cancelada = self._cita_a_appointment(respuesta.body)
        # Recado 054/058 — mismo hallazgo que book_appointment: cancelar
        # (vía el endpoint de canal de confianza que ZANTIA usa) NUNCA
        # dispara ningún correo por sí solo — confirmado leyendo el
        # código real de hrmm-backend (`cancelar_cita`, backend/app/api/
        # agenda.py, nunca llama a `_enviar_correo_notificacion`; ese
        # helper solo lo usan los endpoints del portal público). El
        # mismo endpoint genérico `enviar-confirmacion` sirve para los 3
        # casos (reservar/cancelar/reprogramar) — el lado de n8n elige
        # la plantilla mirando el estado REAL de la cita, no un
        # parámetro que ZANTIA tenga que decidir.
        enviado = self._intentar_enviar_confirmacion(appointment_id, correo)
        return cancelada.model_copy(update={"correo_confirmacion_enviado": enviado})

    def reschedule_appointment_verified(
        self, appointment_id: str, new_slot_id: str, documento_paciente: str, codigo: str,
        correo: Optional[str] = None,
    ) -> Appointment:
        respuesta = self._http.request(
            "POST",
            f"/api/agenda/citas/{appointment_id}/reprogramar",
            params={"nuevo_slot_id": new_slot_id, "documento_paciente": documento_paciente, "codigo": codigo},
            headers=self._headers_confianza(),
        )
        if respuesta.status == 401:
            raise AppointmentServiceError("codigo inválido o vencido")
        if respuesta.status == 404:
            raise AppointmentNotFoundError(appointment_id)
        if respuesta.status == 409:
            raise SlotNotAvailableError(new_slot_id)
        if respuesta.status != 200:
            raise AppointmentServiceError(f"reprogramar respondió {respuesta.status}: {respuesta.body}")
        reprogramada = self._cita_a_appointment(respuesta.body)
        # Recado 054/058 — mismo hallazgo, ver cancel_appointment_verified arriba.
        enviado = self._intentar_enviar_confirmacion(appointment_id, correo)
        return reprogramada.model_copy(update={"correo_confirmacion_enviado": enviado})

    # ------------------------------------------------------------------
    # Correo de confirmación real (recado 054/058) — SIEMPRE un segundo
    # paso explícito, nunca disparado automáticamente por hrmm-backend
    # al reservar/cancelar/reprogramar (ver docstring de book_appointment).
    # ------------------------------------------------------------------
    def enviar_confirmacion_email(self, appointment_id: str, correo: str) -> Dict[str, Any]:
        """POST /api/agenda/citas/{id}/enviar-confirmacion — intermediario
        hacia el webhook real de n8n que envía el correo (confirmado
        real y probado muchas veces desde el propio portal de citas,
        ver docs/progreso.md del repo hrmm). Público (solo rate-limited,
        sin `X-Backend-Secret`) — el mismo endpoint que usa el botón
        "Enviar por correo" del portal público, confirmado leyendo
        `backend/app/api/agenda.py:enviar_confirmacion` (repo hrmm, solo
        lectura)."""
        respuesta = self._http.request(
            "POST",
            f"/api/agenda/citas/{appointment_id}/enviar-confirmacion",
            json_body={"email": correo},
        )
        if respuesta.status != 200:
            raise AppointmentServiceError(
                f"enviar-confirmacion respondió {respuesta.status}: {respuesta.body}"
            )
        return respuesta.body  # {"exito": bool, "estado": str, "mensaje": str}

    def _intentar_enviar_confirmacion(self, appointment_id: str, correo: Optional[str]) -> Optional[bool]:
        """Best-effort — NUNCA revierte ni rompe la acción principal
        (reservar/cancelar/reprogramar) ya exitosa, que quedó bien
        hecha independientemente de esto (recado 058, requisito #3: un
        fallo aquí se registra, nunca se expone como error al
        paciente). Devuelve `None` si no había ningún correo disponible
        para intentar (nunca se hizo ninguna llamada de red — distinto
        de "se intentó y falló", `False`) — `True` solo si hrmm-backend
        confirmó el envío real."""
        if not correo:
            return None
        try:
            resultado = self.enviar_confirmacion_email(appointment_id, correo)
        except AppointmentServiceError as exc:
            logger.warning(
                "No se pudo enviar el correo de confirmación real para %s: %s", appointment_id, exc
            )
            return False
        exito = bool(resultado.get("exito"))
        if not exito:
            logger.warning(
                "hrmm-backend no confirmó el envío del correo de confirmación para %s: %r",
                appointment_id, resultado,
            )
        return exito

    # ------------------------------------------------------------------
    def _cita_a_appointment(self, cita: Dict[str, Any]) -> Appointment:
        medico = self._catalog.medico(cita.get("medico_id", ""))
        servicio_id = medico.servicio_id if medico else cita.get("servicio_id", "")
        # `service` guarda el NOMBRE legible (no el servicio_id crudo) —
        # necesario para que get_availability(cita.service) pueda
        # resolverlo de vuelta contra el espejo de catálogo (bug
        # encontrado probando el wizard de reprogramación: ver recado).
        nombre_servicio = self._catalog.nombre_por_servicio_id(servicio_id) or servicio_id
        return Appointment(
            appointment_id=cita["cita_id"],
            patient_reference=cita["documento_paciente"],
            service=nombre_servicio,
            professional=medico.nombre_completo if medico else cita.get("medico_id"),
            location=medico.consultorio if medico else None,
            date=cita["fecha"],
            time=cita["hora_inicio"],
            status=_mapear_estado(cita.get("estado", "")),
        )

    def _reconstruir_appointment(self, appointment_id: str) -> Appointment:
        cita = self.get_appointment(appointment_id)
        if cita is None:
            raise AppointmentNotFoundError(appointment_id)
        return cita
