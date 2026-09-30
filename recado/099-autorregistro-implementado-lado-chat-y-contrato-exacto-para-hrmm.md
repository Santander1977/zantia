# RECADO PARA CHATGPT

Fecha: 2026-09-30
Proyecto: ZANTIA (repo `icaco`), con contrato para hrmm-backend
Tema: Autorregistro por chat, implementación del lado de ZANTIA (diseño de los recados 097/098, aprobado)
Objetivo de la investigación: Implementar el flujo del chat en paralelo a los cambios de hrmm, y dejar el contrato exacto que hrmm debe cumplir.

Estado: **implementado y probado en local, SIN commit y SIN despliegue.** No sirve en producción hasta que hrmm tenga los endpoints (§3). Mientras tanto, en producción el chat mostraría "Registrarme", pero el wizard respondería "En este momento no puedo completar registros por este chat" (§4.3).

## 1. Qué se implementó

| Archivo | Cambio |
|---|---|
| `domains/health/registro.py` (nuevo) | Wizard completo: autorización explícita → tipo de documento → nombre → fecha de nacimiento → correo → teléfono → EPS → régimen → resumen → creación en hrmm → código → identidad verificada. Incluye los límites de abuso (`LimitesRegistro`). |
| `domains/health/gateway.py` | Al no encontrar un documento con forma de documento, reconfirma el número y ofrece `1. Corregir / 2. Registrarme / 3. Contactar al hospital`. Escribir otro número en ese punto cuenta como corrección. Despacha a `registro.py` mientras hay un registro en curso. `_mensaje_verificacion_no_disponible` usa el helper nuevo `texto_contacto_hospital()`, sin cambio de texto. |
| `domains/health/hrmm_appointment_service.py` | `obtener_autorizacion_vigente` (verifica que el sha256 corresponda al texto), `listar_eps`, `registrar_autorizacion` y `registrar_paciente` (201 → `creado`, 409 → `ya_existe`). Todo fallo sale como `AppointmentServiceError`. **Nunca** usa el upsert `POST /api/agenda/pacientes`. |
| `domains/health/institutional_info.py` | `texto_contacto_hospital()`: única fuente de la frase con los canales reales del hospital. |
| `tests/domains/health/test_autorregistro.py` (nuevo) | 31 tests con un hrmm simulado que cumple el contrato de §3. |
| `.ai/INTEGRATIONS.md`, `.ai/DATA_MODEL.md`, `.ai/ARCHITECTURE.md` | Datos nuevos enviados a hrmm y su propósito, propósito de cada dato antes de recolectarlo, y el componente nuevo. |

Suite completa: **671 passed, 17 skipped** (antes 640, más 31 nuevos).

### Reglas implementadas (todas con test)
- **Autorización (Ley 1581):**
  - Solo cuentan `1`, `acepto` o `sí acepto` (con o sin tilde o puntuación). `sí`, `ok`, `dale`, `claro` y `listo` **no** cuentan, y el bot vuelve a preguntar.
  - En este paso nunca interpreta un LLM.
  - Si el paciente rechaza, no se envía **nada** a hrmm y se le derivan los canales reales del hospital.
  - Si el sha256 del texto no coincide, el texto no se muestra.
- **Nada llega a hrmm antes de confirmar el resumen.** Después el orden exacto es: autorización → registro → código enviado → código confirmado.
- **Menores:** con TI o RC, o con menos de 18 años según la fecha de nacimiento, el registro se corta sin enviar nada.
- **Documento existente:** nunca se ofrece el registro. Si hrmm responde 409 al crear, no se envía código y el bot dice "Ya existe un registro…".
- **EPS y régimen son opcionales.** "No sé / prefiero no decir" se guarda como `Pendiente`, y `Pendiente` nunca aparece como una EPS elegible. Sin lista de EPS disponible, el registro sigue con `Pendiente`.
- **Código:**
  - Un texto que no son 6 dígitos **nunca viaja a hrmm** (lección del recado 094).
  - Con 3 códigos inválidos, el registro termina sin bucle.
  - Si el código no se envió, nada queda esperando uno (lección del recado 096).
- **Límites:**
  - 1 registro creado por identidad de canal cada 24 horas, incluso si lo abandonó.
  - Tope global de 10 por hora en el chat web y 30 en los demás canales.
  - Todo en memoria de proceso, con la misma limitación aceptada en R-11.
- **Salir** en cualquier paso, salvo el del código: se cancela sin guardar nada.

## 2. Diferencia con el diseño aprobado (documentada, no silenciosa)

En el recado 097 §2.5, el código iba antes del teléfono, la EPS y el régimen. **Con el contrato del 098 §3, hrmm envía el código al correo de un registro que ya existe como pendiente (cambio 3)**, así que el pendiente tiene que crearse antes del código, con todos los datos. Consecuencia: si el correo no se verifica, los datos quedan en hrmm como pendientes hasta 30 minutos (cambio 6). Mantener el orden original exigiría un endpoint más en hrmm para actualizar el pendiente. Se optó por no pedirlo.

## 3. Contrato EXACTO para hrmm-backend (para la sesión de hrmm)

> Complementa la lista de 7 cambios del recado 098 §3 con las **formas exactas** que ZANTIA ya consume. Todos requieren `X-Backend-Secret`. La referencia viva es `tests/domains/health/test_autorregistro.py`.

1. `GET /api/agenda/autorizacion-datos/vigente` → `200 {"version": str, "texto": str, "sha256": str}`, donde `sha256 = sha256(texto.encode("utf-8")).hexdigest()`. ZANTIA lo verifica y, si no coincide, no muestra el texto.
2. `POST /api/agenda/autorizacion-datos`, body `{"documento_paciente", "tipo_documento", "version", "sha256", "canal", "aceptado_en"}` (`aceptado_en` en ISO-8601 UTC; `canal` es `web` / `telegram` / `chatwoot`) → `201 {"autorizacion_id": str}`. Si `sha256` no corresponde a `version`, conviene responder 422; ZANTIA trata cualquier respuesta distinta de 200/201 con `autorizacion_id` como "servicio no disponible".
3. `GET /api/agenda/eps` → `200 ["Nueva EPS", …, "Otra", "Pendiente"]`. ZANTIA oculta `Pendiente` de las opciones y lo usa para "no sé".
4. `POST /api/agenda/pacientes/registro`, body `{"documento_paciente", "tipo_documento", "nombre_paciente", "fecha_nacimiento" (AAAA-MM-DD), "correo", "telefono", "eps", "tipo_afiliacion", "autorizacion_id", "canal"}` → `201` (crea `pendiente_verificacion`) o `409` (existe o está en curso; **no modifica nada**). Valores de `tipo_documento`: `CC`, `CE`, `PPT`, `PA`. `TI` y `RC` nunca llegan desde el chat. Valores de `tipo_afiliacion`: `Contributivo`, `Subsidiado`, `Especial o de excepción`, `No afiliado (particular)`, `Pendiente`.
5. `POST /api/agenda/verificacion/enviar` `{"documento_paciente"}` (ya existe): para un documento con registro **pendiente**, envía el código al correo de ese registro → `200 {"enviado": true, "correo_parcial": "f***@…"}`.
6. `POST /api/agenda/verificacion/confirmar` `{"documento_paciente", "codigo"}` → `200` si es válido, `401` si no. **Al acertar sobre un registro pendiente, lo pasa a `verificado_correo`.**
7. `GET /api/agenda/citas/buscar-paciente?documento=` (ya existe): debe responder `200` también para un paciente `verificado_correo` sin citas (cambio 2 del 098).

**Texto que hrmm debe servir como versión inicial** (`version = "borrador-sin-revision-legal-v0"`). Los `[PENDIENTE]` los decide el hospital (R-29). **No es un texto final**:

```
[BORRADOR SIN REVISIÓN LEGAL — NO USAR CON PACIENTES REALES]
Antes de registrarte necesito tu autorización. [PENDIENTE: nombre formal del responsable del tratamiento] tratará tus datos (nombre, documento, fecha de nacimiento, correo, teléfono y afiliación a EPS) para registrarte como paciente, agendar y gestionar tus citas y enviarte confirmaciones y códigos de verificación. Los datos sobre tu afiliación en salud son sensibles: responder esas preguntas es opcional. Tienes derecho a conocer, actualizar, rectificar y suprimir tus datos, y a revocar esta autorización, escribiendo a [PENDIENTE: canal oficial de habeas data]. Política completa: [PENDIENTE: URL de la política de tratamiento]. ¿Autorizas el tratamiento de tus datos para estos fines?
```

ZANTIA agrega al final `1. Acepto` / `2. No acepto`. Por eso el texto no las incluye.

## 4. Riesgos y pendientes

1. **R-29 (ABIERTO):** el texto está sin revisión legal y faltan los datos del hospital y la lista real de EPS. Bloquea producción real, no las pruebas.
2. **R-3 (ABIERTO):** el registro deja una traza consultable del lado de hrmm (cambio 7). La consulta y eliminación desde el chat siguen sin diseño.
3. **Si se despliega ZANTIA antes que hrmm:** "Registrarme" aparece, pero el wizard responde "En este momento no puedo completar registros por este chat" con los canales del hospital, porque `autorizacion-datos/vigente` responde 404. No rompe nada, pero ofrece algo que todavía no funciona. **Recomendación: desplegar ZANTIA después de hrmm**, o pedirme un interruptor para ocultar la opción.
4. Límites en memoria: se pierden en cada reinicio (R-11). Aceptable para la v1.
5. ZANTIA registra en su log los eventos del registro sin datos personales. La auditoría que cuenta es la de hrmm (cambio 7).

---

## Anexo: decisión del usuario (2026-09-30)

- **Recado 099 aprobado sin reservas**, incluida la diferencia de orden (§2): no se le pide a hrmm un endpoint extra.
- **Secuencia de despliegue:** **NO desplegar todavía.** hrmm está implementando los hallazgos de seguridad H1, H3 y H3b (recado 107 de hrmm), que son más urgentes y van primero. El autorregistro se despliega solo cuando el usuario confirme que la parte 1 de hrmm (H3 + H3b + H1) está en producción. Ese es el orden correcto del riesgo 3 de §4.
- Se commitea sin push y sin desplegar.
