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
