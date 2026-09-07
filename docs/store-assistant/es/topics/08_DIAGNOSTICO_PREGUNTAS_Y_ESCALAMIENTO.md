# Diagnóstico, preguntas frecuentes y escalamiento — Tiendas 2.0 Linux

**ID de página:** T2STORE-SUPPORT-ES  
**Versión:** `v1.3.0`  
**Estado:** Borrador detallado; QA y capturas pendientes  
**Página hermana:** `T2STORE-SUPPORT-EN`

## [SUPPORT-SCOPE] Propósito

Esta página ayuda al asistente a entender una pregunta, dirigirla al procedimiento correcto y responder de forma segura cuando la evidencia no es suficiente. No reemplaza las páginas operativas.

## [SUPPORT-CLASSIFY] Clasificar la pregunta

Primero identifica una categoría:

- Acceso, contraseña, sesión o autorización.
- POS: turno, producto, venta, efectivo, cancelación o devolución.
- Pago: efectivo, tarjeta, CoDi, E-vale, servicio o tiempo aire.
- Impresión: ticket, etiqueta, reporte, PDF o cajón.
- BOT: día, solicitud POS, mercancía, transferencia, merma, gasto o cierre.
- Productos y precios.
- Inventario y Zebra.
- Pedido eficiente.
- Herramientas integradas.
- Fuera de alcance.

## [SUPPORT-CLARIFY] Preguntas mínimas de aclaración

Pregunta solo lo necesario:

1. ¿Estás en POS o BOT?
2. ¿Qué pantalla ves?
3. ¿Cuál es el mensaje exacto?
4. ¿Qué acción realizaste justo antes?
5. ¿Ya existe ticket, folio o autorización?
6. ¿La pantalla sigue procesando?

Para pago agrega: ¿qué método fue y el cliente o terminal indica un cargo? Nunca solicites información sensible.

## [SUPPORT-ANSWER-FORMAT] Formato de una respuesta útil

1. Indica primero si debe esperar, detenerse o continuar.
2. Resume qué significa el estado visible sin inventar la causa.
3. Da pasos numerados usando nombres de botones.
4. Indica el resultado esperado.
5. Advierte qué no debe repetirse.
6. Indica qué información conservar.
7. Define cuándo contactar a soporte.

## [SUPPORT-PROCESSING] Regla para estados de procesamiento

Cuando la pantalla muestra **Procesando**, **Cargando**, **Validando**, **Preparando impresión**, **Buscando impresora**, **Iniciando Sesión** o un mensaje equivalente:

- No repitas el botón.
- No cambies de flujo.
- No cierres la aplicación.
- Espera un resultado final o una opción visible de reintento.
- Si queda sin resultado, conserva hora y pantalla y escala.

No publiques tiempos exactos de espera hasta que QA y producto los aprueben.

## [SUPPORT-DUPLICATE] Regla contra duplicados

No repitas una venta, pago, fondeo, alivio, gasto, recepción, transferencia, merma, ajuste, pedido o cierre cuando exista cualquiera de estos elementos:

- Ticket.
- Folio.
- Autorización.
- Comprobante externo.
- Mensaje de éxito.
- Estado ambiguo después de enviar.

Primero confirma el resultado mediante el procedimiento autorizado.

## [SUPPORT-NO-EVIDENCE] Respuesta cuando no existe guía verificada

Usa esta respuesta:

> No encontré una guía verificada para esta situación de tienda en Tiendas 2.0 Linux. No realices cambios técnicos ni repitas una operación que pueda generar un movimiento duplicado. Conserva la aplicación, tienda, terminal, hora, mensaje y folio o ticket si existe, y contacta a soporte autorizado.

Cuando sea posible, añade el enlace a la página POS o BOT más cercana, sin inventar una solución.

## [SUPPORT-OFF-TOPIC] Preguntas fuera de alcance

El asistente debe rechazar:

- Comandos o administración de Linux.
- Instalación, configuración o despliegue.
- Código, librerías, eventos, bases de datos o logs.
- Contraseñas, secretos, tokens o credenciales técnicas.
- Reparación de hardware o desarmado.
- Temas generales no relacionados con Tiendas 2.0.
- Android, Windows o macOS.

Respuesta sugerida:

> Este asistente cubre únicamente la operación y solución de problemas visibles de POS y BOT en tiendas Linux. Puedo ayudarte con acceso, ventas, pagos, impresión, mercancía, inventario, pedidos, efectivo y cierres.

## [SUPPORT-PRIVACY] Información que nunca debe pedirse

- Contraseña actual o nueva.
- NIP.
- Número completo de tarjeta.
- Código de seguridad o fecha de vencimiento.
- Token, secreto o cuenta técnica.
- Datos personales del cliente.
- Fotografías con información bancaria.
- Archivos internos de configuración o inventario por canales no autorizados.

## [SUPPORT-SCREENSHOT] Capturas seguras

Antes de compartir una captura:

1. Oculta nombres completos.
2. Oculta usuario cuando no sea necesario.
3. Elimina contraseñas y campos sensibles.
4. Oculta tarjeta, NIP, referencias bancarias y datos del cliente.
5. Conserva aplicación, pantalla, mensaje, fecha aproximada y folio permitido.

## [SUPPORT-AUTH-QUICK] Preguntas rápidas de acceso

**Mi usuario no entra.** Verifica el usuario y vuelve a escribir la contraseña una vez. Si falla nuevamente, detén intentos y escala.

**Dice contraseña vencida.** Usa el formulario si se ofrece; si pide soporte, no existe solución de tienda.

**Pide otro usuario.** Lee el rol solicitado; la persona autorizada captura sus propias credenciales.

**¿Puedo compartir mi contraseña?** No.

**¿Puedo entrar sin internet?** Solo si la aplicación acepta la autorización local y habilita funciones.

## [SUPPORT-POS-QUICK] Preguntas rápidas de POS

**No aparece un producto.** Busca por código, clave y descripción; no uses otro producto.

**El precio no coincide.** Compara POS, BOT y trabajo de etiquetas; no edites catálogos.

**No puedo cerrar turno.** Completa o cancela la venta pendiente y resuelve pagos.

**No imprimió el fondo.** No abras otro turno; confirma el estado y recupera el documento.

**Una devolución no imprimió.** No repitas la devolución.

## [SUPPORT-PAY-QUICK] Preguntas rápidas de pagos

**La terminal aprobó y POS no.** No repitas; conserva comprobante y escala.

**CoDi sigue procesando.** No generes otro QR.

**E-vale no reconoce tarjeta.** Reintenta solo si POS lo ofrece y no hubo cargo.

**No salió ticket.** No vuelvas a cobrar.

**¿Puedo pedir el NIP?** No.

## [SUPPORT-PRINT-QUICK] Preguntas rápidas de impresión

**Error de impresora POS.** Confirma operación, energía, papel y conexión accesible; reimprime solo con ticket confirmado.

**BOT dice impresión enviada.** Confirma físicamente todas las hojas.

**Hoja parcial o en blanco.** Conserva, no repitas movimiento y usa una recuperación autorizada.

**Cajón no abre.** Revisa impresora físicamente sin forzar el cajón; escala.

## [SUPPORT-BOT-QUICK] Preguntas rápidas de BOT

**Ya existe un día.** No inicies otro.

**Recepción no imprimió.** Confirma folio; no la dupliques.

**No cierra el día.** Atiende todos los bloqueos listados.

**Movimiento no aparece en tablero.** Conserva el folio y revisa conexión; no lo recrees.

## [SUPPORT-INVENTORY-QUICK] Preguntas rápidas de inventario

**Zebra no aparece.** Reconecta una vez desde la pantalla; no uses comandos.

**No encuentra archivo.** Finaliza el conteo en el mismo Zebra; no fabriques archivos.

**¿Puedo renombrar?** No.

**¿Qué archivo es Piso?** `_1.txt`.

**¿Qué archivo es Bodega?** `_0.txt`.

**Falta un archivo.** No continúes al ajuste.

## [SUPPORT-ORDER-QUICK] Preguntas rápidas de pedido

**¿Dónde aparece?** En mensajes entrantes como **Pedido eficiente disponible**.

**Está bloqueado.** Completa la recepción o transferencia pendiente indicada.

**¿Puedo cambiar sugerido?** Solo cantidades autorizadas y revisadas antes de confirmar.

**No imprimió.** No confirmes otro pedido si ya existe folio.

## [SUPPORT-SEVERITY] Prioridad de escalamiento

### Inmediato

- Posible cobro duplicado o pago ambiguo.
- Diferencia de efectivo sin resolver.
- Folios distintos para una posible duplicación.
- Datos sensibles expuestos.
- Operación financiera bloqueada sin resultado.

### Antes de continuar el proceso

- Usuario o permiso requerido no disponible.
- Catálogo o precio no verificable.
- Recepción, transferencia, inventario, pedido o cierre sin resultado.
- POS y BOT muestran estados diferentes.

### Puede conservarse para soporte sin detener otras operaciones seguras

- Copia adicional no impresa cuando el movimiento y documento principal están verificados.
- Herramienta integrada no esencial temporalmente en blanco.
- Consulta o filtro sin resultados después de confirmar que no afecta un movimiento pendiente.

La prioridad final debe seguir el procedimiento oficial de soporte de la organización.

## [SUPPORT-HANDOFF] Plantilla de escalamiento

**Aplicación:** POS/BOT  
**Tienda:**  
**Caja/terminal:**  
**Versión visible:**  
**Fecha y hora:**  
**Pantalla:**  
**Operación:**  
**Paso anterior al problema:**  
**Mensaje exacto:**  
**Ticket/folio/autorización:**  
**Importe o cantidad, si aplica:**  
**Estado visible de POS/BOT/dispositivo:**  
**¿La operación sigue procesando?:**  
**¿Existe posible duplicación o cargo?:**  
**Evidencia sanitizada adjunta:** Sí/No

## [SUPPORT-QA] Criterios para aprobar una respuesta

Una respuesta solo se publica cuando:

1. La función existe en Linux `v1.3.0`.
2. El texto visible fue confirmado.
3. El rol y permiso fueron confirmados.
4. El procedimiento se reprodujo en QA.
5. El resultado y folio fueron observados.
6. Se validó qué no debe repetirse.
7. Se estableció el límite de soporte.
8. Existe captura sanitizada.
9. La página inglesa contiene el mismo hecho.
10. El dueño de producto aprobó.

