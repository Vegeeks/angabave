"""El duelo de la ficha y la distancia de la barra: las funciones puras, corridas en node."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

PLANTILLA = Path(__file__).resolve().parent.parent / "quiniela" / "plantillas" / "index.html.j2"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="hace falta node")


def _funcion(texto: str, nombre: str) -> str:
    inicio = texto.index(f"  function {nombre}(")
    fin = texto.index("\n  }\n", inicio) + 5
    return texto[inicio:fin]


def _correr(expresion: str, **datos):
    texto = PLANTILLA.read_text(encoding="utf-8")
    codigo = "\n".join(_funcion(texto, f) for f in ("nombreCorto", "distanciaEnTemporada", "duelaLaPareja"))
    guion = f"""
    {codigo}
    const datos = {json.dumps(datos)};
    console.log(JSON.stringify({expresion}));
    """
    r = subprocess.run(["node", "-e", guion], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _semana(n, picks_a, picks_b, ganadores, estado="cerrada", fa=0, fb=0):
    """Una semana con dos jugadores (0 y 1). ganadores: 'v', 'l' o 'x' por partido."""
    return {
        "n": n, "estado": estado, "jugadores": [0, 1],
        "partidos": [{"cerrado": True, "g": g} for g in ganadores],
        "picks": [picks_a, picks_b],
        "tabla": [{"p": 0, "f": fa, "e": 0, "pos": 1}, {"p": 1, "f": fb, "e": 0, "pos": 2}],
    }


def test_semanas_ganadas_perdidas_y_empatadas():
    semanas = [
        _semana(1, [1, 1], [0, 0], ["l", "l"], fa=2, fb=0),
        _semana(2, [1, 1], [0, 0], ["v", "v"], fa=0, fb=2),
        _semana(3, [1, 0], [1, 0], ["l", "v"], fa=2, fb=2),
        _semana(4, [1, 1], [0, 0], ["l", "l"], estado="abierta", fa=2, fb=0),   # sin cerrar: no cuenta
    ]
    r = _correr("duelaLaPareja(0, 1, datos.semanas)", semanas=semanas)
    assert r["sem"] == {"a": 1, "b": 1, "empates": 1}


def test_diferencias_con_acierto_de_uno_del_otro_y_de_ninguno():
    # Igual, A acierta, B acierta, empate oficial, igual.
    s = _semana(1, [1, 1, 0, 1, 0], [1, 0, 1, 0, 0], ["l", "l", "l", "x", "v"], fa=3, fb=3)
    r = _correr("duelaLaPareja(0, 1, datos.semanas)", semanas=[s])
    assert r["igual"] == 2 and r["comparados"] == 5
    assert r["dif"] == {"a": 1, "b": 1, "ninguno": 1}


def test_sin_pick_y_partidos_sin_cerrar_no_cuentan():
    s = _semana(1, [1, None, 1, 1], [0, 1, 2, 0], ["l", "l", "l", "l"], fa=1, fb=0)
    s["partidos"][3]["cerrado"] = False
    r = _correr("duelaLaPareja(0, 1, datos.semanas)", semanas=[s])
    # Solo cuenta el primero: el segundo y el tercero no tienen pick válido y el cuarto no está cerrado.
    assert r["comparados"] == 1 and r["dif"] == {"a": 1, "b": 0, "ninguno": 0}


def test_el_empate_oficial_no_es_acierto_de_nadie_ni_cuando_eligieron_igual():
    s = _semana(1, [1, 0], [0, 0], ["x", "x"], fa=0, fb=0)
    r = _correr("duelaLaPareja(0, 1, datos.semanas)", semanas=[s])
    assert r["igual"] == 1 and r["dif"] == {"a": 0, "b": 0, "ninguno": 1}


def test_la_diferencia_de_aciertos_sale_de_donde_difieren():
    s = _semana(1, [1, 1, 0, 0, 1, 1], [1, 0, 0, 1, 0, 1], ["l", "l", "v", "l", "v", "x"], fa=3, fb=4)
    r = _correr("duelaLaPareja(0, 1, datos.semanas)", semanas=[s])
    assert r["dif"] == {"a": 1, "b": 2, "ninguno": 0}
    assert r["igual"] == 3
    assert r["dif"]["a"] - r["dif"]["b"] == -1


GENERAL = [
    {"p": 0, "pos": 1, "total": 94, "err": 5},
    {"p": 1, "pos": 2, "total": 90, "err": 9},
    {"p": 2, "pos": 3, "total": 88, "err": 11},
    {"p": 3, "pos": 3, "total": 88, "err": 11},
    {"p": 4, "pos": 5, "total": 80, "err": 19},
]
NOMBRES = ["Ana Ruiz", "Marco Diaz", "Luis Tello", "Luis Soto", "Pepe Cruz"]


def _dist(idx, general=GENERAL):
    return _correr("distanciaEnTemporada(datos.general, datos.nombres, datos.idx)", general=general, nombres=NOMBRES, idx=idx)


def test_distancia_con_uno_justo_arriba():
    assert _dist(1) == "A 4 de Ana"


def test_distancia_con_varios_empatados_arriba():
    assert _dist(4) == "A 8 del 3.º"


def test_distancia_con_nombre_repetido_lleva_inicial():
    general = [{"p": 2, "pos": 1, "total": 90, "err": 1}, {"p": 4, "pos": 2, "total": 89, "err": 2}]
    assert _dist(4, general) == "A 1 de Luis T."


def test_distancia_del_primero():
    assert _dist(0) == "Le llevas 4 a Marco"
    general = [GENERAL[0], {"p": 1, "pos": 2, "total": 90, "err": 9}, {"p": 4, "pos": 2, "total": 90, "err": 9}]
    assert _dist(0, general) == "Le llevas 4 al 2.º"


def test_distancia_empatado_en_la_punta_y_sin_partidos():
    general = [{"p": 0, "pos": 1, "total": 94, "err": 5}, {"p": 1, "pos": 1, "total": 94, "err": 5}]
    assert _dist(0, general) == "Empatas en la punta"
    vacia = [{"p": 0, "pos": 1, "total": 0, "err": 0}, {"p": 1, "pos": 1, "total": 0, "err": 0}]
    assert _dist(0, vacia) == "Temporada"
