"""La general en navidad: un regalo por persona, entre más abajo peor envuelto, y nada encimado."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
PLANTILLA = RAIZ / "quiniela" / "plantillas" / "index.html.j2"

con_node = pytest.mark.skipif(shutil.which("node") is None, reason="hace falta node")

# La general del 20 de noviembre: cuántos llevaban cada número de aciertos.
REAL = {85: 1, 86: 1, 89: 1, 90: 3, 92: 1, 93: 4, 95: 2, 96: 2, 97: 3, 98: 3, 99: 2, 100: 3, 101: 4, 102: 1, 103: 1, 104: 2}


def _texto() -> str:
    return PLANTILLA.read_text(encoding="utf-8")


def _funcion(texto: str, nombre: str) -> str:
    inicio = re.search(rf"\n  (async )?function {nombre}\(", texto).start() + 1
    return texto[inicio:texto.index("\n  }\n", inicio) + 5]


def _constante(texto: str, nombre: str, fin: str) -> str:
    inicio = texto.index(f"  const {nombre} = ")
    return texto[inicio:texto.index(fin, inicio) + len(fin)]


def _gente(cuenta: dict[int, int], yo: int | None = None, cobran_desde: int | None = None) -> list[dict]:
    """Participantes inventados con la cuenta dada: lugar por aciertos (los empates comparten)."""
    gente, p = [], 0
    for total in sorted(cuenta, reverse=True):
        for _ in range(cuenta[total]):
            gente.append({"p": p, "total": total, "ini": f"P{p}", "yo": p == yo})
            p += 1
    for g in gente:
        g["pos"] = 1 + sum(1 for h in gente if h["total"] > g["total"])
        g["cobra"] = cobran_desde is not None and g["total"] >= cobran_desde
    return gente


def _acomodo(casos: list[tuple[list[dict], float, int]]) -> list[dict]:
    texto = _texto()
    codigo = "\n".join([_constante(texto, "ENVOLTURAS", ";\n"), _constante(texto, "MEDALLA_DE_LUGAR", ";\n"),
                        _funcion(texto, "regalosDeLaGeneral")])
    guion = f"""{codigo}
    console.log(JSON.stringify({json.dumps(casos)}.map(([gente, ancho, entrada]) => {{
      const a = regalosDeLaGeneral(gente, ancho, entrada);
      return {{ alto: a.alto, base: a.base, k: a.k, zona: a.zona, a1: a.a1, premio: a.premio, cajas: a.cajas,
        piezas: a.piezas.map((p) => ({{ total: p.g.total, pos: p.g.pos, yo: p.g.yo, tipo: p.tipo, medalla: p.medalla, x: p.x }})),
        focos: a.focos, numeros: a.numeros }};
    }})));"""
    r = subprocess.run(["node", "-e", guion], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _choques(cajas: list[dict]) -> list[str]:
    malos = []
    for i, a in enumerate(cajas):
        for b in cajas[i + 1:]:
            if a["x0"] < b["x1"] - .01 and b["x0"] < a["x1"] - .01 and a["y0"] < b["y1"] - .01 and b["y0"] < a["y1"] - .01:
                malos.append(f'{a["q"]} × {b["q"]}')
    return malos


@con_node
def test_con_la_general_de_verdad_cada_quien_tiene_su_envoltura():
    [a] = _acomodo([(_gente(REAL, cobran_desde=103), 358, 103)])
    tipos = {}
    for p in a["piezas"]:
        tipos.setdefault(p["tipo"], set()).add(p["total"])
    # Quien cobra va de lujo con su medalla: los dos de 104 en oro (comparten el 1.º) y el de 103 en bronce.
    assert tipos["oro"] == {104} and tipos["bronce"] == {103} and "plata" not in tipos
    # Los demás, por cuartos de la tabla; el último lugar, carbón.
    assert tipos["fino"] == {100, 101, 102}
    assert tipos["sencillo"] == {97, 98, 99}
    assert tipos["carton"] == {93, 95, 96}
    assert tipos["bolsa"] == {86, 89, 90, 92}
    assert tipos["carbon"] == {85}
    # Los focos: prenden los de quien cobra, con su medalla; el de 102 queda tibio y dice "a 1".
    estados = {f["t"]: f["estado"] for f in a["focos"]}
    assert (estados[104], estados[103], estados[102], estados[101]) == ("oro", "bronce", "tibio", "apagado")
    assert a["a1"] is not None
    # La zona de premio empieza entre el 102 y el 103 y llega a la orilla.
    x = {p["total"]: p["x"] for p in a["piezas"]}
    assert x[102] < a["zona"]["x0"] < x[103] and a["zona"]["x1"] == 356
    assert _choques(a["cajas"]) == []


@con_node
def test_nada_se_encima_con_datos_dificiles():
    larga = {90: 1, 95: 9, 100: 2, 101: 1}                      # nueve empatados en una columna
    ancha = {t: 1 + (t % 3) for t in range(70, 101)}           # 31 columnas
    todos = {100: 3, 101: 2}                                    # todos cobran
    casos = [
        (_gente(REAL, cobran_desde=103), 300, 103),            # teléfono angosto
        (_gente(REAL, cobran_desde=103), 720, 103),            # computadora
        (_gente(larga, cobran_desde=100), 358, 100),
        (_gente(ancha, cobran_desde=99), 358, 99),
        (_gente(todos, cobran_desde=100), 358, 100),
        (_gente(REAL, yo=20, cobran_desde=103), 358, 103),     # tú, fuera del premio
    ]
    for (gente, ancho, _), a in zip(casos, _acomodo(casos)):
        assert _choques(a["cajas"]) == [], (ancho, len(gente))
        # Todo cabe en el dibujo: nada se sale por los lados ni por abajo.
        assert all(c["x0"] >= 0 and c["x1"] <= ancho and c["y0"] >= 0 and c["y1"] <= a["alto"] for c in a["cajas"])
        assert len(a["piezas"]) == len(gente)
    # La pila de nueve no se aplasta: la gráfica crece.
    assert _acomodo([(_gente(larga, cobran_desde=100), 358, 100)])[0]["alto"] > _acomodo([(_gente(REAL, cobran_desde=103), 358, 103)])[0]["alto"]


@con_node
def test_tu_regalo_sigue_la_escalera_y_sin_premio_no_hay_carbon_de_mas():
    [a] = _acomodo([(_gente(REAL, yo=20, cobran_desde=103), 358, 103)])
    [tuyo] = [p for p in a["piezas"] if p["yo"]]
    assert tuyo["tipo"] == "carton"   # el lugar 21 de 34 cae en el tercer cuarto
    # Si todos cobran, no hay escalera: todos de lujo, sin carbón y sin "a 1".
    [b] = _acomodo([(_gente({100: 3, 101: 2}, cobran_desde=100), 358, 100)])
    assert {p["tipo"] for p in b["piezas"]} <= {"oro", "plata", "bronce"} and b["a1"] is None


def test_la_general_se_viste_solo_en_navidad():
    texto = _texto()
    campo = _funcion(texto, "pintarCampoGeneral")
    assert 'const regalos = !!fiesta && fiesta.clave === "navidad";' in campo
    assert "dibujoDeRegalos(regalosDeLaGeneral(gente, anchoDibujo, entrada), tuyo)" in campo
    # Escondida no se puede medir: se calcula con la pantalla, y el dibujo siempre se ajusta a su caja.
    assert "pasto.clientWidth || Math.min(640, (document.documentElement.clientWidth || 390) - 32)" in campo
    assert ".campo-gral-pasto.regalos svg{display:block; width:100%; height:auto; overflow:visible}" in texto
    # Si algo falla al dibujar, queda la gráfica de puntos.
    assert 'pasto.classList.remove("regalos");' in campo
    # Fuera de navidad sigue la de puntos de siempre.
    assert '"Cada punto es uno de los " + D.general.length' in campo
    # El reparto va en grupos con su lugar: en navidad son etiquetas de regalo con su medalla.
    assert 'grupo.dataset.medalla = MEDALLA_DE_LUGAR[Math.min(Math.max(g.pos, 1), 3)];' in campo
    assert 'html[data-fiesta="navidad"] .campo-gral-grupo{' in texto and ".campo-gral-lugar{display:none}" in texto
    assert "@media (prefers-reduced-motion:reduce){.rg-prendido,.rg-tibio{animation:none}}" in texto
    # Las iniciales vienen del nombre: se escapan antes de entrar al SVG.
    assert 'const textoSvg = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");' in texto
