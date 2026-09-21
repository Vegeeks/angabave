# ANGABAVE · Quiniela NFL 2026

Portal de la quiniela. Lee el Excel semanal de picks, jala los marcadores
reales de ESPN, calcula las tablas y los premios, y publica todo como un sitio
estático y como una imagen lista para WhatsApp.

El trabajo semanal se reduce a subir el Excel a `data/picks/`. Lo demás corre
solo: GitHub Actions recalcula cada 15 minutos durante los partidos.

Versión **alfa v0.9.0**. El historial está en [CHANGELOG.md](CHANGELOG.md).

## Instalación

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Requiere Python 3.11 o superior. No hay base de datos ni servidor: todo vive en
archivos dentro del repo.

## Uso

```bash
python cli.py actualizar --semana 2            # jala marcadores y regenera docs/
python cli.py actualizar --semana 2 --sin-red  # solo usa el caché, no toca la red
python cli.py tabla --semana 2                 # tabla de la semana en la terminal
python cli.py general                          # tabla acumulada en la terminal
python cli.py escenarios --participante "Angel D Luffy"
python cli.py validar --semana 2               # solo revisa el Excel, no calcula
```

Si omites `--semana`, se usa la última semana con archivo de picks.

Flujo semanal:

1. Guarda el Excel del organizador como `data/picks/Semana_NN.xlsx`.
2. Corre `python cli.py validar --semana NN`. Si el archivo trae algo raro, aquí
   te enteras, antes de calcular nada.
3. Haz commit y push. GitHub Actions se encarga del resto durante los partidos.

## El archivo de picks

Se acepta **Excel o PDF**. El organizador arma la quiniela en Excel pero suele
repartir el PDF exportado: ese PDF conserva la capa de texto, así que se lee la
rejilla exacta sin OCR ni transcribir a mano. Hay una prueba que verifica que
los dos formatos producen exactamente los mismos picks.

Para guardarlo con el nombre que espera el proyecto:

```bash
python cli.py importar ~/Downloads/"Quiniela 3.pdf"
```

Formato esperado, que es el que ya usa el organizador:

| | B | C | … | Q | R |
|---|---|---|---|---|---|
| **1** | Lions | Panthers | … | Giants | |
| **2** | Bills | Falcons | … | Rams | Aciertos Totales |
| **3** | Ismael Reyna | Bills | … | Rams | 12 |

* Fila de visitantes y, justo debajo, la de locales. Cada columna es un partido.
* La columna A trae el nombre del participante; en el encabezado dice "Semana N".
* La última columna, **"Aciertos Totales", se ignora por completo**: viene
  precargada con valores incorrectos y es justo el problema que este proyecto
  resuelve.

El lector es tolerante con la posición exacta de las filas y con columnas
separadoras vacías, pero truena ruidosamente si encuentra:

* un participante con más o menos picks que partidos,
* un pick que no corresponde a ninguno de los dos equipos de ese partido,
* un nombre de participante duplicado,
* un equipo que aparece en dos partidos de la misma semana,
* un desacuerdo entre el nombre del archivo y la "Semana N" de adentro.

Los espacios sobrantes y los acentos inconsistentes sí se corrigen solos, y el
log dice cuáles se tocaron. Para la tabla general, "Angél" y "Angel" son la
misma persona.

## Premios

| Concepto | Monto | Cuándo |
|---|---|---|
| Premio semanal | $5,200 | Cada semana, **solo para el 1er lugar** |
| Acumulado semanal | $1,400 | Se aparta cada semana |
| Bolsa final | $25,200 | 18 semanas × $1,400, **al terminar la temporada** |

La bolsa final **no se toca durante la temporada**: se entrega cuando cierran
las 18 semanas, repartida entre los tres primeros de la general.

| Lugar | % | Monto |
|---|---|---|
| 1º | 70 % | $17,640 |
| 2º | 20 % | $5,040 |
| 3º | 10 % | $2,520 |

**Empates.** Si varias personas comparten un lugar, se suman los porcentajes de
los lugares que ocupan entre todas y se divide en partes iguales. Dos en primer
lugar se reparten el 70 % más el 20 % (45 % cada una) y quien sigue queda
tercero con su 10 %. El premio semanal se divide igual entre los ganadores de
esa semana.

Mientras la temporada sigue abierta, el sitio muestra las reglas del reparto
(los porcentajes y los montos) pero **no nombra a nadie**: los nombres del
reparto final aparecen hasta que cierran las 18 semanas.

Los montos viven en `quiniela/scoring.py` (`PREMIO_SEMANAL`,
`ACUMULADO_SEMANAL`, `SEMANAS_TEMPORADA`, `REPARTO_FINAL`).

## Que nadie toque los picks

Los picks viven en el repo y solo cambian con un `git push` autenticado: el
sitio publicado es de solo lectura, no hay formulario ni endpoint que reciba
nada. Pero queda un riesgo real, y es que alguien con acceso edite los picks
**después** de que empezaron los partidos.

Para eso están los sellos. En cuanto arranca el primer partido de una semana se
guarda la huella SHA-256 del archivo en `data/sellos.json`. Si más adelante el
archivo cambia, el cálculo truena con las dos huellas y no publica nada. Antes
del arranque se siguen pudiendo corregir los picks con toda libertad.

Como el sello vive en el repo, cualquier cambio queda además en el historial de
git con fecha y autor.

## Cuándo aparece cada cosa

El sitio calla lo que todavía no significa nada:

| Qué | Aparece cuando | Constante |
|---|---|---|
| Podio de la general | 16 partidos cerrados en la temporada | `UMBRAL_PODIO` |
| Ganador de la semana | 8 partidos cerrados de esa semana | `UMBRAL_SEMANA` |
| Nombres del reparto final | Cierran las 18 semanas | `SEMANAS_TEMPORADA` |

Y cuando hay muchos empatados no enlista a todos: dice cuántos son. Los
nombres sí se escriben cuando el resultado ya es oficial y hay dinero de por
medio (`MAXIMO_NOMBRES` en `quiniela/render_html.py`).

## Cómo se cuenta

El único número que se publica son los **aciertos**: partidos ya cerrados en
los que el participante le atinó al ganador. No hay columna de proyección.

Durante los juegos, junto al número aparece una marca como `+5`: son los
partidos en curso que esa persona va ganando ahora mismo. Sirve para seguir la
tarde, no cuenta para nada y desaparece cuando el partido cierra.

Un partido cuenta como cerrado solo cuando ESPN lo marca como completado. El
reloj en ceros no basta: hay partidos con el reloj agotado que siguen abiertos.

**Empates.** En la NFL existen. Si un partido termina empatado, nadie acierta:
cuenta como error para todos los que lo pronosticaron. Por eso `firme + errores`
siempre es igual al número de partidos cerrados.

**Posiciones.** La posición la decide **solo** el número de aciertos, que es
el que se publica: nadie queda arriba de nadie por un número que no se ve. Los
empatados comparten posición; si tres personas empatan en el primer lugar, las
tres son 1 y la siguiente es 4. Dentro de un empate, quien va ganando más
partidos en curso aparece primero, pero comparte la misma posición.

## Escenarios

```bash
python cli.py escenarios --participante "Angel D Luffy"
```

Enumera por fuerza bruta las 2^n combinaciones de los partidos que faltan (con
16 abiertos son 65,536) y dice en cuántas el participante gana solo, empata o
pierde, más qué partidos son indispensables para él.

Los empates no se enumeran: se asume que cada partido pendiente lo gana uno de
los dos equipos. Es una guía, no una promesa.

Si alguien tiene picks idénticos a los tuyos, tu "gana solo" será 0 por
definición: nunca puedes quedar estrictamente arriba de tu gemelo.

## Caché de marcadores

Los resultados se guardan en `data/resultados/semana_NN.json`. Una vez que un
partido está cerrado no se vuelve a consultar.

El endpoint de ESPN entrega la semana completa, no partido por partido, así que
la regla se implementa así: si el caché existe y **todos** sus partidos están
cerrados, no se toca la red; si alguno sigue abierto, se hace **una** petición y
los cerrados se conservan tal cual estaban en el caché, aunque la API cambie de
opinión.

Ese JSON se versiona en el repo. Es lo que permite que `--sin-red` y la tabla
general funcionen sin conexión.

## Correcciones manuales

Cuando la API se equivoca, `data/overrides.json` manda:

```json
{
  "2": {
    "Giants@Rams": "Rams"
  }
}
```

La llave es el número de semana; adentro, `Visitante@Local` apuntando al equipo
que ganó. Un `null` en lugar del equipo fuerza un empate.

Los overrides ganan siempre sobre la API, se aplican al vuelo (no se escriben en
el caché, para poder corregirlos sin invalidarlo) y el log dice claramente
cuáles se aplicaron y qué decía la API.

## El sitio

`docs/index.html` es **un solo archivo**: HTML, CSS, JavaScript y la temporada
entera en JSON, todo adentro. No hay servidor, ni CDN, ni peticiones de red al
abrirlo. Se regenera completo en cada corrida.

Qué trae:

* **Podio** con los tres primeros escalones y el premio de cada uno. Agrupa a
  los empatados, así que aguanta igual "31 empatados en primero" que un líder
  solitario en diciembre. No aparece hasta que se cierren `UMBRAL_PODIO`
  partidos (16 por defecto): con tres juegos todos van empatados y un podio ahí
  no dice nada.
* **Premios**: la bolsa, el reparto final como va hoy y el ganador de cada
  semana con su monto.
* **Ganador de la semana** arriba de cada semana, con trofeo y confeti cuando
  la semana ya cerró. Mientras sigue abierta dice quién va ganando y cuánto
  hay en juego.
* **Movimiento**: cada fila de la general muestra cuántos lugares subió o
  bajó respecto a la semana anterior.
* **Partidos ordenados por lo que falta**: primero lo que está por jugarse,
  después lo ya jugado del más reciente al más viejo, agrupado por horario. El
  de tu equipo se adelanta mientras no termine.
* **Los empatados se despliegan**: donde dice "N empatados" se ve la lista con
  un toque.
* **Navegación por semanas**: General, Premios y una pestaña por cada semana.
  El portal abre en la semana en curso, que además va marcada en el menú.
* **Marcador en vivo**: el navegador consulta ESPN cada 60 segundos, solo con
  la pestaña al frente. Esa capa nunca cierra un partido ni cambia el conteo
  oficial —eso lo decide CI— así que un error de la API no puede producir una
  tabla equivocada; si falla, se ve lo último publicado.
* **Jugadores**: buscador entre los 34 y un duelo para comparar a dos. La
  ficha de cada quien cruza los picks de todos: promedio, a cuántos está del
  líder, porcentaje de acierto, su equipo consentido con su récord y cuántas
  veces fue contra la mayoría de la quiniela (y cuántas le salió).
* **Modo equipo**: eliges tu equipo y el portal entero se viste de sus colores
  —fondo, superficies, bordes y resplandor— con los de casa o los de visita
  según dónde juegue esa semana, y su partido encabeza la lista. Los 64 temas
  se generan mezclando el color del equipo con la base oscura y cada uno pasa
  una verificación de contraste antes de salir.
* **Se queda donde estabas**: al recargar vuelve a la misma vista, pestaña y
  altura de la página.
* **Se guarda como app**: al agregarlo a la pantalla de inicio en iPhone o
  Android usa el logo propio y abre a pantalla completa.
* **Modo jugador**: en el encabezado eliges tu nombre y el sitio se vuelve
  tuyo. Cada partido de la semana se pinta según tu pick —verde si vas
  ganando, rojo si vas perdiendo, gris si no empieza— con un resumen de
  cuántos llevas, cuántos fallaste, cuántos vas ganando y cuántos faltan. Tu
  fila queda resaltada en las tablas. El nombre se guarda en el navegador, así
  que solo se elige una vez por teléfono.
* Dentro de cada semana: **Tabla**, **Partidos** con marcador en vivo,
  **Quién le fue a quién** y **Escenarios**.
* **Quién le fue a quién** se ve de dos formas: el reparto de cada partido, con
  una barra que muestra cómo se dividió la quiniela y los nombres de cada lado
  en verde o rojo según cómo salió; o la boleta completa de una persona, con
  palomita y tache partido por partido.
* **Escenarios** ordena a los que todavía pueden ganar la semana por el
  porcentaje de desenlaces en que terminan primeros, agrupando a los que están
  en la misma situación y explicando qué significa cada porcentaje.
* Cuando todavía no se sube el Excel de la semana en curso, el sitio publica
  esa semana con sus partidos programados y el letrero **"Actualizando la
  semana N"**, en lugar de quedarse en la anterior.

Todo es responsivo y está pensado primero para el teléfono; se probó desde 320
px. Las animaciones se apagan solas si el dispositivo pide movimiento reducido.

**Se actualiza solo.** El workflow regenera el sitio cada 15 minutos durante
las ventanas de juego, y la página abierta en un teléfono se recarga sola cada
5 minutos mientras haya partidos en curso.

`docs/tabla.png` es la general como imagen de 1080 px de ancho. Con más de 18
participantes se parte en dos columnas para que quede casi cuadrada y se lea en
la vista previa de WhatsApp sin abrirla.

Las horas se muestran en horario de Ciudad de México, que está fijo en UTC-6
todo el año desde que México eliminó el horario de verano en 2022.

## Automatización

Hay dos workflows, porque el cron de GitHub no es de fiar: en repos nuevos
tarda en activarse y GitHub avisa que retrasa o descarta corridas programadas
cuando hay carga.

**`directo.yml`** es el que trabaja durante los partidos. Necesita arrancar una
sola vez por ventana (jueves, domingo y lunes) y de ahí se queda corriendo
hasta 5 horas, recalculando cada 2 minutos y parando cuando cierra el último
partido. Cada vuelta arranca de lo que está publicado, así que si subes un
Excel nuevo o se corrige algo a media tarde, entra sin reiniciar el directo.
Para arrancarlo a mano:

```bash
gh workflow run directo.yml --repo <cuenta>/<repo> -f minutos=300 -f cada=120
```

**`actualizar.yml`** es el respaldo: corre cada 5 minutos en las mismas
ventanas, cuando subes un Excel nuevo y cuando lo disparas a mano.

Cada corrida recalcula y hace commit de `docs/` y `data/resultados/` si algo
cambió. GitHub Pages está configurado para publicar **desde la rama**
(`main`, carpeta `/docs`), así que cada commit se ve en el sitio sin más pasos.
Si el script falla, el workflow falla en rojo: nunca publica una tabla vieja
como si fuera buena.

## Ver el sitio en local

```bash
.venv/bin/python -m http.server 8765 --directory docs
```

Y abrir <http://localhost:8765>. Abrir el archivo con doble clic también
funciona; el servidor solo evita que el navegador cachee la versión anterior.

## Publicar

```bash
./crear_repo.sh
```

Crea el repositorio en GitHub, sube todo, enciende Pages y dispara la primera
publicación. Acepta dos argumentos: `./crear_repo.sh nombre-del-repo private`.

El sitio queda en `https://<tu-cuenta>.github.io/<nombre-del-repo>/`. Ese es el
enlace que se comparte al grupo. La imagen para WhatsApp queda en
`.../tabla.png`.

> En macOS, si `git` responde *"You have not agreed to the Xcode license"*,
> corre una sola vez:
> ```bash
> sudo xcodebuild -license accept
> ```

GitHub Pages gratis necesita repositorio **público**. En un repositorio público
quedan visibles los nombres de los participantes y sus picks.

## Crédito

El sitio va firmado por su desarrollador. El nombre de la quiniela, la firma y
la versión están en `quiniela/render_html.py`: `MARCA`, `DESARROLLADOR`,
`ETAPA` y `VERSION`.

## Pruebas

```bash
.venv/bin/python -m pytest
```

No hacen red: las respuestas de ESPN están guardadas como JSON en
`tests/fixtures/`.

## Estructura

```
quiniela/
  equipos.py     mapeo y normalización de nombres
  espn.py        cliente de marcadores, caché, overrides y el tipo Partido
  picks.py       lectura del Excel
  scoring.py     cálculo de tablas y escenarios
  render_html.py salida web
  render_png.py  imagen para WhatsApp
  plantillas/    plantilla Jinja2 de la página
data/
  picks/         Semana_01.xlsx, Semana_02.xlsx, ...
  resultados/    semana_01.json (caché de partidos cerrados)
  overrides.json correcciones manuales
docs/            salida publicada (GitHub Pages)
tests/
cli.py
```
