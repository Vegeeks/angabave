# Historial de versiones

Esquema: `alfa vMAYOR.MENOR.PARCHE`

* **MENOR** sube con cada función nueva visible.
* **PARCHE** sube con correcciones.
* **MAYOR** llega a 1 cuando la temporada corra completa sin intervención.

La versión se muestra junto a la marca en el portal y vive en
`quiniela/render_html.py` (`VERSION`).

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
