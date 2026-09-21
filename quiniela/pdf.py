"""Lectura del PDF de la quiniela.

El organizador arma la quiniela en Excel, pero lo que reparte suele ser un PDF
exportado de ahí. Ese PDF conserva la capa de texto, así que la rejilla se
reconstruye exacta —sin transcribir a ojo ni pasar por OCR— leyendo los
operadores de texto del propio formato.

Un PDF guarda su contenido en flujos comprimidos con zlib. Dentro, cada
fragmento de texto va entre `BT` y `ET`, posicionado con una matriz `Tm` y
escrito con `TJ`. Con la posición de cada fragmento se rearma la tabla.
"""

from __future__ import annotations

import logging
import re
import zlib
from collections import defaultdict
from pathlib import Path

__all__ = ["ErrorPDF", "extraer_rejilla"]

_log = logging.getLogger(__name__)

#: Tolerancia vertical para considerar que dos fragmentos van en la misma fila.
_TOLERANCIA_FILA = 2.0
#: Tolerancia horizontal para asignar un fragmento a una columna.
_TOLERANCIA_COLUMNA = 20.0
#: Los nombres de participante viven en el margen izquierdo.
_MARGEN_NOMBRES = 110.0

_RE_SEMANA = re.compile(r"semana\s*(\d{1,2})", re.IGNORECASE)


class ErrorPDF(ValueError):
    """El PDF no tiene la forma esperada."""


def _descomprimir(flujo: bytes) -> bytes:
    try:
        return zlib.decompress(flujo.strip(b"\r\n"))
    except zlib.error:
        return b""


def _limpiar(bruto: bytes) -> str:
    """Saca el texto de un arreglo TJ, quitando el interletrado."""
    piezas = re.findall(rb"\((?:\\.|[^\\()])*\)", bruto, re.S)
    texto = "".join(pieza[1:-1].decode("latin-1") for pieza in piezas)
    texto = re.sub(r"\\([()\\])", r"\1", texto)
    return re.sub(r"\\(\d{1,3})", lambda m: chr(int(m.group(1), 8)), texto).strip()


def _fragmentos(ruta: Path) -> list[tuple[float, float, str]]:
    """Devuelve (y, x, texto) de cada fragmento del PDF."""
    datos = ruta.read_bytes()
    contenido = b""
    for flujo in re.findall(rb"stream\r?\n(.*?)endstream", datos, re.S):
        candidato = _descomprimir(flujo)
        if b"TJ" in candidato:
            contenido = candidato
            break
    if not contenido:
        raise ErrorPDF(
            f"{ruta.name}: no encontré capa de texto. ¿Es un PDF escaneado o una imagen? "
            "Este lector no hace OCR; en ese caso hay que pedir el Excel."
        )

    fragmentos = []
    for bloque in re.findall(rb"BT(.*?)ET", contenido, re.S):
        matriz = re.search(rb"([\d.\-]+)\s+([\d.\-]+)\s+Tm", bloque)
        texto = re.search(rb"\[(.*?)\]\s*TJ", bloque, re.S)
        if matriz and texto:
            fragmentos.append((float(matriz.group(2)), float(matriz.group(1)), _limpiar(texto.group(1))))
    if not fragmentos:
        raise ErrorPDF(f"{ruta.name}: la capa de texto está vacía.")
    return fragmentos


def _agrupar_en_filas(fragmentos) -> dict[float, list[tuple[float, str]]]:
    filas: dict[float, list[tuple[float, str]]] = defaultdict(list)
    for y, x, texto in fragmentos:
        destino = next((k for k in filas if abs(k - y) <= _TOLERANCIA_FILA), round(y, 0))
        filas[destino].append((x, texto))
    return filas


def extraer_rejilla(ruta: Path) -> tuple[int, list[str], list[str], list[tuple[str, list[str]]]]:
    """Reconstruye la quiniela del PDF.

    Devuelve (semana, visitantes, locales, [(participante, picks)]), con los
    textos tal cual vienen: normalizarlos es tarea de `picks.py`.
    """
    ruta = Path(ruta)
    filas = _agrupar_en_filas(_fragmentos(ruta))
    alturas = sorted(filas, reverse=True)

    # La fila de locales es la que lleva "Semana N" en la primera columna.
    y_locales = None
    semana = None
    for altura in alturas:
        for x, texto in filas[altura]:
            if x < _MARGEN_NOMBRES:
                encontrado = _RE_SEMANA.search(texto)
                if encontrado:
                    y_locales, semana = altura, int(encontrado.group(1))
                    break
        if y_locales is not None:
            break
    if y_locales is None:
        raise ErrorPDF(
            f"{ruta.name}: no encontré la celda 'Semana N' que marca la fila de locales."
        )

    # Arriba de los locales hay fragmentos sueltos del encabezado; la fila de
    # visitantes es la que trae muchos equipos, no la más cercana.
    candidatas = [a for a in alturas if a > y_locales]
    if not candidatas:
        raise ErrorPDF(f"{ruta.name}: no hay ninguna fila arriba de la de locales.")
    y_visitantes = max(
        candidatas, key=lambda a: sum(1 for x, _ in filas[a] if x > _MARGEN_NOMBRES)
    )

    encabezado = sorted(filas[y_visitantes])
    visitantes = [t for x, t in encabezado if x > _MARGEN_NOMBRES]
    columnas = [x for x, _ in encabezado if x > _MARGEN_NOMBRES]
    if not visitantes:
        raise ErrorPDF(f"{ruta.name}: la fila de visitantes salió vacía.")

    # Todo lo que esté a la derecha del último partido es la columna de totales.
    limite_totales = max(columnas) + _TOLERANCIA_COLUMNA + 5
    locales = [t for x, t in sorted(filas[y_locales]) if _MARGEN_NOMBRES < x < limite_totales]

    if len(visitantes) != len(locales):
        raise ErrorPDF(
            f"{ruta.name}: leí {len(visitantes)} visitantes y {len(locales)} locales. "
            "El PDF no tiene la rejilla esperada."
        )

    participantes: list[tuple[str, list[str]]] = []
    for altura in alturas:
        if altura >= y_locales:
            continue
        orden = sorted(filas[altura])
        if not orden or orden[0][0] > _MARGEN_NOMBRES:
            continue
        nombre = orden[0][1]
        picks = [""] * len(visitantes)
        for x, texto in orden[1:]:
            if x >= limite_totales:
                continue  # columna "Aciertos Totales": se ignora
            distancias = [abs(x - columna) for columna in columnas]
            cercana = min(range(len(columnas)), key=distancias.__getitem__)
            if distancias[cercana] < _TOLERANCIA_COLUMNA:
                picks[cercana] = texto
        participantes.append((nombre, picks))

    if not participantes:
        raise ErrorPDF(f"{ruta.name}: no encontré participantes debajo de los enfrentamientos.")

    _log.info(
        "PDF %s: semana %d, %d partidos, %d participantes.",
        ruta.name, semana, len(visitantes), len(participantes),
    )
    return semana, visitantes, locales, participantes
