"""Semana acomoda los partidos con el marcador en vivo encima: lo que ya empezó no se queda en
"Por jugarse" y lo que ya acabó baja a "Ya jugados" aunque el Directo todavía no lo haga oficial.

La respuesta de ESPN es real (la misma de test_jugada_en_vivo.py): 12 partidos terminados,
Steelers @ Bengals en el primer cuarto y uno para el día siguiente.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from quiniela import render_html
from quiniela.equipos import ABREVIATURAS_ESPN

RAIZ = Path(__file__).resolve().parent.parent
PLANTILLA = RAIZ / "quiniela" / "plantillas" / "index.html.j2"
FIJO = RAIZ / "tests" / "fixtures" / "scoreboard_en_juego.json"

con_node = pytest.mark.skipif(shutil.which("node") is None, reason="hace falta node")


def _texto() -> str:
    return PLANTILLA.read_text(encoding="utf-8")


def _funcion(texto: str, nombre: str) -> str:
    inicio = re.search(rf"\n  (async )?function {nombre}\(", texto).start() + 1
    fin = texto.index("\n  }\n", inicio) + 5
    return texto[inicio:fin]


def _constante(texto: str, nombre: str) -> str:
    inicio = texto.index(f"  const {nombre} = ")
    fin = texto.index("\n  };\n", inicio) + 6
    return texto[inicio:fin]


def _node(cuerpo: str):
    texto = _texto()
    funciones = ("parsearVivo", "ultimaJugada", "situacionDe", "efectivo", "gruposDeLaSemana")
    codigo = _constante(texto, "JUGADAS_ESPN") + "\n".join(_funcion(texto, f) for f in funciones)
    datos = {"vivo": {"equipos": ABREVIATURAS_ESPN, "estados": render_html.ESTADOS}, "siglas": render_html._siglas()}
    guion = f"const D = {json.dumps(datos)};\nconst marcadores = new Map();\n{codigo}\n{cuerpo}"
    r = subprocess.run(["node", "-e", guion], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _grupos(juegos: list[dict], equipo: str | None = None) -> dict:
    """Las claves V@L de cada grupo, en el orden en que se pintan."""
    return _node(f"""
    const juegos = {json.dumps(juegos)}.map((p, i) => ({{ p, i }}));
    const g = gruposDeLaSemana(juegos, {json.dumps(equipo)});
    const claves = (lista) => lista.map(({{ p }}) => p.v + "@" + p.l);
    console.log(JSON.stringify({{ mios: claves(g.mios), enVivo: claves(g.enVivo),
      porJugar: claves(g.porJugar), jugados: claves(g.jugados) }}));
    """)


@con_node
def test_con_la_respuesta_real_de_espn_nada_se_queda_en_por_jugarse():
    # Lo oficial todavía no cierra nada (el Directo va atrasado); ESPN ya sabe más.
    salida = _node(f"""
    parsearVivo({FIJO.read_text(encoding="utf-8")}).forEach((v, k) => marcadores.set(k, v));
    const partidos = Array.from(marcadores.keys()).map((k, i) => {{
      const [v, l] = k.split("@");
      return {{ v, l, t: 1000 + i, cerrado: false, e: "Domingo 12:00" }};
    }});
    const juegos = partidos.map(efectivo).map((p, i) => ({{ p, i }}));
    const g = gruposDeLaSemana(juegos, null);
    const claves = (lista) => lista.map(({{ p }}) => p.v + "@" + p.l);
    console.log(JSON.stringify({{ enVivo: claves(g.enVivo), porJugar: claves(g.porJugar), jugados: claves(g.jugados),
      textos: Array.from(new Set(g.jugados.map(({{ p }}) => p.e))) }}));
    """)
    assert salida["enVivo"] == ["Steelers@Bengals"]
    assert len(salida["porJugar"]) == 1 and len(salida["jugados"]) == 12
    # Bajan a "Ya jugados", pero la fila sigue diciendo que falta lo oficial.
    assert salida["textos"] == ["Final · por confirmar"]


@con_node
def test_en_vivo_arriba_luego_lo_que_falta_y_al_final_lo_jugado():
    juegos = [
        {"v": "A", "l": "B", "t": 300},
        {"v": "C", "l": "D", "t": 100, "vivo": True},
        {"v": "E", "l": "F", "t": 200, "porConfirmar": True},
        {"v": "G", "l": "H", "t": 50, "cerrado": True},
        {"v": "I", "l": "J", "t": 0},
        {"v": "K", "l": "L", "t": 250},
    ]
    assert _grupos(juegos) == {
        "mios": [],
        "enVivo": ["C@D"],
        # Por hora; lo que no tiene hora va al final.
        "porJugar": ["K@L", "A@B", "I@J"],
        # Del más reciente al más viejo, oficial o no.
        "jugados": ["E@F", "G@H"],
    }
    # Tu partido encabeza mientras no termine; ya terminado, baja con los demás.
    assert _grupos(juegos, "C")["mios"] == ["C@D"] and _grupos(juegos, "C")["enVivo"] == []
    con_tu_equipo_terminado = _grupos(juegos, "F")
    assert con_tu_equipo_terminado["mios"] == [] and con_tu_equipo_terminado["jugados"] == ["E@F", "G@H"]


def test_la_seccion_en_vivo_va_antes_de_por_jugarse():
    panel = _funcion(_texto(), "panelPartidos")
    assert "gruposDeLaSemana(juegos, equipo)" in panel
    orden = [panel.index(t) for t in ('agrupar(enVivo, "En vivo")', "agrupar(porJugar,", 'agrupar(jugados, "Ya jugados")')]
    assert orden == sorted(orden)
    # Nada de la semana decide su grupo solo con lo oficial.
    assert ".filter(({ p }) => !p.cerrado)" not in panel
