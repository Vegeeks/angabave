"""La semana de Acción de Gracias: cuándo se viste de otoño el portal, qué cambia y qué no."""
import json
import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from quiniela.espn import ZONA_CDMX, Partido
from quiniela.render_html import _accion_de_gracias, _fiesta, _tandas

RAIZ = Path(__file__).resolve().parent.parent
PLANTILLA = RAIZ / "quiniela" / "plantillas" / "index.html.j2"
UTC = timezone.utc

con_node = pytest.mark.skipif(shutil.which("node") is None, reason="hace falta node")


def _texto() -> str:
    return PLANTILLA.read_text(encoding="utf-8")


def _funcion(texto: str, nombre: str) -> str:
    inicio = re.search(rf"\n  (async )?function {nombre}\(", texto).start() + 1
    fin = texto.index("\n  }\n", inicio) + 5
    return texto[inicio:fin]


def _constante(texto: str, nombre: str, fin: str) -> str:
    inicio = texto.index(f"  const {nombre} = ")
    return texto[inicio:texto.index(fin, inicio) + len(fin)]


def _node(cuerpo: str):
    texto = _texto()
    codigo = "\n".join([
        _funcion(texto, "fiestaVigente"),
        _constante(texto, "PLATOS", ";\n"),
        _funcion(texto, "platoDeFiesta"),
        _constante(texto, "PAVO", "'</svg>';\n"),
        _constante(texto, "HOJA", "\n  };\n"),
    ])
    # Los partidos se leen con la hora de México, como en los teléfonos de la quiniela.
    r = subprocess.run(["node", "-e", f"{codigo}\n{cuerpo}"], capture_output=True, text=True,
                       env={**os.environ, "TZ": "America/Mexico_City"})
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _semana(numero: int, *inicios: datetime):
    return SimpleNamespace(numero=numero, partidos=[Partido(f"V{i}", f"L{i}", inicio=t) for i, t in enumerate(inicios)])


def test_accion_de_gracias_es_el_cuarto_jueves_de_noviembre():
    assert _accion_de_gracias(2026) == date(2026, 11, 26)
    assert _accion_de_gracias(2027) == date(2027, 11, 25)
    assert _accion_de_gracias(2029) == date(2029, 11, 22)


def test_la_fiesta_va_del_lunes_a_la_manana_siguiente_al_ultimo_partido():
    s11 = _semana(11, datetime(2026, 11, 20, 1, 15, tzinfo=UTC), datetime(2026, 11, 24, 1, 15, tzinfo=UTC))
    s12 = _semana(
        12,
        datetime(2026, 11, 26, 1, 0, tzinfo=UTC),    # miércoles 25, 19:00
        datetime(2026, 11, 26, 18, 0, tzinfo=UTC),   # jueves 26, 12:00
        datetime(2026, 11, 27, 20, 0, tzinfo=UTC),   # viernes 27, 14:00
        datetime(2026, 12, 1, 1, 15, tzinfo=UTC),    # lunes 30, 19:15
    )
    f = _fiesta([s11, s12], 2026)
    assert (f["clave"], f["semana"], f["dia"]) == ("accion-de-gracias", 12, "2026-11-26")
    assert datetime.fromtimestamp(f["desde"], ZONA_CDMX) == datetime(2026, 11, 23, 0, 0, tzinfo=ZONA_CDMX)
    assert datetime.fromtimestamp(f["hasta"], ZONA_CDMX) == datetime(2026, 12, 1, 6, 0, tzinfo=ZONA_CDMX)
    # Sin esa semana en el calendario, no hay fiesta.
    assert _fiesta([s11], 2026) is None


def test_la_semana_12_cierra_junta_el_martes():
    """Angel lo confirmó el 20 nov: los cinco de antes del domingo cierran juntos, como en la semana 1."""
    tandas = _tandas([
        Partido("Packers", "Rams", inicio=datetime(2026, 11, 26, 1, 0, tzinfo=UTC)),
        Partido("Bears", "Lions", inicio=datetime(2026, 11, 26, 18, 0, tzinfo=UTC)),
        Partido("Eagles", "Cowboys", inicio=datetime(2026, 11, 26, 21, 30, tzinfo=UTC)),
        Partido("Chiefs", "Bills", inicio=datetime(2026, 11, 27, 1, 20, tzinfo=UTC)),
        Partido("Broncos", "Steelers", inicio=datetime(2026, 11, 27, 20, 0, tzinfo=UTC)),
        Partido("Saints", "Bengals", inicio=datetime(2026, 11, 29, 18, 0, tzinfo=UTC)),
    ])
    assert [len(t["claves"]) for t in tandas] == [5, 1]
    assert tandas[0]["cierre_texto"] == "martes 24 de nov a las 23:59"


@con_node
def test_la_fiesta_solo_vale_dentro_de_su_ventana():
    salida = _node("""
    const f = { desde: 100, hasta: 200 };
    console.log(JSON.stringify([fiestaVigente(f, 99999, false), fiestaVigente(f, 100000, false),
      fiestaVigente(f, 199999, false), fiestaVigente(f, 200000, false), fiestaVigente(f, 0, true),
      fiestaVigente(null, 150000, true)]));
    """)
    dentro = {"desde": 100, "hasta": 200}
    # A la fuerza (?fiesta=1) se ve antes, pero solo si el calendario ya la trae.
    assert salida == [None, dentro, dentro, None, dentro, None]


@con_node
def test_semana_se_lee_como_menu():
    horas = [
        datetime(2026, 11, 26, 1, 0, tzinfo=UTC),    # miércoles 25, 19:00
        datetime(2026, 11, 26, 18, 0, tzinfo=UTC),   # jueves 26, 12:00
        datetime(2026, 11, 27, 1, 20, tzinfo=UTC),   # jueves 26, 19:20: en UTC ya es viernes
        datetime(2026, 11, 27, 20, 0, tzinfo=UTC),   # viernes 27, 14:00
        datetime(2026, 11, 29, 18, 0, tzinfo=UTC),   # domingo 29, 12:00
        datetime(2026, 12, 1, 1, 15, tzinfo=UTC),    # lunes 30, 19:15
    ]
    tiempos = [int(h.timestamp()) for h in horas] + [0]
    salida = _node(f"console.log(JSON.stringify({json.dumps(tiempos)}.map((t) => platoDeFiesta({{ t }}))));")
    assert salida == ["Entrada · ", "Plato fuerte · ", "Plato fuerte · ", "Postre · ",
                      "Recalentado · ", "Recalentado · ", ""]


@con_node
def test_el_pavo_es_un_svg_bien_hecho_y_las_hojas_son_las_del_css():
    pavo, hojas = _node("console.log(JSON.stringify([PAVO, HOJA]));")
    arbol = ET.fromstring(pavo)
    etiquetas = [hijo.tag.split("}")[-1] for hijo in arbol]
    assert (etiquetas.count("ellipse"), etiquetas.count("circle"), etiquetas.count("path")) == (15, 4, 3)
    texto = _texto()
    assert f"d='{hojas['arce']}'" in texto[texto.index(".arce{--forma:"):][:900]
    assert f"fill-rule='evenodd' d='{hojas['roble']}'" in texto[texto.index(".roble{--forma:"):][:900]


def test_la_fiesta_entra_y_se_va_sola():
    texto = _texto()
    arranque = texto[texto.index("let hayFiesta = aplicarFiesta();"):][:300]
    assert "setInterval(() => {" in arranque and "repintarSinEstorbar();" in arranque and "60000" in arranque
    aplica = _funcion(texto, "aplicarFiesta")
    assert "delete raiz.dataset.fiesta;" in aplica and "capa.remove();" in aplica
    # Las hojas viven detrás de todo, no estorban la llegada y respetan el movimiento reducido.
    assert ".fiesta{position:absolute; inset:0; overflow:hidden; pointer-events:none}" in texto
    assert ".estreno .fiesta{visibility:hidden}" in texto
    assert "@media (prefers-reduced-motion:reduce){.fiesta .cae{display:none}}" in texto
    assert "if (!suave) HOJAS_QUE_CAEN.forEach(" in _funcion(texto, "capaDeFiesta")
    # Caen tres veces y se van: nada se anima para siempre, y al terminar cada hoja regresa a su
    # salida, arriba y fuera del recorte, sin quedarse con su capa.
    assert "animation:hoja-cae var(--d) ease-in-out var(--t) 3}" in texto


def test_hoy_semana_la_imagen_y_el_confeti_se_visten():
    texto = _texto()
    saludo = _funcion(texto, "saludo")
    assert '"Feliz Día de Acción de Gracias" : "Semana de Acción de Gracias"' in saludo
    assert 'listonDeFiesta("Acción de Gracias", true)' in _funcion(texto, "pintarSemana")
    panel = _funcion(texto, "panelPartidos")
    assert "const plato = fiesta && s.n === fiesta.semana ? platoDeFiesta : null;" in panel
    assert '(plato ? plato(juego.p) : "") + (juego.p.grupo || "Hora por definir")' in panel
    lienzo = _funcion(texto, "encabezadoEnLienzo")
    assert '"ACCIÓN DE GRACIAS · ANGABAVE · "' in lienzo and "hojasEnLienzo(ctx, sx, sy, radio)" in lienzo
    assert "imagenDeSvg(PAVO, 136)" in lienzo
    # La imagen y el confeti son de la semana, no de la fecha: la boleta de esa semana es conmemorativa.
    assert "const deFiesta = semana !== null && !!D.fiesta && semana === D.fiesta.semana;" in lienzo
    assert "otono ? OTONO[i % OTONO.length]" in _funcion(texto, "lanzarConfeti")


def test_python_manda_la_fiesta_al_navegador():
    fuente = (RAIZ / "quiniela" / "render_html.py").read_text(encoding="utf-8")
    assert '"fiesta": _fiesta(semanas, anio),' in fuente
