# Aislamiento entre proyectos

## Regla obligatoria

Un proyecto nuevo, creado desde `PROJECT-TEMPLATE`, nunca hereda por accidente código, rutas, credenciales, variables, APIs, bases de datos, configuraciones ni documentación privada de otro proyecto de Orangutan.

## Prohibición explícita

- Nunca copiar conocimiento específico de otro proyecto (nombres de dominio, lógica de negocio, estructura de datos concreta) hacia este proyecto sin generalizarlo primero y sin que sea una decisión consciente y documentada.
- Nunca importar código directamente de otro proyecto por ruta relativa cruzando su límite. Si de verdad se comparte una librería entre proyectos, se publica explícitamente como paquete versionado — nunca copy-paste silencioso.
- Nunca reutilizar el `.env`/`.mcp.json` de otro proyecto como punto de partida sin reemplazar cada valor.
- Nunca compartir instancia de base de datos entre proyectos de clientes distintos.

## Checklist antes del primer commit de un proyecto nuevo

1. Grep del nombre de otros clientes/proyectos conocidos sobre todo el árbol del proyecto nuevo — cero resultados esperados.
2. Grep de dominios conocidos de otros proyectos — cero resultados esperados.
3. Verificar que `docs/CLIENT.local.md` no contiene texto de un cliente distinto pegado por error al copiar la plantilla.
4. Verificar que ningún archivo de configuración/despliegue referencia un dominio o servicio de otro proyecto.

Ver `scripts/verificar-aislamiento.sh` para una implementación de referencia de este checklist, y el comando `/paths-audit`.

## Origen de esta regla

Es la condición crítica explícita del diseño de `PROJECT-TEMPLATE`: la plantilla contiene el ADN de Orangutan (arquitectura, reglas, memoria, agentes), nunca el dominio, código o datos de ningún proyecto específico de cliente.
