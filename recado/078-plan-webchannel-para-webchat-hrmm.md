# 078 — PENDIENTE: WebChannel nuevo para ZANTIA (integración con el webchat de HRMM)

**Fecha**: 2026-09-11
**Tipo**: plan a futuro, `[PENDIENTE]` — **nada de esto se implementó en esta sesión**, solo el registro del pedido y el contexto real ya investigado para retomarlo directamente en la próxima sesión, sin tener que reconstruirlo. Ningún código se tocó como parte de este recado (mismo criterio que el recado 033).

## 1. El pedido, textual

> Construir un WebChannel nuevo para ZANTIA, más simple que
> TelegramChannel: recibe POST con `{message, sessionId}` (mismo
> contrato que Express de eis-chat-hrmm ya envía), responde con
> `{reply}` en JSON simple (sin streaming). Usa `sessionId` como
> identificador de canal para el gate de identidad persistente ya
> existente — mismo mecanismo, nuevo tipo de canal.

## 2. Contexto ya investigado (recado 077) — no repetir esa investigación

El recado `/Users/enzoalfonso/recado/077-protocolo-webchat-hrmm-vs-n8n.md`
(escrito para ChatGPT, sobre el repo `eis-chat-hrmm`) ya confirmó, leyendo
código real:

- El navegador llama `POST /api/chat` de un servidor Express propio con
  `{ "message": "<texto>", "sessionId": "<sessionId>" }`.
- Express hoy reenvía eso a n8n (`chatTrigger`, streaming NDJSON) y
  responde al navegador con `{ "success": true, "reply": "...", "sessionId": "..." }`
  (o `{ "success": false, "error": "...", "details": "..." }` en error)
  — **nota: el contrato de salida real que Express ya espera de su
  backend tiene 3 campos (`success`/`reply`/`sessionId`), no solo
  `{reply}` como dice el pedido de arriba** — hay que confirmar, al
  retomar esto, si (a) ZANTIA debe replicar el shape completo que
  Express YA consume hoy (más simple: cambiar solo la URL de destino,
  cero cambios en `server.js`), o (b) se va a reescribir el bloque de
  `server.js` que llama al backend para adaptarse a un `{reply}` más
  simple. La recomendación #1 del recado 077 ya señalaba la opción (a)
  como la de menor fricción.
- `sessionId` HOY es efímero (`Date.now().toString()` en el navegador,
  sin `localStorage`/cookie) — se resetea en cada recarga de página.
  Si el gate de identidad persistente de ZANTIA depende de que
  `sessionId` sea estable entre mensajes de la misma persona, esto es
  una brecha real preexistente, no algo que el WebChannel pueda
  resolver por sí solo — el recado 077 ya lo dejó como pregunta
  pendiente para el negocio.
- El servidor Express ya hace rate limiting (50 msg/min por IP) y
  valida longitud (≤5000 chars) ANTES de reenviar — el WebChannel
  nuevo de ZANTIA recibiría tráfico ya filtrado por esa capa, si el
  punto de integración sigue siendo Express→ZANTIA (no navegador→ZANTIA
  directo).

## 3. Diseño esperado — más simple que `TelegramChannel`, y por qué

`channels/contract.py` ya define el `Channel` Protocol agnóstico de
dominio (`InboundMessage`/`OutboundMessage`, `receive()`/`send()`) que
`TelegramChannel`/`ChatwootChannel` ya implementan — el WebChannel nuevo
implementaría el MISMO contrato, sin tocarlo.

**Por qué es estructuralmente más simple que `TelegramChannel`**:
Telegram es asíncrono en 2 pasos — el webhook ENTREGA un mensaje
(`handle_webhook_payload`, encola) y el envío de la respuesta es una
llamada HTTP SEPARADA a la Bot API (`send()`), desacoplada en el
tiempo — por eso `TelegramChannel` necesita una cola interna
(`receive()` desencola). El contrato pedido acá (`POST` → `{reply}` en
la MISMA respuesta HTTP) es un ciclo request/response síncrono de un
solo paso — no necesita cola, ni `secret_token` de webhook (no hay
webhook que verificar, es un endpoint propio de ZANTIA), ni un paso de
envío separado. El diseño más simple sería: el handler HTTP de
`service/app.py` (nuevo `POST /webhook/web` o el nombre que se decida)
llama directo a `handle_inbound_message(gateway, sessionId, canal="web", message_id, text)`
y devuelve el resultado en la MISMA respuesta — sin necesitar siquiera
una clase `WebChannel` con estado propio, a diferencia de
`TelegramChannel`/`ChatwootChannel` (que sí necesitan traducir un
formato de payload externo distinto). A confirmar al implementar si de
verdad no hace falta ninguna clase de canal, o si el proyecto prefiere
mantener la simetría con los otros 2 canales por consistencia aunque
sea más código del estrictamente necesario.

**`sessionId` como identificador de canal**: mismo patrón ya usado por
`patient_reference`/`conversation_id` en los otros canales — se pasa
tal cual a `handle_inbound_message` como el identificador que activa
el gate de identidad persistente (`_gestionar_identificacion`,
`IdentidadCanalStore`) ya existente, sin ningún cambio a ese mecanismo.

## 4. Preguntas abiertas para cuando se retome (no resueltas en esta sesión)

1. ¿El contrato de salida real es `{reply}` (como dice el pedido) o
   `{success, reply, sessionId}` (como confirmó el recado 077 que
   Express ya espera)? Definir esto ANTES de escribir código evita
   tener que tocar `server.js` de `eis-chat-hrmm` si no es necesario.
2. ¿Necesita este endpoint nuevo algún mecanismo de autenticación
   propio (ej. un secreto compartido en un header, similar en espíritu
   a `TELEGRAM_WEBHOOK_SECRET`), o se confía en que solo el servidor
   Express de `eis-chat-hrmm` lo llamará (red interna/lista blanca de
   IP, a decidir según dónde se despliegue cada uno)? `TelegramChannel`
   exige `TELEGRAM_WEBHOOK_SECRET` obligatoria — un canal web nuevo,
   expuesto sin ninguna verificación de origen, sería una superficie de
   ataque nueva si no se decide esto explícitamente.
3. ¿Se resuelve primero la brecha de `sessionId` efímero (recado 077,
   pregunta pendiente #2), o se acepta esa limitación para una primera
   versión?

## 5. Alcance de este recado

Ninguno de los puntos de arriba se implementó — es un registro del
pedido + el contexto ya investigado, para retomar directamente cuando
corresponda. No se tocó ningún archivo de código en esta sesión como
parte de este pedido.
