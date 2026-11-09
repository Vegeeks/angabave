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


# --- lo ya cobrado en semanas oficiales ------------------------------------------


def _semana_oficial(numero: int, *ganadores_: str, otros: tuple[str, ...] = ("Zeta",), cerrados: int = 8):
    from quiniela.render_html import SemanaRender
    from tests.test_scoring import cerrado

    partidos = [cerrado(f"V{i}", f"L{i}", f"L{i}") for i in range(cerrados)]
    filas = [{"posicion": 1, "participante": nombre, "firme": 8, "errores": 0} for nombre in ganadores_]
    filas += [{"posicion": 1 + len(ganadores_), "participante": nombre, "firme": 5, "errores": 3} for nombre in otros]
    picks = {nombre: [f"L{i}" for i in range(cerrados)] for nombre in (*ganadores_, *otros)}
    return SemanaRender(numero, partidos, picks, pd.DataFrame(filas))


def _indices(*semanas):
    nombres: list[str] = []
    for semana in semanas:
        for nombre in semana.tabla["participante"]:
            if nombre not in nombres:
                nombres.append(nombre)
    return {nombre: i for i, nombre in enumerate(nombres)}


@pytest.mark.parametrize("cuantos, centavos", [(1, 520000), (2, 260000), (6, 86667)])
def test_lo_cobrado_es_el_monto_publicado_por_semana(cuantos, centavos):
    from quiniela.render_html import _datos_semana, _pesos, cobrado_en_centavos

    nombres = [f"G{i}" for i in range(cuantos)]
    semana = _semana_oficial(1, *nombres)
    indices = _indices(semana)
    cobrado = cobrado_en_centavos([semana], indices)
    assert [cobrado[indices[n]] for n in nombres] == [centavos] * cuantos
    assert cobrado[indices["Zeta"]] == 0
    # Es lo que la página publica en esa semana, al centavo.
    assert _pesos(Decimal(cobrado[0]) / 100) == _datos_semana(semana, indices)["premio"]
    assert all(isinstance(c, int) for c in cobrado)


def test_dos_semanas_de_seis_ganadores_suman_el_monto_ya_redondeado():
    from quiniela.render_html import cobrado_en_centavos

    nombres = [f"G{i}" for i in range(6)]
    a, b = _semana_oficial(1, *nombres), _semana_oficial(2, *nombres)
    indices = _indices(a, b)
    assert cobrado_en_centavos([a, b], indices)[0] == 173334   # $1,733.34, no $1,733.33


def test_lo_cobrado_ignora_semanas_en_curso_o_con_pocos_partidos():
    from quiniela.render_html import cobrado_en_centavos
    from tests.test_scoring import cerrado

    oficial = _semana_oficial(1, "Ana")
    pocos = _semana_oficial(2, "Beto", cerrados=3)
    abierta = _semana_oficial(3, "Cris")
    abierta.partidos.append(cerrado("V", "L", "L").__class__("V", "L", 0, 0, None, False, "Scheduled"))
    indices = _indices(oficial, pocos, abierta)
    cobrado = cobrado_en_centavos([oficial, pocos, abierta], indices)
    assert cobrado[indices["Ana"]] == 520000
    assert cobrado[indices["Beto"]] == cobrado[indices["Cris"]] == 0


def test_lo_cobrado_viaja_en_la_pagina_y_nunca_dice_cero():
    import cli
    from quiniela.render_html import cobrado_en_centavos, cobros_de_semana

    semanas = cli.construir_semanas(2026, True)
    indices: dict[str, int] = {}
    for semana in semanas:
        for nombre in semana.picks:
            indices.setdefault(nombre, len(indices))
    cobrado = cobrado_en_centavos(semanas, indices)
    # Cada peso cobrado sale de las semanas oficiales: la suma es la de los premios publicados.
    publicado = sum(sum(m for m in cobros_de_semana(s).values()) for s in semanas)
    assert Decimal(sum(cobrado)) / 100 == publicado
    assert sum(cobrado) > 0
