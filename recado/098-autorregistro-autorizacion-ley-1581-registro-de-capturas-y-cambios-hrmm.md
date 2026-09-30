# RECADO PARA CHATGPT

Fecha: 2026-09-30
Proyecto: ZANTIA (repo `icaco`), con cambios requeridos en hrmm-backend
Tema: Autorregistro, parte 2. Paso de autorización explícita (Ley 1581), registro de capturas preparado para R-3, y lista de cambios para la sesión de hrmm
Objetivo de la investigación: Incorporar las decisiones del usuario del 2026-09-30 al diseño del recado 097, sin implementar todavía.

Modo: SOLO DISEÑO. Todo lo marcado `[PROPUESTO]` está sin implementar. Continúa el recado `097`, que sigue vigente salvo lo que este reemplaza explícitamente.

## Decisiones del usuario que se incorporan

1. **Menores:** fuera de la v1; en una v2, a cargo del acudiente. Se mantiene lo que ya decía el 097 §2.6.
2. **R-2 RESUELTO: aplica la Ley 1581 de 2012 (Colombia).** Registrado en `docs/CLIENT.local.md` (no versionado) y en `.ai/RISKS.md`. El registro exige **autorización explícita**, guardada con la fecha y la versión del texto mostrado.
3. **R-3 no se resuelve ahora**, pero el registro no debe empeorarlo: cada captura tiene que quedar clara y consultable. R-3 queda en `.ai/RISKS.md` como **bloqueante separado, con diseño propio pendiente**.
4. Lista de cambios de hrmm, lista para copiar (§3).
5. **Lista real de EPS: PENDIENTE.** El mensaje del usuario llegó cortado en ese punto. El diseño deja la lista **parametrizada** en hrmm (cambio 5), así que el dato puede llegar después sin rediseñar. No se inventó ninguna EPS.

---

## 1. Paso de autorización de tratamiento de datos

### 1.1 Dónde va en el flujo
```
documento no encontrado → reconfirmación → "2. Registrarme"
  → [AUTORIZACIÓN]  ← primer paso del registro, antes de pedir o guardar cualquier dato
  → tipo de documento → nombre → fecha de nacimiento → correo → código → teléfono → EPS → régimen
  → resumen "¿Confirmas?" → creación
```
El número de documento ya lo escribió el paciente antes, pero **solo se usó para buscarlo; no se guarda** para el registro hasta que haya autorización. Si el paciente no acepta, no se persiste ningún dato personal.

### 1.2 Cómo se acepta, de forma explícita y determinista
Mismo principio que `ConfirmacionEstructuradaRequeridaParaWriteGuardrail`: la aceptación nunca sale de lo que interprete un LLM.

- El bot muestra el texto y dos opciones: `1. Acepto` y `2. No acepto`.
- **Solo cuentan como aceptación** el ordinal `1`, la palabra `acepto` como palabra completa, o las frases `sí acepto` / `si acepto`. Nunca un "sí" suelto, un "ok" ni ninguna frase ambigua.
- Tampoco se usa `interpret_selection` (LLM) en este paso, aunque esté configurado: si nada determinista coincide, se vuelve a preguntar.
- `2` / `no acepto` / `no`: se termina con el mensaje de canales reales del hospital (`INFORMACION_HOSPITAL`). Solo queda un evento anónimo (`AUTORIZACION_RECHAZADA`, sin documento) para métricas.
- Si el paciente pide "salir" o una aclaración, se aplica el mismo clasificador de interrupciones de los wizards (recados 062/063).

### 1.3 Contenido del texto (Ley 1581 y Decreto 1377 de 2013)
**[PROPUESTO] BORRADOR PARA REVISIÓN LEGAL, no es un texto final.** La interpretación jurídica marcada `[INFERIDO]` debe validarla quien el hospital designe.

> Antes de registrarte necesito tu autorización.
> **[PENDIENTE: nombre formal del responsable del tratamiento]** tratará tus datos (nombre, documento, fecha de nacimiento, correo, teléfono y afiliación a EPS) para **registrarte como paciente, agendar y gestionar tus citas y enviarte confirmaciones y códigos de verificación**.
> Los datos sobre tu afiliación en salud son **sensibles**: responder esas preguntas es **opcional**.
> Tienes derecho a conocer, actualizar, rectificar y suprimir tus datos, y a revocar esta autorización, escribiendo a **[PENDIENTE: canal oficial de habeas data]**. Política completa: **[PENDIENTE: URL de la política de tratamiento]**.
> ¿Autorizas el tratamiento de tus datos para estos fines?
> 1. Acepto
> 2. No acepto

- [INFERIDO] El artículo 6 de la Ley 1581 hace **facultativa** la respuesta sobre datos sensibles. Esto encaja con el 097 §2.3 (la EPS puede quedar "Pendiente"): en las preguntas de EPS y régimen, el bot agrega "puedes responder «prefiero no decir»", que se guarda como `Pendiente`.
- Por la longitud de un mensaje de chat, va un texto corto con enlace a la política completa. [INFERIDO] El Decreto 1377 admite una autorización por medios que permitan consultarla después. Por eso lo que se guarda es la versión y el hash exacto del texto mostrado (§1.4).
- Los tres `[PENDIENTE]` son datos del hospital. **No se completan con suposiciones** (misma regla que `INFORMACION_HOSPITAL.direccion`).

### 1.4 Versionado y prueba de la autorización
- **Dueño del texto: hrmm** (cambio 7). El chat lo obtiene de `GET …/autorizacion-datos/vigente` → `{version, texto, sha256}`, así el portal y el panel usan el mismo texto y hay una sola fuente de verdad.
- Al aceptar, ZANTIA envía `{documento, tipo_documento, version, sha256, canal, aceptado_en}`. hrmm lo guarda como una **autorización** con id propio, y el registro del paciente la referencia.
- La prueba se conserva **aunque el registro pendiente expire**: la autorización es evidencia del responsable del tratamiento. Su retención exacta es una decisión legal pendiente, que queda anotada para R-3.

## 2. Registro de capturas, para que R-3 pueda construirse después

Requisito: poder responder, por documento, **qué dato se capturó, cuándo, por qué medio y con qué autorización**, sin rediseñar el registro.

**[PROPUESTO] en hrmm (cambio 7):**

| Tabla | Una fila por… | Columnas mínimas |
|---|---|---|
| `agenda.autorizaciones_datos` | aceptación | `autorizacion_id`, `documento_paciente`, `tipo_documento`, `version_texto`, `sha256_texto`, `canal`, `aceptado_en` |
| `agenda.capturas_datos_paciente` | dato capturado o modificado | `documento_paciente`, `campo` (`correo`, `eps`…), `origen` (`chat` / `panel` / `admision`), `canal`, `autorizacion_id`, `capturado_en`, `actor` (`paciente` / `operador:<id>`) |

- **El valor del dato NO se duplica** en `capturas_datos_paciente`: vive solo en `agenda.pacientes`. Así, suprimir (R-3) es borrar un solo lugar, y el registro de capturas conserva la trazabilidad sin guardar datos personales repetidos.
- `agenda.pacientes` agrega `origen`, `estado` (`pendiente_verificacion` / `verificado_correo`), `autorizacion_id`, `documento_validado_presencialmente` y `creado_en`.
- **Lado de ZANTIA:** el EventLog registra `REGISTRO_INICIADO`, `AUTORIZACION_ACEPTADA` (con `version`, sin datos personales), `REGISTRO_CREADO` y `CORREO_VERIFICADO`, con **nombres de campos, nunca valores**. `identidad_canal` (identity_store) sigue siendo el único vínculo canal↔documento, con su retención de 180 días (`.ai/DATA_MODEL.md`).
- Con esto, la consulta de R-3 ("qué datos tienes de mí") sale de `pacientes` + `capturas_datos_paciente` + `autorizaciones_datos` por documento. La eliminación es un borrado en `pacientes` más la invalidación de `identidad_canal`, con su propio registro de auditoría. **Ese diseño completo queda pendiente (R-3).**

## 3. Cambios requeridos en hrmm-backend (para pasarle a la sesión de hrmm)

> Contexto para la sesión de hrmm: ZANTIA (chat) va a permitir que pacientes nuevos se registren solos. Todo lo de abajo es necesario para hacerlo de forma segura. Referencias de código de hrmm verificadas en modo solo lectura el 2026-09-30. Ningún endpoint existente cambia de forma incompatible: son endpoints nuevos o campos opcionales nuevos (`.claude/rules/contratos-api.md`). Cada cambio necesita una prueba de contrato.

**1. Endpoint de registro de SOLO CREACIÓN.** `POST /api/agenda/pacientes/registro` (con secreto de confianza).
- `INSERT … ON CONFLICT (documento_paciente) DO NOTHING`. Si el documento ya existe, o tiene un registro pendiente sin vencer, responde **409** sin modificar nada.
- Crea el registro con `estado = pendiente_verificacion`, `origen = chat` y el `autorizacion_id` obligatorio (cambio 7).
- **Motivo:** el `POST /api/agenda/pacientes` actual hace `ON CONFLICT … DO UPDATE SET correo = EXCLUDED.correo …` (`app/providers/agenda/mock.py:398-425`). Si el chat lo usara, cualquiera podría reemplazar el correo de un paciente existente y recibir sus códigos, es decir, tomar su identidad. El upsert actual debe quedar **solo** para el panel u operadores.

**2. `buscar-paciente` debe ver también `agenda.pacientes`.** `GET /api/agenda/citas/buscar-paciente` busca hoy solo en citas ("No hay citas registradas con ese documento", `app/api/agenda.py:91-106`).
- Si hay un paciente en `agenda.pacientes` con estado `verificado_correo` (o registrado por el panel o la admisión), debe responder **200** aunque no tenga citas.
- Un registro `pendiente_verificacion` no vencido **no** cuenta como existente para este endpoint (lo cubre el 409 del cambio 1).
- **Motivo:** si no, un paciente recién registrado "no existe" para el chat, que le ofrecería registrarse de nuevo.

**3. `verificacion/enviar` debe leer el correo también de `agenda.pacientes`.** Hoy lo saca solo de las citas (`app/api/agenda.py:247-248`).
- Debe usar el correo de `agenda.pacientes`, incluido el de un registro **pendiente**, que es cuando se envía el código para verificar ese correo.
- **Motivo:** si no, un paciente nuevo sin citas recibe "No tenemos un correo registrado…".
- Sin endpoint nuevo para enviar a correos arbitrarios: sería un relé de spam.

**4. Marcar el registro como verificado al validar el código.** Cuando `verificacion/validar` acierta el código de un documento con registro `pendiente_verificacion`, el registro pasa a `verificado_correo`. Puede hacerse ahí mismo o en un endpoint aparte (`POST …/pacientes/registro/{documento}/verificar`), según convenga a hrmm.

**5. Esquema del paciente y lista de EPS.**
- Agregar `tipo_documento` (CC, TI, CE, PPT, PA, RC).
- `plan`, `direccion` y `genero` pasan a **opcionales**. El chat no los pide, por minimización; se completan en la admisión.
- Agregar a `EPS_VALIDAS` el valor **`Pendiente`**, para "no sé / no tengo / prefiero no decir".
- Exponer la lista vigente en `GET /api/agenda/eps`, para que el chat no tenga una copia propia.
- **La lista actual (`app/schemas/agenda.py:8-11`) parece nacional genérica; la lista real del hospital está PENDIENTE** de que la entregue el usuario.
- Régimen (`tipo_afiliacion`) con valores cerrados: `Contributivo`, `Subsidiado`, `Especial o de excepción`, `No afiliado (particular)`, `Pendiente`.

**6. Expiración de los registros pendientes.** Un job que borre los `pendiente_verificacion` con más de **30 minutos**. Así se libera el documento y se evita que alguien lo acapare.
- **Se conserva** la fila de `autorizaciones_datos`, que es la prueba de la autorización (cambio 7).
- Se borra la fila de `pacientes` y se anota la expiración en `capturas_datos_paciente`, sin valores.

**7. (Nuevo, derivado de las decisiones del usuario sobre Ley 1581 y R-3) Autorizaciones y registro de capturas.**
- `GET /api/agenda/autorizacion-datos/vigente` → `{version, texto, sha256}`, con el texto versionado. Una versión nueva nunca borra las anteriores.
- `POST /api/agenda/autorizacion-datos` → guarda la aceptación `{documento, tipo_documento, version, sha256, canal, aceptado_en}` y devuelve `autorizacion_id`. Rechaza la aceptación si `sha256` no coincide con esa versión.
- Tablas `agenda.autorizaciones_datos` y `agenda.capturas_datos_paciente` (esquema en §2). Cada alta o modificación de un dato de paciente, por cualquier camino (chat, panel, admisión), escribe una fila en `capturas_datos_paciente`.
- **Motivo:** la Ley 1581 exige una autorización explícita y demostrable, y R-3 necesita consultar por documento qué se capturó y cuándo.

## 4. Lo que cambia respecto al recado 097

- §7 del 097: R-2 pasa de bloqueante a **RESUELTO** (Ley 1581). R-3 sigue **ABIERTO**, como bloqueante propio.
- §2.1 del 097: la lista de EPS sigue **pendiente del dato real**; el diseño ya no depende de ella gracias a `GET /api/agenda/eps`.
- §4 del 097: los 6 cambios de hrmm pasan a ser **7**, por las decisiones de Ley 1581 y R-3.
- El resto del 097 se mantiene: reconfirmación y elección explícita, verificación por código al correo de un registro pendiente, no tocar documentos existentes, límites de abuso en ZANTIA, riesgo de suplantación mitigado con validación presencial.

## Pendientes

1. **Lista real de EPS del hospital** (tu mensaje llegó cortado).
2. Nombre formal del responsable del tratamiento, canal oficial de habeas data y URL de la política: los tres `[PENDIENTE]` del texto de §1.3.
3. Revisión legal del texto borrador (§1.3).
4. Retención de las autorizaciones de registros expirados (§1.4), que conviene decidir con R-3.
5. Siguen abiertas las preguntas 1, 3, 6 y 7 del recado 097: la opción B de §1, aceptar el riesgo de suplantación, quién implementa en hrmm, y cómo se agrega el correo de un paciente existente.

---

## Anexo: decisiones del usuario (2026-09-30, después de aprobar este diseño)

**Diseño del recado 098 APROBADO completo.**

1. **Retención de las autorizaciones de registros expirados:** se conservan **indefinidamente, por ahora**. Son la prueba legal, y borrarlas antes de tiempo sería peor que guardar de más. Se revisa junto con R-3. Registrado en `.ai/DATA_MODEL.md` (política de retención) como DECIDIDO (provisional). Resuelve el pendiente 4 de este recado.
2. **Los tres `[PENDIENTE]` del texto de autorización** (responsable del tratamiento, canal de habeas data, URL de la política) **no los completa el equipo: son decisión del hospital**. Quedan como **bloqueantes de lanzamiento**, junto con **SAM-FR-04** (referencia de hrmm, que el usuario nombra; no se describe aquí) y la **lista real de EPS**. Registrado en `docs/CLIENT.local.md`.
3. **Revisión legal del texto borrador:** el mensaje del usuario llegó **cortado** en este punto ("correcto, no se…"). **Sin decisión registrada**; no se infirió el resto.

**Punto 3, completo (usuario, 2026-09-30):** el texto final no se implementa sin la revisión de alguien con criterio legal. Eso es un **bloqueante de producción real, no de pruebas**: se puede implementar y probar con datos de prueba usando el borrador tal cual, marcado claramente `[BORRADOR SIN REVISIÓN LEGAL]`. Registrado como **R-29** en `.ai/RISKS.md`. El usuario **autorizó la implementación del diseño completo**, empezando por el flujo del chat en paralelo a los cambios de hrmm, sin bloquearse por los `[PENDIENTE]` del hospital (se usan placeholders marcados).
