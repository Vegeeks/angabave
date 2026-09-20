"""Traducción y normalización de nombres de equipos de la NFL.

La quiniela usa nombres cortos ("Ravens", "49ers", "Washington") y la API de
ESPN usa abreviaturas ("BAL", "SF", "WSH").  Aquí vive el único diccionario que
une ambos mundos, más la función que acepta cualquiera de las dos formas.
"""

from __future__ import annotations

import unicodedata

__all__ = [
    "ABREVIATURAS_ESPN",
    "NOMBRES_QUINIELA",
    "EquipoDesconocidoError",
    "normalizar",
]


class EquipoDesconocidoError(ValueError):
    """Llegó un equipo que no está en el catálogo."""


#: Abreviatura de ESPN -> nombre que usa la quiniela.
ABREVIATURAS_ESPN: dict[str, str] = {
    "ARI": "Cardinals",
    "ATL": "Falcons",
    "BAL": "Ravens",
    "BUF": "Bills",
    "CAR": "Panthers",
    "CHI": "Bears",
    "CIN": "Bengals",
    "CLE": "Browns",
    "DAL": "Cowboys",
    "DEN": "Broncos",
    "DET": "Lions",
    "GB": "Packers",
    "HOU": "Texans",
    "IND": "Colts",
    "JAX": "Jaguars",
    "KC": "Chiefs",
    "LAC": "Chargers",
    "LAR": "Rams",
    "LV": "Raiders",
    "MIA": "Dolphins",
    "MIN": "Vikings",
    "NE": "Patriots",
    "NO": "Saints",
    "NYG": "Giants",
    "NYJ": "Jets",
    "PHI": "Eagles",
    "PIT": "Steelers",
    "SF": "49ers",
    "SEA": "Seahawks",
    "TB": "Buccaneers",
    "TEN": "Titans",
    "WSH": "Washington",
    # Variantes que ESPN devuelve según el endpoint que responda.
    "JAC": "Jaguars",
    "LA": "Rams",
    "WAS": "Washington",
}

#: Los 32 nombres canónicos, los únicos que devuelve `normalizar`.
NOMBRES_QUINIELA: frozenset[str] = frozenset(ABREVIATURAS_ESPN.values())

# Nombres alternos que aparecen escritos en los archivos de la quiniela.
# La franquicia se llama Commanders, pero la quiniela escribe Washington.
_ALIAS: dict[str, str] = {"COMMANDERS": "Washington"}


def _clave(texto: str) -> str:
    """Forma comparable: sin acentos, sin espacios, en mayúsculas."""
    sin_acentos = "".join(
        caracter
        for caracter in unicodedata.normalize("NFD", texto)
        if not unicodedata.combining(caracter)
    )
    return "".join(caracter for caracter in sin_acentos if caracter.isalnum()).upper()


# Índice de búsqueda: abreviaturas, nombres de quiniela y alias, todos en clave.
_INDICE: dict[str, str] = {}
for _abreviatura, _nombre in ABREVIATURAS_ESPN.items():
    _INDICE[_clave(_abreviatura)] = _nombre
for _nombre in NOMBRES_QUINIELA:
    _INDICE[_clave(_nombre)] = _nombre
for _alias, _nombre in _ALIAS.items():
    _INDICE[_clave(_alias)] = _nombre


def normalizar(nombre: str) -> str:
    """Devuelve el nombre canónico de la quiniela.

    Acepta la abreviatura de ESPN ("WSH", "WAS", "SF"), el nombre de la
    quiniela en cualquier caja ("washington", "49ERS") y el alias
    "Commanders".  Lanza `EquipoDesconocidoError` con el valor recibido si no
    reconoce el equipo: nunca lo ignora en silencio.
    """
    if not isinstance(nombre, str):
        raise EquipoDesconocidoError(
            f"Se esperaba texto con el nombre del equipo, llegó {type(nombre).__name__}: {nombre!r}"
        )

    equipo = _INDICE.get(_clave(nombre))
    if equipo is None:
        raise EquipoDesconocidoError(f"Equipo desconocido: {nombre!r}")
    return equipo
