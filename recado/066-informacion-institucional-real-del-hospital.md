# 066 — Información institucional real del hospital (teléfono, correo, dirección) + guardrail dedicado

**Fecha**: 2026-09-10
**Estado**: Implementado y probado (incluida 1 llamada real a Anthropic). **Sin commitear — a la espera de tu aprobación explícita.**

**Nota de secuencia**: tu primer mensaje decía que la dirección física NO estaba confirmada todavía; segundos después, en un mensaje posterior dentro del mismo turno, la confirmaste ("Carrera 17 # 57-119, Barrio Pueblo Nuevo, Barrancabermeja"). Implementé directamente con los 3 datos ya confirmados — el diseño de abajo sigue soportando igual el caso "dirección todavía sin confirmar" (campo `Optional[str] = None`), por si algún dato institucional futuro llega incompleto.

---

## 1. Fuente única de verdad — decisión y justificación

**Decisión**: constante Python (`dataclass` congelado) en un archivo nuevo, `domains/health/institutional_info.py` — **no** variable de entorno.

**Justificación** (pedida explícitamente, no asumida):
- El NOMBRE del hospital ("Hospital Regional del Magdalena Medio") ya vive hardcodeado en `brain.py` (`_PRESENTACION_ANDRES`) desde el recado 046 — nunca como variable de entorno. Teléfono/correo/dirección son la MISMA naturaleza de dato (identidad/contacto institucional del dominio), no un parámetro de despliegue como `HRMM_BACKEND_URL`.
- No es un secreto bajo `.claude/rules/seguridad-y-secretos.md` (API keys, contraseñas, tokens — un teléfono/correo de atención al público no califica) — no hay ninguna razón de seguridad para sacarlo del código versionado.
- Si este código se reutiliza como plantilla para otro hospital, este archivo es el ÚNICO lugar a tocar — mismo razonamiento que ya aplica al nombre institucional.

```python
@dataclass(frozen=True)
class InformacionInstitucional:
    telefono_citas: str
    correo_citas: str
    direccion: Optional[str] = None  # None explícito si no está confirmada — nunca un placeholder inventado

INFORMACION_HOSPITAL = InformacionInstitucional(
    telefono_citas="607-6010104",
    correo_citas="agendacitas@esehospitalrmm.gov.co",
    direccion="Carrera 17 # 57-119, Barrio Pueblo Nuevo, Barrancabermeja",
)
```

## 2. Conexión a la categoría del recado 064

`_texto_informacion_hospital(info)` (nueva, `brain.py`) arma el texto ÚNICAMENTE a partir de `INFORMACION_HOSPITAL` — ningún valor escrito a mano en el sitio de uso. Extensible sin duplicar lógica (requisito #3 explícito): si `direccion` es `None`, dice la verdad ("no tengo la dirección... pero puedes llamarnos/escribirnos"); si está confirmada (como ahora), la incluye directamente — la MISMA función cubre ambos casos, ningún llamador cambia cuando el dato se completa.

También amplié el vocabulario de la categoría (`_PREGUNTA_UBICACION_HOSPITAL`) para reconocer preguntas DIRECTAS de contacto ("cuál es el teléfono", "tienen correo") — antes solo cubría ubicación; ahora que hay teléfono/correo reales, es la misma categoría de "información de contacto del hospital".

### Texto EXACTO de la respuesta (el que pediste ver antes de aprobar)

> Estamos ubicados en Carrera 17 # 57-119, Barrio Pueblo Nuevo, Barrancabermeja. Si necesitas más detalles, también puedes llamarnos al 607-6010104 o escribirnos a agendacitas@esehospitalrmm.gov.co. {recordatorio breve de la etapa vigente}

## 3. Prompt de sistema reforzado (`HealthAnthropicBrain`)

Regla 8 nueva, agregada a `_PROMPT_SISTEMA` (`llm_brain.py`), explícita sobre estos 3 datos — nunca completarlos/alterarlos "ni un solo dígito o carácter", ni siquiera ante insistencia del paciente:

> 8. Si el "mensaje de contenido" incluye una dirección física, un número de teléfono, o un correo electrónico del hospital, debes reproducir esos 3 datos EXACTAMENTE carácter por carácter [...] Nunca los completes, corrijas, acortes, ni cambies ni un solo dígito o carácter, aunque te parezca un error de formato o el paciente insista en que le des un dato distinto, más específico, o "el número correcto" — el mensaje de contenido es la ÚNICA fuente real de estos datos [...]

## 4. Guardrail extendido — cierra el hueco pendiente del recado 064

`_construir_verificaciones_de_datos` (`llm_brain.py`) — mismo mecanismo EXACTO que fecha/hora (recado 037/041), ahora con 3 categorías más: `telefono`, `correo`, `direccion`. Siempre las 3, incluso vacías (mismo criterio: si el texto base no mencionó un dato, CUALQUIERA que el LLM agregue se bloquea igual).

Patrones, verificados empíricamente antes de escribir código (no supuestos):

| Categoría | Patrón | Real | Alucinaciones detectadas en la prueba |
|---|---|---|---|
| Teléfono | `\b\d{3}-\d{7}\b` | `607-6010104` | `607-6010199` (dígito final cambiado) |
| Correo | patrón email estándar | `agendacitas@esehospitalrmm.gov.co` | — |
| Dirección | `(?:carrera\|calle\|avenida\|...)\s*\d+[a-z]?\s*#\s*\d+-\d+` | `Carrera 17 # 57-119` | `Carrera 170 # 57-119` (número de carrera) y `Carrera 17 # 57-190` (número de predio) — ambos verificados que el patrón los distingue correctamente del real |

**Límite honesto**: el patrón de dirección cubre la parte numérica/vía (`Carrera 17 # 57-119`), no el barrio/ciudad (`Barrio Pueblo Nuevo, Barrancabermeja` — sin un formato tan reconocible como para un regex confiable). Documentado en el propio código, no oculto.

## 5. Verificación

**`tests/domains/health/test_informacion_institucional_real.py`** (nuevo, 6 tests):
1. `test_pregunta_sobre_hospital_incluye_los_3_datos_reales_exactos` / `test_pregunta_directa_por_telefono_o_correo_tambien_se_reconoce` — punto 1.
2. `test_guardrail_bloquea_direccion_alucinada_con_un_solo_digito_cambiado` / `test_guardrail_bloquea_telefono_alucinado` (mismo patrón del recado 041) / `test_control_positivo_direccion_real_sin_alterar_no_se_bloquea` (control anti-falso-positivo) — punto 2.
3. `test_real_pregunta_sobre_hospital_menciona_los_3_datos_reales_sin_alteracion` — punto 3, **llamada real ejecutada en esta sesión**:

```
Paciente: oye, y a todas estas ¿dónde queda el hospital exactamente?
Sistema: ¡Claro que sí! Estamos ubicados en Carrera 17 # 57-119, Barrio Pueblo Nuevo,
Barrancabermeja. Si necesitas más detalles, también puedes llamarnos al 607-6010104 o
escribirnos a agendacitas@esehospitalrmm.gov.co.

Volviendo a lo de antes, ¿te gustaría que te ayude a agendar tu atención?
```
Los 3 datos reales, exactos, sin ninguna alteración — verificado también programáticamente (no solo leyendo el texto).

**Suite completa**: `510 passed, 14 skipped` (505 previas + 5 deterministas nuevas; 14 = 13 previos + 1 real nueva). Cero regresiones.

## 6. Archivos tocados (sin commitear)

- `domains/health/institutional_info.py` — nuevo, fuente única de verdad.
- `domains/health/brain.py` — import, vocabulario ampliado, `_texto_informacion_hospital`, rama del detector actualizada.
- `domains/health/llm_brain.py` — `_RE_TELEFONO`/`_RE_CORREO`/`_RE_DIRECCION`, 3 categorías nuevas en `_construir_verificaciones_de_datos`, regla 8 en `_PROMPT_SISTEMA`.
- `tests/domains/health/test_informacion_institucional_real.py` — nuevo, 6 tests (5 deterministas + 1 real).

## 7. Pendiente de tu aprobación

Todo implementado, probado (incluida la llamada real), documentado. Sin commitear. Dime si apruebas para comitear y pushear (junto con el trabajo del recado 064/065, que también sigue sin commitear), o si quieres ajustar algo del texto/diseño antes.
