# POS Linux — pagos y resultados ambiguos

**ID de página:** T2STORE-PAY-ES  
**Versión:** `v1.3.0`  
**Estado:** Borrador detallado; QA y capturas pendientes  
**Página hermana:** `T2STORE-PAY-EN`

## [PAY-SCOPE] Alcance y regla principal

Esta página cubre efectivo, tarjetas, CoDi, E-vale, pago mixto, servicios y tiempo aire. La regla principal es: **si existe la posibilidad de que un pago electrónico haya sido aplicado, no lo repitas hasta verificar el resultado**.

Frases relacionadas: *se quedó procesando*, *la terminal aprobó*, *no imprimió*, *cliente con cargo*, *CoDi pendiente*, *saldo no aparece*, *tarjeta no reconocida*, *pago rechazado*, *servicio sin folio*.

## [PAY-BEFORE] Antes de cobrar

1. Confirma productos, cantidades, total y cualquier comisión visible.
2. Pregunta al cliente el método de pago.
3. Selecciona el método una sola vez.
4. Para servicio o tiempo aire, confirma proveedor, referencia o teléfono y monto.
5. Verifica que no haya otro pago ya iniciado para la misma venta.

No anotes NIP, número completo, fecha de vencimiento ni código de seguridad de tarjeta.

## [PAY-PROCESSING] Mientras POS muestra “Procesando pago”

- Espera sin seleccionar otro método.
- No presiones varias veces aceptar.
- No cierres POS.
- No retires la tarjeta si aparece **No retires la tarjeta aún**.
- No generes un segundo QR CoDi.
- No inicies otra venta para cobrar el mismo importe.

Una animación o mensaje de procesamiento no confirma aprobación ni rechazo.

## [PAY-CASH] Pago en efectivo

1. Selecciona **Efectivo**.
2. Captura el importe recibido.
3. Verifica **Monto a cubrir**, **Importe pagado** y **Cambio**.
4. Confirma el importe antes de cerrar.
5. Entrega el cambio mostrado después de que POS presente **Cerrar venta**.
6. Conserva o entrega el ticket según el procedimiento de tienda.

Si el importe fue capturado incorrectamente, corrígelo antes de cerrar. No uses movimientos posteriores para compensar un cambio mal entregado.

## [PAY-CARD] Tarjeta débito o crédito

**Controles:** **Tarjeta Débito**, **Tarjeta Crédito**, pantalla **Pago con Tarjeta**.

1. Selecciona el tipo indicado por el cliente.
2. Sigue las instrucciones visibles de POS y la terminal Santander.
3. Mantén la tarjeta según indique la terminal y POS.
4. Espera un resultado final.
5. Si aparece **Transacción exitosa**, verifica que POS cierre la venta y genere el comprobante.
6. Si aparece **Transacción no exitosa**, informa al cliente y usa **Inténtalo de nuevo o solicita otro método de pago** únicamente después del resultado final.

## [PAY-CARD-NOT-RESPONDING] La terminal no responde o no inicia

1. No pulses repetidamente el método de tarjeta.
2. Confirma que la terminal tenga energía y esté físicamente disponible.
3. Lee cualquier mensaje en POS y en la terminal.
4. Si no se mostró aprobación ni se solicitó presentar tarjeta, cancela únicamente mediante el control visible.
5. Si no es posible determinar si comenzó la transacción, trata el resultado como ambiguo y escala.

No desconectes la terminal ni cambies conexiones durante una solicitud activa.

## [PAY-CARD-APPROVED-POS-PENDING] Terminal aprobada, POS sin terminar

Este es un resultado ambiguo.

1. No vuelvas a cobrar.
2. No canceles la venta por tu cuenta si POS sigue procesando.
3. Conserva el comprobante de la terminal.
4. Registra importe, fecha, hora, caja, ticket, autorización y últimos dígitos visibles permitidos.
5. Contacta a soporte autorizado para confirmar el estado.

Nunca solicites al cliente su número completo de tarjeta ni una captura de su aplicación bancaria.

## [PAY-CARD-POS-SUCCESS-NO-PRINT] POS aprobó, pero no imprimió

1. No repitas el cobro.
2. Confirma que la venta esté cerrada y exista número de ticket.
3. Conserva el comprobante de la terminal.
4. Revisa físicamente energía, papel y conexión accesible de la impresora.
5. Usa **Reimprimir ticket** con fecha y número correctos.
6. Si no se localiza el ticket, escala.

## [PAY-CARD-DECLINED] Pago rechazado

Cuando POS muestre **Transacción no exitosa**:

1. Confirma que el mensaje sea final y ya no muestre procesamiento.
2. Informa al cliente sin interpretar el motivo bancario.
3. Usa otro método o un nuevo intento solo cuando POS lo permita.
4. Si el cliente muestra un cargo, trata el caso como ambiguo y no repitas.

El asistente no debe diagnosticar fondos, bloqueo bancario o fraude salvo que la pantalla lo indique expresamente.

## [PAY-CODI] Pago CoDi normal

1. Selecciona **CoDi**.
2. Verifica importe antes de mostrar el QR.
3. Pide al cliente escanear **Escanea para realizar el pago**.
4. Espera **Procesando pago...** sin generar otro código.
5. Continúa solo con **Transacción exitosa**.
6. Verifica cierre de venta, ticket, autorización y folio CoDi cuando aparezcan.

## [PAY-CODI-DECLINED] CoDi no exitoso

Si POS muestra **Transacción no exitosa** y ya no procesa, ofrece otro método según la pantalla. Si el cliente asegura que pagó o muestra movimiento, no repitas ni generes otro QR; conserva folio, importe y hora y escala.

## [PAY-CODI-TIMEOUT] CoDi permanece procesando o vence

1. No generes otro QR.
2. No cierres POS durante la consulta activa.
3. Pide al cliente no volver a enviar el pago.
4. Si aparece un resultado final de rechazo o intento posterior, sigue esa pantalla.
5. Si no aparece resultado, registra caja, ticket, importe, hora, folio y autorización visibles y escala.

## [PAY-EVALE] Pago E-vale normal

1. Selecciona **Tarjeta Bono** o **Tarjeta E-vale**.
2. Cuando aparezca **Desliza la tarjeta por la terminal**, pide al cliente presentarla.
3. Espera **Tarjeta detectada**.
4. El cliente ingresa su NIP en el dispositivo; el cajero nunca lo solicita.
5. Espera **Obteniendo saldo** y revisa el resultado.
6. Confirma el importe y espera el cierre de venta.

## [PAY-EVALE-NOT-DETECTED] Tarjeta E-vale no reconocida

Si aparece **Tarjeta No Reconocida**:

1. Confirma que se está usando el flujo E-vale correcto.
2. Sigue un nuevo intento únicamente si la pantalla lo ofrece y no hubo cargo.
3. Si vuelve a fallar, ofrece otro método con autorización del cliente.
4. No limpies, abras ni ajustes el dispositivo mediante una acción no autorizada.

## [PAY-EVALE-BALANCE] Saldo insuficiente o consulta sin terminar

- **Saldo insuficiente:** informa el saldo visible sin copiar datos personales; solicita otro método o completa el flujo mixto cuando esté permitido.
- **Obteniendo saldo** sin resultado: no deslices repetidamente la tarjeta ni solicites varias veces el NIP. Registra hora y mensaje y escala.
- Si existe duda de cargo, no repitas.

## [PAY-MIXED] Pago mixto

1. Selecciona **Pago Mix**.
2. Confirma el total de la venta.
3. Captura el primer importe y método.
4. Finaliza y verifica esa parte antes de agregar la siguiente.
5. Revisa el **Monto a cubrir** restante.
6. Completa las partes hasta que POS permita **Cerrar venta**.

Si una parte electrónica queda ambigua, detén todo el pago mixto. No borres ni reemplaces la parte incierta hasta recibir verificación.

## [PAY-SERVICE] Pago de servicios

1. Abre **Pago de Servicios**.
2. Escanea el recibo o continúa al catálogo mediante el control visible.
3. Selecciona el proveedor correcto.
4. Captura y vuelve a confirmar la referencia.
5. Confirma el monto del servicio y el total a pagar.
6. Selecciona **Aceptar** una sola vez.
7. Espera autorización, folio y ticket.

Si la referencia o total no coincide, corrige antes de enviar. Después del envío, no repitas por falta de impresión.

## [PAY-AIRTIME] Tiempo aire

1. Abre **Pago de Tiempo Aire**.
2. Selecciona proveedor y monto correctos.
3. Captura el teléfono y repítelo en la confirmación.
4. Si aparece **El número no coincide**, corrige antes de aceptar.
5. Envía una sola vez y espera el resultado.
6. Conserva referencia, autorización, folio y ticket.

Un error de teléfono confirmado por el usuario antes del envío debe corregirse. Después del envío, no repitas automáticamente.

## [PAY-CANCEL] Cancelar un pago en curso

Usa **Cancelar** únicamente cuando POS lo ofrezca y todavía no exista una aprobación. Si la terminal, cliente o POS muestra una posible aprobación, no canceles ni repitas sin verificación. Una cancelación de pantalla no garantiza por sí sola que una transacción externa no se aplicó.

## [PAY-AMBIGUOUS-CHECKLIST] Lista obligatoria para resultado ambiguo

Conserva:

- Tienda y caja.
- Fecha y hora exacta aproximada.
- Importe total y parte electrónica.
- Tipo: débito, crédito, CoDi, E-vale, servicio o tiempo aire.
- Número de ticket si POS lo asignó.
- Folio o autorización visible.
- Mensaje final o pantalla de procesamiento.
- Comprobante físico de la terminal, sin datos sensibles adicionales.
- Si POS cerró la venta o mantuvo el carrito abierto.

No copies número completo de tarjeta, NIP, código de seguridad ni datos bancarios del cliente.

## [PAY-RETRY] Cuándo es seguro reintentar

Un reintento puede considerarse únicamente cuando POS muestra un rechazo final o instruye claramente **Inténtalo de nuevo o solicita otro método de pago**, no existe comprobante, no existe folio de aprobación y el cliente no reporta cargo.

Si falta cualquiera de esas confirmaciones, escala antes de reintentar.

## [PAY-FAQ] Respuestas rápidas

**¿Puedo cobrar otra vez porque no salió ticket?** No. La impresión y el cobro son operaciones diferentes.

**¿Puedo retirar la tarjeta durante “Procesando”?** No cuando POS indica que no se retire.

**¿Puedo crear otro CoDi?** No si el primero sigue pendiente o existe duda de pago.

**¿Qué hago si el cliente dice que sí se cobró?** No repitas. Conserva la evidencia segura y escala.

**¿Puedo pedir el NIP para probar?** Nunca.

## [PAY-QA] Pendientes de QA

- Confirmar cancelación y recuperación por cada método.
- Validar todos los mensajes finales y transiciones visibles.
- Confirmar tiempo autorizado antes de escalar estados pendientes.
- Capturar aprobación, rechazo, timeout y ambigüedad sin datos reales.
- Confirmar reimpresión después de cada tipo de pago.

