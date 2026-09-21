"""Pruebas de la línea de comandos.

Es la pieza que corre el workflow, así que conviene que no se rompa en silencio.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import cli
from quiniela.picks import ErrorPicks

from .conftest import crear_excel, crear_pdf


@pytest.fixture
def picks_en(tmp_path: Path, monkeypatch):
    """Apunta el CLI a un directorio de picks de prueba."""
    directorio = tmp_path / "picks"
    directorio.mkdir()
    monkeypatch.setattr(cli, "DIR_PICKS", directorio)
    return directorio


def test_todos_los_subcomandos_existen():
    parser = cli.construir_parser()
    subcomandos = next(
        accion.choices for accion in parser._actions if hasattr(accion, "choices") and accion.choices
    )
    assert set(subcomandos) == {
        "actualizar", "tabla", "general", "escenarios", "validar",
        "importar", "pendientes", "proximo",
    }


def test_cada_subcomando_tiene_funcion():
    parser = cli.construir_parser()
    for comando in ("actualizar", "tabla", "general", "validar", "pendientes", "proximo"):
        opciones = parser.parse_args([comando])
        assert callable(opciones.funcion)


def test_escenarios_exige_participante():
    parser = cli.construir_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["escenarios"])
    opciones = parser.parse_args(["escenarios", "--participante", "Angel D Luffy"])
    assert opciones.participante == "Angel D Luffy"


def test_el_anio_por_defecto_sigue_la_temporada(monkeypatch):
    import datetime as dt

    class Enero(dt.date):
        @classmethod
        def today(cls):
            return cls(2027, 1, 15)

    class Septiembre(dt.date):
        @classmethod
        def today(cls):
            return cls(2026, 9, 20)

    monkeypatch.setattr(cli, "date", Enero)
    assert cli.anio_por_defecto() == 2026  # enero pertenece a la temporada anterior
    monkeypatch.setattr(cli, "date", Septiembre)
    assert cli.anio_por_defecto() == 2026


def test_encuentra_los_picks_en_excel_y_en_pdf(picks_en: Path):
    crear_pdf(picks_en / "Semana_03.pdf", semana=3)
    assert cli.ruta_picks(3).name == "Semana_03.pdf"
    crear_excel(picks_en / "Semana_02.xlsx", semana=2)
    assert cli.ruta_picks(2).name == "Semana_02.xlsx"


def test_si_hay_los_dos_formatos_gana_el_excel(picks_en: Path):
    crear_pdf(picks_en / "Semana_02.pdf", semana=2)
    crear_excel(picks_en / "Semana_02.xlsx", semana=2)
    assert cli.ruta_picks(2).suffix == ".xlsx"
    assert [p.name for p in cli.semanas_disponibles()] == ["Semana_02.xlsx"]


def test_las_semanas_salen_ordenadas(picks_en: Path):
    for semana in (3, 1, 2):
        crear_excel(picks_en / f"Semana_{semana:02d}.xlsx", semana=semana)
    assert [cli.numero_semana(p) for p in cli.semanas_disponibles()] == [1, 2, 3]
    assert cli.ultima_semana() == 3


def test_ignora_los_temporales_de_excel(picks_en: Path):
    crear_excel(picks_en / "Semana_02.xlsx", semana=2)
    (picks_en / "~$Semana_02.xlsx").write_bytes(b"basura")
    assert len(cli.semanas_disponibles()) == 1


def test_sin_picks_el_mensaje_dice_donde_buscar(picks_en: Path):
    with pytest.raises(ErrorPicks, match="disponibles: ninguno"):
        cli.ruta_picks(5)


def test_importar_guarda_con_el_nombre_canonico(picks_en: Path, tmp_path: Path):
    origen = crear_pdf(tmp_path / "Quiniela 3.pdf", semana=3)
    opciones = cli.construir_parser().parse_args(["importar", str(origen), "--semana", "3"])
    assert cli.comando_importar(opciones) == 0
    assert (picks_en / "Semana_03.pdf").exists()


def test_importar_no_pisa_sin_permiso(picks_en: Path, tmp_path: Path):
    origen = crear_pdf(tmp_path / "Quiniela 3.pdf", semana=3)
    opciones = cli.construir_parser().parse_args(["importar", str(origen), "--semana", "3"])
    cli.comando_importar(opciones)
    with pytest.raises(ErrorPicks, match="--forzar"):
        cli.comando_importar(opciones)

    forzado = cli.construir_parser().parse_args(
        ["importar", str(origen), "--semana", "3", "--forzar"]
    )
    assert cli.comando_importar(forzado) == 0


def test_importar_rechaza_un_archivo_inexistente(picks_en: Path, tmp_path: Path):
    opciones = cli.construir_parser().parse_args(["importar", str(tmp_path / "no.pdf")])
    with pytest.raises(ErrorPicks, match="No existe"):
        cli.comando_importar(opciones)


def test_imprimir_tabla_no_publica_el_proyectado(capsys):
    import pandas as pd

    tabla = pd.DataFrame([
        {"posicion": 1, "participante": "Ana", "firme": 12, "errores": 4, "proyectado": 14},
    ])
    cli.imprimir_tabla(tabla, "Prueba")
    salida = capsys.readouterr().out
    assert "PROYECTADO" not in salida.upper()
    assert "Ana" in salida and "12" in salida


def test_un_error_de_picks_devuelve_codigo_1(picks_en: Path):
    codigo = cli.main(["tabla", "--semana", "9"])
    assert codigo == 1
