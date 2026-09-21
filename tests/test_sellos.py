"""Pruebas del sellado de picks.

Los picks viven en el repo y solo cambian con un push autenticado, pero un
cambio hecho cuando ya hay resultados no se puede dar por bueno. El sello los
congela en cuanto arranca el primer partido de la semana.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quiniela.picks import PicksAlteradosError, huella, verificar_sello

from .conftest import PICKS_S2, crear_excel


def test_antes_del_arranque_los_picks_se_pueden_corregir(tmp_path: Path):
    ruta = crear_excel(tmp_path / "Semana_02.xlsx")
    sellos = tmp_path / "sellos.json"

    assert verificar_sello(ruta, 2, ya_empezo=False, ruta_sellos=sellos) is False

    # El organizador corrige un pick: sigue siendo válido.
    corregidos = {nombre: list(elegidos) for nombre, elegidos in PICKS_S2.items()}
    corregidos["Ismael Reyna"][3] = "Vikings"
    crear_excel(ruta, picks=corregidos)
    assert verificar_sello(ruta, 2, ya_empezo=False, ruta_sellos=sellos) is False


def test_al_arrancar_la_jornada_quedan_congelados(tmp_path: Path):
    ruta = crear_excel(tmp_path / "Semana_02.xlsx")
    sellos = tmp_path / "sellos.json"

    assert verificar_sello(ruta, 2, ya_empezo=True, ruta_sellos=sellos) is True
    guardado = json.loads(sellos.read_text(encoding="utf-8"))
    assert guardado["2"]["sha256"] == huella(ruta)
    assert guardado["2"]["congelado"] is True

    # Sellar de nuevo sin cambios no vuelve a sellar ni truena.
    assert verificar_sello(ruta, 2, ya_empezo=True, ruta_sellos=sellos) is False


def test_cambiar_los_picks_con_la_jornada_empezada_truena(tmp_path: Path):
    ruta = crear_excel(tmp_path / "Semana_02.xlsx")
    sellos = tmp_path / "sellos.json"
    verificar_sello(ruta, 2, ya_empezo=True, ruta_sellos=sellos)

    tramposos = {nombre: list(elegidos) for nombre, elegidos in PICKS_S2.items()}
    tramposos["Ismael Reyna"][0] = "Lions"   # ya sabiendo cómo salió
    crear_excel(ruta, picks=tramposos)

    with pytest.raises(PicksAlteradosError) as excepcion:
        verificar_sello(ruta, 2, ya_empezo=True, ruta_sellos=sellos)
    mensaje = str(excepcion.value)
    assert "semana 2" in mensaje
    assert huella(ruta) in mensaje          # dice la huella nueva
    assert "historial de git" in mensaje    # y dónde mirar


def test_el_sello_es_por_semana(tmp_path: Path):
    sellos = tmp_path / "sellos.json"
    una = crear_excel(tmp_path / "Semana_01.xlsx", semana=1)
    dos = crear_excel(tmp_path / "Semana_02.xlsx", semana=2)
    verificar_sello(una, 1, ya_empezo=True, ruta_sellos=sellos)
    verificar_sello(dos, 2, ya_empezo=True, ruta_sellos=sellos)

    guardado = json.loads(sellos.read_text(encoding="utf-8"))
    assert sorted(guardado) == ["1", "2"]
    assert guardado["1"]["sha256"] != guardado["2"]["sha256"]


def test_sellos_corruptos_avisan(tmp_path: Path):
    ruta = crear_excel(tmp_path / "Semana_02.xlsx")
    sellos = tmp_path / "sellos.json"
    sellos.write_text("{no es json", encoding="utf-8")
    with pytest.raises(Exception, match="no es JSON válido"):
        verificar_sello(ruta, 2, ya_empezo=True, ruta_sellos=sellos)


def test_la_huella_cambia_con_el_contenido(tmp_path: Path):
    una = crear_excel(tmp_path / "a.xlsx")
    otra = crear_excel(tmp_path / "b.xlsx", picks={"Solo Yo": list(PICKS_S2["Ismael Reyna"])})
    assert huella(una) != huella(otra)
