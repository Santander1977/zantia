# RECADO PARA CHATGPT

Fecha: 2026-09-30
Proyecto: ZANTIA (repo `icaco`), con impacto en hrmm-backend (`/Users/enzoalfonso/Orangutan/hrmm`)
Tema: Diseño del autorregistro de pacientes nuevos por el chat (requisito de lanzamiento)
Objetivo de la investigación: Proponer, con alternativas y recomendación, el diseño completo del autorregistro antes de escribir código.

Modo: SOLO DISEÑO. No se modificó código ni se hizo commit. El código de hrmm-backend se leyó en modo solo lectura. Todo lo marcado `[PROPUESTO]` está sin implementar.

---

## Resumen ejecutivo

- **[CONFIRMADO] hoy el chat no tiene ningún camino de registro.** Si el documento no existe, el gate de identidad responde `_MENSAJE_DOCUMENTO_NO_ENCONTRADO` ("No encontré ningún paciente registrado con ese documento — ¿puedes revisarlo…?", `domains/health/gateway.py:2220`). Si no tiene correo, responde el mensaje de R-28 con los canales externos.
- **[CONFIRMADO] hrmm-backend ya tiene casi todo el modelo de datos.** Tiene la tabla `agenda.pacientes` y `POST /api/agenda/pacientes` (con secreto de confianza), con los campos nombre, teléfono, correo, `eps` (**lista cerrada** `EPS_VALIDAS`, que incluye "Otra"), `tipo_afiliacion`, `plan`, `direccion`, `fecha_nacimiento` y `genero`. Los pacientes viven en hrmm con cualquiera de los dos proveedores de agenda: `RealAgendaProvider` hereda de `MockAgendaProvider` para pacientes, y a programador-citas solo viaja un HMAC del documento (`hrmm/backend/app/providers/agenda/real.py`, encabezado).
- **Hay cuatro huecos en hrmm que bloquean un registro seguro** (detalle en §0):
  1. **El endpoint existente es un *upsert* que SOBRESCRIBE el correo de un paciente existente.** Si el chat lo usara, cualquiera podría cambiar el correo de otra persona y después recibir sus códigos: una toma de identidad.
  2. `buscar-paciente` busca solo en **citas**, así que un paciente registrado sin citas "no existe" para el chat.
  3. El envío del código lee el correo solo de las **citas**, así que un paciente recién registrado recibiría "no tenemos un correo registrado".
  4. El límite de tasa de hrmm es **por IP y en memoria**. Todo el tráfico de ZANTIA sale de una sola IP, así que no sirve para limitar a cada usuario del chat.
- **Bloqueante legal ya abierto: R-2** (el marco legal de protección de datos está sin confirmar) y **R-3** (no existe el mecanismo de consulta/eliminación). Registrar a desconocidos por chat es recolección nueva de datos personales, parte de ellos relacionados con salud. Ver §7.
- **Recomendación en una línea:**
  1. Ofrecer el registro solo después de reconfirmar el documento y con aceptación explícita.
  2. Pedir datos mínimos: tipo y número de documento, nombre, fecha de nacimiento, correo, teléfono, EPS de una lista cerrada con "no sé / no tengo", y régimen.
  3. Verificar con un código al correo que la persona escribe.
  4. Guardar el paciente en hrmm, mediante un endpoint nuevo de **solo creación**, nunca el upsert actual.
  5. Nunca tocar un documento que ya existe.
  6. Aplicar límites por identidad de canal en ZANTIA, más un tope global y la expiración de los registros sin verificar.

---

## 0. Estado real encontrado (evidencia)

| # | Hecho | Evidencia | Consecuencia para el diseño |
|---|---|---|---|
| E1 | `POST /api/agenda/pacientes` hace `INSERT … ON CONFLICT (documento_paciente) DO UPDATE SET … correo = EXCLUDED.correo …` | `hrmm/backend/app/providers/agenda/mock.py:398-425`, `app/api/agenda.py:403-411` | **No se puede usar para el autorregistro.** Hace falta un endpoint de solo creación (409 si ya existe). |
| E2 | `EPS_VALIDAS = ("Nueva EPS", "Sura", "Sanitas", "Compensar", "Salud Total", "Coosalud", "Famisanar", "Aliansalud", "Mutual Ser", "Comfenalco Valle", "Otra")`, validada en el upsert | `app/schemas/agenda.py:8-11, 107-112` | Ya existe una lista cerrada. **[INFERIDO]** Parece una lista nacional genérica, no "las EPS que atiende el hospital" (incluye Comfenalco Valle; el hospital está en Barrancabermeja). Hay que confirmarla con el hospital. No existe un valor para "no sé / no tengo". |
| E3 | `plan`, `direccion`, `tipo_afiliacion` son `str` **obligatorios**; `fecha_nacimiento` y `genero` son opcionales; **no existe `tipo_documento`** | `app/schemas/agenda.py:95-105` | Por minimización de datos, el chat no debería pedir `plan` ni `direccion`: hrmm debe aceptarlos vacíos u opcionales. Falta el tipo de documento (CC/TI/CE/PPT/RC…), que se necesita para menores y extranjeros. |
| E4 | `buscar-paciente` responde "No hay citas registradas con ese documento" y busca en citas | `app/api/agenda.py:91-106` | Un paciente registrado sin citas se ve como inexistente, y el chat le ofrecería registrarse **otra vez**. Hay que consultar también `agenda.pacientes`. |
| E5 | `verificacion/enviar` toma el correo con `next(c.correo for c in citas…)` | `app/api/agenda.py:247-248` | Un paciente recién registrado no tiene citas, así que no recibiría ningún código. Hay que leer también `agenda.pacientes.correo`. |
| E6 | `limitar(max, ventana)` es "por IP en una ventana deslizante … en memoria del proceso" | `app/rate_limit.py:21-26` | Para el chat, toda la población comparte un solo cupo (la IP de ZANTIA). Los límites por persona tienen que vivir en ZANTIA. |
| E7 | En el camino entrante, ZANTIA fija `consentimiento_datos=True` de forma implícita ("implícito en el acto de pedirla") | `domains/health/gateway.py:~695-702` | Sirve para gestionar una cita propia. **No sirve** para crear un registro nuevo con datos personales: ahí hace falta una autorización explícita y registrada (§7). |
| E8 | El flujo de beneficiario (recado 013) exige que el documento del beneficiario **ya exista** | `domains/health/brain.py:_interpretar_documento_beneficiario` | Registrar a un menor o a un tercero es un caso aparte (§2.6). |

---

## 1. Cuándo se ofrece el registro

| Alternativa | Ventajas | Desventajas |
|---|---|---|
| A. Ofrecerlo de inmediato al primer "documento no encontrado" | Menos fricción | Un documento mal escrito (el caso más común) termina en un registro duplicado con un número equivocado |
| B. **Reconfirmar el documento y ofrecerlo con una elección explícita** | Separa "me equivoqué al escribirlo" de "soy nuevo"; deja constancia de que el paciente quiso registrarse | Un turno más |
| C. Registro solo si el paciente lo pide ("quiero registrarme") | Cero registros no deseados | Nadie lo va a descubrir solo |

**Recomendación: B.** Con el documento no encontrado, el bot responde algo como: "No encontré a nadie registrado con el documento **1.234.567**. ¿Qué quieres hacer? 1. Corregir el número 2. Registrarme como paciente nuevo 3. Hablar con el hospital (canales reales)". Solo la opción 2 inicia el registro, y la primera pregunta del registro es la **autorización de tratamiento de datos** (§7). Lo mismo aplica al paciente que existe pero **no tiene correo**: se le ofrece **completar su correo** con una verificación propia (§5.2), no un registro nuevo.

## 2. Datos mínimos

| Dato | ¿Obligatorio? | Fuente / validación | Motivo |
|---|---|---|---|
| Tipo de documento (CC, TI, CE, PPT, PA, RC) | Sí | Lista cerrada numerada | Distingue números iguales entre tipos, y los menores o extranjeros. **Falta en hrmm (E3).** |
| Número de documento | Sí | Ya lo escribió; se reconfirma (§1) | Identificador del paciente |
| Nombre completo | Sí | Texto libre, sin números | Atención y confirmaciones |
| Fecha de nacimiento | Sí | `DD/MM/AAAA`, rango razonable | Ayuda a detectar duplicados y errores de tipeo, y a identificar a menores (§2.6); la pide cualquier admisión |
| Correo | Sí | Formato válido, y **verificado con código** (§3) | Es el canal de los códigos de verificación de todo el sistema |
| Teléfono | Sí | 10 dígitos que empiezan por 3 (celular), o se toma del canal si es WhatsApp o Telegram y el paciente lo confirma | Contacto y recordatorios |
| EPS | Sí se pregunta; puede quedar **pendiente** | Lista cerrada (§2.1) | Cobertura y facturación |
| Régimen (`tipo_afiliacion`) | Igual que EPS | Contributivo / Subsidiado / Especial o excepción / No afiliado (particular) / No sé | Define cobertura y cobro |
| Dirección, plan, género | **No se piden por chat** | Se completan en la admisión presencial | Minimización (regla de habeas data). Requiere que hrmm los acepte vacíos (E3). |

### 2.1 EPS: lista cerrada o texto libre

| Alternativa | Ventajas | Desventajas |
|---|---|---|
| Texto libre | Nada se queda por fuera | "nueva eps", "NUEVAEPS", "la nueva"… Datos sucios, inservibles para facturar; exige normalización posterior |
| **Lista cerrada numerada + "Otra" + "No sé / no tengo"** | Datos limpios; hrmm ya valida una lista (E2); el paciente elige con un número, igual que en el resto del bot | Hay que mantener la lista |
| Lista cerrada + un LLM que interprete el texto libre (`core/selection.py`, verificado contra la lista) | Acepta "estoy en la nueva" | Más complejo; es una mejora posterior, no algo del día 1 |

**Recomendación: lista cerrada numerada**, con las EPS que **el hospital confirme que atiende** (la lista actual de hrmm no es ese dato; ver E2). La lista debe ser configuración de hrmm, no texto dentro del código del chat, para que el chat la consuma de un endpoint y nunca haya dos listas distintas (`.claude/rules/fuente-de-verdad.md`). En una iteración posterior se puede sumar la interpretación con `interpret_selection`.

### 2.2 Si no sabe o no tiene EPS
- Opción "No sé / no tengo" → `eps = "Pendiente"` y `tipo_afiliacion = "No sé"` o "No afiliado". **Requiere agregar un valor a `EPS_VALIDAS` en hrmm** (hoy el validador lo rechaza).
- Población sin afiliación: el régimen "No afiliado (particular)" es un dato válido y distinto de "no sé".
- Subsidiado o contributivo se pregunta **aparte** de la EPS, porque varias EPS operan en los dos regímenes.

### 2.3 ¿Obligatorio para completar el registro?
**Recomendación: la EPS se pregunta siempre, pero puede quedar "Pendiente" sin bloquear el registro ni la reserva.** Un paciente sin EPS resuelta igual necesita poder pedir su cita. El registro queda marcado `eps_pendiente` y se completa en la admisión (Digiturno o ventanilla), antes de la atención. **Decisión del hospital, no de software:** si algún servicio exige EPS antes de reservar (por ejemplo por autorizaciones), el chat debe bloquear **ese servicio**, no el registro completo.

### 2.4 Duplicados
- La fecha de nacimiento, junto con el tipo y número de documento, permite detectar en la admisión si "1234567" era en realidad "12345678".
- A futuro se podría validar la afiliación contra BDUA/ADRES, pero es una integración externa nueva, fuera de este diseño.

### 2.5 Orden de las preguntas
Autorización → tipo de documento → nombre → fecha de nacimiento → correo → código de verificación → teléfono → EPS → régimen → resumen con "¿Confirmas?" → creación.

La verificación del correo va **antes** de pedir el resto: si alguien no puede recibir el código, no se le piden más datos que después habría que borrar.

### 2.6 Menores y terceros
Una TI o un RC, o una fecha de nacimiento de menos de 18 años, **no se autorregistra**: el registro lo hace el acudiente, como beneficiario. Esto es una extensión del flujo del recado 013, que hoy exige que el beneficiario ya exista (E8). **Recomendación: fuera del alcance de la primera versión.** Ante un menor, el chat responde con los canales reales del hospital.

## 3. Verificación

| Alternativa | Qué demuestra | Riesgo |
|---|---|---|
| A. Sin verificación | Nada | Correos falsos o ajenos; los códigos futuros irían a otra persona |
| B. **Código al correo que la persona escribe**, reutilizando `recovery_codes` y el webhook de n8n que ya existen | Que la persona controla ese correo, y que los códigos futuros le van a llegar | **No demuestra que el documento sea suyo** (§6) |
| C. Endpoint nuevo "enviar código a un correo arbitrario" | Lo mismo que B | Convierte a hrmm en un **relé de correos hacia cualquier dirección** (spam o acoso). Descartada. |
| D. Validación presencial obligatoria antes de poder reservar | Documento y persona verificados | Rompe el objetivo de autoservicio |

**Recomendación: B, sin endpoint de envío abierto.** El registro se crea primero en estado `pendiente_verificacion`, con el correo escrito. Después se usa el **mismo** `verificacion/enviar` (una vez que lea también `agenda.pacientes.correo`, E5), así el código solo puede ir al correo de un registro pendiente, que expira pronto. Al validar el código, el registro pasa a `verificado_correo` y ZANTIA guarda `identidad_canal` como VERIFICADO, igual que hoy.

Complemento: el registro queda marcado `origen = chat` y `documento_validado_presencialmente = false` hasta la primera admisión, donde se muestra el documento.

## 4. Dónde vive el paciente nuevo

| Alternativa | Evaluación |
|---|---|
| **hrmm (`agenda.pacientes`)** | Es el dueño actual de pacientes con los dos proveedores (`real.py`: "Paciente: se queda en hrmm"; programador-citas solo recibe un HMAC). **Recomendada.** |
| Pasar también por programador-citas | Contradice la división que ya existe: programador-citas es dueño de la oferta y la ocupación, no de personas, y hoy recibe a propósito solo una referencia opaca. Duplicaría la fuente de verdad de pacientes. **Descartada.** |
| Guardarlo en ZANTIA | ZANTIA no es sistema de registro clínico ni administrativo; el panel, el portal y el Digiturno no lo verían. **Descartada.** |

**Cambios en hrmm (otro repo, los coordina esa sesión):**
1. `POST /api/agenda/pacientes/registro` de **solo creación**: `INSERT … ON CONFLICT DO NOTHING`, 409 si ya existe, `estado = pendiente_verificacion`, `origen = chat`, con fecha, canal y versión del texto de autorización. El upsert actual queda solo para el panel u operadores.
2. `buscar-paciente` también consulta `agenda.pacientes` (E4).
3. `verificacion/enviar` toma el correo también de `agenda.pacientes` (E5).
4. Un endpoint para marcar el registro como verificado después de validar el código, o hacer que `verificacion/validar` lo haga.
5. `tipo_documento`; `plan`, `direccion` y `genero` opcionales; un valor "Pendiente" en EPS; la lista de EPS como configuración consultable.
6. Job de expiración de los registros `pendiente_verificacion` con más de 30 minutos, que libera el documento.

ZANTIA solo cambia en `domains/health/gateway.py` (un wizard nuevo, con el mismo patrón que `_pending_identity`) y en `HrmmAppointmentService` (métodos nuevos, con duck-typing como `buscar_paciente`). No toca el Core.

## 5. Documento que ya existe

5.1 **Nunca se crea ni se modifica nada** si el documento existe: ni el nombre ni el correo. El chat lo trata como paciente existente: le envía el código al correo **registrado** o, si no tiene, sigue el camino de R-28.

5.2 Paciente existente **sin correo**: ofrecerle "agregar su correo" por chat **no es seguro**, porque sería el mismo ataque de E1 (cualquiera que sepa un documento le asigna su propio correo). **Recomendación:** en la primera versión, el correo de un paciente existente solo se agrega en la admisión presencial o por el panel. El chat mantiene el mensaje de R-28.

5.3 Carrera entre dos registros del mismo documento: la resuelve la base (`ON CONFLICT DO NOTHING`); el segundo recibe 409 y cae en §5.1.

## 6. Abuso

| Amenaza | Mitigación propuesta |
|---|---|
| Registros falsos en masa (saturar la base) | (a) El registro solo queda activo si **se verifica un correo real**; los pendientes expiran a los 30 minutos. (b) En **ZANTIA**, por identidad de canal: 1 registro completado cada 24 horas y 3 intentos de código. (c) **Tope global** en ZANTIA, por ejemplo 30 registros por hora, con una alerta en el EventLog al superarlo. |
| Correos de código usados como spam | El código solo va al correo de un registro pendiente propio (§3B), con el límite existente de hrmm (3 envíos cada 300 s) más el límite por canal de ZANTIA |
| **Suplantación**: registrar el documento de otra persona que aún no existe (acaparar su documento) | No se puede prevenir por chat (no hay forma de probar la posesión del documento). Mitigación: marca `documento_validado_presencialmente=false`, validación en la primera admisión, y un camino para que el personal reasigne o corrija desde el panel. Riesgo aceptado y documentado, no oculto. |
| El chat web es el canal más débil: su identidad es una sesión anónima, a diferencia del teléfono en Telegram o WhatsApp | Límites más estrictos por canal (por ejemplo, en el chat web, 1 registro por sesión y un tope global propio) y, de ser necesario, un captcha en el frontend `eis-chat-hrmm` (otro repo) |
| Límite por IP de hrmm (E6) mal usado | Documentar que para el tráfico de ZANTIA **no** protege a cada persona; a futuro, que ZANTIA envíe una referencia de canal en un header para limitar por persona |

## 7. Protección de datos (obligatorio antes de implementar)

- **R-2 (ABIERTO):** falta confirmar y documentar el marco legal. El pedido menciona Colombia, pero `.claude/rules/proteccion-datos-personales.md` exige confirmarlo explícitamente, nunca asumirlo. Si es la Ley 1581 de 2012: hace falta **autorización previa, expresa e informada**, que ya no puede ser "implícita" como en E7; los datos de salud son **sensibles**. **[DESCONOCIDO]** si la afiliación a una EPS cuenta como dato sensible; es una pregunta legal.
- Qué hace falta:
  - un texto de autorización versionado, mostrado en el chat, aceptado de forma explícita y guardado con fecha, canal y versión;
  - el propósito de cada dato, documentado en `.ai/DATA_MODEL.md`;
  - una retención definida (por ejemplo, pendientes a 30 minutos, y el registro activo según la política del hospital);
  - un registro de auditoría de la creación.
- **R-3 (ABIERTO):** el paciente debe poder consultar y pedir la eliminación desde el propio chat. El autorregistro **agranda** ese hueco; conviene resolverlo antes o junto con esto.

## 8. Decisiones propuestas (formato del proyecto)

| Decisión | Motivo | Alternativas | Ventajas | Desventajas | Riesgo | Impacto | Estado |
|---|---|---|---|---|---|---|---|
| D-10: registro solo tras reconfirmar el documento y una elección explícita | Evitar registros por errores de tipeo | A, C (§1) | Datos limpios y consentimiento claro | Un turno más | Bajo | `gateway.py` | PROPUESTA |
| D-11: datos mínimos + EPS de lista cerrada, que puede quedar pendiente | Facturable sin bloquear el acceso | Texto libre, EPS obligatoria | Datos limpios y acceso | Mantener la lista | Medio (la lista debe ser la real del hospital) | hrmm (schema), `gateway.py` | PROPUESTA |
| D-12: código al correo de un registro pendiente, sin relé de correo abierto | Probar el correo sin crear un vector de spam | A, C, D (§3) | Reutiliza lo existente | No prueba la posesión del documento | Medio (suplantación, §6) | hrmm (enviar, validar), `gateway.py` | PROPUESTA |
| D-13: paciente en hrmm, endpoint de solo creación | hrmm ya es el dueño; el upsert permite tomar identidades | Upsert, programador-citas, ZANTIA | Fuente única y segura | Cambio en otro repo | Bajo | hrmm | PROPUESTA |
| D-14: límites de abuso en ZANTIA por identidad de canal, con tope global y expiración | El límite de hrmm es por IP (E6) | Límite por IP, captcha | Protege de verdad a cada persona | Estado en memoria (como R-11) | Medio | `gateway.py`, observabilidad | PROPUESTA |

## 9. Orden de implementación sugerido

1. Confirmar R-2 y el texto de autorización (usuario o área legal).
2. Confirmar la lista real de EPS del hospital y si algún servicio exige EPS para reservar.
3. Cambios en hrmm: los 6 puntos de §4, con pruebas de contrato (`.claude/rules/testing.md`).
4. En ZANTIA: el wizard de registro, los límites y los tests, más `.ai/API_CONTRACTS.md` y `.ai/INTEGRATIONS.md`.
5. Prueba en producción con documentos de prueba, y despliegue coordinado (primero hrmm, después ZANTIA).

## Preguntas pendientes (decisiones del usuario o del hospital)

1. ¿Se aprueba la opción B de §1 (reconfirmar y elegir)?
2. ¿Cuáles son las EPS reales que atiende el hospital? ¿Alguna atención exige EPS antes de reservar?
3. ¿Se acepta el riesgo de suplantación documentado en §6, con validación en la primera admisión?
4. ¿Los menores quedan fuera de la primera versión (§2.6)?
5. ¿Quién confirma R-2 y redacta el texto de autorización?
6. ¿Quién implementa los cambios de hrmm (sesión de hrmm)?
7. ¿El correo de un paciente existente sin correo (§5.2) solo se agrega presencialmente o por el panel en la primera versión?
