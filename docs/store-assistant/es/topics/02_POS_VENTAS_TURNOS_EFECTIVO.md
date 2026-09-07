# POS Linux — ventas, turnos y efectivo

**ID de página:** T2STORE-POS-OPS-ES  
**Versión:** `v1.3.0`  
**Estado:** Borrador detallado; QA y capturas pendientes  
**Página hermana:** `T2STORE-POS-OPS-EN`

## [POSOPS-SCOPE] Alcance

Esta página cubre el trabajo diario visible en POS: inicialización, apertura de turno, fondeo, productos, cantidades, venta pendiente, cancelaciones, devoluciones, alivios, retiros, gastos, arqueo y cierre. Los pagos electrónicos y la impresora tienen páginas propias.

## [POSOPS-START] Verificaciones al iniciar POS

1. Confirma que el encabezado diga **Punto de Venta**.
2. Comprueba la tienda y la versión visibles.
3. Inicia sesión con la cuenta del cajero que operará.
4. Espera a que termine la carga de datos operacionales.
5. No comiences una venta mientras aparezca **Cargando...** o un error de inicialización.

Si aparece **Ocurrió un problema al cargar los datos operacionales de la tienda**, usa **Reintentar** una sola vez. Si persiste, no operes con información posiblemente incompleta y escala.

## [POSOPS-OPEN-SHIFT] Abrir turno

**Rol:** cajero con permiso y encargado autorizado.  
**Inicio:** POS inicializado, sin otro turno activo para la caja.  
**Ruta visible:** **Turno y Sesión** y opción de apertura de turno.

### Procedimiento

1. Verifica nombre del cajero, caja y tienda.
2. Selecciona la apertura de turno.
3. Cuando aparezca **Encargado de turno: Ingresar tus credenciales para autorizar**, la persona responsable captura sus credenciales.
4. Revisa el monto de fondo inicial mostrado.
5. Confirma una sola vez.
6. Espera la confirmación de turno abierto y la impresión del documento **FONDO DE CAJA**.
7. Conserva el comprobante y completa las firmas de quien recibe y quien entrega.

### Fallas y límites

- **Acción no permitida. No cuentas con permisos para iniciar un turno:** cancela y solicita a la persona con el rol correcto.
- Sin impresión pero turno confirmado: no abras otro turno; consulta la reimpresión o soporte.
- Sin resultado visible: no repitas la apertura hasta verificar el estado con BOT o soporte.

## [POSOPS-ADDITIONAL-FUNDING] Fondeo adicional

1. Atiende la solicitud o aviso de fondo adicional que muestre POS.
2. Confirma el importe y el responsable que entrega el efectivo.
3. Obtén la autorización solicitada.
4. Confirma una sola vez y espera que el movimiento termine.
5. Conserva el comprobante.

No uses un alivio manual como sustituto de un fondeo que quedó sin resultado. Conserva importe, hora, caja y pantalla y escala.

## [POSOPS-ADD-PRODUCT] Agregar un producto

**Inicio:** pantalla principal de venta con turno abierto.

1. Escanea el código de barras una vez.
2. Confirma descripción, precio y cantidad agregada.
3. Si el producto no tiene código legible, abre el flujo visible de producto sin código o búsqueda.
4. Busca por los campos que ofrezca la pantalla y selecciona el producto correcto.
5. Antes de cobrar, compara físicamente el producto con la descripción.

Si el producto no se encuentra o el precio no es verificable, no selecciones uno parecido. Conserva código, descripción y precio observado y consulta BOT o soporte.

## [POSOPS-QUANTITY] Multiplicar o corregir cantidad

1. Selecciona el producto correcto en el carrito.
2. Usa la función de cantidad o multiplicación visible.
3. Captura la cantidad exacta.
4. Revisa el total de la línea y el total de la venta.

Si aparece que el total supera el monto máximo, reduce o corrige la lista. No dividas una venta únicamente para evadir el límite sin un procedimiento autorizado.

## [POSOPS-PRICE-CHECK] Consultar precio

1. Abre **Consultar precio** cuando esté disponible.
2. Escanea o busca el producto.
3. Lee la descripción y el precio mostrados.
4. Regresa a la venta sin agregar el producto cuando la consulta sea solo informativa.

Si BOT y POS muestran precios distintos, no cambies archivos ni captures manualmente el catálogo. Conserva código, ambos precios, hora y pantallas y escala.

## [POSOPS-PENDING-SALE] Venta pendiente

Una venta abierta debe terminarse o cancelarse correctamente antes del cierre de turno.

- Regresa a la venta pendiente desde la opción visible.
- Revisa productos y pagos ya iniciados.
- Si no hubo pago, completa o cancela con la autorización necesaria.
- Si hubo un pago electrónico ambiguo, no canceles ni repitas hasta que soporte confirme el resultado.

Cerrar la ventana no elimina de forma segura una venta pendiente.

## [POSOPS-CANCEL-PRODUCT] Cancelar productos

1. Selecciona el producto exacto del carrito.
2. Indica la cantidad que se cancelará.
3. Confirma que no sea mayor que la cantidad vendida.
4. Solicita la autorización visible.
5. Confirma y verifica que carrito y total se actualicen.

Si aparece **Este producto no se encuentra en el carrito** o que no puede cancelarse más cantidad, vuelve al carrito y corrige la selección. No agregues o canceles productos distintos para cuadrar el total.

## [POSOPS-CANCEL-SALE] Cancelar toda la venta

1. Verifica que sea la venta correcta y que no exista un pago electrónico ambiguo.
2. Selecciona la cancelación total.
3. Obtén la autorización solicitada.
4. Confirma una sola vez.
5. Espera que POS muestre el resultado y genere **CANCELACIÓN TOTAL** cuando corresponda.

Conserva ticket, autorización y comprobante. Si la pantalla no concluye, no vuelvas a cancelar; escala con hora y datos de la venta.

## [POSOPS-RETURN] Realizar una devolución

1. Abre el flujo de devolución.
2. Captura o localiza el ticket original según la pantalla.
3. Verifica artículos, cantidades e importe.
4. Obtén la autorización requerida.
5. Confirma una sola vez y espera el resultado.
6. Conserva el comprobante **DEVOLUCIÓN**, incluido quién autorizó.

No proceses una segunda devolución por falta de impresión. Usa la recuperación de documento autorizada o escala.

## [POSOPS-OPEN-DRAWER] Abrir cajón

1. Confirma que la apertura es necesaria para una operación autorizada.
2. Selecciona **Abrir cajón**.
3. Cuando aparezca **Ingresa las credenciales del responsable de caja para autorizar**, el responsable captura sus datos.
4. Confirma una sola vez.

El cajón puede depender de la conexión física de la impresora. Si no abre, no golpees ni fuerces el equipo. Revisa energía y conexión accesible de la impresora y escala si persiste.

## [POSOPS-CASH-RELIEF] Realizar alivio

**Controles visibles:** **Posponer**, **Realizar alivio**, **Monto de alivio**, **Confirmar monto**, **Confirmar Alivio**.

1. Lee el tipo y destino: tómbola, gasto, recuperación de fondo inicial o adicional, según aparezca.
2. Cuenta el efectivo antes de capturar.
3. Captura el monto y vuelve a confirmarlo.
4. Revisa la cantidad indicada en **Retira**.
5. Selecciona **Confirmar Alivio** una sola vez.
6. Espera confirmación e impresión.
7. Conserva el número de alivio y las firmas solicitadas.

Si ya se generó un número o comprobante, no repitas aunque la impresión falle.

## [POSOPS-EXPENSE-WITHDRAWAL] Retiro por gasto

1. Abre **Retiro por gasto**.
2. Captura el importe autorizado.
3. Confirma con el encargado cuando se solicite.
4. Espera el **No. de Comprobante**.
5. Imprime y completa nombre y firma de cajero y encargado de turno.

El documento indica si requiere firmas para ser válido. No utilices un comprobante incompleto como liquidado.

## [POSOPS-EXPENSE-SETTLEMENT] Liquidar un gasto

1. Abre el flujo de liquidación.
2. Escanea o captura el comprobante pendiente correcto.
3. Revisa importe retirado, importe utilizado y diferencia devuelta a caja.
4. Obtén la autorización del usuario que abrió el turno cuando se solicite.
5. Confirma una sola vez y conserva el nuevo comprobante.

### Mensajes

- **Comprobante no válido:** no continúes con ese documento.
- **No fue posible leer el código:** revisa físicamente el código; no inventes números.
- **No se encontró un comprobante pendiente:** confirma que sea el comprobante y turno correctos.
- **Se requiere la autorización del usuario que abrió el turno:** espera a esa persona o escala.

## [POSOPS-SUMMARY] Arqueo o resumen de ventas

1. Abre el resumen de ventas del turno.
2. Revisa ventas, efectivo, E-vale, tarjetas/CoDi, alivios y devoluciones.
3. Solicita autorización de Gerente de Distrito cuando la pantalla lo indique.
4. Confirma el efectivo en gaveta y comprobantes que deben corroborarse.
5. Imprime una sola vez y conserva el documento **ARQUEO**.

No corrijas diferencias mediante movimientos nuevos sin autorización.

## [POSOPS-CLOSE-SHIFT] Cerrar turno

**Prerequisitos:** sin venta pendiente, pagos resueltos y movimientos del turno registrados.

1. Selecciona **Cerrar turno** o **Cerrar turno y Cerrar sesión**.
2. Si aparece **Cierre de turno no disponible**, completa o cancela primero la venta indicada.
3. Revisa cualquier recuperación o alivio pendiente.
4. Obtén la autorización requerida.
5. Confirma una sola vez y espera respuesta de BOT.
6. No cierres POS mientras el cierre esté procesándose.
7. Conserva el folio y comprobante cuando aparezcan.

Si BOT no responde o muestra diferencias, no repitas el cierre; compara folio, caja, turno, importe y hora con el responsable.

## [POSOPS-SAFE-RESTART] POS no responde

Antes de considerar cerrar POS, identifica si hay pago, impresión, cancelación, devolución, alivio o cierre en curso. Si existe una operación financiera ambigua, no reinicies. Conserva pantalla y hora y contacta a soporte.

Solo cuando no haya una operación activa y el procedimiento autorizado lo permita, cierra y vuelve a abrir la aplicación desde el acceso normal. Nunca uses comandos ni finalices procesos.

## [POSOPS-FAQ] Respuestas rápidas

**¿Puedo abrir otro turno si no imprimió el fondo?** No. Primero confirma el estado del turno.

**¿Puedo cerrar turno con una venta abierta?** No. POS exige completar o cancelar la venta.

**¿Puedo repetir un alivio si no salió papel?** No si ya existe confirmación o número de alivio.

**¿Puedo usar un producto parecido cuando no aparece el código?** No.

**¿Qué hago con una devolución sin comprobante?** No la repitas; conserva el ticket y escala.

## [POSOPS-ESCALATE] Datos para escalar

Aplicación, tienda, caja, turno, usuario sin contraseña, pantalla, paso, fecha y hora, ticket o folio, importe y texto exacto. Para pagos, aplica además la lista de evidencia de pagos. Para impresión, conserva todas las copias.

## [POSOPS-QA] Pendientes de QA

- Confirmar nombres exactos de rutas y atajos en Linux.
- Confirmar permisos por operación.
- Confirmar impresiones automáticas y número de copias.
- Validar recuperación de ventas pendientes.
- Capturar estados de éxito, vacío, bloqueo y error.

