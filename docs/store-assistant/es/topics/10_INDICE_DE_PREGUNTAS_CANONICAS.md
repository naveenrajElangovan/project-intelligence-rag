# Índice de preguntas canónicas — Tiendas 2.0 Linux

**ID de página:** T2STORE-QUESTIONS-ES  
**Versión:** `v1.3.0`  
**Estado:** Borrador detallado; QA pendiente  
**Página hermana:** `T2STORE-QUESTIONS-EN`

## [QUESTION-PURPOSE] Propósito

Este índice ayuda al asistente a reconocer diferentes formas de preguntar lo mismo y dirigir la respuesta a la sección operativa correcta. No sustituye el procedimiento enlazado. Antes de contestar, el asistente debe leer la sección de destino completa y respetar sus límites de reintento y escalamiento.

## [QUESTION-ROUTING-RULES] Reglas de selección

1. Responde en el idioma de la pregunta.
2. Distingue POS de BOT; si no es evidente, pregunta cuál aplicación está usando.
3. Prioriza el estado visible actual sobre la intención original.
4. Si existe pago, folio, ticket o movimiento ambiguo, aplica primero la regla de no repetir.
5. Si varias secciones aplican, inicia con la que evita pérdida, duplicidad o cobro doble.
6. Cita la página y el identificador exacto de la sección usada.
7. No completes vacíos con conocimiento técnico o general.

## [QUESTION-AUTH] Acceso, usuario y contraseña

Preguntas equivalentes:

- “No puedo entrar.”
- “Mi usuario no funciona.”
- “Dice credenciales inválidas.”
- “La contraseña está mal.”
- “Se quedó iniciando sesión.”
- “¿Puedo entrar sin internet?”
- “Mi autorización fuera de línea venció.”
- “Me pide cambiar contraseña.”
- “Olvidé mi contraseña.”
- “La sesión está bloqueada.”
- “¿Cómo desbloqueo?”

Rutas:

- Inicio normal: `T2STORE-AUTH`, `[AUTH-LOGIN-NORMAL]`.
- Rechazo y límite de intentos: `[AUTH-INVALID]`.
- Sin conexión o autorización vencida: `[AUTH-OFFLINE]`.
- Contraseña: `[AUTH-PASSWORD-WARNING]`, `[AUTH-PASSWORD-REQUIRED]`, `[AUTH-PASSWORD-FAILED]`.
- Bloqueo: `[AUTH-SESSION-LOCK]`, `[AUTH-SESSION-UNLOCK]`.
- Procesamiento: `[AUTH-PROCESSING]`.

## [QUESTION-PERMISSION] Permisos y autorización

Preguntas equivalentes:

- “No me deja hacerlo.”
- “El botón está deshabilitado.”
- “No aparece la opción.”
- “Me pide supervisor.”
- “¿Quién puede autorizar?”
- “La autorización fue rechazada.”
- “¿Puedo usar otro usuario?”

Rutas:

- Principio y roles: `T2STORE-ROLES`, `[ROLE-PRINCIPLE]`, `[ROLE-STORE-USER]`, `[ROLE-AUTHORIZER]`.
- Rechazo o ausencia: `[ROLE-PERMISSION-DENIED]`, `[ROLE-MISSING-MENU]`, `[ROLE-BUTTON-DISABLED]`.
- Autorización: `[ROLE-AUTHORIZATION-WAITING]`, `[ROLE-AUTHORIZATION-FAILED]`, `[ROLE-AUTHORIZATION-SUCCEEDED]`.

## [QUESTION-POS-START] POS, inicialización y turno

Preguntas equivalentes:

- “POS no inicia.”
- “POS se queda cargando.”
- “¿Cómo abro el turno?”
- “No recibí el fondo.”
- “El fondo no imprimió.”
- “Parece que ya hay un turno.”
- “¿Cómo agrego otro fondeo?”

Rutas:

- Inicio: `T2STORE-POSOPS`, `[POSOPS-START]`.
- Abrir turno: `[POSOPS-OPEN-SHIFT]`.
- Fondeo adicional: `[POSOPS-ADDITIONAL-FUNDING]`.
- Impresión del fondo: `T2STORE-PRINT`, `[PRINT-FUNDING]`.
- Duplicidad de turno: `T2STORE-ROLES`, `[ROLE-SHIFT-OWNERSHIP]`.

## [QUESTION-SALE] Productos, cantidades y venta

Preguntas equivalentes:

- “No lee el código.”
- “No encuentra el producto.”
- “¿Cómo busco por descripción?”
- “Puse una cantidad equivocada.”
- “¿Cómo multiplico piezas?”
- “Quiero consultar el precio.”
- “La venta quedó pendiente.”
- “No me deja terminar la venta.”

Rutas:

- Agregar o buscar: `T2STORE-POSOPS`, `[POSOPS-ADD-PRODUCT]`.
- Cantidad: `[POSOPS-QUANTITY]`.
- Consulta de precio: `[POSOPS-PRICE-CHECK]`.
- Venta pendiente: `[POSOPS-PENDING-SALE]`.
- Producto ausente: `T2STORE-TOOLS`, `[PRODUCT-MISSING]`.

## [QUESTION-CANCEL-RETURN] Cancelaciones y devoluciones

Preguntas equivalentes:

- “Quiero quitar un producto.”
- “Cancela toda la venta.”
- “El cliente quiere devolver.”
- “La devolución no imprimió.”
- “Se cerró después de cancelar.”
- “Me pide autorización para devolver.”

Rutas:

- Producto: `T2STORE-POSOPS`, `[POSOPS-CANCEL-PRODUCT]`.
- Venta completa: `[POSOPS-CANCEL-SALE]`.
- Devolución: `[POSOPS-RETURN]`.
- Documento: `T2STORE-PRINT`, `[PRINT-RETURN-CANCEL]`.
- Permiso: `T2STORE-ROLES`, `[ROLE-PROTECTED-ACTIONS]`.

## [QUESTION-PAYMENT-GENERAL] Pago en proceso o resultado desconocido

Preguntas equivalentes:

- “El pago se quedó procesando.”
- “No sé si cobró.”
- “El cliente dice que sí le descontó.”
- “POS regresó sin resultado.”
- “Se fue el internet al cobrar.”
- “¿Intento otra vez?”
- “Se imprimió comprobante pero POS no terminó.”

Ruta prioritaria: `T2STORE-PAY`, `[PAY-SCOPE]`, `[PAY-PROCESSING]`, `[PAY-AMBIGUOUS-CHECKLIST]`, `[PAY-RETRY]`.

Respuesta inmediata: no repetir el pago; conservar método, importe, hora, terminal, pantalla y comprobante permitido; verificar por el flujo aprobado o escalar.

## [QUESTION-CASH] Efectivo y pago mixto

Preguntas equivalentes:

- “¿Cómo cobro en efectivo?”
- “Capturé mal lo recibido.”
- “No muestra el cambio.”
- “El cajón no abrió después de cobrar.”
- “¿Puedo combinar pagos?”
- “Una parte pasó y otra no.”

Rutas:

- Efectivo: `T2STORE-PAY`, `[PAY-CASH]`.
- Mixto: `[PAY-MIXED]`.
- Cajón: `T2STORE-PRINT`, `[PRINT-CASH-DRAWER]`.
- Resultado parcial: `[PAY-AMBIGUOUS-CHECKLIST]`.

## [QUESTION-CARD] Tarjeta y Santander

Preguntas equivalentes:

- “La terminal no está disponible.”
- “No detecta la tarjeta.”
- “La tarjeta fue rechazada.”
- “La terminal aprobó pero POS no.”
- “Dice que no retire la tarjeta.”
- “Falló la conexión con la terminal.”
- “¿Cómo cancelo el pago con tarjeta?”
- “¿Cómo concilio el cobro?”

Rutas: `T2STORE-PAY`, `[PAY-CARD]`, `[PAY-PROCESSING]`, `[PAY-CARD-DECLINED]`, `[PAY-CARD-APPROVED-POS-PENDING]`, `[PAY-CANCEL]`, `[PAY-AMBIGUOUS-CHECKLIST]`.

## [QUESTION-CODI] CoDi

Preguntas equivalentes:

- “No aparece el QR.”
- “El QR no funciona.”
- “El cliente ya pagó.”
- “CoDi sigue esperando.”
- “CoDi venció.”
- “CoDi rechazado.”
- “Cancelé el QR.”
- “¿Genero otro código?”

Rutas: `T2STORE-PAY`, `[PAY-CODI]`, `[PAY-PROCESSING]`, `[PAY-CODI-DECLINED]`, `[PAY-CODI-TIMEOUT]`, `[PAY-CANCEL]`.

Si el cliente muestra cargo o aceptación, no generar otro QR.

## [QUESTION-VOUCHER] E-vale o vale

Preguntas equivalentes:

- “No detecta la tarjeta de vale.”
- “¿Cómo consulto saldo?”
- “No alcanza el saldo.”
- “El vale fue rechazado.”
- “Falló el proveedor.”
- “El dispositivo no responde.”
- “¿Puedo volver a pasarla?”

Rutas: `T2STORE-PAY`, `[PAY-EVALE]`, `[PAY-EVALE-NOT-DETECTED]`, `[PAY-EVALE-BALANCE]`, `[PAY-RETRY]`.

## [QUESTION-SERVICES] Servicios y tiempo aire

Preguntas equivalentes:

- “No se aplicó el pago del servicio.”
- “La recarga no llegó.”
- “Capturé mal el número.”
- “No salió el ticket de tiempo aire.”
- “El proveedor no respondió.”
- “¿Vuelvo a vender la recarga?”

Rutas: `T2STORE-PAY`, `[PAY-SERVICE]`, `[PAY-AIRTIME]`, `[PAY-AMBIGUOUS-CHECKLIST]`; impresión en `T2STORE-PRINT`, `[PRINT-SERVICE-AIRTIME]`.

No repetir una recarga o servicio con resultado ambiguo.

## [QUESTION-PRINT] Impresora, ticket y cajón

Preguntas equivalentes:

- “No imprime.”
- “Dice error de impresora.”
- “Salió en blanco.”
- “Solo imprimió una parte.”
- “Imprimió dos veces.”
- “¿Cómo reimprimo?”
- “BOT dice impresión enviada pero no salió.”
- “El cajón no abre.”

Rutas: `T2STORE-PRINT`, `[PRINT-PHYSICAL-CHECK]`, `[PRINT-POS-ERROR]`, `[PRINT-BOT-STATES]`, `[PRINT-REPRINT-SALE]`, `[PRINT-PARTIAL]`, `[PRINT-DUPLICATE]`, `[PRINT-BLANK]`, `[PRINT-CASH-DRAWER]`.

Primero confirmar el movimiento; nunca repetir venta, pago o movimiento solo para obtener papel.

## [QUESTION-BOT-DAY] BOT, tablero y día de tienda

Preguntas equivalentes:

- “BOT no termina de iniciar.”
- “¿Cómo inicio el día?”
- “Dice que ya existe un día.”
- “No veo una solicitud de POS.”
- “El tablero no se actualiza.”
- “No puedo cerrar el día.”
- “¿Qué pendientes bloquean el cierre?”

Rutas: `T2STORE-BOTOPS`, `[BOTOPS-START]`, `[BOTOPS-START-DAY]`, `[BOTOPS-DASHBOARD]`, `[BOTOPS-POS-REQUEST]`, `[BOTOPS-END-DAY-BLOCKERS]`, `[BOTOPS-END-DAY]`.

## [QUESTION-CASH-OPS] Efectivo, alivios y gastos

Preguntas equivalentes:

- “POS pidió fondo.”
- “¿Cómo autorizo un alivio?”
- “El alivio no aparece.”
- “¿Cómo registro un gasto?”
- “¿Cómo liquido el gasto?”
- “¿Cómo hago entrega de valores?”
- “Se perdió el folio del movimiento.”

Rutas:

- POS: `T2STORE-POSOPS`, `[POSOPS-ADDITIONAL-FUNDING]`, `[POSOPS-CASH-RELIEF]`, `[POSOPS-EXPENSE-WITHDRAWAL]`, `[POSOPS-EXPENSE-SETTLEMENT]`.
- BOT: `T2STORE-BOTOPS`, `[BOTOPS-INITIAL-FUND]`, `[BOTOPS-ADDITIONAL-FUND]`, `[BOTOPS-RELIEF]`, `[BOTOPS-EXPENSE]`, `[BOTOPS-CASH-DELIVERY]`.
- Impresión: `T2STORE-PRINT`, `[PRINT-FUNDING]`, `[PRINT-RELIEF]`, `[PRINT-EXPENSE]`.

## [QUESTION-MERCHANDISE] Recepción, transferencias y merma

Preguntas equivalentes:

- “¿Dónde recibo mercancía?”
- “Las cantidades no coinciden.”
- “Confirmé recepción y no imprimió.”
- “¿Cómo transfiero a otra tienda?”
- “No aparece la transferencia de entrada.”
- “¿Cómo registro merma?”
- “El movimiento quedó pendiente.”

Rutas: `T2STORE-BOTOPS`, `[BOTOPS-RECEIVE-SELECT]`, `[BOTOPS-RECEIVE-COUNT]`, `[BOTOPS-TRANSFER-OUT]`, `[BOTOPS-TRANSFER-IN]`, `[BOTOPS-SHRINKAGE]`; documentos en `T2STORE-PRINT`.

## [QUESTION-CATALOG] Catálogo, producto, precio y etiqueta

Preguntas equivalentes:

- “¿Dónde subo el catálogo?”
- “¿Cómo actualizo los productos?”
- “Llegó un producto nuevo y no aparece.”
- “El precio de POS no coincide.”
- “Hay cambios de precio pendientes.”
- “¿Cómo elijo formato o color?”
- “La etiqueta no imprimió.”
- “El cambio de precio bloquea el cierre.”

Rutas: `T2STORE-TOOLS`, `[PRODUCT-CATALOG-AUTO]`, `[PRODUCT-MISSING]`, `[PRODUCT-PRICE-DIFFERENCE]`, `[PRICE-NOTIFICATION]`, `[PRICE-FORMAT]`, `[PRICE-PREVIEW]`, `[PRICE-PAPER-COLOR]`, `[PRICE-END-DAY]`.

Respuesta clave: los usuarios de tienda no suben catálogos; BOT procesa las actualizaciones recibidas automáticamente.

## [QUESTION-INVENTORY] Inventario y Zebra

Preguntas equivalentes:

- “BOT no detecta el Zebra.”
- “¿Cómo descargo productos al escáner?”
- “¿Dónde cuento piso y bodega?”
- “No encuentra los archivos.”
- “¿Cuál archivo es piso?”
- “¿Puedo renombrar el archivo?”
- “¿Reemplazo lo importado?”
- “No sincroniza con POS.”
- “Hay diferencias en la comparación.”
- “¿Cómo hago el reconteo o ajuste?”

Rutas: `T2STORE-INVORDER`, `[INV-CONNECT-ZEBRA]`, `[INV-DOWNLOAD]`, `[INV-ZEBRA-ERRORS]`, `[INV-COUNT-FLOOR]`, `[INV-COUNT-WAREHOUSE]`, `[INV-IMPORT-FLOOR]`, `[INV-IMPORT-WAREHOUSE]`, `[INV-NO-FILES]`, `[INV-REPLACE]`, `[INV-SYNC]`, `[INV-COMPARISON]`, `[INV-RECOUNT]`, `[INV-ADJUSTMENT]`.

Nunca indicar edición, renombrado o manipulación manual de archivos.

## [QUESTION-ORDER] Pedido eficiente y reabasto

Preguntas equivalentes:

- “¿Dónde veo el reabasto?”
- “Dice Pedido eficiente disponible.”
- “No me deja abrir el pedido.”
- “Tengo recepción CEDIS pendiente.”
- “¿Cómo filtro prioridad?”
- “¿Qué es cantidad sugerida?”
- “¿Dónde capturo stock?”
- “¿Cómo confirmo el pedido?”
- “No obtuve folio.”
- “El pedido bloquea el cierre.”

Rutas: `T2STORE-INVORDER`, `[ORDER-NOTIFICATION]`, `[ORDER-BLOCKED]`, `[ORDER-CATEGORIES]`, `[ORDER-STOCK]`, `[ORDER-QUANTITIES]`, `[ORDER-PRINT-LIST]`, `[ORDER-CONFIRM]`, `[ORDER-END-DAY]`.

## [QUESTION-REPORTS-TOOLS] Reportes, PDF y herramientas integradas

Preguntas equivalentes:

- “El reporte no abre.”
- “El PDF está en blanco.”
- “Faltan páginas.”
- “No imprime el reporte.”
- “La herramienta de BOT queda cargando.”
- “Veo una página en blanco.”
- “La sesión de la herramienta venció.”
- “¿Cómo regreso a BOT?”

Rutas: `T2STORE-TOOLS`, `[PDF-GENERATION]`, `[PDF-FAILURE]`, `[TOOLS-OPEN]`, `[TOOLS-BLANK]`, `[TOOLS-INIT-ERROR]`, `[TOOLS-EXTERNAL-SESSION]`.

## [QUESTION-NAVIGATION] Búsqueda, tablas, diálogos y teclado

Preguntas equivalentes:

- “La búsqueda no encuentra.”
- “La tabla está vacía.”
- “¿Cómo cambio de página?”
- “No puedo seleccionar el renglón.”
- “Cerré un diálogo por error.”
- “¿Qué hace Atrás o Cancelar?”
- “El teclado no responde.”
- “¿Cuáles son los atajos?”

Rutas: `T2STORE-TOOLS`, `[TABLE-SEARCH]`, `[TABLE-EMPTY]`, `[TABLE-PAGINATION]`, `[DIALOG-CONFIRM]`, `[KEYBOARD]`.

No inventar atajos no confirmados en la pantalla liberada.

## [QUESTION-OFFLINE-SYNC] Sin conexión, guardado local y sincronización

Preguntas equivalentes:

- “Se fue el internet.”
- “¿Puedo seguir trabajando?”
- “¿Se guardó lo que hice?”
- “Falta información al iniciar.”
- “POS y BOT no coinciden.”
- “El movimiento no llega.”
- “¿Reinicio para sincronizar?”

Rutas: `T2STORE-AUTH`, `[AUTH-OFFLINE]`; documento maestro `T2.0-STORE`, `[SYNC-01]`; y `T2STORE-TOOLS`, `[TOOLS-INIT-ERROR]`, `[LINUX-RESTART]`.

No afirmar que una operación se guardó si no existe confirmación visible.

## [QUESTION-CLOSURE] Cierre de turno y cierre de día

Preguntas equivalentes:

- “No puedo cerrar turno.”
- “Hay una venta pendiente.”
- “BOT sigue esperando al POS.”
- “No puedo cerrar el día.”
- “El pedido o precios bloquean.”
- “Cerré pero no imprimió.”

Rutas:

- POS: `T2STORE-POSOPS`, `[POSOPS-CLOSE-SHIFT]`.
- BOT: `T2STORE-BOTOPS`, `[BOTOPS-SHIFT-CLOSE-REQUEST]`, `[BOTOPS-END-DAY-BLOCKERS]`, `[BOTOPS-END-DAY]`.
- Documentos: `T2STORE-PRINT`, `[PRINT-BOT-CLOSE]`.

No forzar el cierre ni omitir bloqueos.

## [QUESTION-FROZEN] Aplicación sin respuesta y reinicio Linux

Preguntas equivalentes:

- “POS se congeló.”
- “BOT no responde.”
- “La pantalla está en blanco.”
- “¿Puedo cerrar la aplicación?”
- “¿Puedo reiniciar la computadora?”
- “Dame un comando de Linux.”

Rutas: `T2STORE-TOOLS`, `[LINUX-BOUNDARY]`, `[LINUX-RESTART]`; para pago usar antes `T2STORE-PAY`, `[PAY-AMBIGUOUS-CHECKLIST]`.

No proporcionar comandos. Antes de cerrar, confirmar que no exista pago, impresión, importación, confirmación o cierre en proceso.

## [QUESTION-ESCALATION] Cuándo y cómo escalar

Preguntas equivalentes:

- “Nada de esto funciona.”
- “¿Qué datos mando a soporte?”
- “No hay guía para mi mensaje.”
- “La operación quedó en estado desconocido.”
- “¿Puedo enviarte una captura?”

Rutas: `T2STORE-SUPPORT`, `[SUPPORT-SEVERITY]`, `[SUPPORT-HANDOFF]`, `[SUPPORT-SCREENSHOT]`, `[SUPPORT-NO-EVIDENCE]`.

La escalación debe incluir solo información operativa sanitizada y nunca contraseñas, NIP, tarjeta completa, datos del cliente, secretos o archivos técnicos.

## [QUESTION-OUT-OF-SCOPE] Preguntas no relacionadas o técnicas

Preguntas equivalentes:

- “¿Cómo cambio la configuración?”
- “Muéstrame eventos, código o logs.”
- “¿Cómo entro a la base de datos?”
- “¿Cómo instalo o despliego?”
- “Dame la contraseña o un token.”
- “Ayúdame con Windows, Android o macOS.”
- Cualquier pregunta general no relacionada con la operación de tienda.

Ruta: `T2STORE-SUPPORT`, `[SUPPORT-OFF-TOPIC]`, `[SUPPORT-NO-EVIDENCE]`.

Redirige a acceso, ventas, pagos, impresión, mercancía, inventario, pedidos, efectivo o cierres de Tiendas 2.0 Linux.

## [QUESTION-QA] Validación del índice

Antes de publicar:

- Probar cada variante en español y su equivalente en inglés.
- Confirmar que la recuperación llega a la sección indicada y no a evidencia técnica.
- Añadir variantes reales observadas en soporte sin incluir datos personales.
- Verificar preguntas cortas, errores ortográficos comunes y mensajes exactos de pantalla.
- Confirmar que pagos ambiguos siempre producen una advertencia de no repetir.
- Confirmar que preguntas fuera de alcance no reciben conocimiento general.
