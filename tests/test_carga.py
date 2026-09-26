"""Pruebas de la puerta de entrada de los picks.

Cada caso es algo que puede pasar un sábado en la noche con el organizador
solo frente a la forma: el archivo equivocado, la tanda que falta, un pick
cambiado después de empezar, un nombre mal escrito. En todos, o entra bien o
no se toca nada y se explica por qué.
"""

from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import openpyxl
import pytest

from quiniela import carga
from quiniela.carga import recibir, reporte_markdown, reporte_texto
from quiniela.espn import ErrorRed
from quiniela.picks import leer_hoja

from .conftest import ENFRENTAMIENTOS_S2, PICKS_S2, calendario_nfl, crear_excel, crear_pdf

JUEVES = "Lions@Bills"
ANTES_DE_TODO = datetime(2026, 9, 20, tzinfo=timezone.utc)
DESPUES_DEL_JUEVES = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def entorno(tmp_path: Path):
    """Carpeta de picks vacía, sellos aparte y un calendario sin partidos jugados."""
    class Entorno:
        picks = tmp_path / "picks"
        sellos = tmp_path / "sellos.json"
        empezados: set[str] = set()
        ahora = ANTES_DE_TODO
        calendarios: dict[int, list] = {}

        def recibir(self, ruta, **extra):
            opciones = dict(
                calendario=lambda n: self.calendarios.get(n) or calendario_nfl(empezados=self.empezados),
                dir_picks=self.picks,
                ruta_sellos=self.sellos,
                ahora=self.ahora,
            )
            opciones.update(extra)
            return recibir(ruta, **opciones)

    entorno = Entorno()
    entorno.picks.mkdir()
    return entorno


def _picks(**cambios) -> dict[str, list[str]]:
    """Los picks de prueba con algunos cambios: nombre=(indice, equipo)."""
    picks = {nombre: list(elegidos) for nombre, elegidos in PICKS_S2.items()}
    for nombre, (indice, equipo) in cambios.items():
        picks[nombre.replace("_", " ")][indice] = equipo
    return picks


def _archivo(tmp_path: Path, nombre: str, **kw) -> Path:
    (tmp_path / "entrada").mkdir(exist_ok=True)
    return crear_excel(tmp_path / "entrada" / nombre, **kw)


# --- casos que entran ------------------------------------------------------------


def test_semana_nueva_se_guarda_en_la_rejilla_de_siempre(entorno, tmp_path):
    resultado = entorno.recibir(_archivo(tmp_path, "Quiniela 1.xlsx", semana=1))
    assert resultado.aceptado and resultado.accion == "nueva"
    assert resultado.destino == entorno.picks / "Semana_01.xlsx"

    guardada = leer_hoja(resultado.destino)
    assert guardada.semana == 1
    assert [p.clave for p in guardada.partidos] == [f"{v}@{l}" for v, l in ENFRENTAMIENTOS_S2]
    assert guardada.picks == PICKS_S2
    assert (resultado.participantes, resultado.partidos_cargados) == (len(PICKS_S2), 16)


def test_el_pdf_tambien_entra_y_se_guarda_como_excel(entorno, tmp_path):
    resultado = entorno.recibir(crear_pdf(tmp_path / "Quiniela.1.pdf", semana=1))
    assert resultado.aceptado
    assert [p.name for p in entorno.picks.iterdir()] == ["Semana_01.xlsx"]
    assert leer_hoja(resultado.destino).picks == PICKS_S2


def test_el_mismo_archivo_otra_vez_no_cambia_nada(entorno, tmp_path):
    archivo = _archivo(tmp_path, "Quiniela 1.xlsx", semana=1)
    primero = entorno.recibir(archivo)
    marca = primero.destino.stat().st_mtime_ns
    sellos = entorno.sellos.read_text(encoding="utf-8")

    segundo = entorno.recibir(archivo)
    assert segundo.aceptado and segundo.accion == "sin_cambios"
    assert primero.destino.stat().st_mtime_ns == marca
    assert entorno.sellos.read_text(encoding="utf-8") == sellos


def test_reemplazo_antes_de_arrancar_dice_que_cambio(entorno, tmp_path):
    entorno.recibir(_archivo(tmp_path, "Quiniela 1.xlsx", semana=1))
    corregido = _archivo(
        tmp_path, "Quiniela 1 corregida.xlsx", semana=1, picks=_picks(Ismael_Reyna=(3, "Vikings"))
    )
    resultado = entorno.recibir(corregido)
    assert resultado.aceptado and resultado.accion == "reemplazo"
    assert any("Ismael Reyna cambia Bears → Vikings" in c for c in resultado.cambios)
    assert leer_hoja(resultado.destino).picks["Ismael Reyna"][3] == "Vikings"


def test_una_semana_en_pdf_de_antes_queda_en_un_solo_archivo(entorno, tmp_path):
    """Una semana cargada antes como PDF no puede quedar duplicada al reemplazarla."""
    crear_pdf(entorno.picks / "Semana_01.pdf", semana=1)
    corregido = _archivo(
        tmp_path, "Quiniela 1.xlsx", semana=1, picks=_picks(Ismael_Reyna=(3, "Vikings"))
    )
    resultado = entorno.recibir(corregido)
    assert resultado.aceptado
    assert sorted(p.name for p in entorno.picks.iterdir()) == ["Semana_01.xlsx"]


def test_la_tanda_del_domingo_se_junta_con_la_del_jueves(entorno, tmp_path):
    jueves = _archivo(
        tmp_path, "Quiniela 1 Jueves.xlsx", semana=1,
        enfrentamientos=ENFRENTAMIENTOS_S2[:1],
        picks={n: e[:1] for n, e in PICKS_S2.items()},
    )
    entorno.recibir(jueves)
    entorno.empezados, entorno.ahora = {JUEVES}, DESPUES_DEL_JUEVES

    domingo = _archivo(
        tmp_path, "Quiniela 1 Domingo.xlsx", semana=1,
        enfrentamientos=ENFRENTAMIENTOS_S2[1:],
        picks={n: e[1:] for n, e in PICKS_S2.items()},
    )
    resultado = entorno.recibir(domingo)
    assert resultado.aceptado and resultado.accion == "tanda"
    assert resultado.partidos_cargados == 16
    assert leer_hoja(resultado.destino).picks == PICKS_S2


def test_la_hoja_completa_despues_de_la_del_jueves_la_reemplaza(entorno, tmp_path):
    entorno.recibir(_archivo(
        tmp_path, "Jueves.xlsx", semana=1,
        enfrentamientos=ENFRENTAMIENTOS_S2[:1], picks={n: e[:1] for n, e in PICKS_S2.items()},
    ))
    entorno.empezados, entorno.ahora = {JUEVES}, DESPUES_DEL_JUEVES

    resultado = entorno.recibir(_archivo(tmp_path, "Quiniela 1.xlsx", semana=1))
    assert resultado.aceptado and resultado.accion == "reemplazo"
    assert resultado.partidos_cargados == 16


def test_la_hoja_que_llega_tarde_queda_sellada_y_lo_avisa(entorno, tmp_path):
    entorno.empezados, entorno.ahora = {JUEVES}, DESPUES_DEL_JUEVES
    resultado = entorno.recibir(_archivo(tmp_path, "Quiniela 1.xlsx", semana=1))
    assert resultado.aceptado
    assert resultado.sellados == [JUEVES]
    assert JUEVES in json.loads(entorno.sellos.read_text(encoding="utf-8"))["1"]["partidos"]
    assert any("ya habían empezado" in aviso for aviso in resultado.avisos)


def test_la_semana_la_decide_la_hoja_y_el_nombre_solo_avisa(entorno, tmp_path):
    resultado = entorno.recibir(_archivo(tmp_path, "Quiniela 4.xlsx", semana=1))
    assert resultado.aceptado and resultado.semana == 1
    assert any("suena a la semana 4" in aviso for aviso in resultado.avisos)


def test_solo_revisar_no_escribe_nada(entorno, tmp_path):
    resultado = entorno.recibir(_archivo(tmp_path, "Quiniela 1.xlsx", semana=1), escribir=False)
    assert resultado.aceptado and resultado.destino is None
    assert list(entorno.picks.iterdir()) == []
    assert not entorno.sellos.exists()


# --- casos que se rechazan sin tocar nada ---------------------------------------


def _intacto(entorno, antes: dict[str, bytes]) -> bool:
    ahora = {p.name: p.read_bytes() for p in entorno.picks.iterdir()}
    return ahora == antes


def _foto(entorno) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in entorno.picks.iterdir()}


def test_no_se_puede_cambiar_un_pick_de_un_partido_ya_empezado(entorno, tmp_path):
    entorno.recibir(_archivo(tmp_path, "Quiniela 1.xlsx", semana=1))
    entorno.empezados, entorno.ahora = {JUEVES}, DESPUES_DEL_JUEVES
    foto = _foto(entorno)

    tramposo = _archivo(
        tmp_path, "Quiniela 1 v2.xlsx", semana=1, picks=_picks(Tristan_Mejia=(0, "Bills"))
    )
    resultado = entorno.recibir(tramposo)
    assert not resultado.aceptado
    assert JUEVES in resultado.error and "Tristan Mejia" in resultado.error
    assert _intacto(entorno, foto)


def test_tampoco_se_puede_agregar_a_alguien_a_un_partido_ya_empezado(entorno, tmp_path):
    entorno.recibir(_archivo(tmp_path, "Quiniela 1.xlsx", semana=1))
    entorno.empezados, entorno.ahora = {JUEVES}, DESPUES_DEL_JUEVES
    con_uno_mas = {**PICKS_S2, "Nuevo Participante": list(PICKS_S2["Ismael Reyna"])}
    resultado = entorno.recibir(_archivo(tmp_path, "v2.xlsx", semana=1, picks=con_uno_mas))
    assert not resultado.aceptado
    assert "Nuevo Participante" in resultado.error


def test_pero_si_se_puede_cambiar_uno_que_no_ha_empezado(entorno, tmp_path):
    entorno.recibir(_archivo(tmp_path, "Quiniela 1.xlsx", semana=1))
    entorno.empezados, entorno.ahora = {JUEVES}, DESPUES_DEL_JUEVES
    resultado = entorno.recibir(_archivo(
        tmp_path, "v2.xlsx", semana=1, picks=_picks(Ismael_Reyna=(3, "Vikings"))
    ))
    assert resultado.aceptado and resultado.accion == "reemplazo"


def _tanda(tmp_path, nombre, desde, hasta, picks=None, semana=1):
    """Una hoja con solo los partidos [desde, hasta) de la semana de prueba."""
    picks = picks if picks is not None else PICKS_S2
    return _archivo(
        tmp_path, nombre, semana=semana,
        enfrentamientos=ENFRENTAMIENTOS_S2[desde:hasta],
        picks={n: e[desde:hasta] for n, e in picks.items()},
    )


def test_el_jueves_luego_el_domingo_y_luego_el_lunes(entorno, tmp_path):
    """Una tanda por vez, como las reparte el organizador."""
    assert entorno.recibir(_tanda(tmp_path, "jueves.xlsx", 0, 1)).accion == "nueva"
    entorno.empezados, entorno.ahora = {JUEVES}, DESPUES_DEL_JUEVES
    assert entorno.recibir(_tanda(tmp_path, "domingo.xlsx", 1, 14)).accion == "tanda"
    resultado = entorno.recibir(_tanda(tmp_path, "lunes.xlsx", 14, 16))
    assert resultado.accion == "tanda" and resultado.partidos_cargados == 16
    assert leer_hoja(resultado.destino).picks == PICKS_S2


def test_si_a_la_hoja_le_falta_un_partido_se_carga_despues_solo_ese(entorno, tmp_path):
    entorno.recibir(_tanda(tmp_path, "jueves.xlsx", 0, 1))
    sin_el_ultimo = entorno.recibir(_tanda(tmp_path, "casi.xlsx", 1, 15))
    assert sin_el_ultimo.partidos_cargados == 15 and "Faltan 1 partido" in reporte_markdown(sin_el_ultimo)
    resultado = entorno.recibir(_tanda(tmp_path, "el-que-faltaba.xlsx", 15, 16))
    assert resultado.accion == "tanda" and resultado.partidos_cargados == 16
    assert leer_hoja(resultado.destino).picks == PICKS_S2


def test_una_hoja_que_repite_parte_y_trae_otros_suma(entorno, tmp_path):
    """Repite el partido 2 (con un pick corregido), trae el 3 y no trae el 1: el 1 se conserva."""
    entorno.recibir(_tanda(tmp_path, "a.xlsx", 0, 2))
    corregidos = _picks(Ismael_Reyna=(1, "Falcons"))
    resultado = entorno.recibir(_tanda(tmp_path, "b.xlsx", 1, 3, picks=corregidos))
    assert resultado.aceptado and resultado.accion == "tanda" and resultado.partidos_cargados == 3
    assert any("Se agregan 1 partido" in c for c in resultado.cambios)
    assert any("Ismael Reyna cambia Panthers → Falcons" in c for c in resultado.cambios)
    guardada = leer_hoja(resultado.destino)
    assert guardada.picks["Ismael Reyna"] == [PICKS_S2["Ismael Reyna"][0], "Falcons", PICKS_S2["Ismael Reyna"][2]]


def test_una_hoja_solo_con_correcciones_corrige_esos_y_deja_lo_demas(entorno, tmp_path):
    entorno.recibir(_archivo(tmp_path, "Quiniela 1.xlsx", semana=1))
    corregidos = _picks(Ismael_Reyna=(3, "Vikings"))
    resultado = entorno.recibir(_tanda(tmp_path, "correccion.xlsx", 3, 4, picks=corregidos))
    assert resultado.accion == "reemplazo" and resultado.partidos_cargados == 16
    esperado = list(PICKS_S2["Ismael Reyna"])
    esperado[3] = "Vikings"
    assert leer_hoja(resultado.destino).picks["Ismael Reyna"] == esperado


def test_una_correccion_suelta_no_toca_un_partido_ya_empezado(entorno, tmp_path):
    entorno.recibir(_archivo(tmp_path, "Quiniela 1.xlsx", semana=1))
    entorno.empezados, entorno.ahora = {JUEVES}, DESPUES_DEL_JUEVES
    foto = _foto(entorno)
    tramposos = _picks(Tristan_Mejia=(0, "Bills"))
    resultado = entorno.recibir(_tanda(tmp_path, "solo-jueves.xlsx", 0, 1, picks=tramposos))
    assert not resultado.aceptado and JUEVES in resultado.error and "Tristan Mejia" in resultado.error
    assert _intacto(entorno, foto)


def test_una_hoja_que_suma_con_otros_participantes_no_entra(entorno, tmp_path):
    entorno.recibir(_tanda(tmp_path, "a.xlsx", 0, 2))
    sin_ismael = {n: e for n, e in PICKS_S2.items() if n != "Ismael Reyna"}
    resultado = entorno.recibir(_tanda(tmp_path, "b.xlsx", 1, 3, picks=sin_ismael))
    assert not resultado.aceptado and "No vienen en esta hoja: Ismael Reyna" in resultado.error


def test_una_tanda_con_otros_participantes_no_se_junta(entorno, tmp_path):
    entorno.recibir(_archivo(
        tmp_path, "jueves.xlsx", semana=1,
        enfrentamientos=ENFRENTAMIENTOS_S2[:1], picks={n: e[:1] for n, e in PICKS_S2.items()},
    ))
    sin_ismael = {n: e[1:] for n, e in PICKS_S2.items() if n != "Ismael Reyna"}
    resultado = entorno.recibir(_archivo(
        tmp_path, "domingo.xlsx", semana=1,
        enfrentamientos=ENFRENTAMIENTOS_S2[1:], picks=sin_ismael,
    ))
    assert not resultado.aceptado
    assert "No vienen en esta hoja: Ismael Reyna" in resultado.error


def test_no_se_salta_semanas(entorno, tmp_path):
    entorno.recibir(_archivo(tmp_path, "Quiniela 1.xlsx", semana=1))
    resultado = entorno.recibir(_archivo(tmp_path, "Quiniela 3.xlsx", semana=3))
    assert not resultado.aceptado
    assert "falta la 2" in resultado.error


def test_la_primera_carga_tiene_que_ser_la_semana_1(entorno, tmp_path):
    resultado = entorno.recibir(_archivo(tmp_path, "Quiniela 2.xlsx", semana=2))
    assert not resultado.aceptado and "falta la 1" in resultado.error


def test_semana_fuera_de_la_temporada(entorno, tmp_path):
    resultado = entorno.recibir(_archivo(tmp_path, "x.xlsx", semana=19))
    assert not resultado.aceptado and "de la 1 a la 18" in resultado.error


def test_lo_declarado_tiene_que_coincidir_con_la_hoja(entorno, tmp_path):
    resultado = entorno.recibir(_archivo(tmp_path, "x.xlsx", semana=1), semana=2)
    assert not resultado.aceptado and "semana 2" in resultado.error


def test_sin_semana_en_ningun_lado(entorno, tmp_path):
    ruta = _archivo(tmp_path, "picks.xlsx", semana=1)
    libro = openpyxl.load_workbook(ruta)
    libro.active["A2"] = None
    libro.save(ruta)
    resultado = entorno.recibir(ruta)
    assert not resultado.aceptado and "No sé de qué semana es" in resultado.error


def test_un_partido_que_no_es_de_esa_semana(entorno, tmp_path):
    entorno.calendarios[1] = calendario_nfl(ENFRENTAMIENTOS_S2[1:] + [("Jets", "Titans")])
    resultado = entorno.recibir(_archivo(tmp_path, "Quiniela 1.xlsx", semana=1))
    assert not resultado.aceptado and JUEVES in resultado.error


def test_un_partido_al_reves(entorno, tmp_path):
    entorno.calendarios[1] = calendario_nfl([("Bills", "Lions"), *ENFRENTAMIENTOS_S2[1:]])
    resultado = entorno.recibir(_archivo(tmp_path, "Quiniela 1.xlsx", semana=1))
    assert not resultado.aceptado and "al revés" in resultado.error


def test_espn_caido_se_explica(entorno, tmp_path):
    def caido(_numero):
        raise ErrorRed("sin conexión")
    resultado = entorno.recibir(_archivo(tmp_path, "Quiniela 1.xlsx", semana=1), calendario=caido)
    assert not resultado.aceptado and "ESPN no respondió" in resultado.error
    assert list(entorno.picks.iterdir()) == []


@pytest.mark.parametrize("nombre", [
    "<img src=x onerror=alert(1)>",
    "=HYPERLINK(\"http://x\")",
    "Ana; DROP TABLE",
    "A" * 41,
])
def test_nombres_que_no_son_nombres(entorno, tmp_path, nombre):
    picks = {**PICKS_S2, nombre: list(PICKS_S2["Ismael Reyna"])}
    resultado = entorno.recibir(_archivo(tmp_path, "Quiniela 1.xlsx", semana=1, picks=picks))
    assert not resultado.aceptado
    assert "nombre" in resultado.error


def test_avisa_nombres_parecidos_y_ausencias(entorno, tmp_path):
    entorno.recibir(_archivo(tmp_path, "Quiniela 1.xlsx", semana=1))
    otro = {("Ismael Reina" if n == "Ismael Reyna" else n): e for n, e in PICKS_S2.items()}
    entorno.calendarios[2] = calendario_nfl()
    resultado = entorno.recibir(_archivo(tmp_path, "Quiniela 2.xlsx", semana=2, picks=otro))
    assert resultado.aceptado
    avisos = " ".join(resultado.avisos)
    assert "'Ismael Reina' y 'Ismael Reyna' se parecen" in avisos or "'Ismael Reyna' y 'Ismael Reina' se parecen" in avisos
    assert "Estaban en la semana 1 y aquí no vienen: Ismael Reyna" in avisos


# --- el archivo en sí ------------------------------------------------------------


def test_un_archivo_que_no_es_excel(entorno, tmp_path):
    ruta = tmp_path / "Quiniela 1.xlsx"
    ruta.write_bytes(b"esto no es un excel")
    resultado = entorno.recibir(ruta)
    assert not resultado.aceptado and "no lo es" in resultado.error


def test_un_excel_con_contrasena(entorno, tmp_path):
    ruta = tmp_path / "Quiniela 1.xlsx"
    ruta.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 512)
    resultado = entorno.recibir(ruta)
    assert not resultado.aceptado and "contraseña" in resultado.error


def test_un_xls_viejo(entorno, tmp_path):
    ruta = tmp_path / "Quiniela 1.xls"
    ruta.write_bytes(b"\xd0\xcf\x11\xe0")
    resultado = entorno.recibir(ruta)
    assert not resultado.aceptado and ".xlsx" in resultado.error


def test_un_pdf_que_no_es_pdf(entorno, tmp_path):
    ruta = tmp_path / "Quiniela 1.pdf"
    ruta.write_bytes(b"PK\x03\x04 no soy pdf")
    resultado = entorno.recibir(ruta)
    assert not resultado.aceptado and "PDF" in resultado.error


def test_un_archivo_enorme(entorno, tmp_path, monkeypatch):
    monkeypatch.setattr(carga, "TAMANO_MAXIMO", 1000)
    resultado = entorno.recibir(_archivo(tmp_path, "Quiniela 1.xlsx", semana=1))
    assert not resultado.aceptado and "MB" in resultado.error


def test_un_zip_hecho_para_reventar(entorno, tmp_path, monkeypatch):
    monkeypatch.setattr(carga, "DESCOMPRIMIDO_MAXIMO", 1_000_000)
    ruta = tmp_path / "Quiniela 1.xlsx"
    with zipfile.ZipFile(ruta, "w", zipfile.ZIP_DEFLATED) as libro:
        libro.writestr("xl/workbook.xml", "<workbook/>")
        libro.writestr("xl/relleno.bin", b"\0" * 5_000_000)
    assert ruta.stat().st_size < 100_000
    resultado = entorno.recibir(ruta)
    assert not resultado.aceptado and "descomprimido" in resultado.error


def test_un_zip_que_no_es_libro_de_excel(entorno, tmp_path):
    ruta = tmp_path / "Quiniela 1.xlsx"
    with zipfile.ZipFile(ruta, "w") as libro:
        libro.writestr("hola.txt", "hola")
    resultado = entorno.recibir(ruta)
    assert not resultado.aceptado and "libro de Excel" in resultado.error


# --- reportes --------------------------------------------------------------------


def test_reporte_de_rechazo_dice_que_no_se_toco_nada(entorno, tmp_path):
    resultado = entorno.recibir(_archivo(tmp_path, "Quiniela 3.xlsx", semana=3))
    texto = reporte_markdown(resultado, forma="https://forma")
    assert texto.startswith("### ❌")
    assert "No se tocó nada" in texto and "https://forma" in texto


def test_reporte_de_carga_resume_lo_importante(entorno, tmp_path):
    entorno.recibir(_archivo(
        tmp_path, "jueves.xlsx", semana=1,
        enfrentamientos=ENFRENTAMIENTOS_S2[:1], picks={n: e[:1] for n, e in PICKS_S2.items()},
    ))
    resultado = entorno.recibir(_archivo(
        tmp_path, "jueves.xlsx", semana=1,
        enfrentamientos=ENFRENTAMIENTOS_S2[:1],
        picks={n: (["Lions"] if n == "Ismael Reyna" else e[:1]) for n, e in PICKS_S2.items()},
    ))
    texto = reporte_markdown(resultado)
    assert texto.startswith("### ✅ Semana 1 actualizada")
    assert "1 de 16" in texto and "Faltan 15 partido(s)" in texto
    assert "Ismael Reyna cambia Bills → Lions" in texto
    assert "Semana 1 actualizada" in reporte_texto(resultado)


def test_reporte_sin_cambios(entorno, tmp_path):
    archivo = _archivo(tmp_path, "Quiniela 1.xlsx", semana=1)
    entorno.recibir(archivo)
    texto = reporte_markdown(entorno.recibir(archivo))
    assert "ya estaba igual" in texto and "No hubo nada que cambiar" in texto
