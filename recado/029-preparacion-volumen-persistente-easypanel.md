# 029 — Preparación del código para un volumen persistente único en EasyPanel

**Fecha**: 2026-09-06
**Disparador**: el usuario va a configurar un volumen persistente en EasyPanel (fuera del alcance de esta sesión — lo hace él directamente en el panel) y pidió: (1) confirmar el estado real de `ZANTIA_DB_PATH`/`ZANTIA_IDENTIDAD_DB_PATH`, (2) una ruta recomendada para ambos dentro de UN solo directorio montable, (3) confirmar/agregar creación automática de ese directorio, (4) las 2 líneas exactas para EasyPanel.

## 1. Estado real confirmado `[CONFIRMADO]`

`.env` real (no versionado, leído directamente):
```
ZANTIA_DB_PATH=
ZANTIA_IDENTIDAD_DB_PATH=
```
Ambas **vacías** — consistente con el hallazgo ya documentado en recados anteriores (021/022 resolvieron el WIRING de `ZANTIA_DB_PATH`, pero nunca se configuró un valor real en este `.env`). Con ambas vacías, hoy:
- `ZANTIA_DB_PATH` → `core/agent_contract.py:build_orchestrator` cae a `":memory:"` con un `logger.warning` explícito en cada conversación nueva (confirmado leyendo el código).
- `ZANTIA_IDENTIDAD_DB_PATH` → `domains/health/identity_store.py:build_identity_store` cae a `":memory:"` también, pero **sin ningún `logger.warning`** (asimetría real encontrada al verificar esto — no se corrigió en esta sesión por estar fuera del pedido explícito; señalada aquí para que quede registrada, no en silencio).

## 2. Ruta recomendada

```
/app/data/conversaciones.db
/app/data/identidad.db
```
Un solo volumen montado en `/app/data` cubre ambos. Verificado que esto es seguro:
- El `Dockerfile` usa `WORKDIR /app` y no existe hoy ningún directorio `data/` en el repo (`find . -maxdepth 2 -iname data` → vacío) — sin colisión con nada ya empaquetado en la imagen.
- `.dockerignore` ya excluye `*.db` — ningún archivo SQLite local de desarrollo se hornea por accidente dentro de la imagen.
- No hace falta declarar `VOLUME /app/data` en el `Dockerfile` — EasyPanel monta el volumen en la ruta que el usuario indique en su panel, independientemente de si el Dockerfile lo declara. Agregarlo no es necesario y podría tener efectos secundarios no pedidos (volúmenes anónimos en corridas sin volumen explícito) — no se tocó el Dockerfile.

## 3. Creación automática del directorio — confirmado y corregido

`[CONFIRMADO leyendo el código]`:
- `state/store.py:SQLiteStateStore.__init__` **ya hace** `Path(db_path).parent.mkdir(parents=True, exist_ok=True)` cuando `db_path != ":memory:"` (recado 021, R-22) — `ZANTIA_DB_PATH` está cubierto.
- `domains/health/identity_store.py:SQLiteIdentidadCanalStore.__init__` **NO lo hacía** — llamaba `sqlite3.connect(db_path, ...)` directo. `sqlite3.connect` no crea directorios intermedios: si `/app/data` no existiera todavía en el momento exacto de esta llamada, habría reventado con un error críptico en el primer arranque real.

**Corregido en esta sesión** (mismo criterio exacto que `state/store.py`): se agregó el mismo `Path(db_path).parent.mkdir(parents=True, exist_ok=True)` a `SQLiteIdentidadCanalStore.__init__`. En la práctica, con AMBOS archivos apuntando directo dentro de `/app/data` (el propio punto de montaje del volumen, que Docker/EasyPanel garantiza que exista), este `mkdir` es una red de seguridad más que una necesidad estricta — pero deja el comportamiento simétrico entre los dos stores y cubre cualquier variación futura (ej. si alguna vez se usa un subdirectorio anidado dentro de `/app/data`).

Test nuevo: `tests/domains/health/test_identidad_persistente.py::test_sqlite_identidad_canal_store_crea_el_directorio_padre_si_falta` — reproduce exactamente el escenario (carpeta que no existe todavía) y confirma que no revienta.

**Hallazgo lateral corregido de paso**: el docstring de `identity_store.py` (líneas iniciales) seguía diciendo que `build_orchestrator` "no conecta `ZANTIA_DB_PATH` (brecha de wiring preexistente, no resuelta aquí)" — eso era cierto cuando se escribió, pero quedó RESUELTO en el recado 021/R-22 y el comentario nunca se actualizó. Corregido para no dejar un `[CONFIRMADO]` desactualizado en el propio código — la separación de stores entre `identity_store.py` y `state/store.py` se sostiene por la razón real (ciclo de vida distinto: por conversación vs. por teléfono, con retención de 180 días), no por esa brecha ya cerrada.

## 4. Las 2 líneas exactas para EasyPanel

Una vez que el volumen esté montado en `/app/data`:

```
ZANTIA_DB_PATH=/app/data/conversaciones.db
ZANTIA_IDENTIDAD_DB_PATH=/app/data/identidad.db
```

## Verificación

Suite completa: **183 tests pasando + 2 deshabilitados a propósito** (antes de esta sesión: 182). Sin regresiones. No se tocó `Dockerfile`, `.env` real, ni EasyPanel — solo `domains/health/identity_store.py` (mkdir + corrección de comentario) y el test nuevo, tal como se pidió ("no necesitas tocar EasyPanel ni configurar infraestructura").
