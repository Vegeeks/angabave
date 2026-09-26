"""Pruebas de la línea de comandos.

Es la pieza que corre el workflow, así que conviene que no se rompa en silencio.
"""

from __future__ import annotations

from pathlib import Path

import json

import pytest

import cli
from quiniela.buzon import ErrorBuzon
from quiniela.picks import ErrorPicks, leer_hoja

from .conftest import PICKS_S2, calendario_nfl, crear_excel, crear_pdf


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
        "importar", "buzon", "pendientes", "proximo",
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


@pytest.fixture
def carga_en(picks_en: Path, tmp_path: Path, monkeypatch):
    """Aísla también los sellos y el calendario: nada de red ni del sellos.json real."""
    monkeypatch.setattr(cli, "RUTA_SELLOS", tmp_path / "sellos.json")
    monkeypatch.setattr(cli, "obtener_partidos", lambda anio, semana, sin_red=False: calendario_nfl())
    return picks_en


def _importar(*argumentos: str) -> int:
    return cli.comando_importar(cli.construir_parser().parse_args(["importar", *argumentos]))


def test_importar_guarda_la_semana_en_la_rejilla_de_siempre(carga_en: Path, tmp_path: Path):
    origen = crear_pdf(tmp_path / "Quiniela 1.pdf", semana=1)
    assert _importar(str(origen)) == 0
    assert sorted(p.name for p in carga_en.iterdir()) == ["Semana_01.xlsx"]
    assert leer_hoja(carga_en / "Semana_01.xlsx").picks == PICKS_S2


def test_importar_reemplaza_sin_forzar_y_rechaza_con_1(carga_en: Path, tmp_path: Path):
    assert _importar(str(crear_excel(tmp_path / "Quiniela 1.xlsx", semana=1))) == 0
    cambiados = {n: (["Lions", *e[1:]] if n == "Ismael Reyna" else e) for n, e in PICKS_S2.items()}
    assert _importar(str(crear_excel(tmp_path / "v2.xlsx", semana=1, picks=cambiados))) == 0
    assert leer_hoja(carga_en / "Semana_01.xlsx").picks["Ismael Reyna"][0] == "Lions"
    # --forzar se sigue aceptando para no romper instrucciones viejas.
    assert _importar(str(crear_excel(tmp_path / "v3.xlsx", semana=1)), "--forzar") == 0
    # Una semana que se salta otra se rechaza sin tocar nada.
    assert _importar(str(crear_excel(tmp_path / "Quiniela 3.xlsx", semana=3))) == 1
    assert sorted(p.name for p in carga_en.iterdir()) == ["Semana_01.xlsx"]


def test_importar_deja_reporte_y_resumen(carga_en: Path, tmp_path: Path):
    reporte, resumen = tmp_path / "r.md", tmp_path / "r.json"
    origen = crear_excel(tmp_path / "Quiniela 1.xlsx", semana=1)
    assert _importar(str(origen), "--reporte", str(reporte), "--resumen", str(resumen),
                     "--forma", "https://forma") == 0
    assert reporte.read_text(encoding="utf-8").startswith("### ✅ Semana 1 cargada")
    assert json.loads(resumen.read_text(encoding="utf-8")) == {
        "aceptado": True, "accion": "nueva", "semana": 1,
    }


def test_importar_solo_revisar_no_guarda(carga_en: Path, tmp_path: Path):
    assert _importar(str(crear_excel(tmp_path / "Quiniela 1.xlsx", semana=1)), "--solo-revisar") == 0
    assert list(carga_en.iterdir()) == []


def test_una_falla_de_este_lado_devuelve_3_y_lo_dice(carga_en: Path, tmp_path: Path, monkeypatch):
    def roto(anio, semana, sin_red=False):
        raise RuntimeError("algo interno")
    monkeypatch.setattr(cli, "obtener_partidos", roto)
    reporte = tmp_path / "r.md"
    origen = crear_excel(tmp_path / "Quiniela 1.xlsx", semana=1)
    assert _importar(str(origen), "--reporte", str(reporte)) == 3
    assert "de mi lado" in reporte.read_text(encoding="utf-8")
    assert list(carga_en.iterdir()) == []


def _buzon(tmp_path: Path, evento: dict) -> tuple[int, Path, Path]:
    ruta_evento = tmp_path / "evento.json"
    ruta_evento.write_text(json.dumps(evento), encoding="utf-8")
    reporte, salida = tmp_path / "reporte.md", tmp_path / "archivo.txt"
    opciones = cli.construir_parser().parse_args([
        "buzon", "--evento", str(ruta_evento), "--carpeta", str(tmp_path / "entrada"),
        "--reporte", str(reporte), "--salida", str(salida),
    ])
    return cli.comando_buzon(opciones), reporte, salida


def _evento(cuenta: int) -> dict:
    return {"issue": {
        "number": 3, "user": {"login": "alguien", "id": cuenta},
        "body": "### Archivo de la semana\n\n[Q](https://github.com/user-attachments/files/1/Quiniela.3.xlsx)",
    }}


def test_buzon_contesta_a_quien_no_esta_autorizado(tmp_path: Path):
    codigo, reporte, salida = _buzon(tmp_path, _evento(42))
    assert codigo == 1 and not salida.exists()
    assert reporte.read_text(encoding="utf-8").startswith("### ⛔")


def test_buzon_baja_el_archivo_de_quien_si(tmp_path: Path, monkeypatch):
    def bajar(solicitud, carpeta, sesion=None):
        carpeta.mkdir(parents=True, exist_ok=True)
        destino = carpeta / solicitud.nombre
        destino.write_bytes(b"PK\x03\x04")
        return destino
    monkeypatch.setattr(cli, "descargar", bajar)
    codigo, _, salida = _buzon(tmp_path, _evento(51868211))
    assert codigo == 0
    assert Path(salida.read_text(encoding="utf-8")).name == "Quiniela.3.xlsx"


def test_buzon_explica_una_descarga_fallida(tmp_path: Path, monkeypatch):
    def falla(solicitud, carpeta, sesion=None):
        raise ErrorBuzon("GitHub respondió 404")
    monkeypatch.setattr(cli, "descargar", falla)
    codigo, reporte, _ = _buzon(tmp_path, _evento(51868211))
    assert codigo == 1 and "404" in reporte.read_text(encoding="utf-8")


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
