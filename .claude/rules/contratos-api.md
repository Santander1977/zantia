# Contratos API

## Reglas obligatorias

- Un endpoint/contrato consumido por más de un componente (frontend, servicio, integración) no puede cambiar de forma (entrada/salida, código de estado, autenticación requerida) sin: (a) una versión nueva, o (b) un período de compatibilidad documentado con fecha de retiro.
- Todo endpoint nuevo o modificado se registra en `.ai/API_CONTRACTS.md` en el mismo cambio que lo crea — nunca "se documenta después".
- Ningún endpoint que exponga datos sensibles queda sin un mecanismo de autenticación explícito y deliberado. Si un endpoint no lleva auth, esa ausencia debe ser una decisión documentada (con motivo) en `.ai/SECURITY.md` o `docs/decisions/`, nunca un olvido silencioso.

## Origen de estas reglas

En un proyecto real auditado, la API no versiona su contrato pese a tener 2 frontends externos independientes que la consumen — un cambio de contrato ahí solo se detectaría cuando un frontend externo falle en producción. Además, un router entero de esa API quedó sin ningún gate de autenticación visible, sin que se pudiera confirmar si era una decisión deliberada o un descuido.
