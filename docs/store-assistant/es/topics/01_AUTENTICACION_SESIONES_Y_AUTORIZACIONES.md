# Autenticación, sesiones y autorizaciones — POS y BOT Linux

**ID de página:** T2STORE-AUTH-ES  
**Versión:** `v1.3.0`  
**Estado:** Borrador detallado; QA y capturas pendientes  
**Aplicaciones:** POS y BOT en Linux  
**Página hermana:** `T2STORE-AUTH-EN`

## [AUTH-SCOPE] Alcance

Esta página responde preguntas de usuarios de tienda sobre acceso, contraseñas, sesiones bloqueadas y autorizaciones solicitadas dentro de POS o BOT. No proporciona recuperación técnica, administración de cuentas, configuración de red ni comandos de Linux.

Palabras que pueden usar los usuarios: *no puedo entrar*, *rechaza mi usuario*, *contraseña incorrecta*, *sesión bloqueada*, *me pide encargado*, *no tengo permiso*, *cambiar contraseña*, *contraseña vencida*, *sin internet*, *no avanza al iniciar sesión*.

## [AUTH-PREREQ] Información que debe confirmar el asistente

Antes de indicar pasos, pregunta o identifica:

1. ¿La persona está en POS o BOT?
2. ¿Ve la pantalla **Punto de Venta** o **Back Office Tienda**?
3. ¿Cuál es el texto exacto del mensaje?
4. ¿Está intentando entrar, desbloquear una sesión o autorizar una acción?
5. ¿La pantalla muestra una actualización de contraseña?
6. ¿Existe una operación en proceso que podría perderse al cerrar sesión?

Nunca solicites que la persona escriba o comparta su contraseña en el chat.

## [AUTH-LOGIN-NORMAL] Inicio de sesión normal

**Rol:** cualquier usuario habilitado para la aplicación.  
**Pantalla inicial:** encabezado **Punto de Venta** o **Back Office Tienda**, campos **Usuario** y **Contraseña**.  
**Controles visibles:** **Iniciar Sesión**; en algunas pantallas puede aparecer la tienda y la versión.

### Procedimiento

1. Confirma que la tienda mostrada sea la correcta.
2. Captura el usuario asignado a la persona que operará.
3. Captura la contraseña respetando mayúsculas y minúsculas.
4. Selecciona **Iniciar Sesión** una sola vez.
5. Mientras aparezca **Iniciando Sesión ...**, espera y no vuelvas a presionar el botón.
6. Cuando aparezca la pantalla principal, confirma que el nombre o rol corresponda al usuario esperado.

### Resultado correcto

La aplicación termina la carga y muestra las opciones permitidas para el usuario. Que una opción no aparezca puede ser una restricción de rol; no significa automáticamente que la aplicación esté dañada.

### No repetir

No presiones varias veces **Iniciar Sesión** mientras se muestra la carga. No pruebes contraseñas de otras personas.

### Escalamiento

Escala si la pantalla queda cargando, regresa al acceso sin explicación o rechaza nuevamente credenciales que la persona confirma como correctas. Conserva aplicación, tienda, terminal, versión visible, hora y mensaje; nunca la contraseña.

## [AUTH-INVALID] Usuario o contraseña no válidos

**Mensajes relacionados:**

- **No fue posible iniciar sesión. Intente nuevamente.**
- **Usuario o contraseña incorrectos.**
- **Usuario o contraseña no válidos. Intenta de nuevo.**

### Respuesta canónica

1. Verifica que no haya espacios agregados al inicio o al final del usuario.
2. Confirma visualmente el usuario, sin mostrar la contraseña.
3. Borra y captura de nuevo la contraseña una sola vez.
4. Si el mensaje vuelve a aparecer, detén los intentos y contacta a soporte autorizado.

### Lo que no debe decir el asistente

No debe afirmar si falló un servicio remoto, un directorio, un token o una base local. Esos motivos no son visibles para el usuario. Tampoco debe recomendar borrar información, cambiar archivos, reiniciar servicios ni usar la cuenta de un compañero.

## [AUTH-OFFLINE] Acceso cuando no hay conectividad

POS o BOT pueden permitir acceso sin conexión únicamente cuando ya existe una autorización local todavía válida. La disponibilidad depende del usuario y de la información guardada anteriormente.

### Procedimiento seguro

1. Intenta el acceso normal una vez.
2. Si la aplicación permite entrar, utiliza solamente las funciones que se mantengan habilitadas.
3. Lee cualquier aviso de operación limitada o información pendiente.
4. No asumas que pagos, sincronizaciones, recepciones o cierres funcionarán sin conexión.
5. Si el acceso se rechaza o la autorización expiró, conserva el mensaje y contacta a soporte.

### Prohibiciones

No cambies la fecha u hora del equipo. No modifiques la red, archivos, credenciales almacenadas ni configuración de Linux.

## [AUTH-PASSWORD-WARNING] Contraseña próxima a vencer

**Mensajes relacionados:** **Tu contraseña está por vencer** o **Tu contraseña está próxima a vencer**.

La pantalla indica los días restantes y permite actualizar ahora o continuar cuando el cambio todavía sea opcional.

### Procedimiento

1. Si la tienda está en medio de una operación urgente, utiliza **Continuar** únicamente cuando la pantalla lo permita.
2. Para actualizar, abre el formulario mostrado.
3. Captura **Nueva contraseña**.
4. Cumple cada requisito visible: longitud mínima indicada, una mayúscula, una minúscula y un número.
5. Repite exactamente el valor en **Confirmar contraseña**.
6. Selecciona **Actualizar contraseña** una sola vez.
7. Espera **Contraseña actualizada** y selecciona **Aceptar**.

El asistente no debe proponer una contraseña concreta ni pedir que el usuario se la muestre.

## [AUTH-PASSWORD-REQUIRED] Actualización obligatoria o contraseña expirada

**Mensajes relacionados:**

- **Actualización de contraseña requerida**.
- **Tu contraseña debe actualizarse para continuar.**
- **La contraseña ha expirado. Contacta a soporte para continuar.**

### Si el formulario permite actualizar

Completa los campos y requisitos mostrados. No cierres la aplicación durante el envío. Si falla, realiza como máximo un segundo intento después de revisar que ambos campos coincidan.

### Si la pantalla ordena contactar a soporte

Detén los intentos. No existe una recuperación autorizada para el usuario de tienda en esta guía. Informa aplicación, usuario sin contraseña, tienda, terminal, hora y mensaje exacto.

## [AUTH-PASSWORD-MISMATCH] Las contraseñas no coinciden

1. Vacía **Nueva contraseña** y **Confirmar contraseña**.
2. Captura el nuevo valor en ambos campos con cuidado.
3. Verifica los indicadores visibles de requisitos.
4. Envía una sola vez.

Este mensaje no confirma que la contraseña anterior sea incorrecta; únicamente indica que los dos nuevos valores no coinciden.

## [AUTH-PASSWORD-FAILED] No fue posible actualizar la contraseña

1. Confirma que ambos campos coincidan y cumplan todos los requisitos visibles.
2. Realiza un solo nuevo intento.
3. Si falla nuevamente, conserva el mensaje y escala.

No alternes repetidamente entre POS y BOT para cambiar la contraseña y no uses herramientas externas.

## [AUTH-SESSION-LOCK] Bloquear una sesión

La opción **Bloquear sesión** protege una caja o BOT temporalmente sin autorizar que otra persona opere con la sesión abierta.

1. Confirma que no haya un pago, impresión, recepción, transferencia, inventario, pedido o cierre procesándose.
2. Usa **Bloquear sesión** o el acceso directo visible.
3. Confirma que aparezca **Sesión bloqueada**.

Bloquear sesión no equivale a cerrar turno ni cerrar día.

## [AUTH-SESSION-UNLOCK] Desbloquear una sesión

**Pantalla:** **Sesión bloqueada** con campos de usuario y contraseña.

1. Captura las credenciales autorizadas solicitadas por la pantalla.
2. Confirma una sola vez.
3. Espera a que regrese la pantalla anterior.
4. Verifica que la operación previa conserve el estado esperado.

Si la pantalla exige cambio de contraseña, complétalo primero. Si no puede desbloquearse, usa **Cerrar Sesión** solo cuando esté disponible y no exista procesamiento activo; de lo contrario escala.

## [AUTH-LOGOUT] Cerrar sesión

1. Finaliza o cancela correctamente cualquier operación abierta.
2. En POS, confirma si también debe cerrarse el turno.
3. Selecciona **Salir / Cerrar sesión** o **Cerrar Sesión**.
4. Lee y confirma el diálogo cuando aparezca.
5. Verifica que regrese a la pantalla de acceso.

Cerrar la ventana de Linux no sustituye el cierre de sesión, turno o día.

## [AUTH-PERMISSION] Acción no permitida o autorización fallida

Una acción puede requerir un permiso específico o la autorización de otro rol.

### Procedimiento

1. Lee qué rol solicita la pantalla.
2. Cancela el diálogo si esa persona no está disponible; no pruebes cuentas al azar.
3. Cuando llegue la persona autorizada, debe capturar sus propias credenciales.
4. Confirma una sola vez y espera el resultado.
5. Si aparece **Autorización fallida, intente nuevamente**, verifica el rol y realiza solo un nuevo intento.

### Casos visibles conocidos

- Abrir turno puede rechazarse cuando el usuario no tiene permiso.
- Abrir cajón solicita al responsable de caja.
- Liquidar gastos puede exigir al usuario que abrió el turno.
- Un arqueo puede solicitar a un Gerente de Distrito.
- Cancelaciones, devoluciones, ajustes y movimientos pueden pedir autorización según la operación.

## [AUTH-DIFFERENT-USER] La aplicación solicita otro usuario

Si POS indica **El usuario es diferente al usuario conectado al POS**, no cambies automáticamente de cuenta. Lee la acción protegida y utiliza únicamente al usuario que el procedimiento autorizado requiera. Si no es claro quién debe autorizar, cancela sin completar la acción y escala.

## [AUTH-TERMINAL-CONFIG] Se requiere configuración del terminal

Si aparece **Se requiere la configuración del terminal para la autenticación**:

1. No intentes configurar el equipo.
2. No copies archivos desde otra caja.
3. Conserva tienda, caja o terminal, versión y mensaje exacto.
4. Contacta a soporte autorizado.

Este caso no tiene solución de usuario de tienda.

## [AUTH-PROCESSING] La pantalla permanece en “Iniciando Sesión”

1. Espera sin volver a seleccionar **Iniciar Sesión**.
2. Comprueba únicamente si la aplicación sigue mostrando cambios visibles.
3. No cierres la ventana si acaba de enviarse la solicitud.
4. Si permanece sin resultado y no hay una instrucción visible de reintento, registra la hora y contacta a soporte.

El tiempo exacto de espera debe validarse en QA antes de publicarse como una cifra.

## [AUTH-FAQ] Respuestas rápidas de autenticación

**¿Puedo usar la cuenta de otra persona?** No. Cada persona debe usar sus credenciales y las autorizaciones deben ser ingresadas por el responsable.

**¿Puedo decirle mi contraseña al asistente?** No. El asistente nunca necesita una contraseña.

**¿Bloquear sesión cierra el turno?** No.

**¿Puedo seguir trabajando si estoy sin conexión?** Solo con las opciones que la aplicación permita; no se garantiza que todas las funciones estén disponibles.

**¿Qué hago si mi contraseña expiró?** Sigue el formulario si está disponible. Si la pantalla ordena contactar a soporte, detén los intentos y escala.

**¿Puedo reiniciar Linux para entrar?** No como procedimiento de autenticación de tienda.

## [AUTH-ESCALATE] Evidencia segura para soporte

Proporciona: POS o BOT, tienda, caja o terminal, versión visible, fecha y hora, tipo de acción, usuario sin contraseña y texto exacto del mensaje. No proporciones contraseña, datos de clientes, tokens ni fotografías con información sensible.

## [AUTH-QA] Validación pendiente

- Confirmar el número autorizado de reintentos con el dueño de producto.
- Capturar acceso normal, rechazo, advertencia y cambio obligatorio en POS y BOT Linux.
- Confirmar qué roles pueden desbloquear cada aplicación.
- Confirmar comportamiento visible de acceso sin conexión.
- Confirmar todas las acciones que solicitan autorización y el texto del rol.

