# Corpus de regresión — conversaciones reales

**Recado 068** — creado tras un patrón repetido de hallazgos individuales en
producción (recados 026, 032, 045-050, 053, 056-059, 062-064, 066-068):
corregir un caso a la vez, sin un lugar único donde acumular la evidencia
real, hacía que el siguiente hallazgo empezara la investigación desde cero.

## Qué es esto

Cada archivo de este directorio reproduce, de EXTREMO A EXTREMO (vía
`handle_inbound_message`, nunca llamando a una función interna aislada),
una transcripción REAL que reveló un bug en producción — nunca un
escenario inventado o hipotético. El conjunto de este directorio se
ejecuta con el resto de la suite (`pytest`), sin necesitar ningún
comando ni configuración especial — es, a propósito, "obligatorio" solo
por ser parte de la suite normal del proyecto.

## Cuándo agregar un archivo nuevo

Cada vez que una transcripción real (reportada por el usuario, o
encontrada auditando) revela un comportamiento incorrecto — sin
importar cuán pequeño parezca. Antes de corregir el bug, agregar el
archivo reproduciéndolo (test que FALLA contra el código actual);
después de corregirlo, el mismo archivo pasa a ser la prueba de
regresión permanente.

## Convención de nombre

`test_recadoNNN_slug-corto-del-hallazgo.py` — `NNN` es el número del
recado que documenta el hallazgo (ver `/Users/enzoalfonso/recado/`),
para poder ir directo al detalle completo (causa raíz, investigación,
decisiones) sin tener que reconstruirlo desde el test.

## Estructura esperada de cada archivo

1. Docstring del módulo: fecha real (si se conoce), transcripción real
   citada TEXTUALMENTE (nunca parafraseada — si algún dato es sensible,
   se anonimiza el dato puntual, nunca la forma real del mensaje),
   hallazgo, causa raíz, corrección — un resumen autocontenido,
   entendible sin abrir el recado original.
2. Una función `test_...` por escenario — usa `handle_inbound_message`
   (o `handle_patient_message` si el escenario nace de un flujo
   OUTBOUND/demanda inducida) con el texto REAL de cada turno, y
   aserciones sobre la respuesta Y, cuando aplica, sobre el estado real
   (`ConversationState`/citas creadas contra un `FakeHttpClient`) — no
   basta con verificar el texto si el hallazgo original fue sobre una
   acción real (una reserva, una cancelación).
3. Si el escenario necesita datos reales verificados contra producción
   (ej. una fecha/hora real confirmada con el usuario o con una
   consulta real a hrmm-backend), decirlo explícitamente en el
   docstring — nunca inventar el dato y presentarlo como si fuera real.

## Qué NO va acá

Tests de unidad de una función aislada (esos viven en el archivo de
test correspondiente al módulo, ej. `test_hrmm_appointment_service.py`)
— este corpus es específicamente para transcripciones REALES
reproducidas de punta a punta. Es normal y deseable que un mismo
hallazgo tenga AMBOS: un test aislado de la función exacta que falló
(rápido, preciso para debuguear) y un test de punta a punta aquí
(prueba que el escenario COMPLETO, tal como lo vivió el paciente real,
funciona).
