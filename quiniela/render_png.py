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
from PIL import Image, ImageDraw, ImageFilter, ImageFont

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

_FONDO_ICONO = (10, 14, 22)
_ORO_ALTO = (255, 231, 170)
_ORO_BAJO = (208, 150, 23)
_ORO_PLANO = (247, 201, 72)


def _bezier(inicio, control, fin, pasos: int = 24):
    """Curva cuadrática, para que el escudo no se vea de cartón."""
    puntos = []
    for paso in range(pasos + 1):
        t = paso / pasos
        u = 1 - t
        puntos.append(
            (
                u * u * inicio[0] + 2 * u * t * control[0] + t * t * fin[0],
                u * u * inicio[1] + 2 * u * t * control[1] + t * t * fin[1],
            )
        )
    return puntos


def _escudo(lado: int, escala: float = 1.0) -> list[tuple[float, float]]:
    """Silueta del escudo: hombros rectos y punta curva, como los de liga."""
    # Coordenadas en fracción del lienzo, medidas desde el centro.
    izquierda, derecha = 0.145, 0.855
    alto, hombro, punta = 0.085, 0.50, 0.925
    centro = 0.5

    forma = [(izquierda, alto), (derecha, alto), (derecha, hombro)]
    forma += _bezier((derecha, hombro), (derecha, punta - 0.10), (centro, punta))
    forma += _bezier((centro, punta), (izquierda, punta - 0.10), (izquierda, hombro))
    forma.append((izquierda, alto))

    return [
        ((x - centro) * escala * lado + centro * lado,
         (y - centro) * escala * lado + centro * lado)
        for x, y in forma
    ]


def _degradado_vertical(lado: int, arriba, abajo) -> Image.Image:
    tira = Image.new("RGB", (1, lado))
    for y in range(lado):
        mezcla = y / max(1, lado - 1)
        tira.putpixel(
            (0, y), tuple(round(a + (b - a) * mezcla) for a, b in zip(arriba, abajo))
        )
    return tira.resize((lado, lado), Image.BILINEAR)


def _mascara(lado: int, forma) -> Image.Image:
    mascara = Image.new("L", (lado, lado), 0)
    ImageDraw.Draw(mascara).polygon(forma, fill=255)
    return mascara


def _balon(lado: int) -> Image.Image:
    """Balón recortado en negativo sobre el escudo, con costuras doradas."""
    capa = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
    pincel = ImageDraw.Draw(capa)
    ancho, alto = lado * 0.46, lado * 0.285
    cx, cy = lado / 2, lado * 0.475
    pincel.ellipse(
        [cx - ancho / 2, cy - alto / 2, cx + ancho / 2, cy + alto / 2],
        fill=_FONDO_ICONO + (255,),
    )
    grosor = max(2, int(lado * 0.018))
    pincel.line(
        [(cx - ancho * 0.26, cy), (cx + ancho * 0.26, cy)],
        fill=_ORO_PLANO + (255,), width=grosor,
    )
    for paso in (-1.5, -0.5, 0.5, 1.5):
        x = cx + paso * ancho * 0.12
        pincel.line(
            [(x, cy - alto * 0.2), (x, cy + alto * 0.2)],
            fill=_ORO_PLANO + (255,), width=grosor,
        )
    return capa.rotate(25, resample=Image.BICUBIC, expand=False, center=(cx, cy))


def generar_iconos(dir_salida: Path = RUTA_SALIDA.parent) -> list[Path]:
    """Escribe los iconos cuadrados con el escudo de la quiniela.

    Se dibuja en grande y se reduce con LANCZOS: así los bordes curvos salen
    limpios en los tamaños chicos, que es donde se nota lo amateur.
    """
    dir_salida = Path(dir_salida)
    dir_salida.mkdir(parents=True, exist_ok=True)
    lado = 1024

    lienzo = Image.new("RGBA", (lado, lado), _FONDO_ICONO + (255,))

    # Escudo dorado con degradado de arriba a abajo.
    forma = _escudo(lado, escala=0.94)
    oro = _degradado_vertical(lado, _ORO_ALTO, _ORO_BAJO).convert("RGBA")
    lienzo.paste(oro, (0, 0), _mascara(lado, forma))

    # Brillo sutil en la mitad superior. Va difuminado: un borde duro aquí se
    # ve como un pliegue de plástico, que es justo lo que no queremos.
    brillo = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
    ImageDraw.Draw(brillo).polygon(
        [(0, 0), (lado, 0), (lado, lado * 0.40), (0, lado * 0.56)], fill=(255, 255, 255, 34)
    )
    brillo = brillo.filter(ImageFilter.GaussianBlur(lado * 0.07))
    lienzo.alpha_composite(Image.composite(
        brillo, Image.new("RGBA", (lado, lado), (0, 0, 0, 0)), _mascara(lado, forma)
    ))

    # Filete interior oscuro: separa el escudo del fondo y marca el borde.
    contorno = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
    ImageDraw.Draw(contorno).line(
        forma + [forma[0]], fill=_FONDO_ICONO + (170,), width=max(2, int(lado * 0.014)), joint="curve"
    )
    lienzo.alpha_composite(contorno)

    lienzo.alpha_composite(_balon(lado))

    rutas = []
    for tamano in TAMANOS_ICONO:
        ruta = dir_salida / f"icono-{tamano}.png"
        lienzo.resize((tamano, tamano), Image.LANCZOS).convert("RGB").save(
            ruta, "PNG", optimize=True
        )
        rutas.append(ruta)
    _log.info("Escribí %d iconos en %s.", len(rutas), dir_salida)
    return rutas
