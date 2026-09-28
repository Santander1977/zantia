# 036 — Tolerancia a errores de tipeo al elegir un servicio (fuzzy matching)

**Fecha**: 2026-09-06
**Continúa**: recados 026-035 (misma conversación real de Telegram, mismo dominio de salud)
**Estado**: implementado, probado, **commiteado y pusheado** (`d7d4835`) — umbral 0.82 y tono de los 2 mensajes de ambigüedad aprobados por el usuario.

## Nota aparte: cancelación de `CITA-b1d3def03d` — RESUELTA

En paralelo a este trabajo, se completó la cancelación real que el usuario autorizó explícitamente (`CITA-b1d3def03d`, documento 72302972, Pediatría, Consultorio 3, 2026-09-07 07:30), usando el mismo mecanismo real ya construido (`send_verification_code` + `cancel_appointment_verified`, mismo camino que usaría un paciente real por el sub-flujo de verificación de `gateway.py`), nunca un bypass administrativo. El primer código enviado y el primer código que el usuario pasó (`442001`) habían vencido (TTL de 10 min, ver `app/recovery_codes.py`) por el tiempo transcurrido durante el trabajo de fuzzy matching de este mismo recado; se reenvió un código nuevo (con aprobación explícita del usuario, ya que el reenvío automático fue bloqueado por el clasificador de permisos de Claude Code por ser una escritura real de red) y se confirmó la cancelación con el código `261738`.

Verificado con una consulta real e INDEPENDIENTE de solo lectura (`get_appointment("CITA-b1d3def03d")`, llamada nueva y separada de la propia cancelación):

```
appointment_id: CITA-b1d3def03d
status: AppointmentStatus.CANCELLED
service: Pediatria
date/time: 2026-09-07 07:30
location: Consultorio 3
```

El turno quedó liberado. No queda ninguna cita huérfana de prueba conocida pendiente de esta conversación.

---

## Problema real

Con un catálogo de más de un servicio, `HealthBrain._interpretar_servicio` (recados 030/031) solo reconocía un nombre si calzaba EXACTO o como substring contra el catálogo real (ya normalizado sin tildes desde el recado 030). Un paciente real que escribe con errores de tipeo — "pedeatria", "pediatra", "medisina general", "sicologia", "urgencia" en singular contra un servicio real llamado "Urgencias" — no calzaba con nada, y caía siempre al mensaje "No logré identificar cuál de estos prefieres", aunque la intención fuera obvia para cualquier humano leyendo el mensaje.

## Solución: `difflib.SequenceMatcher` (librería estándar, sin dependencia nueva)

Verifiqué antes de implementar que `rapidfuzz` **no está instalado** en este proyecto (`ModuleNotFoundError`) y no aparece en `requirements.txt`. Tu pedido permitía cualquiera de las dos opciones ("difflib... o rapidfuzz si ya está disponible") — como no lo está, usé `difflib.SequenceMatcher` de la librería estándar de Python, sin agregar ninguna dependencia nueva al proyecto.

### Cómo funciona (`_emparejar_servicio_por_similitud`, `domains/health/brain.py`)

1. Se intenta primero el match EXACTO/substring de siempre (sin cambios) — más barato y sin ningún riesgo de falso positivo.
2. Si no hay match exacto, se compara el texto del paciente (tokenizado, sin tildes, sin puntuación de borde) contra cada nombre real del catálogo, usando ventanas contiguas de palabras del MISMO largo que el nombre del servicio — esto permite que el paciente escriba palabras de más alrededor ("necesito una cita de pedeatria por favor") sin que la comparación se vea penalizada por la longitud total del mensaje.
3. Se calcula `SequenceMatcher(None, ventana, servicio).ratio()` para cada ventana y cada servicio, y se toma el mejor puntaje por servicio.
4. Si **un solo** servicio cruza el umbral → se elige ese, se avanza a fechas.
5. Si **dos o más** servicios cruzan el umbral (ambigüedad genuina) → nunca se elige por el paciente; se le muestran solo esos candidatos cercanos (no el catálogo completo de nuevo).
6. Si **ningún** servicio cruza el umbral → mismo fallback de siempre, con las variantes rotativas del recado 034.

### Umbral elegido: **0.82 (82%)**

Calibrado con los ejemplos reales que pediste, contra un catálogo de prueba `["medicina general", "pediatria", "psicologia", "urgencias"]`:

| Texto del paciente | Mejor match | Puntaje | Segundo más cercano | Puntaje |
|---|---|---|---|---|
| `pediatria` (exacto) | pediatria | 1.000 | medicina general | 0.480 |
| `pedeatria` | pediatria | 0.889 | odontologia | 0.400 |
| `pediatra` | pediatria | 0.941 | medicina general | 0.500 |
| `urgencia` | urgencias | 0.941 | pediatria | 0.353 |
| `medisina general` | medicina general | 0.938 | pediatria | 0.588 |
| `sicologia` | psicologia | 0.947 | odontologia | 0.600 |
| `necesito una cita de pediatria por favor` | pediatria | 1.000 | urgencias | 0.500 |
| `odontologa` | odontologia | 0.952 | psicologia | 0.500 |
| `no se, cualquiera` | (ninguno) | 0.345 máx | — | — |
| **`medicina interna`** (servicio DISTINTO, similar por la primera palabra) | medicina general | **0.812** | pediatria | 0.588 |

El caso `medicina interna` es la prueba de que 0.82 sigue siendo estricto: puntúa **por debajo** del umbral (0.812 < 0.82) contra "medicina general", así que **no se confunde** con ese servicio — cae al fallback normal en vez de asumir el servicio equivocado. Todos los typos reales que pediste puntúan 0.889 o más, con un margen amplio sobre el segundo candidato más cercano (máximo 0.6).

### Corrección propia tras revisión del usuario

Al presentar este recado inicialmente escribí, por error, "dos servicios reales genuinamente parecidos entre sí" refiriéndome a `["pediatria", "psiquiatria"]`. El usuario cuestionó esto correctamente: **"psiquiatria" NO es parte del catálogo real** — el catálogo real confirmado hoy contra hrmm-backend tiene 5 servicios: **Medicina General, Odontologia, Pediatria, Psicologia, Urgencias**.

Aclaración de las dos preguntas que hizo:

1. **Fue un error de redacción mío**, no un bug del código ni del test. El test de ambigüedad usa un catálogo FICTICIO de prueba (`_CatalogoHipoteticoConAmbiguedad`, renombrado explícitamente para que quede inequívoco) — mismo patrón que ya usan otros tests de este archivo (ej. `_AppointmentServiceDosServicios` en `test_tildes_y_servicio_inicial.py` también inventa un catálogo ficticio). Se usa para ejercitar en aislamiento el camino de código de "ambigüedad genuina", porque el catálogo real de hoy no produce ese caso (ver más abajo) — nunca se presentó como un hallazgo sobre datos reales, pero mi redacción lo dio a entender por error.
2. **El código ya cumplía el requisito, verificado con evidencia de código**: `_emparejar_servicio_por_similitud(texto, servicios)` (`brain.py:288`) recibe `servicios` como **parámetro** — no hay ningún nombre de servicio escrito dentro de la función ni en ningún otro lugar de `brain.py`. Se invoca como `_emparejar_servicio_por_similitud(texto, servicios)` donde `servicios = self._appointment_service.list_services()`, que para `HrmmAppointmentService` (producción real) es literalmente `self._catalog.listar_nombres()` — el catálogo real sincronizado por `CatalogMirror` desde `GET /api/agenda/servicios`. Nunca hay una lista fija. Agregué un test directo que lo prueba (`test_matching_siempre_recibe_el_catalogo_como_parametro_nunca_fijo`) para que quede verificado, no solo argumentado.

Además, hice un barrido de typos plausibles contra el catálogo REAL de 5 servicios (ver `test_catalogo_real_de_5_servicios_no_produce_ambiguedad_falsa`) — **hoy no existe ninguna ambigüedad genuina entre esos 5 nombres reales**, son lo bastante distintos entre sí. El catálogo ficticio de 2 servicios parecidos sigue siendo necesario para probar que el mecanismo de ambigüedad funciona correctamente el día que sí ocurra (un catálogo real nunca es una garantía permanente de que dos nombres nunca se van a parecer).

## Ambigüedad genuina — ejemplo con catálogo ficticio de prueba

Con el catálogo FICTICIO de prueba `["pediatria", "psiquiatria"]` (nunca el real — ver corrección arriba):

| Texto | pediatria | psiquiatria |
|---|---|---|
| `pequiatria` | **0.842** | **0.857** |

Ambos cruzan el umbral de 0.82 — este es el caso donde el sistema **no elige por el paciente**. Sirve para probar el mecanismo en aislamiento, no como ejemplo del catálogo real.

## Ejemplos de tono (para tu aprobación)

**Typo reconocido, avanza normalmente** (sin cambio de tono — el paciente nunca ve que hubo "tolerancia a errores", simplemente avanza):
> Paciente: "pedeatria"
> ZANTIA: "Estas son las fechas disponibles: 1) Sábado 5 de septiembre; 2) Domingo 6 de septiembre. ¿Cuál te queda mejor?"

**Ambigüedad genuina** (nuevo mensaje, 2 variantes rotativas — texto EXACTO, verificado ejecutando el código real, `repr()` incluido para descartar cualquier corte o error de caracteres):

Primera vez en la conversación:
```
'Creo que podrías referirte a más de uno de estos: psiquiatria, pediatria. ¿Cuál de los dos es el que necesitas?'
```
(111 caracteres)

Si se repite en la misma conversación (segunda variante, rotación del recado 034):
```
'No quiero adivinar entre estos: psiquiatria, pediatria. ¿Me confirmas cuál de los dos prefieres?'
```
(96 caracteres)

Nota: el orden de los nombres es por puntaje descendente (psiquiatria 0.857 > pediatria 0.842) — con el catálogo real de 5, este ejemplo nunca ocurriría hoy (ver sección "Corrección propia" arriba); se muestra con el catálogo ficticio de prueba únicamente para que veas el tono exacto del mensaje.

**Texto no relacionado, fallback sin cambios** (mismo mensaje de siempre, recado 034):
> Paciente: "no sé, cualquiera"
> ZANTIA: "No logré identificar cuál de estos prefieres: medicina general, pediatria, psicologia, urgencias. ¿Me confirmas el nombre tal como aparece en la lista?"

## Requisito #5 — ¿aplica también a fecha/horario?

Confirmado con un test antes de decidir (no asumido): **no aplica**. La selección de fecha (`_interpretar_fecha`) y de horario (`_interpretar_horario`) usan `_elegir_opcion`, que reconoce únicamente ordinales ("1"/"primera", "2"/"segunda", "3"/"tercera") — nunca el nombre libre de una fecha u hora real. No existe ningún "nombre de catálogo" contra el cual el paciente pueda escribir un typo en esas dos etapas: el patrón de bug de este recado (comparar texto libre contra nombres reales) simplemente no existe ahí. Documentado con test explícito (`test_seleccion_de_fecha_es_por_ordinal_no_por_nombre_libre_no_aplica_fuzzy`) en vez de dejarlo como supuesto sin verificar.

## Verificación

- **14 tests nuevos** (`tests/domains/health/test_tolerancia_a_errores_de_tipeo_en_servicio.py`):
  - 2 tests de fuente del catálogo (agregados tras la corrección): `_emparejar_servicio_por_similitud` recibe el catálogo como parámetro, nunca fijo — probado directamente con dos catálogos distintos que cambian el resultado; y barrido de typos plausibles contra el catálogo REAL de 5 confirmando que hoy no produce ninguna ambigüedad falsa.
  - 6 typos reales pedidos explícitamente, ahora contra el catálogo REAL de 5 servicios, cada uno matcheando su servicio real correspondiente (incluyendo uno con palabras extra alrededor).
  - 3 tests de ambigüedad genuina (con el catálogo ficticio de prueba, ver corrección arriba): pide confirmar mostrando solo los 2 candidatos cercanos, nunca el catálogo completo; no se confunde con el fallback genérico; rota entre las 2 variantes si se repite.
  - 2 tests de "no debe matchear" contra el catálogo real: texto no relacionado, y el caso límite deliberado "medicina interna" (similar pero genuinamente distinto) para confirmar que el umbral sigue siendo estricto.
  - 1 test confirmando que fecha/horario no necesitan el mismo tratamiento (ordinal, no nombre libre).
- **Suite completa**: 248 passed, 2 skipped (234 anteriores + 14 nuevos) — cero regresiones.
- Guardrails + identidad corridos por separado: 30 passed, 1 skipped, sin cambios.
- Sin dependencias nuevas agregadas a `requirements.txt` — `difflib` es parte de la librería estándar de Python.
- Match exacto/substring de antes (recados 030/031) sigue intacto y sigue siendo la primera opción — el fuzzy matching es estrictamente un fallback adicional, nunca un reemplazo.

## Pendiente de tu aprobación

1. **El umbral 0.82** — ¿te parece razonable con la evidencia de la tabla de arriba, o prefieres uno más estricto/permisivo?
2. **El tono de los 2 mensajes de ambigüedad** (arriba) — ¿aprobado tal cual, o prefieres otra redacción?
3. Si apruebas ambos, quedo lista para commitear y pushear este recado (igual que 034/035), pendiente de tu confirmación explícita.
