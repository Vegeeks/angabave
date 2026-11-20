"""El gol de campo de la entrada y las frases de Hoy en día de picks: funciones puras, probadas en node."""
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


def _correr(funciones: tuple[str, ...], llamada: str, casos: list):
    texto = PLANTILLA.read_text(encoding="utf-8")
    codigo = "\n".join(_funcion(texto, f) for f in funciones)
    guion = f"""
    const DIAS_SEMANA = ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"];
    const mismoDia = (a, b) => {{
      const x = new Date(a), y = new Date(b);
      return x.getFullYear() === y.getFullYear() && x.getMonth() === y.getMonth() && x.getDate() === y.getDate();
    }};
    {codigo}
    const casos = {json.dumps(casos)};
    console.log(JSON.stringify(casos.map((c) => {llamada})));
    """
    r = subprocess.run(["node", "-e", guion], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)



def test_el_boton_de_hoy_dice_fg():
    saludo = _funcion(PLANTILLA.read_text(encoding="utf-8"), "saludo")
    assert "<span>FG</span>" in saludo and "<span>Gol</span>" not in saludo
    # El lector de pantalla oye el nombre completo, no las dos letras.
    assert 'gol.setAttribute("aria-label", "Ver el gol de campo");' in saludo


BASE = {"nombre": "Ana", "total": 94, "visto": None, "fecha": "2026-11-14", "ultimoDia": None, "enVivo": False, "reducido": False}


def _gol(**cambios):
    return {**BASE, **cambios}


def test_el_gol_sube_por_lo_que_sumaste_o_por_tres():
    casos = [_gol(visto=91), _gol(visto=93), _gol(visto=86), _gol(visto=85), _gol(visto=94), _gol(visto=None), _gol(visto=96)]
    salida = _correr(("decidirGol",), "decidirGol(c)", casos)
    assert [s["sube"] for s in salida] == [3, 1, 8, 3, 3, 3, 3]
    assert salida[0] == {"sube": 3, "desde": 91, "hasta": 94}
    assert salida[1] == {"sube": 1, "desde": 93, "hasta": 94}
    assert salida[4]["desde"] == 91 and salida[4]["hasta"] == 94


def test_el_gol_solo_se_juega_cuando_todo_se_cumple():
    casos = [
        _gol(nombre=None),                    # sin nombre elegido
        _gol(total=2), _gol(total=0),         # menos de 3 aciertos
        _gol(enVivo=True),                    # hay partidos en vivo
        _gol(reducido=True),                  # movimiento reducido
        _gol(ultimoDia="2026-11-14"),         # ya hubo uno hoy
        _gol(ultimoDia="2026-11-13"),         # el de ayer no cuenta
        _gol(total=3, visto=None),
    ]
    salida = _correr(("decidirGol",), "decidirGol(c)", casos)
    assert salida[:6] == [None] * 6
    assert salida[6] == {"sube": 3, "desde": 91, "hasta": 94}
    assert salida[7] == {"sube": 3, "desde": 0, "hasta": 3}


def test_el_titular_dice_cuando_cierran_los_picks():
    # Sábado 14 de noviembre de 2026, 12:00 hora local.
    ahora = int(__import__("datetime").datetime(2026, 11, 14, 12, 0).timestamp() * 1000)
    dia = 864e5
    casos = [{"cierre": ahora + 3600e3 * 11, "ahora": ahora}, {"cierre": ahora + dia, "ahora": ahora},
             {"cierre": ahora + 3 * dia, "ahora": ahora}]
    salida = _correr(("tituloDeCierre",), "tituloDeCierre(c.cierre, c.ahora)", casos)
    assert salida == [["Hoy cierran", "los picks"], ["Cierran", "mañana"], ["Cierran el", "martes"]]


def test_el_estado_de_tus_picks_dice_lo_que_sigue():
    base = {"total": 13, "armados": 13, "correo": "picks@ejemplo.mx", "imagen": None, "registrados": 0, "faltanEntregar": False}
    casos = [
        {**base},
        {**base, "armados": 5},
        {**base, "armados": 0},
        {**base, "imagen": "sáb 14, 18:43"},
        {**base, "registrados": 13},
        {**base, "registrados": 1},
        {**base, "registrados": 1, "faltanEntregar": True},
    ]
    salida = _correr(("estadoDeMisPicks",), "estadoDeMisPicks(c)", casos)
    assert salida == [
        "Llevas 13 de 13 en tu borrador; falta generar la imagen.",
        "Llevas 5 de 13 en tu borrador.",
        "Te faltan 13 picks por armar.",
        "Ya generaste tu imagen el sáb 14, 18:43: mándala a picks@ejemplo.mx.",
        "Tus 13 picks ya quedaron registrados ✓.",
        "Tu pick ya quedó registrado ✓.",
        "Llevas 13 de 13 en tu borrador; falta generar la imagen.",
    ]


def test_tu_lugar_usa_la_distancia_de_la_barra():
    casos = [["Le llevas 1 a Marco", 1], ["Le llevas 3 al 2.º", 1], ["A 2 de Marco", 6], ["A 1 del 5.º", 6],
             ["Empatas en la punta", 1], ["Temporada", 4]]
    salida = _correr(("lugarEnLaGeneral",), "lugarEnLaGeneral(c[0], c[1])", casos)
    assert salida == [
        "Vas 1.º en la general, uno arriba de Marco.",
        "Vas 1.º en la general, 3 arriba del 2.º.",
        "Vas 6.º en la general, a 2 de Marco.",
        "Vas 6.º en la general, a 1 del 5.º.",
        "Vas 1.º en la general, empatado en la punta.",
        None,
    ]


# --- tu avance en la semana ---------------------------------------------------

NOMBRES = ["Ana", "Beto", "Caro", "Dani", "Eli"]


def _tabla(*aciertos):
    return [{"p": i, "pos": 1, "f": f, "e": 0} for i, f in enumerate(aciertos)]


def _semana(aciertos, oficial=False, ganadores=None, cerrados=None):
    return {"tabla": _tabla(*aciertos), "oficial": oficial, "ganadores": ganadores or [], "cerrados": cerrados if cerrados is not None else max(aciertos, default=0), "total": 14}


def _avance(casos):
    entradas = [{"s": s, "yo": yo} for s, yo in casos]
    return _correr(("avanceDeSemana",), f"avanceDeSemana(c.s, c.yo, (i) => {json.dumps(NOMBRES)}[i])", entradas)


def test_semana_oficial_con_un_ganador():
    s = _semana([12, 9, 6, 12 - 1], oficial=True, ganadores=[0])
    gana, otro, ajeno = _avance([(s, 0), (s, 1), (s, None)])
    assert gana["p"] == 1 and gana["yarda"] == 100 and gana["anota"] and gana["ganaste"]
    assert gana["texto"] == "Ganaste: anotaste touchdown"
    assert otro["yarda"] == 75 and not otro["anota"] and otro["texto"] == "Vas en la yarda 75 · Ana anotó"
    assert ajeno["texto"] == "Ana anotó" and ajeno["anota"] and ajeno["yarda"] == 100


def test_semana_oficial_con_empate_en_la_punta():
    s = _semana([12, 12, 12, 8], oficial=True, ganadores=[0, 1, 2])
    gana, otro, ajeno = _avance([(s, 1), (s, 3), (s, None)])
    assert gana["texto"] == "Ganaste: anotaste touchdown" and gana["yarda"] == 100
    assert otro["texto"] == "Vas en la yarda 67 · Anotaron 3"
    assert ajeno["texto"] == "Anotaron 3"


def test_semana_en_curso_nadie_anota_y_la_punta_es_primera_y_gol():
    s = _semana([8, 6, 4, 0], cerrados=8)
    lider, otro, cero, ajeno = _avance([(s, 0), (s, 1), (s, 3), (s, None)])
    assert lider["texto"] == "Vas en la punta: primera y gol" and lider["p"] == 0.99 and not lider["anota"]
    assert otro["yarda"] == 75 and otro["texto"] == "Vas en la yarda 75 · a 2 aciertos de la punta"
    assert cero["yarda"] == 0 and cero["texto"] == "Vas en la yarda 0 · a 8 aciertos de la punta"
    assert ajeno["texto"] == "Ana va en primera y gol" and ajeno["yarda"] == 99


def test_semana_en_curso_con_empate_en_la_punta():
    s = _semana([5, 5, 5, 4], cerrados=6)
    lider, otro, ajeno = _avance([(s, 2), (s, 3), (s, None)])
    assert lider["texto"] == "Vas en la punta: primera y gol"
    assert otro["texto"] == "Vas en la yarda 80 · a 1 acierto de la punta"
    assert ajeno["texto"] == "Van 3 en primera y gol"


def test_sin_partidos_jugados_todos_en_la_yarda_cero():
    s0 = _semana([0, 0, 0], cerrados=0)
    s1 = _semana([0, 0, 0], cerrados=3)
    for av in _avance([(s0, 0), (s1, 1), (s1, None)]):
        assert av["hay"] and av["sinJuego"] and av["p"] == 0 and av["yarda"] == 0 and not av["anota"]
    assert _avance([({"tabla": [], "cerrados": 0, "oficial": False, "ganadores": []}, 0)])[0]["hay"] is False


def test_sin_nombre_solo_se_ve_al_lider_y_sin_ganador_oficial_nadie_pasa_de_099():
    en_curso = _semana([9, 3, 9, 7], cerrados=9)
    oficial = _semana([9, 3, 9, 8], oficial=True, ganadores=[0, 2])
    salida = _avance([(en_curso, yo) for yo in (None, 0, 1, 2, 3, 4)] + [(oficial, yo) for yo in (None, 0, 1, 2, 3, 4)])
    for av in salida[:6]:
        assert av["p"] <= 0.99 and av["yarda"] <= 99 and not av["anota"] and not av["ganaste"]
    assert salida[0]["texto"] == "Van 2 en primera y gol"
    # Un participante que ni aparece en la tabla se queda en la yarda 0.
    assert salida[5]["yarda"] == 0
    # En una semana oficial solo los ganadores llegan a 100.
    assert [av["yarda"] for av in salida[6:]] == [100, 100, 33, 100, 89, 0]
    assert salida[10]["p"] < 1
