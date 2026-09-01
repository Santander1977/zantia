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
    No probada contra red real en esta sesión (ver recado)."""

    def __init__(self, base_url: str, timeout_seconds: float = 10.0) -> None:
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
        except urllib.error.URLError as exc:
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
