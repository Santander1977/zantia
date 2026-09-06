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

import logging
import os
from dataclasses import dataclass
from typing import Any, Callable

from core.brain import Brain

from .appointment_service import AppointmentService, MockAppointmentService
from .brain import HealthBrain
from .hrmm_appointment_service import HrmmAppointmentService
from .hrmm_catalog import CatalogMirror
from .hrmm_http import HttpClient, RealHttpClient

logger = logging.getLogger("zantia.health")


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


@dataclass(frozen=True)
class HealthBrainConfig:
    """Recado 038 — mismo patrón que `HealthServiceConfig` arriba,
    aplicado a la elección de Brain: `build_health_brain()` es el ÚNICO
    punto que lee `HEALTH_BRAIN_TYPE` — ningún otro archivo decide por
    su cuenta cuál Brain construir."""

    env_var: str = "HEALTH_BRAIN_TYPE"
    anthropic_api_key_env_var: str = "ANTHROPIC_API_KEY"
    anthropic_model: str = "claude-sonnet-5"


DEFAULT_HEALTH_BRAIN_CONFIG = HealthBrainConfig()


def build_health_brain(
    activity_provider: Callable[[], Any],
    appointment_service: AppointmentService,
    config: HealthBrainConfig = DEFAULT_HEALTH_BRAIN_CONFIG,
) -> Brain:
    """Único punto de composición para el Brain del dominio salud
    (recado 038). Valores válidos de `HEALTH_BRAIN_TYPE`:

    - (no definida) o `deterministico` -> `HealthBrain` — default
      SEGURO, sin cambios de comportamiento frente a antes de este
      recado.
    - `llm` -> `HealthAnthropicBrain` (recado 038: interpreta con el
      MISMO `HealthBrain` determinista de siempre, redacta el texto
      final con Anthropic real) — requiere `ANTHROPIC_API_KEY`
      configurada. Si falta, **nunca falla al arrancar ni a mitad de
      una conversación**: cae al `HealthBrain` determinista con un
      `logger.warning` explícito (mismo criterio de "nunca en
      silencio" que el resto del proyecto, recado 021/037) — a
      diferencia de `HRMM_BACKEND_ENV=production` (que si falla,
      *sí* debe fallar fuerte, porque ahí la alternativa segura no
      existe), acá SÍ existe una alternativa segura y funcional
      (el Brain determinista), así que degradar es la decisión
      correcta, no un descuido.

    El default de `HEALTH_BRAIN_TYPE` es SIEMPRE `deterministico` —
    nunca se activa `llm` automáticamente en ningún archivo de
    configuración de este repo (`.env.example` documenta la variable
    con el valor vacío)."""
    brain_determinista = HealthBrain(activity_provider, appointment_service)
    tipo = os.environ.get(config.env_var, "deterministico").strip().lower()

    # --- LOG TEMPORAL DE DIAGNÓSTICO (recado en curso, 2026-09-06) ---
    # Confirma, para cada Activity/conversación construida, qué tipo de
    # Brain se pidió (HEALTH_BRAIN_TYPE tal como llegó, ya normalizado)
    # y qué clase se construyó DE VERDAD — nunca expone ningún valor de
    # secreto (ANTHROPIC_API_KEY), solo su presencia se reporta en el
    # warning de fallback que ya existía. Objetivo puntual: confirmar en
    # los logs de EasyPanel si HEALTH_BRAIN_TYPE nunca llega como "llm"
    # a este punto, o si llega pero algo más falla en silencio después.
    # QUITAR una vez resuelto el diagnóstico — no es una verificación de
    # seguridad real, es un log puntual para esta investigación.
    def _log_brain_construido(brain: Brain) -> Brain:
        logger.info(
            "BRAIN CONSTRUIDO: tipo=%s, clase=%s",
            tipo,
            brain.__class__.__name__,
        )
        return brain
    # --- FIN LOG TEMPORAL (la llamada a _log_brain_construido en cada
    # return de abajo también se quita junto con esto) ---

    if tipo in ("", "deterministico", "determinista"):
        return _log_brain_construido(brain_determinista)

    if tipo == "llm":
        api_key = os.environ.get(config.anthropic_api_key_env_var)
        if not api_key:
            logger.warning(
                f"{config.env_var}=llm pero {config.anthropic_api_key_env_var} no está "
                "configurada — cayendo al Brain determinista (HealthBrain). Configurar "
                f"{config.anthropic_api_key_env_var} (ver .env.example) para usar el Brain "
                "basado en LLM real."
            )
            return _log_brain_construido(brain_determinista)
        from .llm_brain import AnthropicResponseDrafter, HealthAnthropicBrain

        drafter = AnthropicResponseDrafter(
            model=config.anthropic_model, api_key_env_var=config.anthropic_api_key_env_var
        )
        return _log_brain_construido(HealthAnthropicBrain(brain_determinista, drafter))

    raise HealthConfigError(
        f"{config.env_var}={tipo!r} no es un valor reconocido — usar 'deterministico' o 'llm'."
    )
