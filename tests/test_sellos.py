"""Pruebas del sellado de picks.

Los picks viven en el repo y solo cambian con un push autenticado, pero un
cambio hecho cuando ya hay resultados no se puede dar por bueno. El sello los
congela partido por partido, en cuanto ese partido arranca: la jornada cierra
por tandas, así que con el jueves jugado los picks del domingo todavía valen.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quiniela.picks import (
    PicksAlteradosError,
    huella,
    huellas_por_partido,
    verificar_sello,
)

from .conftest import ENFRENTAMIENTOS_S2, PICKS_S2, crear_excel

#: Claves de los partidos de la semana de prueba, en el orden del archivo.
CLAVES = [f"{visitante}@{local}" for visitante, local in ENFRENTAMIENTOS_S2]
JUEVES, DOMINGO = CLAVES[0], CLAVES[3]


def _copia_de_picks() -> dict[str, list[str]]:
    return {nombre: list(elegidos) for nombre, elegidos in PICKS_S2.items()}


def test_antes_del_arranque_los_picks_se_pueden_corregir(tmp_path: Path):
    ruta = crear_excel(tmp_path / "Semana_02.xlsx")
    sellos = tmp_path / "sellos.json"

    assert verificar_sello(ruta, 2, set(), ruta_sellos=sellos) == set()

    corregidos = _copia_de_picks()
    corregidos["Ismael Reyna"][3] = "Vikings"
    crear_excel(ruta, picks=corregidos)
    assert verificar_sello(ruta, 2, set(), ruta_sellos=sellos) == set()


def test_al_arrancar_un_partido_quedan_congelados_sus_picks(tmp_path: Path):
    ruta = crear_excel(tmp_path / "Semana_02.xlsx")
    sellos = tmp_path / "sellos.json"

    assert verificar_sello(ruta, 2, {JUEVES}, ruta_sellos=sellos) == {JUEVES}
    guardado = json.loads(sellos.read_text(encoding="utf-8"))
    assert guardado["2"]["partidos"] == {JUEVES: huellas_por_partido(ruta)[JUEVES]}

    # Sellar de nuevo sin cambios no vuelve a sellar ni truena.
    assert verificar_sello(ruta, 2, {JUEVES}, ruta_sellos=sellos) == set()


def test_cambiar_el_pick_de_un_partido_ya_jugado_truena(tmp_path: Path):
    ruta = crear_excel(tmp_path / "Semana_02.xlsx")
    sellos = tmp_path / "sellos.json"
    verificar_sello(ruta, 2, {JUEVES}, ruta_sellos=sellos)

    tramposos = _copia_de_picks()
    tramposos["Ismael Reyna"][0] = "Lions"   # ya sabiendo cómo salió
    crear_excel(ruta, picks=tramposos)

    with pytest.raises(PicksAlteradosError) as excepcion:
        verificar_sello(ruta, 2, {JUEVES}, ruta_sellos=sellos)
    mensaje = str(excepcion.value)
    assert JUEVES in mensaje                # dice qué partido
    assert "historial de git" in mensaje    # y dónde mirar


def test_el_pick_de_un_partido_que_no_arranca_todavia_se_puede_cambiar(tmp_path: Path):
    """El jueves ya se jugó, pero la tanda del domingo cierra el sábado."""
    ruta = crear_excel(tmp_path / "Semana_02.xlsx")
    sellos = tmp_path / "sellos.json"
    verificar_sello(ruta, 2, {JUEVES}, ruta_sellos=sellos)

    tardios = _copia_de_picks()
    tardios["Ismael Reyna"][3] = "Vikings"
    crear_excel(ruta, picks=tardios)

    assert verificar_sello(ruta, 2, {JUEVES}, ruta_sellos=sellos) == set()
    assert verificar_sello(ruta, 2, {JUEVES, DOMINGO}, ruta_sellos=sellos) == {DOMINGO}


def test_la_hoja_completa_llega_despues_de_la_del_jueves(tmp_path: Path):
    """El organizador manda el jueves aparte y el resto de la semana después."""
    sellos = tmp_path / "sellos.json"
    solo_jueves = crear_excel(
        tmp_path / "Semana_02.xlsx",
        enfrentamientos=ENFRENTAMIENTOS_S2[:1],
        picks={nombre: elegidos[:1] for nombre, elegidos in PICKS_S2.items()},
    )
    assert verificar_sello(solo_jueves, 2, {JUEVES}, ruta_sellos=sellos) == {JUEVES}

    completa = crear_excel(tmp_path / "Semana_02.xlsx")
    assert verificar_sello(completa, 2, {JUEVES}, ruta_sellos=sellos) == set()


def test_borrar_los_picks_de_un_partido_jugado_truena(tmp_path: Path):
    sellos = tmp_path / "sellos.json"
    ruta = crear_excel(tmp_path / "Semana_02.xlsx")
    verificar_sello(ruta, 2, {JUEVES}, ruta_sellos=sellos)

    crear_excel(
        ruta,
        enfrentamientos=ENFRENTAMIENTOS_S2[1:],
        picks={nombre: elegidos[1:] for nombre, elegidos in PICKS_S2.items()},
    )
    with pytest.raises(PicksAlteradosError, match="desaparecieron"):
        verificar_sello(ruta, 2, {JUEVES}, ruta_sellos=sellos)


def test_el_sello_es_por_semana(tmp_path: Path):
    sellos = tmp_path / "sellos.json"
    una = crear_excel(tmp_path / "Semana_01.xlsx", semana=1)
    dos = crear_excel(tmp_path / "Semana_02.xlsx", semana=2)
    verificar_sello(una, 1, {JUEVES}, ruta_sellos=sellos)
    verificar_sello(dos, 2, {JUEVES}, ruta_sellos=sellos)

    guardado = json.loads(sellos.read_text(encoding="utf-8"))
    assert sorted(guardado) == ["1", "2"]


def test_el_sello_viejo_por_archivo_se_convierte_si_nada_cambio(tmp_path: Path):
    """Los sellos de las semanas 1 y 2 se guardaron con la huella del archivo."""
    ruta = crear_excel(tmp_path / "Semana_02.xlsx")
    sellos = tmp_path / "sellos.json"
    sellos.write_text(
        json.dumps({"2": {
            "archivo": ruta.name,
            "sha256": huella(ruta),
            "sellado": "2026-09-21T14:25:57+00:00",
            "congelado": True,
        }}),
        encoding="utf-8",
    )

    assert verificar_sello(ruta, 2, set(), ruta_sellos=sellos) == set()
    guardado = json.loads(sellos.read_text(encoding="utf-8"))
    assert guardado["2"]["partidos"] == huellas_por_partido(ruta)


def test_el_sello_viejo_sigue_atrapando_un_cambio(tmp_path: Path):
    ruta = crear_excel(tmp_path / "Semana_02.xlsx")
    sellos = tmp_path / "sellos.json"
    sellos.write_text(
        json.dumps({"2": {
            "archivo": ruta.name,
            "sha256": huella(ruta),
            "sellado": "2026-09-21T14:25:57+00:00",
            "congelado": True,
        }}),
        encoding="utf-8",
    )

    tramposos = _copia_de_picks()
    tramposos["Ismael Reyna"][0] = "Lions"
    crear_excel(ruta, picks=tramposos)
    with pytest.raises(PicksAlteradosError, match="semana 2"):
        verificar_sello(ruta, 2, {JUEVES}, ruta_sellos=sellos)


def test_sellos_corruptos_avisan(tmp_path: Path):
    ruta = crear_excel(tmp_path / "Semana_02.xlsx")
    sellos = tmp_path / "sellos.json"
    sellos.write_text("{no es json", encoding="utf-8")
    with pytest.raises(Exception, match="no es JSON válido"):
        verificar_sello(ruta, 2, {JUEVES}, ruta_sellos=sellos)


def test_la_huella_cambia_con_el_contenido(tmp_path: Path):
    una = crear_excel(tmp_path / "a.xlsx")
    otra = crear_excel(tmp_path / "b.xlsx", picks={"Solo Yo": list(PICKS_S2["Ismael Reyna"])})
    assert huella(una) != huella(otra)


def test_la_huella_por_partido_solo_mira_su_columna(tmp_path: Path):
    ruta = crear_excel(tmp_path / "Semana_02.xlsx")
    antes = huellas_por_partido(ruta)

    cambiados = _copia_de_picks()
    cambiados["Ismael Reyna"][3] = "Vikings"
    crear_excel(ruta, picks=cambiados)
    despues = huellas_por_partido(ruta)

    assert despues[DOMINGO] != antes[DOMINGO]
    assert {c: h for c, h in despues.items() if c != DOMINGO} == {
        c: h for c, h in antes.items() if c != DOMINGO
    }
