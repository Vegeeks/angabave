"""Lectura del Excel semanal de picks.

Formato del archivo (confirmado contra la Semana 2 real):

* Fila de visitantes y, justo debajo, fila de locales.  Cada columna es un
  partido.
* La columna A trae el nombre del participante; en la zona del encabezado dice
  "Semana N".
* De ahí para abajo, una fila por participante con sus picks.
* La última columna, "Aciertos Totales", se ignora por completo: viene
  precargada con valores incorrectos y es justo lo que este proyecto arregla.

El organizador arma el archivo en Excel pero suele repartir el PDF exportado.
Los dos se leen igual: cada formato se convierte a la misma rejilla y de ahí en
adelante pasan por las mismas validaciones.

Todo lo que huela a captura equivocada truena con el detalle completo en vez de
producir una tabla en silencio.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path

import openpyxl

from .equipos import EquipoDesconocidoError, normalizar
from .espn import Partido
from .pdf import ErrorPDF, extraer_rejilla

__all__ = [
    "ErrorPicks",
    "ErrorFormatoExcel",
    "clave_participante",
    "leer_picks",
    "numero_semana",
]

_log = logging.getLogger(__name__)

#: Título de la columna que hay que ignorar.
COLUMNA_IGNORADA = "Aciertos Totales"

#: Hasta dónde buscamos el encabezado antes de rendirnos.
_MAX_FILAS_ENCABEZADO = 12

_RE_SEMANA = re.compile(r"semana\s*_?\s*(\d{1,2})", re.IGNORECASE)


class ErrorPicks(ValueError):
    """El Excel se pudo abrir pero su contenido no es usable."""


class ErrorFormatoExcel(ErrorPicks):
    """No se reconoce la estructura del archivo."""


def _texto(valor: object) -> str:
    """Convierte una celda a texto limpio, con los espacios colapsados."""
    if valor is None:
        return ""
    if isinstance(valor, str):
        return " ".join(valor.split())
    return str(valor).strip()


def _sin_acentos(texto: str) -> str:
    return "".join(
        caracter
        for caracter in unicodedata.normalize("NFD", texto)
        if not unicodedata.combining(caracter)
    )


def clave_participante(nombre: str) -> str:
    """Identidad de un participante entre semanas.

    Sin acentos, sin espacios sobrantes y en minúsculas, para que "Angél" y
    "Angel" sean la misma persona en la tabla general.
    """
    return " ".join(_sin_acentos(nombre).split()).casefold()


def numero_semana(ruta: Path) -> int:
    """Extrae el número de semana del nombre del archivo."""
    coincidencia = _RE_SEMANA.search(ruta.stem)
    if coincidencia is None:
        raise ErrorPicks(
            f"No pude sacar el número de semana del nombre del archivo: {ruta.name!r}. "
            "Se espera algo como 'Semana_02.xlsx'."
        )
    return int(coincidencia.group(1))


def _es_fila_de_equipos(fila: tuple, columnas: range) -> bool:
    """¿Todas las celdas con contenido de esta fila son equipos válidos?"""
    valores = [_texto(fila[columna]) for columna in columnas if columna < len(fila)]
    con_contenido = [valor for valor in valores if valor]
    if len(con_contenido) < 2:
        return False
    for valor in con_contenido:
        try:
            normalizar(valor)
        except EquipoDesconocidoError:
            return False
    return True


def _localizar_columna_ignorada(filas: list[tuple]) -> int | None:
    objetivo = clave_participante(COLUMNA_IGNORADA)
    for fila in filas[:_MAX_FILAS_ENCABEZADO]:
        for indice, celda in enumerate(fila):
            if clave_participante(_texto(celda)) == objetivo:
                return indice
    return None


def _localizar_encabezado(filas: list[tuple], columnas: range) -> int:
    """Devuelve el índice de la fila de visitantes (la de locales es la siguiente)."""
    tope = min(_MAX_FILAS_ENCABEZADO, len(filas) - 1)
    for indice in range(tope):
        if _es_fila_de_equipos(filas[indice], columnas) and _es_fila_de_equipos(
            filas[indice + 1], columnas
        ):
            return indice
    raise ErrorFormatoExcel(
        "No encontré las dos filas de enfrentamientos (visitantes arriba, locales "
        f"abajo) en las primeras {_MAX_FILAS_ENCABEZADO} filas del archivo."
    )


def _semana_del_encabezado(filas: list[tuple], hasta: int) -> int | None:
    for fila in filas[: hasta + 2]:
        for celda in fila[:2]:
            coincidencia = _RE_SEMANA.search(_texto(celda))
            if coincidencia:
                return int(coincidencia.group(1))
    return None


def _leer_enfrentamientos(
    fila_visitantes: tuple, fila_locales: tuple, columnas: range
) -> tuple[list[Partido], list[int]]:
    partidos: list[Partido] = []
    columnas_de_partido: list[int] = []
    problemas: list[str] = []

    for columna in columnas:
        crudo_visitante = _texto(fila_visitantes[columna]) if columna < len(fila_visitantes) else ""
        crudo_local = _texto(fila_locales[columna]) if columna < len(fila_locales) else ""

        if not crudo_visitante and not crudo_local:
            continue  # columna separadora, se ignora
        if not crudo_visitante or not crudo_local:
            problemas.append(
                f"columna {openpyxl.utils.get_column_letter(columna + 1)}: enfrentamiento "
                f"incompleto (visitante={crudo_visitante!r}, local={crudo_local!r})"
            )
            continue

        visitante = normalizar(crudo_visitante)
        local = normalizar(crudo_local)
        if visitante == local:
            problemas.append(
                f"columna {openpyxl.utils.get_column_letter(columna + 1)}: "
                f"{visitante} aparece como visitante y como local"
            )
            continue

        partidos.append(Partido(visitante=visitante, local=local))
        columnas_de_partido.append(columna)

    repetidos = _equipos_repetidos(partidos)
    if repetidos:
        problemas.append(
            "estos equipos aparecen en más de un partido de la semana: "
            + ", ".join(sorted(repetidos))
        )
    if problemas:
        raise ErrorFormatoExcel(
            "Los enfrentamientos del archivo tienen problemas:\n  - "
            + "\n  - ".join(problemas)
        )
    if not partidos:
        raise ErrorFormatoExcel("No encontré ningún enfrentamiento en el archivo.")
    return partidos, columnas_de_partido


def _equipos_repetidos(partidos: list[Partido]) -> set[str]:
    vistos: set[str] = set()
    repetidos: set[str] = set()
    for partido in partidos:
        for equipo in (partido.visitante, partido.local):
            if equipo in vistos:
                repetidos.add(equipo)
            vistos.add(equipo)
    return repetidos


def _rejilla_excel(ruta: Path) -> list[tuple]:
    libro = openpyxl.load_workbook(ruta, data_only=True, read_only=True)
    hoja = libro.worksheets[0]
    if len(libro.worksheets) > 1:
        _log.warning(
            "El archivo tiene %d hojas; uso la primera (%r).", len(libro.worksheets), hoja.title
        )
    filas = [fila for fila in hoja.iter_rows(values_only=True)]
    libro.close()
    return filas


def _rejilla_pdf(ruta: Path) -> list[tuple]:
    """Arma la misma rejilla que el Excel, para que el resto no note diferencia."""
    try:
        semana, visitantes, locales, participantes = extraer_rejilla(ruta)
    except ErrorPDF as error:
        raise ErrorFormatoExcel(str(error)) from error

    filas: list[tuple] = [
        (None, *visitantes, None),
        (f"Semana {semana}", *locales, COLUMNA_IGNORADA),
    ]
    filas.extend((nombre, *picks) for nombre, picks in participantes)
    return filas


def _rejilla(ruta: Path) -> list[tuple]:
    """La rejilla del archivo, sea Excel o PDF."""
    if ruta.suffix.lower() == ".pdf":
        return _rejilla_pdf(ruta)
    if ruta.suffix.lower() in (".xlsx", ".xlsm"):
        return _rejilla_excel(ruta)
    raise ErrorPicks(
        f"No sé leer {ruta.name}: se esperaba .xlsx o .pdf."
    )


def leer_picks(ruta: Path) -> tuple[list[Partido], dict[str, list[str]]]:
    """Lee el Excel de una semana.

    Devuelve los enfrentamientos en el orden del archivo y un diccionario de
    participante a lista de picks ya normalizados, uno por partido.
    """
    ruta = Path(ruta)
    if not ruta.exists():
        raise ErrorPicks(f"No existe el archivo de picks: {ruta}")

    filas = _rejilla(ruta)
    if not filas:
        raise ErrorFormatoExcel(f"El archivo {ruta.name} está vacío.")

    ancho = max(len(fila) for fila in filas)
    filas = [tuple(fila) + (None,) * (ancho - len(fila)) for fila in filas]

    columna_ignorada = _localizar_columna_ignorada(filas)
    if columna_ignorada is None:
        _log.warning(
            "No encontré la columna %r; uso todas las columnas como partidos.", COLUMNA_IGNORADA
        )
        limite = ancho
    else:
        _log.info(
            "Ignoro la columna %s (%r), viene precargada con totales incorrectos.",
            openpyxl.utils.get_column_letter(columna_ignorada + 1),
            COLUMNA_IGNORADA,
        )
        limite = columna_ignorada

    columnas = range(1, limite)
    fila_visitantes = _localizar_encabezado(filas, columnas)
    fila_locales = fila_visitantes + 1

    partidos, columnas_de_partido = _leer_enfrentamientos(
        filas[fila_visitantes], filas[fila_locales], columnas
    )
    _log.info("Leí %d enfrentamientos de %s.", len(partidos), ruta.name)

    semana_hoja = _semana_del_encabezado(filas, fila_locales)
    try:
        semana_archivo = numero_semana(ruta)
    except ErrorPicks:
        semana_archivo = None
    if semana_hoja is not None and semana_archivo is not None and semana_hoja != semana_archivo:
        raise ErrorPicks(
            f"El archivo se llama {ruta.name} (semana {semana_archivo}) pero por dentro "
            f"dice 'Semana {semana_hoja}'. Corrige uno de los dos antes de calcular."
        )

    picks, problemas = _leer_participantes(filas, fila_locales + 1, partidos, columnas_de_partido)
    if problemas:
        raise ErrorPicks(
            f"El archivo {ruta.name} tiene {len(problemas)} problema(s):\n  - "
            + "\n  - ".join(problemas)
        )

    _log.info("Leí los picks de %d participantes.", len(picks))
    return partidos, picks


def _leer_participantes(
    filas: list[tuple],
    primera_fila: int,
    partidos: list[Partido],
    columnas_de_partido: list[int],
) -> tuple[dict[str, list[str]], list[str]]:
    picks: dict[str, list[str]] = {}
    problemas: list[str] = []
    claves_vistas: dict[str, str] = {}

    for numero_fila, fila in enumerate(filas[primera_fila:], start=primera_fila + 1):
        # Se lee en crudo para poder avisar qué se corrigió.
        celda_nombre = fila[0]
        crudo_nombre = celda_nombre if isinstance(celda_nombre, str) else _texto(celda_nombre)
        celdas = [_texto(fila[columna]) for columna in columnas_de_partido]

        nombre = unicodedata.normalize("NFC", " ".join(crudo_nombre.split()))
        if not nombre and not any(celdas):
            continue
        if not nombre:
            problemas.append(f"fila {numero_fila}: hay picks pero la celda del nombre está vacía")
            continue
        if nombre != crudo_nombre:
            _log.info(
                "Fila %d: corregí espacios o acentos en %r -> %r.", numero_fila, crudo_nombre, nombre
            )

        clave = clave_participante(nombre)
        if clave in claves_vistas:
            problemas.append(
                f"fila {numero_fila}: {nombre!r} está duplicado "
                f"(ya apareció como {claves_vistas[clave]!r})"
            )
            continue
        claves_vistas[clave] = nombre

        elegidos, fallas = _leer_fila_de_picks(celdas, partidos)
        if fallas:
            problemas.extend(f"fila {numero_fila} ({nombre}): {falla}" for falla in fallas)
            continue
        picks[nombre] = elegidos

    if not picks and not problemas:
        problemas.append("no encontré ningún participante debajo de los enfrentamientos")
    return picks, problemas


def _leer_fila_de_picks(celdas: list[str], partidos: list[Partido]) -> tuple[list[str], list[str]]:
    elegidos: list[str] = []
    fallas: list[str] = []
    faltantes: list[str] = []

    for celda, partido in zip(celdas, partidos):
        if not celda:
            faltantes.append(partido.clave)
            elegidos.append("")
            continue
        try:
            equipo = normalizar(celda)
        except EquipoDesconocidoError as error:
            fallas.append(f"pick ilegible en {partido.clave}: {error}")
            elegidos.append("")
            continue
        if equipo not in (partido.visitante, partido.local):
            fallas.append(f"eligió {equipo} en {partido.clave}, que no juega ese partido")
        elegidos.append(equipo)

    if faltantes:
        fallas.append(
            f"tiene {len(partidos) - len(faltantes)} picks de {len(partidos)}; "
            f"faltan: {', '.join(faltantes)}"
        )
    return elegidos, fallas
