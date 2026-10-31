"""Pruebas del cliente de ESPN. Sin red: todo sale de los fixtures."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from quiniela import espn
from quiniela.espn import (
    ErrorESPN,
    ErrorEstructura,
    Partido,
    aplicar_overrides,
    cargar_cache,
    guardar_cache,
    obtener_partidos,
    parsear_scoreboard,
)

FIXTURES = Path(__file__).parent / "fixtures"


def cargar_fixture(nombre: str) -> dict:
    return json.loads((FIXTURES / nombre).read_text(encoding="utf-8"))


@pytest.fixture
def partidos_s2() -> list[Partido]:
    return parsear_scoreboard(cargar_fixture("scoreboard_semana_02.json"))


def test_parsea_los_cuatro_partidos(partidos_s2):
    assert [p.clave for p in partidos_s2] == [
        "Lions@Bills",
        "Jaguars@Broncos",
        "Washington@Cowboys",
        "Giants@Rams",
    ]


def test_partido_cerrado_normal(partidos_s2):
    bills = partidos_s2[0]
    assert bills.finalizado is True
    assert bills.ganador == "Bills"
    assert (bills.marcador_visitante, bills.marcador_local) == (31, 41)
    assert bills.estado == "Final"
    assert bills.inicio is not None and bills.inicio.year == 2026


def test_empate_cierra_sin_ganador(partidos_s2):
    empate = partidos_s2[1]
    assert empate.finalizado is True
    assert empate.ganador is None
    assert empate.empatado is True
    assert empate.marcador_visitante == empate.marcador_local == 24


def test_reloj_en_ceros_pero_todavia_abierto(partidos_s2):
    """El reloj marca 0:00 y el periodo es el cuarto, pero no cerró."""
    abierto = partidos_s2[2]
    assert abierto.finalizado is False
    assert abierto.ganador is None
    assert abierto.estado == "End of Period"


def test_variantes_de_abreviatura(partidos_s2):
    assert partidos_s2[1].visitante == "Jaguars"   # JAC
    assert partidos_s2[2].visitante == "Washington"  # WAS
    assert partidos_s2[3].local == "Rams"          # LA


def test_lider_de_un_partido_en_curso(partidos_s2):
    assert partidos_s2[2].lider is None  # van empatados 27-27
    assert partidos_s2[0].lider == "Bills"


def test_estructura_inesperada_dice_que_campo_falto():
    with pytest.raises(ErrorEstructura) as excepcion:
        parsear_scoreboard(cargar_fixture("scoreboard_sin_competitors.json"))
    assert "competitors" in str(excepcion.value)
    assert "401772801" in str(excepcion.value)


def test_sin_completed_no_se_infiere_el_cierre():
    with pytest.raises(ErrorEstructura, match="completed"):
        parsear_scoreboard(cargar_fixture("scoreboard_sin_completed.json"))


def test_events_vacio_truena():
    with pytest.raises(ErrorEstructura, match="vacío"):
        parsear_scoreboard({"events": []})


def test_events_ausente_truena():
    with pytest.raises(ErrorEstructura, match="'events'"):
        parsear_scoreboard({"season": {"year": 2026}})


def test_caché_ida_y_vuelta(tmp_path: Path, partidos_s2):
    guardar_cache(2, partidos_s2, tmp_path)
    recuperados = cargar_cache(2, tmp_path)
    assert recuperados == partidos_s2


def test_caché_inexistente_devuelve_vacio(tmp_path: Path):
    assert cargar_cache(9, tmp_path) == []


def _sin_red(*args, **kwargs):
    raise AssertionError("No se debía consultar la API")


def test_no_consulta_la_api_si_todos_los_partidos_cerraron(tmp_path, monkeypatch, partidos_s2):
    cerrados = [
        Partido(p.visitante, p.local, 21, 17, p.local, True, "Final", p.inicio) for p in partidos_s2
    ]
    guardar_cache(2, cerrados, tmp_path)
    monkeypatch.setattr(espn, "_consultar_api", _sin_red)

    partidos = obtener_partidos(2026, 2, dir_cache=tmp_path, ruta_overrides=tmp_path / "no.json")
    assert len(partidos) == 4


def test_los_partidos_cerrados_no_se_refrescan(tmp_path, monkeypatch, partidos_s2):
    """Con un partido abierto sí hay petición, pero los cerrados salen del caché."""
    guardar_cache(2, partidos_s2, tmp_path)
    fixture = cargar_fixture("scoreboard_semana_02.json")
    # La API "cambia de opinión" sobre un partido que ya estaba cerrado.
    fixture["events"][0]["competitions"][0]["competitors"][0]["score"] = "3"
    monkeypatch.setattr(espn, "_consultar_api", lambda anio, semana: fixture)

    partidos = obtener_partidos(2026, 2, dir_cache=tmp_path, ruta_overrides=tmp_path / "no.json")
    assert partidos[0].marcador_local == 41  # el del caché, no el 3 de la API


def test_sin_red_sin_cache_truena(tmp_path):
    with pytest.raises(ErrorESPN, match="sin red"):
        obtener_partidos(2026, 7, sin_red=True, dir_cache=tmp_path)


def test_override_le_gana_a_la_api(tmp_path, partidos_s2, caplog):
    ruta = tmp_path / "overrides.json"
    ruta.write_text(json.dumps({"2": {"Lions@Bills": "Lions"}}), encoding="utf-8")

    with caplog.at_level("WARNING", logger="quiniela.espn"):
        corregidos = aplicar_overrides(partidos_s2, 2, ruta)

    assert partidos_s2[0].ganador == "Bills"       # lo que dijo la API
    assert corregidos[0].ganador == "Lions"        # lo que manda el override
    assert corregidos[0].finalizado is True
    assert "Override aplicado" in caplog.text


def test_override_cierra_un_partido_abierto(tmp_path, partidos_s2):
    ruta = tmp_path / "overrides.json"
    ruta.write_text(json.dumps({"2": {"Washington@Cowboys": "Cowboys"}}), encoding="utf-8")
    corregidos = aplicar_overrides(partidos_s2, 2, ruta)
    assert corregidos[2].finalizado is True
    assert corregidos[2].ganador == "Cowboys"


def test_override_de_un_partido_inexistente_truena(tmp_path, partidos_s2):
    ruta = tmp_path / "overrides.json"
    ruta.write_text(json.dumps({"2": {"Bears@Packers": "Bears"}}), encoding="utf-8")
    with pytest.raises(ErrorESPN, match="no corresponde a ningún partido"):
        aplicar_overrides(partidos_s2, 2, ruta)


def test_override_con_equipo_que_no_juega_ese_partido(tmp_path, partidos_s2):
    ruta = tmp_path / "overrides.json"
    ruta.write_text(json.dumps({"2": {"Lions@Bills": "Cowboys"}}), encoding="utf-8")
    with pytest.raises(ErrorESPN, match="no juega ese partido"):
        aplicar_overrides(partidos_s2, 2, ruta)


def test_reintentos_con_espera_exponencial(monkeypatch):
    esperas: list[float] = []
    intentos = {"n": 0}

    def get_falla(*args, **kwargs):
        intentos["n"] += 1
        raise RuntimeError("conexión rechazada")

    monkeypatch.setattr(espn.requests, "get", get_falla)
    monkeypatch.setattr(espn.time, "sleep", lambda segundos: esperas.append(segundos))

    with pytest.raises(espn.ErrorRed, match="después de 3 intentos"):
        espn._consultar_api(2026, 2)
    assert intentos["n"] == 3
    assert esperas == [1.0, 2.0]


# --- la hora por definir -------------------------------------------------------


def _con_hora_por_definir() -> dict:
    fixture = cargar_fixture("scoreboard_semana_02.json")
    fixture["events"][1]["competitions"][0]["timeValid"] = False
    return fixture


def test_lee_cuando_la_nfl_no_ha_puesto_hora():
    partidos = parsear_scoreboard(_con_hora_por_definir())
    assert partidos[1].hora_definida is False
    assert partidos[0].hora_definida is True   # sin el campo también cuenta como definida


def test_la_hora_por_definir_sobrevive_al_cache(tmp_path: Path):
    partidos = parsear_scoreboard(_con_hora_por_definir())
    guardar_cache(2, partidos, tmp_path)
    assert cargar_cache(2, tmp_path) == partidos


def test_un_cache_viejo_sin_el_campo_se_lee_como_definida(tmp_path: Path):
    (tmp_path / "semana_02.json").write_text(json.dumps({"semana": 2, "partidos": [
        {"visitante": "Lions", "local": "Bills", "estado": "Scheduled", "inicio": "2026-09-20T17:00:00+00:00"},
    ]}), encoding="utf-8")
    assert cargar_cache(2, tmp_path)[0].hora_definida is True


def test_una_hora_de_relleno_no_cuenta_como_arranque():
    ayer = datetime(2026, 12, 27, 5, tzinfo=timezone.utc)
    ahora = ayer + timedelta(days=1)
    relleno = Partido("Lions", "Bills", estado="Scheduled", inicio=ayer, hora_definida=False)
    assert relleno.sin_hora and not relleno.arranco(ahora) and not relleno.en_curso(ahora)
    # Si ESPN ya lo trae jugándose, se le cree aunque no haya corregido el campo.
    jugandose = Partido("Lions", "Bills", estado="In Progress", inicio=ayer, hora_definida=False)
    assert not jugandose.sin_hora and jugandose.arranco(ahora)


def test_en_curso_tiene_un_limite():
    arranque = datetime(2026, 12, 27, 18, tzinfo=timezone.utc)
    partido = Partido("Lions", "Bills", estado="In Progress", inicio=arranque)
    assert partido.en_curso(arranque + timedelta(hours=5))
    assert not partido.en_curso(arranque + timedelta(hours=13))
    assert partido.arranco(arranque + timedelta(hours=13))   # arrancó, pero ya no se sigue
    assert not partido.en_curso(arranque - timedelta(minutes=1))


# --- el caché solo cambia si cambia algo que dure ------------------------------


def _semana_con(tmp_path, monkeypatch, partidos, frescos):
    guardar_cache(2, partidos, tmp_path)
    monkeypatch.setattr(espn, "_consultar_api", lambda anio, semana: {})
    monkeypatch.setattr(espn, "parsear_scoreboard", lambda carga: frescos)
    antes = (tmp_path / "semana_02.json").read_bytes()
    regreso = obtener_partidos(2026, 2, dir_cache=tmp_path, ruta_overrides=tmp_path / "no.json")
    return regreso, (tmp_path / "semana_02.json").read_bytes() != antes


_ARRANQUE = datetime(2026, 9, 20, 17, tzinfo=timezone.utc)


def test_un_marcador_en_curso_no_reescribe_el_cache_pero_si_se_devuelve(tmp_path, monkeypatch):
    previo = [Partido("Lions", "Bills", 0, 0, None, False, "Scheduled", _ARRANQUE)]
    fresco = [Partido("Lions", "Bills", 7, 3, None, False, "In Progress", _ARRANQUE)]
    regreso, cambio = _semana_con(tmp_path, monkeypatch, previo, fresco)
    assert not cambio
    assert regreso[0].marcador_visitante == 7


@pytest.mark.parametrize("fresco", [
    Partido("Lions", "Bills", 7, 3, "Lions", True, "Final", _ARRANQUE),
    Partido("Lions", "Bills", 0, 0, None, False, "Scheduled", _ARRANQUE + timedelta(hours=3)),
    Partido("Lions", "Bills", 0, 0, None, False, "Postponed", _ARRANQUE),
    Partido("Lions", "Bills", 0, 0, None, False, "Scheduled", _ARRANQUE, hora_definida=False),
], ids=["cerro", "cambio-la-hora", "pospuesto", "hora-por-definir"])
def test_lo_que_dura_si_reescribe_el_cache(tmp_path, monkeypatch, fresco):
    previo = [Partido("Lions", "Bills", 0, 0, None, False, "Scheduled", _ARRANQUE)]
    _, cambio = _semana_con(tmp_path, monkeypatch, previo, [fresco])
    assert cambio
