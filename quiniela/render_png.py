"""Genera las dos imágenes del sitio, con el look del portal: campo de noche y vidrio.

  docs/tabla.png    la tabla general, para mandarla por WhatsApp
  docs/portada.png  la vista previa que sale al compartir el enlace

La prioridad de la tabla es que se lea en el chat sin abrir la imagen, así que
con muchos participantes se parte en dos columnas para que quede más cuadrada y
el texto se escale menos. La portada tiene lo importante al centro porque hay
chats que la recortan en cuadrado.
"""

from __future__ import annotations

import logging
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import marca
from .carga import SITIO
from .espn import ahora_cdmx
from .render_html import BASE_CAMPO, MEDALLAS, SEMANTICOS, TAMANO_PORTADA, tema_campo

__all__ = ["ANCHO", "RUTA_PORTADA", "RUTA_SALIDA", "generar_png", "generar_portada"]

_log = logging.getLogger(__name__)

RAIZ = Path(__file__).resolve().parents[1]
RUTA_SALIDA = RAIZ / "docs" / "tabla.png"
RUTA_PORTADA = RAIZ / "docs" / "portada.png"
#: Oswald recortada: solo mayúsculas, dígitos y unos cuantos signos (LEEME.md).
RUTA_ROTULO = Path(__file__).resolve().parent / "tipografia" / "oswald-recortada.woff2"

ANCHO = 1080
MARGEN = 28
ALTO_FILA = 54
#: A partir de aquí la tabla se parte en dos columnas.
MAXIMO_POR_COLUMNA = 18

_TEMA = tema_campo()
TEXTO = _TEMA["--txt"]
TENUE = _TEMA["--tenue"]
VERDE = SEMANTICOS["verde"]
ROJO = SEMANTICOS["rojo"]
ORO = SEMANTICOS["oro"]
TINTA = "#0A1020"
#: La medalla de cada lugar con premio: plana, como en el podio del portal.
COLOR_MEDALLA = {
    "oro": ("#FFD60A", "#FFD60A"),
    "plata": ("#C9D2DB", "#C9D2DB"),
    "bronce": ("#D8935C", "#D8935C"),
}

# Las primeras que existan; en el runner de Linux caen a la fuente de Pillow.
_FUENTES = {
    "normal": [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ],
    "negrita": [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ],
}

_MESES = ["ENE", "FEB", "MAR", "ABR", "MAY", "JUN", "JUL", "AGO", "SEP", "OCT", "NOV", "DIC"]


def _fuente(estilo: str, tamano: int) -> ImageFont.FreeTypeFont:
    for ruta in _FUENTES[estilo]:
        if Path(ruta).exists():
            try:
                return ImageFont.truetype(ruta, tamano)
            except OSError:  # pragma: no cover - fuente corrupta
                continue
    # Pillow trae una fuente escalable propia: nunca dependemos de un .ttf en el repo.
    return ImageFont.load_default(size=tamano)


@lru_cache(maxsize=None)
def _rotulo(tamano: int, peso: str = "Bold") -> ImageFont.FreeTypeFont:
    """La de los titulares y las cifras del portal. Nunca para nombres: no trae minúsculas."""
    try:
        fuente = ImageFont.truetype(str(RUTA_ROTULO), tamano)
        fuente.set_variation_by_name(peso)
        return fuente
    except (OSError, NotImplementedError):  # pragma: no cover - FreeType sin WOFF2
        return _fuente("negrita", tamano)


def _recortar(texto: str, fuente: ImageFont.FreeTypeFont, ancho: int) -> str:
    if fuente.getlength(texto) <= ancho:
        return texto
    while texto and fuente.getlength(texto + "…") > ancho:
        texto = texto[:-1]
    return texto + "…"


def _rgb(hexadecimal: str) -> tuple[int, int, int]:
    return tuple(int(hexadecimal[i:i + 2], 16) for i in (1, 3, 5))


def _alfa(color: str, opacidad: float) -> tuple[int, int, int, int]:
    return (*_rgb(color), round(opacidad * 255))


def _espaciado(dibujo, x: float, y: float, texto: str, fuente, color, espacio: float, ancla: str = "l") -> None:
    """Texto con letras separadas, como los rótulos del portal. El ancla es l, m o r."""
    total = sum(fuente.getlength(letra) for letra in texto) + espacio * (len(texto) - 1)
    x -= {"l": 0, "m": total / 2, "r": total}[ancla]
    for letra in texto:
        dibujo.text((x, y), letra, font=fuente, fill=color, anchor="lm")
        x += fuente.getlength(letra) + espacio


# --- el campo y el vidrio ------------------------------------------------------


def _degradado(tamano: tuple[int, int], arriba: str, abajo: str, hasta: float = 1.0) -> Image.Image:
    """De un color a otro, de arriba a abajo; `hasta` es dónde termina el cambio."""
    a, b = _rgb(arriba), _rgb(abajo)
    tira = Image.new("RGB", (1, tamano[1]))
    for y in range(tamano[1]):
        mezcla = min(1.0, y / max(1, tamano[1] * hasta))
        tira.putpixel((0, y), tuple(round(p + (q - p) * mezcla) for p, q in zip(a, b)))
    return tira.resize(tamano).convert("RGBA")


def _luz(lienzo: Image.Image, centro: tuple[float, float], radios: tuple[float, float], color: tuple) -> None:
    """Un resplandor elíptico que se apaga hacia afuera. `color` lleva su opacidad."""
    tamano = (max(1, round(radios[0] * 2)), max(1, round(radios[1] * 2)))
    # El degradado de Pillow llega a 255 en las esquinas; en la orilla va en 181.
    mascara = Image.radial_gradient("L").resize(tamano, Image.BICUBIC)
    mascara = mascara.point(lambda v: round(max(0.0, 1 - v / 181) ** 2 * color[3]))
    capa = Image.new("RGBA", lienzo.size, (0, 0, 0, 0))
    capa.paste(color[:3] + (255,), (round(centro[0] - radios[0]), round(centro[1] - radios[1])), mascara)
    lienzo.alpha_composite(capa)


def _campo(ancho: int, alto: int, paso: int = 84) -> Image.Image:
    """El campo de noche del portal: corte del pasto, cal, yardas y las luces del estadio."""
    lienzo = _degradado((ancho, alto), BASE_CAMPO["bg2"], BASE_CAMPO["bg"], 0.46)

    capa = Image.new("RGBA", (ancho, alto), (0, 0, 0, 0))
    pincel = ImageDraw.Draw(capa)
    cal, cal2, franja = (255, 255, 255, 16), (255, 255, 255, 11), (255, 255, 255, 5)
    for fila, y in enumerate(range(0, alto, paso)):
        if fila % 2 == 0:
            pincel.rectangle([0, y, ancho, y + paso - 1], fill=franja)
        pincel.rectangle([0, y, ancho, y + 1], fill=cal)
    # Las marcas de cada yarda, a los lados y en las dos hileras de en medio.
    for centro, largo in ((0.042, 10), (0.35, 14), (0.65, 14), (0.958, 10)):
        x = round(ancho * centro)
        for y in range(0, alto, paso // 5):
            pincel.rectangle([x - largo // 2, y, x + largo // 2, y + 1], fill=cal2)
    # Las bandas laterales.
    for x in (round(ancho * 0.025), round(ancho * 0.975)):
        pincel.rectangle([x, 0, x + 1, alto], fill=cal)
    lienzo.alpha_composite(capa)

    # Los números de las yardas, de lado como en el campo.
    numeros = _rotulo(round(paso * 0.64))
    for indice, yardas in enumerate((10, 20, 30, 40, 50, 40, 30, 20, 10), start=1):
        y = paso * indice * 2
        if y >= alto:
            break
        for x, giro in ((round(ancho * 0.07), 90), (round(ancho * 0.93), -90)):
            letrero = Image.new("RGBA", (paso * 2, paso * 2), (0, 0, 0, 0))
            _espaciado(ImageDraw.Draw(letrero), paso, paso, str(yardas), numeros, (255, 255, 255, 11),
                       paso * 0.2, ancla="m")
            letrero = letrero.rotate(giro, resample=Image.BICUBIC)
            lienzo.alpha_composite(letrero, (max(0, x - paso), max(0, y - paso)))

    # Las luces, en las dos esquinas de arriba; y la sombra del fondo.
    for x in (0.06, 0.94):
        _luz(lienzo, (ancho * x, alto * -0.04), (ancho * 0.55, alto * 0.42), _alfa("#EAFBF0", 0.1))
    _luz(lienzo, (ancho * 0.5, alto * 1.18), (ancho * 1.3, alto * 0.7), (0, 0, 0, 128))
    return lienzo


def _redondeado(tamano: tuple[int, int], radio: int, grosor: int = 0) -> Image.Image:
    """Máscara de un rectángulo redondeado, relleno o solo el borde, sin dientes."""
    grande = (tamano[0] * 4, tamano[1] * 4)
    mascara = Image.new("L", grande, 0)
    ImageDraw.Draw(mascara).rounded_rectangle(
        [0, 0, grande[0] - 1, grande[1] - 1], radius=radio * 4,
        fill=None if grosor else 255, outline=255 if grosor else None, width=grosor * 4,
    )
    return mascara.resize(tamano, Image.LANCZOS)


def _vidrio(lienzo: Image.Image, caja: tuple[int, int, int, int], *, radio: int = 18,
            opacidad: float = 0.8, borde: tuple = (255, 255, 255, 24)) -> None:
    """Un panel de vidrio esmerilado: difumina lo que tiene atrás y le pone un velo encima."""
    izquierda, arriba, derecha, abajo = caja
    tamano = (derecha - izquierda, abajo - arriba)
    panel = lienzo.crop(caja).filter(ImageFilter.GaussianBlur(9))
    panel.alpha_composite(Image.new("RGBA", tamano, _alfa(BASE_CAMPO["panel"], opacidad)))
    brillo = _degradado(tamano, "#FFFFFF", "#FFFFFF")
    brillo.putalpha(Image.linear_gradient("L").rotate(180).resize(tamano).point(lambda v: round(v * 0.05)))
    panel.alpha_composite(brillo)
    lienzo.paste(panel, (izquierda, arriba), _redondeado(tamano, radio))
    lienzo.paste(borde[:3] + (255,), (izquierda, arriba),
                 _redondeado(tamano, radio, 1).point(lambda v: round(v * borde[3] / 255)))


def _medalla(lienzo: Image.Image, centro: tuple[int, int], radio: int, cual: str, cifra: str) -> None:
    lado = radio * 2
    disco = _degradado((lado, lado), *COLOR_MEDALLA[cual])
    lienzo.paste(disco, (centro[0] - radio, centro[1] - radio), _redondeado((lado, lado), radio))
    ImageDraw.Draw(lienzo).text(centro, cifra, font=_rotulo(round(radio * 1.15)), fill=TINTA, anchor="mm")


def _logo(lienzo: Image.Image, xy: tuple[int, int], lado: int) -> None:
    lienzo.paste(dibujar_marca(lado), xy, _redondeado((lado, lado), round(lado * 0.22)))


# --- la tabla ------------------------------------------------------------------


def estado_de_semana(semana: int, cerrados: int, total: int) -> str:
    """Cómo va la semana, contando todos sus partidos y no solo los ya repartidos."""
    if total and cerrados >= total:
        return "CERRADA"
    return f"{cerrados} DE {total} PARTIDOS"


def titulo_ganadores(semana: int, cuantos: int, oficial: bool) -> str:
    if not oficial:
        return f"VA GANANDO LA SEMANA {semana}"
    return f"{'GANADORES' if cuantos > 1 else 'GANADOR'} DE LA SEMANA {semana}"


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


def _franja_ganador(lienzo: Image.Image, caja: tuple[int, int, int, int], ganadores: list[str],
                    premio: str | None, oficial: bool, semana: int) -> None:
    """Banda con quien se lleva la semana, arriba de la tabla."""
    izquierda, arriba, derecha, abajo = caja
    color = ORO if oficial else TENUE
    _vidrio(lienzo, caja, opacidad=0.86, borde=_alfa(color, 0.55))
    dibujo = ImageDraw.Draw(lienzo)
    _espaciado(dibujo, izquierda + 24, arriba + 24, titulo_ganadores(semana, len(ganadores), oficial),
               _rotulo(19), color, 2.2)

    ancho_premio = 0
    if premio:
        monto = _rotulo(44)
        cola = " C/U" if oficial and len(ganadores) > 1 else ""
        ancho_premio = monto.getlength(premio) + _rotulo(22).getlength(cola) + 24
        x = derecha - 24 - _rotulo(22).getlength(cola)
        dibujo.text((x, (arriba + abajo) // 2), premio, font=monto, fill=color, anchor="rm")
        if cola:
            dibujo.text((x, (arriba + abajo) // 2 + 6), cola, font=_rotulo(22), fill=color, anchor="lm")

    limite = derecha - izquierda - 48 - ancho_premio
    # Con pocos nombres, grandes; si son más, en dos renglones; con muchos se cuentan.
    grande, chica = _fuente("negrita", 32), _fuente("negrita", 25)
    renglones = _renglones(ganadores, grande, limite, maximo=1)
    fuente = grande
    if renglones is None:
        renglones, fuente = _renglones(ganadores, chica, limite), chica
    if renglones is None:
        renglones, fuente = [f"{len(ganadores)} empatados"], grande
    centro = arriba + 66 if len(renglones) == 1 else arriba + 50
    for indice, renglon in enumerate(renglones):
        dibujo.text((izquierda + 24, centro + indice * 34), renglon, font=fuente, fill=TEXTO, anchor="lm")


def _fila(lienzo: Image.Image, caja: tuple[int, int, int, int], fila: dict, sombreada: bool) -> None:
    """Una persona. La medalla sale del lugar: del 4º en adelante no hay, aunque vaya arriba."""
    izquierda, arriba, derecha, abajo = caja
    centro = (arriba + abajo) // 2
    posicion = int(fila["posicion"])
    cual = MEDALLAS.get(posicion)

    if cual:
        tinte = Image.new("RGBA", (derecha - izquierda, abajo - arriba), _alfa(COLOR_MEDALLA[cual][1], 0.13))
        lienzo.alpha_composite(tinte, (izquierda, arriba))
        lienzo.paste(_rgb(COLOR_MEDALLA[cual][1]) + (255,), (izquierda, arriba, izquierda + 3, abajo))
    elif sombreada:
        lienzo.alpha_composite(
            Image.new("RGBA", (derecha - izquierda, abajo - arriba), (255, 255, 255, 7)), (izquierda, arriba)
        )

    dibujo = ImageDraw.Draw(lienzo)
    x_lugar = izquierda + 32
    if cual:
        _medalla(lienzo, (x_lugar, centro), 17, cual, str(posicion))
    else:
        dibujo.text((x_lugar, centro), str(posicion), font=_rotulo(25, "Medium"), fill=TENUE, anchor="mm")

    x_total, x_fallos = derecha - 92, derecha - 22
    x_nombre = izquierda + 62
    fuente = _fuente("negrita" if cual else "normal", 26)
    nombre = _recortar(str(fila["participante"]), fuente, x_total - x_nombre - 44)
    dibujo.text((x_nombre, centro), nombre, font=fuente, fill=TEXTO, anchor="lm")
    dibujo.text((x_total, centro), str(int(fila["acumulado"])), font=_rotulo(33), fill=VERDE, anchor="rm")
    dibujo.text((x_fallos, centro), str(int(fila["errores"])), font=_rotulo(25, "Medium"), fill=ROJO, anchor="rm")


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
    alto_cabecera, alto_franja, alto_rotulos, alto_pie = 124, 118 if ganadores else 0, 40, 56
    arriba_tabla = alto_cabecera + alto_franja
    alto = arriba_tabla + alto_rotulos + por_columna * ALTO_FILA + 10 + alto_pie

    lienzo = _campo(ANCHO, alto)
    dibujo = ImageDraw.Draw(lienzo)

    # La cabecera: la marca a la izquierda y cómo va la semana a la derecha.
    _logo(lienzo, (MARGEN, 24), 80)
    dibujo.text((MARGEN + 98, 44), "ANGABAVE", font=_rotulo(50), fill=TEXTO, anchor="lm")
    _espaciado(dibujo, MARGEN + 98, 88, f"QUINIELA NFL {anio} · TABLA GENERAL", _rotulo(21, "Medium"), TENUE, 2.0)
    dibujo.text((ANCHO - MARGEN, 44), f"SEMANA {semana}", font=_rotulo(38), fill=ORO, anchor="rm")
    _espaciado(dibujo, ANCHO - MARGEN, 88, estado_de_semana(semana, cerrados, total_partidos),
               _rotulo(21, "Medium"), TENUE, 1.6, ancla="r")

    if ganadores:
        _franja_ganador(lienzo, (MARGEN, alto_cabecera, ANCHO - MARGEN, alto_cabecera + 104),
                        ganadores, premio, oficial, semana_ganadores or semana)

    separacion = 16
    ancho_columna = (ANCHO - MARGEN * 2 - (separacion if columnas == 2 else 0)) // columnas
    letrero = _rotulo(17)
    for indice_columna in range(columnas):
        izquierda = MARGEN + indice_columna * (ancho_columna + separacion)
        derecha = izquierda + ancho_columna
        _vidrio(lienzo, (izquierda, arriba_tabla, derecha, arriba_tabla + alto_rotulos + por_columna * ALTO_FILA + 4))

        y = arriba_tabla + alto_rotulos // 2 + 1
        dibujo.text((izquierda + 32, y), "#", font=_fuente("negrita", 15), fill=TENUE, anchor="mm")
        _espaciado(dibujo, izquierda + 62, y, "PARTICIPANTE", letrero, TENUE, 1.8)
        _espaciado(dibujo, derecha - 92, y, "ACIERTOS", letrero, TENUE, 1.2, ancla="r")
        _espaciado(dibujo, derecha - 22, y, "FALLOS", letrero, TENUE, 1.2, ancla="r")

        y = arriba_tabla + alto_rotulos
        tramo = filas[indice_columna * por_columna : (indice_columna + 1) * por_columna]
        for indice, fila in enumerate(tramo):
            _fila(lienzo, (izquierda + 1, y, derecha - 1, y + ALTO_FILA), fila, indice % 2 == 0)
            y += ALTO_FILA

    pie = _rotulo(18, "Medium")
    y_pie = alto - alto_pie // 2 - 2
    _espaciado(dibujo, MARGEN, y_pie, f"ACTUALIZADO {momento.day} {_MESES[momento.month - 1]} "
               f"{momento.strftime('%H:%M')} CDMX", pie, TENUE, 1.4)
    _espaciado(dibujo, ANCHO - MARGEN, y_pie, _direccion(), pie, TENUE, 1.4, ancla="r")

    return _guardar(lienzo, ruta_salida)


def _direccion() -> str:
    return SITIO.removeprefix("https://").rstrip("/").upper()


def _guardar(lienzo: Image.Image, ruta_salida: Path) -> Path:
    ruta_salida = Path(ruta_salida)
    ruta_salida.parent.mkdir(parents=True, exist_ok=True)
    lienzo.convert("RGB").save(ruta_salida, "PNG", optimize=True)
    _log.info("Escribí %s (%dx%d px).", ruta_salida, lienzo.width, lienzo.height)
    return ruta_salida


# --- la portada: lo que se ve al compartir el enlace ---------------------------


def linea_de_lideres(tabla_acumulada: pd.DataFrame) -> str:
    """Quién va arriba, con sus aciertos. Con muchos empatados se cuentan."""
    primeros = tabla_acumulada[tabla_acumulada["posicion"] == 1]
    if primeros.empty:
        return ""
    aciertos = int(primeros.iloc[0]["acumulado"])
    if len(primeros) > 2:
        return f"{len(primeros)} empatados en primero con {aciertos}"
    return f"{' y '.join(primeros['participante'])} · {aciertos} aciertos"


def generar_portada(
    *,
    tabla_acumulada: pd.DataFrame,
    semana: int,
    anio: int,
    cerrados: int,
    total_partidos: int,
    ruta_salida: Path = RUTA_PORTADA,
) -> Path:
    """Dibuja la vista previa del enlace: la marca, la semana y quién va arriba."""
    ancho, alto = TAMANO_PORTADA
    centro = ancho // 2
    lienzo = _campo(ancho, alto, paso=70)
    dibujo = ImageDraw.Draw(lienzo)

    _logo(lienzo, (centro - 50, 46), 100)
    dibujo.text((centro, 214), "ANGABAVE", font=_rotulo(104), fill=TEXTO, anchor="mm")
    _espaciado(dibujo, centro, 296, f"QUINIELA NFL {anio}", _rotulo(30, "Medium"), TENUE, 6, ancla="m")

    texto = f"SEMANA {semana} · {estado_de_semana(semana, cerrados, total_partidos)}"
    fuente = _rotulo(36)
    ancho_pastilla = round(fuente.getlength(texto)) + 72
    _vidrio(lienzo, (centro - ancho_pastilla // 2, 346, centro + ancho_pastilla // 2, 416),
            radio=35, opacidad=0.86, borde=_alfa(ORO, 0.55))
    dibujo.text((centro, 381), texto, font=fuente, fill=ORO, anchor="mm")

    lideres = linea_de_lideres(tabla_acumulada)
    if lideres:
        _espaciado(dibujo, centro, 464, "VA EN PRIMERO", _rotulo(22), TENUE, 3.2, ancla="m")
        nombre = _fuente("negrita", 40)
        dibujo.text((centro, 516), _recortar(lideres, nombre, ancho - 120), font=nombre, fill=TEXTO, anchor="mm")

    return _guardar(lienzo, ruta_salida)


# --- iconos para la pantalla de inicio ---------------------------------------

#: Tamaños que piden iOS y Android al guardar el sitio como app.
TAMANOS_ICONO = (180, 192, 512)


def _cubica(p0, p1, p2, p3, pasos: int = 48):
    """Curva cúbica de Bézier, como las del SVG de la marca."""
    puntos = []
    for paso in range(pasos + 1):
        t = paso / pasos
        u = 1 - t
        puntos.append(tuple(
            u ** 3 * a + 3 * u * u * t * b + 3 * u * t * t * c + t ** 3 * d
            for a, b, c, d in zip(p0, p1, p2, p3)
        ))
    return puntos


def _degradado_diagonal(lado: int, inicio: str, fin: str) -> Image.Image:
    """La loseta: de arriba a la izquierda a abajo a la derecha."""
    a, b = _rgb(inicio), _rgb(fin)
    tira = Image.new("RGB", (2 * lado, 1))
    for x in range(2 * lado):
        mezcla = x / max(1, 2 * lado - 1)
        tira.putpixel((x, 0), tuple(round(p + (q - p) * mezcla) for p, q in zip(a, b)))
    # Una tira horizontal girada 45° y recortada al centro da el degradado diagonal.
    grande = tira.resize((2 * lado, 2 * lado)).rotate(-45, resample=Image.BICUBIC)
    return grande.crop((lado // 2, lado // 2, lado // 2 + lado, lado // 2 + lado)).convert("RGBA")


def _oro_en(forma, tamano: tuple[int, int]) -> Image.Image:
    """El oro de arriba a abajo, medido sobre la altura de la propia forma (como el SVG)."""
    ys = [y for _, y in forma]
    arriba, abajo = min(ys), max(ys)
    paradas = [(0.0, _rgb(marca.ORO[0])), (0.55, _rgb(marca.ORO[1])), (1.0, _rgb(marca.ORO[2]))]
    columna = Image.new("RGB", (1, tamano[1]))
    for y in range(tamano[1]):
        t = min(1.0, max(0.0, (y - arriba) / max(1.0, abajo - arriba)))
        for (t0, c0), (t1, c1) in zip(paradas, paradas[1:]):
            if t <= t1:
                m = (t - t0) / (t1 - t0)
                columna.putpixel((0, y), tuple(round(a + (b - a) * m) for a, b in zip(c0, c1)))
                break
    return columna.resize(tamano).convert("RGBA")


def dibujar_marca(lado: int, *, escala: float = 0.9) -> Image.Image:
    """La marca sobre su loseta, de orilla a orilla, para los íconos de la app.

    La loseta llena todo el cuadro porque iOS y Android le ponen sus propias
    esquinas; la A va al `escala` para quedar dentro de la zona segura de los
    íconos que Android recorta en círculo. Se dibuja al cuádruple y se reduce,
    para que las diagonales y las puntas del balón salgan limpias.
    """
    grande = lado * 4
    factor = grande / 64 * escala
    margen = (grande - 64 * factor) / 2

    def punto(x: float, y: float) -> tuple[float, float]:
        return (margen + x * factor, margen + y * factor)

    lienzo = _degradado_diagonal(grande, *marca.LOSETA)

    for forma in (
        [punto(*p) for p in marca.A],
        [punto(*p) for p in (
            _cubica(*marca.BALON[0:4]) + _cubica(marca.BALON[3], marca.BALON[4], marca.BALON[5], marca.BALON[0])[1:]
        )],
    ):
        mascara = Image.new("L", lienzo.size, 0)
        ImageDraw.Draw(mascara).polygon(forma, fill=255)
        lienzo.paste(_oro_en(forma, lienzo.size), (0, 0), mascara)

    pincel = ImageDraw.Draw(lienzo)
    tinta = _rgb(marca.TINTA) + (255,)
    balon = [punto(*p) for p in (
        _cubica(*marca.BALON[0:4]) + _cubica(marca.BALON[3], marca.BALON[4], marca.BALON[5], marca.BALON[0])[1:]
    )]
    pincel.line(balon + [balon[1]], fill=tinta, width=round(marca.GROSOR_CONTORNO * factor), joint="curve")
    grosor = marca.GROSOR_COSTURA * factor
    for a, b in marca.COSTURAS:
        pa, pb = punto(*a), punto(*b)
        pincel.line([pa, pb], fill=tinta, width=round(grosor))
        for x, y in (pa, pb):   # puntas redondas, como stroke-linecap="round"
            pincel.ellipse([x - grosor / 2, y - grosor / 2, x + grosor / 2, y + grosor / 2], fill=tinta)

    return lienzo.resize((lado, lado), Image.LANCZOS)


def generar_iconos(dir_salida: Path = RUTA_SALIDA.parent) -> list[Path]:
    """Escribe los iconos cuadrados de la app con la marca (quiniela/marca.py)."""
    dir_salida = Path(dir_salida)
    dir_salida.mkdir(parents=True, exist_ok=True)
    original = dibujar_marca(1024)
    rutas = []
    for tamano in TAMANOS_ICONO:
        ruta = dir_salida / f"icono-{tamano}.png"
        original.resize((tamano, tamano), Image.LANCZOS).convert("RGB").save(ruta, "PNG", optimize=True)
        rutas.append(ruta)
    _log.info("Escribí %d iconos en %s.", len(rutas), dir_salida)
    return rutas
