"""La jugada en vivo (quién trae el balón, la oportunidad y dónde) y el filtro de quién le fue a quién.

La respuesta de ESPN es real: se guardó con Steelers @ Bengals en el primer cuarto
(Bengals con el balón, primera y 10 en la 32 de Pittsburgh).
"""
import copy
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
CLAVE = "Steelers@Bengals"

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


def _codigo() -> str:
    texto = _texto()
    funciones = ("parsearVivo", "ultimaJugada", "situacionDe", "textoSituacion")
    return _constante(texto, "JUGADAS_ESPN") + "\n".join(_funcion(texto, f) for f in funciones)


def _node(cuerpo: str):
    datos = {"vivo": {"equipos": ABREVIATURAS_ESPN, "estados": render_html.ESTADOS}, "siglas": render_html._siglas()}
    guion = f"const D = {json.dumps(datos)};\n{_codigo()}\n{cuerpo}"
    r = subprocess.run(["node", "-e", guion], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _parsear(cargas: list[dict]) -> list:
    """Por carga: {clave: [sit, texto, estado]}, o None si parsearVivo la rechaza."""
    return _node(f"""
    console.log(JSON.stringify({json.dumps(cargas)}.map((c) => {{
      const m = parsearVivo(c);
      if (!m) return null;
      const salida = {{}};
      m.forEach((v, k) => {{ salida[k] = [v.sit, textoSituacion(v.sit), v.e, v.mv, v.ml]; }});
      return salida;
    }})));
    """)


def _carga() -> dict:
    return json.loads(FIJO.read_text(encoding="utf-8"))


def _con_jugada(cambios: dict, *, estado: dict | None = None) -> dict:
    """La respuesta real con la jugada (y, si se pide, el estado) del partido en juego cambiada."""
    carga = copy.deepcopy(_carga())
    for ev in carga["events"]:
        comp = ev["competitions"][0]
        if "situation" in comp:
            comp["situation"].update(cambios)
            if estado:
                comp["status"]["type"].update(estado)
    return carga


@con_node
def test_en_juego_se_sabe_quien_trae_el_balon_y_donde():
    [vivo] = _parsear([_carga()])
    sit, texto, estado, mv, ml = vivo[CLAVE]
    assert sit == {
        "lado": "l", "zr": False, "bajada": 1, "faltan": 10, "en": "PIT 32",
        "serie": {"jugadas": 5, "yardas": 54, "tiempo": "2:38"},
        "ultima": "pase completo de 27 yardas",
        "prob": {"l": 77, "v": 23},
        "tiempos": {"v": 3, "l": 3},
    }
    assert texto == "1.ª y 10 en PIT 32"
    assert estado.startswith("Q1")
    # Los terminados y el de mañana no traen jugada.
    otros = [v for k, v in vivo.items() if k != CLAVE]
    assert len(otros) == 13 and all(v[0] is None and v[1] == "" for v in otros)


@con_node
def test_primera_y_gol_en_zona_roja_y_medio_campo():
    gol = _con_jugada({"down": 1, "distance": 5, "shortDownDistanceText": "1st & Goal",
                       "downDistanceText": "1st & Goal at PIT 5", "possessionText": "PIT 5", "isRedZone": True})
    medio = _con_jugada({"down": 3, "distance": 7, "shortDownDistanceText": "3rd & 7", "possessionText": "50"})
    a, b = (r[CLAVE] for r in _parsear([gol, medio]))
    assert a[1] == "1.ª y gol en PIT 5" and a[0]["zr"] is True
    assert b[1] == "3.ª y 7 en medio campo" and b[0]["zr"] is False


@con_node
def test_en_el_medio_tiempo_no_hay_jugada_pero_si_marcador():
    carga = _con_jugada({}, estado={"name": "STATUS_HALFTIME", "description": "Halftime"})
    [vivo] = _parsear([carga])
    sit, texto, _, mv, ml = vivo[CLAVE]
    assert sit is None and texto == ""
    assert mv is not None and ml is not None


@con_node
def test_lo_que_no_cuadra_no_se_dice():
    sin_dueno = _con_jugada({"possession": "999"})
    sin_bajada = _con_jugada({"down": -1, "distance": 0})
    rara = _con_jugada({"lastPlay": {"type": {"text": "Weird Play"}, "team": {"id": "23"},
                                     "drive": {"description": "5 plays, 54 yards, 2:38"},
                                     "probability": {"homeWinPercentage": 0.4}}, "homeTimeouts": 5})
    basura = _con_jugada({"possessionText": {"x": 1}, "lastPlay": "nada", "down": "uno"})
    a, b, c, d = (r[CLAVE] for r in _parsear([sin_dueno, sin_bajada, rara, basura]))
    assert a[0] is None
    # Sin oportunidad válida se sabe quién trae el balón, pero no se inventa la jugada.
    assert b[0]["lado"] == "l" and "bajada" not in b[0] and b[1] == ""
    # Jugada desconocida, serie del rival, probabilidad incompleta y tiempos imposibles: nada.
    assert c[0]["lado"] == "l" and c[1] == "1.ª y 10 en PIT 32"
    assert not {"ultima", "serie", "prob", "tiempos"} & set(c[0])
    # Y aunque venga basura, el marcador sigue llegando.
    assert d[0] == {"lado": "l", "zr": False, "tiempos": {"v": 3, "l": 3}} and d[3] is not None


@con_node
def test_la_ultima_jugada_se_dice_en_espanol():
    casos = [["Rush", 4], ["Rush", 1], ["Rush", 0], ["Rush", -3], ["Sack", -7], ["Penalty", 5],
             ["Punt", 45], ["Two-minute warning", 0], ["Passing Touchdown", 12], ["Weird Play", 3]]
    salida = _node(f"""
    console.log(JSON.stringify({json.dumps(casos)}.map(([t, y]) => ultimaJugada({{ type: {{ text: t }}, statYardage: y }}))));
    """)
    assert salida == ["acarreo de 4 yardas", "acarreo de 1 yarda", "acarreo sin ganancia", "acarreo, pierde 3 yardas",
                      "captura, pierde 7 yardas", "castigo", "despeje", "aviso de dos minutos", "touchdown por pase", None]
    # Ninguna traducción deja pasar inglés.
    traducciones = re.findall(r'": "([^"]+)"', _constante(_texto(), "JUGADAS_ESPN"))
    assert len(traducciones) >= 22
    assert not [t for t in traducciones if re.search(r"\b(Pass|Rush|Punt|Kick|Goal|Fumble|Sack|Timeout)\b", t)]


def test_la_fila_trae_el_balon_y_la_oportunidad():
    fila = _funcion(_texto(), "filaJuego")
    assert "const sit = p.vivo ? p.sit : null;" in fila
    assert "if (conBalon) nombreEq.appendChild(balon());" in fila
    assert 'crear("div", "situacion")' in fila and '"Zona roja"' in fila
    # El lector de pantalla también lo oye.
    assert '"balón para "' in fila


def test_la_hoja_del_partido_sigue_la_jugada_mientras_esta_abierta():
    texto = _texto()
    hoja = _funcion(texto, "abrirPartido")
    assert "pintarArribaHoja(arriba, p);" in hoja
    assert "hojaPartido = s && !p.cerrado ?" in hoja
    detalle = _funcion(texto, "jugadaEnHoja")
    for renglon in ('"Serie"', '"Última jugada"', '"Tiempos fuera"', '"Según ESPN"'):
        assert renglon in detalle
    consulta = _funcion(texto, "consultarVivo")
    assert "refrescarHojaPartido();" in consulta
    assert "hojaPartido.nodo.isConnected" in _funcion(texto, "refrescarHojaPartido")
    # La hoja abierta se repinta en su lugar y sin estorbar: .vivo-hoja no agrega caja.
    assert ".vivo-hoja{display:contents}" in texto


def test_con_partido_en_juego_se_pregunta_mas_seguido():
    assert render_html.SEGUNDOS_VIVO == 20
    consulta = _funcion(_texto(), "consultarVivo")
    assert "!juegosEnVivo(s).length && ultimaConsulta && Date.now() - ultimaConsulta.getTime() < 55000" in consulta
    # La jugada solo llega con el partido corriendo y se va con él.
    assert "sit: vivo.enJuego ? vivo.sit || null : null," in _funcion(_texto(), "efectivo")


def test_quien_le_fue_a_quien_se_filtra_por_equipo():
    texto = _texto()
    tarjeta = _funcion(texto, "tarjetaSplit")
    assert 'filtro.setAttribute("role", "group");' in tarjeta
    assert '[["v", visita.length], ["", visita.length + casa.length], ["l", casa.length]]' in tarjeta
    assert 'b.setAttribute("aria-pressed", String(suyo === lado))' in tarjeta
    # Un segundo toque en el mismo equipo regresa a todos.
    assert 'aplicar(lado && filtroReparto.get(clave) === lado ? "" : lado)' in tarjeta
    assert 'aplicar(filtroReparto.get(clave) || "");' in tarjeta
    assert "const filtroReparto = new Map();" in texto
    assert '.split[data-filtro="v"] .gente.lado-l,.split[data-filtro="l"] .gente.lado-v{display:none}' in texto
    # Cada renglón de nombres empieza con la sigla de su equipo.
    assert 'fila.appendChild(sigla(lado === "v" ? p.v : p.l));' in tarjeta
    assert "cuenta-lado" not in texto
    # En la hoja, filtrar no la encoge: el botón se queda debajo del dedo.
    assert 'hoja.style.minHeight = Math.round(hoja.getBoundingClientRect().height) + "px"' in tarjeta
    # Y en la hoja la tarjeta no repite el partido ni el marcador de arriba.
    hoja = _funcion(texto, "abrirPartido")
    assert 'reparto.querySelector(".cab .vs").textContent = "Quién le fue a quién";' in hoja
    assert 'reparto.querySelector(".cab .mr").remove();' in hoja
