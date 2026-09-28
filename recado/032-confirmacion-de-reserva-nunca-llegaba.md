# 032 — URGENTE: la reserva se completaba de verdad pero nunca se confirmaba

**Fecha**: 2026-09-06
**Continúa**: recados 026-031 (misma conversación real de Telegram)
**Severidad**: crítica — una reserva real contra producción quedaba invisible para el paciente y para el propio dominio ZANTIA.

## Resumen ejecutivo

`[CONFIRMADO]`, reproducido byte por byte con `FakeHttpClient` simulando una respuesta real de hrmm-backend: **la reserva se completaba de verdad** (POST `/api/agenda/citas` exitoso, sin ninguna excepción) **pero el sistema nunca se enteraba**, porque el chequeo de "¿la tool tuvo éxito?" exigía que el `estado` de la cita recién creada fuera literalmente `"CONFIRMED"` — un mapeo (`_MAPA_ESTADO_HRMM`) que sigue siendo **inferencia nunca confirmada contra una cita real** (riesgo `R-9`, abierto desde el recado 009). Si el `estado` real no está en ese mapa, el sistema entero se comporta como si la reserva nunca hubiera pasado, aunque sí pasó.

## Reproducción exacta (antes del fix)

Con una cita real creada con `estado="pendiente"` (un valor plausible, no confirmado, que `_MAPA_ESTADO_HRMM` no contempla):

```
>>> "necesito una cita"
<<< "¡Perfecto! Estas son las opciones disponibles: 1) 2026-09-10 09:00 en Consultorio 3. ¿Cuál te queda mejor?"

>>> "la primera"
<<< "¡Perfecto! Voy a reservarlo — dame un momento."          <- sin confirmación, EXACTO al reporte

>>> "Ok"
<<< "No logré entender si es un sí o un no — ¿me confirmas..." <- EXACTO al reporte

cita real creada en 'hrmm-backend': {'cita_id': 'C-REAL-1', ..., 'estado': 'pendiente'}
```

La cita **sí existe** del lado de hrmm-backend en esta simulación — el sistema simplemente nunca se enteró.

## Diagnóstico completo (respondiendo los 4 puntos pedidos)

**1. ¿Qué pasa después de "Voy a reservarlo"? ¿síncrono o pendiente de otro turno?**
`[CONFIRMADO]` Es **síncrono**, en el MISMO turno: `HealthBrain._interpretar_seleccion` propone `tool_requerida={"name": "book_appointment", ...}`, y el `Orchestrator` ejecuta `BookAppointmentTool.run()` de inmediato — que a su vez llama `book_appointment()` Y `confirm_appointment()` (para `HrmmAppointmentService`, esto último es solo una relectura vía `GET /api/agenda/citas/{id}`, documentado así porque hrmm-backend no tiene un segundo paso real de confirmación). No queda pendiente de ningún turno siguiente.

**2. Revisar logs reales / qué devolvió `book_appointment()`**
`[DESCONOCIDO — no se pudo verificar con logs reales]`: no hay ningún log persistente de esa conversación específica (mismo límite ya documentado, R-11 — `EventLog` vive solo en memoria del proceso). **No fue una excepción no capturada** — la reproducción con `FakeHttpClient` confirma que el mecanismo funciona exactamente así incluso SIN ningún error: la tool devuelve éxito, pero el resultado nunca se usa correctamente para componer la respuesta siguiente porque una verificación adicional (el `estado` literal) falla en silencio.

**3. ¿Qué mensaje debería haber disparado la confirmación? ¿Por qué "Ok" no lo hizo?**
La confirmación debía llegar en el MISMO turno que "Voy a reservarlo" (no en uno posterior) — y de hecho el código ya estaba diseñado para eso (`agent.py`, `just_booked` + texto "¡Listo! Quedó confirmado..." concatenado en la misma respuesta). El bug es que esa concatenación nunca se disparó. "Ok" no tiene nada que ver con la causa raíz: simplemente cayó en el mismo fallback genérico de sí/no ya corregido en el recado 030, porque el ciclo se había reabierto (`CIERRE` → `_reabrir_ciclo`, mecanismo ya existente) sin que la reserva ya lograda quedara registrada en ningún lado.

**4. ¿Rediseño más amplio necesario?**
En este caso el problema NO era el patrón de fallback (ya corregido en recados 030-031) sino una verificación de éxito basada en un dato (`Cita.estado`) cuyo vocabulario real **nunca se confirmó** — mismo patrón de raíz que otros hallazgos de esta serie (confiar en un supuesto no verificado sobre el sistema real). Recomendación: cuando exista oportunidad de hacerlo con autorización explícita, ejecutar una reserva real de prueba contra un entorno confirmado con el usuario para leer el `estado` real de una `Cita` recién creada y cerrar `R-9` de una vez — hoy se corrigió el síntoma (dejar de exigir un valor no confirmado) sin necesitar conocer el valor real.

## Corrección aplicada

`domains/health/agent.py` — nueva función `_book_appointment_exitoso(resultados_tools)`, que reemplaza la exigencia de `status == "CONFIRMED"` por `bool(resultados_tools.get("book_appointment"))`. Justificación: `BookAppointmentTool.run()` (sin tocar) YA es la autoridad real de éxito/fracaso — `ToolResult.data` es `None` en cualquier falla (excepción de `book_appointment`/`confirm_appointment`), y solo un dict real cuando ambos pasos respondieron sin excepción. Exigir además una palabra de estado específica, nunca confirmada contra datos reales, era una segunda verificación redundante y frágil.

**Acotado a `book_appointment`** — deliberadamente NO se tocó `reschedule_appointment`/`cancel_appointment` (mismo patrón de `_tool_exitosa`): con `HrmmAppointmentService` real, esos flujos pasan por el sub-flujo de verificación por código de `gateway.py` (completo, fuera de `HealthBrain`/`agent.py` — ver docstring del módulo), no por aquí — no exhiben este mismo bug, y tocarlos sin un caso real que lo justifique sería ampliar el alcance sin evidencia.

## PUNTO 4 — ¿Quedó una cita real duplicada/huérfana en producción? `[CONFIRMADO — el usuario proveyó el documento real]`

Consulta real, de solo lectura, contra `GET /api/agenda/citas?documento_paciente=<documento real provisto por el usuario en el chat>` — no se registra el documento completo en este archivo (fuera del repo git de todas formas, pero se minimiza igual, mismo criterio de `.claude/rules/proteccion-datos-personales.md`).

**Resultado**: 5 citas reales para ese documento. Cuatro son historial previo (dos del 25-31 de agosto, ya en estados terminales "no_show"/"atendida"; dos más con fecha de creación 25 de agosto pero actualizadas hoy — probablemente parte del refresco diario del entorno de demo de hrmm-backend, `slot_id` con patrón `SLOT-SEED20260906-...`, no algo que ZANTIA haya tocado hoy).

**Una sí es un artefacto real de esta sesión de depuración**: `cita_id` con fecha 2026-09-07, servicio Pediatría, **`estado = "agendada"`** (creada hoy), con `nombre_paciente` y `telefono` **vacíos** — esa es la firma exacta de una reserva creada por el flujo INBOUND sintético de ZANTIA (`patient_contact={}` para una Activity sintética, nunca lleva nombre/teléfono reales). **No hay duplicado** — solo una fila con esa firma, consistente con que la idempotencia (`idempotency_key` atada al `activity_id`) evitó una segunda escritura real en el reintento ("La 2" otra vez).

**Consecuencia práctica**: existía una cita real, en producción, ocupando un turno real de Pediatría para el 2026-09-07, creada como efecto de esta sesión de pruebas — no de un paciente real que la necesitara.

**RESUELTO (2026-09-06)**: con autorización explícita del usuario, se canceló usando el mecanismo real ya construido (`HrmmAppointmentService.send_verification_code` + `cancel_appointment_verified`, el mismo camino que usaría un paciente real por el sub-flujo de verificación de `gateway.py`) — nunca un bypass administrativo (no existe uno sin código). Primer código venció antes de usarse (10 min de TTL); se reenvió uno nuevo y se confirmó la cancelación con éxito. Verificado con una consulta real e independiente (`GET /api/agenda/citas/CITA-4f8220b68f`): `estado: "cancelada"`, `updated_at` reflejando el momento exacto de la cancelación. El turno quedó liberado.

## Hallazgo adicional que cerró R-9 con datos reales

La misma consulta reveló, por primera vez con evidencia real, el vocabulario COMPLETO de `Cita.estado`: **"agendada", "atendida", "cancelada", "reprogramada", "no_show"**. Esto confirma exactamente la causa raíz: `_MAPA_ESTADO_HRMM` nunca tuvo `"agendada"` (adivinó `"reservada"`/`"confirmada"`, ambas incorrectas para una reserva recién creada) y tenía `"no_asistio"`/`"no_asistió"` en vez de `"no_show"` (ortografía real distinta). Corregido en `hrmm_appointment_service.py` con los 5 valores reales confirmados — `R-9` (`.ai/RISKS.md`) puede marcarse RESUELTO. Test nuevo: `test_mapear_estado_con_vocabulario_real_confirmado`.

Este hallazgo también corrige, de paso, un bug relacionado no reportado explícitamente pero real: `_resolver_consulta` (CONSULTAR_CITA) y la detección de "cita activa" para reprogramar/cancelar filtran por `status in (CONFIRMED, RESCHEDULED)` — con `"agendada"` cayendo antes al default `REQUESTED`, un paciente preguntando "¿cuál es mi cita?" **no habría visto su propia cita recién agendada**. Ya corregido con el mismo fix del mapeo.

## Verificación

- 3 tests nuevos (`tests/domains/health/test_confirmacion_reserva_real.py`), reproduciendo la conversación real exacta contra `HrmmAppointmentService`/`CatalogMirror` reales vía `FakeHttpClient` (nunca contra producción — ver recado 031 para por qué no se hacen escrituras reales sin autorización explícita).
- Suite completa: **217 tests pasando + 2 deshabilitados a propósito** (antes de esta sesión: 214). Cero regresiones.
- Test de control (`test_reserva_real_con_estado_ya_mapeado_sigue_funcionando_como_antes`) confirma que el comportamiento para un `estado` YA mapeado ("reservada") es idéntico al de antes del fix — la corrección no depende de qué tan bueno o malo sea el mapeo real, solo deja de exigirlo como condición de éxito.
