"""Pruebas de la normalización de nombres de equipos."""

from __future__ import annotations

import pytest

from quiniela.equipos import (
    ABREVIATURAS_ESPN,
    NOMBRES_QUINIELA,
    EquipoDesconocidoError,
    normalizar,
)


def test_hay_32_equipos_y_35_entradas():
    assert len(NOMBRES_QUINIELA) == 32
    assert len(ABREVIATURAS_ESPN) == 35  # 32 + las tres variantes de ESPN


@pytest.mark.parametrize(
    ("variante_a", "variante_b", "esperado"),
    [
        ("JAC", "JAX", "Jaguars"),
        ("LA", "LAR", "Rams"),
        ("WAS", "WSH", "Washington"),
    ],
)
def test_variantes_de_espn_dan_el_mismo_equipo(variante_a, variante_b, esperado):
    assert normalizar(variante_a) == normalizar(variante_b) == esperado


def test_todas_las_abreviaturas_se_normalizan():
    for abreviatura, esperado in ABREVIATURAS_ESPN.items():
        assert normalizar(abreviatura) == esperado


def test_acepta_el_nombre_de_la_quiniela_en_cualquier_caja():
    assert normalizar("washington") == "Washington"
    assert normalizar("  49ERS ") == "49ers"
    assert normalizar("Buccaneers") == "Buccaneers"


def test_commanders_es_alias_pero_la_salida_es_washington():
    assert normalizar("COMMANDERS") == "Washington"
    assert normalizar("Commanders") == "Washington"


def test_equipo_desconocido_incluye_el_valor_recibido():
    with pytest.raises(EquipoDesconocidoError, match="Vaqueros"):
        normalizar("Vaqueros")


def test_celda_vacia_tambien_truena():
    with pytest.raises(EquipoDesconocidoError):
        normalizar("")
