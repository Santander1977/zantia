# 063 — Mismo callejón sin salida, ahora en el gate de identidad de canal (primer contacto)

**Fecha**: 2026-09-10
**Estado**: Corregido y probado. Reutiliza el clasificador compartido del recado 062 (refactorizado para ser genuinamente compartido, no duplicado).

---

## 1. Confirmación de causa raíz — `[CONFIRMADO]`, leyendo el código real

`_gestionar_identificacion` (`domains/health/gateway.py`, recados 012/014) tiene el MISMO patrón estructural que el wizard de cancelar/reprogramar (recado 062), en sus DOS etapas:

- **`esperando_documento`** (primer paso, ANTES de validar nada): cualquier texto se toma literalmente como `documento = text.strip()` y se busca contra `buscar-paciente`. Si no calza, se cuenta como intento fallido — tras 3, escala a un humano (mecanismo YA existente, único paracaídas real en esta etapa). Una pregunta, un "salir", o una expresión emocional se malinterpretaban como un documento inválido, consumiendo intentos sin necesidad.
- **`esperando_codigo`** (documento ya validado contra `buscar-paciente`, código de verificación enviado): cualquier texto se toma literalmente como `codigo` y se envía a `confirm_verification_code`. **Esta etapa era objetivamente MÁS grave que la del recado 062**: a diferencia del wizard de cancelar/reprogramar, acá NO existe ningún contador de intentos ni escalamiento propio — el propio código documenta explícitamente que se confía por completo en el límite de hrmm-backend (5 intentos, TTL 10 min). Sin ese fix, un paciente que preguntara o pidiera ayuda en esta etapa podía quedar genuinamente sin salida alguna dentro de ZANTIA.

Confirmado con un test de control ANTES de corregir (reproducido localmente): "¿a cuál correo lo enviaron?" se enviaba tal cual como intento de código.

## 2. Corrección — mecanismo COMPARTIDO, no duplicado (requisito #2)

Refactoricé el detector del recado 062 en dos piezas:
- **`_clasificar_interrupcion_wizard(texto)`** (`gateway.py`) — clasificador PURO (sin `gateway`, sin efectos secundarios), reconoce las mismas 5 categorías (`salir`/`reenviar`/`pregunta_correo`/`consulta_citas`/`emocional`), con las MISMAS listas de palabras y el MISMO umbral fuzzy (0.82, recado 036) — una sola fuente de verdad, usada ahora por AMBOS wizards.
- **`_reenviar_codigo`/`_respuesta_pregunta_correo_wizard`/`_respuesta_expresion_emocional_wizard`** — generalizadas para recibir el `documento`/`pendiente` explícito de cada wizard (claves de dict distintas: `documento_paciente` vs. `documento_candidato`), reutilizadas tal cual.

Cada wizard decide QUÉ hacer con la categoría detectada, porque tienen datos y garantías distintas disponibles — eso es diseño, no duplicación (ver punto 4).

**"salir" sigue siendo coincidencia EXACTA, nunca fuzzy** (requisito #3) — mismo criterio y misma razón que el recado 062: una salida es irreversible sin confirmación adicional; mejor un falso negativo (corregible con un segundo mensaje) que un falso positivo que interrumpa un documento/código real que el paciente esté escribiendo. Verificado que un documento/código real (numérico) nunca puntúa por encima del umbral contra ninguna frase de estas listas (mismo análisis empírico del recado 062, ninguna colisión posible).

## 3. Decisión de fondo sobre "salir" en ESTE wizard — pensada, no improvisada (requisito #4)

**Pregunta**: ¿el paciente queda sin identificar y vuelve al punto de partida, o hay un estado intermedio razonable?

**Respuesta, con evidencia**: `_gestionar_identificacion` SOLO se alcanza cuando `patient_reference not in gateway._identidad_resuelta` (gate en `handle_inbound_message`) — es decir, **mientras se está dentro de este wizard, nunca existe ninguna identidad confiable todavía, en ninguna etapa**. Ni siquiera con el documento ya validado contra `buscar-paciente` (etapa `esperando_codigo`): eso confirma que el documento EXISTE, no que la persona del otro lado del canal es su dueña — para eso está el segundo factor, que es precisamente lo que "salir" interrumpe.

**Conclusión**: no existe ningún estado intermedio seguro que preservar. La única opción correcta es la (a) que planteaste — el paciente queda sin identificar y vuelve al punto de partida, igual que un contacto genuinamente nuevo. `del gateway._pending_identity[patient_reference]` logra esto sin dejar estado residual. La fila `PENDIENTE_VERIFICACION` que pueda haber quedado en `identity_store` (si ya se había enviado un código) es inofensiva por diseño — nunca otorga acceso por sí sola (solo `marcar_verificado`, al completar el segundo factor, escribe `VERIFICADO`), y un intento futuro la sobrescribe sin acumular filas huérfanas.

## 4. Decisión de seguridad adicional, encontrada al implementar (no estaba en el pedido explícito, pero era necesaria)

Al conectar `_CONSULTA_CITAS_EXISTENTES` a este wizard, encontré que la implementación ingenua (igual que en el recado 062) revelaría las citas reales del paciente usando `documento_candidato` — es decir, **antes de confirmar el segundo factor**. Esto socavaría la razón de ser completa de este gate (recados 012/014: un documento por sí solo NO prueba identidad en un canal como WhatsApp — cualquiera que lo conozca o lo adivine podría ver citas ajenas). Por eso, en este wizard específicamente, "consulta_citas" se reconoce (no cae en "código inválido") pero se **redirige** (`_MENSAJE_CITAS_ANTES_DE_VERIFICAR`) en vez de responderse con datos reales — a diferencia del wizard de cancelar/reprogramar (recado 062), donde la identidad YA estaba confirmada antes de entrar, así que mostrar las propias citas ahí siempre fue seguro. Documentado en el propio código (docstring de la constante), para que quede claro que es una decisión deliberada, no un olvido.

## 5. Verificación

Tests nuevos en `tests/domains/health/test_identity_gate_chatwoot.py`:
- `test_wizard_identidad_no_queda_atrapado_esperando_codigo` — reproduce el escenario equivalente al de la transcripción real (identificándose → pregunta sobre el correo → pide reenvío [confirmado con 2 llamadas reales a `verificacion/enviar`] → pregunta por sus citas [confirmado que NO revela datos reales] → sale). Ninguno cae en "código inválido".
- `test_salir_durante_gate_de_identidad_vuelve_al_punto_de_partida` — "salir"/"exit"/"cancelar esto" funcionan en AMBAS etapas (`esperando_documento` y `esperando_codigo`); confirma `_pending_identity` vacío, `_identidad_resuelta` nunca poblado, reintento posterior arranca limpio desde `esperando_documento`.
- `test_wizard_identidad_reconoce_expresiones_con_errores_de_tipeo` — "Estoy tristw" reconocida en ambas etapas, sin perder el progreso ya alcanzado.
- `test_codigo_y_documento_reales_siguen_funcionando_sin_confundirse_con_un_comando` — control anti-regresión.

**Suite completa**: `498 passed, 9 skipped` (494 previas del recado 062 + 4 nuevas). Cero regresiones.

## 6. Archivos tocados (recados 062+063 juntos, mismo diff sin commitear)

- `domains/health/gateway.py` — clasificador compartido + dispatch en ambos wizards + 2 nuevas constantes de mensaje (`_MENSAJE_SALIR_GESTION_IDENTIDAD`, `_MENSAJE_CITAS_ANTES_DE_VERIFICAR`, `_MENSAJE_EMOCIONAL_ESPERANDO_DOCUMENTO`) + `correo_parcial` guardado en `_pending_identity`.
- `domains/health/brain.py` — sin cambios adicionales en este recado (el mecanismo fuzzy genérico y la entrada nueva en `_CONSULTA_CITAS_EXISTENTES` ya se agregaron en el recado 062).
- `tests/domains/health/test_identity_gate_chatwoot.py` — 4 tests nuevos.

Listo para commitear junto con el trabajo del recado 062 (mismo diff, nunca llegó a commitearse por separado).
