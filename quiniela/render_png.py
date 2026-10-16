"""Genera docs/tabla.png: la tabla general como imagen para WhatsApp.

La prioridad es que se lea en la vista previa del chat sin abrir la imagen, así
que con muchos participantes la tabla se parte en dos columnas para que la
imagen quede más cuadrada y el texto se escale menos al hacer el thumbnail.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw, ImageFont

from . import marca
from .espn import ahora_cdmx

__all__ = ["ANCHO", "RUTA_SALIDA", "generar_png"]

_log = logging.getLogger(__name__)

RAIZ = Path(__file__).resolve().parents[1]
RUTA_SALIDA = RAIZ / "docs" / "tabla.png"

ANCHO = 1080
MARGEN = 28
ALTO_FILA = 58
#: A partir de aquí la tabla se parte en dos columnas.
MAXIMO_POR_COLUMNA = 18

FONDO = (13, 17, 23)
PANEL = (22, 27, 34)
CEBRA = (26, 32, 40)
BORDE = (39, 46, 56)
TEXTO = (230, 237, 243)
TENUE = (139, 148, 158)
VERDE = (63, 185, 80)
AMBAR = (210, 153, 34)
ROJO = (248, 81, 73)
AZUL = (88, 166, 255)

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

_MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def _fuente(estilo: str, tamano: int) -> ImageFont.FreeTypeFont:
    for ruta in _FUENTES[estilo]:
        if Path(ruta).exists():
            try:
                return ImageFont.truetype(ruta, tamano)
            except OSError:  # pragma: no cover - fuente corrupta
                continue
    # Pillow trae una fuente escalable propia: nunca dependemos de un .ttf en el repo.
    return ImageFont.load_default(size=tamano)


def _recortar(texto: str, fuente: ImageFont.FreeTypeFont, ancho: int) -> str:
    if fuente.getbbox(texto)[2] <= ancho:
        return texto
    while texto and fuente.getbbox(texto + "…")[2] > ancho:
        texto = texto[:-1]
    return texto + "…"


def _a_la_derecha(dibujo, x: int, y: int, texto: str, fuente, color) -> None:
    ancho = fuente.getbbox(texto)[2]
    dibujo.text((x - ancho, y), texto, font=fuente, fill=color)


def _franja_ganador(dibujo, ganadores: list[str], premio: str | None, oficial: bool) -> None:
    """Banda con quien se lleva la semana, arriba de la tabla."""
    arriba, abajo = 146, 218
    color = AMBAR if oficial else TENUE
    dibujo.rounded_rectangle(
        [MARGEN, arriba, ANCHO - MARGEN, abajo], radius=14,
        fill=PANEL, outline=color, width=2,
    )

    rotulo = _fuente("negrita", 19)
    nombre_f = _fuente("negrita", 34)
    monto_f = _fuente("negrita", 30)

    titulo = (
        ("Ganadores de la semana" if len(ganadores) > 1 else "Ganador de la semana")
        if oficial else "Va ganando la semana"
    )
    dibujo.text((MARGEN + 22, arriba + 12), titulo.upper(), font=rotulo, fill=color)

    # Con muchos empatados se cuenta, no se enlista: no cabrían.
    texto = " · ".join(ganadores) if len(ganadores) <= 3 else f"{len(ganadores)} empatados"
    limite = ANCHO - MARGEN * 2 - 44 - (220 if premio else 0)
    dibujo.text(
        (MARGEN + 22, arriba + 34), _recortar(texto, nombre_f, limite),
        font=nombre_f, fill=TEXTO,
    )
    if premio:
        _a_la_derecha(dibujo, ANCHO - MARGEN - 22, arriba + 26, premio, monto_f, color)


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
) -> Path:
    """Dibuja la tabla general y devuelve la ruta del PNG.

    Si se pasan `ganadores`, arriba va una franja con quién se llevó la semana:
    es el dato que la gente comparte, y sin él la imagen solo cuenta la mitad.
    """
    momento = momento or ahora_cdmx()
    filas = tabla_acumulada.to_dict("records")

    # Resaltar el primer lugar solo cuando de verdad destaca: al arrancar la
    # semana medio mundo va empatado en 1 y marcarlos a todos no dice nada.
    lideres = sum(1 for fila in filas if int(fila["posicion"]) == 1)
    resaltar = lideres <= 3

    columnas = 2 if len(filas) > MAXIMO_POR_COLUMNA else 1
    por_columna = -(-len(filas) // columnas)  # división hacia arriba

    titulo = _fuente("negrita", 46)
    subtitulo = _fuente("normal", 26)
    encabezado = _fuente("negrita", 17)
    nombre_f = _fuente("normal", 27)
    nombre_podio = _fuente("negrita", 27)
    numero = _fuente("negrita", 31)
    chico = _fuente("normal", 24)
    pie = _fuente("normal", 22)

    ganadores = [g for g in (ganadores or []) if g]
    franja = bool(ganadores)
    alto_franja = 86 if franja else 0

    alto_cabecera = 148 + alto_franja
    alto_pie = 62
    alto = alto_cabecera + 34 + por_columna * ALTO_FILA + alto_pie

    imagen = Image.new("RGB", (ANCHO, alto), FONDO)
    dibujo = ImageDraw.Draw(imagen)

    dibujo.text((MARGEN, 26), f"QUINIELA NFL {anio}", font=titulo, fill=TEXTO)
    dibujo.text(
        (MARGEN, 82),
        f"General · tras la semana {semana} · {cerrados} de {total_partidos} partidos cerrados",
        font=subtitulo,
        fill=TENUE,
    )
    dibujo.line([(MARGEN, 132), (ANCHO - MARGEN, 132)], fill=BORDE, width=2)

    if franja:
        _franja_ganador(dibujo, ganadores, premio, oficial)

    ancho_columna = (ANCHO - MARGEN * 2 - (24 if columnas == 2 else 0)) // columnas
    for indice_columna in range(columnas):
        izquierda = MARGEN + indice_columna * (ancho_columna + 24)
        derecha = izquierda + ancho_columna

        x_pos = izquierda + 40
        x_total = derecha - 104
        x_err = derecha - 8
        x_nombre = izquierda + 52
        ancho_nombre = x_total - x_nombre - 18

        y = alto_cabecera
        dibujo.text((izquierda + 8, y), "#", font=encabezado, fill=TENUE)
        dibujo.text((x_nombre, y), "PARTICIPANTE", font=encabezado, fill=TENUE)
        _a_la_derecha(dibujo, x_total, y, "ACIERTOS", encabezado, TENUE)
        _a_la_derecha(dibujo, x_err, y, "FALLOS", encabezado, TENUE)

        y += 30
        tramo = filas[indice_columna * por_columna : (indice_columna + 1) * por_columna]
        for indice, fila in enumerate(tramo):
            if indice % 2 == 0:
                dibujo.rectangle([izquierda, y, derecha, y + ALTO_FILA - 4], fill=CEBRA)

            posicion = int(fila["posicion"])
            es_podio = resaltar and posicion == 1
            centro = y + (ALTO_FILA - 4) // 2

            _a_la_derecha(
                dibujo, x_pos, centro - 15, str(posicion), numero if es_podio else chico,
                AZUL if es_podio else TENUE,
            )
            fuente_nombre = nombre_podio if es_podio else nombre_f
            dibujo.text(
                (x_nombre, centro - 14),
                _recortar(str(fila["participante"]), fuente_nombre, ancho_nombre),
                font=fuente_nombre,
                fill=TEXTO,
            )
            _a_la_derecha(dibujo, x_total, centro - 16, str(int(fila["acumulado"])), numero, VERDE)
            _a_la_derecha(dibujo, x_err, centro - 12, str(int(fila["errores"])), chico, ROJO)

            y += ALTO_FILA
            dibujo.line([(izquierda, y - 4), (derecha, y - 4)], fill=BORDE, width=1)

    dibujo.text(
        (MARGEN, alto - alto_pie + 14),
        f"Actualizado {momento.day} {_MESES[momento.month - 1]} {momento.strftime('%H:%M')} CDMX"
        f"  ·  {cerrados} de {total_partidos} partidos cerrados en la semana {semana}",
        font=pie,
        fill=TENUE,
    )

    ruta_salida = Path(ruta_salida)
    ruta_salida.parent.mkdir(parents=True, exist_ok=True)
    imagen.save(ruta_salida, "PNG", optimize=True)
    _log.info("Escribí %s (%dx%d px).", ruta_salida, ANCHO, alto)
    return ruta_salida


# --- iconos para la pantalla de inicio ---------------------------------------

#: Tamaños que piden iOS y Android al guardar el sitio como app.
TAMANOS_ICONO = (180, 192, 512)


def _rgb(hexadecimal: str) -> tuple[int, int, int]:
    return tuple(int(hexadecimal[i:i + 2], 16) for i in (1, 3, 5))


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
