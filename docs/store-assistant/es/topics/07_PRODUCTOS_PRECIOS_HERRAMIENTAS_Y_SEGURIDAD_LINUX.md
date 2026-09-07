# BOT Linux — productos, precios, herramientas y operación segura

**ID de página:** T2STORE-BOT-TOOLS-ES  
**Versión:** `v1.3.0`  
**Estado:** Borrador detallado; QA y capturas pendientes  
**Página hermana:** `T2STORE-BOT-TOOLS-EN`

## [TOOLS-SCOPE] Alcance

Esta página cubre búsqueda de productos, catálogo automático, cambio de precios, configuración e impresión de etiquetas, tablas, navegación, herramientas integradas, documentos PDF y límites seguros de operación en Linux.

## [PRODUCT-CATALOG-AUTO] Cómo se actualizan los productos

BOT recibe y procesa automáticamente la información de productos y precios durante la inicialización y cuando llegan actualizaciones disponibles.

- El usuario de tienda no carga un catálogo.
- No existe un procedimiento autorizado para crear, reemplazar o editar archivos de productos.
- Una actualización puede reflejar productos nuevos, cambios, bajas o nuevos precios.
- Espera a que termine la inicialización antes de concluir que falta información.

## [PRODUCT-MISSING] Producto no encontrado

1. Confirma que estás en la tienda correcta.
2. Espera que BOT termine de cargar.
3. Busca por clave, código de barras y descripción cuando esos campos estén disponibles.
4. Revisa filtros activos y cámbialos a **Todos** cuando proceda.
5. Confirma si el producto aparece en POS.
6. Si continúa ausente, conserva clave, código, descripción, hora y pantallas de ambos sistemas y escala.

No selecciones un producto parecido ni intentes crearlo manualmente.

## [PRODUCT-PRICE-DIFFERENCE] Precio distinto entre POS, BOT y etiqueta

1. Identifica el producto exacto mediante clave y código de barras.
2. Anota el precio mostrado en POS.
3. Anota **Precio actual** y **Precio nuevo** en BOT cuando aparezcan.
4. Revisa si existe trabajo pendiente en **Impresión de precios**.
5. No cambies el precio manualmente ni finalices una impresión no realizada.
6. Escala si la diferencia persiste después de completar el flujo autorizado.

## [PRICE-NOTIFICATION] Productos que requieren actualización de precio

BOT puede indicar cuántos productos deben actualizarse.

1. Abre **Impresión cambio precios** o **Impresión de precios**.
2. Revisa el total de productos.
3. Identifica productos nuevos y cambios de precio.
4. Revisa si existen grupos o momentos de impresión separados.
5. Completa cada grupo antes de marcar terminado.

El cierre de día puede permanecer bloqueado hasta completar este trabajo.

## [PRICE-FORMAT] Elegir formato

Los formatos visibles pueden incluir:

- **Grande — 8 cenefas por hoja**.
- **Chico — 16 cenefas por hoja**.
- **Señalización — hoja completa**.

1. Selecciona el formato indicado por el procedimiento comercial.
2. Revisa estado, tipo, facing, flecha, tachado y tamaño cuando aparezcan.
3. Usa **Previsualizar configuración**.
4. Aplica cambios únicamente a los productos seleccionados o a todos cuando el diálogo lo diga claramente.

## [PRICE-PER-PRODUCT] Configuración por producto

1. Selecciona el producto exacto.
2. Abre **Edición de impresión por producto**.
3. Revisa si el ajuste aplica solo a esta impresión o modifica la configuración.
4. Selecciona flecha, formato u opciones visibles.
5. Usa **Guardar Configuración** una sola vez.
6. Espera **Configuración guardada**.

Si aparece **Error al guardar configuración**, realiza un nuevo intento solo después de revisar los campos. Si persiste, escala.

## [PRICE-PREVIEW] Previsualización

1. Abre **Previsualización de impresión**.
2. Revisa descripción, precio, flecha, tachado, tamaño y color.
3. Usa **Anterior**, **Siguiente** o **Ir a página** para revisar todas las páginas.
4. Corrige antes de imprimir.

La previsualización no significa que el documento haya sido impreso.

## [PRICE-PAPER-COLOR] Impresión por color

BOT puede separar:

- Hojas azules para Nuevos, In & Out y Temporales.
- Hojas amarillas para productos del catálogo.
- Hojas blancas para productos de farmacia.

Sigue siempre el mensaje visible de la tienda:

1. Coloca el papel indicado.
2. Confirma el número de hojas.
3. Selecciona **Imprimir** una vez.
4. Espera el estado enviado.
5. Revisa físicamente la salida.
6. Selecciona **Terminar** solo cuando el grupo esté completo.

## [PRICE-END-DAY] Impresión de precios bloquea cierre

Si **No es posible cerrar el día** lista **Impresión de precios**:

1. Abre ese elemento.
2. Revisa productos y páginas pendientes.
3. Completa o resuelve la impresión conforme a la pantalla.
4. Regresa a **Cierre de día**.

No cierres BOT para quitar el bloqueo.

## [TABLE-SEARCH] Buscar dentro de una tabla

1. Lee el texto del campo de búsqueda.
2. Usa clave, código de barras, descripción u otro dato que solicite la pantalla.
3. Borra filtros anteriores si no aparecen resultados.
4. Espera que la tabla termine de actualizar.
5. Confirma el producto o movimiento por más de un dato antes de seleccionarlo.

## [TABLE-EMPTY] Tabla o lista vacía

Una lista vacía puede significar que no hay elementos para el filtro, no que exista una falla.

1. Revisa filtros y página actual.
2. Cambia a **Todos** cuando esté disponible.
3. Limpia búsqueda.
4. Confirma fecha o estado del proceso.
5. Si debería existir un elemento confirmado, conserva su folio y escala.

## [TABLE-PAGINATION] Paginación

- Usa **Anterior** y **Siguiente** para recorrer resultados.
- En **Ir a página**, captura únicamente un número dentro del total mostrado.
- Revisa todas las páginas antes de afirmar que un producto o movimiento no existe.
- No cambies página mientras una confirmación esté procesándose.

## [DIALOG-CONFIRM] Diálogos de confirmación

Antes de seleccionar **Aceptar**, **Aplicar**, **Reemplazar**, **Confirmar** o **Finalizar**:

1. Lee el título y la descripción completa.
2. Identifica qué se creará, modificará, reemplazará o cerrará.
3. Verifica importe, productos, cantidades y alcance.
4. Si no estás seguro, usa **Cancelar** o **Atrás**.

No utilices una confirmación para probar qué ocurre.

## [KEYBOARD] Teclado y foco

- **F1** puede aceptar cuando aparece junto al botón.
- **Enter** puede continuar o enviar cuando la pantalla lo indique.
- **Esc** puede cancelar o regresar cuando aparezca visible.
- Las letras de atajo como **D**, **C** o **I** se usan únicamente en la pantalla que las muestra.
- Si el cursor no está en el campo correcto, selecciónalo antes de escribir.

No memorices un atajo de otra pantalla como si fuera global.

## [TOOLS-OPEN] Abrir herramientas operativas

1. Selecciona **Herramientas operativas**.
2. Elige únicamente una herramienta aprobada para tu función.
3. Espera **Inicializando Contenido ...**.
4. Después espera **Cargando Contenido ...**.
5. Realiza la actividad dentro de la herramienta.
6. Regresa mediante el control visible de BOT.

No cambies la dirección, configuración ni motor de contenido.

## [TOOLS-BLANK] Herramienta en blanco o sin contenido

1. Espera a que finalicen los mensajes de carga.
2. No actualices repetidamente.
3. Usa el control visible para regresar a BOT.
4. Abre una sola vez de nuevo si no había operación en curso.
5. Si continúa en blanco, conserva nombre de herramienta, hora y pantalla y escala.

## [TOOLS-INIT-ERROR] Error al inicializar contenido

**Mensajes relacionados:**

- **Se requiere reinicio del motor web.**
- **Ocurrió un error al inicializar el motor web.**

Respuesta de tienda:

1. No borres cachés ni archivos.
2. No uses comandos.
3. Regresa a BOT si el control está disponible.
4. Conserva trabajo pendiente y mensaje.
5. Contacta a soporte autorizado.

La palabra “reinicio” del mensaje no autoriza reiniciar Linux.

## [TOOLS-EXTERNAL-SESSION] Herramienta solicita acceso o sesión

Utiliza únicamente la cuenta oficial asignada para esa herramienta. El asistente de Tiendas 2.0 no restablece credenciales de servicios externos. No guardes contraseñas en campos no reconocidos. Si el acceso falla, identifica la herramienta y contacta al soporte autorizado correspondiente.

## [PDF-GENERATION] Generar y revisar reportes

BOT puede preparar reportes de productos, recepción, transferencias, merma, inventario, pedido, turno y día.

1. Completa el movimiento y espera el folio cuando corresponda.
2. Abre **Reportes**, **Previsualizar** o el control visible.
3. Revisa encabezado, tienda, fecha, folio, totales y páginas.
4. Imprime una sola vez.
5. Conserva todas las páginas.

No repitas el movimiento para volver a generar un PDF.

## [PDF-FAILURE] Reporte no abre o no se imprime

1. Confirma si el movimiento ya tiene folio.
2. Si tiene folio, no repitas el movimiento.
3. Intenta abrir la vista previa una vez más solo si BOT ofrece el control.
4. Para error de impresión, aplica la guía de impresora.
5. Si el PDF sigue sin abrir, conserva folio, nombre del reporte y hora y escala.

## [LINUX-BOUNDARY] Acciones permitidas y prohibidas en Linux

### Permitido

- Usar controles visibles de POS/BOT.
- Revisar energía, papel y cables accesibles.
- Reconectar Zebra una vez.
- Cerrar y abrir la aplicación solo con autorización y sin operación activa.
- Capturar una evidencia sanitizada.

### Prohibido

- Abrir terminal y ejecutar comandos.
- Editar o mover archivos.
- Instalar programas, herramientas o controladores.
- Cambiar permisos, servicios, procesos, red, reloj o configuración.
- Borrar caché, datos o base local.
- Usar credenciales técnicas.

## [LINUX-RESTART] Decidir si puede reiniciarse la aplicación

No cierres ni reinicies durante pagos, importación Zebra, comparación, impresión, recepción, transferencia, merma, pedido, ajuste, cierre de turno o cierre de día.

Si no hay operación activa y el procedimiento autorizado lo permite:

1. Registra pantalla y hora.
2. Cierra mediante el control de la aplicación.
3. Ábrela desde su acceso normal.
4. Verifica tienda, versión, sesión y estado anterior.

Si hay duda, escala antes de cerrar.

## [TOOLS-FAQ] Respuestas rápidas

**¿Dónde subo productos?** En ningún lugar; la actualización es automática.

**¿Puedo editar un precio?** Solo mediante opciones visibles y autorizadas; nunca en archivos.

**¿Qué hago con una página BOT en blanco?** Regresa, prueba una vez y escala si persiste.

**¿“Reinicio del motor” significa reiniciar Linux?** No.

**¿Una vista previa significa impreso?** No.

## [TOOLS-ESCALATE] Datos para escalar

BOT o POS, tienda, terminal, versión, producto o herramienta, clave/código cuando aplique, pantalla, filtro, página, paso, folio, fecha, hora y mensaje. Captura sin nombres, credenciales, clientes ni datos de pago.

## [TOOLS-QA] Pendientes de QA

- Confirmar herramientas visibles por rol.
- Capturar estados de carga, vacío y error.
- Validar formatos y colores de etiquetas.
- Confirmar bloqueos de impresión de precios.
- Verificar todos los reportes y páginas.
- Confirmar atajos por pantalla en Linux.

