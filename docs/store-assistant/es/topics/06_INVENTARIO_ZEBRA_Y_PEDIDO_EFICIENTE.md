# BOT Linux — inventario Zebra y pedido eficiente

**ID de página:** T2STORE-INVENTORY-ORDER-ES  
**Versión:** `v1.3.0`  
**Estado:** Borrador detallado; QA y capturas pendientes  
**Página hermana:** `T2STORE-INVENTORY-ORDER-EN`

## [INV-SCOPE] Alcance y advertencias

Esta página cubre el conteo de inventario con escáner Zebra, importación de Piso de venta y Bodega, sincronización con POS, comparación, reconteo, ajuste y pedido eficiente.

No se permite editar, renombrar, copiar manualmente, fabricar ni mover archivos mediante Linux. Toda transferencia se realiza desde los controles visibles de BOT.

## [INV-BEFORE] Antes de iniciar inventario

1. Confirma que BOT y POS pertenezcan a la misma tienda.
2. Revisa que el día operativo esté en el estado requerido.
3. Verifica que el escáner Zebra autorizado tenga carga.
4. Confirma que no exista otro conteo activo para el mismo alcance.
5. Determina el tipo visible: Facing, Grupo, Artículo, Regla 13 o Reconteo.
6. Coordina quién contará Piso de venta y quién contará Bodega.

No inicies si BOT está cargando datos operacionales o si no puede verificarse la comunicación con POS.

## [INV-RULE13] Regla 13

1. Abre **Inventario**.
2. Selecciona el flujo correspondiente a **Regla 13**.
3. En **Inicio de conteo de inventario**, revisa el alcance.
4. Selecciona **Ejecutar regla 13** una sola vez.
5. Espera; la pantalla advierte que el proceso puede tardar varios minutos.
6. Revisa el resultado: puede indicar que no hay productos con stock menor o igual a cero o mostrar cuántos encontró.

No cierres BOT ni vuelvas a ejecutar mientras está procesándose.

## [INV-SELECT-LAYOUT] Seleccionar el diseño de conteo

1. En **Tipo de inventario**, selecciona Facing, Grupo o Artículo según la tarea asignada.
2. Usa **Buscar** para ubicar el alcance correcto.
3. Revisa la selección antes de continuar.
4. Selecciona **Siguiente**.

No elijas un alcance parecido si el solicitado no aparece. Conserva el nombre esperado y escala.

## [INV-CONNECT-ZEBRA] Conectar Zebra

1. Conecta físicamente el escáner al equipo BOT mediante el cable aprobado.
2. Espera unos segundos a que el dispositivo complete su conexión visible.
3. Mantén BOT en la pantalla de inventario.
4. No abras carpetas de Linux ni busques archivos manualmente.

Si BOT muestra **No se encontró un dispositivo**, desconecta y reconecta físicamente una sola vez y vuelve a intentar desde la pantalla.

## [INV-DOWNLOAD] Descargar productos al Zebra

1. Confirma el tipo y alcance seleccionado.
2. Conecta Zebra.
3. Selecciona **Descargar** una sola vez.
4. No desconectes mientras procesa.
5. Espera **Descarga de archivo** y el texto que indica cuántos productos se descargaron correctamente.
6. Verifica en el flujo del escáner que la lista esté disponible antes de ir al piso.

Si aparece **Error de descarga**, realiza un nuevo intento solo después de reconectar físicamente y verificar que no haya otro proceso activo.

## [INV-ZEBRA-ERRORS] Errores visibles del Zebra

- **No se encontró un dispositivo:** reconecta una vez; después escala.
- **Ocurrió un error con el archivo:** no edites ni renombres; conserva el mensaje y escala.
- **No se encontró la herramienta adb:** no instales nada; es un caso de soporte autorizado.
- **Faltan permisos en el dispositivo:** no cambies permisos de Linux; reconecta y acepta únicamente una solicitud visible del dispositivo, si existe; si persiste, escala.
- **No se pudo descargar el archivo:** confirma conexión física y realiza como máximo un nuevo intento desde BOT.

## [INV-COUNT-FLOOR] Conteo de Piso de venta

1. Abre la lista descargada en el escáner.
2. Recorre el alcance físico indicado.
3. Captura cada producto y cantidad siguiendo el procedimiento del escáner.
4. Evita contar Bodega dentro de Piso de venta.
5. Revisa artículos omitidos o cantidades fuera de lo esperado antes de terminar.
6. Finaliza el conteo en el escáner para que genere su archivo.

El archivo de Piso de venta termina en `_1.txt`. No cambies ese nombre.

## [INV-COUNT-WAREHOUSE] Conteo de Bodega

1. Abre el conteo correspondiente en el escáner.
2. Recorre únicamente la Bodega.
3. Captura cada producto y cantidad.
4. Revisa antes de finalizar.
5. Finaliza para generar el archivo.

El archivo de Bodega termina en `_0.txt`. No cambies ese nombre.

## [INV-IMPORT-START] Iniciar importación

1. Regresa a BOT y conecta Zebra.
2. Abre **Conteo de inventario**.
3. Revisa **Archivos requeridos**.
4. Confirma si muestra **Piso de venta pendiente** y **Bodega pendiente**.
5. Selecciona **Importar archivo** una sola vez.

BOT busca los archivos generados. El usuario no debe elegir rutas ni copiar archivos manualmente.

## [INV-IMPORT-FLOOR] Importar Piso de venta

1. Espera que BOT identifique el archivo `_1.txt`.
2. Revisa la pregunta **¿Deseas importar ... artículos a este conteo de inventario?**.
3. Confirma que corresponda a Piso de venta y que la cantidad sea razonable.
4. Selecciona **Aceptar**.
5. Espera **Archivo importado correctamente** y **Piso de venta importado** con cantidad.

Si la cantidad es inesperada, cancela antes de aceptar y revisa el conteo físico.

## [INV-IMPORT-WAREHOUSE] Importar Bodega

1. Espera que BOT identifique el archivo `_0.txt`.
2. Confirma que corresponda a Bodega.
3. Revisa cantidad de artículos.
4. Selecciona **Aceptar**.
5. Espera **Bodega importada** con cantidad.

No utilices el archivo de Piso como Bodega ni viceversa.

## [INV-NO-FILES] No se encontraron archivos para importar

1. Confirma que ambos conteos se finalizaron en Zebra.
2. Confirma que el dispositivo conectado sea el usado para el conteo.
3. Reconecta una vez.
4. Selecciona **Importar archivo** una vez más.
5. Si sigue sin encontrarlos, no fabriques ni renombres archivos; escala.

## [INV-REPLACE] Reemplazar información ya importada

BOT puede mostrar **Ya existe información para Piso de venta**, **Ya existe información para Bodega** o **Reemplazar archivo**.

1. Identifica qué parte ya fue importada.
2. Compara cantidad anterior y nueva cuando estén visibles.
3. Selecciona **Cancelar** si no estás seguro.
4. Selecciona **Reemplazar** únicamente cuando el nuevo archivo es el reconteo correcto y la sustitución está autorizada.
5. Espera la nueva confirmación.

Reemplazar elimina de ese conteo la información anterior de esa parte; no es una acción de prueba.

## [INV-BOTH-READY] Confirmar ambos archivos

Antes de comparar, la pantalla debe mostrar Piso de venta y Bodega importados con sus cantidades. Si indica **Falta 1 archivo** o **Faltan 2 archivos**, no continúes al ajuste.

## [INV-SYNC] Sincronización con POS

1. Abre el paso **Sincronización** o **Validar información de inventario**.
2. Lee el aviso de verificar que las ventas estén actualizadas.
3. Inicia la validación una sola vez.
4. Espera **Validando conexión con punto de venta**.
5. No cierres BOT, POS ni desconectes Zebra mientras el proceso está activo.

Si falla la validación, revisa la última conexión visible de POS y usa **Revalidar** una vez. Si persiste, escala.

## [INV-COMPARISON] Comparación

BOT compara el conteo del escáner con el inventario y descuenta las ventas registradas durante el conteo. El proceso puede tardar varios minutos.

- No repitas la importación.
- No realices un ajuste paralelo.
- Espera el resultado de diferencias.
- Si no hay diferencias, conserva la confirmación y cierra el flujo según la pantalla.

## [INV-DISCREPANCIES] Diferencias encontradas

1. Revisa la lista de productos con diferencias.
2. Usa los criterios visibles: diferencia de costo mayor a $100, diferencia de piezas mayor a 2 o ambas.
3. Selecciona únicamente los artículos que deben recontarse.
4. Imprime o utiliza la lista autorizada si la pantalla lo ofrece.
5. Realiza un nuevo conteo físico.

No cambies cantidades solo para igualar el sistema.

## [INV-RECOUNT] Reconteo

1. Selecciona **Reconteo**.
2. Descarga al Zebra la lista seleccionada cuando el flujo lo solicite.
3. Cuenta nuevamente Piso y Bodega según corresponda.
4. Importa sin editar los nuevos archivos.
5. Confirma cualquier reemplazo únicamente para la parte recontada.
6. Vuelve a ejecutar la comparación.

## [INV-ADJUSTMENT] Ajuste de inventario

1. Revisa diferencias finales después del reconteo.
2. Obtén la autorización requerida.
3. Selecciona **Ajuste de inventario** una sola vez.
4. Espera el mensaje de éxito y folio.
5. Revisa cuántos artículos se ajustaron.
6. Conserva folio y reporte.

Si no aparece folio, no repitas el ajuste. Conserva pantalla, hora, cantidades y estado POS/BOT y escala.

## [ORDER-NOTIFICATION] Localizar pedido eficiente

El aviso **Pedido eficiente disponible** aparece en el área de mensajes entrantes de BOT.

1. Revisa el inicio de BOT.
2. Abre el mensaje una sola vez.
3. Confirma que corresponda al día y tienda actuales.

No busques ni cargues un archivo para crear el pedido.

## [ORDER-BLOCKED] Pedido bloqueado por recepción pendiente

BOT puede listar **Recepción de mercancía** o **Transferencia** pendiente.

1. Anota la referencia mostrada.
2. Sal del pedido sin confirmarlo.
3. Completa la recepción o transferencia correcta.
4. Regresa al mensaje de pedido eficiente.

No cree una recepción nueva si ya existe una pendiente con la misma referencia.

## [ORDER-CATEGORIES] Categorías y filtros

El pedido puede incluir:

- **Frutas, Verduras y carne**.
- **Pedido Normal**.
- **Insumos**.

Usa búsqueda, **Todo**, **Solo prioritarios** u orden **Prioritarios** según la pantalla. Revisa cada categoría aunque no tenga artículos modificados.

## [ORDER-STOCK] Captura de stock

Cuando BOT habilite registro de stock:

1. Revisa producto, facing y ubicación.
2. Captura stock de Piso de venta y Bodega en los campos ofrecidos.
3. Verifica unidad, piezas, cajas o empaque.
4. Revisa el stock total y días de stock cuando aparezcan.
5. Continúa solo después de completar los campos obligatorios.

## [ORDER-QUANTITIES] Sugerido y pedido final

1. Compara **Sugerido** con **Pedido final**.
2. Revisa venta diaria, días de stock, empaque y cajas óptimas cuando aparezcan.
3. Modifica únicamente cantidades autorizadas.
4. Comprueba que la cantidad final tenga la unidad correcta.
5. Revisa el resumen de artículos automáticos y modificados.

## [ORDER-PRINT-LIST] Imprimir lista para preparar pedido

Usa **Imprimir lista de productos** cuando esté disponible. La lista puede corresponder a Insumos, Pedido Normal, registro de stock o pedido de frutas, verduras y carne. Durante la impresión no confirmes el pedido ni generes otra lista. La falta de papel no cambia las cantidades guardadas en pantalla.

## [ORDER-CONFIRM] Confirmar pedido

**Permiso:** se requiere autorización para confirmar la solicitud de reposición.

1. Abre **Resumen de pedido**.
2. Verifica total, automáticos, modificados, artículos y cajas.
3. Confirma que no haya categorías pendientes.
4. La persona autorizada confirma **Confirmar pedido** una sola vez.
5. Espera el mensaje de pedido generado.
6. Conserva folio y documento **Pedido eficiente enviado**.

No vuelva a confirmar por falta de impresión o demora visible.

## [ORDER-END-DAY] Pedido y cierre de día

Un pedido eficiente disponible sin procesar puede bloquear el cierre. Abre el elemento mostrado en **No es posible cerrar el día**, completa el pedido y regresa al cierre. No cierres BOT para omitirlo.

## [INV-ORDER-ESCALATE] Evidencia para soporte

Tienda, terminal, versión, tipo de inventario o categoría de pedido, pantalla, paso, hora, cantidades, archivos indicados solo por su nombre permitido, estado de Piso/Bodega, estado de conexión POS, folio y mensaje exacto. No adjuntes archivos de conteo a canales no autorizados.

## [INV-ORDER-FAQ] Respuestas rápidas

**¿Dónde edito el archivo del Zebra?** No se edita.

**¿Puedo renombrar `_1.txt` o `_0.txt`?** No.

**¿Cuál es Piso?** `_1.txt`.

**¿Cuál es Bodega?** `_0.txt`.

**¿Puedo importar solo uno y ajustar?** No; BOT debe mostrar ambos archivos requeridos como importados.

**¿Puedo confirmar dos veces el pedido?** No.

**¿Por qué no cierra el día?** Revisa si el pedido eficiente sigue pendiente.

## [INV-ORDER-QA] Pendientes de QA

- Capturar todos los errores Zebra en Linux.
- Confirmar nombres visibles de tipos de inventario.
- Verificar sustitución y reconteo con datos sembrados.
- Medir tiempos sin publicar límites hasta aprobación.
- Confirmar roles para ajuste y pedido.
- Capturar cada categoría, resumen, folio y bloqueo de cierre.

