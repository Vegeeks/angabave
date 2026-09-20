"""Utilidades compartidas por las pruebas.

Aquí se arman los Excel de prueba con el mismo layout que el archivo real:
fila de visitantes, fila de locales debajo, participantes a partir de la
tercera fila y una última columna "Aciertos Totales" con valores basura.
"""

from __future__ import annotations

from pathlib import Path

import openpyxl
import pytest

#: Enfrentamientos reales de la Semana 2 de 2026, en el orden del archivo.
ENFRENTAMIENTOS_S2: list[tuple[str, str]] = [
    ("Lions", "Bills"),
    ("Panthers", "Falcons"),
    ("Saints", "Ravens"),
    ("Vikings", "Bears"),
    ("Bengals", "Texans"),
    ("Steelers", "Patriots"),
    ("Packers", "Jets"),
    ("Browns", "Buccaneers"),
    ("Eagles", "Titans"),
    ("Jaguars", "Broncos"),
    ("Raiders", "Chargers"),
    ("Seahawks", "Cardinals"),
    ("Washington", "Cowboys"),
    ("Dolphins", "49ers"),
    ("Colts", "Chiefs"),
    ("Giants", "Rams"),
]

#: Participantes de prueba. Los nombres son reales, los picks NO: están
#: inventados para cubrir casos concretos. Los de verdad viven en data/picks/.
PICKS_S2: dict[str, list[str]] = {
    "Ismael Reyna": [
        "Bills", "Panthers", "Ravens", "Bears", "Texans", "Patriots", "Packers",
        "Buccaneers", "Eagles", "Jaguars", "Chargers", "Seahawks", "Cowboys",
        "49ers", "Chiefs", "Rams",
    ],
    "Angel D Luffy": [
        "Bills", "Panthers", "Ravens", "Bears", "Texans", "Patriots", "Packers",
        "Buccaneers", "Eagles", "Broncos", "Chargers", "Seahawks", "Cowboys",
        "49ers", "Chiefs", "Rams",
    ],
    "Chilangos Norteños": [
        "Bills", "Panthers", "Ravens", "Bears", "Texans", "Steelers", "Packers",
        "Buccaneers", "Eagles", "Jaguars", "Chargers", "Seahawks", "Cowboys",
        "49ers", "Chiefs", "Rams",
    ],
    "Tristan Mejia": [
        "Lions", "Panthers", "Ravens", "Vikings", "Texans", "Patriots", "Packers",
        "Buccaneers", "Eagles", "Broncos", "Chargers", "Cardinals", "Cowboys",
        "49ers", "Colts", "Rams",
    ],
}


def crear_excel(
    ruta: Path,
    enfrentamientos: list[tuple[str, str]] | None = None,
    picks: dict[str, list[str]] | None = None,
    semana: int = 2,
    con_columna_totales: bool = True,
) -> Path:
    """Escribe un Excel de picks con el layout del archivo real."""
    enfrentamientos = enfrentamientos if enfrentamientos is not None else ENFRENTAMIENTOS_S2
    picks = picks if picks is not None else PICKS_S2

    libro = openpyxl.Workbook()
    hoja = libro.active
    hoja.title = f"Semana {semana}"

    for columna, (visitante, local) in enumerate(enfrentamientos, start=2):
        hoja.cell(row=1, column=columna, value=visitante)
        hoja.cell(row=2, column=columna, value=local)
    hoja.cell(row=2, column=1, value=f"Semana {semana}")

    columna_totales = len(enfrentamientos) + 2
    if con_columna_totales:
        hoja.cell(row=2, column=columna_totales, value="Aciertos Totales")

    for fila, (participante, elegidos) in enumerate(picks.items(), start=3):
        hoja.cell(row=fila, column=1, value=participante)
        for columna, pick in enumerate(elegidos, start=2):
            if pick:
                hoja.cell(row=fila, column=columna, value=pick)
        if con_columna_totales:
            # Valor deliberadamente incorrecto: es la columna que hay que ignorar.
            hoja.cell(row=fila, column=columna_totales, value=99)

    libro.save(ruta)
    return ruta


@pytest.fixture
def excel_s2(tmp_path: Path) -> Path:
    """Excel de la Semana 2 completo y bien formado."""
    return crear_excel(tmp_path / "Semana_02.xlsx")
