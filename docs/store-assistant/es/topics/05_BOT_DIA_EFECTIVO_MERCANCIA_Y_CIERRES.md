# BOT Linux — día, efectivo, mercancía y cierres

**ID de página:** T2STORE-BOT-OPS-ES  
**Versión:** `v1.3.0`  
**Estado:** Borrador detallado; QA y capturas pendientes  
**Página hermana:** `T2STORE-BOT-OPS-EN`

## [BOTOPS-SCOPE] Alcance

Esta página cubre el ciclo operativo de BOT: inicio de día, tablero, solicitudes POS, fondeos, alivios, efectivo, gastos, entrega de valores, recepción, transferencias, merma, cierre de turno y cierre de día.

## [BOTOPS-START] Iniciar BOT

1. Confirma el encabezado **Back Office Tienda**.
2. Verifica tienda y versión visibles.
3. Inicia sesión con el usuario autorizado.
4. Espera que termine la carga operacional.
5. Revisa el tablero antes de iniciar movimientos.

Si aparece un error al cargar los datos operacionales, selecciona **Reintentar** una vez. Si vuelve a fallar, no inicies el día ni movimientos y escala.

## [BOTOPS-START-DAY] Inicio de día

**Inicio:** BOT inicializado, fecha de tienda correcta y sin día operativo abierto para la misma fecha.

1. Selecciona **Inicio de día**.
2. Lee la fecha mostrada.
3. Confirma una sola vez.
4. Espera la hora de inicio y el tablero del día.

Si aparece **Ya se tiene un día operativo registrado para esta fecha**, no vuelvas a iniciar el día. Verifica el día activo y continúa con ese registro o escala si la fecha no corresponde.

## [BOTOPS-DASHBOARD] Leer el tablero

El inicio puede mostrar ventas totales del día, efectivo, productos, merma, ajustes y estado de POS.

- **Total puntos de venta:** resumen de cajas.
- **Caja fuerte** y **Tómbola:** destinos de efectivo.
- **Últ. conexión:** última comunicación visible del POS.
- Mensajes entrantes: solicitudes o trabajos pendientes.

Los datos del tablero ayudan a verificar, pero no sustituyen el folio final de un movimiento.

## [BOTOPS-POS-REQUEST] Atender una solicitud de POS

1. Abre el mensaje o tarjeta pendiente.
2. Identifica POS, turno, cajero, tipo de solicitud e importe.
3. Compara con el responsable físico antes de aceptar.
4. Completa los campos visibles.
5. Confirma una sola vez y espera el resultado.
6. Conserva el folio y documento.

Si el POS deja de aparecer conectado, no dupliques la solicitud. Conserva hora y datos de ambos sistemas y escala.

## [BOTOPS-INITIAL-FUND] Fondo de caja inicial

1. Abre la solicitud de **Fondo de caja inicial**.
2. Confirma POS, turno, responsable e importe.
3. Entrega o registra el efectivo conforme al procedimiento de tienda.
4. Confirma una sola vez.
5. Espera **Se procesó correctamente el fondo de caja inicial**.
6. Conserva el documento y verifica que POS reciba el resultado.

## [BOTOPS-ADDITIONAL-FUND] Fondo adicional

1. Abre **Fondo de caja adicional**.
2. Revisa POS, turno, responsable e importe.
3. Confirma la entrega física antes de aprobar.
4. Confirma una sola vez y espera resultado.
5. Conserva el comprobante.

No genere otro fondo adicional porque POS tarda en actualizar. Comprueba el folio y la última conexión.

## [BOTOPS-RELIEF] Alivios

BOT puede mostrar alivio a tómbola, recuperación de fondo inicial o adicional, recuperación de gasto o alivio manual.

1. Identifica **Alivio No.**, tipo, destino e importe.
2. Confirma el responsable en caja.
3. Cuenta y recibe el efectivo físico según el tipo.
4. Completa la cantidad solicitada.
5. Confirma una sola vez.
6. Conserva número, folio y documento.

Si el último alivio se procesa con diferencias, revisa el desglose visible. No cree otro alivio para compensar sin autorización.

## [BOTOPS-CASH-DASHBOARD] Tablero de efectivo

Abre **Efectivo** o **Tablero de efectivo** para revisar movimientos como fondo de caja, fondo adicional, ventas en efectivo, alivios, correcciones, gastos, faltantes, sobrantes y entrega de valores.

- Filtra o revisa el periodo visible.
- Compara importe, tipo, POS, turno, persona y folio.
- No edites ni recrees un movimiento para corregir una vista.
- Si falta un movimiento confirmado, conserva el folio de origen y escala.

## [BOTOPS-EXPENSE] Registrar gastos

1. Selecciona **Registrar gastos**.
2. Abre el comprobante o retiro pendiente correcto cuando aplique.
3. Selecciona **Tipo de gasto**.
4. Captura el comentario obligatorio.
5. Revisa importe retirado, utilizado y diferencia devuelta.
6. Confirma una sola vez.
7. Espera **Registro de gastos con folio** y conserva el documento.

Todos los gastos deben tener motivo y comentario antes de finalizar el turno. Si BOT muestra que no hubo gastos, no cree uno vacío.

## [BOTOPS-CASH-DELIVERY] Entrega de valores

1. Abre **Entrega de valores**.
2. Verifica número de servicio, sello de seguridad y totales.
3. Captura alivios automáticos, manuales y adicionales según corresponda.
4. Verifica que el formato del sello cumpla lo indicado por la pantalla.
5. Revisa número de alivios e importe total.
6. Confirma una sola vez y conserva el folio.

BOT permite una entrega de valores por día cuando así lo indique. Si ya existe una entrega para la fecha actual, no genere otra.

## [BOTOPS-RECEIVE-SELECT] Seleccionar recepción de mercancía

1. Abre **Recibir mercancía**.
2. Selecciona el origen correcto: almacén/CEDIS u otra tienda según aparezca.
3. Confirma factura o referencia y tienda de origen.
4. Revisa que la recepción esté pendiente y no completada.

Una recepción pendiente puede bloquear otros procesos como pedido eficiente.

## [BOTOPS-RECEIVE-COUNT] Revisar y confirmar recepción

1. Compara cajas y artículos recibidos físicamente con los mostrados.
2. Revisa cada producto y cantidad.
3. Atiende diferencias mediante el control visible; no modifiques archivos.
4. Si BOT avisa que productos no están en el catálogo de la tienda, registra cuáles serán omitidos.
5. Confirma una sola vez.
6. Espera el folio y las copias del documento.

Sin folio o resultado, no vuelva a recibir la misma factura. Escala con referencia, origen, hora y cantidades.

## [BOTOPS-TRANSFER-OUT] Transferencia de salida

1. Selecciona productos y cantidades.
2. Abre **Transferir**.
3. Elige **CEDIS** o **Tiendas**.
4. Lee si se eliminaron productos de peso variable.
5. Confirma destino, persona que envía y motivo.
6. Captura **Comentario obligatorio**.
7. Revisa cajas, piezas o gramos.
8. Confirma una sola vez.
9. Conserva folio, documento y firmas o sellos solicitados.

Los insumos o retornables incluidos pueden transferirse únicamente a CEDIS cuando BOT lo indique.

## [BOTOPS-TRANSFER-IN] Transferencia de entrada

1. Selecciona la transferencia pendiente correcta.
2. Confirma origen, destino, factura o referencia.
3. Revisa productos y cantidades recibidas.
4. Registra diferencias mediante el flujo visible.
5. Confirma una sola vez.
6. Conserva folio, documento y quién recibió.

No vuelva a procesar la misma referencia porque no imprimió.

## [BOTOPS-SHRINKAGE] Registrar merma

1. Abre **Merma**.
2. Busca y selecciona el producto correcto.
3. Captura piezas o gramos según la unidad mostrada.
4. Selecciona un **Motivo** para cada producto.
5. Revisa costo unitario e importe total.
6. Elimina líneas incorrectas antes de confirmar.
7. Obtén autorización.
8. Confirma una sola vez.
9. Espera **Registro de merma con folio** y conserva el documento firmado.

Para peso variable, usa **Registrar merma peso variable** y no conviertas manualmente unidades.

## [BOTOPS-SHIFT-CLOSE-REQUEST] Solicitud de cierre de turno POS

1. Abre el mensaje **Cerrar turno** del POS correcto.
2. Confirma caja, turno y cajero.
3. Revisa ventas, efectivo, pagos electrónicos, alivios, gastos, devoluciones y cancelaciones.
4. Captura denominaciones del último alivio.
5. Compara total ingresado y monto del sistema.
6. Revisa faltante o sobrante.
7. Selecciona **Finalizar turno** una sola vez.
8. Conserva el folio y verifica las dos copias cuando BOT lo confirme.

Si el monto se procesa con diferencias, no repitas el cierre. Conserva el desglose y escala.

## [BOTOPS-END-DAY-BLOCKERS] Bloqueos del cierre de día

BOT puede mostrar **No es posible cerrar el día**. Resuelve únicamente los elementos listados en pantalla:

- **Cierre de turno - POS**: termina el turno indicado.
- **Impresión de precios**: completa o resuelve el trabajo pendiente.
- **Pedido eficiente**: procesa el pedido disponible.
- Gastos pendientes: completa tipo y comentario.
- Recepciones u otros movimientos pendientes cuando se muestren.

No intentes omitir el bloqueo cerrando la aplicación.

## [BOTOPS-END-DAY] Cerrar el día

1. Abre **Cierre de día**.
2. Revisa el recordatorio de registrar todos los gastos.
3. Si falta alguno, selecciona **Registrar gastos** y complétalo.
4. Revisa ventas, alivios, pagos, gastos, entrega de valores, merma y transferencias.
5. Resuelve todos los bloqueos visibles.
6. Confirma el cierre una sola vez.
7. Espera **Cierre de día con folio**.
8. Conserva la carátula completa y todas las páginas.

No repitas el cierre cuando ya existe folio aunque la impresión falle.

## [BOTOPS-LOGOUT] Cerrar sesión BOT

1. Confirma que no haya movimientos pendientes ni procesamiento activo.
2. Selecciona **Salir / Cerrar sesión**.
3. Responde al diálogo **¿Deseas cerrar sesión?**.
4. Verifica que regrese al acceso.

Cerrar sesión no sustituye el cierre de día.

## [BOTOPS-FAQ] Respuestas rápidas

**¿Puedo iniciar otro día si BOT dice que ya existe?** No.

**¿Puedo duplicar una recepción si no imprimió?** No; primero confirma el folio.

**¿Qué bloquea el cierre?** Atiende exactamente la lista que muestra BOT.

**¿Puedo cerrar BOT para ignorar una diferencia?** No.

**¿Cuántas entregas de valores puedo registrar?** Sigue el límite mostrado; BOT puede permitir solo una por día.

## [BOTOPS-ESCALATE] Datos para soporte

Tienda, terminal, versión, usuario sin contraseña, pantalla, movimiento, POS y turno relacionados, importe, productos o cantidades, factura o referencia, folio, fecha, hora y mensaje exacto. Conserva documentos sin compartir datos sensibles.

## [BOTOPS-QA] Pendientes de QA

- Confirmar rutas, roles y autorizaciones.
- Confirmar copias por recepción y transferencia.
- Validar bloqueos completos de cierre.
- Capturar estados vacíos, diferencias, éxito y fallo.
- Confirmar recuperación después de pérdida de conexión POS/BOT.

