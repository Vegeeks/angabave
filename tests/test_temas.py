"""Cada tema se lee: el del campo y los de los 32 equipos, de casa y de visita.

Los textos se miden contra lo más claro que les puede quedar detrás: el campo
bajo la luz del estadio, el cristal encima de ese campo, las superficies y la
fila resaltada de quien eligió su nombre.
"""

import re
from pathlib import Path

import pytest

from quiniela.render_html import (
    ACENTO_CAMPO,
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

MINIMOS = {"--txt": 7.0, "--tenue": 6.0, "--tenue2": 4.5, "--acento": CONTRASTE_MINIMO}


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


def test_el_campo_es_verde_y_el_acento_la_linea_amarilla():
    rojo, verde, azul = _a_rgb(BASE_CAMPO["bg"])
    assert verde > rojo and verde > azul
    assert tema_campo()["--acento"] == ACENTO_CAMPO
    # El cristal de las barras deja ver lo de atrás, pero tapa lo bastante para leer encima.
    cristal = tema_campo()["--cristal"]
    assert len(cristal) == 9 and 0.6 <= int(cristal[-2:], 16) / 255 <= 0.9


def test_los_temas_de_equipo_apenas_tinen_las_superficies():
    """El equipo se nota en el acento y en la luz; el fondo sigue casi negro."""
    for temas in temas_equipos().values():
        for tema in temas.values():
            assert max(_a_rgb(tema["--bg"])) < 0.2


def test_la_pagina_trae_el_campo_y_nada_de_relieves(armado, tmp_path: Path):  # noqa: F811
    html = render(armado, tmp_path)
    raiz = html[html.index(":root{"):html.index("--oro:")]
    for variable, valor in tema_campo().items():
        assert f"{variable}:{valor};" in raiz
    assert 'class="cancha"' in html and "backdrop-filter:blur(" in html
    # Lo que hacía verse viejo no regresa: ni grano ni botones con degradado.
    estilo = html[html.index("<style>"):html.index("</style>")]
    assert "--grano" not in estilo
    assert not re.search(r"\.boton(-principal)?\{[^}]*gradient", estilo)


def test_solo_hay_seis_tamanos_de_letra(armado, tmp_path: Path):  # noqa: F811
    html = render(armado, tmp_path)
    estilo = html[html.index("<style>"):html.index("</style>")]
    tamanos = set(re.findall(r"font-size:([^;}]+)", estilo))
    assert tamanos <= {f"var(--t{i})" for i in range(1, 7)}, tamanos
    assert "--t6:.75rem" in estilo     # 12 px: de ahí no se baja
