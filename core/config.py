"""
Configuración separada del código (prompt maestro, sección 17).

Solo lee NOMBRES de variables de entorno, nunca valores por defecto que
parezcan secretos. Ver .env.example en la raíz del proyecto para la
lista documentada.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ZantiaConfig:
    anthropic_api_key_env_var: str = "ANTHROPIC_API_KEY"
    anthropic_model: str = "claude-sonnet-5"
    db_path_env_var: str = "ZANTIA_DB_PATH"
    # Recado 037, Parte 1 (R-11): mismo patrón que db_path_env_var,
    # aplicado a EventLog y ConversationMemory.
    events_db_path_env_var: str = "ZANTIA_EVENTS_DB_PATH"
    memory_db_path_env_var: str = "ZANTIA_MEMORY_DB_PATH"

    @property
    def db_path(self) -> str:
        return os.environ.get(self.db_path_env_var, ":memory:")

    @property
    def events_db_path(self) -> str:
        return os.environ.get(self.events_db_path_env_var, ":memory:")

    @property
    def memory_db_path(self) -> str:
        return os.environ.get(self.memory_db_path_env_var, ":memory:")


DEFAULT_CONFIG = ZantiaConfig()
