"""Pruebas de la lectura del PDF del organizador."""

from __future__ import annotations

from pathlib import Path

import pytest

from quiniela.pdf import ErrorPDF, extraer_rejilla
from quiniela.picks import ErrorPicks, leer_picks

from .conftest import ENFRENTAMIENTOS_S2, PICKS_S2, crear_excel, crear_pdf


def test_lee_la_rejilla_completa(tmp_path: Path):
    ruta = crear_pdf(tmp_path / "Quiniela 2.pdf")
    semana, visitantes, locales, participantes = extraer_rejilla(ruta)
    assert semana == 2
    assert visitantes == [v for v, _ in ENFRENTAMIENTOS_S2]
    assert locales == [l for _, l in ENFRENTAMIENTOS_S2]
    assert [nombre for nombre, _ in participantes] == list(PICKS_S2)


def test_el_pdf_da_exactamente_lo_mismo_que_el_excel(tmp_path: Path):
    """Es la garantía de que leer el PDF no introduce diferencias."""
    desde_excel = leer_picks(crear_excel(tmp_path / "Semana_02.xlsx"))
    desde_pdf = leer_picks(crear_pdf(tmp_path / "Semana_02.pdf"))
    assert [p.clave for p in desde_excel[0]] == [p.clave for p in desde_pdf[0]]
    assert desde_excel[1] == desde_pdf[1]


def test_ignora_la_columna_de_totales(tmp_path: Path):
    _, picks = leer_picks(crear_pdf(tmp_path / "Semana_02.pdf"))
    assert all(len(elegidos) == 16 for elegidos in picks.values())
    assert all("99" not in elegidos for elegidos in picks.values())


def test_las_validaciones_tambien_aplican_al_pdf(tmp_path: Path):
    malos = {nombre: list(elegidos) for nombre, elegidos in PICKS_S2.items()}
    malos["Ismael Reyna"][0] = "Cowboys"  # no juega ese partido
    ruta = crear_pdf(tmp_path / "Semana_02.pdf", picks=malos)
    with pytest.raises(ErrorPicks, match="eligió Cowboys"):
        leer_picks(ruta)


def test_pdf_sin_capa_de_texto(tmp_path: Path):
    ruta = tmp_path / "escaneado.pdf"
    ruta.write_bytes(b"%PDF-1.4\n1 0 obj <</Type/Catalog>> endobj\n%%EOF\n")
    with pytest.raises(ErrorPDF, match="capa de texto"):
        extraer_rejilla(ruta)


def test_pdf_sin_la_celda_de_semana(tmp_path: Path):
    import zlib
    bloques = "BT /F1 6 Tf 1 0 0 1 200 500 Tm [(Lions)] TJ ET\n"
    comprimido = zlib.compress(bloques.encode("latin-1"))
    ruta = tmp_path / "raro.pdf"
    ruta.write_bytes(b"stream\n" + comprimido + b"\nendstream")
    with pytest.raises(ErrorPDF, match="Semana"):
        extraer_rejilla(ruta)


def test_formato_desconocido(tmp_path: Path):
    ruta = tmp_path / "picks.txt"
    ruta.write_text("nada", encoding="utf-8")
    with pytest.raises(ErrorPicks, match="No sé leer"):
        leer_picks(ruta)


def test_hoja_de_una_sola_tanda(tmp_path: Path):
    """El organizador manda el jueves aparte: un partido y la rejilla centrada.

    Ahí los nombres empiezan mucho más a la derecha que en la hoja completa, así
    que el margen de la columna de nombres no se puede dar por fijo.
    """
    ruta = crear_pdf(
        tmp_path / "Quiniela 3 Jueves.pdf",
        enfrentamientos=[("Falcons", "Packers")],
        picks={"Ismael Reyna": ["Packers"], "Emir Ibarra": ["Falcons"]},
        semana=3,
        centrado=True,
    )
    semana, visitantes, locales, participantes = extraer_rejilla(ruta)
    assert (semana, visitantes, locales) == (3, ["Falcons"], ["Packers"])
    assert participantes == [("Ismael Reyna", ["Packers"]), ("Emir Ibarra", ["Falcons"])]


def test_la_hoja_centrada_tambien_ignora_los_totales(tmp_path: Path):
    ruta = crear_pdf(
        tmp_path / "Semana_03.pdf",
        enfrentamientos=[("Falcons", "Packers")],
        picks={"Ismael Reyna": ["Packers"]},
        semana=3,
        centrado=True,
    )
    _, picks = leer_picks(ruta)
    assert picks == {"Ismael Reyna": ["Packers"]}
