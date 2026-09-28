# 076 — Extracción al Core: `TimedStateStore`, mecanismo genérico de "estado con ventana de tiempo"

**Fecha**: 2026-09-11
**Estado**: Implementado, probado, **cero regresiones confirmadas**. **Nada comiteado ni pusheado** — pendiente aprobación explícita, como pediste. **Nada desplegado en EasyPanel.**

---

## 0. Restricción respetada: cero cambio de comportamiento observable

Requisito explícito: "el comportamiento real de HealthBrain/gateway.py debe quedar IDÉNTICO al actual". Esto es un refactor interno puro — mismo texto, mismos tiempos (2 min / 30 min), misma lógica de decisión. La prueba de que se cumplió:

- **Suite completa antes del refactor**: 567 passed, 15 skipped, 0 failed.
- **Suite completa después del refactor + tests nuevos**: 576 passed, 15 skipped, 0 failed (los 9 nuevos son del mecanismo genérico en sí, `tests/core/test_timed_state.py` — ninguno de `domains/health/` cambió de cantidad).
- Ningún test de `domains/health/` se modificó por cambio de comportamiento — los 4 archivos tocados (`test_auditoria_salida_y_cierre_formal.py`, `test_pregunta_correo_y_despedida.py`, `test_saludo_corto_tras_cierre_reciente.py`, y un test del corpus de regresión) solo cambiaron CÓMO acceden al estado interno (`gateway._cierre_reciente[ref]` → `gateway._cierre_reciente.obtener_payload(ref)`, ya que el tipo cambió de `dict` a `TimedStateStore`) — nunca qué esperan que responda el sistema.

---

## 1. El mecanismo genérico — `core/timed_state.py`

Extraído del patrón real ya probado en `domains/health/gateway.py` a lo largo de 4 recados (057, 067, 069, 071) — ver el docstring completo del módulo para el detalle de cada uno.

### `TimedStateStore`

Registro `clave (texto) -> (momento real, payload arbitrario)`. El Core nunca sabe qué representa la clave ni el payload — eso es 100% del dominio que lo usa.

```python
store.registrar(clave, payload=..., ahora=None)     # registra/reemplaza (timestamp real, o controlado en tests)
store.obtener_payload(clave)                          # -> payload o None
store.actualizar_payload(clave, payload)               # reemplaza SOLO el payload, preserva el momento original
store.momento_de(clave)                                # -> datetime o None (para tests que simulan tiempo pasado)
store.transcurrido(clave, ahora=None)                   # -> timedelta o None
store.dentro_de_ventana(clave, ventana, ahora=None)      # -> bool
store.tiempo_restante(clave, ventana, ahora=None)        # -> timedelta (nunca negativo) o None
store.existe(clave) / clave in store
store.limpiar(clave)
```

### `VentanaDeTiempo` + `ModoVentana`

```python
VentanaDeTiempo(duracion: timedelta, modo: Optional[ModoVentana] = None, nombre: str = "")
ModoVentana.BLOQUEO   # dentro de la ventana: no procesar nada nuevo, informar tiempo restante
ModoVentana.ABIERTA   # dentro de la ventana: SÍ aceptar/acumular contenido nuevo
```

### Los dos modos, documentados explícitamente (requisito del pedido)

- **`BLOQUEO`** — único modo con uso real hoy: el enfriamiento de 2 minutos de ZANTIA tras una despedida.
- **`ABIERTA`** — sin ningún uso real todavía. El mecanismo lo soporta ESTRUCTURALMENTE (`actualizar_payload` preserva el `momento` original al aceptar contenido nuevo — así un dominio puede ir acumulando evidencia sin que cada actualización reinicie el plazo), pero ninguna lógica de negocio de ese caso vive en ningún archivo de este proyecto todavía — exactamente como pediste ("no implementes el caso (b) con lógica real, solo asegúrate de que no sea imposible después").
- **`modo` es opcional**: el saludo corto de 30 minutos de ZANTIA (recado 057) es un TERCER caso real que no encaja en ninguno de los dos — nunca bloquea, nunca acumula, solo elige qué texto de saludo mostrar. Documentado explícitamente en el módulo para que quede claro que `ModoVentana` es metadata descriptiva, no una restricción de uso.

---

## 2. Refactor de `domains/health/gateway.py` — mismo comportamiento, mecanismo nuevo por debajo

- Campo `_cierre_reciente`: de `Dict[str, Tuple[datetime, Optional[str], bool]]` a `TimedStateStore` (payload ahora `(nombre_conocido, es_despedida)` — el `momento` lo gestiona el store).
- `_VENTANA_SALUDO_CORTO`/`_VENTANA_ENFRIAMIENTO`: de `timedelta` sueltos a `VentanaDeTiempo` (mismas duraciones exactas: 30 min / 2 min).
- 2 sitios de escritura (`_cerrar_si_definitivo`, la rama `RequestIntent.SALIR` del recado 070/071) → `gateway._cierre_reciente.registrar(patient_reference, payload=(nombre, es_despedida))`.
- 2 sitios de lectura (el chequeo de enfriamiento y el chequeo de saludo corto en `handle_inbound_message`) → `dentro_de_ventana`/`tiempo_restante`/`obtener_payload`, mismo cálculo exacto que antes (incluido el "+1 segundo" de redondeo, que sigue siendo decisión del dominio, no del Core — documentado así en `tiempo_restante`).

---

## 3. Tests nuevos del mecanismo genérico — `tests/core/test_timed_state.py`

9 tests, con un dominio ficticio (un "trámite" de soporte, NO salud — mismo criterio que `tests/core/test_selection.py`):

- **Modo BLOQUEO** (5 tests): informa tiempo restante real, el tiempo restante disminuye con tiempo real transcurrido (no simulado con mocks de reloj — un `datetime` real desplazado), deja de aplicar pasada la ventana, `None`/`False` correctos cuando nunca se registró nada, `registrar` reemplaza una entrada existente por completo.
- **Modo ABIERTA** (4 tests) — usando el ejemplo ilustrativo real que pediste documentar (seguridad ciudadana, evidencia adjunta a un caso): confirma que `actualizar_payload` acumula contenido SIN reiniciar el `momento` original (2 actualizaciones seguidas, el timestamp no cambia ninguna vez), confirma que una ventana vencida no borra el payload acumulado (el Core nunca decide cerrar nada, solo informa), confirma que `actualizar_payload` nunca crea una entrada nueva implícitamente, confirma que `limpiar` borra correctamente.

---

## 4. `.ai/CORE_REUSABLE_PATTERNS.md` — nuevo, sucesor con evidencia real del recado 033

Cataloga TODO lo que hoy vive en `core/`/`guardrails/` y ya tiene evidencia real de uso (no un plan): `agent_contract.py`, `orchestrator.py`, `brain.py`, `config.py`, `selection.py` (recado 052), los guardrails del recado 037, y el nuevo `timed_state.py`.

Incluye el ejemplo de diseño COMPLETO que pediste para el dominio futuro de seguridad ciudadana (crear caso → confirmar → ventana de 5 minutos ABIERTA para adjuntar evidencia → cierre formal) — marcado explícitamente como "SOLO diseño, nada implementado", con el código ilustrativo de cómo se apoyaría en `TimedStateStore` para cuando se retome ese proyecto. También deja registrado que el plan del recado 033 (mover `identity_store` al Core) sigue `[PROPUESTO]`, sin retomar — el criterio de "listo" de ese recado (ausencia de bugs de conversación nuevos en `domains/health/`) sigue sin cumplirse (esta misma sesión encontró y corrigió los hallazgos de los recados 070-074) — y explica por qué esta extracción puntual (un patrón ya estabilizado en 4 recados, deliberadamente mínimo) es un caso distinto al riesgo que motivó "esperar" en el 033.

---

## 5. Archivos tocados

```
Nuevos:
  core/timed_state.py
  tests/core/test_timed_state.py
  .ai/CORE_REUSABLE_PATTERNS.md

Modificados (refactor interno, sin cambio de comportamiento):
  domains/health/gateway.py
  tests/domains/health/test_auditoria_salida_y_cierre_formal.py
  tests/domains/health/test_pregunta_correo_y_despedida.py
  tests/domains/health/test_saludo_corto_tras_cierre_reciente.py
  tests/domains/health/corpus_regresion/test_recado070_despedida_sin_conversacion_no_armaba_enfriamiento.py
```

**Nota aparte, no relacionada con este recado**: `.ai/DEPLOYMENT.md` sigue con cambios sin comitear de la sesión anterior (documentación del incidente de `HRMM_BACKEND_URL`, recado 075) — a la espera de tu decisión de cómo agruparlo. No lo toqué en este trabajo.

---

## 6. Nada comiteado, nada desplegado

Como pediste explícitamente. Suite completa verificada en verde (576 passed, 15 skipped, 0 failed). Quedo a la espera de tu aprobación para comitear — y de tu decisión sobre si el commit de `.ai/DEPLOYMENT.md` (recado 075) va junto o por separado.
