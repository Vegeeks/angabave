"""La marca de ANGABAVE, en un solo lugar.

Una A atlética —vértice recto, piernas cortadas en plano— con un balón de
travesaño: se lee como "A" y como fútbol americano aun a 16 px.

La geometría vive aquí, en un espacio de 64 × 64, y de aquí salen todas sus
copias: el SVG del encabezado, el ícono de la pestaña, el dibujo en canvas de
la imagen de picks y los íconos de la app (render_png). Si se cambia algo, se
cambia aquí y nada se desalinea.
"""

from __future__ import annotations

from urllib.parse import quote

__all__ = [
    "A", "BALON", "COSTURAS", "ORO", "LOSETA", "TINTA",
    "GROSOR_CONTORNO", "GROSOR_COSTURA",
    "ruta_a", "ruta_balon", "ruta_costuras", "svg", "favicon", "rutas",
]

#: La A: un solo polígono, del pie izquierdo al pie derecho por el hueco central.
A = ((13.2, 52.5), (29.4, 12.6), (34.6, 12.6), (50.8, 52.5), (42.4, 52.5), (32.0, 25.2), (21.6, 52.5))
#: El balón: dos curvas cúbicas que se cruzan en las puntas.
#: (inicio, control, control, punta, control, control) y de vuelta al inicio.
BALON = ((18.3, 37.6), (22.9, 31.3), (41.1, 31.3), (45.7, 37.6), (41.1, 43.9), (22.9, 43.9))
#: La costura larga y las tres cortas.
COSTURAS = (
    ((25.8, 37.6), (38.2, 37.6)),
    ((28.8, 35.4), (28.8, 39.8)),
    ((32.0, 35.4), (32.0, 39.8)),
    ((35.2, 35.4), (35.2, 39.8)),
)
GROSOR_CONTORNO = 2.4
GROSOR_COSTURA = 1.55

#: Los colores: planos a propósito, sin brillos ni relieve. El amarillo es el de la
#: línea de primera y diez. Oro de arriba a abajo, loseta en diagonal y tinta.
ORO = ("#ffd60a", "#ffd60a", "#ffd60a")
LOSETA = ("#0c120f", "#0c120f")
TINTA = "#0c120f"


def _n(valor: float) -> str:
    return f"{valor:g}"


def ruta_a() -> str:
    inicio, *resto = A
    return "M" + " ".join(f"{_n(x)} {_n(y)}" for x, y in [inicio]) + "L" + "L".join(
        f"{_n(x)} {_n(y)}" for x, y in resto
    ) + "Z"


def ruta_balon() -> str:
    p0, c1, c2, p1, c3, c4 = BALON
    par = lambda p: f"{_n(p[0])} {_n(p[1])}"  # noqa: E731
    return f"M{par(p0)}C{par(c1)} {par(c2)} {par(p1)}C{par(c3)} {par(c4)} {par(p0)}Z"


def ruta_costuras() -> str:
    return "".join(f"M{_n(a[0])} {_n(a[1])}L{_n(b[0])} {_n(b[1])}" for a, b in COSTURAS)


def rutas() -> dict[str, str]:
    """Las tres rutas, para dibujarlas en canvas con Path2D."""
    return {"a": ruta_a(), "balon": ruta_balon(), "costuras": ruta_costuras()}


def svg(id_base: str = "marca", *, loseta: bool = True, clase: str = "marca-svg") -> str:
    """El SVG de la marca. `id_base` evita que dos copias compartan degradados."""
    oro, fondo = f"{id_base}-oro", f"{id_base}-loseta"
    partes = [
        f'<svg class="{clase}" viewBox="0 0 64 64" aria-hidden="true" focusable="false">',
        "<defs>",
        f'<linearGradient id="{oro}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{ORO[0]}"/><stop offset=".55" stop-color="{ORO[1]}"/>'
        f'<stop offset="1" stop-color="{ORO[2]}"/></linearGradient>',
        f'<linearGradient id="{fondo}" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="{LOSETA[0]}"/><stop offset="1" stop-color="{LOSETA[1]}"/>'
        "</linearGradient>",
        "</defs>",
    ]
    if loseta:
        partes.append(
            f'<rect x="1" y="1" width="62" height="62" rx="15" fill="url(#{fondo})" '
            f'stroke="{ORO[1]}" stroke-opacity=".3"/>'
        )
    partes += [
        f'<path d="{ruta_a()}" fill="url(#{oro})"/>',
        f'<path d="{ruta_balon()}" fill="url(#{oro})" stroke="{TINTA}" '
        f'stroke-width="{_n(GROSOR_CONTORNO)}" stroke-linejoin="round"/>',
        f'<path d="{ruta_costuras()}" stroke="{TINTA}" stroke-width="{_n(GROSOR_COSTURA)}" '
        'stroke-linecap="round" fill="none"/>',
        "</svg>",
    ]
    return "".join(partes)


def favicon() -> str:
    """El ícono de la pestaña, como data URI: el sitio no pide archivos aparte."""
    marcado = svg("f", clase="f").replace(' class="f"', ' xmlns="http://www.w3.org/2000/svg"')
    # Codificado completo: dentro de un atributo HTML no puede ir ni una comilla.
    return "data:image/svg+xml," + quote(marcado, safe="")


def _alto_del_balon() -> tuple[float, float]:
    """Arriba y abajo reales del balón: las curvas no llegan a sus controles."""
    p0, c1, c2, p1, c3, c4 = BALON
    ys = []
    for (a, b, c, d) in ((p0, c1, c2, p1), (p1, c3, c4, p0)):
        for paso in range(101):
            t = paso / 100
            u = 1 - t
            ys.append(u ** 3 * a[1] + 3 * u * u * t * b[1] + 3 * u * t * t * c[1] + t ** 3 * d[1])
    return round(min(ys), 2), round(max(ys), 2)


def para_canvas() -> dict:
    """Lo que necesita la página para dibujar la marca en la imagen de picks."""
    return {
        "rutas": rutas(),
        "oro": list(ORO),
        "loseta": list(LOSETA),
        "tinta": TINTA,
        "contorno": GROSOR_CONTORNO,
        "costura": GROSOR_COSTURA,
        "alto_a": [min(y for _, y in A), max(y for _, y in A)],
        "alto_balon": list(_alto_del_balon()),
    }
