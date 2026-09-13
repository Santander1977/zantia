"""
Capa HTTP para integraciones reales del dominio salud — componente
NUEVO (no existía en 007/008), sin dependencias externas (usa
`urllib` de la librería estándar, mismo criterio de minimalismo ya
aplicado a `sqlite3` en `state/store.py`, D-1).

`HttpClient` es la interfaz que consume `HrmmAppointmentService`
(`domains/health/hrmm_appointment_service.py`). `FakeHttpClient` es la
implementación usada por los tests (sin red real, sin secretos —
petición explícita del usuario para esta sesión). `RealHttpClient`
existe y es funcional, pero NINGÚN test de esta sesión la ejercita
contra una red real (ver recado de esta fase).
"""
from __future__ import annotations

import json as _json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple


class HttpError(Exception):
    """Error de transporte (no se pudo conectar, timeout, etc.) —
    distinto de un status HTTP de error, que se representa en
    `HttpResponse.status` (el llamador decide qué hacer con cada uno,
    igual que ya hace `tools/base.py:ToolResult` con `success`)."""


@dataclass
class HttpResponse:
    status: int
    body: Any  # ya deserializado de JSON si el content-type lo permitía


class HttpClient(Protocol):
    def request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> HttpResponse: ...


class RealHttpClient:
    """Implementación real — stdlib `urllib`, sin dependencias nuevas.
    No probada contra red real en esta sesión (ver recado).

    Recado 083 — `timeout_seconds` subido de 10s a 30s: hallazgo real
    de producción, mismo día del recado 082 (timeout de transporte no
    capturado hacia `verificacion/enviar`, ya corregido ahí). Con el
    fix de captura ya desplegado, se confirmó que el timeout SIGUE
    ocurriendo — reproducido localmente contra producción real, tardó
    ~10.8s antes de fallar, justo en el límite anterior. `hrmm-backend`
    (`app/api/agenda.py:enviar_codigo_verificacion`, otro repo, leído
    en modo solo lectura) llama a SU PROPIO webhook de n8n con
    `timeout=20` — es decir, hrmm-backend nunca debería tardar más de
    ~20-22s en responder (éxito o su propio `enviado: false`) para este
    endpoint específico, aun si n8n está lento tras un reinicio (el
    usuario reportó hasta 60s en casos puntuales del Task Runner, pero
    el propio timeout interno de hrmm-backend ya lo acota a 20s antes
    de llegar a eso). 30s deja margen sobre ese máximo conocido de
    hrmm-backend sin ser un límite arbitrario ni tan largo como para
    ocultar un fallo real de red — sigue siendo un único valor
    compartido por TODAS las llamadas de este cliente (catálogo,
    disponibilidad, reservas, verificación), decisión deliberada: el
    resto de esas llamadas no dependen de n8n y responden rápido de
    por sí, así que un techo más alto no las hace más lentas en el
    caso normal, solo evita cortar de más una respuesta lenta pero
    válida en el caso raro."""

    def __init__(self, base_url: str, timeout_seconds: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    def request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> HttpResponse:
        url = self._base_url + path
        if params:
            # urlencode con doseq=True para soportar listas (ej. estados[]):
            url += "?" + urllib.parse.urlencode(params, doseq=True)

        data = _json.dumps(json_body).encode("utf-8") if json_body is not None else None
        cabeceras = {"Accept": "application/json"}
        if data is not None:
            cabeceras["Content-Type"] = "application/json"
        cabeceras.update(headers or {})

        solicitud = urllib.request.Request(url, data=data, headers=cabeceras, method=method)
        try:
            with urllib.request.urlopen(solicitud, timeout=self._timeout) as respuesta:
                cuerpo_bruto = respuesta.read()
                status = respuesta.status
        except urllib.error.HTTPError as exc:
            cuerpo_bruto = exc.read()
            status = exc.code
        except OSError as exc:
            # Recado 082 — hallazgo real de producción: `urllib.request`
            # solo envuelve en `URLError` los fallos de red ocurridos
            # mientras se ENVÍA la solicitud (`AbstractHTTPHandler.do_open`
            # solo captura `OSError` alrededor de `h.request(...)`) —
            # un timeout ocurrido mientras se ESPERA/LEE la respuesta
            # (`h.getresponse()`, fuera de ese `try`) se propaga como
            # `socket.timeout`/`TimeoutError` CRUDO, sin envolver, y antes
            # de este fix escapaba de aquí sin convertirse en `HttpError`
            # — confirmado con un traceback real (hrmm-backend/n8n lentos
            # tras un reinicio de n8n): el código nunca llegaba a
            # `except AppointmentServiceError` en `gateway.py` (no es esa
            # clase), y terminaba en el `except Exception` genérico de
            # `service/app.py`, mostrando "Tuvimos un problema procesando
            # tu mensaje" en vez de un mensaje honesto. `URLError` ya es
            # subclase de `OSError`, así que capturar `OSError` aquí
            # cubre ambos casos sin duplicar lógica — coincide además con
            # lo que este mismo docstring de `HttpError` ya prometía
            # ("no se pudo conectar, timeout, etc.") desde el día 1.
            raise HttpError(str(exc)) from exc

        cuerpo = None
        if cuerpo_bruto:
            try:
                cuerpo = _json.loads(cuerpo_bruto)
            except ValueError:
                cuerpo = cuerpo_bruto.decode("utf-8", errors="replace")
        return HttpResponse(status=status, body=cuerpo)


@dataclass
class FakeHttpClient:
    """Doble de prueba — sin red real. Se programa con respuestas fijas
    por (método, ruta) o con una función generadora, y registra cada
    llamada recibida para poder verificarla en los tests (mismo patrón
    que `NotifyTeamTool` en `tools/demo_tools.py`, que registra sus
    notificaciones en una lista)."""

    respuestas: Dict[Tuple[str, str], HttpResponse] = field(default_factory=dict)
    generador: Optional[Callable[[str, str, Optional[dict], Optional[dict], Optional[dict]], HttpResponse]] = None
    llamadas: List[Dict[str, Any]] = field(default_factory=list)

    def programar(self, method: str, path: str, response: HttpResponse) -> None:
        self.respuestas[(method, path)] = response

    def request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> HttpResponse:
        self.llamadas.append(
            {"method": method, "path": path, "params": params, "json_body": json_body, "headers": headers}
        )
        if self.generador is not None:
            return self.generador(method, path, params, json_body, headers)
        clave = (method, path)
        if clave not in self.respuestas:
            raise HttpError(f"FakeHttpClient sin respuesta programada para {method} {path}")
        return self.respuestas[clave]
