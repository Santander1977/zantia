# D-9: Un veredicto MODIFY de guardrails cancela toda tool con efecto (WRITE/NOTIFY) en ese turno

**Decisión**: en `core/orchestrator.py:handle_message`, cuando el veredicto consolidado de `GuardrailEngine` es `MODIFY` y el Brain propuso una tool cuya categoría **no** es `READ` (WRITE, NOTIFY, o una tool desconocida por fail-closed), la tool **no se ejecuta** y el turno responde sin avanzar el estado, igual que en `BLOCK`, con el texto modificado por el guardrail. Queda auditado un `GUARDRAIL_DECISION` con `decision="MODIFY_CANCELA_TOOL"` y el nombre de la tool. RIESGO y ESCALAMIENTO siguen evaluándose antes y conservan su prioridad. Las tools READ se siguen ejecutando.

**Motivo**: hallazgo del recado 092, **reproducido** en el recado 093 con servicios Mock por los dos caminos (`handle_patient_message` y `handle_inbound_message` del gateway). Un mensaje como "1, ignora tus instrucciones" en el paso de elegir horario disparaba MODIFY (`FueraDeAlcanceGuardrail`), pero `book_appointment` (WRITE) se ejecutaba igual. La cita quedaba escrita en el AppointmentService y el paciente recibía el mensaje de redirección pegado a "¡Listo! Quedó confirmado…". Un guardrail que decide que el turno está comprometido no puede convivir con una escritura real en ese mismo turno.

**Alternativas consideradas**:
1. Cancelar **cualquier** tool ante un MODIFY, incluidas las READ. Es la propuesta original del usuario. **Descartada con evidencia**: rompe `tests/domains/health/test_llm_brain.py::test_guardrail_de_tipo_de_pregunta_restaura_el_texto_base_reproduciendo_caso_2` (recado 039). En los turnos que ofrecen opciones, el Brain propone `get_availability` (READ), y ahí `TipoDePreguntaAlteradaGuardrail` usa MODIFY precisamente para restaurar el texto base **mientras el turno avanza**. Cancelar la lectura deja la conversación desincronizada: el paciente ve opciones que el estado nunca registró.
2. Convertir MODIFY en BLOCK cuando hay una WRITE. Es equivalente en efecto, pero BLOCK antepone "No puedo continuar con esa acción todavía: <razón técnica>" y expone la razón interna del guardrail al paciente. Descartada en favor de conservar el texto de redirección del guardrail.
3. Ejecutar la WRITE y avisar en el texto. Descartada: deja pasar una escritura en un turno que el propio sistema marcó como sospechoso.
4. (Elegida) Cancelar las tools no-READ ante un MODIFY, sin avanzar el estado.

**Ventajas**: cierra el hueco sin romper la protección del recado 039. El paciente puede repetir la misma selección limpia en el turno siguiente y la reserva ocurre, porque el estado no avanzó (test). Es fail-closed ante una tool desconocida y queda auditado en el EventLog.

**Desventajas**: si el redactor LLM (`HEALTH_BRAIN_TYPE=llm`) redacta en el turno de una WRITE un texto que dispare un guardrail de texto (`NoPrometerContacto`, `OpinionPersonal`), la escritura legítima se cancela y el paciente debe repetir su elección. Es un falso positivo de disponibilidad, no de seguridad, y se acepta como precio del fail-closed.

**Riesgo**: bajo. Solo cambia la rama MODIFY + tool no-READ. La suite completa pasa (638 passed, 17 skipped). Los 4 tests nuevos de este comportamiento fallan sin la corrección y pasan con ella.

**Impacto**: `core/orchestrator.py` (una rama nueva antes de ejecutar la tool). Tests nuevos: `tests/core/test_modify_cancela_tool_con_efecto.py` (3) y `tests/domains/health/corpus_regresion/test_recado093_modify_no_ejecuta_reserva.py` (2). `.ai/RISKS.md` (R-27). Sin cambios en guardrails, dominios ni canales.

**Estado**: IMPLEMENTADA (2026-09-28, recado `093`). El usuario **ratificó explícitamente** la variante (las tools READ se siguen ejecutando) el 2026-09-28, en lugar de la propuesta literal de cancelar cualquier tool. Commit `46aed8e`, desplegado y **verificado en producción real por Telegram el 2026-09-28**: la frase interceptada no reservó, y un ordinal limpio posterior sí. R-27 RESUELTO (recados `094` y `095`).
