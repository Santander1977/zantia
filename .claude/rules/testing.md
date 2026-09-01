# Testing

## Reglas obligatorias (mínimas)

- Ningún endpoint/contrato consumido por más de un componente se considera "terminado" sin al menos una prueba de contrato que falle si el contrato cambia de forma incompatible.
- Todo componente nuevo nace con al menos un test de humo (smoke test) — no se pospone "para después".

## Opcional (depende del proyecto)

- Nivel de cobertura unitaria/integración más allá del mínimo — se decide según la criticidad real del dominio, nunca se impone un porcentaje universal.
- Suite E2E completa — alto valor pero alto costo de mantenimiento; se justifica solo si el flujo cruza varios componentes con frecuencia de cambio alta.

## Origen de estas reglas

En un sistema real de varios repos, solo uno tenía tests automatizados reales; los demás dependían enteramente de verificación manual. Un cambio de contrato en el componente central no tenía ninguna red de seguridad automatizada contra los componentes que lo consumen — el riesgo se materializaba solo cuando un usuario reportaba el fallo en producción.
