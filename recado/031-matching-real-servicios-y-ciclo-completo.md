# 031 — Matching real de servicios, quinto hallazgo (loop tras elegir servicio válido) y 10 corridas del ciclo completo

**Fecha**: 2026-09-06
**Continúa**: recados 026-030 (misma conversación real de Telegram)

## PARTE 1 — Matching real de servicios/disponibilidad

### Hallazgo más importante: NO era un bug de matching

`[CONFIRMADO con una llamada real, de solo lectura, contra hrmm-backend en producción]`:

```
GET /api/agenda/servicios  -> Medicina General, Odontologia, Pediatria, Psicologia, Urgencias
```

**El catálogo real de hrmm-backend NO usa tildes.** "Pediatria", "Odontologia", "Psicologia" — sin acento, confirmado en vivo el 2026-09-06. Esto contradice la premisa del reporte ("el catálogo se lista con tildes: 'Pediatría'") — no pude reproducir esa discrepancia con los datos reales actuales; lo más probable es un error de transcripción al reportar el hallazgo, o que el proceso desplegado tuviera cacheado un catálogo de un momento anterior con otra convención (`CatalogMirror` solo sincroniza una vez al arrancar, nunca se re-sincroniza automáticamente — `.ai/RISKS.md`, sección de recomendaciones). No se pudo confirmar cuál de las dos por falta de logs de ese momento exacto (mismo límite ya documentado en R-11).

Con el nombre elegido por el paciente (`HealthBrain._interpretar_servicio`, recado 030) siempre siendo EXACTAMENTE uno de los nombres reales del catálogo (nunca un valor libre inventado), y el catálogo real sin tildes, la traducción `nombre -> servicio_id` (`CatalogMirror.servicio_id_por_nombre`) no tenía en realidad ningún mismatch de tildes que corregir en el camino que se reprodujo.

**Se aplicó la normalización de tildes de todas formas** (mismo criterio ya usado en recados 026/027/030) directamente en `CatalogMirror.servicio_id_por_nombre` — es el ÚNICO punto real donde un nombre se traduce a `servicio_id` para consultar disponibilidad, y protege un camino DISTINTO que si es un riesgo real: `Activity.service` de una campaña OUTBOUND (demanda inducida) lo define el sistema fuente (la IPS), que podría usar una convención de acentuación distinta a la de hrmm-backend — un mismatch ahí sí causaría "sin disponibilidad" real sin que el paciente haya escrito nada. Test de control: `test_catalog_mirror_servicio_id_por_nombre_ignora_tildes` (simula un catálogo CON tilde, confirma que "Pediatria"/"pediatria"/"Pediatría" resuelven al mismo `servicio_id`).

### El hallazgo real: hoy no hay NINGÚN cupo disponible, en ningún servicio

`[CONFIRMADO con una llamada real, de solo lectura]`:

```
GET /api/agenda/disponibilidad  ->  []   (HTTP 200, cero bloques)
```

Esto es **antes de filtrar por servicio o por "Libre"/"Reservado"** — la respuesta cruda ya viene vacía. No es un problema de Pediatría específicamente, ni un problema de ZANTIA: **el calendario real de hrmm-backend no tiene ningún bloque de disponibilidad cargado en este momento, para ningún médico, de ningún servicio.** Confirmado cruzando `GET /api/agenda/medicos` (6 médicos reales, repartidos en los 5 servicios) contra la disponibilidad vacía.

**Esto responde directamente el punto 2 pedido**: no es un bug — es un hecho real del sistema de agenda en este momento. Dicho de otra forma: **hoy, un ciclo de reserva real contra producción no tiene ningún turno real que reservar**, para ningún servicio, independientemente de cualquier corrección de código. (Nota: en el recado 010, el 2026-09-01, la misma llamada sin filtros devolvió 10311 bloques reales — el calendario de este entorno de demo/prueba parece no repoblarse automáticamente con fechas futuras.)

## PARTE 2 — El loop tras elegir un servicio válido

### Diagnóstico confirmado

Reproducido exactamente: preguntar "qué servicios tienen" como **primer mensaje** de una conversación devuelve el catálogo correctamente, pero **no abre ninguna Activity/conversación rastreable** (`find_open_context` devolvía `None` después). Cuando el paciente respondía justo después nombrando un servicio real ("Medicina general"), esa respuesta se procesaba como un mensaje **completamente nuevo y sin relación** — `classify_intent("medicina general")` no coincide con ninguna palabra clave específica, cae al fallback por defecto (`PROGRAMAR_CITA`), que vuelve a preguntar "¿para cuál servicio?" desde cero (ignorando lo que el paciente acababa de decir) — y si la secuencia real tuvo un paso más de por medio, terminaba en el fallback genérico de sí/no de `HealthBrain`, exactamente como se reportó.

Mismo defecto, en paralelo, **dentro** de una conversación ya abierta: `HealthBrain._interpretar_decision`, rama `_CONSULTAR_SERVICIOS` (recado 027), listaba el catálogo pero se quedaba en la etapa `"esperando_decision"` — sin ningún patrón ahí que reconociera un nombre de servicio como respuesta válida.

### Corrección

Ambas rutas ahora dejan la conversación en la etapa `"esperando_servicio"` (el mismo mecanismo que `gateway.py:_resolver_programar_cita` ya usaba correctamente cuando detecta 2+ servicios reales, recado 030) inmediatamente después de listar el catálogo:

- `gateway.py`: nueva función `_resolver_consulta_catalogo` (reemplaza a `_mensaje_catalogo_real`) — abre una Activity sintética con `service=None` (nunca asume ninguno) y dejando la etapa en `"esperando_servicio"`.
- `brain.py`: la rama `_CONSULTAR_SERVICIOS` de `_interpretar_decision` ahora transiciona a `"esperando_servicio"` cuando el catálogo tiene servicios que listar.

La respuesta siguiente del paciente se interpreta con `HealthBrain._interpretar_servicio` (recado 030, sin cambios en su lógica) — el mismo mecanismo que ya funcionaba correctamente cuando la pregunta de servicio se disparaba desde `_resolver_programar_cita`.

Un test existente (`test_catalogo_no_crea_ni_registra_una_conversacion_abierta`) encodeaba la garantía VIEJA (y ya incorrecta) de que una pregunta de catálogo nunca debía abrir una conversación — se actualizó para verificar la garantía correcta: sí abre una, pero sin asumir ningún servicio y dejándola en `esperando_servicio`, nunca saltando directo a una reserva.

## Sobre "probar el envío del correo de confirmación" — límite real, no implementado

`[CONFIRMADO leyendo el código]`: **ZANTIA no envía ningún correo de confirmación hoy, y no puede hacerlo con el código actual.** `HrmmAppointmentService.book_appointment` nunca incluye un campo `correo` en el `POST /api/agenda/citas` (riesgo `R-21`, documentado y ABIERTO desde el recado 015) — y la razón de fondo, confirmada ahora con más detalle: **`Activity.patient_contact` no tiene ningún mecanismo para capturar un correo del paciente en ningún punto de la conversación** — no se pregunta, no se guarda, no se pasa a ningún lado. `GET /citas/buscar-paciente` (la única fuente de datos del paciente que ZANTIA consulta) tampoco expone un correo.

Resolver esto de verdad requiere una decisión de producto que no se puede tomar de forma autónoma en esta sesión: ¿en qué momento de la conversación se le pide el correo al paciente? ¿es obligatorio para reservar, u opcional? ¿se reutiliza el correo que hrmm-backend ya tenga registrado del paciente (si lo tiene, y si existe un endpoint para consultarlo — no confirmado)? Por eso **no se implementó** — quedó exactamente donde estaba (R-21, ABIERTO), documentado aquí con el detalle adicional en vez de tocarlo sin definir el diseño primero.

**Consecuencia práctica para el pedido de "probar el ciclo completo incluyendo el correo"**: no es posible probar algo que el código no hace. Las 10 corridas de abajo verifican el ciclo completo hasta donde ZANTIA participa (servicio → disponibilidad real → reserva → `APPOINTMENT_CONFIRMED`) — ninguna incluye ni puede incluir un envío de correo real.

## Por qué las 10 pruebas corrieron contra test doubles, no contra producción real

Dos motivos, ambos ya explicados arriba, y un tercero de seguridad:

1. **Hoy no hay ningún cupo real que reservar** (Parte 1) — un ciclo de reserva real no tendría nada que reservar en este momento.
2. **Reservar (`POST /api/agenda/citas`) es una escritura contra producción real, sin entorno de staging** (`R-7`, `.ai/RISKS.md`, sigue ABIERTO) — nunca se ha ejercitado escritura real contra hrmm-backend (`R-6`, sigue ABIERTO). Ejecutar 10 reservas reales (aunque hubiera cupos) ocuparía turnos reales de un sistema de agenda real, sin poder deshacerlo limpiamente y sin que exista todavía una decisión explícita del usuario de hacerlo contra producción.
3. Por la regla de protección de producción de este proyecto (`.claude/rules/proteccion-produccion-y-codigo.md`): una escritura contra un servicio real requiere autorización explícita del usuario en la sesión concreta — no asumida de un pedido general de "probar el ciclo completo".

**Si el usuario quiere una prueba de escritura real** contra hrmm-backend (con cupos reales, cuando existan), es una decisión aparte y explícita — this recado la deja lista para pedirse: el test gateado ya existe desde el recado 015 (`tests/domains/health/test_identidad_persistente.py::test_identidad_canal_real_e2e`, variable `ZANTIA_RUN_REAL_HRMM_TESTS`), aunque ese test específico es sobre identidad, no sobre reserva — habría que construir uno nuevo, y solo con confirmación explícita.

## Resultado consolidado — 10 corridas del ciclo completo (servicio → disponibilidad → reserva → confirmación)

Contra `MockAppointmentService` con un catálogo de 5 servicios (mismos nombres reales confirmados en la Parte 1, sin tildes) y 3 turnos libres por servicio — variando mensaje inicial (con/sin tilde, distintas formas de pedir cita), nombre de servicio (con/sin tilde, mayúsculas/minúsculas) y selección de turno (número/ordinal):

| # | Paciente | Mensaje inicial | Servicio elegido | Selección | Resultado |
|---|---|---|---|---|---|
| 1 | TG-CICLO-1 | "que servicios tienen" | medicina general | "1" | ✅ CONFIRMED |
| 2 | TG-CICLO-2 | "Que tienes disponible para citas" | Medicina General | "2" | ✅ CONFIRMED |
| 3 | TG-CICLO-3 | "necesito una cita" | pediatria | "primera" | ✅ CONFIRMED |
| 4 | TG-CICLO-4 | "Necesito una cita" | Pediatria | "segunda" | ✅ CONFIRMED |
| 5 | TG-CICLO-5 | "cual tienes" | odontologia | "1" | ✅ CONFIRMED |
| 6 | TG-CICLO-6 | "Cuál tienes" | Odontologia | "tercera" | ✅ CONFIRMED |
| 7 | TG-CICLO-7 | "qué servicios tienen" | psicologia | "1" | ✅ CONFIRMED |
| 8 | TG-CICLO-8 | "quiero agendar una cita" | Psicologia | "segunda" | ✅ CONFIRMED |
| 9 | TG-CICLO-9 | "cuales servicios tienes" | urgencias | "1" | ✅ CONFIRMED |
| 10 | TG-CICLO-10 | "Necesito Una Cita" | Urgencias | "primera" | ✅ CONFIRMED |

**10/10 pasando.** Cada corrida verifica, con datos reales del propio dominio (no solo texto): la Activity alcanza `ManagementStatus.APPOINTMENT_CONFIRMED`, tiene un `appointment_id` real, y `AppointmentService.get_patient_appointments()` confirma la cita del lado del "sistema de agenda" — nunca solo un texto optimista sin respaldo (principio ya establecido desde el recado 007).

## Verificación general

- Suite completa: **214 tests pasando + 2 deshabilitados a propósito** (antes de esta sesión: 204). Cero regresiones.
- 1 test actualizado (`test_catalogo_no_crea_ni_registra_una_conversacion_abierta` → renombrado y reescrito para verificar la garantía correcta).
- Nada se escribió contra producción real — todas las verificaciones de red real en esta sesión fueron `GET` (lectura), explícitamente autorizadas por el pedido del usuario.

## Pendiente, explícitamente NO resuelto en esta sesión

1. **R-21** (correo de confirmación) — requiere decisión de diseño de producto antes de tocar código.
2. **R-6/R-7** (escritura real contra hrmm-backend, sin staging) — sigue sin ejercitarse, correctamente, a la espera de autorización explícita y de que existan cupos reales.
3. **Re-sincronización periódica de `CatalogMirror`** — sincroniza una sola vez al arrancar el proceso; si el catálogo real cambia mientras el proceso sigue corriendo, ZANTIA no se entera hasta el próximo reinicio. Podría explicar una eventual discrepancia futura entre lo que el paciente ve y el catálogo real vigente — no confirmado como causa de nada ya reportado, pero es un riesgo real no cubierto todavía.
