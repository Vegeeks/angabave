"""Las fiestas: Acción de Gracias en su semana y navidad hasta año nuevo. Cuándo se viste el portal,
qué cambia y qué no."""
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
from quiniela.render_html import _accion_de_gracias, _fiestas, _tandas

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


def _node(cuerpo: str, fiestas=None):
    texto = _texto()
    codigo = "\n".join([
        _constante(texto, "mismoDia", "\n  };\n"),
        _funcion(texto, "fiestaDe"),
        _constante(texto, "fiestaDeSemana", ";\n"),
        _funcion(texto, "textoDeFiesta"),
        _constante(texto, "PLATOS", ";\n"),
        _funcion(texto, "platoDeFiesta"),
        _constante(texto, "PAVO", "'</svg>';\n"),
        _constante(texto, "ARBOL", "'</svg>';\n"),
        _constante(texto, "HOJA", "\n  };\n"),
        _constante(texto, "COPO", ";\n"),
    ])
    guion = f"const D = {{ fiestas: {json.dumps(fiestas)} }};\n{codigo}\n{cuerpo}"
    # Las fechas se leen con la hora de México, como en los teléfonos de la quiniela.
    r = subprocess.run(["node", "-e", guion], capture_output=True, text=True,
                       env={**os.environ, "TZ": "America/Mexico_City"})
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _semana(numero: int, *inicios: datetime):
    return SimpleNamespace(numero=numero, partidos=[Partido(f"V{i}", f"L{i}", inicio=t) for i, t in enumerate(inicios)])


def _cdmx(*partes) -> int:
    return int(datetime(*partes, tzinfo=ZONA_CDMX).timestamp())


TEMPORADA = [
    _semana(10, datetime(2026, 11, 13, 1, 15, tzinfo=UTC), datetime(2026, 11, 17, 1, 15, tzinfo=UTC)),
    _semana(11, datetime(2026, 11, 20, 1, 15, tzinfo=UTC), datetime(2026, 11, 24, 1, 15, tzinfo=UTC)),
    _semana(12, datetime(2026, 11, 26, 1, 0, tzinfo=UTC),    # miércoles 25, 19:00
            datetime(2026, 11, 26, 18, 0, tzinfo=UTC),       # jueves 26, 12:00
            datetime(2026, 11, 27, 20, 0, tzinfo=UTC),       # viernes 27, 14:00
            datetime(2026, 12, 1, 1, 15, tzinfo=UTC)),       # lunes 30, 19:15
    _semana(13, datetime(2026, 12, 4, 1, 15, tzinfo=UTC), datetime(2026, 12, 6, 18, 0, tzinfo=UTC)),
    _semana(17, datetime(2026, 12, 31, 21, 0, tzinfo=UTC), datetime(2027, 1, 3, 18, 0, tzinfo=UTC)),
    _semana(18, datetime(2027, 1, 9, 21, 0, tzinfo=UTC), datetime(2027, 1, 10, 18, 0, tzinfo=UTC)),
]


def test_accion_de_gracias_es_el_cuarto_jueves_de_noviembre():
    assert _accion_de_gracias(2026) == date(2026, 11, 26)
    assert _accion_de_gracias(2027) == date(2027, 11, 25)
    assert _accion_de_gracias(2029) == date(2029, 11, 22)


def test_las_fiestas_de_la_temporada():
    de_gracias, navidad = _fiestas(TEMPORADA, 2026)
    # Acción de Gracias va primero: en su semana manda ella.
    assert (de_gracias["clave"], de_gracias["semanas"], de_gracias["dia"]) == ("accion-de-gracias", [12], "2026-11-26")
    assert de_gracias["desde"] == _cdmx(2026, 11, 23, 0, 0) and de_gracias["hasta"] == _cdmx(2026, 12, 1, 6, 0)
    # Navidad: del 15 de noviembre a la mañana del 2 de enero, con las semanas que arrancan en ese
    # tramo (la 11, que ya está en curso, sí; la 10 y la 18, no), menos la de Acción de Gracias.
    assert navidad["clave"] == "navidad" and navidad["semanas"] == [11, 13, 17]
    assert navidad["desde"] == _cdmx(2026, 11, 15, 0, 0) and navidad["hasta"] == _cdmx(2027, 1, 2, 6, 0)
    # Sin la semana de Acción de Gracias en el calendario, solo queda navidad.
    assert [f["clave"] for f in _fiestas(TEMPORADA[:2], 2026)] == ["navidad"]


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
def test_cada_dia_con_su_fiesta():
    fiestas = _fiestas(TEMPORADA, 2026)
    momentos = [
        _cdmx(2026, 11, 14, 12, 0),   # antes de todo
        _cdmx(2026, 11, 20, 18, 0),   # hoy: navidad, como pidió Angel
        _cdmx(2026, 11, 23, 0, 0),    # entra Acción de Gracias
        _cdmx(2026, 12, 1, 5, 59),    # todavía Acción de Gracias
        _cdmx(2026, 12, 1, 6, 0),     # regresa navidad
        _cdmx(2027, 1, 2, 5, 59),     # el último rato de navidad
        _cdmx(2027, 1, 2, 6, 0),      # se acabó
    ]
    salida = _node(f"""
    const f = (x) => x ? x.clave : null;
    console.log(JSON.stringify({{
      dia: {json.dumps(momentos)}.map((m) => f(fiestaDe(D.fiestas, m * 1000, null))),
      pedidas: ["navidad", "accion-de-gracias", "1", "otra"].map((p) => f(fiestaDe(D.fiestas, 0, p))),
      sinLista: fiestaDe(null, Date.now(), "1"),
      semanas: [10, 11, 12, 13, 18].map((n) => f(fiestaDeSemana(n))),
    }}));
    """, fiestas)
    assert salida["dia"] == [None, "navidad", "accion-de-gracias", "accion-de-gracias", "navidad", "navidad", None]
    assert salida["pedidas"] == ["navidad", "accion-de-gracias", "accion-de-gracias", None]
    assert salida["sinLista"] is None
    # La boleta va por semana: la 12 es de Acción de Gracias aunque la vea en diciembre.
    assert salida["semanas"] == [None, "navidad", "accion-de-gracias", "navidad", None]


@con_node
def test_lo_que_dice_el_liston():
    fiestas = _fiestas(TEMPORADA, 2026)
    momentos = {
        "ag": [_cdmx(2026, 11, 24, 12, 0), _cdmx(2026, 11, 26, 9, 0)],
        "nav": [_cdmx(2026, 11, 20, 12, 0), _cdmx(2026, 12, 24, 20, 0), _cdmx(2026, 12, 25, 10, 0),
                _cdmx(2026, 12, 26, 10, 0), _cdmx(2026, 12, 31, 23, 0), _cdmx(2027, 1, 1, 13, 0)],
    }
    salida = _node(f"""
    const m = {json.dumps(momentos)};
    console.log(JSON.stringify([m.ag.map((t) => textoDeFiesta(D.fiestas[0], t * 1000)),
      m.nav.map((t) => textoDeFiesta(D.fiestas[1], t * 1000))]));
    """, fiestas)
    assert salida[0] == ["Semana de Acción de Gracias", "Feliz Día de Acción de Gracias"]
    assert salida[1] == ["Felices fiestas", "Feliz Navidad", "Feliz Navidad", "Felices fiestas",
                         "Feliz Año Nuevo", "Feliz Año Nuevo"]


@con_node
def test_semana_12_se_lee_como_menu():
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
    # Y el menú es solo de Acción de Gracias.
    panel = _funcion(_texto(), "panelPartidos")
    assert 'fiesta.clave === "accion-de-gracias" && fiesta.semanas.includes(s.n) ? platoDeFiesta : null' in panel


@con_node
def test_el_pavo_y_el_pino_son_svg_bien_hechos_y_las_formas_son_las_del_css():
    pavo, arbol, hojas, copo = _node("console.log(JSON.stringify([PAVO, ARBOL, HOJA, COPO]));")
    figuras = {}
    for nombre, svg in (("pavo", pavo), ("arbol", arbol)):
        etiquetas = [hijo.tag.split("}")[-1] for hijo in ET.fromstring(svg)]
        figuras[nombre] = (etiquetas.count("ellipse"), etiquetas.count("circle"), etiquetas.count("path"))
    assert figuras == {"pavo": (15, 4, 3), "arbol": (0, 6, 6)}
    texto = _texto()
    assert f"d='{hojas['arce']}'" in texto[texto.index(".arce{--forma:"):][:900]
    assert f"fill-rule='evenodd' d='{hojas['roble']}'" in texto[texto.index(".roble{--forma:"):][:900]
    assert f"d='{copo}'" in texto[texto.index(".copo{--forma:"):][:1200]


def test_las_fiestas_entran_y_se_van_solas():
    texto = _texto()
    arranque = texto[texto.index("let fiestaPuesta = aplicarFiesta();"):][:300]
    assert "setInterval(() => {" in arranque and "repintarSinEstorbar();" in arranque and "60000" in arranque
    aplica = _funcion(texto, "aplicarFiesta")
    # Si cambia de fiesta (navidad → Acción de Gracias → navidad), se quita todo y se pone lo nuevo.
    assert 'puesta && (!f || puesta.dataset.clave !== f.clave)' in aplica
    assert 'document.querySelectorAll(".fiesta-luces").forEach((n) => n.remove());' in aplica
    assert 'if (f.clave === "navidad") cancha.after(lucesDeNavidad());' in aplica
    assert "delete raiz.dataset.fiesta;" in aplica and "return f.clave;" in aplica


def test_todo_vive_detras_y_no_se_anima_para_siempre():
    texto = _texto()
    assert ".fiesta{position:absolute; inset:0; overflow:hidden; pointer-events:none}" in texto
    luces = texto[texto.index("\n.fiesta-luces{"):][:200]
    assert "top:var(--alto-campo)" in luces and "z-index:-1" in luces and "pointer-events:none" in luces
    assert ".estreno .fiesta,.estreno .fiesta-luces{visibility:hidden}" in texto
    assert ("@media (prefers-reduced-motion:reduce){.fiesta .cae{display:none} .foco,.fiesta .destello{animation:none}}"
            in texto)
    assert ('@media (prefers-reduced-motion:reduce){html[data-fiesta="navidad"] .progreso-semana '
            ':is(.gana,.pierde,.juega)::before{animation:none}}' in texto)
    capa = _funcion(texto, "capaDeFiesta")
    assert capa.count("if (!suave)") == 2
    # Las hojas caen tres veces y se van; en navidad la nieve, los focos y las estrellas no paran.
    assert "animation:hoja-cae var(--d) ease-in-out var(--t) 3}" in texto
    assert ".fiesta .cae.nieve{animation-name:copo-cae; animation-iteration-count:infinite}" in texto
    assert "animation:titila 1.2s ease-in-out var(--t) infinite alternate}" in texto
    # Las luces cálidas del estadio son solo de Acción de Gracias.
    assert 'html[data-fiesta="accion-de-gracias"] .cancha .luz{' in texto


def test_hoy_semana_la_boleta_y_el_confeti_se_visten():
    texto = _texto()
    assert "listonDeFiesta(fiesta, textoDeFiesta(fiesta, Date.now()))" in _funcion(texto, "saludo")
    assert ("if (fiesta && fiesta.semanas.includes(n)) fila.appendChild(listonDeFiesta(fiesta, NOMBRE_FIESTA[fiesta.clave], true));"
            in _funcion(texto, "pintarSemana"))
    lienzo = _funcion(texto, "encabezadoEnLienzo")
    assert "const deFiesta = fiestaDelSello ? SELLOS[fiestaDelSello.clave] : null;" in lienzo
    assert '(deFiesta ? deFiesta.anillo : "PICKS OFICIALES") + " · ANGABAVE · "' in lienzo
    assert "imagenDeSvg(deFiesta.figura, 136)" in lienzo and "deFiesta.adornos(ctx, sx, sy, radio)" in lienzo
    sellos = _constante(texto, "SELLOS", "\n  };\n")
    assert '"ACCIÓN DE GRACIAS"' in sellos and '"FELICES FIESTAS"' in sellos
    assert "adornos: hojasEnLienzo" in sellos and "adornos: coposEnLienzo" in sellos
    confeti = _funcion(texto, "lanzarConfeti")
    assert "const paleta = fiesta ? (otono ? OTONO : NAVIDAD) : null;" in confeti


def test_en_navidad_los_aciertos_y_errores_son_foquitos():
    texto = _texto()
    # La tira de tu semana: verde lo que le atinaste, rojo lo que no, parpadea lo que se juega.
    assert 'html[data-fiesta="navidad"] .progreso-semana :is(.ok,.gana){--c:#2BD67B;' in texto
    assert 'html[data-fiesta="navidad"] .progreso-semana :is(.mal,.pierde){--c:#FF3B47;' in texto
    assert 'html[data-fiesta="navidad"] .progreso-semana :is(.gana,.pierde,.juega)::before{animation:titila' in texto
    # La marca de cada fila lleva su tono para volverse foquito.
    assert '"fila-marca " + (palabras.tono === "bien" ? "bien" : "mal")' in _funcion(texto, "filaJuego")
    assert 'html[data-fiesta="navidad"] .juego-fila .fila-marca.bien{--c:#2BD67B;' in texto
    # Y la imagen de "Mi semana" de una semana navideña también es una serie.
    assert 'if ((fiestaDeSemana(s.n) || {}).clave === "navidad") focosEnLienzo(ctx, trazos, MARGEN, ANCHO - MARGEN * 2, TIRA);' in texto
    # Más navidad: zona de anotación roja, gorro de Santa en la A y nieve sobre tu barra.
    for regla in ('html[data-fiesta="navidad"] .cp-zona{fill:#B3121F}', 'html[data-fiesta="navidad"] .logo::before{',
                  'html[data-fiesta="navidad"] .mi-barra-yo::before{'):
        assert regla in texto


def test_python_manda_las_fiestas_al_navegador():
    fuente = (RAIZ / "quiniela" / "render_html.py").read_text(encoding="utf-8")
    assert '"fiestas": _fiestas(semanas, anio),' in fuente
