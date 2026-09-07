# Roles, permisos y operación segura — Tiendas 2.0 Linux

**ID de página:** T2STORE-ROLES-ES  
**Versión:** `v1.3.0`  
**Estado:** Borrador detallado; QA y capturas pendientes  
**Página hermana:** `T2STORE-ROLES-EN`

## [ROLE-SCOPE] Propósito y alcance

Esta página explica cómo orientar a una persona de tienda cuando una función depende de su rol, de un permiso o de la autorización de otra persona. Describe únicamente lo que el usuario puede ver y hacer en POS o BOT sobre Linux.

No identifica componentes técnicos, nombres internos de permisos, reglas de servidor ni configuración. La aplicación decide si la persona está autorizada.

## [ROLE-PRINCIPLE] Regla principal

- Cada persona debe iniciar sesión con su propio usuario.
- Una autorización protegida debe realizarla la persona autorizada con sus propias credenciales.
- No se deben compartir contraseñas, dejar una sesión abierta para otra persona ni intentar evitar una restricción.
- Que un botón exista no significa que el usuario tenga permiso para completar la acción.
- Si la aplicación rechaza una acción, no se debe repetir con credenciales prestadas.

## [ROLE-IDENTIFY-CONTEXT] Identificar el contexto antes de orientar

El asistente debe confirmar:

1. Si la persona está en POS o BOT.
2. El nombre visible de la pantalla o acción.
3. El mensaje exacto mostrado.
4. Si se solicita autorización de otra persona.
5. Si la operación ya produjo ticket, folio o cambio visible.
6. Si la pantalla continúa procesando.

No se debe pedir la contraseña ni solicitar que el usuario la comparta en una captura.

## [ROLE-STORE-USER] Persona operadora de tienda

Una persona operadora puede utilizar las funciones que su sesión muestre y permita. Dependiendo de su asignación, esto puede incluir:

- Iniciar sesión y desbloquear su propia sesión.
- Abrir y operar un turno POS cuando se hayan cumplido los prerrequisitos.
- Buscar, escanear y vender productos.
- Recibir pagos mediante los métodos habilitados.
- Consultar estados visibles y recuperar documentos cuando esté permitido.
- Ejecutar tareas BOT que su menú y autorización permitan.

La documentación nunca debe prometer acceso a una función. Si la pantalla solicita autorización o muestra rechazo, se sigue el procedimiento de acción protegida.

## [ROLE-AUTHORIZER] Persona autorizadora o supervisora

Algunas acciones de riesgo pueden solicitar una autorización adicional. Cuando aparece el diálogo:

1. Lee el texto y confirma qué acción se está autorizando.
2. La persona autorizadora debe estar físicamente presente y revisar la operación.
3. La persona autorizadora captura sus propias credenciales sin compartirlas.
4. Espera el resultado visible antes de continuar.
5. Si la autorización se rechaza, detén la acción y contacta al responsable autorizado.

Una autorización no debe utilizarse para una acción distinta, otra venta o un movimiento posterior.

## [ROLE-PROTECTED-ACTIONS] Acciones que pueden estar protegidas

La aplicación puede solicitar permiso o autorización para acciones como:

- Cancelar productos o una venta completa.
- Procesar una devolución.
- Abrir el cajón fuera del flujo normal.
- Reimprimir determinados documentos.
- Registrar o confirmar movimientos de efectivo.
- Confirmar recepciones, transferencias, mermas o ajustes.
- Confirmar un pedido eficiente.
- Cerrar turno o día.
- Cambiar datos operativos disponibles en pantalla.

La lista exacta puede variar por asignación. La evidencia definitiva es el diálogo visible en la versión liberada.

## [ROLE-PERMISSION-DENIED] La acción fue rechazada por permiso

**Síntoma:** el botón está deshabilitado, la opción no aparece, la aplicación indica falta de permiso o solicita otro usuario.

**Respuesta segura:**

1. Confirma que se inició sesión con el usuario correcto.
2. No cierres ni repitas una operación que ya esté procesando.
3. Si aparece autorización, solicita a la persona autorizada que revise la acción.
4. Si no existe opción de autorización, no intentes rutas alternativas.
5. Conserva aplicación, pantalla, acción, usuario sin contraseña, hora y mensaje.
6. Contacta al responsable autorizado.

No se debe indicar cómo modificar permisos.

## [ROLE-MISSING-MENU] Una opción o menú no aparece

Las causas visibles pueden ser el rol, el estado actual del día o turno, un requisito pendiente o que la función no esté disponible en esa aplicación.

1. Confirma POS o BOT y la pantalla inicial.
2. Verifica que el inicio de sesión terminó correctamente.
3. Revisa si el día o turno requerido está abierto.
4. Revisa avisos o bloqueos visibles.
5. No cambies de usuario solo para buscar la opción.
6. Si continúa ausente, conserva una captura sanitizada y escala.

El asistente no debe afirmar cuál permiso falta si la pantalla no lo identifica.

## [ROLE-BUTTON-DISABLED] Botón visible pero deshabilitado

Un botón deshabilitado normalmente indica que falta una selección, dato requerido, estado previo o autorización. El asistente debe revisar primero la pantalla:

- Campos obligatorios vacíos.
- Renglón, categoría, terminal o documento no seleccionado.
- Cantidad inválida.
- Operación todavía cargando.
- Bloqueo informado en pantalla.

No recomiendes reiniciar solo porque el botón está deshabilitado.

## [ROLE-SUPERVISOR-CREDENTIALS] Captura segura de autorización

- El operador no debe conocer ni escribir la contraseña de la persona autorizadora.
- La persona autorizadora debe confirmar que el diálogo corresponde a la acción esperada.
- No se debe fotografiar el campo de contraseña.
- Si las credenciales se rechazan, solo se permite corregir un error evidente una vez.
- Después de otro rechazo, detener intentos evita bloqueos adicionales.

## [ROLE-AUTHORIZATION-WAITING] Autorización en proceso o sin respuesta

Mientras exista un indicador de procesamiento:

- No pulses nuevamente **Autorizar**, **Aceptar** o **Confirmar**.
- No abras otro diálogo para la misma operación.
- No cambies de usuario ni cierres la aplicación.
- Espera el resultado visible.

Si no aparece resultado, conserva pantalla, hora, operación y cualquier folio previo. Escala sin repetir el movimiento.

## [ROLE-AUTHORIZATION-FAILED] Autorización rechazada

1. Lee el mensaje completo.
2. Confirma que la persona autorizadora usó su propio usuario.
3. Corrige una sola vez un error de captura evidente.
4. Si se vuelve a rechazar, cancela el diálogo de forma segura.
5. No utilices las credenciales de otra persona.
6. Contacta al responsable autorizado para revisar la asignación fuera de la operación.

## [ROLE-AUTHORIZATION-SUCCEEDED] Autorización aceptada

Una autorización aceptada no siempre significa que el movimiento completo terminó. Después de autorizar:

1. Regresa al flujo de la operación.
2. Completa únicamente la acción revisada.
3. Espera el mensaje final.
4. Conserva el folio o ticket generado.
5. Si aparece un error posterior, no vuelvas a autorizar ni repitas hasta confirmar el estado.

## [ROLE-SHIFT-OWNERSHIP] Sesiones y turnos

- Cada cajero debe usar su sesión asignada.
- Antes de cerrar sesión, resuelve o cancela de forma autorizada cualquier venta pendiente.
- No abras un segundo turno si el primero parece abierto o si el fondo ya fue registrado.
- Si BOT muestra una solicitud de POS, atiéndela en la terminal y turno indicados.
- Si el turno pertenece a otra persona o muestra un estado inesperado, detén la operación y escala.

## [ROLE-POS-BOT-BOUNDARY] Diferencia entre POS y BOT

POS se utiliza para la operación de caja y venta; BOT coordina actividades de tienda, mercancía, inventario, pedidos, efectivo y cierres. Una acción iniciada en una aplicación puede requerir confirmación en la otra.

No se debe recrear manualmente en BOT una operación ya enviada desde POS, ni repetir en POS una respuesta pendiente de BOT.

## [ROLE-SENSITIVE-ACTIONS] Operaciones con mayor riesgo

Trata como sensibles:

- Pagos electrónicos y resultados ambiguos.
- Cancelaciones y devoluciones.
- Fondos, alivios, retiros, gastos y entrega de valores.
- Recepciones, transferencias, mermas y ajustes.
- Inventarios y reemplazo de conteos.
- Confirmación de pedidos.
- Cierres de turno y día.

Para estas operaciones, el asistente siempre debe indicar el resultado esperado, qué no repetir y qué evidencia conservar.

## [ROLE-DO-NOT-REPEAT] Cuándo no repetir

No repitas si existe cualquiera de estas condiciones:

- La pantalla sigue procesando.
- Existe ticket, folio, autorización o comprobante.
- Un proveedor externo indica pago aceptado.
- La aplicación regresó a otra pantalla sin mostrar resultado.
- POS y BOT muestran estados distintos.
- Se perdió conexión después de confirmar.

Primero verifica el resultado con la ruta documentada o contacta a soporte autorizado.

## [ROLE-SAFE-RETRY] Cuándo puede ser seguro reintentar

Un reintento solo es aceptable cuando:

1. La aplicación muestra una opción explícita de reintento o indica que no se envió la operación.
2. No existe ticket, folio, cargo, autorización ni cambio visible.
3. El flujo específico documenta el reintento.
4. Se corrigió una causa visible, como un campo vacío o una conexión física accesible.

Si falta cualquiera de estas condiciones, no prometas que el reintento es seguro.

## [ROLE-PRIVACY] Privacidad y credenciales

Nunca solicites ni expongas:

- Contraseñas o NIP.
- Número completo de tarjeta o código de seguridad.
- Tokens, cuentas técnicas o secretos.
- Datos personales del cliente.
- Configuración, archivos internos o registros técnicos.

Para soporte son suficientes la aplicación, tienda, terminal, usuario sin contraseña, pantalla, hora, mensaje y folio permitido.

## [ROLE-ESCALATE] Información para soporte autorizado

Conserva:

- POS o BOT.
- Tienda y terminal.
- Fecha y hora aproximada.
- Usuario o rol afectado, sin contraseña.
- Pantalla y acción intentada.
- Mensaje exacto.
- Estado de día y turno.
- Ticket, folio o referencia permitida.
- Si la operación continúa procesando.
- Captura sanitizada.

## [ROLE-ANSWER-EXAMPLES] Respuestas canónicas

**“¿Cómo obtengo permiso?”**  
La aplicación utiliza los permisos asignados a tu usuario. No intentes cambiarlos desde la tienda. Si la acción solicita autorización, pide a la persona autorizada que revise y capture sus propias credenciales; si no existe esa opción, contacta al responsable autorizado.

**“Préstame otro usuario para hacerlo.”**  
No compartas ni uses credenciales de otra persona. Conserva el mensaje de rechazo y solicita la autorización mediante el flujo visible o contacta al responsable autorizado.

**“Ya me autorizaron, ¿terminó?”**  
No necesariamente. Regresa a la operación, espera el mensaje final y conserva el ticket o folio. No repitas si el resultado queda ambiguo.

## [ROLE-QA] Validación pendiente

Antes de publicar:

- Confirmar en QA qué acciones solicitan autorización en POS y BOT.
- Confirmar el texto exacto de cada diálogo de rechazo.
- Confirmar qué botones se ocultan o deshabilitan por rol.
- Confirmar la relación visible entre terminal, sesión y turno.
- Añadir capturas sanitizadas en español e inglés.
- Registrar fecha, rol probado y resultado.

