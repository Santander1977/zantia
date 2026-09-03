"""
Capa de configuración de `domains/health/` — el ÚNICO punto que lee
`HRMM_BACKEND_ENV` y decide qué implementación de `AppointmentService`
(`MockAppointmentService` vs. `HrmmAppointmentService`) se construye en
tiempo de arranque (recado 009, pendiente #1; recado 011).

Ningún otro archivo de `domains/health/` debe leer `HRMM_BACKEND_ENV`
ni decidir por su cuenta cuál adaptador usar — `agent.py`/`gateway.py`
reciben la instancia ya construida vía `build_appointment_service()`.

Valores válidos de `HRMM_BACKEND_ENV`:
- (no definida) o `mock`   -> `MockAppointmentService()` — comportamiento
  por defecto, seguro, no requiere ninguna otra variable.
- `production` -> `HrmmAppointmentService` real, contra `HRMM_BACKEND_URL`
  con `HRMM_BACKEND_SECRET` — falla al arrancar (nunca en medio de una
  conversación) si falta cualquiera de las dos.
- `staging` -> falla explícitamente: no existe un entorno de staging
  real documentado para hrmm-backend (recado 009) — nunca se inventa
  una URL ni se redirige a producción ni se cae silenciosamente al Mock.

Ver `.env.example` para los nombres documentados (nunca valores).
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from .appointment_service import AppointmentService, MockAppointmentService
from .hrmm_appointment_service import HrmmAppointmentService
from .hrmm_catalog import CatalogMirror
from .hrmm_http import HttpClient, RealHttpClient


class HealthConfigError(Exception):
    """Fallo de configuración al arrancar — nunca se degrada en
    silencio al Mock ni se deja para descubrir en medio de una
    conversación con un paciente."""


@dataclass(frozen=True)
class HealthServiceConfig:
    env_var: str = "HRMM_BACKEND_ENV"
    url_env_var: str = "HRMM_BACKEND_URL"
    secret_env_var: str = "HRMM_BACKEND_SECRET"


DEFAULT_HEALTH_CONFIG = HealthServiceConfig()


def build_appointment_service(
    config: HealthServiceConfig = DEFAULT_HEALTH_CONFIG,
    http_client: HttpClient | None = None,
) -> AppointmentService:
    """Único punto de composición: lee `HRMM_BACKEND_ENV` (o su default
    seguro `mock`) y construye la instancia correcta. Se llama una sola
    vez, al arrancar el proceso — no en medio de una conversación.

    `http_client` es un punto de inyección SOLO para tests (permite
    pasar un `FakeHttpClient` y verificar la composición sin red real,
    ver `.env.example` y `tests/domains/health/test_health_config.py`)
    — en uso real, en producción, siempre se omite y se construye un
    `RealHttpClient` real contra `HRMM_BACKEND_URL`."""
    entorno = os.environ.get(config.env_var, "mock").strip().lower()

    if entorno == "" or entorno == "mock":
        return MockAppointmentService()

    if entorno == "staging":
        raise HealthConfigError(
            f"{config.env_var}=staging, pero no existe un entorno de staging real "
            "documentado para hrmm-backend (ver recado 009 en /Users/enzoalfonso/recado/). "
            "No se inventa una URL ni se redirige a producción ni se usa el Mock como si "
            "fuera staging real — configura 'mock' o 'production', o construye primero "
            "un staging real y documenta su URL antes de usar este valor."
        )

    if entorno == "production":
        url = os.environ.get(config.url_env_var)
        secreto = os.environ.get(config.secret_env_var)
        faltantes = [
            nombre
            for nombre, valor in ((config.url_env_var, url), (config.secret_env_var, secreto))
            if not valor
        ]
        if faltantes:
            raise HealthConfigError(
                f"{config.env_var}=production requiere {', '.join(faltantes)} "
                f"(ver .env.example) — no configuradas. Fallando al arrancar en vez de "
                "caer silenciosamente al Mock."
            )
        cliente = http_client if http_client is not None else RealHttpClient(base_url=url)
        catalog = CatalogMirror()
        catalog.sync(cliente)
        return HrmmAppointmentService(
            cliente, catalog, trusted_secret_env_var=config.secret_env_var
        )

    raise HealthConfigError(
        f"{config.env_var}={entorno!r} no es un valor reconocido — usar 'mock', "
        "'staging' o 'production'."
    )
