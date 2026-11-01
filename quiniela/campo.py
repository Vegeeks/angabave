"""El campo del portal: una toma de transmisión dibujada con geometría.

Todo se calcula en yardas sobre el pasto y se proyecta con una cámara de verdad.
Lo que queda en la página son polígonos ya en perspectiva: por eso las líneas salen
nítidas en cualquier pantalla, adelgazan con la distancia y no hay capas 3D en reposo.

Hay dos dibujos del mismo estadio:

* ``.plano``: la toma quieta, ya proyectada. Una para teléfono y otra para compu.
* ``.vuelo``: el pasto en yardas, sin proyectar. Solo se enciende al llegar (y en un
  touchdown): el navegador lo mueve con ``transform`` y al terminar se cruza con la
  toma quieta, que cae exactamente encima porque sale de la misma cámara.

Ejes: X a lo ancho (la banda izquierda es negativa), Y a lo largo (el medio campo es
0 y la zona de anotación lejana empieza en 50), Z hacia arriba. Todo en yardas.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

RUTA_CONTORNOS = Path(__file__).resolve().parent / "tipografia" / "contornos.json"
GLIFOS: dict[str, list] = json.loads(RUTA_CONTORNOS.read_text(encoding="utf-8"))
#: Alto de las mayúsculas en unidades de la fuente.
ALTO_CAP = 810.0

# --- medidas del campo -------------------------------------------------------
ANCHO = 53.33
MEDIO = ANCHO / 2
#: La zona lejana es más honda que la real: desde esta cámara, 10 yardas se aplastan
#: tanto que las letras se leerían mal. Es lo que hacen las letras pintadas en el asfalto.
HONDO_ZONA = 15.0
ALTO_LETRA = 12.0
LARGO_PALABRA = 41.0
#: El ancho que puede tomar una letra suelta, para que JETS no se estire de más.
ESCALA_X_MAX = 0.0126
GROSOR_YARDA = 0.17
GROSOR_GOL = 0.5
GROSOR_BORDE = 1.3
GROSOR_TRANSMISION = 0.36
#: Hasta dónde llegan las líneas de la transmisión.
YARDA_PRIMERA = 40.5
YARDA_SCRIMMAGE = 36
#: Las cifras son más grandes que las reales, igual que en un paquete gráfico.
ALTO_CIFRA = 4.2
SEPARA_CIFRA = 0.42
#: Del pie de la cifra a la banda.
PIE_CIFRA = 9.0
#: Cuántos píxeles de .vuelo hay por yarda: lo justo para que no se vea borroso al
#: arrancar sin pedirle de más a la memoria del teléfono.
PIXELES_POR_YARDA = 11
PIXELES_POR_YARDA_COMPU = 24
#: Cuánto avanza la cámara en la carrera de un touchdown.
YARDAS_CARRERA = 11.0
#: Lo que abarca el pasto de .vuelo.
VUELO_X = 46.0
#: Este pasto empieza delante de la cámara en todo el vuelo: una capa que cruza el plano de la
#: cámara se dibuja distinto en cada navegador. Su orilla se pierde en lo oscuro y hay prueba.
VUELO_Y0 = 23.0
VUELO_Y1 = 82.0


@dataclass(frozen=True)
class Camara:
    """Una cámara con su lente, en yardas y grados. El centro óptico va en píxeles."""

    x: float
    y: float
    h: float
    rumbo: float        # hacia dónde gira: negativo es a la izquierda
    picada: float       # cuánto mira hacia abajo
    f: float
    u0: float
    v0: float

    def _ejes(self):
        ry, rp = math.radians(self.rumbo), math.radians(self.picada)
        frente = (math.sin(ry) * math.cos(rp), math.cos(ry) * math.cos(rp), -math.sin(rp))
        derecha = (math.cos(ry), -math.sin(ry), 0.0)
        arriba = (math.sin(ry) * math.sin(rp), math.cos(ry) * math.sin(rp), math.cos(rp))
        return derecha, arriba, frente

    def a_camara(self, p):
        z = p[2] if len(p) > 2 else 0.0
        d = (p[0] - self.x, p[1] - self.y, z - self.h)
        return tuple(sum(d[i] * eje[i] for i in range(3)) for eje in self._ejes())

    def a_pantalla(self, q):
        return self.u0 + self.f * q[0] / q[2], self.v0 - self.f * q[1] / q[2]

    def punto(self, p):
        return self.a_pantalla(self.a_camara(p))

    def homografia(self) -> list[float]:
        """Los ocho números que llevan un punto del pasto a la pantalla (el noveno es 1)."""
        (rx, ry, rz), (ax, ay, az), (fx, fy, fz) = self._ejes()
        # Para z = 0: xc = rx·X + ry·Y + c1; lo mismo para yc y zc.
        c1 = -(rx * self.x + ry * self.y + rz * self.h)
        c2 = -(ax * self.x + ay * self.y + az * self.h)
        c3 = -(fx * self.x + fy * self.y + fz * self.h)
        num_x = [self.u0 * fx + self.f * rx, self.u0 * fy + self.f * ry, self.u0 * c3 + self.f * c1]
        num_y = [self.v0 * fx - self.f * ax, self.v0 * fy - self.f * ay, self.v0 * c3 - self.f * c2]
        return [round(v / c3, 7) for v in (*num_x, *num_y, fx, fy)]


def encuadrar(h, rumbo, f, horizonte, v0, mundo, pantalla, u0) -> Camara:
    """La cámara de altura `h` con el horizonte en y=`horizonte` que pone `mundo` en `pantalla`."""
    picada = math.degrees(math.atan((v0 - horizonte) / f))
    x, y = 0.0, mundo[1] - 30.0
    for _ in range(40):
        c = Camara(x, y, h, rumbo, picada, f, u0, v0)
        p = c.punto(mundo)
        e = 1e-3
        dx = Camara(x + e, y, h, rumbo, picada, f, u0, v0).punto(mundo)
        dy = Camara(x, y + e, h, rumbo, picada, f, u0, v0).punto(mundo)
        a, b = (dx[0] - p[0]) / e, (dy[0] - p[0]) / e
        c_, d = (dx[1] - p[1]) / e, (dy[1] - p[1]) / e
        rx, ry = pantalla[0] - p[0], pantalla[1] - p[1]
        det = a * d - b * c_
        x += (d * rx - b * ry) / det
        y += (-c_ * rx + a * ry) / det
    return Camara(x, y, h, rumbo, picada, f, u0, v0)


# --- de polígonos a trazos ---------------------------------------------------

CERCA = 0.5


def _recorta_cerca(pol):
    sal = []
    for i, a in enumerate(pol):
        b = pol[(i + 1) % len(pol)]
        dentro_a, dentro_b = a[2] >= CERCA, b[2] >= CERCA
        if dentro_a:
            sal.append(a)
        if dentro_a != dentro_b:
            t = (CERCA - a[2]) / (b[2] - a[2])
            sal.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, CERCA))
    return sal


def _recorta_caja(pol, x0, y0, x1, y1):
    def corte(pol, dentro, cruce):
        sal = []
        for i, a in enumerate(pol):
            b = pol[(i + 1) % len(pol)]
            if dentro(a):
                sal.append(a)
            if dentro(a) != dentro(b):
                sal.append(cruce(a, b))
        return sal

    def en_x(v):
        return lambda a, b: (v, a[1] + (b[1] - a[1]) * (v - a[0]) / (b[0] - a[0]))

    def en_y(v):
        return lambda a, b: (a[0] + (b[0] - a[0]) * (v - a[1]) / (b[1] - a[1]), v)

    for dentro, cruce in (
        (lambda p: p[0] >= x0, en_x(x0)),
        (lambda p: p[0] <= x1, en_x(x1)),
        (lambda p: p[1] >= y0, en_y(y0)),
        (lambda p: p[1] <= y1, en_y(y1)),
    ):
        if not pol:
            return pol
        pol = corte(pol, dentro, cruce)
    return pol


def _numero(v: int, dec: int) -> str:
    """Una cifra entera en centésimas (o lo que diga `dec`), lo más corta posible."""
    if v == 0:
        return "0"
    signo = "-" if v < 0 else ""
    v = abs(v)
    entero, resto = divmod(v, 10 ** dec)
    if not resto:
        return f"{signo}{entero}"
    frac = f"{resto:0{dec}d}".rstrip("0")
    return f"{signo}{entero if entero else ''}.{frac}"


def trazo(poligonos, dec: int = 2) -> str:
    """Polígonos a un `d` compacto de SVG, con coordenadas relativas."""
    m = 10 ** dec
    salida = []
    for pol in poligonos:
        puntos = []
        for x, y in pol:
            p = (round(x * m), round(y * m))
            if not puntos or p != puntos[-1]:
                puntos.append(p)
        if len(puntos) > 1 and puntos[0] == puntos[-1]:
            puntos.pop()
        if len(puntos) < 3:
            continue
        texto = f"M{_numero(puntos[0][0], dec)} {_numero(puntos[0][1], dec)}l"
        px, py = puntos[0]
        tira = ""
        for x, y in puntos[1:]:
            for v in (x - px, y - py):
                n = _numero(v, dec)
                # Sin espacio cuando el signo o el punto ya separan.
                tira += n if (not tira or n[0] == "-" or (n[0] == "." and "." in tira.rsplit(" ", 1)[-1].rsplit("-", 1)[-1])) else " " + n
            px, py = x, y
        salida.append(texto + tira + "z")
    return "".join(salida)


class _Lienzo:
    """Junta polígonos del mundo y los proyecta, recortados a la caja del dibujo."""

    def __init__(self, camara: Camara | None, caja):
        self.camara, self.caja, self.capas = camara, caja, {}

    def pol(self, capa, puntos):
        if self.camara:
            q = _recorta_cerca([self.camara.a_camara(p) for p in puntos])
            if len(q) < 3:
                return
            q = [self.camara.a_pantalla(p) for p in q]
        else:
            q = [(p[0], -p[1]) for p in puntos]
        q = _recorta_caja(q, *self.caja)
        if len(q) >= 3:
            self.capas.setdefault(capa, []).append(q)

    def d(self, capa, dec=2):
        return trazo(self.capas.get(capa, []), dec)


def _rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def contornos(letra: str):
    """El avance y los contornos de una letra, en unidades de la fuente."""
    avance, datos = GLIFOS[letra]
    salida = []
    for parte in datos.split("|"):
        nums = list(map(int, parte.split()))
        x = y = 0
        contorno = []
        for i in range(0, len(nums), 2):
            x += nums[i]
            y += nums[i + 1]
            contorno.append((x, y))
        salida.append(contorno)
    return avance, salida


def palabra_en_el_pasto(palabra: str):
    """Los contornos de la palabra pintada en la zona lejana, en yardas."""
    tracking = 26
    total = sum(GLIFOS[c][0] for c in palabra) + tracking * (len(palabra) - 1)
    sx = min(LARGO_PALABRA / total, ESCALA_X_MAX)
    sy = ALTO_LETRA / ALTO_CAP
    x = -total * sx / 2
    y0 = 50 + (HONDO_ZONA - ALTO_LETRA) / 2
    salida = []
    for c in palabra:
        avance, cs = contornos(c)
        for contorno in cs:
            salida.append([(x + gx * sx, y0 + gy * sy) for gx, gy in contorno])
        x += (avance + tracking) * sx
    return salida


def _campo(l: _Lienzo, y_min=-60.0):
    """Todo lo que va pintado en el pasto. `y_min` ahorra lo que queda detrás de la cámara."""
    l.pol("pasto", _rect(-MEDIO, max(y_min, -50), MEDIO, 50))
    y = -50
    k = 0
    while y < 50:
        if k % 2 == 0 and y + 5 > y_min:
            l.pol("franja", _rect(-MEDIO, y, MEDIO, y + 5))
        y += 5
        k += 1
    l.pol("zona", _rect(-MEDIO, 50, MEDIO, 50 + HONDO_ZONA))

    fondo = 50 + HONDO_ZONA
    for puntos in (
        _rect(-MEDIO - GROSOR_BORDE, max(y_min, -60), -MEDIO, fondo + GROSOR_BORDE),
        _rect(MEDIO, max(y_min, -60), MEDIO + GROSOR_BORDE, fondo + GROSOR_BORDE),
        _rect(-MEDIO, fondo, MEDIO, fondo + GROSOR_BORDE),
    ):
        l.pol("borde", puntos)
    l.pol("gol", _rect(-MEDIO, 50 - GROSOR_GOL / 2, MEDIO, 50 + GROSOR_GOL / 2))

    for y in range(-45, 50, 5):
        if y - 1 < y_min:
            continue
        l.pol("cal", _rect(-MEDIO + 0.67, y - GROSOR_YARDA / 2, MEDIO - 0.67, y + GROSOR_YARDA / 2))
    for y in range(-49, 50):
        if y % 5 == 0 or y - 1 < y_min:
            continue
        for x in (-3.08, 3.08, -MEDIO + 0.33, MEDIO - 0.33):
            l.pol("cal", _rect(x - 0.33, y - 0.07, x + 0.33, y + 0.07))
    l.pol("cal", _rect(-0.5, 47.93, 0.5, 48.07))

    _cifras(l, y_min)

    # Las diagonales a los costados de la palabra.
    margen = LARGO_PALABRA / 2 + 1.0
    for lado in (-1, 1):
        k = 0
        while True:
            xa = lado * (margen + k * 2.1)
            if abs(xa) > MEDIO + HONDO_ZONA:
                break
            xb = xa + lado * 0.55
            d = lado * HONDO_ZONA
            puntos = [(xa, 50), (xb, 50), (xb + d, fondo), (xa + d, fondo)]
            puntos = _corta_banda(puntos, lado * MEDIO, lado)
            if len(puntos) >= 3:
                l.pol("raya", puntos)
            k += 1

    for x in (-MEDIO, MEDIO):
        for y in (50, fondo):
            l.pol("pilon", [(x - 0.22, y, 0), (x + 0.22, y, 0), (x + 0.22, y, 1.7), (x - 0.22, y, 1.7)])

    l.pol("azul", _rect(-MEDIO, YARDA_SCRIMMAGE - GROSOR_TRANSMISION / 2, MEDIO, YARDA_SCRIMMAGE + GROSOR_TRANSMISION / 2))
    l.pol("primera", _rect(-MEDIO, YARDA_PRIMERA - GROSOR_TRANSMISION / 2, MEDIO, YARDA_PRIMERA + GROSOR_TRANSMISION / 2))


def _corta_banda(puntos, limite, sentido):
    sal = []
    for i, p in enumerate(puntos):
        q = puntos[(i + 1) % len(puntos)]
        dentro_p, dentro_q = (p[0] - limite) * sentido <= 0, (q[0] - limite) * sentido <= 0
        if dentro_p:
            sal.append(p)
        if dentro_p != dentro_q:
            t = (limite - p[0]) / (q[0] - p[0])
            sal.append((limite, p[1] + (q[1] - p[1]) * t))
    return sal


def _cifras(l: _Lienzo, y_min):
    """Las yardas, de lado como en un campo de verdad: cada cifra a un lado de su línea."""
    s = ALTO_CIFRA / ALTO_CAP
    for yl in range(-40, 50, 10):
        if yl - 4 < y_min:
            continue
        valor = 50 - abs(yl)
        for lado in (-1, 1):
            xb = lado * (MEDIO - PIE_CIFRA)
            for i, cifra in enumerate(str(valor)):
                avance, cs = contornos(cifra)
                inicio = -(avance * s) - SEPARA_CIFRA if i == 0 else SEPARA_CIFRA
                for c in cs:
                    if lado < 0:
                        # Se lee parado en la banda izquierda: su derecha es -Y.
                        l.pol("cifra", [(xb + gy * s, yl - (inicio + gx * s)) for gx, gy in c])
                    else:
                        l.pol("cifra", [(xb - gy * s, yl + (inicio + gx * s)) for gx, gy in c])
            if valor != 50:
                # La flecha apunta a la meta más cercana.
                hacia = 1 if yl > 0 else -1
                ya = yl + hacia * (ALTO_CIFRA * 0.74)
                xm = lado * (MEDIO - PIE_CIFRA - ALTO_CIFRA * 0.5)
                l.pol("cifra", [(xm - 0.8, ya), (xm + 0.8, ya), (xm, ya + hacia * 1.5)])


def _estadio(l: _Lienzo):
    """Lo que rodea al campo: el piso oscuro y la tribuna de enfrente, un plano liso."""
    l.pol("fuera", _rect(-300, -300, 300, 300))
    l.pol("grada", [(-420, 84, 0), (420, 84, 0), (420, 300, 90), (-420, 300, 90)])


def _torre(x, y, ancho, columnas=9, filas=3, gira=2.0):
    """Un banco de focos: una rejilla de puntos nítidos, inclinada como las yardas."""
    a = math.radians(gira)
    ca, sa = math.cos(a), math.sin(a)
    celda = ancho / columnas
    lado = celda * 0.62
    salida = []
    for fila in range(filas):
        for col in range(columnas):
            u = (col - (columnas - 1) / 2) * celda
            v = (fila - (filas - 1) / 2) * celda
            cx, cy = x + u * ca - v * sa, y + u * sa + v * ca
            salida.append([(cx - lado / 2, cy - lado / 2), (cx + lado / 2, cy - lado / 2),
                           (cx + lado / 2, cy + lado / 2), (cx - lado / 2, cy + lado / 2)])
    return salida


# --- las dos cámaras ---------------------------------------------------------
#
# El teléfono se diseña a 390 px de ancho: la marca y tu avance llegan hasta el ancla
# (y=121), la palabra cae justo debajo y el horizonte queda detrás de la marca. En compu
# el dibujo va centrado y la palabra se recarga a la derecha del titular.

ANCLA_X_TELEFONO, ANCLA_Y_TELEFONO = 195.0, 121.0
CAMARA_TELEFONO = encuadrar(13.6, -13.0, 300.0, 34.0, 190.0, (0.0, 57.5), (195.0, 147.0), 195.0)
CAJA_TELEFONO = (-260.0, -110.0, 650.0, 660.0)
POZA_TELEFONO = (215.0, 154.0, 300.0, 86.0)
#: De dónde arranca el vuelo: desde arriba de la zona de anotación, con la palabra entera y girada.
_INICIO_T = encuadrar(33.0, -34.0, 300.0, -330.0, 190.0, (0.0, 57.5), (188.0, 300.0), 195.0)
INICIO_TELEFONO = (_INICIO_T.x, _INICIO_T.y, _INICIO_T.h, _INICIO_T.rumbo, _INICIO_T.picada, _INICIO_T.f)
#: Torres: centro, halo (dos radios y su fuerza) y ancho del banco de focos.
TORRES_TELEFONO = (
    (284.0, 20.0, 104.0, 54.0, 0.42, 40.0),
    (224.0, 15.0, 70.0, 36.0, 0.26, 26.0),
)
#: Haces: de dónde sale y los dos puntos donde toca el piso, con su fuerza.
HACES_TELEFONO = (
    (284.0, 24.0, 140.0, 128.0, 346.0, 134.0, 0.16),
    (224.0, 18.0, 84.0, 124.0, 262.0, 128.0, 0.1),
)

ANCLA_X_COMPU, ANCLA_Y_COMPU = 0.0, 121.0
CAMARA_COMPU = encuadrar(14.5, -33.0, 640.0, -40.0, 170.0, (0.0, 57.5), (290.0, 134.0), 0.0)
CAJA_COMPU = (-1100.0, -60.0, 1100.0, 560.0)
POZA_COMPU = (340.0, 140.0, 560.0, 150.0)
_INICIO_C = encuadrar(34.0, -52.0, 640.0, -900.0, 170.0, (0.0, 57.5), (120.0, 300.0), 0.0)
INICIO_COMPU = (_INICIO_C.x, _INICIO_C.y, _INICIO_C.h, _INICIO_C.rumbo, _INICIO_C.picada, _INICIO_C.f)
TORRES_COMPU = (
    (150.0, 74.0, 150.0, 70.0, 0.4, 56.0),
    (40.0, 66.0, 100.0, 48.0, 0.24, 34.0),
)
HACES_COMPU = (
    (150.0, 80.0, 70.0, 124.0, 250.0, 130.0, 0.12),
)


def _degradado(ident, origen, normal, tramo, paradas) -> str:
    """Un degradado a lo largo de `normal`, en distancias desde `origen`."""
    s0, s1 = tramo
    x1, y1 = origen[0] + normal[0] * s0, origen[1] + normal[1] * s0
    x2, y2 = origen[0] + normal[0] * s1, origen[1] + normal[1] * s1
    filas = ""
    for s, color, alfa in paradas:
        op = "" if alfa == 1 else f";stop-opacity:{alfa}"
        filas += f'<stop offset="{(s - s0) / (s1 - s0):.4f}" style="stop-color:{color}{op}"/>'
    return (f'<linearGradient id="{ident}" gradientUnits="userSpaceOnUse" '
            f'x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}">{filas}</linearGradient>')


def _palabra_proyectada(camara: Camara, palabra: str):
    return [[camara.punto(p) for p in c] for c in palabra_en_el_pasto(palabra)]


@dataclass(frozen=True)
class Luz:
    """Por dónde cae la luz en una toma. Todo se mide a lo largo de una dirección en pantalla.

    La línea de gol y el borde se apagan en `corte_gol`, medido desde la línea de gol. Las yardas,
    las cifras y las líneas de la transmisión siguen `eje`: encendidas antes de `cortes[0]`, ya
    tenues en `cortes[1]` (ahí puede ir un titular) y casi apagadas entre `cortes[2]` y
    `cortes[3]` (ahí puede ir un párrafo). El pasto pasa de claro a oscuro en `corte_pasto`.
    """

    corte_gol: tuple[float, float]
    eje: tuple | None
    cortes: tuple[float, float, float, float]
    corte_pasto: tuple[float, float]


LUZ_TELEFONO = Luz((1.5, 5.0), None, (1.5, 5.0, 74.0, 112.0), (-2.0, 46.0))
#: En compu el texto se queda a la izquierda: la luz baja en diagonal y a la derecha todo sigue encendido.
LUZ_COMPU = Luz((1.5, 6.0), ((300.0, 210.0), (-0.74, 0.673)), (0.0, 46.0, 420.0, 640.0), (-20.0, 60.0))


def _toma(camara: Camara, caja, sufijo: str, clase: str, luz: Luz, x_gol: float, poza) -> str:
    """La toma quieta: lo que se ve en reposo, ya en perspectiva."""
    l = _Lienzo(camara, caja)
    _estadio(l)
    _campo(l, y_min=camara.y - 8)

    gol = _normal_del_gol(camara, x_gol)
    origen, normal = luz.eje or gol
    ini, fin, baja, honda = luz.cortes
    tramo = (-900.0, 1300.0)

    def rampa(nombre, lejos, cerca, a_honda=1):
        paradas = [(tramo[0], lejos, 1), (ini, lejos, 1), (fin, cerca, 1), (baja, cerca, 1), (honda, cerca, a_honda), (tramo[1], cerca, a_honda)]
        return _degradado(f"cp-{nombre}{sufijo}", origen, normal, tramo, paradas)

    p0, p1 = luz.corte_pasto
    defs = [
        _degradado(f"cp-grada{sufijo}", (0.0, 0.0), (0.0, 1.0), (caja[1], caja[3]), [
            (caja[1], "var(--bg)", 1), (caja[1] + 90, "var(--bg)", 1), (gol[0][1] - 40, "var(--grada)", 1), (caja[3], "var(--grada)", 1)]),
        _degradado(f"cp-pasto{sufijo}", origen, normal, tramo, [
            (tramo[0], "var(--pasto-luz)", 1), (p0, "var(--pasto-luz)", 1), (p1, "var(--pasto)", 1), (tramo[1], "var(--pasto)", 1)]),
        _degradado(f"cp-franja{sufijo}", origen, normal, tramo, [
            (tramo[0], "#fff", 0.05), (p0, "#fff", 0.05), (p1, "#fff", 0.018), (tramo[1], "#fff", 0.018)]),
        _degradado(f"cp-gol{sufijo}", gol[0], gol[1], tramo, [
            (tramo[0], "#fff", 1), (luz.corte_gol[0], "#fff", 1), (luz.corte_gol[1], "var(--cal)", 1), (tramo[1], "var(--cal)", 1)]),
        rampa("cal", "#fff", "var(--cal)", 0.38),
        rampa("cifra", "#fff", "var(--cal2)", 0.42),
        rampa("prim", "var(--primera)", "var(--primera2)", 0.2),
        rampa("azul", "var(--scrim)", "var(--scrim2)", 0.2),
        (f'<radialGradient id="cp-poza{sufijo}" gradientUnits="userSpaceOnUse" cx="0" cy="0" r="1" '
         f'gradientTransform="translate({poza[0]:g} {poza[1]:g}) scale({poza[2]:g} {poza[3]:g})">'
         '<stop offset="0" style="stop-color:var(--pasto-luz);stop-opacity:.95"/>'
         '<stop offset=".55" style="stop-color:var(--pasto-luz);stop-opacity:.4"/>'
         '<stop offset="1" style="stop-color:var(--pasto-luz);stop-opacity:0"/></radialGradient>'),
    ]
    x0, y0, x1, y1 = caja
    palabra = ""   # la zona la pinta el guion con el equipo o el nombre
    capas = [
        f'<path class="cp-fuera" d="{l.d("fuera", 1)}"/>',
        f'<path fill="url(#cp-grada{sufijo})" d="{l.d("grada", 1)}"/>',
        f'<path fill="url(#cp-pasto{sufijo})" d="{l.d("pasto", 1)}"/>',
        f'<path fill="url(#cp-franja{sufijo})" d="{l.d("franja", 1)}"/>',
        f'<path class="cp-zona" d="{l.d("zona", 1)}"/>',
        f'<path fill="url(#cp-poza{sufijo})" d="{l.d("zona", 1)}"/>',
        f'<path class="cp-raya" d="{l.d("raya")}"/>',
        f'<path fill="url(#cp-cal{sufijo})" d="{l.d("cal")}"/>',
        f'<path fill="url(#cp-gol{sufijo})" d="{l.d("borde")}{l.d("gol")}"/>',
        f'<path fill="url(#cp-cifra{sufijo})" d="{l.d("cifra")}"/>',
        f'<path class="cp-palabra" id="cp-palabra{sufijo}" d="{palabra}"/>',
        f'<path class="cp-pilon" d="{l.d("pilon")}"/>',
        f'<path fill="url(#cp-azul{sufijo})" d="{l.d("azul")}"/>',
        f'<path fill="url(#cp-prim{sufijo})" d="{l.d("primera")}"/>',
    ]
    return (f'<svg class="plano {clase}" viewBox="{x0:g} {y0:g} {x1 - x0:g} {y1 - y0:g}" aria-hidden="true" focusable="false">'
            f'<defs>{"".join(defs)}</defs>{"".join(capas)}</svg>')


def _haz(ident, x0, y0, x1, y1, x2, y2, alfa):
    """Un haz de luz: un triángulo de orillas limpias que se apaga al llegar al piso."""
    defs = (f'<linearGradient id="{ident}" gradientUnits="userSpaceOnUse" x1="{x0:g}" y1="{y0:g}" '
            f'x2="{(x1 + x2) / 2:g}" y2="{(y1 + y2) / 2:g}">'
            f'<stop offset="0" style="stop-color:var(--haz);stop-opacity:{alfa}"/>'
            '<stop offset="1" style="stop-color:var(--haz);stop-opacity:0"/></linearGradient>')
    return defs, f'<path fill="url(#{ident})" d="M{x0:g} {y0:g}L{x1:g} {y1:g}L{x2:g} {y2:g}z"/>'


def _luces(caja, sufijo, clase, torres, haces) -> str:
    """Los focos y sus haces: una capa aparte para poder prenderlos al llegar."""
    x0, y0, x1, y1 = caja
    defs, trazos = [], []
    for i, (x, y, rx, ry, alfa) in enumerate(t[:5] for t in torres):
        defs.append(f'<radialGradient id="cp-halo{sufijo}{i}" gradientUnits="userSpaceOnUse" cx="0" cy="0" r="1" '
                    f'gradientTransform="translate({x:g} {y:g}) scale({rx:g} {ry:g})">'
                    f'<stop offset="0" style="stop-color:var(--haz);stop-opacity:{alfa}"/>'
                    f'<stop offset=".4" style="stop-color:var(--haz);stop-opacity:{alfa * .3:.3f}"/>'
                    '<stop offset="1" style="stop-color:var(--haz);stop-opacity:0"/></radialGradient>')
        trazos.append(f'<ellipse cx="{x:g}" cy="{y:g}" rx="{rx:g}" ry="{ry:g}" fill="url(#cp-halo{sufijo}{i})"/>')
    for i, h in enumerate(haces):
        d, t = _haz(f"cp-haz{sufijo}{i}", *h)
        defs.append(d)
        trazos.append(t)
    focos = []
    for x, y, _rx, _ry, _alfa, ancho in torres:
        focos += _torre(x, y, ancho)
    return (f'<svg class="luz {clase}" viewBox="{x0:g} {y0:g} {x1 - x0:g} {y1 - y0:g}" aria-hidden="true" focusable="false">'
            f'<defs>{"".join(defs)}</defs>{"".join(trazos)}<path class="cp-foco" d="{trazo(focos)}"/></svg>')


def _vuelo() -> str:
    """El pasto en yardas para el movimiento de cámara."""
    caja = (-VUELO_X, -VUELO_Y1, VUELO_X, -VUELO_Y0)
    l = _Lienzo(None, caja)
    l.pol("fuera", _rect(-VUELO_X, VUELO_Y0, VUELO_X, VUELO_Y1))
    _campo(l, y_min=VUELO_Y0)
    palabra = ""
    yy0, yy1 = -48.0, -VUELO_Y0

    def plano_luz(ident, lejos, cerca):
        return (f'<linearGradient id="{ident}" gradientUnits="userSpaceOnUse" x1="0" y1="{yy0:g}" x2="0" y2="{yy1:g}">'
                f'<stop offset="0" style="stop-color:{lejos}"/><stop offset=".55" style="stop-color:{cerca}"/>'
                '<stop offset="1" style="stop-color:var(--bg)"/></linearGradient>')

    defs = (plano_luz("cp-v-p", "var(--pasto-luz)", "var(--pasto)") + plano_luz("cp-v-c", "#fff", "var(--cal)")
            + plano_luz("cp-v-1", "var(--primera)", "var(--primera2)") + plano_luz("cp-v-2", "var(--scrim)", "var(--scrim2)"))
    capas = [
        f'<defs>{defs}</defs>',
        f'<path class="cp-fuera" d="{l.d("fuera")}"/>',
        f'<path fill="url(#cp-v-p)" d="{l.d("pasto")}"/>',
        f'<path class="cp-v-franja" d="{l.d("franja")}"/>',
        f'<path class="cp-zona" d="{l.d("zona")}"/>',
        f'<path class="cp-raya" d="{l.d("raya")}"/>',
        f'<path fill="url(#cp-v-c)" d="{l.d("borde")}{l.d("gol")}{l.d("cal")}{l.d("cifra")}"/>',
        f'<path class="cp-palabra" id="cp-palabra-v" d="{palabra}"/>',
        f'<path fill="url(#cp-v-2)" d="{l.d("azul")}"/>',
        f'<path fill="url(#cp-v-1)" d="{l.d("primera")}"/>',
    ]
    return (f'<div class="vuelo"><svg viewBox="{-VUELO_X:g} {-VUELO_Y1:g} {VUELO_X * 2:g} {VUELO_Y1 - VUELO_Y0:g}" '
            f'aria-hidden="true" focusable="false">{"".join(capas)}</svg></div>')


def _normal_del_gol(camara: Camara, x_centro: float):
    """Un punto de la línea de gol y la dirección que baja, perpendicular a ella en pantalla."""
    a = camara.punto((-MEDIO, 50.0))
    b = camara.punto((MEDIO, 50.0))
    dx, dy = b[0] - a[0], b[1] - a[1]
    largo = math.hypot(dx, dy)
    t = (x_centro - a[0]) / dx
    origen = (x_centro, a[1] + dy * t)
    return origen, (-dy / largo, dx / largo)


@lru_cache(maxsize=1)
def html() -> str:
    """Lo que va dentro de .cancha."""
    tel = _toma(CAMARA_TELEFONO, CAJA_TELEFONO, "t", "en-telefono", LUZ_TELEFONO, ANCLA_X_TELEFONO, POZA_TELEFONO)
    compu = _toma(CAMARA_COMPU, CAJA_COMPU, "c", "en-compu", LUZ_COMPU, 340.0, POZA_COMPU)
    luz_t = _luces(CAJA_TELEFONO, "t", "en-telefono", TORRES_TELEFONO, HACES_TELEFONO)
    luz_c = _luces(CAJA_COMPU, "c", "en-compu", TORRES_COMPU, HACES_COMPU)
    return tel + compu + _vuelo() + luz_t + luz_c


def poses_del_vuelo():
    """El principio y el fin del vuelo de cada toma: (x, y, h, rumbo, picada, f)."""
    fin = lambda c: (c.x, c.y, c.h, c.rumbo, c.picada, c.f)  # noqa: E731
    return ((INICIO_TELEFONO, fin(CAMARA_TELEFONO)), (INICIO_COMPU, fin(CAMARA_COMPU)))


def _css_pose(prefijo, pose) -> str:
    x, y, h, rumbo, picada, f = pose
    return (f"--{prefijo}-f:calc({f:g}*var(--u));--{prefijo}-rx:{90 - picada:.3f}deg;--{prefijo}-rz:{-rumbo:.3f}deg;"
            f"--{prefijo}-x:calc({-x:.3f}*var(--k));--{prefijo}-y:calc({y:.3f}*var(--k));--{prefijo}-z:calc({-h:.3f}*var(--k));")


def _css_carrera(c: Camara, caja) -> str:
    """La carrera de un touchdown: avanzar sobre el pasto es, en pantalla, abrirse desde el punto
    de fuga de la dirección de avance, tanto más cuanto más abajo del horizonte. Eso es matrix3d."""
    picada = math.radians(c.picada)
    horizonte = c.v0 - c.f * math.tan(picada)
    fuga_x = c.u0 + c.f * math.tan(math.radians(c.rumbo)) / math.cos(picada)
    fuerza = YARDAS_CARRERA * math.cos(math.radians(c.rumbo)) * math.cos(picada) ** 2 / (c.f * c.h)
    return (f"--carrera:{-fuerza:.5f};--fuga-x:calc({fuga_x - caja[0]:.1f}*var(--u));--fuga-y:calc({horizonte - caja[1]:.1f}*var(--u));")


def _css_camara(c: Camara, caja, inicio, ancla_x, ancla_y) -> str:
    final = (c.x, c.y, c.h, c.rumbo, c.picada, c.f)
    return (_css_pose("fin", final) + _css_pose("ini", inicio) + _css_carrera(c, caja)
            + f"--dx:calc({c.u0 - ancla_x:g}*var(--u));--dy:calc({c.v0 - ancla_y:g}*var(--u));")


def _css_caja(clase, caja, ancla_x, ancla_y) -> str:
    x0, y0, x1, y1 = caja
    return (f".plano.{clase},.luz.{clase}{{left:calc(50% + {x0 - ancla_x:g}*var(--u));"
            f"top:calc(var(--ancla) + {y0 - ancla_y:g}*var(--u));"
            f"width:calc({x1 - x0:g}*var(--u));height:calc({y1 - y0:g}*var(--u))}}")


def css() -> str:
    """Las poses de cada cámara y dónde va cada dibujo, en unidades de 1/390 de pantalla."""
    return (":root{" + f"--k:calc({PIXELES_POR_YARDA}*var(--u));"
            + _css_camara(CAMARA_TELEFONO, CAJA_TELEFONO, INICIO_TELEFONO, ANCLA_X_TELEFONO, ANCLA_Y_TELEFONO) + "}"
            + _css_caja("en-telefono", CAJA_TELEFONO, ANCLA_X_TELEFONO, ANCLA_Y_TELEFONO)
            + _css_caja("en-compu", CAJA_COMPU, ANCLA_X_COMPU, ANCLA_Y_COMPU)
            + f".vuelo svg{{left:calc({-VUELO_X:g}*var(--k));top:calc({-VUELO_Y1:g}*var(--k));"
            f"width:calc({VUELO_X * 2:g}*var(--k));height:calc({VUELO_Y1 - VUELO_Y0:g}*var(--k))}}"
            + ".cancha .en-compu{display:none}"
            + "@media (min-width:900px){.cancha .en-telefono{display:none}.cancha .en-compu{display:block}"
            + ":root{--k:calc(" + str(PIXELES_POR_YARDA_COMPU) + "*var(--u));" + _css_camara(CAMARA_COMPU, CAJA_COMPU, INICIO_COMPU, ANCLA_X_COMPU, ANCLA_Y_COMPU) + "}}")


def datos_pagina() -> dict:
    """Lo que necesita la página para pintar el nombre de un equipo en las dos tomas."""
    return {"glifos": GLIFOS, "h": {"t": CAMARA_TELEFONO.homografia(), "c": CAMARA_COMPU.homografia()},
            "zona": {"hondo": HONDO_ZONA, "alto": ALTO_LETRA, "largo": LARGO_PALABRA, "maxX": ESCALA_X_MAX, "cap": ALTO_CAP}}
