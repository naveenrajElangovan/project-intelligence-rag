# POS y BOT Linux — impresión, comprobantes, reportes y cajón

**ID de página:** T2STORE-PRINT-ES  
**Versión:** `v1.3.0`  
**Estado:** Borrador detallado; QA y capturas pendientes  
**Página hermana:** `T2STORE-PRINT-EN`

## [PRINT-SCOPE] Alcance y seguridad

Esta página cubre únicamente controles y mensajes visibles de impresión. No contiene configuración de impresoras, controladores, servicios, rutas de dispositivo, Bluetooth, permisos del sistema ni comandos Linux.

Una falla de impresión no significa que la operación de negocio haya fallado. Antes de repetir cualquier cosa, confirma si ya existe ticket, folio, autorización o mensaje de éxito.

## [PRINT-ASK-FIRST] Preguntas que el asistente debe hacer

1. ¿La impresión se hizo desde POS o BOT?
2. ¿Qué documento esperaba la persona?
3. ¿La operación ya mostró éxito, ticket o folio?
4. ¿Qué mensaje de impresora aparece?
5. ¿Salió una hoja completa, parcial, en blanco o ninguna?
6. ¿Se requiere una o varias copias?

## [PRINT-PHYSICAL-CHECK] Revisión física permitida

El usuario de tienda puede:

- Confirmar que la impresora tenga energía.
- Verificar que el cable accesible no esté suelto.
- Confirmar que haya papel y esté colocado según la guía física aprobada.
- Revisar que no haya un atasco visible sin desarmar el equipo.
- Conservar todas las hojas producidas.

El usuario no debe abrir cubiertas técnicas, cambiar puertos, instalar controladores, editar configuración, ejecutar comandos ni desconectar equipos durante una impresión activa.

## [PRINT-POS-ERROR] POS muestra “Error de impresora”

**Mensaje relacionado:** **Verifica que la impresora térmica está correctamente conectada.**

1. Determina si la venta o movimiento ya terminó.
2. Si existe ticket o folio, no repitas el movimiento.
3. Realiza la revisión física permitida.
4. Si existe un flujo de reimpresión para el documento, úsalo una sola vez.
5. Si el error continúa, detén los intentos y escala.

POS no debe considerarse capaz de diagnosticar papel, tapa o tipo exacto de conexión salvo que la pantalla lo diga expresamente.

## [PRINT-BOT-STATES] Estados visibles de impresión en BOT

- **Impresora en espera:** no hay una impresión activa.
- **Preparando impresión:** BOT está creando o preparando el documento; no repitas.
- **Buscando impresora disponible...:** espera; no cambies la selección ni cierres BOT.
- **Impresión enviada** o **Documento enviado a impresión:** confirma físicamente que el documento salga.
- **Error de impresión** o **No se pudo procesar la impresión...:** verifica primero si el movimiento ya tiene folio y después realiza la revisión física permitida.

“Enviada” no garantiza por sí sola que el papel haya salido completo.

## [PRINT-REPRINT-SALE] Reimprimir ticket de venta POS

**Inicio:** opción **Reimprimir ticket**.  
**Campos:** **Fecha (DD/MM/AAAA)** y **Número de ticket**.

1. Obtén la fecha y número del ticket original.
2. Captura ambos datos.
3. Selecciona **Buscar**.
4. Verifica que aparezca **Ticket localizado**.
5. Revisa que tienda, caja, fecha e importe correspondan cuando estén visibles.
6. Selecciona **Reimprimir ticket** una sola vez.
7. Espera el resultado y conserva la copia marcada como reimpresión.

Si aparece **Ticket no localizado**, revisa fecha y número una vez. No pruebes números consecutivos ni uses otro ticket.

## [PRINT-NO-PAPER-AFTER-SALE] Venta completa sin papel

1. No vuelvas a cobrar.
2. Confirma que POS cerró la venta y asignó ticket.
3. Para tarjeta, CoDi o E-vale, conserva también el comprobante o folio disponible.
4. Revisa impresora físicamente.
5. Reimprime con el ticket correcto.
6. Si no puede localizarse, escala; no reconstruyas el comprobante manualmente.

## [PRINT-PARTIAL] Documento parcial o ilegible

1. Conserva el documento incompleto.
2. Verifica si contiene número de ticket o folio.
3. No repitas la venta, devolución, alivio, transferencia, merma, recepción, pedido o cierre.
4. Usa el flujo de reimpresión o impresión del documento únicamente cuando exista.
5. Si la segunda salida es parcial, detén los intentos.

Para documentos con firmas o sellos, utiliza una copia completa; no completes a mano información faltante que debió imprimir el sistema.

## [PRINT-DUPLICATE] Salieron copias duplicadas

- No repitas la operación.
- Compara ticket, folio, fecha, hora e importe.
- Conserva todas las copias y márcalas o gestionalas según el procedimiento oficial de tienda.
- Si los identificadores son diferentes, trata el caso como posibles operaciones duplicadas y escala inmediatamente.

## [PRINT-BLANK] Salió papel en blanco

1. Conserva la hoja como evidencia.
2. No repitas la operación de negocio.
3. Realiza únicamente la revisión física aprobada de papel.
4. Reimprime una vez si el documento y folio están confirmados.
5. Si vuelve a salir en blanco, escala.

No cambies tipo de papel, configuración o equipo sin instrucción autorizada.

## [PRINT-SALES-RECEIPT] Comprobante de venta

Puede incluir tienda, caja, vendedor, número de ticket, productos, cantidades, precios, IVA, efectivo, otros pagos, cambio e información adicional del servicio o pago.

Antes de entregarlo, verifica que corresponda a la venta actual y que sea legible. Para pagos electrónicos, conserva las copias de cliente o comercio conforme a lo que indique el propio documento.

## [PRINT-RETURN-CANCEL] Devolución y cancelación total

- Una devolución genera un documento identificado como **DEVOLUCIÓN**.
- Una cancelación completa puede generar **CANCELACIÓN TOTAL**.
- La falta de impresión no autoriza repetir la devolución o cancelación.
- Conserva quién autorizó, ticket original, importe y hora.

## [PRINT-FUNDING] Fondo de caja

El documento **FONDO DE CAJA** registra el importe y espacios de firma para quien recibe y quien entrega. Si el turno ya quedó abierto, no repitas la apertura por falta del papel. Recupera la impresión si existe un flujo autorizado o escala.

## [PRINT-RELIEF] Comprobante de alivio

Puede indicar tipo, monto, persona que realiza y firma de autorización. Confirma que el número y destino coincidan con el movimiento. No repitas un alivio confirmado para obtener otra hoja.

## [PRINT-EXPENSE] Retiro y liquidación de gasto

- **RETIRO POR GASTO** incluye número de comprobante, importe y firmas requeridas.
- La liquidación puede incluir importe utilizado y diferencia devuelta.
- El texto impreso determina qué nombres, firmas o validaciones son obligatorios.
- No alteres manualmente el código del comprobante.

## [PRINT-SALES-SUMMARY] Arqueo

El documento **ARQUEO** puede mostrar fondeo, ventas, efectivo, E-vale, tarjetas/CoDi, alivios, devoluciones, efectivo en gaveta y comprobantes que deben corroborarse. Puede requerir autorización de Gerente de Distrito. Una diferencia se escala; no se corrige generando movimientos sin autorización.

## [PRINT-POS-LISTS] Listas de merma o transferencia desde POS

POS puede imprimir listas de productos a mermar o transferir, incluidas cantidades. Estas listas apoyan la coordinación con BOT; no demuestran por sí solas que BOT haya completado el movimiento. Conserva la lista hasta obtener el folio final.

## [PRINT-SERVICE-AIRTIME] Servicios y tiempo aire

El ticket puede incluir referencia, autorización y folio. Si la operación tuvo éxito y no imprimió, no repitas el servicio o recarga. Conserva el resultado visible y usa recuperación autorizada.

## [PRINT-CODI-CARD] Comprobantes electrónicos

Pueden incluir ticket, autorización, folio, operador o información enmascarada de tarjeta. Nunca copies ni compartas datos completos de pago. Si terminal y POS muestran resultados diferentes, aplica el procedimiento de pago ambiguo antes de reimprimir.

## [PRINT-BOT-PRICE] Etiquetas y cambios de precio BOT

1. Abre **Impresión de precios**.
2. Revisa filtros, productos, precio actual, precio nuevo y tipo.
3. Selecciona formato grande, chico o señalización según la pantalla.
4. Usa **Previsualizar**.
5. Si BOT separa impresiones por papel azul, amarillo o blanco, coloca el color solicitado.
6. Selecciona **Imprimir** una vez por grupo.
7. Espera **Documento enviado a impresión**.
8. Compara una muestra impresa con la vista previa antes de **Terminar**.

No marques terminada la impresión si faltan hojas o productos.

## [PRINT-BOT-TRANSFER] Transferencias BOT

- La transferencia de mercancía puede confirmar tres copias.
- La transferencia de producto puede confirmar dos copias.
- Confirma siempre el mensaje real mostrado en la operación.
- Revisa folio, origen, destino, productos, cantidades y comentario.
- Completa sello, nombre y firmas originales que solicite el documento.

No repitas la transferencia por falta de una copia.

## [PRINT-BOT-SHRINKAGE] Merma BOT

El reporte registra folio, autorización, productos, piezas o gramos e importes. Puede requerir sello, nombre y firmas del Encargado de turno y Gerente Distrital. Si ya existe folio, no registres la merma nuevamente por una falla de impresión.

## [PRINT-BOT-INVENTORY] Inventario BOT

Conserva el reporte de comparación, reconteo y ajuste con su folio. La impresión no reemplaza la confirmación visible de que el ajuste terminó. Si el PDF o impresión falla después del folio, no repitas el ajuste.

## [PRINT-BOT-ORDER] Pedido eficiente

BOT puede generar listas para Insumos, Pedido Normal y Frutas, verduras y carne, además del resumen y pedido enviado. Verifica artículos, cajas, stock y pedido final. Los artículos modificados pueden identificarse en el documento. No confirmes un pedido adicional por falta del PDF.

## [PRINT-BOT-CLOSE] Cierre de turno y día

- El cierre de turno puede confirmar dos copias.
- El cierre de día genera una carátula y puede incluir ventas, alivios, gastos, entrega de valores, merma y transferencias.
- Conserva folio y todas las páginas.
- No repitas el cierre si existe folio aunque una copia falle.

## [PRINT-CASH-DRAWER] Cajón conectado a impresora

Cuando POS solicita abrir el cajón, requiere autorización del responsable de caja. Si no abre:

1. Confirma que la impresora tenga energía.
2. Revisa la conexión accesible sin mover otros equipos.
3. No fuerces el cajón.
4. No repitas varias veces la orden.
5. Escala con tienda, caja, hora y mensaje.

## [PRINT-ESCALATE] Evidencia para soporte

Conserva: POS o BOT, tienda, caja o terminal, versión, documento esperado, operación, ticket o folio, hora, mensaje de impresión, estado físico observado, número de hojas esperadas y producidas, y todas las copias. Redacta datos de clientes y pagos.

## [PRINT-FAQ] Respuestas rápidas

**No salió ticket. ¿Repito la venta?** No.

**BOT dice “Impresión enviada”. ¿Ya terminó?** Confirma que el papel haya salido completo.

**¿Puedo reimprimir con otro número?** No.

**¿Puedo reiniciar el servicio de impresión?** No es una acción de usuario de tienda.

**¿Qué hago si salió media hoja?** Conserva la hoja, confirma el folio y usa una reimpresión autorizada una vez.

## [PRINT-QA] Pendientes de QA

- Confirmar cada documento y número de copias.
- Validar diferencias entre impresora térmica POS e impresora de documentos BOT.
- Confirmar qué errores físicos detecta realmente la interfaz.
- Verificar reimpresión disponible por tipo documental.
- Capturar estados en Linux con información sanitizada.

