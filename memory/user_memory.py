"""
Memoria del usuario/ciudadano — Capa C de 004 sección 3.

MVP-PARCIAL, a propósito: solo el mecanismo de guardar/leer un perfil
por usuario, en memoria de proceso. No hay todavía identidad de usuario
real, retención, ni el mecanismo de acceso/eliminación que exige la
regla de protección de datos personales del proyecto — eso queda
PENDIENTE (ver recado 006), no se inventa aquí.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


class UserMemory:
    def __init__(self) -> None:
        self._profiles: Dict[str, Dict[str, Any]] = {}

    def get_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        return self._profiles.get(user_id)

    def save_profile(self, user_id: str, data: Dict[str, Any]) -> None:
        self._profiles[user_id] = data
