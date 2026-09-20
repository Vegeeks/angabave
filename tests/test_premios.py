"""Pruebas del reparto de premios."""

from __future__ import annotations

from decimal import Decimal

import pandas as pd
import pytest

from quiniela.scoring import (
    ACUMULADO_SEMANAL,
    ACUMULADO_TOTAL,
    PREMIO_SEMANAL,
    SEMANAS_TEMPORADA,
    ganadores,
    premio_semanal,
    reparto_final,
)


def general(*filas) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"posicion": pos, "participante": nombre, "acumulado": puntos}
            for pos, nombre, puntos in filas
        ]
    )


def test_la_bolsa_final_es_el_acumulado_de_toda_la_temporada():
    assert ACUMULADO_SEMANAL * SEMANAS_TEMPORADA == ACUMULADO_TOTAL == Decimal("25200")


def test_el_reparto_normal_es_70_20_10():
    tabla = general((1, "Ana", 40), (2, "Beto", 38), (3, "Cris", 37), (4, "Dani", 30))
    reparto = reparto_final(tabla)
    assert [fila["participante"] for fila in reparto] == ["Ana", "Beto", "Cris"]
    assert [str(fila["premio"]) for fila in reparto] == ["17640.00", "5040.00", "2520.00"]


def test_el_reparto_completo_suma_la_bolsa():
    tabla = general((1, "Ana", 40), (2, "Beto", 38), (3, "Cris", 37))
    assert sum(fila["premio"] for fila in reparto_final(tabla)) == ACUMULADO_TOTAL


def test_dos_empatados_en_primero_se_reparten_el_70_y_el_20():
    tabla = general((1, "Ana", 40), (1, "Beto", 40), (3, "Cris", 37), (4, "Dani", 30))
    reparto = reparto_final(tabla)
    assert [str(fila["premio"]) for fila in reparto] == ["11340.00", "11340.00", "2520.00"]
    assert sum(fila["premio"] for fila in reparto) == ACUMULADO_TOTAL


def test_tres_empatados_en_primero_se_llevan_toda_la_bolsa():
    tabla = general((1, "Ana", 40), (1, "Beto", 40), (1, "Cris", 40), (4, "Dani", 30))
    reparto = reparto_final(tabla)
    assert len(reparto) == 3
    assert all(str(fila["premio"]) == "8400.00" for fila in reparto)
    assert sum(fila["premio"] for fila in reparto) == ACUMULADO_TOTAL


def test_empate_en_segundo_deja_fuera_al_cuarto():
    tabla = general((1, "Ana", 40), (2, "Beto", 38), (2, "Cris", 38), (4, "Dani", 30))
    reparto = reparto_final(tabla)
    assert [fila["participante"] for fila in reparto] == ["Ana", "Beto", "Cris"]
    # Beto y Cris se reparten el 20 % más el 10 %.
    assert [str(fila["premio"]) for fila in reparto] == ["17640.00", "3780.00", "3780.00"]


def test_con_menos_de_tres_participantes_no_se_inventa_un_tercero():
    tabla = general((1, "Ana", 40), (2, "Beto", 38))
    assert len(reparto_final(tabla)) == 2


def test_tabla_vacia():
    assert reparto_final(pd.DataFrame(columns=["posicion", "participante", "acumulado"])) == []


def test_el_premio_semanal_se_divide_entre_los_empatados():
    assert premio_semanal(1) == PREMIO_SEMANAL
    assert premio_semanal(2) == Decimal("2600.00")
    assert premio_semanal(5) == Decimal("1040.00")
    assert premio_semanal(3) == Decimal("1733.33")


def test_sin_ganadores_no_hay_premio():
    assert premio_semanal(0) == Decimal("0")


def test_ganadores_son_los_de_posicion_uno():
    tabla = pd.DataFrame(
        [
            {"posicion": 1, "participante": "Ana", "firme": 12},
            {"posicion": 1, "participante": "Beto", "firme": 12},
            {"posicion": 3, "participante": "Cris", "firme": 11},
        ]
    )
    assert ganadores(tabla) == ["Ana", "Beto"]


def test_ganadores_de_una_tabla_vacia():
    assert ganadores(pd.DataFrame(columns=["posicion", "participante"])) == []
