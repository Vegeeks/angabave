"""v0.34: "Qué pasa si…", el cierre de la semana y la jugada de tu pick, probados en node."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

PLANTILLA = Path(__file__).resolve().parent.parent / "quiniela" / "plantillas" / "index.html.j2"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="hace falta node")

NOMBRES = ["Ana Ruiz", "Beto Gil", "Carla Paz", "Dani Soto", "Eli Cruz", "Fer Diaz"]


def _funcion(texto: str, nombre: str) -> str:
    inicio = texto.index(f"  function {nombre}(")
    fin = texto.index("\n  }\n", inicio) + 5
    return texto[inicio:fin]


def _correr(funciones: tuple[str, ...], llamada: str, casos: list) -> list:
    texto = PLANTILLA.read_text(encoding="utf-8")
    codigo = "\n".join(_funcion(texto, f) for f in funciones)
    guion = f"""
    const ordinal = (n) => n + ".º";
    const nombre = (i) => {json.dumps(NOMBRES)}[i];
    {codigo}
    const casos = {json.dumps(casos)};
    console.log(JSON.stringify(casos.map((c) => {llamada})));
    """
    r = subprocess.run(["node", "-e", guion], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


# ── Qué pasa si… ────────────────────────────────────────────────────────────
def _semana(picks, f, **extra):
    """Seis participantes; `picks[i][col]` es 1 si eligió al local. `f` son los aciertos oficiales."""
    s = {"n": 9, "proyectable": True, "por_entregar": [], "jugadores": list(range(len(picks))), "picks": picks,
         "tabla": [{"p": i, "f": f[i], "e": 0, "pos": 1} for i in range(len(picks))]}
    s.update(extra)
    return s


def _juego(v, l, **extra):
    return {"v": v, "l": l, "cerrado": False, **extra}


def _desenlaces(s, juegos):
    return _correr(("desenlacesDeLaSemana",), "desenlacesDeLaSemana(c.s, c.juegos)", [{"s": s, "juegos": juegos}])[0]


def _quien(fila):
    return sorted(fila["ganadores"])


def test_un_partido_que_cambia_al_ganador():
    # Ana y Beto van con 5; Ana eligió Eagles (visitante) y Beto Washington (local).
    s = _semana([[0], [1], [1], [0], [1], [1]], [5, 5, 3, 3, 3, 3])
    r = _desenlaces(s, [_juego("Eagles", "Washington")])
    assert [a["col"] for a in r["abiertos"]] == [0]
    assert [(f["pone"][0]["equipo"], _quien(f)) for f in r["filas"]] == [("Eagles", [0]), ("Washington", [1])]


def test_sin_pick_no_cuenta_como_visitante():
    # Beto no tiene pick en el partido: si gana el visitante, Ana gana sola con 6 y Beto se queda en 5.
    s = _semana([[0], [None], [1], [1], [1], [1]], [5, 5, 3, 3, 3, 3])
    r = _desenlaces(s, [_juego("Eagles", "Washington")])
    assert [(f["pone"][0]["equipo"], _quien(f)) for f in r["filas"]] == [("Eagles", [0]), ("Washington", [0, 1])]


def test_un_partido_que_no_cambia_nada_es_una_sola_fila():
    s = _semana([[0], [1], [1], [0], [1], [1]], [9, 5, 3, 3, 3, 3])
    r = _desenlaces(s, [_juego("Eagles", "Washington")])
    assert len(r["filas"]) == 1
    assert r["filas"][0]["pone"] == [] and r["filas"][0]["ganadores"] == [0]


def test_dos_partidos_dan_cuatro_desenlaces():
    # Ana (0) y Beto (1) van con 5 y eligieron al revés en los dos partidos.
    s = _semana([[0, 0], [1, 1], [1, 0], [0, 1], [1, 1], [1, 1]], [5, 5, 4, 4, 3, 3])
    r = _desenlaces(s, [_juego("A", "B"), _juego("C", "D")])
    assert [[x["equipo"] for x in f["pone"]] for f in r["filas"]] == [["A", "C"], ["A", "D"], ["B", "C"], ["B", "D"]]
    assert _quien(r["filas"][0]) == [0] and _quien(r["filas"][3]) == [1]
    assert all(len(f["ganadores"]) >= 1 for f in r["filas"])


def test_los_desenlaces_iguales_se_juntan():
    # Ana y Beto van con 5 y eligen igual el segundo partido: solo importa el primero.
    s = _semana([[0, 0], [1, 0], [1, 1], [1, 1], [1, 1], [1, 1]], [5, 5, 1, 1, 1, 1])
    r = _desenlaces(s, [_juego("A", "B"), _juego("C", "D")])
    assert [[x["equipo"] for x in f["pone"]] for f in r["filas"]] == [["A"], ["B"]]
    assert [_quien(f) for f in r["filas"]] == [[0], [1]]


def test_el_empate_de_personas_reparte():
    s = _semana([[0], [0], [1], [1], [1], [1]], [5, 5, 4, 4, 4, 4])
    r = _desenlaces(s, [_juego("A", "B")])
    gana = {f["pone"][0]["equipo"]: _quien(f) for f in r["filas"]}
    assert gana["A"] == [0, 1]
    assert gana["B"] == [0, 1, 2, 3, 4, 5]


def test_un_partido_terminado_sin_confirmar_cuenta_con_su_resultado():
    # El primero ya terminó (ganó el visitante A) y aún no se confirma: solo Ana lo eligió.
    s = _semana([[0, 0], [1, 0], [1, 0], [1, 0], [1, 0], [1, 0]], [5, 5, 5, 5, 5, 5])
    r = _desenlaces(s, [_juego("A", "B", porConfirmar=True, g="v"), _juego("C", "D")])
    assert [a["col"] for a in r["abiertos"]] == [1]
    assert len(r["filas"]) == 1 and _quien(r["filas"][0]) == [0]


def test_no_aplica_con_tres_o_mas_partidos_ni_con_picks_por_entregar_ni_sin_proyeccion():
    s = _semana([[0, 0, 0]] * 6, [5] * 6)
    tres = [_juego("A", "B"), _juego("C", "D"), _juego("E", "F")]
    assert _desenlaces(s, tres) is None
    assert _desenlaces({**s, "por_entregar": [{"v": "X", "l": "Y"}]}, tres[:1] + [dict(tres[1], cerrado=True)] * 2) is None
    assert _desenlaces({**s, "proyectable": False}, [_juego("A", "B"), dict(tres[1], cerrado=True), dict(tres[2], cerrado=True)]) is None
    assert _desenlaces(s, [dict(j, cerrado=True) for j in tres]) is None


def test_quien_gana_le_habla_a_quien_lo_lee():
    casos = [
        {"g": [2], "yo": 2}, {"g": [2, 4, 5], "yo": 4}, {"g": [3], "yo": 2},
        {"g": [3, 0, 5], "yo": 2}, {"g": [3], "yo": None}, {"g": [1, 0], "yo": None},
    ]
    r = _correr(("quienGana",), "quienGana(c.g, c.yo, nombre)", casos)
    assert [x["fila"] for x in r] == ["Ganas tú", "Empatas con 2", "Dani Soto", "Ana Ruiz y 2 más", "Dani Soto", "Ana Ruiz y 1 más"]
    assert r[0]["mio"] and r[1]["mio"] and not r[2]["mio"]
    assert r[2]["frase"] == "gana Dani Soto" and r[3]["frase"] == "ganan Ana Ruiz y 2 más" and r[0]["frase"] == "ganas tú"


# ── el cierre de la semana ─────────────────────────────────────────────────
def _cerrada(ganadores, **extra):
    partidos = [{"cerrado": True, "g": "l"}] * 15
    tabla = [{"p": 0, "f": 11, "e": 4, "pos": 1}, {"p": 1, "f": 11, "e": 4, "pos": 1},
             {"p": 2, "f": 9, "e": 6, "pos": 3}, {"p": 3, "f": 7, "e": 8, "pos": 4}]
    tabla = [f for f in tabla if f["pos"] != 1 or f["p"] in ganadores]
    s = {"n": 9, "oficial": True, "cerrados": 15, "partidos": partidos, "ganadores": ganadores, "tabla": tabla, "premio": "$5,200"}
    s.update(extra)
    return s


def _cierre(s, yo):
    return _correr(("cierreDeSemana",), "cierreDeSemana(c.s, c.yo, nombre)", [{"s": s, "yo": yo}])[0]


def test_ganaste_la_semana_con_tus_aciertos_y_lo_que_cobras():
    r = _cierre(_cerrada([0]), 0)
    assert r["gano"] and " ".join(r["titulo"]) == "Ganaste la semana 9"
    assert r["detalle"] == "11 de 15. Cobras $5,200." and not r["perfecta"]


def test_empataste_la_semana():
    s = _cerrada([0, 1], premio="$2,600")
    r = _cierre(s, 1)
    assert " ".join(r["titulo"]) == "Ganaste la semana 9 con 1 más"
    assert r["detalle"] == "11 de 15. Cobras $2,600."


def test_semana_perfecta_es_acertar_todo_lo_que_tuvo_ganador():
    s = _cerrada([0])
    s["partidos"] = [{"cerrado": True, "g": "l"}] * 11 + [{"cerrado": True, "g": None}] * 4
    assert _cierre(s, 0)["perfecta"]
    s["partidos"] = [{"cerrado": True, "g": "l"}] * 12 + [{"cerrado": True, "g": None}] * 3
    assert not _cierre(s, 0)["perfecta"]


def test_si_no_ganaste_te_dice_quien_y_como_quedaste_sin_juicios():
    r = _cierre(_cerrada([0]), 2)
    assert not r["gano"] and " ".join(r["titulo"]) == "Ganó Ana Ruiz"
    assert r["detalle"] == "11 de 15. Tú: 9, 3.º."
    r = _cierre(_cerrada([0, 1]), 3)
    assert " ".join(r["titulo"]) == "Ganaron 2 con 11" and r["detalle"] == "11 de 15. Tú: 7, 4.º."


def test_sin_nombre_dice_quien_gano_y_nada_mas():
    r = _cierre(_cerrada([1]), None)
    assert " ".join(r["titulo"]) == "Ganó Beto Gil" and r["detalle"] == "11 de 15."


def test_una_semana_sin_confirmar_no_tiene_cierre():
    assert _cierre(_cerrada([0], oficial=False), 0) is None


# ── la jugada de tu pick ───────────────────────────────────────────────────
def _marcador(mv, ml, e="Q3 · 8:00", g=None, completado=False):
    if g is None and mv != ml:
        g = "v" if mv > ml else "l"
    return {"v": "Bengals", "l": "Chiefs", "mv": mv, "ml": ml, "g": g, "e": e, "completado": completado, "enJuego": not completado}


def _jugada(previo, valor, lado):
    return _correr(("jugadaDe",), "jugadaDe(c.previo, c.valor, c.lado)", [{"previo": previo, "valor": valor, "lado": lado}])[0]


def test_touchdown_a_favor_y_en_contra():
    previo = _marcador(10, 10, e="Q1 · 3:00")
    a_favor = _jugada(previo, _marcador(10, 17, e="Q1 · 1:00"), "l")
    assert a_favor == {"tipo": "touchdown", "texto": "Touchdown de Chiefs: 17–10", "aFavor": True}
    en_contra = _jugada(previo, _marcador(10, 17, e="Q1 · 1:00"), "v")
    assert en_contra == {"tipo": "touchdown", "texto": "Touchdown de Chiefs: 17–10", "aFavor": False}
    assert _jugada(_marcador(14, 10, e="Q2"), _marcador(14, 13, e="Q2"), "l") is None   # gol de campo


def test_volteo_solo_del_tercer_cuarto_en_adelante():
    q2 = _jugada(_marcador(10, 12), _marcador(13, 12, e="Q2 · 0:10"), "l")
    assert q2 is None
    q3 = _jugada(_marcador(10, 12, e="Q3 · 9:00"), _marcador(13, 12, e="Q3 · 5:00"), "v")
    assert q3 == {"tipo": "volteo", "texto": "Ahora va ganando tu pick: Bengals 13–12", "aFavor": True}
    contra = _jugada(_marcador(10, 12, e="Q4 · 9:00"), _marcador(13, 12, e="Q4 · 5:00"), "l")
    assert contra == {"tipo": "volteo", "texto": "Ahora va perdiendo tu pick: Bengals 13–12", "aFavor": False}


def test_final_ganado_y_perdido():
    previo = _marcador(20, 24, e="Q4 · 0:20")
    ganado = _jugada(previo, _marcador(20, 27, e="Final", completado=True), "l")
    assert ganado == {"tipo": "final", "texto": "Ganó tu pick: Chiefs 27–20", "aFavor": True}
    perdido = _jugada(previo, _marcador(20, 27, e="Final", completado=True), "v")
    assert perdido == {"tipo": "final", "texto": "Perdió tu pick: Bengals 20–27", "aFavor": False}


def test_correccion_a_la_baja_sin_pick_o_sin_nombre_no_avisa():
    previo = _marcador(10, 17, e="Q3")
    assert _jugada(previo, _marcador(10, 14, e="Q3"), "l") is None
    assert _jugada(_marcador(10, 10, e="Q1"), _marcador(10, 17, e="Q1"), None) is None
    assert _jugada(None, _marcador(10, 17), "l") is None
    assert _jugada(_marcador(10, 17, e="Q4"), _marcador(10, 17, e="Q4"), "l") is None


# ── lo que va en la página ─────────────────────────────────────────────────
def test_las_piezas_estan_en_su_lugar_y_la_jugada_va_fuera_de_la_consulta():
    texto = PLANTILLA.read_text(encoding="utf-8")
    inicio = texto.index("async function consultarVivo(")
    consulta = texto[inicio:texto.index("\n  }\n", inicio)]
    assert consulta.index("avisarJugadas(s, cambios)") > consulta.index("} finally {")
    assert 'id="jugadas" aria-live="polite"' in texto
    assert "semanal_por_ganadores" in texto
