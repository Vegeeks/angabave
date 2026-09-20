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


def generar_png(
    *,
    tabla_acumulada: pd.DataFrame,
    semana: int,
    anio: int,
    cerrados: int,
    total_partidos: int,
    ruta_salida: Path = RUTA_SALIDA,
    momento: datetime | None = None,
) -> Path:
    """Dibuja la tabla general y devuelve la ruta del PNG."""
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

    alto_cabecera = 148
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
