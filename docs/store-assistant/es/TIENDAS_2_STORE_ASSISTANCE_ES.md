# Asistente de Tienda Tiendas 2.0 — Linux

**Documento:** T2.0-STORE-ES  
**Versión de aplicación:** POS y BOT `v1.3.0`  
**Plataforma:** Linux de tienda  
**Estado:** Borrador; requiere evidencia visual, validación en QA y aprobación del dueño de producto  
**Audiencia:** Personal autorizado de tienda

Este documento contiene respuestas operativas para usuarios de tienda. No contiene instrucciones de administración de Linux ni detalles técnicos internos.

## [SCOPE-01] Cómo debe responder el asistente

- Responde en español cuando la pregunta esté en español.
- Si falta saber si la pregunta corresponde a POS o BOT, pregunta primero cuál aplicación está usando la persona.
- Usa únicamente instrucciones publicadas y verificadas para Linux `v1.3.0`.
- No inventes causas técnicas. Describe el síntoma visible, la acción segura y el límite de escalamiento.
- Nunca solicites contraseñas, NIP, datos completos de tarjeta, códigos de seguridad ni información de clientes.
- Si la guía no está verificada, responde: **“No encontré una guía verificada para esta situación. Conserva la información indicada y contacta a soporte autorizado.”**

## [START-01] Antes de iniciar una operación

1. Confirma si estás en **Punto de Venta (POS)** o **Back Office Tienda (BOT)**.
2. Confirma que la pantalla muestra la tienda y la versión esperadas.
3. Usa únicamente tu usuario; no compartas credenciales.
4. No cierres la aplicación durante una pantalla que diga **Procesando**, **Cargando**, **Preparando impresión**, **Validando** o equivalente.
5. Para soporte conserva: aplicación, tienda, caja o terminal, hora aproximada, paso realizado, texto exacto del mensaje y folio o ticket si existe.

## [AUTH-01] Iniciar sesión en POS o BOT

**Rol:** usuario de tienda autorizado.  
**Inicio:** pantalla de acceso con los campos **Usuario** y **Contraseña**.

1. Escribe tu usuario en **Usuario**.
2. Escribe tu contraseña en **Contraseña** sin mostrarla a otras personas.
3. Selecciona **Iniciar Sesión** una sola vez.
4. Espera mientras aparece **Iniciando Sesión ...**.

**Resultado esperado:** aparece la pantalla inicial correspondiente a tu rol.  
**Reintento seguro:** corrige un error de captura y realiza un nuevo intento. No repitas intentos continuamente.  
**Escala cuando:** las credenciales correctas siguen siendo rechazadas, la pantalla no avanza o aparece un mensaje de configuración del terminal. No cambies archivos ni ajustes de Linux.  
**QA:** pendiente de capturas de POS y BOT.

## [AUTH-02] Usuario o contraseña rechazados

POS puede mostrar **No fue posible iniciar sesión. Intente nuevamente.** BOT puede mostrar **Usuario o contraseña incorrectos.** o **Usuario o contraseña no válidos. Intenta de nuevo.**

1. Verifica que el usuario corresponde a quien está intentando entrar.
2. Vuelve a escribir la contraseña una sola vez, respetando mayúsculas y minúsculas.
3. Si vuelve a fallar, detén los intentos y contacta a soporte autorizado.

No solicites a otra persona su contraseña y no envíes una contraseña por chat, fotografía o correo.

## [AUTH-03] Inicio de sesión sin conexión

La aplicación puede admitir acceso sin conexión solamente cuando ya existe una autorización local válida para ese usuario.

- Intenta iniciar sesión normalmente una vez.
- Si el acceso sin conexión es aceptado, continúa únicamente con las funciones que la aplicación deje disponibles.
- Si el acceso fue rechazado o expiró, no cambies la fecha del equipo, la red ni archivos de configuración.
- Conserva la hora, terminal y mensaje visible; contacta a soporte autorizado.

No se debe prometer que todas las operaciones funcionarán sin conexión.

## [AUTH-04] Contraseña próxima a vencer o actualización requerida

La pantalla puede mostrar **Tu contraseña está por vencer** o **Actualización de contraseña requerida**.

1. Lee si la actualización es opcional o necesaria para continuar.
2. En **Nueva contraseña**, escribe una contraseña que cumpla la longitud mínima mostrada, al menos una mayúscula, una minúscula y un número.
3. Escribe la misma contraseña en **Confirmar contraseña**.
4. Selecciona **Actualizar contraseña** una vez.
5. Espera **Contraseña actualizada** y selecciona **Aceptar**.

Si aparece **Las contraseñas no coinciden**, vuelve a capturar ambos campos. Si aparece **No fue posible actualizar la contraseña**, realiza como máximo un nuevo intento y luego contacta a soporte autorizado. Si la contraseña ya expiró y la aplicación pide contactar a soporte, no existe una recuperación de tienda autorizada.

## [AUTH-05] Sesión bloqueada y desbloqueo

1. En **Sesión bloqueada**, escribe el usuario y contraseña autorizados que solicita la pantalla.
2. Confirma una sola vez y espera el resultado.
3. Si se solicita cambio obligatorio de contraseña, complétalo antes de continuar.
4. Si no puedes desbloquear, usa **Cerrar Sesión** solamente si la pantalla lo permite y no hay una operación procesándose.

No reinicies Linux ni finalices procesos para evadir el bloqueo.

## [AUTH-06] Autorización de acciones protegidas

Algunas acciones solicitan las credenciales de un responsable, encargado o gerente.

- La persona autorizadora debe escribir sus propias credenciales.
- Si aparece **Autorización fallida, intente nuevamente**, verifica que la persona tenga el rol requerido y realiza un solo nuevo intento.
- Si POS indica que el usuario es diferente al usuario conectado, usa al usuario solicitado por la operación.
- Para liquidación de gastos, POS puede exigir al usuario que abrió el turno.
- Para arqueo, POS puede exigir autorización de un Gerente de Distrito.

No uses credenciales prestadas. Si no está disponible el rol requerido, conserva la operación y contacta a soporte autorizado.

## [POS-01] Inicialización de POS

Después del acceso, POS carga los datos operacionales de la tienda. Si aparece **Ocurrió un problema al cargar los datos operacionales de la tienda**:

1. No inicies una venta.
2. Selecciona **Reintentar** una sola vez.
3. Si vuelve a fallar, conserva tienda, caja, hora y mensaje; contacta a soporte autorizado.

No modifiques archivos de configuración ni uses comandos de Linux.

## [POS-02] Venta, búsqueda y cantidades

- Escanea el producto o usa la búsqueda disponible.
- Verifica descripción, cantidad y precio antes de cobrar.
- Para productos sin código, utiliza únicamente el flujo visible autorizado.
- Si aparece **Este producto no se encuentra en el carrito**, regresa a la lista y selecciona un producto existente.
- Si el total supera el monto máximo permitido, ajusta la lista antes de continuar.
- No continúes si el producto o precio no puede verificarse; consulta BOT o soporte según el procedimiento de tienda.

## [POS-03] Cierre de turno con venta pendiente

Si aparece **Cierre de turno no disponible** y se indica completar o cancelar la venta pendiente:

1. Regresa a la venta pendiente.
2. Completa el cobro o cancela la venta mediante la opción visible y la autorización requerida.
3. Vuelve a **Cerrar turno**.

No cierres la aplicación para intentar eliminar la venta pendiente.

## [POS-04] Abrir turno y recibir fondeo

1. Inicia sesión con el usuario que operará la caja.
2. Abre el turno desde **Turno y Sesión**.
3. Cuando aparezca la autorización, el encargado de turno debe escribir sus propias credenciales.
4. Verifica el monto de **Fondeo inicial** antes de aceptar.
5. Espera la confirmación y conserva el comprobante de fondo de caja.

Si aparece **Acción no permitida. No cuentas con permisos para iniciar un turno**, no uses otro usuario sin autorización. Contacta al responsable de tienda. Si el comprobante no imprime, no abras otro turno; utiliza la guía de impresión.

## [POS-05] Alivios, retiros y gastos

- Para un **Alivio**, verifica monto y destino antes de **Confirmar Alivio**.
- En un retiro por gasto, conserva el número de comprobante y completa los nombres y firmas que solicita el documento.
- Para liquidar el gasto, usa el comprobante pendiente correcto. Si POS indica **Comprobante no válido**, **No fue posible leer el código** o **No se encontró un comprobante pendiente**, no captures otro movimiento como reemplazo.
- La liquidación puede requerir al mismo usuario que abrió el turno.
- No repitas un alivio o retiro si POS ya mostró confirmación o generó un comprobante.

## [POS-06] Cancelaciones y devoluciones

1. Confirma si se cancelará un producto, toda la venta o se realizará una devolución.
2. Revisa producto, cantidad, ticket e importe antes de continuar.
3. Obtén la autorización que solicite la pantalla.
4. Espera el resultado final y conserva el comprobante de cancelación o devolución.

No canceles más unidades de las que existen en la venta. Si la operación queda procesándose o no genera resultado verificable, no la repitas; conserva ticket, hora, importe y autorización y escala.

## [PAY-01] Regla general para pagos electrónicos

Durante **Procesando pago...**:

- No selecciones nuevamente el método.
- No cierres POS.
- No retires la tarjeta cuando POS muestre **No retires la tarjeta aún.**
- No inicies una segunda venta para el mismo cobro.

Solo considera terminado el pago cuando POS muestre un resultado final y la venta genere su comprobante o cierre correspondiente.

## [PAY-02] Pago con tarjeta Santander

1. Selecciona **Tarjeta Débito** o **Tarjeta Crédito**.
2. Sigue las indicaciones visibles de POS y de la terminal de pago.
3. Espera **Transacción exitosa** o **Transacción no exitosa**.
4. Si se aprueba, confirma que POS cierre la venta y genere el comprobante esperado.

**Resultado ambiguo:** si la terminal parece aprobar pero POS no termina, no repitas el cobro. Conserva ticket, autorización si aparece, importe, hora, caja y comprobante de la terminal; contacta a soporte autorizado.

## [PAY-03] Pago con CoDi

1. Selecciona **CoDi**.
2. Pide al cliente escanear el código mostrado en **Escanea para realizar el pago**.
3. Espera mientras POS muestre **Procesando pago...**.
4. Continúa únicamente al ver **Transacción exitosa**.

Si se muestra **Transacción no exitosa**, sigue la opción visible para intentar después o usar otro método. Si el cliente reporta cargo pero POS no confirma, no generes otro código ni repitas el cobro; conserva importe, hora, caja, folio o autorización visibles y escala.

## [PAY-04] Pago con tarjeta E-vale

1. Selecciona **Tarjeta Bono** o **Tarjeta E-vale**, según la pantalla.
2. Sigue **Desliza la tarjeta por la terminal**.
3. Espera **Tarjeta detectada** y captura el NIP únicamente en el dispositivo autorizado.
4. Espera la consulta de saldo y el resultado final.

Si aparece **Tarjeta No Reconocida** o **Saldo insuficiente**, no fuerces la operación. Usa otra forma de pago únicamente con la aceptación del cliente. Nunca solicites ni anotes el NIP.

## [PAY-05] Efectivo y pago mixto

- Verifica el **Monto a cubrir**, el **Importe pagado** y el **Cambio** antes de cerrar.
- En **Pago Mix**, confirma cada importe antes de iniciar la siguiente parte.
- Si una parte electrónica queda ambigua, no reemplaces ni repitas esa parte hasta recibir verificación autorizada.
- Entrega el cambio únicamente después de que POS muestre **Cerrar venta** y el importe correspondiente.

## [PAY-06] Servicios y tiempo aire

- Confirma proveedor, referencia, teléfono y total antes de aceptar.
- Si la confirmación no coincide, corrige los datos antes del pago.
- Después de enviar la operación, espera el resultado final; no repitas si existe duda de cobro.
- Conserva referencia, autorización, folio, importe, hora y ticket para cualquier aclaración.

## [PRINT-01] POS no imprime un ticket

Si aparece **Error de impresora** o **Verifica que la impresora térmica está correctamente conectada**:

1. Confirma que la impresora tenga energía.
2. Revisa visualmente que el cable accesible esté conectado y que haya papel colocado correctamente.
3. No desconectes otros equipos y no cambies ajustes de Linux.
4. Si la venta ya terminó, no vuelvas a cobrar. Usa **Reimprimir ticket** únicamente con el número de ticket y la fecha correctos.
5. Si no existe ticket localizado o la reimpresión falla, contacta a soporte autorizado.

## [PRINT-02] Reimprimir ticket POS

1. Abre **Reimprimir ticket**.
2. Captura **Fecha (DD/MM/AAAA)** y **Número de ticket**.
3. Selecciona **Buscar**.
4. Verifica **Ticket localizado** antes de reimprimir.
5. Selecciona **Reimprimir ticket** una sola vez y espera.

Si aparece **Ticket no localizado**, verifica fecha y número una vez. No uses otro ticket como sustituto.

## [PRINT-03] Impresión parcial, ilegible o duplicada

- No repitas el pago.
- Conserva todas las copias producidas.
- Si POS confirma la venta y existe número de ticket, usa el flujo de reimpresión una sola vez.
- Si el documento operativo requiere firmas, no lo consideres válido hasta que esté completo y firmado según el texto impreso.
- Si la segunda salida también falla, detén intentos y contacta a soporte autorizado.

## [PRINT-04] Documentos POS que pueden imprimirse

Según la operación, POS puede generar comprobantes de venta, devolución, cancelación total, apertura de turno, alivio, retiro por gasto, liquidación de gasto, arqueo, lista de merma o transferencia, servicios y tiempo aire. El usuario debe conservar el número de ticket, folio, autorización y firmas que el propio documento solicite.

## [BOT-01] Inicialización de BOT

Si BOT muestra **Ocurrió un problema al cargar los datos operacionales de la tienda**:

1. No inicies movimientos de tienda.
2. Selecciona **Reintentar** una sola vez.
3. Si vuelve a fallar, conserva tienda, terminal, versión, hora y mensaje; contacta a soporte autorizado.

## [BOT-02] Fondeos, alivios y solicitudes de POS

- Abre la solicitud desde el área de mensajes o desde el tablero correspondiente.
- Verifica POS, turno, responsable, tipo de movimiento e importe.
- Para **Fondo de caja inicial** o **Fondo de caja adicional**, confirma una sola vez y espera el mensaje de procesamiento correcto.
- Para un alivio, verifica número, destino, importe y responsable en caja antes de completarlo.
- Si el monto se procesa con diferencias, conserva el folio y sigue el desglose visible; no generes un segundo movimiento para compensarlo sin autorización.

## [BOT-03] Recepción de mercancía

1. Abre **Recibir mercancía**.
2. Selecciona la recepción pendiente correcta y confirma origen, factura o referencia.
3. Revisa cajas, artículos y productos antes de procesar.
4. Si BOT advierte que algunos productos no están en el catálogo de la tienda, entiende que serán omitidos; conserva cuáles fueron antes de confirmar.
5. Completa la recepción una sola vez y conserva el folio y el documento generado.

Una recepción CEDIS pendiente puede bloquear el pedido eficiente. No crees una recepción duplicada si no aparece resultado; conserva la referencia y escala.

## [BOT-04] Transferencias de entrada y salida

1. Confirma si es una transferencia de entrada, hacia CEDIS o hacia otra tienda.
2. Verifica origen, destino, motivo, productos, cajas, piezas o gramos.
3. Captura el comentario obligatorio cuando aparezca.
4. Lee cualquier aviso de productos omitidos antes de confirmar.
5. Espera el folio y la confirmación de impresión.

Los insumos o retornables pueden estar limitados a CEDIS y los productos de peso variable pueden excluirse según el flujo. Conserva todas las copias y completa sellos, nombres y firmas que el documento solicite.

## [BOT-05] Registrar merma

1. Abre **Merma** o **Registrar Merma**.
2. Selecciona el producto, cantidad o peso y el motivo visible.
3. Revisa costo e importe antes de continuar.
4. Obtén la autorización requerida.
5. Confirma una sola vez y espera el folio **Registro de merma**.
6. Conserva el documento y completa sello, nombre y firmas solicitados.

Para merma de peso variable, usa el flujo específico y no sustituyas gramos por piezas.

## [BOT-06] Registrar y completar gastos

1. Abre **Registrar gastos**.
2. Selecciona **Tipo de gasto** y captura el comentario obligatorio.
3. Verifica importe retirado, importe utilizado y diferencia devuelta.
4. Confirma una sola vez y conserva el folio.

Antes de terminar el turno o día, completa motivo y comentario de todos los gastos pendientes. Si no hubo gastos, BOT puede mostrar **No se registró ningún gasto durante el turno**.

## [BOT-07] Cerrar turno y cerrar día

Para cerrar turno:

1. Atiende primero el mensaje **Cerrar turno** del POS correspondiente.
2. Captura las denominaciones del último alivio y revisa caja fuerte, tómbola, faltante o sobrante.
3. Selecciona **Finalizar turno** una sola vez.
4. Conserva el folio y verifica las dos copias cuando BOT confirme que se imprimieron correctamente.

Para cerrar día:

1. Abre **Cierre de día**.
2. Registra todos los gastos del día antes de confirmar.
3. Resuelve cada bloqueo visible: turnos POS abiertos, impresión de precios o pedido eficiente pendiente.
4. Confirma una sola vez y conserva el folio y comprobante de cierre.

No cierres BOT ni repitas el cierre mientras esté procesándose.

## [SYNC-01] POS y BOT no muestran la misma información

1. Confirma que ambos equipos corresponden a la misma tienda.
2. Revisa en BOT la **Últ. conexión** del POS cuando esté disponible.
3. No repitas solicitudes, alivios, cierres, recepciones o ajustes mientras una pantalla indique procesamiento.
4. Usa **Revalidar** solamente cuando el flujo de inventario lo ofrezca.
5. Si la información continúa diferente, conserva folios, horas y pantallas de ambos sistemas; escala.

No edites la base de datos ni archivos locales.

## [CATALOG-01] Productos, catálogo y precios

Las actualizaciones de catálogo llegan automáticamente a BOT. El personal de tienda no carga archivos de productos.

- Si un producto o precio no aparece, espera a que termine la inicialización y vuelve a buscar.
- Revisa los avisos de cambios de precio y la función **Impresión de precios**.
- No crees ni modifiques archivos de catálogo.
- Si POS y BOT siguen mostrando datos diferentes, conserva código de barras, clave, precio observado, hora y pantallas; contacta a soporte autorizado.

## [LABEL-01] Imprimir cambios de precio y etiquetas

1. Abre **Impresión de precios**.
2. Selecciona el formato visible: cenefa grande, cenefa chica o señalización, según corresponda.
3. Revisa productos, precio actual, precio nuevo y configuración.
4. Usa **Previsualizar** antes de imprimir.
5. Cuando BOT pida un color de papel, coloca el indicado y selecciona **Imprimir** una sola vez.
6. Espera **Documento enviado a impresión** antes de continuar con el siguiente grupo.

Si aparece **No se pudo procesar la impresión**, no marques el trabajo como terminado. Revisa físicamente la impresora una vez y vuelve a intentar solo si BOT lo permite.

## [ZEBRA-01] Descargar el diseño de inventario al escáner

1. Conecta el escáner Zebra autorizado.
2. En BOT abre **Inventario** y selecciona el tipo de inventario.
3. Selecciona **Descargar** una sola vez.
4. Espera **Descarga de archivo** y la cantidad de productos descargados.

Si aparece que no se encontró dispositivo, archivo, herramienta o permiso, no uses comandos de Linux. Reconecta físicamente el dispositivo una vez y repite desde BOT. Si vuelve a fallar, conserva el mensaje exacto y escala.

## [ZEBRA-02] Importar conteos de Piso de venta y Bodega

1. Realiza los conteos de piso y bodega en el escáner.
2. No edites ni renombres los archivos generados.
3. Conecta el escáner y abre **Importar archivo**.
4. Importa el archivo de **Piso de venta** (`_1.txt`) y el de **Bodega** (`_0.txt`) mediante BOT.
5. Verifica la cantidad de artículos cargados y que ambos estados aparezcan como importados.
6. Si BOT muestra **Reemplazar archivo**, confirma solamente si estás seguro de sustituir el conteo previamente importado.

Si aparece **No se encontraron archivos para importar**, no fabriques archivos manualmente. Revisa que el conteo se haya generado en el escáner y escala si persiste.

## [ZEBRA-03] Comparación, reconteo y ajuste

1. Cuando ambos archivos estén importados, continúa con la validación.
2. Espera mientras BOT valida la conexión con POS y compara ventas registradas durante el conteo.
3. No cierres BOT ni repitas la importación durante la comparación.
4. Si existen diferencias, selecciona los artículos indicados para reconteo.
5. Repite el conteo físico y completa el ajuste únicamente con la autorización requerida.
6. Conserva el folio del ajuste y el reporte generado.

## [REPL-01] Pedido eficiente disponible

1. Busca **Pedido eficiente disponible** en el área de mensajes entrantes de BOT.
2. Abre el mensaje.
3. Si BOT bloquea el proceso por recepciones CEDIS pendientes, termina primero esas recepciones.
4. Revisa Frutas, Verduras y carne, Pedido Normal e Insumos según aparezcan.
5. Usa búsqueda y los filtros **Todo** o **Solo prioritarios**.
6. Revisa sugerido, stock y pedido final; modifica únicamente cantidades autorizadas.
7. Selecciona **Confirmar pedido** una sola vez.
8. Espera la confirmación, conserva el folio y completa la impresión solicitada.

No cierres el día con un pedido eficiente pendiente si BOT lo muestra como bloqueo.

## [REPORT-01] Informes y PDF de BOT

BOT puede generar documentos para recepciones, transferencias, merma, inventario, pedido eficiente, cierre de turno y cierre del día.

- Revisa el documento o vista previa antes de imprimir.
- Durante **Preparando impresión** o **Buscando impresora disponible**, espera sin repetir.
- **Impresión enviada** significa que el documento fue enviado; confirma físicamente la salida.
- **Error de impresión** o **No se pudo procesar la impresión** requiere revisión física segura y, si persiste, soporte.
- Conserva el folio y no repitas el movimiento de negocio para obtener otra impresión.

BOT confirma que el cierre de turno imprime dos copias cuando muestra el mensaje correspondiente.

## [TOOLS-01] Herramientas integradas de BOT

1. Abre **Herramientas operativas** y selecciona únicamente una herramienta aprobada.
2. Espera **Inicializando Contenido ...** y **Cargando Contenido ...**.
3. Si la página queda en blanco, regresa a BOT mediante el control visible; no actualices repetidamente.
4. Si aparece **Se requiere reinicio del motor web** o **Ocurrió un error al inicializar el motor web**, conserva el trabajo actual y contacta a soporte autorizado.

No uses comandos, borres cachés ni cambies direcciones o configuración.

## [NAV-01] Tablas, búsqueda, diálogos y teclado

- Usa **Buscar** con clave, código de barras o descripción según el campo visible.
- En tablas con varias páginas usa **Anterior**, **Siguiente** o **Ir a página**.
- Antes de aceptar un diálogo de reemplazo, cancelación, cierre o ajuste, lee qué información será sustituida o finalizada.
- Usa **F1**, **Enter** o **Esc** solamente cuando la pantalla muestre esa tecla como acceso directo.
- Si el foco no está en el campo correcto, selecciónalo con el mouse o navegación visible antes de escribir.

## [LINUX-01] Reinicio seguro de POS o BOT

Reiniciar la aplicación es el último paso de tienda, no la primera respuesta.

No reinicies cuando haya un pago, impresión, importación, comparación, recepción, transferencia, pedido, ajuste o cierre procesándose. Si la pantalla está inmóvil y no existe un resultado verificable, conserva hora y folio y contacta a soporte antes de reiniciar. Nunca reinicies Linux, servicios o procesos mediante comandos como parte de esta guía.

## [ESC-01] Información para soporte autorizado

Conserva solamente información operativa segura:

- POS o BOT.
- Tienda y caja o terminal.
- Versión visible.
- Fecha y hora aproximada.
- Pantalla y paso realizado.
- Mensaje exacto.
- Folio, ticket o autorización, si existe.
- Estado visible del POS, BOT, terminal de pago, impresora o Zebra.
- Fotografía o captura sanitizada, sin clientes, credenciales ni datos de pago.

Nunca compartas contraseñas, NIP, tokens, números completos de tarjeta, códigos de seguridad ni información personal del cliente.

## [FAQ-01] Preguntas frecuentes

**¿Dónde cargo el catálogo de productos?**  
No se carga manualmente. BOT recibe las actualizaciones automáticamente.

**La terminal aprobó, pero POS sigue procesando. ¿Cobro otra vez?**  
No. Conserva la evidencia visible y contacta a soporte autorizado antes de repetir.

**¿Puedo renombrar los archivos del Zebra?**  
No. Importa los archivos generados sin editar ni renombrar.

**¿Qué archivo corresponde a piso y cuál a bodega?**  
Piso de venta termina en `_1.txt`; Bodega termina en `_0.txt`.

**BOT dice que el documento fue enviado, pero no salió papel.**  
No repitas la operación de negocio. Revisa energía, conexión accesible y papel; después usa la opción de impresión o reimpresión autorizada.

**¿Puedo usar comandos de Linux para arreglar POS, BOT, impresora o Zebra?**  
No. Contacta a soporte autorizado.

**¿Puede el asistente explicar eventos, configuraciones o código?**  
No. Este asistente cubre únicamente la operación visible de tienda en Linux.

## [QA-01] Pendientes antes de publicar

- Validar cada procedimiento en QA Linux con datos sembrados.
- Confirmar roles y permisos por acción.
- Confirmar cuándo una impresión es automática, manual y cuántas copias produce.
- Confirmar los estados visibles reales de impresora y dispositivos.
- Confirmar límites de reintento de autenticación y pagos.
- Agregar capturas sanitizadas en español y sus equivalentes en inglés.
- Registrar fecha de verificación y aprobación del dueño de producto.
