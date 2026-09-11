"""
Fuente única de verdad para la información institucional REAL del
hospital — teléfono, correo, dirección física (recado 066).

Decisión de diseño (constante Python en `domains/health/`, NO variable
de entorno) — justificada explícitamente, no asumida:
- Mismo criterio ya establecido en este archivo/dominio: el NOMBRE del
  hospital ("Hospital Regional del Magdalena Medio") ya vive hardcodeado
  como texto institucional en `domains/health/brain.py` (`_PRESENTACION_ANDRES`),
  nunca como variable de entorno — este dato es de la misma naturaleza
  (identidad/contacto institucional del dominio salud, no un secreto ni
  un parámetro de despliegue como `HRMM_BACKEND_URL`).
- No es un secreto (`.claude/rules/seguridad-y-secretos.md` — API keys,
  contraseñas, tokens; un teléfono/correo de atención al público NO
  califica) — no hay ninguna razón de seguridad para sacarlo del código
  versionado.
- Si esto se convierte en una plantilla reutilizable para otro hospital
  (ver `.claude/rules/aislamiento-entre-proyectos.md`), este archivo es
  precisamente el ÚNICO lugar que habría que tocar — mismo razonamiento
  que ya aplica al nombre institucional en `brain.py`.

Ningún otro archivo debe declarar estos datos por su cuenta — siempre
se importan desde acá (`from .institutional_info import INFORMACION_HOSPITAL`).

Valores confirmados por el usuario a partir de comunicaciones
institucionales reales del hospital (2026-09-10) — NUNCA inventados,
NUNCA buscados en internet sin verificación oficial (instrucción
explícita del pedido que originó este archivo). El campo `direccion`
llegó inicialmente `None` (pendiente) y se completó en el mismo pedido,
momentos después, con el dato real confirmado — el tipo `Optional[str]`
se conserva de todas formas: es la forma correcta de modelar "puede
no estar confirmado todavía" para cualquier campo futuro de este tipo
(recado 066)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class InformacionInstitucional:
    telefono_citas: str
    correo_citas: str
    # `None` explícito, nunca un placeholder inventado ("Dirección por
    # confirmar", una calle de ejemplo, etc.) — hasta que el usuario la
    # confirme contra una fuente oficial real del hospital. Cualquier
    # código que lea este campo debe tratar `None` como "dato
    # desconocido, no mencionar", nunca completarlo con una suposición.
    direccion: Optional[str] = None


# Única instancia real de esta información en todo el proyecto.
INFORMACION_HOSPITAL = InformacionInstitucional(
    telefono_citas="607-6010104",
    correo_citas="agendacitas@esehospitalrmm.gov.co",
    direccion="Carrera 17 # 57-119, Barrio Pueblo Nuevo, Barrancabermeja",
)
