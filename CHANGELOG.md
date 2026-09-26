# Historial de versiones

Esquema: `alfa vMAYOR.MENOR.PARCHE`

* **MENOR** sube con cada función nueva visible.
* **PARCHE** sube con correcciones.
* **MAYOR** llega a 1 cuando la temporada corra completa sin intervención.

La versión se muestra junto a la marca en el portal y vive en
`quiniela/render_html.py` (`VERSION`).

## alfa v0.17.0

* **La semana se puede cargar en las partes que sea.** Antes, una hoja que
  repetía algunos partidos ya cargados y omitía otros se rechazaba. Ahora
  cualquier hoja parcial **suma**: agrega los partidos que falten, de los que
  repite se queda con lo nuevo (si no han empezado) y lo que no trae se
  conserva. Así se puede mandar el jueves el miércoles, el resto el sábado, y si
  a una hoja se le olvidó un partido, después solo ese; o mandar solo los
  partidos que haya que corregir.

  Los candados no cambian: ningún pick de un partido ya empezado cambia,
  aparece ni desaparece, y para sumar los participantes tienen que ser los
  mismos. La hoja completa sigue reemplazando la semana.

## alfa v0.16.2

* **La imagen de picks salía vacía en la semana 3.** Desde la v0.14.0, con la
  semana a medias, el generador ofrece los partidos que faltan por repartir,
  pero la imagen seguía cruzando los picks con los partidos ya cargados (solo
  el del jueves): salía "0 PICKS", sin renglones, y se veía cortada. El
  contador tenía el mismo error ("5 de 1 elegidos"). Ahora los dos salen de los
  partidos que ofrece el generador, y el borrador guardado ya no cuenta picks de
  partidos que dejaron de ofrecerse. Hay prueba para que no vuelva.
* `herramientas/llaves.py --help` tronaba: el enlace del formulario del token
  traía un `%` que argparse toma como formato. Ahora `token` muestra ese enlace
  al correr, antes de pedir el token.
* `herramientas/llaves.py token` tronaba con `CERTIFICATE_VERIFY_FAILED` en el
  Python de python.org para Mac, que no trae certificados hasta instalarlos
  aparte. Ahora usa los de `certifi` o los de macOS (`/etc/ssl/cert.pem`), sin
  dejar de validarlos, y un problema de conexión se explica en vez de soltar un
  traceback. Probado con los cuatro Python de la Mac.

## alfa v0.16.1

* Página del enlace: los rótulos chicos van en mayúsculas, como en el portal (la
  fuente recortada no tiene minúsculas), y un envío que no se pudo revisar dice
  "No se cargó" en vez de "No se subió", que contradecía al texto de abajo.
* `herramientas/llaves.py token` comprueba el token con una escritura inofensiva
  (habilitar el workflow de carga, que ya lo está): un token que solo puede leer
  se descubre al guardarlo. Usa solo la biblioteca estándar, así que corre con el
  `python3` del sistema, y el token nunca pasa por la línea de comandos.

## alfa v0.16.0

* **Carga por enlace, sin cuenta de nada.** Quien carga la semana recibe su
  propio enlace; lo abre en el teléfono, elige el archivo y la página le dice
  cómo quedó, con lo que cambió o lo que hay que corregir. Solo quien tiene el
  enlace puede cargar, y cada enlace se anula por separado.

  Como el portal no tiene servidor, el archivo lo recibe una función de
  Supabase (`angabave-carga`, en el proyecto de la app pero aparte: su cubeta,
  sus secretos, ninguna tabla). La función comprueba la llave, guarda el
  archivo y le pide a GitHub que lo revise con la misma puerta de siempre,
  `quiniela/carga.py`; el resultado vuelve a la página.

  La llave va después del `#`, que nunca viaja al servidor del portal ni a la
  vista previa de WhatsApp, y no se guarda en ningún lado: solo su huella. El
  token con que la función llama a GitHub solo puede correr workflows de este
  repo. La página solo puede hablar con la función.

* `herramientas/llaves.py` crea, lista y anula enlaces, y guarda el token.

* La forma de Issues sigue, para quien sí tiene cuenta de GitHub.

## alfa v0.15.0

* **El organizador carga la semana él mismo.** Hay una forma en GitHub, "Cargar
  semana", donde adjunta el archivo tal como lo reparte —Excel o PDF, la semana
  completa o una tanda— desde el teléfono o la computadora. En uno o dos
  minutos le contesta en el mismo hilo: o quedó publicado y qué cambió, o qué
  corregir, sin tocar nada. No necesita acceso al repo; solo pueden usarla las
  cuentas de `data/cargadores.json`, reconocidas por su número de cuenta.

* **Una sola puerta para los picks** (`quiniela/carga.py`), la misma para la
  forma y para `importar`. Revisa que el archivo sea lo que dice ser (sin
  contraseña, sin .xls viejo, sin zips tramposos, 10 MB como máximo), todo lo
  del lector, de qué semana es, que no se salte ninguna, que cada partido exista
  esa semana con local y visitante en su lugar, cómo encaja con lo que ya
  estaba y que no cambie ni un pick de un partido que ya empezó. Avisa de
  nombres nuevos, ausentes o parecidos a otros.

  La semana se guarda siempre en la rejilla de siempre, escrita por el propio
  programa y vuelta a leer para comprobarla, y en **un solo archivo**: si había
  PDF, se quita. La tanda del domingo se junta sola con la del jueves.

* **Tres huecos cerrados** que la carga habría vuelto frecuentes:

  * **Los sellos no se subían.** Los workflows los calculaban en la nube y se
    perdían al terminar; solo valían los sellados desde la Mac. Ahora se suben
    con el sitio, y la carga además compara contra lo publicado.
  * **Un reintento podía deshacer una carga.** Cuando dos corridas chocaban, la
    segunda reintentaba con `reset --soft` y volvía a subir sus archivos viejos:
    en un repo de prueba, una carga del organizador quedó revertida a los picks
    anteriores. Ahora recalcula encima de lo publicado.
  * **La página no escapaba los nombres.** La plantilla se llama
    `index.html.j2` y el autoescape solo miraba `.html`, así que un nombre con
    código habría entrado tal cual. Ahora se escapa todo (la página sale
    idéntica byte por byte) y el lector rechaza nombres con signos raros,
    caracteres invisibles o más de 40 caracteres.

* Un partido capturado con local y visitante al revés ahora lo dice así.

## alfa v0.14.0

* **La semana puede llegar en partes.** El organizador manda la hoja del jueves
  aparte del resto, porque esa tanda cierra el miércoles y la del domingo el
  sábado. Ahora el proyecto lee esa hoja suelta y publica la semana con los
  partidos que ya tiene; cuando llega la hoja completa, la reemplaza sin más.

  Tres cosas tuvieron que ceder para eso:

  * **El margen de la columna de nombres ya no es un número fijo.** La hoja de
    una sola tanda viene centrada y los nombres empiezan pasados los 160 pt, no
    antes de los 110. Ahora el margen se deduce de la celda "Semana N", que es
    justo el encabezado de esa columna.
  * **Una hoja puede traer un solo partido.** La búsqueda del encabezado pedía
    al menos dos equipos por fila; ahora le basta uno, y lo que sostiene la
    búsqueda sigue siendo que las filas de visitantes y locales vengan pegadas
    y que todas sus celdas sean equipos válidos.
  * **El aviso de partidos que faltan se agrupa.** Con quince partidos por
    llegar eran quince líneas en cada corrida; ahora es una sola, y dice que
    seguramente es una tanda sin repartir.

* **El sello es por partido, no por semana.** Antes se congelaba la jornada
  entera en cuanto arrancaba el primer partido, y eso ya no corresponde a cómo
  cierra la quiniela: con el jueves jugado, los picks del domingo todavía se
  entregan hasta el sábado a las 23:59. Ahora cada partido se congela cuando
  arranca **ese** partido.

  Es más estricto donde importa y más fiel a las reglas: sigue siendo imposible
  cambiar el pick de un partido ya jugado —y el error dice cuál—, pero la
  segunda hoja de la semana entra sin pelear. Los sellos de las semanas 1 y 2 se
  convierten solos al formato nuevo, y solo si el archivo sigue siendo idéntico:
  si cambió, truena igual que antes.

## alfa v0.13.0

* **Los partidos van en el orden de la NFL**: por hora de inicio —jueves,
  domingo temprano, domingo tarde, domingo por la noche, lunes—, que es como
  publica la liga la jornada y como la lee todo el mundo.

  Antes la base era el orden del Excel del organizador, y ESPN devuelve un
  tercero distinto (en la Semana 2 pone el Giants @ Rams del lunes en primer
  lugar). Ahora el orden se fija en un solo sitio, al armar los datos, así que
  sale igual en "Quién le fue a quién", en la boleta de cada quien, en el
  generador de picks y en la imagen que se manda. Los partidos a la misma hora
  conservan el orden del archivo, para que no bailen de una semana a otra.

  La pestaña **Partidos** sigue con su propio criterio a propósito: primero lo
  que falta por jugarse.

* **Prueba nueva contra el error silencioso.** Reordenar los partidos obliga a
  reordenar los picks de cada quien con ellos; si se despegan, el conteo entero
  queda mal y no se nota a simple vista. Hay una prueba que arma una semana con
  los horarios al revés del archivo y verifica **pick por pick** —los 544 de
  esta semana— que cada quien conserva el suyo.

## alfa v0.12.1

* **El sitio ya no se queda pegado en una versión vieja.** GitHub Pages sirve
  el HTML con `cache-control: max-age=600` y esa cabecera no se puede cambiar
  publicando por rama, así que cualquiera podía estar diez minutos viendo una
  copia atrasada —justo en domingo, que es cuando importa—. Ahora se publica
  `version.json`, de unos cien bytes, y la página lo consulta sin caché cada
  minuto y medio: si detecta que el sitio se regeneró, se recarga sola con un
  parámetro nuevo para saltarse el caché.

## alfa v0.12.0

Generador de picks para la semana que todavía no se carga.

* **"Arma tu quiniela y mándala"**, donde antes solo había un letrero de
  "picks por cargar". Eliges los partidos que quieras —no tienen que ser todos—
  y el sitio genera una **imagen membretada** con tu nombre y tus picks.
* **Se comparte o se descarga** según el teléfono: en móvil abre el menú de
  compartir con la imagen adjunta; en escritorio la descarga. Y hay un enlace
  de correo a `quinielanfl@hotmail.com` con el asunto ya puesto.
* **Dice hasta cuándo se reciben.** Cada tanda muestra su cierre, calculado
  como las 23:59 del día anterior a su primer partido: la del jueves cierra el
  miércoles, la del domingo y el lunes cierra el sábado. Si ya pasó, lo marca
  en rojo.
* **Lo que elijas se guarda en tu navegador** mientras armas la quiniela, así
  que puedes cerrar y volver sin perderlo.
* **No sube ni registra nada.** La tabla la sigue armando el organizador con su
  compilado; esto solo produce la imagen para mandársela. Hay una prueba que
  falla si alguien mete un POST o un envío de formulario.

La imagen quedó en **192 KB**: el primer intento pesaba 1.7 MB por un degradado
de fondo que el PNG no comprime, y esta imagen está hecha para mandarse por
correo y por WhatsApp.

## alfa v0.11.0

Identidad visual: tipografía propia, jerarquía y movimiento que informa.

* **Tipografía propia.** El sitio usaba una sola familia, la del sistema, y por
  eso se sentía a panel de control y no a producto de deportes. Ahora los
  marcadores, las cifras y los rótulos van en **Oswald condensada** (SIL OFL),
  recortada a mayúsculas y dígitos: pesa **8 KB** y viaja incrustada en el
  HTML, así que el sitio sigue sin pedirle un archivo a nadie. Los nombres de
  los participantes siguen en la fuente del sistema a propósito: llevan
  minúsculas, que el recorte no incluye, y se partirían a media palabra.
* **Jerarquía.** Los marcadores, los puntos del podio y los montos crecieron de
  verdad. Antes todo pesaba lo mismo: el ganador de la semana se leía igual que
  una etiqueta.
* **El marcador avisa cuando cambia.** Si estabas viendo la pantalla en el
  momento de la anotación, no pasaba nada: ahora la tarjeta destella y la cifra
  pulsa un par de veces. Solo cuando el cambio se observa en vivo, no al
  cargar.
* **Las cifras cuentan hacia arriba** al entrar, en el podio y en tu resumen de
  la semana.
* **Invitación de primera visita.** Un chip gris que decía "Identifícate" no lo
  iba a ver nadie, y con él se perdía el modo jugador entero. Ahora la primera
  vez aparece una tarjeta que pregunta cuál de los 34 eres, con el selector a
  un toque. Se muestra una sola vez.

## alfa v0.10.0

Los escenarios dicen qué falta, no solo cuánto falta.

* **Cada fila dice qué resultado hace falta**: "Necesita que gane Giants",
  "Necesitan que ganen Rams y Chiefs". Sale del mismo cálculo que ya usaba
  `cli.py escenarios` para los partidos indispensables, ahora para los 34 de
  una sola pasada y publicado en el sitio.
* **Cuando ya está resuelto se dice así**: "Ya aseguraron el primer lugar,
  compartido". Sin porcentajes que interpretar.
* **Tu fila te habla de tú** y va resaltada: "Ya aseguraste el primer lugar",
  "Necesitas que gane Giants". El resto va en tercera persona.
* Todo en una línea por fila: la idea era que dijera más, no que ocupara más.

Los requisitos se calculan acumulando dos máscaras sobre los desenlaces
favorables de cada quien —los bits encendidos en todos y los apagados en
todos— en lugar de recorrer partido por partido, que multiplicaba el trabajo
por dieciséis.

## alfa v0.9.0

Escenarios agrupados: los empatados también cuando hay posibles ganadores.

* **Los posibles ganadores se agrupan por situación.** Con un partido por
  jugarse, seis personas compartían exactamente el mismo 100 % y salían como
  seis filas idénticas. Ahora es una sola fila —"6 empatados"— desplegable con
  los nombres, igual que en el podio y en el ganador de la semana.
* **Cada grupo explica qué significa su porcentaje**, que no es obvio:
  "Terminan primeros pase lo que pase, compartiendo el premio", "Solo le
  alcanza para empatar el primer lugar", "Gana solo en N y empata en M".
* La entrada dice cuántos desenlaces quedan en vez de cuántas combinaciones,
  que se lee mejor cuando falta un solo partido.

## alfa v0.8.0

* **Los partidos se ordenan por lo que importa.** Arriba lo que falta por
  jugarse —bajo "Por jugarse", o "Falta este" cuando queda uno solo— y abajo
  "Ya jugados", del más reciente al más viejo. Antes iban en orden cronológico
  puro, así que el único partido pendiente quedaba hasta el final.
* **Tu equipo se adelanta solo mientras su partido no haya terminado.** Ya
  cerrado no tiene por qué encabezar nada, y así no estorba el nuevo orden.
* **Los empatados dicen quiénes son.** Donde antes aparecía "31 empatados" sin
  más, ahora se despliega la lista con un toque: en el podio, en el ganador de
  la semana y en los ganadores por semana. Tu nombre va resaltado dentro de la
  lista.

## alfa v0.7.0

Encabezado más chico y fichas de jugador con sustancia.

* **El encabezado bajó de cuatro filas a tres.** Los dos selectores se
  guardaron tras un botón de identidad que muestra tus iniciales y a quién le
  vas; se abre con un toque y se cierra al tocar fuera o con Escape. Son 18 px
  menos de barra fija en un teléfono.
* **La ficha de jugador dejó de ser cuatro números.** Ahora cruza los picks de
  los 34 y dice:
  * su promedio por semana y a cuántos aciertos está del primer lugar;
  * su porcentaje de acierto sobre los partidos cerrados;
  * **su equipo consentido**, cuántas veces lo eligió y cuántas le salió;
  * **cuántas veces fue contra la mayoría** de la quiniela y cuántas de esas
    le funcionó, que es la estadística que de verdad retrata a alguien en una
    quiniela;
  * las barras por semana ahora llevan el número encima.

**Lo que se intentó y no se publicó:** que el encabezado se plegara solo al
hacer scroll. El CSS quedó escrito pero en las pruebas no se pudo confirmar que
surtiera efecto, así que se retiró en vez de publicar algo sin verificar.

## alfa v0.6.0

Una pasada crítica a la interfaz.

* **Quién subió y quién bajó.** Cada fila de la general lleva ▲ o ▼ con los
  lugares que se movió desde la semana pasada. Era lo que más le faltaba a una
  tabla de posiciones.
* **El podio vuelve a decir nombres.** Estaba mostrando "4 empatados" sin
  decir quiénes: el elemento más visible de la página era el menos informativo.
  Ahora enlista hasta seis y solo cuenta a partir de ahí.
* **Los partidos se agrupan por horario** —"Domingo 20 · 11:00", "Lunes 21 ·
  18:15"— como se vive la jornada, en vez de dieciséis tarjetas seguidas. Cada
  bloque avisa cuántos le faltan por cerrar.
* **Tu equipo tiene bloque propio** arriba. Antes se colaba entre los demás y
  rompía el orden cronológico, partiendo el bloque de las once en dos.
* **La tabla general deja de desbordarse.** Muestra las últimas cuatro semanas
  y el resto queda a un clic; si no, para diciembre serían veintitrés columnas.
* **En escenarios siempre te ves**, aunque vayas abajo del lugar doce.

## alfa v0.5.0

El PDF del organizador entra solo, y la tabla se protege.

* **`leer_picks` acepta PDF o Excel.** El archivo que reparte el organizador ya
  no necesita conversión previa: se lee su capa de texto y se reconstruye la
  rejilla exacta, sin OCR. Hay una prueba que verifica que el PDF y el Excel
  producen picks idénticos.
* **`cli.py importar`** guarda el archivo tal como llega ("Quiniela 3.pdf"),
  deduce de qué semana es y lo deja validado en `data/picks/`.
* **Picks sellados.** En cuanto arranca el primer partido de una semana se
  guarda la huella del archivo. Si cambia después, el cálculo truena en vez de
  publicar una tabla con picks retocados. Antes del arranque se siguen pudiendo
  corregir.
* **Aviso de rezago.** Si la tabla lleva más de 25 minutos sin recalcularse y
  hay partidos abiertos, el sitio lo dice. Una página que se ve perfecta con
  números viejos es peor que una que avisa.
* **El PNG lleva al ganador de la semana** y su premio, que es el dato que la
  gente comparte.
* **Detección de erratas en nombres.** Avisa si dos participantes se llaman
  casi igual y nunca coinciden en la misma semana: eso es una errata que
  partiría la temporada de alguien en dos. Los que sí coinciden —como Alberto y
  Beto Alvarez— se descartan solos.
* **El directo se encadena.** Duerme hasta el arranque del próximo partido y,
  si no le alcanza el tiempo del job, lanza el siguiente eslabón. Se detiene al
  cerrar el último partido o si el próximo está a más de 12 horas.
* De 100 a 132 pruebas: se agregaron las del CLI (que no tenía ninguna), las
  del PDF y las del sellado.

## alfa v0.4.2

* **Directo se sincroniza en cada vuelta.** Antes el job se quedaba con el
  código del momento en que arrancó: una corrección publicada a media tarde se
  habría perdido en la siguiente vuelta, y un Excel nuevo no habría entrado
  hasta reiniciarlo. Ahora cada vuelta parte de lo que está publicado, así que
  **subir el compilado de una semana entra en el directo sin reiniciar nada**.

## alfa v0.4.1

Arreglo de la publicación automática.

* **El cron de GitHub no disparó ni una vez** en la primera ventana de domingo:
  en repos nuevos las tareas programadas tardan en activarse y GitHub avisa que
  retrasa o descarta corridas cuando hay carga. Depender de que dispare 70
  veces una tarde era frágil.
* Nuevo workflow **Directo**: necesita arrancar una sola vez por ventana y se
  queda corriendo hasta 5 horas, recalculando cada 2 minutos y parando solo
  cuando cierra el último partido. Si el cron llega tarde, el resto de la tarde
  queda cubierta igual.
* **GitHub Pages pasa a publicar por rama** en lugar de por workflow: cada
  commit a `docs/` se ve de inmediato. Antes, los commits del bucle no habrían
  aparecido en el sitio hasta que el bucle terminara, horas después.
* Comando nuevo `python cli.py pendientes`, que dice cuántos partidos siguen
  abiertos. Es lo que usa el bucle para saber cuándo parar.

## alfa v0.4.0

Temas de equipo completos y comodidades de uso.

* **Tema completo por equipo**: elegir equipo ya no cambia un acento, cambia el
  fondo, las superficies, los bordes, el resplandor y las pastillas activas.
  Cada tema se genera mezclando el color del equipo con la base oscura y pasa
  una verificación de contraste; los 64 (32 equipos × casa/visita) la cumplen.
* **Tu partido al frente**: si elegiste equipo, su juego encabeza la lista de
  la semana con una cinta que lo marca.
* **Podio rediseñado**: en el teléfono es una lista compacta que se lee de un
  vistazo; en escritorio es una peana de verdad, con la plata a la izquierda,
  el oro al centro y más alto, y el bronce a la derecha.
* **Se queda donde estabas**: al recargar vuelve a la misma vista, la misma
  pestaña y la misma altura de la página.
* Pestañas con corredera deslizante, pegadas debajo del encabezado.
* Buscador en la tabla general y en la de la semana.
* Botón para volver arriba.
* La columna de nombres ya no se colapsa cuando la tabla se desborda.

## alfa v0.3.0

Rediseño completo y herramientas.

* Logo propio: escudo con balón, en el encabezado, como favicon y como icono
  de app al guardar el sitio en el teléfono (iOS y Android, con manifiesto).
* Marcador estilo transmisión: siglas y color de cada equipo, ganador marcado.
* **Modo equipo**: eliges tu equipo y el portal se tiñe con sus colores —los de
  casa si juega de local esa semana, los de visita si va de visitante.
* **Jugadores**: buscador entre los 34, ficha de cada quien con su línea por
  semana, su mejor semana y cuántas ha ganado, y un duelo para comparar a dos
  y ver en qué partidos difieren.
* Consenso en "quién le fue a quién": marca los partidos casi unánimes y los
  divididos.
* Todos los colores de equipo pasan por una verificación de contraste (WCAG
  4.5:1) contra el fondo: ninguno queda ilegible.

## alfa v0.2.0

Marcador en vivo.

* El navegador consulta los marcadores directo a ESPN cada 60 segundos, solo
  con la pestaña al frente y solo si la semana tiene partidos abiertos.
* La capa en vivo **nunca cierra un partido ni toca el conteo oficial**: eso lo
  decide CI. Si la consulta falla tres veces seguidas, se rinde y manda lo
  publicado. Así un error de la API jamás produce una tabla equivocada.
* El cron bajó de 15 a 5 minutos, que es el mínimo de GitHub Actions.
* El paso de publicación reintenta si otra corrida se le adelanta, en vez de
  fallar en rojo.

## alfa v0.1.0

Primera versión publicada.

* Lectura del Excel semanal, marcadores de ESPN, tabla de la semana y general.
* Podio, premios, ganadores por semana y escenarios.
* Modo jugador con memoria en el navegador.
* Publicación automática en GitHub Pages e imagen para WhatsApp.
