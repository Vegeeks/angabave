"""Pruebas de la línea de comandos.

Es la pieza que corre el workflow, así que conviene que no se rompa en silencio.
"""

from __future__ import annotations

from pathlib import Path

import json
from datetime import datetime, timedelta, timezone

import pytest

import cli
from quiniela import espn
from quiniela.buzon import ErrorBuzon
from quiniela.espn import Partido
from quiniela.picks import ErrorPicks, leer_hoja
from quiniela.scoring import tabla_general

from .conftest import ENFRENTAMIENTOS_S2, PICKS_S2, calendario_nfl, crear_excel, crear_pdf


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
        "importar", "buzon", "enlace", "proximo",
    }


def test_cada_subcomando_tiene_funcion():
    parser = cli.construir_parser()
    for comando in ("actualizar", "tabla", "general", "validar", "proximo"):
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
    # Partidos siempre en el futuro: el CLI usa la hora real, y con una fecha fija
    # la prueba empezó a fallar en cuanto esa fecha quedó atrás.
    futuro = datetime.now(timezone.utc) + timedelta(days=3)
    monkeypatch.setattr(
        cli, "obtener_partidos", lambda anio, semana, sin_red=False: calendario_nfl(inicio=futuro)
    )
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
    datos = json.loads(resumen.read_text(encoding="utf-8"))
    assert (datos["aceptado"], datos["accion"], datos["semana"]) == (True, "nueva", 1)
    assert datos["titulo"] == "Semana 1 cargada"
    assert (datos["participantes"], datos["partidos_cargados"], datos["partidos_semana"]) == (
        len(PICKS_S2), 16, 16,
    )


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


# --- proximo: de esto depende que el directo se despierte o se duerma ---------


def _proximo(capsys) -> int:
    cli.comando_proximo(cli.construir_parser().parse_args(["proximo"]))
    return int(capsys.readouterr().out.strip())


def _con_partidos(monkeypatch, picks_en: Path, partidos: list[Partido]) -> None:
    crear_excel(picks_en / "Semana_02.xlsx")
    monkeypatch.setattr(cli, "obtener_partidos", lambda anio, semana, sin_red=False: partidos)


def test_proximo_cuenta_los_segundos_al_siguiente(picks_en: Path, monkeypatch, capsys):
    ahora = datetime.now(timezone.utc)
    _con_partidos(monkeypatch, picks_en, [
        Partido("Lions", "Bills", estado="Scheduled", inicio=ahora + timedelta(hours=9)),
        Partido("Saints", "Ravens", estado="Scheduled", inicio=ahora + timedelta(hours=3)),
    ])
    assert 3 * 3600 - 60 < _proximo(capsys) <= 3 * 3600


def test_proximo_es_cero_con_un_partido_en_curso(picks_en: Path, monkeypatch, capsys):
    ahora = datetime.now(timezone.utc)
    _con_partidos(monkeypatch, picks_en, [
        Partido("Lions", "Bills", estado="In Progress", inicio=ahora - timedelta(hours=1)),
        Partido("Saints", "Ravens", estado="Scheduled", inicio=ahora + timedelta(hours=3)),
    ])
    assert _proximo(capsys) == 0


def test_proximo_ignora_una_hora_que_es_relleno(picks_en: Path, monkeypatch, capsys):
    """Con la hora por definir no hay a qué despertarse, aunque el relleno ya haya pasado."""
    ahora = datetime.now(timezone.utc)
    _con_partidos(monkeypatch, picks_en, [
        Partido("Lions", "Bills", estado="Scheduled", inicio=ahora - timedelta(hours=1), hora_definida=False),
        Partido("Saints", "Ravens", estado="Scheduled", inicio=ahora + timedelta(hours=2), hora_definida=False),
    ])
    assert _proximo(capsys) == -1


def test_proximo_no_se_queda_pegado_a_un_partido_pospuesto(picks_en: Path, monkeypatch, capsys):
    """Abierto y con su hora muy atrás: si contara, el directo correría para siempre."""
    ahora = datetime.now(timezone.utc)
    _con_partidos(monkeypatch, picks_en, [
        Partido("Lions", "Bills", estado="Postponed", inicio=ahora - timedelta(days=2)),
    ])
    assert _proximo(capsys) == -1


def test_proximo_sin_nada_abierto_es_menos_uno(picks_en: Path, monkeypatch, capsys):
    _con_partidos(monkeypatch, picks_en, [Partido("Lions", "Bills", 1, 2, "Bills", True, "Final")])
    assert _proximo(capsys) == -1


# --- actualizar: publica solo si hay algo que contar ---------------------------


@pytest.fixture
def sitio(picks_en: Path, tmp_path: Path, monkeypatch):
    """El CLI completo, con ESPN de mentira y sin tocar docs/ ni los datos reales."""
    crear_excel(picks_en / "Semana_02.xlsx")
    dir_sitio = tmp_path / "docs"
    monkeypatch.setattr(cli, "DIR_SITIO", dir_sitio)
    monkeypatch.setattr(cli, "RUTA_SELLOS", tmp_path / "sellos.json")

    # ESPN es lo único de mentira: el caché lo maneja el código de verdad.
    dir_cache = tmp_path / "resultados"
    futuro = datetime.now(timezone.utc) + timedelta(days=2)
    estado = {"partidos": [
        Partido(v, l, 0, 0, None, False, "Scheduled", futuro) for v, l in ENFRENTAMIENTOS_S2
    ]}
    monkeypatch.setattr(espn, "_consultar_api", lambda anio, semana: {"semana": semana})

    def parsear(carga):
        if carga["semana"] != 2:
            raise cli.ErrorESPN("sin partidos todavía")
        return estado["partidos"]

    monkeypatch.setattr(espn, "parsear_scoreboard", parsear)
    monkeypatch.setattr(cli, "obtener_partidos", lambda anio, semana, sin_red=False: espn.obtener_partidos(
        anio, semana, sin_red=sin_red, dir_cache=dir_cache, ruta_overrides=tmp_path / "no.json"))
    monkeypatch.setattr(cli, "tabla_general", lambda rutas: tabla_general(
        rutas, dir_cache=dir_cache, ruta_overrides=tmp_path / "no.json"))
    return dir_sitio, estado


def _actualizar() -> int:
    return cli.comando_actualizar(cli.construir_parser().parse_args(["actualizar"]))


def _huellas(carpeta: Path) -> dict[str, bytes]:
    return {r.name: r.read_bytes() for r in carpeta.iterdir()}


def test_sin_novedad_no_cambia_ni_un_archivo(sitio):
    dir_sitio, _ = sitio
    assert _actualizar() == 0
    antes = _huellas(dir_sitio)
    assert {"index.html", "tabla.png", "portada.png", "version.json"} <= set(antes)
    assert _actualizar() == 0
    assert _huellas(dir_sitio) == antes


def test_un_partido_cerrado_si_se_publica_con_todo_e_imagenes(sitio):
    dir_sitio, estado = sitio
    _actualizar()
    antes = _huellas(dir_sitio)
    primero = estado["partidos"][0]
    estado["partidos"] = [Partido(primero.visitante, primero.local, 10, 20, primero.local, True, "Final", primero.inicio),
                          *estado["partidos"][1:]]
    _actualizar()
    despues = _huellas(dir_sitio)
    for archivo in ("index.html", "tabla.png", "portada.png", "version.json"):
        assert despues[archivo] != antes[archivo], archivo


def test_los_marcadores_de_un_partido_abierto_no_publican_nada(sitio):
    dir_sitio, estado = sitio
    _actualizar()
    antes = _huellas(dir_sitio)
    primero = estado["partidos"][0]
    # Se mueve el marcador, pero el partido todavía es del futuro: no toca latido.
    estado["partidos"] = [Partido(primero.visitante, primero.local, 7, 3, None, False, "In Progress", primero.inicio),
                          *estado["partidos"][1:]]
    _actualizar()
    assert _huellas(dir_sitio) == antes


def test_la_imagen_cuenta_toda_la_semana_y_no_solo_lo_repartido(picks_en: Path, tmp_path: Path, monkeypatch):
    """Con la hoja del jueves decía "1 de 1 partidos" con 14 en la jornada."""
    crear_excel(picks_en / "Semana_02.xlsx", enfrentamientos=ENFRENTAMIENTOS_S2[:1],
                picks={nombre: elegidos[:1] for nombre, elegidos in PICKS_S2.items()})
    monkeypatch.setattr(cli, "DIR_SITIO", tmp_path / "docs")
    monkeypatch.setattr(cli, "RUTA_SELLOS", tmp_path / "sellos.json")
    futuro = datetime.now(timezone.utc) + timedelta(days=2)
    jornada = [Partido(v, l, 0, 0, None, False, "Scheduled", futuro) for v, l in ENFRENTAMIENTOS_S2]
    jornada[0] = Partido(jornada[0].visitante, jornada[0].local, 3, 7, jornada[0].local, True, "Final", futuro)

    def obtener(anio, semana, sin_red=False):
        if semana != 2:
            raise cli.ErrorESPN("sin partidos todavía")
        return jornada

    from quiniela.espn import guardar_cache
    guardar_cache(2, jornada, tmp_path / "resultados")
    monkeypatch.setattr(cli, "obtener_partidos", obtener)
    monkeypatch.setattr(cli, "tabla_general", lambda rutas: tabla_general(
        rutas, dir_cache=tmp_path / "resultados", ruta_overrides=tmp_path / "no.json"))

    vistos = {}
    monkeypatch.setattr(cli, "generar_png", lambda **k: vistos.update(k))
    monkeypatch.setattr(cli, "generar_portada", lambda **k: None)
    assert _actualizar() == 0
    assert (vistos["cerrados"], vistos["total_partidos"]) == (1, 16)


def test_una_semana_vieja_con_un_partido_abierto_tambien_se_consulta(picks_en: Path, monkeypatch, tmp_path: Path):
    """Si la hoja siguiente llegaba antes de cerrar el lunes, ese partido no cerraba nunca."""
    crear_excel(picks_en / "Semana_02.xlsx", semana=2)
    crear_excel(picks_en / "Semana_03.xlsx", semana=3)
    monkeypatch.setattr(cli, "RUTA_SELLOS", tmp_path / "sellos.json")
    pedidas = []

    def obtener(anio, semana, sin_red=False):
        pedidas.append((semana, sin_red))
        return [Partido(v, l, 1, 2, l, True, "Final") for v, l in ENFRENTAMIENTOS_S2]

    monkeypatch.setattr(cli, "obtener_partidos", obtener)
    cli.construir_semanas(2026, False)
    # obtener_partidos es quien decide no tocar la red si ya está todo cerrado.
    assert pedidas == [(2, False), (3, False)]


def test_la_franja_de_la_imagen_es_de_la_ultima_semana_cerrada(picks_en: Path, tmp_path: Path, monkeypatch):
    import pandas as pd

    from quiniela.render_html import SemanaRender

    tabla = pd.DataFrame([
        {"posicion": 1, "participante": "Ana", "firme": 12, "errores": 4},
        {"posicion": 2, "participante": "Beto", "firme": 10, "errores": 6},
    ])
    cerrada = SemanaRender(7, [Partido("Lions", "Bills", 1, 2, "Bills", True, "Final")], {"Ana": ["Bills"]}, tabla)
    en_curso = SemanaRender(8, [Partido("Saints", "Ravens", 1, 2, "Ravens", True, "Final"),
                                Partido("Jets", "Bears", estado="Scheduled")], {"Ana": ["Ravens", "Jets"]}, tabla)
    franja = cli._ganador_para_imagen([cerrada, en_curso], en_curso)
    assert franja["semana_ganadores"] == 7 and franja["ganadores"] == ["Ana"]
    assert franja["oficial"] is True and franja["premio"] == "$5,200"
    # Sin ninguna cerrada todavía no hay nada que presumir.
    assert cli._ganador_para_imagen([en_curso], en_curso) == {}
