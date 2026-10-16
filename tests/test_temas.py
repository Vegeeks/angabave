"""Cada tema se lee: el del campo y los de los 32 equipos, de casa y de visita.

Los textos se miden contra lo más claro que les puede quedar detrás: el campo
bajo las luces del estadio, el vidrio esmerilado encima de ese campo, los
paneles opacos y la fila resaltada de quien eligió su nombre.
"""

from pathlib import Path

import pytest

from quiniela.render_html import (
    BASE_CAMPO,
    CONTRASTE_MINIMO,
    CONTRASTE_SEMANTICO,
    LUZ_EQUIPO,
    LUZ_ESTADIO,
    SEMANTICOS,
    _a_rgb,
    contraste,
    fondos_de_prueba,
    paleta_equipos,
    tema_campo,
    temas_equipos,
)
from tests.test_render import armado, render  # noqa: F401  (armado es fixture)

MINIMOS = {"--txt": 7.0, "--tenue": 4.5, "--tenue2": 3.0, "--acento": CONTRASTE_MINIMO}


def _luz(tema: dict[str, str]) -> tuple[str, float]:
    """La luz que de verdad lleva la página: la del --resplandor del tema."""
    valor = tema["--resplandor"]
    return valor[:7], int(valor[7:], 16) / 255


def _todos():
    yield "campo", tema_campo()
    for equipo, temas in temas_equipos().items():
        for donde, tema in temas.items():
            yield f"{equipo}-{donde}", tema


TEMAS = list(_todos())


@pytest.mark.parametrize("nombre,tema", TEMAS, ids=[t[0] for t in TEMAS])
def test_cada_tema_se_lee(nombre, tema):
    fondos = fondos_de_prueba(tema, *_luz(tema))
    for variable, minimo in MINIMOS.items():
        for fondo in fondos:
            assert contraste(tema[variable], fondo) >= minimo, (nombre, variable, fondo)
    # Acierto, fallo, en vivo y el oro: si el tema no los aclaró, van los de siempre.
    for clave, base in SEMANTICOS.items():
        color = tema.get("--" + clave, base)
        for fondo in fondos:
            assert contraste(color, fondo) >= CONTRASTE_SEMANTICO, (nombre, clave, fondo)


def test_son_65_temas_y_la_luz_es_la_de_cada_uno():
    assert len(TEMAS) == 1 + 32 * 2
    assert _luz(tema_campo()) == (LUZ_ESTADIO[0], pytest.approx(LUZ_ESTADIO[1], abs=0.003))
    chiefs = temas_equipos()["Chiefs"]["local"]
    assert _luz(chiefs) == (paleta_equipos()["Chiefs"]["local"], pytest.approx(LUZ_EQUIPO, abs=0.003))


def test_el_campo_es_verde():
    rojo, verde, azul = _a_rgb(BASE_CAMPO["bg"])
    assert verde > rojo and verde > azul
    # El vidrio deja ver el campo, pero tapa lo bastante para leer encima.
    vidrio = tema_campo()["--vidrio"]
    assert len(vidrio) == 9 and 0.6 <= int(vidrio[-2:], 16) / 255 <= 0.85


def test_la_pagina_trae_el_campo_y_el_vidrio(armado, tmp_path: Path):  # noqa: F811
    html = render(armado, tmp_path)
    raiz = html[html.index(":root{"):html.index("--oro:")]
    for variable, valor in tema_campo().items():
        assert f"{variable}:{valor};" in raiz
    # Las yardas de los dos lados y el grano del vidrio, sin pedir archivos.
    assert html.count('class="num izq"') == html.count('class="num der"') == 9
    assert '--grano:url("data:image/svg+xml,%3Csvg' in html
    assert "backdrop-filter:blur(14px)" in html
