# RECADO PARA CHATGPT

Fecha: 2026-08-31
Proyecto: icaco (agente conversacional de Orangutan, dominio inicial: salud)
Tema: Diseño de la arquitectura conceptual del "Cerebro Conversacional ICACO v1", usando la autopsia de "Dani" (`002-autopsia-cerebro-dani.md`) como fuente de patrones arquitectónicos, no como plantilla a clonar.
Objetivo: Producir una arquitectura conceptual sólida y modular para ICACO — sin escribir código, sin modificar archivos de icaco/Dani/PROJECT-TEMPLATE — que sirva de base para una fase posterior de validación antes de implementar.

Este documento es autocontenido: no requiere haber leído los recados anteriores (`001-auditoria-dani.md`, `002-autopsia-cerebro-dani.md`) para entenderse, aunque los complementa y no los contradice. Toda referencia a Dani está sustentada en `002-autopsia-cerebro-dani.md`, ruta `/Users/enzoalfonso/recado/002-autopsia-cerebro-dani.md`.

**Nota de alcance importante**: el estado actual de icaco (verificado en esta sesión leyendo `/Users/enzoalfonso/Orangutan/icaco/.ai/ARCHITECTURE.md`, `/Users/enzoalfonso/Orangutan/icaco/.ai/CURRENT_STATE.md` y `/Users/enzoalfonso/Orangutan/icaco/PROJECT.md`) es: proyecto recién creado desde `PROJECT-TEMPLATE`, sin stack elegido, sin canal de mensajería decidido, sin una sola línea de código, y con `PROJECT.md` todavía con campos "para quién"/"objetivo" sin completar. El dato "orientado inicialmente a salud" fue dado directamente por el usuario en esta sesión y **todavía no está reflejado en `PROJECT.md`** — se recomienda actualizarlo ahí cuando corresponda (fuera del alcance de este documento, que es solo lectura/diseño).

---

# CEREBRO CONVERSACIONAL ICACO v1

## 1. Objetivo

Diseñar la arquitectura conceptual de un agente conversacional (ICACO) orientado inicialmente al dominio de salud, pero con un núcleo (orquestación, estado, guardrails, observabilidad) suficientemente desacoplado del dominio para poder extenderse después a otros dominios sin rediseñar desde cero.

**Regla fundamental de esta fase**: DANI = fuente de patrones y aprendizaje arquitectónico. ICACO = arquitectura nueva, diseñada conscientemente, que conserva lo que funcionó en Dani y corrige lo que la autopsia identificó como debilidad.

### Identidad del agente

- **Qué es ICACO**: un agente conversacional que interactúa con un ciudadano/usuario final por un canal de mensajería (canal exacto PENDIENTE, ver sección 19), interpreta su intención dentro del dominio de salud, recopila la información necesaria para resolverla, entrega información o ejecuta una acción dentro de límites definidos, y escala a un humano cuando corresponde.
- **Responsabilidades que SÍ tiene**: interpretar mensajes, mantener continuidad de una conversación (incluso si se retoma días después), recopilar y validar datos necesarios para un objetivo, consultar fuentes de conocimiento (estático/dinámico/RAG/externo), ejecutar acciones de bajo riesgo dentro de permisos explícitos, detectar señales que requieren intervención humana, y dejar un rastro auditable de lo que hizo.
- **Responsabilidades que NO tiene**: tomar decisiones clínicas o diagnósticas (eso corresponde a un profesional de salud humano); ejecutar acciones irreversibles sin confirmación explícita; sustituir atención médica real; resolver soporte técnico o administrativo fuera de su dominio; decidir por sí solo, sin regla determinista de por medio, si una situación es urgente.

Esta última responsabilidad NO tenida es la diferencia más importante frente a Dani: **Dani nunca tuvo que distinguir una urgencia real de una objeción de venta — ICACO sí, y esa distinción no puede depender únicamente de que el LLM "lo interprete bien"** (ver secciones 6, 11 y 12).

---

## 2. ADN heredado de Dani

Análisis directo sobre `002-autopsia-cerebro-dani.md`, respondiendo a las 7 preguntas solicitadas:

**1. Elementos a conservar** (ya HECHO que funcionan bien conceptualmente en Dani):
- Regla de interrupción global desde cualquier estado (en Dani: señal de compra; en ICACO se transforma, ver punto 3 abajo).
- Separación de fuente de verdad dinámica vs. estática, con jerarquía explícita.
- Escalación sin prometer lo que no se puede garantizar.
- Post-procesamiento desacoplado de la generación (formatear para el canal es responsabilidad distinta de decidir qué decir).
- Traducción de una técnica de comunicación reconocida en instrucción operativa con ejemplos concretos (el mecanismo, no el contenido de venta).
- Memoria de conversación indexada por identificador de sesión en una base de datos relacional.
- Regla de "no te quedes en bucle": forzar una acción concreta tras N intercambios sin avance.

**2. Elementos a mejorar** (existen en Dani pero de forma frágil):
- Estado conversacional: pasar de inferido-cada-turno a explícito y persistido.
- Reglas de negocio: pasar de texto libre dentro del prompt a datos/configuración estructurada y versionada.
- Memoria: agregar una capa de perfil/resumen de largo plazo, no depender solo de una ventana fija.
- Escalación: agregar motivo estructurado y distinción entre urgente/estándar (en Dani toda escalación era del mismo tipo).

**3. Elementos que NO deben trasladarse**:
- Todo el contenido de negocio específico de Dani (precios, marca, casos de éxito, chistes, emojis).
- La dependencia de n8n como orquestador, si ICACO no adopta ese mismo stack (decisión pendiente, ver sección 19).
- Identificadores operativos reales encontrados en el archivo de Dani (correos, IDs de chat, URLs de documentos privados).
- La práctica de "todo se controla por instrucción de texto, nada se verifica por código" — es la debilidad más transversal de todo el diseño de Dani.

**4. Capacidades que en Dani dependen únicamente del prompt** (de las 14 secciones A–N analizadas en la autopsia, 13 son puramente de instrucción, sin ningún mecanismo de código detrás — solo la sección B de formato tiene un mecanismo parcial de código vía los nodos `Evaluación`/`Frankestein`): identidad y manejo de "¿eres bot?", las 5 fases de conversación y sus transiciones, el modo post-venta, el protocolo de escalación (qué decir, cuándo), la jerarquía de qué tool usar, los contadores de repetición, el tono/lenguaje, la psicología de venta aplicada, los límites del agente, la filosofía del producto, el sistema de upgrades, la filosofía de planes, y las reglas finales. Es decir: **toda la lógica de negocio y casi toda la lógica de conversación de Dani vive exclusivamente en texto de prompt, sin ningún guardrail de código que verifique su cumplimiento.**

**5. Capacidades que deben convertirse en componentes reales de arquitectura en ICACO**:
- La fase/estado de la conversación → campo persistido, no inferido (sección 6).
- Los contadores de repetición → contador real en base de datos, no "mental".
- El modo (venta/postventa en Dani; en ICACO algo como atención/seguimiento/escalado) → campo persistido en el estado.
- La verificación de que la respuesta generada cumple las reglas críticas → guardrail de código antes de enviar (sección 11).
- La decisión de escalar → regla determinista con motivo estructurado, no solo una lista de palabras clave interpretada por el LLM.

**6. Conceptos implícitos en Dani que deben hacerse explícitos en ICACO**: la fase conversacional; el modo activo; los contadores; el nivel de confianza de la interpretación del agente (Dani no modela esto en absoluto — actúa como si siempre estuviera seguro); la necesidad de escalar (en Dani es una reacción puntual a palabras clave, no un estado con motivo persistido).

**7. Información que falta para poder implementar correctamente ICACO** (no se inventa aquí — se documenta como pendiente, ver también sección 19):
- Qué caso de uso exacto dentro de salud se ataca primero (triage informativo, agendamiento, seguimiento de tratamiento, resolución de dudas generales, u otro) — el encargo solo dice "orientado inicialmente a salud".
- Stack de orquestación, modelo LLM, base de datos y canal de mensajería — ninguno decidido todavía en icaco (confirmado leyendo `.ai/ARCHITECTURE.md` y `.ai/CURRENT_STATE.md`).
- Marco legal/jurisdicción exacta de protección de datos aplicable — ya señalado como pendiente en icaco (`.claude/rules/proteccion-datos-personales.md`), y en salud existe además la pregunta de si aplica una categoría de dato sensible adicional (no se asume ninguna respuesta aquí).
- Protocolo clínico para reconocer y manejar una señal de urgencia — esto requiere criterio médico/legal humano, no es una decisión que deba tomar esta arquitectura.
- A quién exactamente se escala y con qué disponibilidad real (equipo humano, call center, otro).

---

## 3. Principios de diseño

Marco general que gobierna todas las decisiones de este documento (el listado extenso y definitivo de principios está en la sección 18; aquí solo el encuadre):

- **Dani es un maestro, no un molde.** Se estudia su comportamiento para extraer principios, nunca se copia su implementación.
- **Lo que en Dani era "confiar en que el LLM se acuerde" se convierte en ICACO en "el sistema recuerda por diseño".**
- **Lo que en Dani era "confiar en que el LLM obedezca" se convierte en ICACO en "el sistema verifica que se obedeció".**
- **El dominio de salud exige un nivel de cautela que el dominio de ventas de Dani nunca necesitó** — cualquier ambigüedad sobre riesgo/urgencia se resuelve hacia la opción más segura (escalar), no hacia la más fluida conversacionalmente.
- **Ninguna arquitectura se da por definitiva.** Este es un v1 conceptual, explícitamente sujeto a revisión (sección 20).

---

## 4. Arquitectura conceptual

Diagrama de componentes de alto nivel. Parte del esquema discutido en conversación (`CIUDADANO → CANAL → ORQUESTADOR → ESTADO → CEREBRO → GUARDRAILS → RESPUESTA → OBSERVABILIDAD`) y lo completa con lo que la autopsia de Dani identificó como ausente:

```
                         CIUDADANO
                             │
                             ▼
                          CANAL                 (WhatsApp/Telegram/web/otro — PENDIENTE, sec.19)
                             │
                             ▼
                       ORQUESTADOR              (único punto de entrada; NO es el LLM)
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
          IDENTIDAD/      ESTADO         MEMORIA
          CONTEXTO      (explícito,    (conversación,
        (usuario, canal, persistido,    perfil, resumen
         consentimiento)  sec. 6)        largo plazo, sec.8)
              │              │              │
              └──────────────┼──────────────┘
                             ▼
                          CEREBRO                (razonamiento — LLM, sec. 7)
                             │
              ┌──────────────┼───────────────┬─────────────┐
              ▼              ▼                ▼             ▼
         CONOCIMIENTO      TOOLS           REGLAS DE      REGLAS
        (estático/         (sec. 10)       NEGOCIO       DETERMINISTAS
       dinámico/RAG/                     (configuración   (riesgo/urgencia,
        externo, sec.9)                   estructurada)    permisos, sec.11)
              │              │                │             │
              └──────────────┴────────────────┴─────────────┘
                             ▼
                        GUARDRAILS               (verifica ANTES de responder — sec. 11;
                             │                     esto NO EXISTÍA en Dani)
                             ▼
                         RESPUESTA               (formateada para el canal)
                             │
                             ▼
                           CANAL ──────────────► CIUDADANO
                             │
                             ▼
                      OBSERVABILIDAD             (registra todo lo anterior — sec. 14;
                                                   esto NO EXISTÍA en Dani)
                             │
                             ▼
                   ESCALAMIENTO HUMANO            (puede dispararse desde CUALQUIER
                                                    punto del flujo — interrupción
                                                    global, ver sec. 12 y 13)
```

**Diferencia estructural clave frente a Dani**: en Dani, el nodo `Daniv2` (el LLM) *era* casi toda la arquitectura — memoria, reglas y tools convergían directo en el LLM, y de ahí salía casi sin filtro la respuesta. En ICACO, el LLM (CEREBRO) es un componente más, rodeado de un ORQUESTADOR que decide qué le entrega y qué hace con lo que devuelve, y de una capa de GUARDRAILS que nunca existió en Dani.

---

## 5. Orquestador

- **Cómo recibe una interacción**: es el único punto de entrada — recibe el mensaje ya normalizado desde el CANAL (equivalente mejorado al nodo `Concatenar + Session ID` de Dani, pero con el nodo de entrada real, que en Dani estaba ausente/referenciado como `Organizador`).
- **Cómo decide qué hacer**: carga el ESTADO existente de esa conversación (o crea uno nuevo), carga la MEMORIA relevante, y entrega ambos al CEREBRO junto con el mensaje. No decide el contenido de la respuesta — eso es responsabilidad del cerebro. Sí decide, de forma determinista, si hay una condición que debe interrumpir el flujo normal (ej. señal de riesgo ya detectada previamente, o límite de permisos) antes incluso de invocar al cerebro.
- **Cómo coordina cerebro, memoria, conocimiento y herramientas**: el cerebro no accede directo a memoria/conocimiento/tools — las solicita a través del orquestador, que aplica reglas de negocio y permisos antes de ejecutar cualquier llamada (a diferencia de Dani, donde el LLM invocaba las tools directamente sin ninguna capa intermedia de control).
- **Qué hace con la salida del cerebro**: la pasa por GUARDRAILS antes de formatearla para el canal y enviarla; actualiza el ESTADO con lo que el cerebro propuso (sujeto a validación); registra el evento en OBSERVABILIDAD.

---

## 6. Estado conversacional

Este es el punto de mayor divergencia respecto a Dani, y el corregido central de esta arquitectura: **en Dani no existe ningún estado persistido — todo se re-infiere del historial de memoria cada turno** (hallazgo confirmado en `002-autopsia-cerebro-dani.md`, sección "Máquina de estados conversacional"). Para ICACO, el estado es una entidad explícita.

Modelo conceptual de campos (sin implementar, sin definir tipo de almacenamiento — eso es decisión de stack, sección 19):

| Campo | Qué representa | Quién lo determina | Por qué debe ser explícito (lección de Dani) |
|---|---|---|---|
| `fase_actual` | Punto de la conversación (ver máquina de estados, sec. 12) | Cerebro propone, orquestador persiste | En Dani se perdía en conversaciones largas; debe sobrevivir a cualquier longitud |
| `intención` | Qué quiere el usuario en este turno | Cerebro (interpretación) | En Dani se recalculaba desde cero cada vez, sin persistirse |
| `objetivo_de_conversación` | La meta de la interacción completa (ej. "resolver duda", "agendar", "dar seguimiento") | Se fija al inicio, puede revisarse | Dani no distinguía "objetivo" de "fase" — eran lo mismo, mezclado en el prompt |
| `modo` | Régimen de comportamiento activo (equivalente sano al "venta/postventa" de Dani) | Orquestador, según reglas deterministas | En Dani el modo era inferido y podía "olvidarse" si el evento que lo activó salía de la ventana de memoria |
| `contexto` | Resumen curado de la conversación relevante al objetivo (no el historial crudo completo) | Cerebro genera, orquestador almacena | Evita depender de una ventana fija como única fuente de continuidad |
| `datos_recopilados` | Información ya obtenida del usuario, relevante al objetivo | Cerebro extrae, orquestador valida | Dani no tenía este concepto — vendía sin necesitar datos estructurados del usuario |
| `datos_faltantes` | Qué información aún se necesita para avanzar | Se deriva de comparar objetivo vs. recopilados | Guía la siguiente pregunta sin releer todo el historial |
| `herramientas_utilizadas` | Qué tools ya se invocaron y con qué resultado resumido | Orquestador registra tras cada llamada | Evita invocaciones redundantes de forma garantizada (en Dani esto era solo una instrucción de prompt, "no consultes varias tools para lo mismo") |
| `resultado_de_herramientas` | Última respuesta relevante de cada tool | Orquestador | Insumo para el cerebro sin re-invocar |
| `próxima_acción` | Qué se planea hacer en el siguiente turno | Cerebro propone, guardrails validan | Hace explícita una planificación que en Dani era implícita dentro del propio prompt |
| `nivel_de_confianza` | Qué tan seguro está el sistema de su interpretación | Cerebro estima | Dani no modela esto en absoluto — actúa siempre como si estuviera seguro; en salud, la incertidumbre debe poder frenar una acción |
| `necesidad_de_escalar` | Bandera + motivo estructurado | Reglas deterministas + cerebro | En Dani era solo una lista de palabras clave interpretada en el momento, sin persistirse como señal |
| `nivel_de_riesgo` / `señal_de_urgencia` | Si el mensaje sugiere una situación que requiere atención inmediata (concepto **ausente por completo en Dani**) | Reglas deterministas (no solo el LLM) + cerebro como señal de entrada | Diferencia crítica de dominio: Dani nunca necesitó distinguir "urgencia real" de "objeción de venta". El protocolo exacto queda PENDIENTE de validación clínica/legal (sec. 19) — aquí solo se reserva el lugar arquitectónico |
| `consentimiento_datos` | Si el usuario fue informado/aceptó el tratamiento de sus datos | Orquestador, al inicio o al recopilar un dato sensible | Exigido por la regla de protección de datos personales ya vigente en icaco |
| `canal` | Por dónde llegó la conversación | Orquestador | Canal exacto PENDIENTE (sec. 19); el estado debe ser agnóstico al canal para permitir multicanal a futuro |
| `última_actualización` | Marca de tiempo | Orquestador | Permite políticas de retención/expiración del propio estado |

**Principio derivado**: el cerebro **lee** el estado como entrada y **propone** actualizaciones a ese estado como salida — no lo reconstruye desde el historial crudo en cada turno, que es exactamente lo que hacía Dani.

---

## 7. Cerebro

Funciones que le corresponden al LLM dentro de este componente, y cuáles NO deben dejársele en exclusiva (detalle completo en la tabla de la sección 16):

- **Interpretación**: extraer intención, entidades y tono del mensaje. Responsabilidad del LLM.
- **Detección de intención**: LLM — pero el resultado se escribe de inmediato al `estado.intención`, no se re-infiere cada turno desde el historial (a diferencia de Dani).
- **Razonamiento**: decidir qué falta y qué tool consultar. LLM propone; el orquestador y las reglas deterministas pueden anular la propuesta (ej. si hay `señal_de_urgencia`, la propuesta del LLM se descarta y se fuerza escalamiento, sin importar qué haya "razonado").
- **Planificación**: proponer `próxima_acción`. LLM propone, guardrails validan antes de ejecutar.
- **Generación de respuesta**: LLM, siempre sujeta a GUARDRAILS después (sección 11) — en Dani la generación llegaba casi directo al usuario, con solo el partidor de mensajes como filtro real.
- **Manejo de contexto**: el cerebro NO es responsable de "recordar" — eso es del ESTADO y la MEMORIA (secciones 6 y 8), que se le entregan como entrada. Este es el cambio arquitectónico más importante frente a Dani, donde el LLM era, a la vez, quien razonaba y quien "recordaba" todo desde el historial crudo.

**Regla de diseño central de esta sección**: *el cerebro razona con estado explícito como entrada y propone actualizaciones a ese estado como salida; nunca reconstruye el estado completo desde cero leyendo el historial, como sí lo hacía Dani.*

---

## 8. Memoria

Capas conceptuales (Dani solo tenía la primera):

- **Memoria de conversación**: turnos recientes crudos, ventana corta — igual patrón que Dani (Postgres, `sessionKey`), pero explícitamente entendida como una capa entre varias, no la única fuente de continuidad.
- **Memoria estructurada**: el ESTADO de la sección 6 — persistido, no inferido. Es la capa que Dani no tenía en absoluto.
- **Memoria de usuario/ciudadano**: perfil persistente entre conversaciones distintas (datos de contacto, interacciones previas relevantes al dominio de salud). Ausente en Dani — relevante en salud porque un ciudadano puede retomar un tema días o semanas después.
- **Memoria temporal**: contexto de la sesión actual, con expiración — para no arrastrar información que ya no aplica.
- **Memoria relevante (resumen curado)**: un resumen mantenido activamente, no la ventana cruda completa — evita el problema observado en Dani de que un evento importante (ej. confirmación de compra) "se saliera" de la ventana fija de 8 turnos.

**Qué debe persistirse**: el estado explícito, un resumen curado de la conversación, los datos recopilados relevantes al objetivo declarado, y los eventos de escalamiento/riesgo (para auditoría).

**Qué NO debe persistirse**: contenido verbatim más allá de lo necesario, y ningún dato no relacionado con el objetivo declarado de la conversación — esto es directamente la regla ya vigente en icaco ("todo dato personal capturado... tiene un propósito explícito documentado antes de recolectarse — nunca se recolecta 'por si sirve después'"), y es más estricta aún porque el dominio es salud.

**¿Es adecuado el modelo de Dani (ventana fija de 8 turnos) para ICACO?** No por sí solo — es un buen componente de la capa "memoria de conversación", pero insuficiente como único mecanismo si ICACO necesita continuidad más allá de una sesión (lo cual es previsible en salud: seguimiento de un mismo caso a lo largo de varios días).

---

## 9. Conocimiento

Cuatro categorías, ampliando el patrón de Dani (que solo tenía estático/dinámico vía Google Docs):

- **Conocimiento estático**: información que no cambia con frecuencia (ej. información general de servicios, preguntas frecuentes). Equivalente a `get_detailed_info` de Dani.
- **Conocimiento dinámico**: información que cambia (ej. disponibilidad de horarios, campañas vigentes). Equivalente a `get_course_data` de Dani — **conserva la misma jerarquía de verdad**: si el dato dinámico contradice al prompt o a lo estático, gana el dato dinámico.
- **Conocimiento recuperado por RAG**: para un corpus más grande del que cabe en un documento simple (ej. protocolos extensos, FAQ grande). Dani no lo necesitaba — sus 3 fuentes eran documentos pequeños. En salud, el volumen de información potencial es mayor, por lo que RAG es una evolución natural del mismo patrón, no un componente distinto en espíritu.
- **Conocimiento de sistemas externos**: cualquier dato que vive en un sistema de terceros (ej. un sistema real de agendamiento, un historial clínico si aplica). PENDIENTE por completo — no se puede diseñar el contrato exacto sin saber qué sistemas existen (sección 19).

**Separación dinámico/estático — por qué importa (heredado directamente de Dani)**: evita dos fallos comunes en agentes con LLM — alucinar datos que cambian con frecuencia, y sobrecargar el contexto con detalle estático que rara vez se necesita. Es, en esencia, una forma simple de recuperación de conocimiento con jerarquía de verdad explícita. Este principio es agnóstico al dominio y se traslada sin cambios de ventas a salud.

**Cuándo usar cada uno**: si el dato puede cambiar → dinámico. Si es profundidad rara vez consultada → estático. Si es un corpus grande no acotable a un documento simple → RAG. Si vive en un sistema de un tercero → integración externa con contrato explícito, nunca acceso directo no controlado.

---

## 10. Tools / Herramientas

Categorías generalizadas a partir de las 6 tools de Dani (no se asume que ICACO necesita exactamente las mismas):

| Categoría | Equivalente en Dani | Quién puede invocarla | Cuándo | Qué NO puede decidir por sí sola |
|---|---|---|---|---|
| Datos (dinámico/estático) | `get_course_data` / `get_detailed_info` | Cerebro, vía orquestador | Antes de afirmar cualquier dato variable o de profundidad | No decide si el dato debe compartirse con el usuario (eso es del cerebro + reglas) |
| Evidencia/respaldo | `get_success_stories` | Cerebro, vía orquestador | Cuando el usuario necesita contexto de respaldo | PENDIENTE si aplica igual en salud — en Dani era prueba social de venta; en salud podría transformarse en material educativo, a definir con criterio de dominio, no asumido aquí |
| Manejo de preocupaciones/dudas | `handle_objection` | Cerebro, vía orquestador | Ante duda o resistencia expresada por el usuario | No decide el contenido clínico de la respuesta — solo aporta guion de comunicación, nunca reemplaza criterio profesional |
| Escalación a humano | `escalate_to_human` | Orquestador (el cerebro propone, el orquestador ejecuta) | Palabras clave, incapacidad de resolver, o señal de riesgo (esta última siempre determinista, sección 11) | La tool nunca decide si escalar — solo ejecuta la notificación una vez que la decisión ya se tomó |
| Reporte de vacíos de conocimiento | `report_knowledge_gap` | Cerebro, vía orquestador | Cuando no se puede responder algo que debería saberse | No corrige el vacío por sí sola — solo lo reporta |
| **Acción sobre sistema externo** (nueva, ausente en Dani) | — | Orquestador únicamente, tras confirmación explícita del usuario capturada en el estado | Cuando el objetivo requiere una acción transaccional real (ej. agendar/reagendar/cancelar una cita) | Nunca ejecuta una acción irreversible sin confirmación explícita ya registrada en `estado.datos_recopilados`; nunca decide el permiso por sí sola (ver sección 11) |

**Diferencia clave frente a Dani**: todas las tools de Dani eran de **lectura o notificación** — ninguna ejecutaba una acción transaccional real sobre un sistema externo. ICACO, si su objetivo incluye por ejemplo agendar una cita, necesita una categoría de tool que **escribe**, lo cual exige guardrails más estrictos (confirmación explícita, reversibilidad, registro de auditoría) que no tienen precedente en el diseño de Dani.

**Regla común a todas las categorías**: ninguna tool decide por sí sola escalar, cerrar la conversación, o ejecutar una acción crítica — esas decisiones viven en el orquestador y las reglas deterministas, la tool solo ejecuta una vez tomada la decisión.

---

## 11. Reglas y guardrails

Separación conceptual (en Dani, estas seis capas están todas mezcladas dentro del mismo prompt de texto libre — es la debilidad transversal más importante encontrada en la autopsia):

| Capa | Qué contiene | Dónde vive | Determinista o LLM |
|---|---|---|---|
| **Instrucciones** | Tono, estilo, formato de redacción | Prompt | LLM (equivalente a las secciones "de personalidad" de Dani, ej. H) |
| **Reglas de negocio** | Lógica condicional de qué se ofrece/dice según datos (equivalente al sistema de upgrades de Dani) | Datos/configuración estructurada, NO texto libre | Determinista (el LLM lee el resultado, no decide la regla) |
| **Validaciones** | Que los datos recopilados tengan el formato/tipo esperado | Código | Determinista |
| **Guardrails** | Verificación de la salida del LLM antes de enviarla (formato, promesas prohibidas, no inventar datos, no continuar sin escalar si hay señal de riesgo) | Código, después del cerebro | Determinista — **esto es lo que Dani no tiene en absoluto** |
| **Políticas** | Reglas de alto nivel no negociables (ej. nunca ofrecer un diagnóstico definitivo, siempre derivar decisión clínica a un humano) | Configuración de más alto nivel que las reglas de negocio | Determinista; contenido exacto PENDIENTE de validación médica/legal (sec. 19) — aquí solo se reserva el lugar arquitectónico |
| **Permisos** | Qué puede hacer el agente por sí mismo vs. qué requiere confirmación | Código/configuración | Determinista |
| **Límites del agente** | Qué NO resuelve y a dónde redirige (equivalente a la sección J de Dani) | Configuración + prompt | Mixto: el límite es determinista, la forma de comunicarlo es del LLM |

**Qué debe ser determinista y qué puede quedar en el LLM**: cualquier regla cuyo incumplimiento tenga una consecuencia grave (prometer algo indebido, actuar sobre una urgencia como si no lo fuera, ejecutar una acción irreversible, filtrar un dato personal) debe verificarse en código, no solo en instrucción. Cualquier regla de tono/estilo/personalidad puede quedar en el LLM, porque su incumplimiento degrada la experiencia pero no genera un daño real. Esta línea divisoria es, en esencia, la lección más importante que deja la autopsia de Dani: **en Dani, absolutamente todo — incluidas las reglas críticas de negocio — dependía de instrucción de texto, sin ningún guardrail duro.**

---

## 12. Máquina de estados

Construida a partir del análisis de Dani (fases + regla maestra) y del objetivo de ICACO (orientado a resolver un objetivo del ciudadano, no a cerrar una venta) — no es una copia del ejemplo dado como referencia en el encargo, sino una derivación propia:

```
INICIO
   │
   ▼
IDENTIFICACIÓN_DE_INTENCIÓN          (equivalente sano a la "apertura" de Dani,
   │                                   pero con foco en entender el objetivo,
   │                                   no en calidez comercial)
   ▼
RECOPILACIÓN_DE_DATOS ◄────────┐     (equivalente al "descubrimiento" de Dani,
   │                           │      pero recolectando datos_recopilados
   │ (dato_faltante crítico     │      explícitos hacia un objetivo, no
   │  no obtenible)             │      indagando para personalizar una venta)
   ▼                           │
RAZONAMIENTO/DECISIÓN ─────────┘
   │
   ▼
ACCIÓN                                (invoca tool: dato, escritura externa,
   │                                   o ninguna si ya hay suficiente para responder)
   ▼
RESPUESTA
   │
   ├──► ¿objetivo cumplido? ──► CIERRE
   ├──► ¿falta información? ──► RECOPILACIÓN_DE_DATOS
   ├──► ¿usuario tiene duda/preocupación? ──► MANEJO_DE_DUDA ──► RESPUESTA
   └──► ¿objetivo cumplido pero conversación continúa? ──► SEGUIMIENTO

INTERRUPCIONES GLOBALES (desde CUALQUIER estado, sin excepción):
  señal_de_urgencia detectada (regla determinista, sec. 6/11)
        → ESCALADO_URGENTE (interrumpe todo, sin looping, sin más preguntas)

  usuario pide humano / agente no puede resolver
        → ESCALADO_ESTÁNDAR

  dato faltante crítico que el propio agente no puede resolver
        → PAUSA_POR_DATOS_FALTANTES
```

**Diferencia central frente a la máquina de estados de Dani** (documentada en `002-autopsia-cerebro-dani.md`): en Dani, la única interrupción global era la señal de compra (orientada a *acelerar* la conversación hacia el cierre). En ICACO, la interrupción global de mayor prioridad es la señal de riesgo/urgencia, orientada a *proteger* al usuario, no a completar un objetivo de conversión. Es, conceptualmente, la misma arquitectura de "interrupción desde cualquier estado" — pero con el propósito invertido.

**Advertencia heredada, ya corregida por diseño**: a diferencia de Dani, donde esta máquina de estados no existía como entidad real (todo se inferías del historial), en ICACO cada transición debe escribir explícitamente al `estado.fase_actual` (sección 6) — no basta con que el LLM "sepa" en qué fase está.

---

## 13. Escalamiento humano

- **Cuándo escala**: dos categorías explícitas, a diferencia de Dani (que trataba toda escalación igual):
  - **Urgente**: activada por `señal_de_urgencia` (regla determinista). No requiere looping, ni confirmación, ni que el usuario lo pida.
  - **Estándar**: el usuario lo solicita explícitamente, o el agente agota su capacidad de resolver (equivalente a la escalación de Dani).
- **Quién decide**: la urgente la decide una regla determinista, con el cerebro como señal de entrada pero sin ser el árbitro único (ver sección 11). La estándar puede proponerla el cerebro; el orquestador es quien la ejecuta.
- **Qué información se transfiere**: el `estado` completo — fase, intención, objetivo, datos_recopilados, resumen de contexto. **A diferencia de Dani** (donde el resumen se generaba ad-hoc por el LLM en el momento de escalar, vía `$fromAI`, sin contrato estructurado), en ICACO el contexto que se transfiere ya existe de antemano porque el estado es explícito — no hay que "reconstruirlo" en el instante de escalar.
- **Cómo se evita que el ciudadano repita todo**: precisamente porque el ESTADO (sección 6) es persistente y estructurado, la persona humana que recibe la escalación puede leerlo directamente, sin depender de que el ciudadano vuelva a narrar su caso.
- **A quién exactamente se escala, por qué canal, y con qué disponibilidad real**: PENDIENTE — depende de qué mecanismo humano exista del lado del cliente/operación de ICACO; no se inventa aquí (sección 19).

---

## 14. Observabilidad

Componente completo, **ausente por completo en el diseño de Dani** (ni un solo nodo de logging/métricas fue encontrado en la autopsia). Qué debería registrarse:

- **Eventos**: cada cambio de `fase_actual`/`modo`/`estado`.
- **Decisiones**: qué tool se llamó y por qué, qué guardrail se activó (y si bloqueó o dejó pasar la respuesta).
- **Herramientas**: entrada/salida resumida de cada invocación (sin incluir dato sensible innecesario en el log).
- **Errores**: fallos de integración, tiempos de espera agotados.
- **Tiempos**: latencia por turno y por componente.
- **Estados**: historial de transiciones de la máquina de estados de cada conversación.
- **Conversaciones**: a nivel resumen por defecto; guardar contenido verbatim solo si hay una razón explícita y documentada para hacerlo (coherente con minimización de datos).
- **Métricas**: tasa de resolución, tasa de escalamiento (urgente vs. estándar), tasa de activación de guardrails, tasa de vacíos de conocimiento reportados.
- **Auditoría**: quién accedió, exportó o eliminó datos de un ciudadano — exigido ya por la regla de protección de datos personales vigente en icaco, y por la regla de documentación/memoria del ecosistema (que pide un mecanismo de auditoría propio del dominio, no solo logs de aplicación).

---

## 15. Seguridad y datos

ICACO maneja datos personales de un ciudadano/usuario final real, en un dominio (salud) que típicamente implica una categoría de dato más sensible que datos personales genéricos. Diseño conceptual, sin inventar marco legal:

- **Separación de datos**: datos operativos del agente (configuración, reglas de negocio) separados de los datos personales del usuario — nunca mezclados en el mismo archivo/tabla. Lección directa de Dani, donde ambos convivían en el mismo JSON exportado (aunque en Dani el dato mezclado era operativo de negocio, no personal de un usuario final — en ICACO el riesgo es mayor porque sí hay datos personales reales).
- **Acceso**: PENDIENTE — depende del stack elegido (sección 19); el principio es acceso mínimo necesario por componente, no un acceso total compartido.
- **Permisos**: debe existir un mecanismo para que el propio usuario final sepa qué se guarda de él y pida corregirlo/eliminarlo, disponible desde el propio flujo conversacional — exigido ya por la regla de protección de datos personales vigente en icaco. Mecanismo exacto: PENDIENTE de diseño (sección 20, "siguiente fase").
- **Minimización**: solo recolectar lo necesario para el `objetivo_de_conversación` declarado — regla ya vigente en icaco ("nunca se recolecta 'por si sirve después'"), reforzada aquí por tratarse de datos de salud.
- **Trazabilidad**: todo acceso/cambio a un dato de un usuario debe quedar registrado (conecta directo con Observabilidad, sección 14).
- **Protección**: el marco legal/jurisdicción exacto aplicable a datos de salud está PENDIENTE — no se asume ningún marco específico (ni HIPAA, ni Ley 1581, ni ningún otro) sin confirmación explícita del cliente/usuario, tal como ya exige la propia regla de protección de datos personales de icaco.
- **Retención**: política explícita por tipo de dato — a definir en `.ai/DATA_MODEL.md` de icaco (regla ya vigente), con plazos concretos PENDIENTES.
- **Auditoría**: mecanismo propio del dominio, no solo logs de aplicación — regla ya vigente en icaco vía `.claude/rules/documentacion-y-memoria.md`.

**Nada de esta sección inventa un requisito legal específico** — cada punto que requiere una decisión legal/regulatoria queda marcado PENDIENTE y se traslada también a la sección 19.

---

## 16. LLM vs. software determinista

| Responsabilidad | LLM | Software determinista | Base de datos | Tool | Regla |
|---|---|---|---|---|---|
| Interpretar el mensaje (intención, entidades) | ✅ | | | | |
| Detectar señal de riesgo/urgencia | Propone | ✅ decide | | | ✅ regla dura |
| Persistir el estado de la conversación | | ✅ | ✅ | | |
| Decidir la siguiente pregunta/acción | Propone | ✅ valida | | | |
| Consultar dato dinámico/estático | | | ✅ fuente | ✅ acceso | |
| Ejecutar una acción transaccional (agendar/cancelar) | | ✅ requiere confirmación | | ✅ | ✅ permiso |
| Generar el texto de la respuesta | ✅ | | | | |
| Verificar formato/contenido antes de enviar | | ✅ guardrail | | | ✅ |
| Escalar a humano | Propone | ✅ ejecuta | | ✅ notifica | ✅ |
| Registrar evento de auditoría | | ✅ | ✅ | | |
| Definir precio/condición de negocio | | ✅ lee config | ✅ fuente | | |
| Mantener tono/personalidad | ✅ | | | | |

**Lectura de esta tabla**: casi todo lo crítico (riesgo, acciones transaccionales, permisos, auditoría, verificación de salida) **no** debe dejarse solo al LLM. El LLM interpreta, razona y redacta — pero no gobierna solo. Este es, en una frase, el principio que corrige la debilidad más grande encontrada en Dani, donde absolutamente toda decisión —incluidas las críticas— dependía únicamente del LLM obedeciendo instrucciones de texto.

---

## 17. Matriz Dani → ICACO

| Elemento de Dani | Destino en ICACO |
|---|---|
| Regla maestra de interrupción (señal de compra) | **CONSERVAR** el concepto de interrupción global + **TRANSFORMAR**: la interrupción de mayor prioridad en ICACO es por riesgo/urgencia, no por intención de conversión |
| Separación fuente dinámica/estática | **CONSERVAR** tal cual como patrón de tools (sección 9) |
| Fases de conversación (5 fases de venta) | **TRANSFORMAR EN ARQUITECTURA**: de fases fijas de venta a una máquina de estados orientada a objetivo, con `fase_actual` persistida (sección 12) |
| Contadores de repetición (mentales) | **MEJORAR + TRANSFORMAR**: de "mentales" a campos reales en el estado |
| Escalación sin promesas | **CONSERVAR** el principio; **MEJORAR** con motivo estructurado y distinción urgente/estándar |
| Post-procesamiento desacoplado (partidor de mensajes) | **CONSERVAR** el patrón de separar generación de formateo de canal |
| Psicología de venta (Hormozi/Kahneman/Voss/Belfort/Cialdini) | **DESCARTAR** como técnica de conversión comercial; el principio de labeling/empatía (Voss) puede **CONSERVARSE** para manejo de preocupaciones en salud, sin objetivo de venta |
| Sistema de upgrades condicional | **DESCARTAR** el contenido; **TRANSFORMAR** el patrón de "lógica condicional estructurada" si aplica algún caso análogo en salud |
| Contenido de marca/negocio (precios, chistes, emojis) | **DESCARTAR** completo |
| "Nunca confirmes ser IA" | **MEJORAR/REDISEÑAR**: pendiente de validación legal (sección 19); en salud la transparencia sobre ser un agente automatizado puede ser aún más sensible que en ventas |
| Memoria por `sessionKey` en base relacional | **CONSERVAR** tal cual |
| Ausencia de estado persistido | **TRANSFORMAR EN ARQUITECTURA**: corrección central de este documento (sección 6) |
| Ausencia de guardarraíles de código | **TRANSFORMAR EN ARQUITECTURA**: sección 11 |
| Ausencia de testing | **MEJORAR**: agregar smoke tests + tests de contrato, coherente con la regla de testing ya vigente en icaco |
| Ausencia de observabilidad | **TRANSFORMAR EN ARQUITECTURA**: componente nuevo completo (sección 14) |
| Dependencia de n8n | **DESCARTAR** si ICACO no adopta ese stack — decisión PENDIENTE (sección 19) |

---

## 18. Principios arquitectónicos

1. El LLM razona y redacta; no gobierna solo — toda decisión crítica (riesgo, acción transaccional, escalamiento) pasa por una capa determinista.
2. El estado conversacional es una entidad explícita y persistida, nunca solo inferido del historial.
3. Las reglas de negocio viven en datos/configuración estructurada y versionada, no en texto libre de prompt.
4. Todo dato dinámico tiene una única fuente de verdad, con prioridad explícita sobre lo que el LLM "recuerda".
5. Ninguna tool ejecuta una acción irreversible sin confirmación explícita capturada en el estado.
6. Toda salida del LLM pasa por un guardrail de verificación antes de llegar al usuario.
7. La memoria se diseña en capas (conversación corta, estado estructurado, perfil de usuario, resumen de largo plazo) — nunca una única ventana fija como única fuente de continuidad.
8. Todo evento relevante (decisión, tool, error, escalamiento) es observable y auditable desde el primer día, no agregado después.
9. La recolección de datos personales/sensibles tiene un propósito explícito documentado antes de recolectarse — nunca "por si sirve después".
10. El usuario final puede, desde el propio flujo conversacional, saber qué se guarda de él y pedir su corrección o eliminación.
11. La señal de riesgo/urgencia se evalúa con reglas deterministas, nunca depende solo de que el LLM la reconozca por generalización semántica.
12. El núcleo de orquestación, estado y guardrails es agnóstico de dominio — solo el conocimiento, las tools y las reglas de negocio cambian si ICACO se extiende más allá de salud.
13. Todo componente nuevo nace con al menos una prueba de humo, coherente con la regla de testing ya vigente en el proyecto.
14. Ninguna integración externa se asume sin que su propósito y alcance queden registrados explícitamente antes de construirla.
15. Ante la duda entre inferir una arquitectura o confirmarla, se confirma o se marca como pendiente — nunca se asume.

---

## 19. Pendientes de decisión humana

Ninguna de estas decisiones se asume ni se inventa en este documento:

- Caso de uso exacto dentro de salud (triage informativo, agendamiento, seguimiento de tratamiento, telemedicina, otro).
- Modelo de LLM a usar.
- Base de datos / stack de persistencia.
- Canal de mensajería (WhatsApp, Telegram, web, otro) — ya pendiente en `.ai/CURRENT_STATE.md` e `.ai/INTEGRATIONS.md` de icaco.
- Arquitectura de orquestación/deployment (n8n como Dani, agente nativo tipo Claude Agent SDK, u otro).
- Proveedores de integración externa (sistema real de agendamiento, historia clínica si aplica, etc.).
- Mecanismos de autenticación de usuarios finales.
- Jurisdicción/marco legal exacto de protección de datos — ya pendiente en icaco (`.claude/rules/proteccion-datos-personales.md`); específicamente para salud, si aplica además un marco de dato sensible adicional.
- Protocolo clínico exacto para detectar y manejar señales de urgencia médica — requiere validación de personal de salud/legal, no es una decisión de arquitectura de software.
- A quién exactamente se escala (personal de salud, call center, otro) y su disponibilidad/SLA real.
- Si "nunca confirmar ser un agente automatizado" es aceptable en el dominio de salud, dado que ahí la transparencia puede ser más sensible que en ventas.
- Alcance real y calendario de "evolucionar a otros dominios" — si condiciona alguna decisión de stack desde ahora.

---

## 20. Siguiente fase

Antes de escribir una sola línea de código, se recomienda diseñar (sin implementar todavía):

1. El caso de uso exacto dentro de salud que se ataca primero, traducido a un `objetivo_de_conversación` concreto — evitar intentar cubrir todo el dominio de salud de una vez.
2. El contrato de datos exacto del ESTADO (campos, tipos, validaciones) como un contrato formal, coherente con la regla de contratos ya vigente en icaco.
3. El protocolo de señal de riesgo/urgencia, junto con una persona con criterio clínico/legal — esto no es una decisión de software y no debería diseñarse solo con este documento.
4. La elección de stack (LLM, orquestador, base de datos, canal) — cada decisión aquí determina cuánto de esta arquitectura conceptual es directamente implementable tal cual.
5. Recién después de lo anterior, un primer prototipo mínimo (un solo objetivo de conversación, sin las categorías completas de tools) para validar el patrón de estado explícito + guardrails antes de construir el sistema completo.

Esta fase de siguiente diseño **no se implementa en este documento** — queda propuesta para una sesión posterior.

# FIN DEL RECADO
