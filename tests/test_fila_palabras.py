"""palabrasDeFila: lo que dice cada partido de ti, en palabras y en personas."""
import json
import re
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


def _correr(casos: list[dict]) -> list:
    texto = PLANTILLA.read_text(encoding="utf-8")
    codigo = "\n".join(_funcion(texto, f) for f in ("consenso", "miPick", "palabrasDeFila"))
    guion = f"""
    let jugador = null, borrador = null;
    const D = {{ siglas: {{ Bills: "BUF", Chiefs: "KC" }},
      participantes: ["Ana Ruiz", "Tristan Lopez", "Luis Tello", "Luis Soto", "Mara Paz", "Nora Gil", "Omar Diaz", "Pepe Cruz", "Quique Sol"] }};
    const nombre = (i) => D.participantes[i] || "?";
    const LLAVE_BORRADOR = (n) => "angabave.borrador." + n;
    const leer = () => borrador;
    {codigo}
    const casos = {json.dumps(casos)};
    console.log(JSON.stringify(casos.map((c) => {{
      jugador = c.yo; borrador = c.borrador || null;
      const s = {{ n: 9, jugadores: c.jugadores, picks: c.picks, partidos: [{{ v: "Bills", l: "Chiefs" }}] }};
      return palabrasDeFila(s, c.p, c.col === undefined ? 0 : c.col);
    }})));
    """
    r = subprocess.run(["node", "-e", guion], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _picks(locales: int, visitantes: int, primero="l"):
    """Una columna de picks: 1 es local (Chiefs), 0 visitante (Bills)."""
    cols = [[1]] * locales + [[0]] * visitantes
    if primero == "v":
        cols = cols[::-1]
    return cols


def _caso(yo, locales, visitantes, p, **extra):
    n = locales + visitantes
    return {"yo": yo, "jugadores": list(range(n)), "picks": _picks(locales, visitantes), "p": p, **extra}


ANTES = {"v": "Bills", "l": "Chiefs", "t": 1}
VIVO = {"v": "Bills", "l": "Chiefs", "vivo": True, "mv": 7, "ml": 14, "g": "l"}
FINAL = {"v": "Bills", "l": "Chiefs", "cerrado": True, "mv": 17, "ml": 24, "g": "l"}


def test_antes_de_empezar_con_nombre():
    r = _correr([
        _caso(0, 1, 8, ANTES),          # eres el único local
        _caso(0, 5, 4, ANTES),          # 5 contigo: "Tú y 4 más"
        _caso(0, 8, 1, ANTES),          # demasiados: solo el equipo
    ])
    assert [x["texto"] for x in r] == ["Solo tú", "Tú y 4 más", "Elegiste KC"]
    assert {x["tono"] for x in r} == {"neutro"}


def test_en_juego_ganando_perdiendo_y_empatado():
    ganando = _caso(0, 5, 4, VIVO)
    perdiendo = _caso(8, 5, 4, VIVO)                      # fila 8 le fue al visitante
    empatado = _caso(0, 5, 4, {**VIVO, "g": None, "mv": 7, "ml": 7})
    r = _correr([ganando, perdiendo, empatado])
    assert [(x["texto"], x["tono"]) for x in r] == [
        ("Vas ganando", "bien"), ("Vas perdiendo", "mal"), ("Van empatados", "neutro")]


def test_final_acierto_solo_pocos_y_muchos():
    r = _correr([
        _caso(0, 1, 8, FINAL),
        _caso(0, 5, 4, FINAL),
        _caso(0, 29, 4, FINAL),
    ])
    assert [x["texto"] for x in r] == ["Solo tú", "Tú y 4 más", "Le atinaron 29"]
    assert {x["tono"] for x in r} == {"bien"}


def test_final_fallo_uno_nadie_o_varios():
    uno = _caso(1, 1, 8, FINAL)                                       # solo Ana (fila 0) le atinó
    nadie = _caso(0, 0, 4, {**FINAL, "g": "l"})
    nadie["picks"] = [[0]] * 4
    varios = _caso(31, 29, 4, FINAL)
    r = _correr([uno, nadie, varios])
    assert [x["texto"] for x in r] == ["Le atinó Ana", "Nadie le atinó", "Le atinaron 29"]
    assert {x["tono"] for x in r} == {"mal"}


def test_primer_nombre_repetido_lleva_inicial():
    luis = _caso(0, 1, 8, FINAL)
    luis["jugadores"] = [2] + list(range(1, 9))     # el único acierto es Luis Tello
    luis["yo"] = 5
    assert _correr([luis])[0]["texto"] == "Le atinó Luis T."


def test_el_empate_oficial_no_es_acierto_de_nadie():
    r = _correr([_caso(0, 5, 4, {**FINAL, "g": None, "mv": 20, "ml": 20}),
                 _caso(None, 5, 4, {**FINAL, "g": None, "mv": 20, "ml": 20})])
    assert [(x["texto"], x["tono"]) for x in r] == [("Empate: nadie le atinó", "neutro")] * 2


def test_el_empate_con_x_tambien_es_empate():
    # Los datos oficiales marcan el empate con "x"; ESPN en vivo puede mandarlo vacío.
    r = _correr([_caso(0, 5, 4, {**FINAL, "g": "x", "mv": 20, "ml": 20}),
                 _caso(0, 5, 4, {**VIVO, "g": "x", "mv": 7, "ml": 7})])
    assert [(x["texto"], x["tono"]) for x in r] == [("Empate: nadie le atinó", "neutro"), ("Van empatados", "neutro")]


def test_final_por_confirmar_cuenta_como_terminado():
    por_confirmar = {"v": "Bills", "l": "Chiefs", "porConfirmar": True, "vivo": False, "mv": 3, "ml": 10, "g": "l"}
    assert _correr([_caso(0, 1, 8, por_confirmar)])[0]["texto"] == "Solo tú"


def test_sin_nombre_son_personas_y_no_porcentajes():
    r = _correr([
        _caso(None, 5, 28, ANTES),
        _caso(None, 17, 17, VIVO),
        _caso(None, 3, 30, FINAL),
        _caso(None, 1, 8, FINAL),
        _caso(None, 5, 4, {**FINAL, "g": "v"}),
    ])
    assert [x["texto"] for x in r] == ["28 con BUF", "17 y 17", "Le atinaron 3", "Le atinó Ana", "Le atinaron 4"]
    assert all("%" not in x["texto"] and x["tono"] == "neutro" for x in r)


def test_sin_picks_cargados():
    sin = {"yo": 0, "jugadores": [0, 1], "picks": [[1], [0]], "p": ANTES, "col": -1}
    con_borrador = {**sin, "borrador": json.dumps({"Bills@Chiefs": "v"})}
    r = _correr([sin, con_borrador])
    assert [x["texto"] for x in r] == ["Picks por llegar", "En tu borrador: BUF"]
    assert {x["tono"] for x in r} == {"neutro"}


def test_la_barra_de_abajo_se_pega_solo_en_la_pestana_del_navegador():
    texto = PLANTILLA.read_text(encoding="utf-8")
    assert "navigator.standalone===true" in texto and "r.classList.add('instalada')" in texto
    bloque = texto[texto.index("@media (max-width:899px){\n  html:not(.instalada)"):]
    bloque = bloque[:bloque.index("\n}\n")]
    assert "backdrop-filter:none" in bloque and "box-shadow:none" in bloque and "background:var(--bg)" in bloque
    assert "env(safe-area-inset-bottom)" in bloque


def test_el_vivo_no_consulta_espn_sin_partido_cerca():
    texto = PLANTILLA.read_text(encoding="utf-8")
    assert "hayJuegoCerca(s)" in texto and "15 * 60e3" in texto and "5 * 3600e3" in texto
    assert 'addEventListener("online", consultarVivo)' in texto
