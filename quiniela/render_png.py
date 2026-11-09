"""Genera las imágenes que salen del portal, con los mismos valores que él: negro plano,
un resplandor del campo arriba de la línea amarilla y una sola letra.

  docs/tabla.png    la tabla general, para mandarla por WhatsApp
  docs/portada.png  la vista previa que sale al compartir el enlace

La prioridad de la tabla es que se lea en el chat sin abrir la imagen, así que
con muchos participantes se parte en dos columnas para que quede más cuadrada y
el texto se escale menos. En la portada todo el texto va dentro del cuadrado
central porque hay chats que la recortan.
"""

from __future__ import annotations

import logging
from datetime import datetime
from functools import lru_cache
from math import ceil
from pathlib import Path

import pandas as pd
from PIL import Image, ImageChops, ImageDraw, ImageFont

from . import marca
from .carga import SITIO
from .espn import ahora_cdmx
from .render_html import (
    BASE_CAMPO,
    MEDALLAS,
    SEMANTICOS,
    TAMANO_PORTADA,
    como_va_la_semana,
    quien_va_primero,
    tema_campo,
)

__all__ = ["ANCHO", "RUTA_PORTADA", "RUTA_SALIDA", "generar_png", "generar_portada"]

_log = logging.getLogger(__name__)

RAIZ = Path(__file__).resolve().parents[1]
RUTA_SALIDA = RAIZ / "docs" / "tabla.png"
RUTA_PORTADA = RAIZ / "docs" / "portada.png"

ANCHO = 1080
MARGEN = 40
ALTO_FILA = 56
#: A partir de aquí la tabla se parte en dos columnas.
MAXIMO_POR_COLUMNA = 18
SEPARACION_COLUMNAS = 48

_TEMA = tema_campo()
FONDO = BASE_CAMPO["bg"]
FILETE = BASE_CAMPO["linea"]
TEXTO = _TEMA["--txt"]
TENUE = _TEMA["--tenue"]
ORO = SEMANTICOS["oro"]
TINTA = "#0A0F0C"
#: El resplandor del campo, arriba de la línea: color y opacidad.
RESPLANDOR = ("#165C38", 0.55)
#: La medalla de cada lugar que cobra, la misma del podio del portal.
COLOR_MEDALLA = {"oro": "#FFD60A", "plata": "#C9D2DB", "bronce": "#D8935C"}

#: Lo que dibuja Pillow sale con esta ventaja y se reduce: diagonales sin dientes.
_ESCALA = 4

# Las primeras que existan: Arial en la Mac, y en el runner de Linux la Liberation, que
# mide lo mismo. Si no hay ninguna, la fuente de Pillow: nunca hay un .ttf en el repo.
_FUENTES = {
    "normal": [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ],
    "negrita": [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ],
}

_MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


@lru_cache(maxsize=None)
def _fuente(estilo: str, tamano: int) -> ImageFont.FreeTypeFont:
    for ruta in _FUENTES[estilo]:
        if Path(ruta).exists():
            try:
                return ImageFont.truetype(ruta, tamano)
            except OSError:  # pragma: no cover - fuente corrupta
                continue
    return ImageFont.load_default(size=tamano)


def _recortar(texto: str, fuente: ImageFont.FreeTypeFont, ancho: float) -> str:
    if fuente.getlength(texto) <= ancho:
        return texto
    while texto and fuente.getlength(texto + "…") > ancho:
        texto = texto[:-1]
    return texto + "…"


def _la_que_quepa(textos: list[str], estilo: str, tamano: int, minimo: int, ancho: float) -> ImageFont.FreeTypeFont:
    """La letra más grande con la que todos los textos caben, sin bajar del mínimo."""
    for prueba in range(tamano, minimo, -1):
        fuente = _fuente(estilo, prueba)
        if all(fuente.getlength(texto) <= ancho for texto in textos):
            return fuente
    return _fuente(estilo, minimo)


def _rgb(hexadecimal: str) -> tuple[int, int, int]:
    return tuple(int(hexadecimal[i:i + 2], 16) for i in (1, 3, 5))


# --- el fondo y la marca ---------------------------------------------------------


def _luz(lienzo: Image.Image, centro: tuple[float, float], radios: tuple[float, float],
         color: str, opacidad: float) -> None:
    """Un resplandor elíptico que se apaga hacia afuera."""
    tamano = (max(1, round(radios[0] * 2)), max(1, round(radios[1] * 2)))
    # El degradado de Pillow llega a 255 en las esquinas; en la orilla va en 181.
    forma = Image.radial_gradient("L").resize(tamano, Image.BICUBIC)
    forma = forma.point(lambda v: round(max(0.0, 1 - v / 181) ** 2 * opacidad * 255))
    alfa = Image.new("L", lienzo.size, 0)
    alfa.paste(forma, (round(centro[0] - radios[0]), round(centro[1] - radios[1])))
    capa = Image.new("RGBA", lienzo.size, _rgb(color) + (0,))
    capa.putalpha(alfa)
    lienzo.alpha_composite(capa)


def _lienzo(ancho: int, alto: int, y_linea: int, grueso: int) -> Image.Image:
    """Negro plano y la línea de orilla a orilla: arriba de ella va el campo, abajo nada."""
    lienzo = Image.new("RGBA", (ancho, alto), _rgb(FONDO) + (255,))
    arriba = lienzo.crop((0, 0, ancho, y_linea))
    _luz(arriba, (ancho / 2, 0), (ancho * 0.62, y_linea * 1.05), *RESPLANDOR)
    lienzo.paste(arriba)
    ImageDraw.Draw(lienzo).rectangle([0, y_linea, ancho - 1, y_linea + grueso - 1], fill=ORO)
    return lienzo


def _piezas(pincel: ImageDraw.ImageDraw, piezas, escala: float, color: str) -> None:
    for pieza in piezas:
        pincel.polygon([(x * escala, y * escala) for x, y in pieza], fill=color)


def dibujar_marca(lado: int) -> Image.Image:
    """La marca sin fondo, para pegarla encima de lo que sea."""
    grande = lado * _ESCALA
    capa = Image.new("RGBA", (grande, grande), (0, 0, 0, 0))
    pincel = ImageDraw.Draw(capa)
    _piezas(pincel, marca.A, grande / 64, marca.BLANCO)
    _piezas(pincel, [marca.LINEA], grande / 64, marca.ORO)
    return capa.resize((lado, lado), Image.LANCZOS)


def dibujar_palabra(alto: int, color: str = marca.BLANCO) -> Image.Image:
    """ANGABAVE dibujada, sin fondo. `alto` es el de su caja, como en el SVG."""
    escala = alto * _ESCALA / marca.ALTO_PALABRA
    tamano = (ceil(marca.ANCHO_PALABRA * escala), alto * _ESCALA)
    mascara = Image.new("L", tamano, 0)
    for poligono in marca.poligonos_de_palabra():
        capa = Image.new("L", tamano, 0)
        ImageDraw.Draw(capa).polygon([(x * escala, (y + 1) * escala) for x, y in poligono], fill=255)
        # Par e impar: el segundo paso por un hueco de la B lo vuelve a vaciar.
        mascara = ImageChops.difference(mascara, capa)
    final = (ceil(tamano[0] / _ESCALA), alto)
    salida = Image.new("RGBA", final, _rgb(color) + (0,))
    salida.putalpha(mascara.resize(final, Image.LANCZOS))
    return salida


def _medalla(lienzo: Image.Image, centro: tuple[int, int], radio: int, cual: str, cifra: str) -> None:
    grande = radio * 2 * _ESCALA
    disco = Image.new("L", (grande, grande), 0)
    ImageDraw.Draw(disco).ellipse([0, 0, grande - 1, grande - 1], fill=255)
    lienzo.paste(_rgb(COLOR_MEDALLA[cual]) + (255,), (centro[0] - radio, centro[1] - radio),
                 disco.resize((radio * 2, radio * 2), Image.LANCZOS))
    ImageDraw.Draw(lienzo).text(centro, cifra, font=_fuente("negrita", round(radio * 1.2)), fill=TINTA, anchor="mm")


# --- la tabla ------------------------------------------------------------------


def titulo_ganadores(semana: int, cuantos: int, oficial: bool) -> str:
    if oficial:
        return f"{'Ganaron' if cuantos > 1 else 'Ganó'} la semana {semana}"
    return f"{'Van' if cuantos > 1 else 'Va'} ganando la semana {semana}"


def _renglones(nombres: list[str], fuente, ancho: float, maximo: int = 2) -> list[str] | None:
    """Reparte los nombres en renglones. None si no caben: entonces se cuentan."""
    renglones: list[str] = []
    actual = ""
    for nombre in nombres:
        prueba = f"{actual} · {nombre}" if actual else nombre
        if fuente.getlength(prueba) <= ancho:
            actual = prueba
            continue
        if not actual or len(renglones) + 1 == maximo:
            return None
        renglones.append(actual)
        actual = nombre
    return [*renglones, actual]


def _nombres_de_la_franja(ganadores: list[str], limite: float) -> tuple[list[str], ImageFont.FreeTypeFont]:
    """Con pocos nombres, grandes; si son más, en dos renglones; con muchos se cuentan."""
    grande, chica = _fuente("negrita", 36), _fuente("negrita", 28)
    renglones = _renglones(ganadores, grande, limite, maximo=1)
    if renglones is not None:
        return renglones, grande
    renglones = _renglones(ganadores, chica, limite)
    if renglones is not None:
        return renglones, chica
    return [f"{len(ganadores)} empatados"], grande


def _franja_ganador(lienzo: Image.Image, arriba: int, renglones: list[str], fuente, premio: str | None,
                    cola: str, titulo: str, oficial: bool) -> None:
    """Quién se lleva la semana, sin caja: el título, sus nombres y a la derecha el monto."""
    dibujo = ImageDraw.Draw(lienzo)
    color = ORO if oficial else TENUE
    dibujo.text((MARGEN, arriba + 34), titulo, font=_fuente("negrita", 22), fill=color, anchor="lm")
    for indice, renglon in enumerate(renglones):
        y = arriba + 74 if len(renglones) == 1 else arriba + 68 + indice * 32
        dibujo.text((MARGEN, y), renglon, font=fuente, fill=TEXTO, anchor="lm")
    if premio:
        derecha = ANCHO - MARGEN - _fuente("negrita", 22).getlength(cola)
        y = arriba + (54 if len(renglones) == 1 else 62)
        dibujo.text((derecha, y), premio, font=_fuente("negrita", 52), fill=color, anchor="rm")
        if cola:
            dibujo.text((derecha, y + 8), cola, font=_fuente("negrita", 22), fill=color, anchor="lm")


def _fila(lienzo: Image.Image, caja: tuple[int, int, int, int], fila: dict) -> None:
    """Una persona. La medalla sale del lugar: del 4º en adelante nadie cobra, aunque vaya arriba."""
    izquierda, arriba, derecha, abajo = caja
    centro = (arriba + abajo) // 2
    posicion = int(fila["posicion"])
    cual = MEDALLAS.get(posicion)

    dibujo = ImageDraw.Draw(lienzo)
    x_lugar = izquierda + 17
    if cual:
        _medalla(lienzo, (x_lugar, centro), 17, cual, str(posicion))
    else:
        dibujo.text((x_lugar, centro), str(posicion), font=_fuente("negrita", 22), fill=TENUE, anchor="mm")

    aciertos = str(int(fila["acumulado"]))
    letra_aciertos = _fuente("negrita", 30)
    # Dos píxeles adentro: con la Liberation del runner, el último dígito alineado a la
    # derecha se pasaba un píxel del margen.
    dibujo.text((derecha - 2, centro), aciertos, font=letra_aciertos, fill=TEXTO, anchor="rm")

    x_nombre = izquierda + 50
    letra = _fuente("negrita" if cual else "normal", 26)
    nombre = _recortar(str(fila["participante"]), letra, derecha - letra_aciertos.getlength(aciertos) - 16 - x_nombre)
    dibujo.text((x_nombre, centro), nombre, font=letra, fill=TEXTO, anchor="lm")


def _cabecera(lienzo: Image.Image, semana: int, anio: int, cerrados: int, total_partidos: int) -> None:
    """La marca a la izquierda y cómo va la semana a la derecha, arriba de la línea."""
    dibujo = ImageDraw.Draw(lienzo)
    lienzo.alpha_composite(dibujar_marca(76), (MARGEN, 18))
    palabra = dibujar_palabra(33)
    x_texto = MARGEN + 76 + 14
    lienzo.alpha_composite(palabra, (x_texto, 26))
    subtitulo = f"Quiniela NFL {anio} · Tabla general"
    letra_sub = _fuente("normal", 22)
    dibujo.text((x_texto, 82), subtitulo, font=letra_sub, fill=TENUE, anchor="lm")

    titulo, avance = como_va_la_semana(semana, cerrados, total_partidos)
    libre = ANCHO - MARGEN - x_texto - max(palabra.width, letra_sub.getlength(subtitulo)) - 24
    dibujo.text((ANCHO - MARGEN, 44), titulo, font=_la_que_quepa([titulo], "negrita", 40, 26, libre),
                fill=TEXTO, anchor="rm")
    dibujo.text((ANCHO - MARGEN, 82), avance, font=_la_que_quepa([avance], "normal", 22, 16, libre),
                fill=TENUE, anchor="rm")


def generar_png(
    *,
    tabla_acumulada: pd.DataFrame,
    semana: int,
    anio: int,
    cerrados: int,
    total_partidos: int,
    ruta_salida: Path = RUTA_SALIDA,
    momento: datetime | None = None,
    ganadores: list[str] | None = None,
    premio: str | None = None,
    oficial: bool = False,
    semana_ganadores: int | None = None,
) -> Path:
    """Dibuja la tabla general y devuelve la ruta del PNG.

    Si se pasan `ganadores`, arriba va una franja con quién se llevó la semana:
    es el dato que la gente comparte, y sin él la imagen solo cuenta la mitad.
    """
    momento = momento or ahora_cdmx()
    filas = tabla_acumulada.to_dict("records")

    columnas = 2 if len(filas) > MAXIMO_POR_COLUMNA else 1
    por_columna = -(-len(filas) // columnas)  # división hacia arriba

    ganadores = [g for g in (ganadores or []) if g]
    y_linea, grueso, alto_pie = 112, 4, 70
    abajo_linea = y_linea + grueso

    # La franja crece si los nombres piden dos renglones: se reparten antes de medir el lienzo.
    renglones, letra_nombres, cola, alto_franja = [], None, "", 0
    if ganadores:
        cola = " c/u" if oficial and len(ganadores) > 1 else ""
        ancho_premio = 0.0
        if premio:
            ancho_premio = _fuente("negrita", 52).getlength(premio) + _fuente("negrita", 22).getlength(cola) + 24
        renglones, letra_nombres = _nombres_de_la_franja(ganadores, ANCHO - MARGEN * 2 - ancho_premio)
        alto_franja = 112 if len(renglones) == 1 else 128

    arriba_filas = abajo_linea + alto_franja + 8
    alto = arriba_filas + por_columna * ALTO_FILA + alto_pie

    lienzo = _lienzo(ANCHO, alto, y_linea, grueso)
    dibujo = ImageDraw.Draw(lienzo)
    _cabecera(lienzo, semana, anio, cerrados, total_partidos)

    if ganadores:
        titulo = titulo_ganadores(semana_ganadores or semana, len(ganadores), oficial)
        _franja_ganador(lienzo, abajo_linea, renglones, letra_nombres, premio, cola, titulo, oficial)
        dibujo.line([(MARGEN, arriba_filas - 8), (ANCHO - MARGEN, arriba_filas - 8)], fill=FILETE)

    ancho_columna = (ANCHO - MARGEN * 2 - (SEPARACION_COLUMNAS if columnas == 2 else 0)) // columnas
    for indice_columna in range(columnas):
        izquierda = MARGEN + indice_columna * (ancho_columna + SEPARACION_COLUMNAS)
        derecha = izquierda + ancho_columna
        tramo = filas[indice_columna * por_columna : (indice_columna + 1) * por_columna]
        for indice, fila in enumerate(tramo):
            y = arriba_filas + indice * ALTO_FILA
            _fila(lienzo, (izquierda, y, derecha, y + ALTO_FILA), fila)
            if indice < len(tramo) - 1:
                dibujo.line([(izquierda, y + ALTO_FILA), (derecha, y + ALTO_FILA)], fill=FILETE)

    y_pie = alto - 36
    dibujo.text(
        (MARGEN, y_pie),
        f"Al {momento.day} {_MESES[momento.month - 1]}, {momento.strftime('%H:%M')}, hora de CDMX",
        font=_fuente("normal", 20), fill=TENUE, anchor="lm",
    )
    dibujo.text((ANCHO - MARGEN, y_pie), _direccion(), font=_fuente("negrita", 20), fill=TENUE, anchor="rm")

    return _guardar(lienzo, ruta_salida)


def _direccion() -> str:
    return SITIO.removeprefix("https://").rstrip("/")


def _guardar(lienzo: Image.Image, ruta_salida: Path) -> Path:
    ruta_salida = Path(ruta_salida)
    ruta_salida.parent.mkdir(parents=True, exist_ok=True)
    lienzo.convert("RGB").save(ruta_salida, "PNG", optimize=True)
    _log.info("Escribí %s (%dx%d px).", ruta_salida, lienzo.width, lienzo.height)
    return ruta_salida


# --- la portada: lo que se ve al compartir el enlace ---------------------------

#: Lo más ancho que va el texto de la portada: cabe en el cuadrado central, que va de
#: x = 285 a x = 915 cuando un chat la recorta.
ANCHO_SEGURO = 560


def _centrado(dibujo: ImageDraw.ImageDraw, centro: int, y: int, texto: str, fuente, color: str) -> None:
    dibujo.text((centro, y), _recortar(texto, fuente, ANCHO_SEGURO), font=fuente, fill=color, anchor="mm")


def _lideres_en_portada(dibujo: ImageDraw.ImageDraw, centro: int, nombres: list[str]) -> None:
    """El nombre lo más grande que quepa; dos nombres largos se van a dos renglones."""
    junto = " y ".join(nombres)
    fuente = _la_que_quepa([junto], "negrita", 78, 44, ANCHO_SEGURO)
    if len(nombres) == 1 or fuente.getlength(junto) <= ANCHO_SEGURO:
        fuente = _la_que_quepa([junto], "negrita", 78, 40, ANCHO_SEGURO)
        _centrado(dibujo, centro, 186, junto, fuente, TEXTO)
        return
    renglones = [nombres[0], f"y {nombres[1]}"]
    fuente = _la_que_quepa(renglones, "negrita", 48, 36, ANCHO_SEGURO)
    for y, renglon in zip((146, 198), renglones):
        _centrado(dibujo, centro, y, renglon, fuente, TEXTO)


def generar_portada(
    *,
    tabla_acumulada: pd.DataFrame,
    semana: int,
    anio: int,
    cerrados: int,
    total_partidos: int,
    ruta_salida: Path = RUTA_PORTADA,
) -> Path:
    """Dibuja la vista previa del enlace: la noticia, y la marca solo para firmarla."""
    ancho, alto = TAMANO_PORTADA
    centro = ancho // 2
    lienzo = _lienzo(ancho, alto, 312, 6)
    dibujo = ImageDraw.Draw(lienzo)

    lienzo.alpha_composite(dibujar_marca(88), (centro - 44, 26))

    nombres, verbo, aciertos = quien_va_primero(tabla_acumulada)
    if nombres:
        _lideres_en_portada(dibujo, centro, nombres)
        frase = f"{verbo} en primero {aciertos}"
        _centrado(dibujo, centro, 252, frase, _la_que_quepa([frase], "normal", 34, 26, ANCHO_SEGURO), TENUE)

    titulo, avance = como_va_la_semana(semana, cerrados, total_partidos)
    _centrado(dibujo, centro, 392, titulo, _la_que_quepa([titulo], "negrita", 70, 44, ANCHO_SEGURO), TEXTO)
    _centrado(dibujo, centro, 456, avance, _la_que_quepa([avance], "normal", 34, 26, ANCHO_SEGURO), TENUE)

    palabra = dibujar_palabra(22, TEXTO)
    resto = f"Quiniela NFL {anio}"
    letra = _fuente("normal", 26)
    x = centro - round((palabra.width + 14 + letra.getlength(resto)) / 2)
    lienzo.alpha_composite(palabra, (x, 568 - palabra.height // 2))
    dibujo.text((x + palabra.width + 14, 568), resto, font=letra, fill=TENUE, anchor="lm")

    return _guardar(lienzo, ruta_salida)


# --- iconos para la pantalla de inicio ---------------------------------------

#: Tamaños que piden iOS y Android al guardar el sitio como app.
TAMANOS_ICONO = (180, 192, 512)


def dibujar_icono(lado: int) -> Image.Image:
    """El ícono de la app, de orilla a orilla porque iOS y Android le ponen sus esquinas.

    Es la primera pantalla del portal en chico: arriba el campo, abajo el negro y la
    línea amarilla de frontera, con la A cruzándola.
    """
    grande = lado * _ESCALA
    escala = grande / 64
    y, alto = marca.LINEA_ICONO
    lienzo = Image.new("RGB", (grande, grande), _rgb(marca.NEGRO))
    pincel = ImageDraw.Draw(lienzo)
    pincel.rectangle([0, 0, grande, y * escala], fill=marca.CAMPO)
    pincel.rectangle([0, y * escala, grande, (y + alto) * escala], fill=marca.ORO)
    _piezas(pincel, marca.A_ICONO, escala, marca.BLANCO)
    return lienzo.resize((lado, lado), Image.LANCZOS)


def generar_iconos(dir_salida: Path = RUTA_SALIDA.parent) -> list[Path]:
    """Escribe los iconos cuadrados de la app con la marca (quiniela/marca.py)."""
    dir_salida = Path(dir_salida)
    dir_salida.mkdir(parents=True, exist_ok=True)
    rutas = []
    for tamano in TAMANOS_ICONO:
        ruta = dir_salida / f"icono-{tamano}.png"
        dibujar_icono(tamano).save(ruta, "PNG", optimize=True)
        rutas.append(ruta)
    _log.info("Escribí %d iconos en %s.", len(rutas), dir_salida)
    return rutas
