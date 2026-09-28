# 041 — Corrección: `_RE_FECHA` y `DatoInventadoGuardrail` ahora funcionan case-insensitive

**Fecha**: 2026-09-06
**Estado**: corregido, probado (295 passed, 3 skipped), **confirmado con una llamada real nueva a Anthropic**. `HEALTH_BRAIN_TYPE` sigue sin activarse en ningún archivo, no se probó Telegram.
**Continúa**: recado 040 (hallazgo real: la categoría "fecha" de `DatoInventadoGuardrail` nunca verificaba nada de verdad contra texto redactado por un LLM real, por una discrepancia de mayúsculas/minúsculas).

## El fix — 2 cambios, ambos necesarios

### 1. `_RE_FECHA` ahora es case-insensitive (`domains/health/llm_brain.py`)

Se agregó `(?i)` al INICIO del patrón (no solo `re.IGNORECASE` al compilar): esto es deliberado — `(?i)` viaja con el STRING del patrón (`_RE_FECHA.pattern`), así que sigue siendo case-insensitive cuando `DatoInventadoGuardrail` (Core) vuelve a compilarlo desde cero vía `re.findall(verificacion.patron, texto)`. Si hubiera usado solo `re.compile(..., re.IGNORECASE)`, la bandera se habría quedado en el objeto `Pattern` de `llm_brain.py` y nunca habría llegado al `re.findall` que corre en `guardrails/rules.py`.

### 2. `DatoInventadoGuardrail` ahora compara sin distinguir mayúsculas/minúsculas (`guardrails/rules.py`)

Encontrar la fecha en el texto ya redactado NO bastaba — también había que comparar correctamente contra `valores_permitidos` (que vienen capitalizados, "Martes 8 de septiembre", extraídos del texto BASE). Se normalizó la comparación: ambos lados a minúscula antes del chequeo de pertenencia (`c.lower() not in {v.lower() for v in permitidos}`).

**Decisión explícita, documentada en el docstring de la clase** (pediste que decidiera y documentara): la comparación case-insensitive se aplicó como política GENERAL de la regla (no solo para "fecha", no como un flag opcional por categoría) — un LLM real varía mayúsculas/minúsculas de un dato correcto por razones puramente gramaticales, nunca porque el dato en sí sea distinto. Si algún dominio futuro necesitara distinguir mayúsculas/minúsculas como parte genuina del valor (ej. un código alfanumérico sensible a mayúsculas), seguiría funcionando en la inmensa mayoría de los casos reales — y si eso cambiara, se agregaría esa excepción entonces, no antes (mismo criterio de "no sobrearquitectura" del resto del proyecto).

## Verificación (los 5 puntos pedidos)

1. ✅ **`_RE_FECHA` ahora encuentra "el martes 8 de septiembre" en minúscula** — `test_re_fecha_encuentra_fecha_en_minuscula_como_claude_la_escribe`.
2. ✅ **Los 5 casos reales del recado 040, reproducidos con los textos literales exactos** (nunca se gastó una llamada real de nuevo para esto) — `tests/domains/health/test_fecha_case_insensitive.py`, confirmando que `_RE_FECHA.findall()` ahora SÍ extrae cada fecha del texto redactado, y que `DatoInventadoGuardrail` los evalúa como ALLOW genuino (no un no-op silencioso).
3. ✅ **Test crítico: alucinación de fecha en minúscula, ahora bloqueada** — `test_alucinacion_de_fecha_en_minuscula_ahora_queda_bloqueada`: un texto redactado que agrega "el miércoles 9 de septiembre" (fecha nunca ofrecida) queda `BLOCK` — antes del fix, esto habría pasado como `ALLOW` sin que el guardrail siquiera detectara que había una fecha que revisar.
4. ✅ **Caso 1 repetido con una llamada REAL nueva a Anthropic** (gateada, con tu API key ya configurada):
   - Texto base: `"Estas son las fechas disponibles: 1) Jueves 10 de septiembre; 2) Viernes 11 de septiembre. ¿Cuál te queda mejor?"`
   - Texto redactado (Claude real, llamada nueva): `"¡Claro que sí! Tengo estas fechas disponibles para tu cita de pediatría: 1) jueves 10 de septiembre o 2) viernes 11 de septiembre. ¿Cuál te queda mejor?"`
   - `_RE_FECHA.findall()` sobre el texto redactado: `['jueves 10 de septiembre', 'viernes 11 de septiembre']` — **encontradas de verdad, con evidencia real, no simulada**.
   - `DatoInventadoGuardrail`: `ALLOW`, razón `"sin datos inventados detectados"` — esta vez un ALLOW que significa "se verificó y es correcto", no "no encontré nada que revisar".
5. ✅ **Suite completa**: 295 passed, 3 skipped (286 anteriores + 9 nuevos) — cero regresiones.

## Archivos tocados

- `domains/health/llm_brain.py`: `(?i)` en `_RE_FECHA`.
- `guardrails/rules.py`: comparación case-insensitive en `DatoInventadoGuardrail`, con la decisión documentada en el docstring.
- Nuevos: `tests/guardrails/test_dato_inventado_case_insensitive.py` (2 tests), `tests/domains/health/test_fecha_case_insensitive.py` (7 tests).

## Estado del mecanismo tras esta corrección

Con este fix, la batería completa de verificaciones reales hechas hasta ahora (recados 038, 039, 040, 041) no tiene ningún hallazgo pendiente de corregir. El mecanismo de redacción con LLM + guardrails (persistencia, datos inventados — ahora genuinamente verificando fecha/hora —, confirmación estructurada, tipo de pregunta preservado, fuera de alcance) está probado con evidencia real repetida, con casos variados de mensaje del paciente (typos, tono emocional, manipulación, confirmación ambigua, catálogo con typo).

## Pendiente de tu decisión

1. `HEALTH_BRAIN_TYPE` sigue sin activarse en ningún archivo de configuración de este repo.
2. Con este hallazgo corregido y verificado con evidencia real (incluida una llamada real nueva), ¿autorizas avanzar a una prueba en Telegram real, o prefieres una ronda más de pruebas/revisión?
3. Revisar si quieres que commitee y pushee este trabajo.
