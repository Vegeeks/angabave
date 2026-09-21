# Historial de versiones

Esquema: `alfa vMAYOR.MENOR.PARCHE`

* **MENOR** sube con cada función nueva visible.
* **PARCHE** sube con correcciones.
* **MAYOR** llega a 1 cuando la temporada corra completa sin intervención.

La versión se muestra junto a la marca en el portal y vive en
`quiniela/render_html.py` (`VERSION`).

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
