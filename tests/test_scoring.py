"""Pruebas del cálculo de tablas y de los escenarios."""

from __future__ import annotations

from pathlib import Path

import pytest

from quiniela.espn import Partido, guardar_cache
from quiniela.picks import leer_picks
from quiniela.scoring import (
    ErrorCalendario,
    emparejar_resultados,
    escenarios,
    panorama,
    posiciones,
    tabla_general,
    tabla_semana,
)

from .conftest import ENFRENTAMIENTOS_S2, PICKS_S2, crear_excel


def cerrado(visitante: str, local: str, ganador: str) -> Partido:
    marcador = (17, 24) if ganador == local else (24, 17)
    return Partido(visitante, local, *marcador, ganador, True, "Final")


def empatado(visitante: str, local: str) -> Partido:
    return Partido(visitante, local, 24, 24, None, True, "Final/OT")


def en_curso(visitante: str, local: str, lider: str | None) -> Partido:
    if lider is None:
        marcador = (14, 14)
    else:
        marcador = (7, 21) if lider == local else (21, 7)
    return Partido(visitante, local, *marcador, None, False, "In Progress")


def sin_empezar(visitante: str, local: str) -> Partido:
    return Partido(visitante, local, 0, 0, None, False, "Scheduled")


# --- tabla semanal ---------------------------------------------------------


def test_firme_errores_y_proyectado(excel_s2: Path):
    partidos, picks = leer_picks(excel_s2)
    resultados = [
        cerrado("Lions", "Bills", "Bills"),              # todos le atinaron menos Tristan
        cerrado("Panthers", "Falcons", "Panthers"),      # todos le atinaron
        en_curso("Saints", "Ravens", "Ravens"),          # todos van ganando
        sin_empezar("Vikings", "Bears"),                 # no suma a nadie
        *[sin_empezar(v, l) for v, l in ENFRENTAMIENTOS_S2[4:]],
    ]
    tabla = tabla_semana(partidos, picks, resultados)

    fila = tabla.set_index("participante").loc["Ismael Reyna"]
    assert fila["firme"] == 2
    assert fila["errores"] == 0
    assert fila["proyectado"] == 3  # los dos firmes más el Ravens en curso

    tristan = tabla.set_index("participante").loc["Tristan Mejia"]
    assert tristan["firme"] == 1      # falló Lions@Bills
    assert tristan["errores"] == 1
    assert tristan["proyectado"] == 2


def test_firme_mas_errores_es_el_numero_de_partidos_cerrados(excel_s2: Path):
    partidos, picks = leer_picks(excel_s2)
    resultados = [
        cerrado(v, l, l) for v, l in ENFRENTAMIENTOS_S2[:5]
    ] + [en_curso(v, l, v) for v, l in ENFRENTAMIENTOS_S2[5:]]
    tabla = tabla_semana(partidos, picks, resultados)
    assert ((tabla["firme"] + tabla["errores"]) == 5).all()


def test_el_empate_no_le_da_acierto_a_nadie(excel_s2: Path):
    partidos, picks = leer_picks(excel_s2)
    resultados = [empatado("Lions", "Bills")] + [
        sin_empezar(v, l) for v, l in ENFRENTAMIENTOS_S2[1:]
    ]
    tabla = tabla_semana(partidos, picks, resultados)
    assert (tabla["firme"] == 0).all()
    assert (tabla["errores"] == 1).all()  # cuenta como partido cerrado para todos


def test_partido_en_curso_sin_lider_no_proyecta(excel_s2: Path):
    partidos, picks = leer_picks(excel_s2)
    resultados = [en_curso("Lions", "Bills", None)] + [
        sin_empezar(v, l) for v, l in ENFRENTAMIENTOS_S2[1:]
    ]
    tabla = tabla_semana(partidos, picks, resultados)
    assert (tabla["proyectado"] == 0).all()
    assert (tabla["errores"] == 0).all()


def test_columnas_y_orden_de_la_tabla_semanal(excel_s2: Path):
    partidos, picks = leer_picks(excel_s2)
    resultados = [cerrado(v, l, l) for v, l in ENFRENTAMIENTOS_S2]
    tabla = tabla_semana(partidos, picks, resultados)
    assert list(tabla.columns) == ["posicion", "participante", "firme", "errores", "proyectado"]
    assert tabla["firme"].is_monotonic_decreasing


# --- empates y posiciones --------------------------------------------------


def test_tres_empatados_en_primero_y_el_siguiente_es_cuarto():
    assert posiciones([(13, 13), (13, 13), (13, 13), (12, 12)]) == [1, 1, 1, 4]


def test_empate_multiple_en_la_tabla_real(tmp_path: Path):
    """Tres personas empatadas en primero son las tres 1 y la siguiente es 4."""
    perfectos = [local for _, local in ENFRENTAMIENTOS_S2]
    fallon = list(perfectos)
    fallon[0] = ENFRENTAMIENTOS_S2[0][0]  # le erra al primero
    ruta = crear_excel(
        tmp_path / "Semana_02.xlsx",
        picks={
            "Zulema": list(perfectos),
            "Ana": list(perfectos),
            "Mauro": list(perfectos),
            "Beto": fallon,
        },
    )
    partidos, picks = leer_picks(ruta)
    tabla = tabla_semana(partidos, picks, [cerrado(v, l, l) for v, l in ENFRENTAMIENTOS_S2])

    primeros = tabla[tabla["posicion"] == 1]
    assert len(primeros) == 3
    # El desempate final es alfabético, pero la posición se comparte.
    assert list(primeros["participante"]) == ["Ana", "Mauro", "Zulema"]
    assert list(tabla["posicion"]) == [1, 1, 1, 4]


def test_el_proyectado_desempata_el_orden_pero_no_la_posicion(excel_s2: Path):
    partidos, picks = leer_picks(excel_s2)
    resultados = [cerrado(v, l, l) for v, l in ENFRENTAMIENTOS_S2[:15]] + [
        en_curso("Giants", "Rams", "Rams")
    ]
    tabla = tabla_semana(partidos, picks, resultados)
    for _, grupo in tabla.groupby("posicion"):
        assert grupo["firme"].nunique() == 1          # la posición la decide el firme
    # Dentro de un empate, el que va ganando en vivo aparece primero.
    empatados = tabla[tabla["posicion"] == tabla["posicion"].iloc[0]]
    assert empatados["proyectado"].is_monotonic_decreasing


# --- verificación del calendario -------------------------------------------


def test_enfrentamiento_del_excel_que_no_existe(excel_s2: Path):
    partidos, picks = leer_picks(excel_s2)
    resultados = [cerrado(v, l, l) for v, l in ENFRENTAMIENTOS_S2[:-1]]
    with pytest.raises(ErrorCalendario, match="Giants@Rams"):
        tabla_semana(partidos, picks, resultados)


def test_partido_real_que_no_esta_en_la_quiniela_solo_avisa(excel_s2: Path, caplog):
    partidos, picks = leer_picks(excel_s2)
    resultados = [cerrado(v, l, l) for v, l in ENFRENTAMIENTOS_S2] + [
        cerrado("Jets", "Titans", "Jets")
    ]
    with caplog.at_level("WARNING", logger="quiniela.scoring"):
        tabla = tabla_semana(partidos, picks, resultados)
    assert len(tabla) == len(PICKS_S2)
    assert "Jets@Titans" in caplog.text


def test_los_resultados_se_alinean_al_orden_del_excel(excel_s2: Path):
    partidos, _ = leer_picks(excel_s2)
    resultados = list(reversed([cerrado(v, l, l) for v, l in ENFRENTAMIENTOS_S2]))
    alineados = emparejar_resultados(partidos, resultados)
    assert [p.clave for p in alineados] == [p.clave for p in partidos]


# --- tabla general ---------------------------------------------------------


@pytest.fixture
def temporada(tmp_path: Path) -> tuple[list[Path], Path, Path]:
    """Dos semanas con picks y marcadores en caché."""
    dir_cache = tmp_path / "resultados"
    overrides = tmp_path / "overrides.json"

    s1 = crear_excel(tmp_path / "Semana_01.xlsx", semana=1)
    guardar_cache(1, [cerrado(v, l, l) for v, l in ENFRENTAMIENTOS_S2], dir_cache)

    picks_s2 = dict(PICKS_S2)
    picks_s2.pop("Tristan Mejia")           # no jugó la semana 2
    picks_s2["Chilangos Nortenos"] = picks_s2.pop("Chilangos Norteños")  # sin acentos
    s2 = crear_excel(tmp_path / "Semana_02.xlsx", picks=picks_s2, semana=2)
    guardar_cache(2, [cerrado(v, l, v) for v, l in ENFRENTAMIENTOS_S2], dir_cache)

    return [s2, s1], dir_cache, overrides  # desordenadas a propósito


def test_la_general_suma_varias_semanas(temporada):
    semanas, dir_cache, overrides = temporada
    tabla = tabla_general(semanas, dir_cache=dir_cache, ruta_overrides=overrides)

    assert list(tabla.columns) == [
        "posicion", "participante", "acumulado", "errores", "proyectado", "S1", "S2",
    ]
    fila = tabla.set_index("participante").loc["Ismael Reyna"]
    assert fila["acumulado"] == fila["S1"] + fila["S2"]
    assert fila["acumulado"] + fila["errores"] == 32  # dos semanas cerradas completas


def test_quien_no_jugo_una_semana_lleva_cero(temporada):
    semanas, dir_cache, overrides = temporada
    tabla = tabla_general(semanas, dir_cache=dir_cache, ruta_overrides=overrides)
    tristan = tabla.set_index("participante").loc["Tristan Mejia"]
    assert tristan["S2"] == 0
    assert tristan["acumulado"] == tristan["S1"]


def test_los_acentos_inconsistentes_son_una_sola_fila(temporada):
    semanas, dir_cache, overrides = temporada
    tabla = tabla_general(semanas, dir_cache=dir_cache, ruta_overrides=overrides)
    chilangos = tabla[tabla["participante"].str.startswith("Chilangos")]
    assert len(chilangos) == 1
    assert chilangos.iloc[0]["S1"] > 0 and chilangos.iloc[0]["S2"] > 0


def test_la_general_sin_cache_dice_que_hacer(tmp_path: Path):
    ruta = crear_excel(tmp_path / "Semana_01.xlsx", semana=1)
    with pytest.raises(ErrorCalendario, match="actualizar --semana 1"):
        tabla_general([ruta], dir_cache=tmp_path / "vacio", ruta_overrides=tmp_path / "no.json")


# --- escenarios ------------------------------------------------------------


def test_escenarios_cuenta_las_combinaciones():
    pendientes = [sin_empezar("Lions", "Bills"), sin_empezar("Panthers", "Falcons")]
    picks = {"A": ["Bills", "Falcons"], "B": ["Lions", "Panthers"]}
    resultado = escenarios("A", pendientes, picks, {"A": 5, "B": 5})
    assert resultado.combinaciones == 4
    assert resultado.gana_solo + resultado.empata + resultado.pierde == 4


def test_escenarios_con_tres_pendientes_a_mano():
    pendientes = [
        sin_empezar("Lions", "Bills"),
        sin_empezar("Panthers", "Falcons"),
        sin_empezar("Saints", "Ravens"),
    ]
    picks = {
        "Local": ["Bills", "Falcons", "Ravens"],
        "Visita": ["Lions", "Panthers", "Saints"],
    }
    resultado = escenarios("Local", pendientes, picks, {"Local": 5, "Visita": 5})
    # Gana cuando el local se lleva 2 o 3 de los 3 partidos: 3 + 1 = 4 de 8.
    assert (resultado.gana_solo, resultado.empata, resultado.pierde) == (4, 0, 4)
    assert resultado.indispensables == {}


def test_escenarios_encuentra_los_partidos_indispensables():
    pendientes = [sin_empezar("Lions", "Bills"), sin_empezar("Panthers", "Falcons")]
    picks = {"Atras": ["Bills", "Falcons"], "Lider": ["Lions", "Panthers"]}
    # Atrás por dos: necesita ganar los dos pendientes para siquiera empatar.
    resultado = escenarios("Atras", pendientes, picks, {"Atras": 4, "Lider": 6})
    assert (resultado.gana_solo, resultado.empata, resultado.pierde) == (0, 1, 3)
    assert resultado.indispensables == {"Lions@Bills": "Bills", "Panthers@Falcons": "Falcons"}
    assert resultado.vive is True


def test_escenarios_de_quien_ya_no_alcanza():
    pendientes = [sin_empezar("Lions", "Bills")]
    picks = {"Atras": ["Bills"], "Lider": ["Bills"]}
    resultado = escenarios("Atras", pendientes, picks, {"Atras": 3, "Lider": 9})
    assert (resultado.gana_solo, resultado.empata, resultado.pierde) == (0, 0, 2)
    assert resultado.indispensables == {}
    assert resultado.vive is False


def test_escenarios_de_un_participante_que_no_existe():
    pendientes = [sin_empezar("Lions", "Bills")]
    with pytest.raises(KeyError, match="Fulano"):
        escenarios("Fulano", pendientes, {"A": ["Bills"]}, {"A": 1})


def test_escenarios_con_los_16_partidos_abiertos(excel_s2: Path):
    """65,536 combinaciones por fuerza bruta, como pediste."""
    partidos, picks = leer_picks(excel_s2)
    firmes = dict.fromkeys(picks, 0)
    resultado = escenarios("Angel D Luffy", partidos, picks, firmes)
    assert resultado.combinaciones == 65536
    assert resultado.gana_solo + resultado.empata + resultado.pierde == 65536


# --- panorama --------------------------------------------------------------


def test_el_panorama_coincide_con_escenarios_uno_por_uno():
    """La pasada única tiene que dar lo mismo que calcular a cada quien aparte."""
    pendientes = [
        sin_empezar("Lions", "Bills"),
        sin_empezar("Panthers", "Falcons"),
        sin_empezar("Saints", "Ravens"),
    ]
    picks = {
        "Ana": ["Bills", "Falcons", "Ravens"],
        "Beto": ["Lions", "Panthers", "Saints"],
        "Cris": ["Bills", "Panthers", "Ravens"],
    }
    firmes = {"Ana": 5, "Beto": 6, "Cris": 5}

    vista = panorama(pendientes, picks, firmes)
    for participante in picks:
        uno = escenarios(participante, pendientes, picks, firmes)
        assert vista[participante]["gana_solo"] == uno.gana_solo
        assert vista[participante]["empata"] == uno.empata


def test_el_panorama_reparte_todas_las_combinaciones():
    pendientes = [sin_empezar("Lions", "Bills"), sin_empezar("Panthers", "Falcons")]
    picks = {"Ana": ["Bills", "Falcons"], "Beto": ["Lions", "Panthers"]}
    vista = panorama(pendientes, picks, {"Ana": 4, "Beto": 4})
    # Cada combinación tiene exactamente un primer lugar, solo o compartido.
    con_ganador = sum(v["gana_solo"] for v in vista.values())
    empatadas = max(v["empata"] for v in vista.values())
    assert con_ganador + empatadas == 4


def test_el_panorama_sin_participantes():
    assert panorama([sin_empezar("Lions", "Bills")], {}, {}) == {}
