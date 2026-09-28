# 074 — Fix del hallazgo de seguridad del recado 073: dígito suelto en el menú principal

**Fecha**: 2026-09-11
**Rama**: `main` (base `0b89286`, recados 070/071/072 ya desplegados en ese commit)
**Estado**: Implementado, probado, **comiteado y pusheado** (ver hash al final).

---

## 1. El hallazgo (recado 073, resumen)

`gateway.py::_interpretar_opcion_menu` — la función que revisa PRIMERO cualquier mensaje nuevo, antes incluso de la despedida — reconocía un dígito del 1 al 5 SUELTO en cualquier parte de un mensaje, sin ningún límite de longitud. Confirmado con la transcripción real: "Y pasaron los 2 minutos" (un comentario del paciente sobre el enfriamiento) disparó la opción "2. Reprogramar una cita" del menú, y con una cita real reservada, ofreció horarios reales de reprogramación que nadie pidió.

---

## 2. Fix implementado

### 2.1 Reutiliza `_indice_ordinal_seguro` (recado 067) — pero no basta sola

Primer intento: usar directamente `_indice_ordinal_seguro` (la misma función que ya protege `_elegir_opcion`/`_elegir_opcion_ordinal`, límite de 8 palabras). **Verificado empíricamente que NO bastaba**:

```python
>>> _interpretar_opcion_menu("Y pasaron los 2 minutos")   # con SOLO el límite de 8 palabras
RequestIntent.REPROGRAMAR_CITA   # ("Y pasaron los 2 minutos" = 5 palabras, sigue dentro del límite)
>>> _interpretar_opcion_menu("mi hijo cumple 4 años la otra semana")
RequestIntent.CONSULTAR_CITA     # 7 palabras, también dentro del límite
```

**Por qué el límite de 8 palabras, por sí solo, no es suficiente acá**: ese límite fue calibrado para `_elegir_opcion`/`_elegir_opcion_ordinal`, que interpretan la RESPUESTA a una pregunta de selección YA HECHA ("¿cuál de estas 3 prefieres?") — en ese contexto, cualquier mensaje corto se presume una respuesta a esa pregunta específica. `_interpretar_opcion_menu` es estructuralmente distinta: interpreta el **primer mensaje de una conversación nueva**, sin ninguna pregunta de selección de por medio — un mensaje corto ahí no implica en absoluto que sea sobre el menú.

### 2.2 Segunda capa de seguridad: relleno reconocido, mismo patrón que `_es_solo_despedida` (recado 069)

`_indice_menu_ordinal_seguro` (`gateway.py`) envuelve `_indice_ordinal_seguro` con una condición adicional: para que un ordinal SUELTO cuente, **toda otra palabra del mensaje** (además del propio ordinal) debe pertenecer a un conjunto reconocido de relleno neutral (`_PALABRAS_FILLER_SELECCION_MENU`: "opción", "la", "el", "quiero", "por favor", etc.) — mismo patrón exacto ya usado en este archivo/proyecto para `_es_solo_despedida` (brain.py, recado 069): exigir que el mensaje COMPLETO esté compuesto solo por relleno reconocido, nunca solo acotar por longitud.

```python
_PALABRAS_FILLER_SELECCION_MENU = frozenset({
    "opcion", "numero", "num", "la", "el", "los", "las", "una", "un",
    "quiero", "quisiera", "elijo", "escojo", "prefiero", "dame", "es",
    "por", "favor", "porfa", "porfavor", "esa", "ese", "esta", "este", "de",
})

def _indice_menu_ordinal_seguro(texto_norm: str) -> Optional[int]:
    indice = _indice_ordinal_seguro(texto_norm)
    if indice is None:
        return None
    palabras = [p for p in re.split(r"\s+", texto_norm.strip()) if p]
    if not all(p in _PALABRAS_FILLER_SELECCION_MENU or p in _ORDINALES_SUELTOS_MENU for p in palabras):
        return None
    return indice
```

`_interpretar_opcion_menu` ahora llama a `_indice_menu_ordinal_seguro` en vez de hacer `re.search` directo del ordinal — las palabras/frases clave (`"reservar"`, `"cancelar"`, etc.) siguen sin ningún límite adicional, ya protegidas desde el recado 046 con `\b...\b` (una palabra real de contenido es mucho menos propensa a colarse por coincidencia que un dígito de paso).

### 2.3 Auditoría del resto del código (punto 4 pedido)

Busqué sistemáticamente cualquier otro matching de ordinal/dígito que no pasara por el mecanismo centralizado:

- `_elegir_opcion`/`_elegir_opcion_ordinal` — ya usan `_indice_ordinal_seguro`, sin cambios, ya seguros desde el recado 067.
- `intent.py` (`classify_intent_or_none`/`_estricto`/`_tiene_senal_de_intencion`) — confirmado que NO hace ningún matching de dígitos sueltos, solo frases de contenido real ("reprogramar", "cancelar mi cita", etc.) — no vulnerable a este patrón.
- No encontré ningún otro `re.search`/matching de dígito 1-5 fuera de estos 3 puntos, ni ningún otro camino que construya un `RequestIntent` a partir de un número sin pasar por `_interpretar_opcion_menu` o `_clasificar_solicitud_nueva_via_llm` (este último, verificado en el recado 073 con una llamada real a Anthropic, no propone nada para estas frases — descartado como causa, y no comparte el mismo mecanismo de matching).

**Conclusión de la auditoría**: `_interpretar_opcion_menu` era el único punto sin el mecanismo centralizado. Ya cerrado.

---

## 3. Verificación

### 3.1 Los 3 casos vulnerables confirmados en el recado 073 — ahora bloqueados
```python
_interpretar_opcion_menu("Y pasaron los 2 minutos")                        # -> None
_interpretar_opcion_menu("tengo una duda, nos vemos el 3 de este mes")     # -> None
_interpretar_opcion_menu("mi hijo cumple 4 años la otra semana")           # -> None
_interpretar_opcion_menu("llego en 1 hora aprox")                          # -> None
```

### 3.2 Formas cortas legítimas — confirmado que siguen funcionando
```python
"2" -> REPROGRAMAR_CITA          "opcion 2" -> REPROGRAMAR_CITA
"la 2" -> REPROGRAMAR_CITA       "quiero la 2 por favor" -> REPROGRAMAR_CITA
"la segunda" -> REPROGRAMAR_CITA "quiero la segunda opcion" -> REPROGRAMAR_CITA
"5" -> SALIR                     "salir" -> SALIR
"quiero cancelar mi cita" -> CANCELAR_CITA
```

### 3.3 Automatizada
Nuevo archivo `tests/domains/health/corpus_regresion/test_recado073_digito_suelto_disparaba_reprogramacion_fantasma.py` (4 tests): los 4 casos vulnerables bloqueados, las 9 formas legítimas cortas intactas, y una reproducción de extremo a extremo (`handle_inbound_message`) confirmando que "Y pasaron los 2 minutos" nunca revela horarios reales de reprogramación.

**Suite completa: 567 passed, 15 skipped, 0 failed** (antes de este fix: 563 passed — los 4 nuevos son de este recado).

`.ai/CONVERSATION_COVERAGE.md` (fila #1) actualizado en el mismo cambio.

---

## 4. Comiteado y pusheado

```
$ git rev-parse HEAD
4201717475ddf6f5435d8fcee5b293dcd7dfdd17
$ git ls-remote origin refs/heads/main
4201717475ddf6f5435d8fcee5b293dcd7dfdd17	refs/heads/main
```

Confirmado: local y remoto coinciden.

---

## 5. Estado de los hallazgos pendientes

- **Hallazgo 1 (enfriamiento tras despedida sin conversación abierta)**: fix ya en `main` desde el commit `0b89286` (recados 070/071). Pendiente tu confirmación del redeploy en EasyPanel para re-verificar contra el entorno real — avísame cuando lo hagas.
- **Hallazgo 2 (oferta fantasma de reprogramación)**: causa raíz confirmada (recado 073) y corregida (este recado). Con este fix, la transcripción real completa del recado 073 ya NO debería reproducirse — puedo volver a intentarla contra el entorno real una vez confirmes el redeploy de este commit también.
