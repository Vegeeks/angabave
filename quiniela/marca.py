"""La marca de ANGABAVE, en un solo lugar.

Una A sin travesaño: su travesaño es la línea amarilla de primera y diez, que la
cruza y se sale por los dos lados. Arriba y abajo de la línea la A va cortada de
verdad, con aire, para que se lea igual sobre el campo, sobre negro y con la línea
del color de cada equipo.

La geometría vive aquí, en un espacio de 64 × 64, y de aquí salen todas sus copias:
el SVG del encabezado, el ícono de la pestaña, el dibujo en canvas de la imagen de
picks, y las imágenes e íconos de la app (render_png). Si se cambia algo, se cambia
aquí y nada se desalinea.
"""

from __future__ import annotations

import re
from urllib.parse import quote

__all__ = [
    "A", "A_FAVICON", "A_ICONO", "ALTO_PALABRA", "ANCHO_PALABRA", "BLANCO", "CAMPO", "LINEA",
    "LINEA_FAVICON", "LINEA_ICONO", "NEGRO", "ORO", "PALABRA",
    "favicon", "palabra", "para_canvas", "poligonos_de_palabra", "ruta_a", "ruta_linea", "rutas", "svg",
]

BLANCO = "#F3F6F4"
#: El amarillo de la línea de primera y diez.
ORO = "#FFD60A"
#: El piso del portal y el pasto de noche: lo que queda abajo y arriba de la línea.
NEGRO = "#060A08"
CAMPO = "#0A4329"


def _a(
    *, arriba: float, abajo: float, ancho: float, punta: float, grosor: float,
    linea_y: float, linea_alto: float, aire: float,
) -> tuple:
    """La A en tres piezas, la punta y los dos pies, simétrica sobre x = 32.

    `punta` es lo ancho de arriba, `grosor` lo ancho de cada pierna medido en
    horizontal y `aire` lo que se corta a cada lado de la línea.
    """
    izquierda = 32 - ancho / 2
    pendiente = (ancho - punta) / 2 / (abajo - arriba)

    def fuera(y: float) -> float:
        return izquierda + (abajo - y) * pendiente

    def cerca(puntos) -> tuple:
        return tuple((round(x, 2), round(y, 2)) for x, y in puntos)

    hueco = abajo - (ancho / 2 - grosor) / pendiente
    corte_alto, corte_bajo = linea_y - aire, linea_y + linea_alto + aire
    x_alto, x_bajo = fuera(corte_alto), fuera(corte_bajo)
    pie = (
        (izquierda, abajo), (x_bajo, corte_bajo),
        (x_bajo + grosor, corte_bajo), (izquierda + grosor, abajo),
    )
    return (
        cerca((
            (x_alto, corte_alto), (32 - punta / 2, arriba), (32 + punta / 2, arriba),
            (64 - x_alto, corte_alto), (64 - x_alto - grosor, corte_alto),
            (32, hueco), (x_alto + grosor, corte_alto),
        )),
        cerca(pie),
        cerca((64 - x, y) for x, y in pie),
    )


#: La marca: se usa de 30 px para arriba, sin loseta, encima de lo que sea.
A = _a(arriba=6, abajo=58, ancho=52, punta=9, grosor=13, linea_y=40, linea_alto=6.5, aire=3)
#: La línea sale inclinada de las puntas, como quien avanza.
LINEA = ((4.5, 40), (63.5, 40), (59.5, 46.5), (0.5, 46.5))

#: El ícono de la app: la misma A, dentro de la zona segura de Android (radio 25.6).
#: La línea va de orilla a orilla: su altura y su grueso.
A_ICONO = _a(arriba=10.5, abajo=48.5, ancho=38, punta=6.6, grosor=9.5, linea_y=35.4, linea_alto=4.8, aire=2.2)
LINEA_ICONO = (35.4, 4.8)

#: El ícono de la pestaña: los cortes caen en la rejilla de 16 px para que salgan nítidos.
A_FAVICON = _a(arriba=8, abajo=56, ancho=48, punta=10, grosor=12, linea_y=36, linea_alto=8, aire=4)
LINEA_FAVICON = (36, 8)

#: La palabra dibujada: no depende de la letra de ningún teléfono. Las A van sin
#: travesaño, como la de la marca, y la V es su espejo. Solo M, L, H, V, C y Z absolutas.
PALABRA = (
    "M0 40L10.6 0H20.4L31 40H22.4L15.5 13.2L8.6 40Z"  # A
    "M35 40V0H43L54 22.4V0H61.8V40H53.8L42.8 17.6V40Z"  # N
    "M81.9 -0.6C90.5 -0.6 95.9 4.6 96.7 12.6H88.6C88 8.8 85.7 6.6 82 6.6C77.1 6.6 74.5 11 74.5 20"
    "C74.5 29 77.1 33.4 82.1 33.4C86.3 33.4 89 30.8 89.3 26.2H81.9V19.8H96.9V40H90.7L90.2 35.4"
    "C88.7 38.8 85.5 40.6 81.1 40.6C72.3 40.6 66.5 33 66.5 20C66.5 7 72.5 -0.6 81.9 -0.6Z"  # G
    "M101.5 40L112.1 0H121.9L132.5 40H123.9L117 13.2L110.1 40Z"  # A
    "M136.5 0H150.9C158.9 0 163.5 3.8 163.5 10.2C163.5 14.2 161.5 17.2 158.1 18.6"
    "C162.3 19.8 164.9 23.2 164.9 28C164.9 35.4 159.9 40 151.3 40H136.5Z"
    "M144.3 6.6V16.8H149.9C153.5 16.8 155.5 15 155.5 11.7C155.5 8.4 153.5 6.6 149.9 6.6Z"
    "M144.3 23.2V33.4H150.5C154.3 33.4 156.5 31.6 156.5 28.3C156.5 25 154.3 23.2 150.5 23.2Z"  # B
    "M168.5 40L179.1 0H188.9L199.5 40H190.9L184 13.2L177.1 40Z"  # A
    "M201.5 0H210.1L217 26.8L223.9 0H232.5L221.9 40H212.1Z"  # V
    "M236.5 0H259.5V7H244.3V16H257.9V23H244.3V33H259.9V40H236.5Z"  # E
)
#: La caja de la palabra, con un margen de 1 arriba y abajo para lo redondo de la G.
ANCHO_PALABRA, ALTO_PALABRA = 260, 42


def _ruta(*piezas) -> str:
    return "".join("M" + "L".join(f"{x:g} {y:g}" for x, y in pieza) + "Z" for pieza in piezas)


def ruta_a() -> str:
    return _ruta(*A)


def ruta_linea() -> str:
    return _ruta(LINEA)


def rutas() -> dict[str, str]:
    """Las rutas, para dibujarlas en canvas con Path2D."""
    return {"a": ruta_a(), "linea": ruta_linea(), "palabra": PALABRA}


def svg(clase: str = "marca-svg") -> str:
    """La marca. La A toma el color del texto; la línea se puede pintar con .marca-linea."""
    return (
        f'<svg class="{clase}" viewBox="0 0 64 64" aria-hidden="true" focusable="false">'
        f'<path fill="currentColor" d="{ruta_a()}"/>'
        f'<path class="marca-linea" fill="{ORO}" d="{ruta_linea()}"/>'
        "</svg>"
    )


def palabra(clase: str = "marca-palabra") -> str:
    """ANGABAVE dibujada, del color del texto."""
    return (
        f'<svg class="{clase}" viewBox="0 -1 {ANCHO_PALABRA} {ALTO_PALABRA}" aria-hidden="true" focusable="false">'
        f'<path fill="currentColor" fill-rule="evenodd" d="{PALABRA}"/>'
        "</svg>"
    )


def favicon() -> str:
    """El ícono de la pestaña, como data URI: el sitio no pide archivos aparte."""
    y, alto = LINEA_FAVICON
    marcado = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        f'<rect width="64" height="64" rx="12" fill="{NEGRO}"/>'
        f'<path fill="{CAMPO}" d="M0 {y}V12A12 12 0 0 1 12 0H52A12 12 0 0 1 64 12V{y}Z"/>'
        f'<rect y="{y}" width="64" height="{alto}" fill="{ORO}"/>'
        f'<path fill="{BLANCO}" d="{_ruta(*A_FAVICON)}"/>'
        "</svg>"
    )
    # Codificado completo: dentro de un atributo HTML no puede ir ni una comilla.
    return "data:image/svg+xml," + quote(marcado, safe="")


def poligonos_de_palabra(pasos: int = 16) -> list[list[tuple[float, float]]]:
    """La palabra aplanada en polígonos, para dibujarla con Pillow.

    Los huecos de la B salen como polígonos aparte: se rellena par e impar.
    """
    poligonos: list[list[tuple[float, float]]] = []
    actual: list[tuple[float, float]] = []
    x = y = 0.0
    fichas = re.findall(r"[MLHVCZ]|-?\d*\.?\d+", PALABRA)
    i = 0
    while i < len(fichas):
        orden = fichas[i]
        i += 1
        if orden == "Z":
            poligonos.append(actual)
            actual = []
            continue
        cuantos = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6}[orden]
        n = [float(valor) for valor in fichas[i:i + cuantos]]
        i += cuantos
        if orden == "C":
            for paso in range(1, pasos + 1):
                t = paso / pasos
                u = 1 - t
                actual.append((
                    u ** 3 * x + 3 * u * u * t * n[0] + 3 * u * t * t * n[2] + t ** 3 * n[4],
                    u ** 3 * y + 3 * u * u * t * n[1] + 3 * u * t * t * n[3] + t ** 3 * n[5],
                ))
            x, y = n[4], n[5]
            continue
        if orden == "H":
            x = n[0]
        elif orden == "V":
            y = n[0]
        else:
            x, y = n
        actual.append((x, y))
    return poligonos


def para_canvas() -> dict:
    """Lo que necesita la página para dibujar la marca en la imagen de picks."""
    return {"rutas": rutas(), "blanco": BLANCO, "oro": ORO, "alto_palabra": ALTO_PALABRA}
