"""Pruebas de las dos salidas: la página y la imagen."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from quiniela.espn import ZONA_CDMX, Partido, guardar_cache
from quiniela.picks import leer_picks
from quiniela.render_html import SemanaRender, generar_html
from quiniela.render_png import ANCHO, generar_png
from quiniela.scoring import panorama, tabla_general, tabla_semana

from .conftest import ENFRENTAMIENTOS_S2, crear_excel
from .test_scoring import cerrado, en_curso, sin_empezar

MOMENTO = datetime(2026, 9, 20, 14, 32, tzinfo=ZONA_CDMX)


@pytest.fixture
def armado(tmp_path: Path):
    """Una semana en vivo, una general y una semana siguiente sin picks."""
    dir_cache = tmp_path / "resultados"
    ruta = crear_excel(tmp_path / "Semana_02.xlsx")
    partidos, picks = leer_picks(ruta)
    resultados = [
        cerrado("Lions", "Bills", "Bills"),
        en_curso("Panthers", "Falcons", "Panthers"),
        *[sin_empezar(v, l) for v, l in ENFRENTAMIENTOS_S2[2:]],
    ]
    guardar_cache(2, resultados, dir_cache)
    tabla = tabla_semana(partidos, picks, resultados)
    firmes = dict(zip(tabla["participante"], tabla["firme"]))
    pendientes = [p for p in resultados if not p.finalizado]

    semana2 = SemanaRender(2, resultados, picks, tabla, panorama(pendientes, picks, firmes))
    # Con horarios reales: es lo que necesita el generador de picks para saber
    # cuándo cierra cada tanda.
    jueves = datetime(2026, 9, 25, 0, 15, tzinfo=timezone.utc)
    domingo = datetime(2026, 9, 27, 17, 0, tzinfo=timezone.utc)
    semana3 = SemanaRender(3, [
        Partido("Bears", "Vikings", 0, 0, None, False, "Scheduled", jueves),
        Partido("Jets", "Titans", 0, 0, None, False, "Scheduled", domingo),
    ])
    general = tabla_general([ruta], dir_cache=dir_cache, ruta_overrides=tmp_path / "no.json")
    return [semana2, semana3], general


def render(armado, tmp_path: Path) -> str:
    semanas, general = armado
    ruta = generar_html(
        anio=2026,
        semanas=semanas,
        tabla_acumulada=general,
        ruta_salida=tmp_path / "index.html",
        momento=MOMENTO,
    )
    return ruta.read_text(encoding="utf-8")


def datos_embebidos(html: str) -> dict:
    crudo = re.search(r'<script type="application/json" id="datos">(.*?)</script>', html, re.S)
    return json.loads(crudo.group(1).replace("\\u003c", "<"))


def test_la_pagina_no_carga_codigo_de_afuera(armado, tmp_path: Path):
    """CSS y JavaScript van embebidos: sin CDN, sin hojas ni scripts externos."""
    html = render(armado, tmp_path)
    assert "<style>" in html
    assert "@import" not in html
    assert not re.search(r"<script[^>]+src=", html, re.I)
    assert not re.search(r'<link[^>]+rel="stylesheet"', html, re.I)


def _externas(html: str) -> set[str]:
    """Las direcciones que la página pide al abrirse. Las de la vista previa las lee
    el chat donde se comparte el enlace; el navegador no pide nada a ninguna."""
    sin_vista_previa = re.sub(r'<meta property="og:[^>]*>', "", html)
    externas = set(re.findall(r"https?://[^\s\"'<>]+", sin_vista_previa))
    # El espacio de nombres de SVG es un identificador, no una petición de red.
    externas.discard("http://www.w3.org/2000/svg")
    return externas


def test_la_unica_direccion_externa_es_la_de_los_marcadores(armado, tmp_path: Path):
    """El resto de los enlaces son archivos propios (iconos, manifiesto)."""
    html = render(armado, tmp_path)
    assert _externas(html) == {"https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"}
    for propio in ('href="manifest.webmanifest"', 'href="icono-180.png"'):
        assert propio in html


def test_el_encabezado_trae_la_hora_de_cdmx(armado, tmp_path: Path):
    html = render(armado, tmp_path)
    assert "20 sep 2026, 14:32" in html
    assert "Ciudad de México" in html
    assert datos_embebidos(html)["actualizado"] == "20 sep 2026, 14:32"


def test_lleva_el_credito_del_desarrollador_y_ningun_otro(armado, tmp_path: Path):
    html = render(armado, tmp_path)
    assert "Desarrollado por Angel Barrera" in html
    assert 'name="author" content="Angel Barrera"' in html
    for rastro in ("Claude", "Anthropic", "inteligencia artificial", "GPT", "automáticamente"):
        assert rastro.lower() not in html.lower()


def test_la_general_se_escribe_en_el_html_aunque_no_corra_el_script(armado, tmp_path: Path):
    """El podio y la tabla general viven en el HTML, no solo en el JSON."""
    html = render(armado, tmp_path)
    cuerpo = html[: html.index('<script type="application/json"')]
    assert "Ismael Reyna" in cuerpo
    assert "TABLA GENERAL" in cuerpo.upper()


def test_el_json_lleva_toda_la_temporada(armado, tmp_path: Path):
    datos = datos_embebidos(render(armado, tmp_path))
    assert [s["n"] for s in datos["semanas"]] == [2, 3]
    assert datos["activa"] == 2
    assert len(datos["participantes"]) == 4
    # La matriz de picks permite reconstruir quién le fue a quién.
    semana2 = datos["semanas"][0]
    assert len(semana2["picks"]) == len(semana2["jugadores"]) == 4
    assert all(len(fila) == 16 for fila in semana2["picks"])
    assert set(semana2["picks"][0]) <= {0, 1}


def test_el_premio_semanal_viaja_para_cada_numero_de_ganadores(armado, tmp_path: Path):
    """El navegador no divide dinero: lee lo que cobra cada ganador según cuántos ganen."""
    from quiniela.scoring import premio_semanal
    from quiniela.render_html import _pesos

    datos = datos_embebidos(render(armado, tmp_path))
    por = datos["premios"]["semanal_por_ganadores"]
    assert list(por) == [str(n) for n in range(1, len(datos["participantes"]) + 1)]
    assert all(por[str(n)] == _pesos(premio_semanal(n)) for n in range(1, len(datos["participantes"]) + 1))
    assert por["1"] == datos["premios"]["semanal"]


def test_la_semana_sin_picks_se_marca_como_pendiente(armado, tmp_path: Path):
    html = render(armado, tmp_path)
    datos = datos_embebidos(html)
    semana3 = datos["semanas"][1]
    assert semana3["estado"] == "pendiente"
    assert semana3["jugadores"] == []
    assert len(semana3["partidos"]) == 2
    assert "Picks por cargar" in html            # así lo dice la línea de estado


def test_las_semanas_jugadas_quedan_navegables(armado, tmp_path: Path):
    """Las semanas se eligen dentro de "Semana", con su propio selector."""
    html = render(armado, tmp_path)
    assert 'data-vista="semana"' in html and 'data-vista="general"' in html
    assert "function selectorDeSemanas" in html
    assert [s["n"] for s in datos_embebidos(html)["semanas"]] == [2, 3]
    assert '"#s" + vista' in html                  # y cada una tiene su dirección


def test_los_estados_que_se_muestran_salen_en_espanol(armado, tmp_path: Path):
    """Ni los que calcula Python ni los que traerá el navegador van en inglés."""
    datos = datos_embebidos(render(armado, tmp_path))
    mostrados = {p["e"] for s in datos["semanas"] for p in s["partidos"]}
    for ingles in ("In Progress", "Scheduled", "End of Period", "Halftime"):
        assert ingles not in mostrados

    # El navegador traduce con este diccionario antes de pintar nada.
    traducciones = datos["vivo"]["estados"]
    assert traducciones["In Progress"] == "En curso"
    assert traducciones["Halftime"] == "Medio tiempo"
    for ingles in ("In Progress", "Scheduled", "End of Period", "Halftime", "Final/OT"):
        assert ingles in traducciones


def test_el_proyectado_no_se_publica(armado, tmp_path: Path):
    html = render(armado, tmp_path)
    assert "Proy" not in html
    assert "proyectado" not in html.lower()


def test_los_escenarios_viajan_con_la_pagina(armado, tmp_path: Path):
    datos = datos_embebidos(render(armado, tmp_path))
    semana2 = datos["semanas"][0]
    assert semana2["combinaciones"] == 2**15
    assert semana2["panorama"]
    for solo, empata, requiere in semana2["panorama"].values():
        assert solo + empata > 0
        # Cada requisito es [partido, equipo que tiene que ganar].
        assert all(len(par) == 2 for par in requiere)


def test_el_png_mide_1080_de_ancho(armado, tmp_path: Path):
    _, general = armado
    ruta = generar_png(
        tabla_acumulada=general,
        semana=2,
        anio=2026,
        cerrados=1,
        total_partidos=16,
        ruta_salida=tmp_path / "tabla.png",
        momento=MOMENTO,
    )
    with Image.open(ruta) as imagen:
        assert imagen.width == ANCHO
        assert imagen.height > 300


def test_el_png_se_parte_en_dos_columnas_con_muchos_participantes(tmp_path: Path):
    """Con 34 personas la imagen tiene que quedar casi cuadrada para WhatsApp."""
    dir_cache = tmp_path / "resultados"
    picks = {
        f"Participante {indice:02d}": [local for _, local in ENFRENTAMIENTOS_S2]
        for indice in range(34)
    }
    ruta_excel = crear_excel(tmp_path / "Semana_02.xlsx", picks=picks)
    guardar_cache(2, [cerrado(v, l, l) for v, l in ENFRENTAMIENTOS_S2], dir_cache)
    general = tabla_general([ruta_excel], dir_cache=dir_cache, ruta_overrides=tmp_path / "no.json")

    ruta = generar_png(
        tabla_acumulada=general,
        semana=2,
        anio=2026,
        cerrados=16,
        total_partidos=16,
        ruta_salida=tmp_path / "tabla.png",
        momento=MOMENTO,
    )
    with Image.open(ruta) as imagen:
        assert imagen.width == ANCHO
        assert imagen.height < ANCHO * 1.5  # una sola columna se iría al doble


def test_no_se_reparte_la_bolsa_final_antes_de_tiempo(armado, tmp_path: Path):
    """La bolsa final es del final: sin temporada cerrada, nadie aparece con monto."""
    datos = datos_embebidos(render(armado, tmp_path))
    assert datos["premios"]["temporada_cerrada"] is False
    assert datos["premios"]["reparto"] == []
    # Las reglas sí se publican: cuánto y a qué porcentaje.
    assert [r["monto"] for r in datos["premios"]["reglas"]] == ["$17,640", "$5,040", "$2,520"]


def test_sin_ganador_semanal_hasta_tener_partidos_suficientes(armado, tmp_path: Path):
    datos = datos_embebidos(render(armado, tmp_path))
    semana2 = datos["semanas"][0]
    assert semana2["cerrados"] == 1
    assert semana2["proyectable"] is False
    assert semana2["ganadores"] == []
    assert "premio" not in semana2


def test_el_ganador_aparece_al_cruzar_el_umbral(tmp_path: Path):
    from quiniela.render_html import UMBRAL_SEMANA
    from quiniela.scoring import tabla_semana

    dir_cache = tmp_path / "resultados"
    ruta = crear_excel(tmp_path / "Semana_02.xlsx")
    partidos, picks = leer_picks(ruta)
    resultados = [cerrado(v, l, l) for v, l in ENFRENTAMIENTOS_S2[:UMBRAL_SEMANA]] + [
        sin_empezar(v, l) for v, l in ENFRENTAMIENTOS_S2[UMBRAL_SEMANA:]
    ]
    guardar_cache(2, resultados, dir_cache)
    tabla = tabla_semana(partidos, picks, resultados)
    semana = SemanaRender(2, resultados, picks, tabla)
    general = tabla_general([ruta], dir_cache=dir_cache, ruta_overrides=tmp_path / "no.json")

    html = generar_html(
        anio=2026, semanas=[semana], tabla_acumulada=general,
        ruta_salida=tmp_path / "index.html", momento=MOMENTO,
    ).read_text(encoding="utf-8")
    bloque = datos_embebidos(html)["semanas"][0]
    assert bloque["proyectable"] is True
    assert bloque["ganadores"]
    assert bloque["premio_total"] == "$5,200"


def test_el_modo_jugador_viaja_en_la_pagina(armado, tmp_path: Path):
    html = render(armado, tmp_path)
    assert 'id="quien-soy"' in html          # selector de participante
    assert "angabave.jugador" in html        # se recuerda en el navegador
    assert "Tu semana" in html               # resumen personal
    assert "palabrasDeFila" in html          # lo que dice cada partido de ti


def test_la_semana_en_curso_queda_destacada(armado, tmp_path: Path):
    html = render(armado, tmp_path)
    datos = datos_embebidos(html)
    assert datos["activa"] == 2
    # En el selector, la semana en curso lleva su marca.
    assert 'classList.add("en-curso")' in html


def test_la_pagina_no_pide_fuentes(armado, tmp_path: Path):
    """Las cifras de marcador viajan dentro de la página; lo demás es la letra del teléfono."""
    html = render(armado, tmp_path)
    caras = re.findall(r"@font-face\{[^}]*\}", html)
    assert len(caras) == 1
    assert "font-family:'Rotulo'" in caras[0]
    assert "src:url(data:font/woff2;base64," in caras[0]
    assert "unicode-range:U+30-39,U+24,U+25,U+2B-2F,U+3A" in caras[0]     # solo cifras y signos
    assert "-apple-system" in html
    assert _externas(html) == {"https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"}


def _estilo(html: str) -> str:
    return html[html.index("<style>"):html.index("</style>")]


def _reglas(html: str) -> list[tuple[str, str]]:
    """El CSS en (selector, declaraciones), también lo que va dentro de un @media."""
    return [(s.strip(), d) for s, d in re.findall(r"([^{}]+)\{([^{}]*)\}", _estilo(html))]


def test_las_cifras_de_marcador_nunca_van_en_nombres_ni_frases(armado, tmp_path: Path):
    html = render(armado, tmp_path)
    assert "--num:'Rotulo',var(--cuerpo)" in html
    selectores = ",".join(s for s, d in _reglas(html) if "font-family:var(--num)" in d)
    for cifra in (".mrc", ".pts", ".sem", ".c-pos .n", ".fila-gan .monto", ".bolsa-final .val", ".campeon .bolsa",
                  ".mi-barra .linea b", ".mi-barra .linea .rango", ".celda-semana b", ".lugar .puntos",
                  ".candidato .pct", ".detalle-partido .marcador", ".cifras .cifra b"):
        assert cifra in selectores, cifra
    for palabras in (".c-nombre", ".quien", ".nombres", ".nom", ".eq", ".saludo", ".titulo", ".rot", ".sig"):
        assert not re.search(re.escape(palabras) + r"(?![\w-])", selectores), palabras


def test_el_dinero_es_oro_lo_tuyo_acento_y_tu_fila_no_es_mostaza(armado, tmp_path: Path):
    html = render(armado, tmp_path)
    regla = dict(_reglas(html))
    for dinero in (".lugar .bolsa", ".fila-gan .monto", ".campeon .bolsa"):
        assert "color:var(--oro)" in regla[dinero], dinero
    assert "color:var(--oro)" in regla[".bolsa-final .val"]
    assert "background:var(--oro)" in regla['.saludo::after']
    assert "color:var(--txt)" in regla[".mi-barra .linea .rango"]
    assert "box-shadow:inset 3px 0 0 var(--acento)" in regla["tbody tr.yo td:first-child"]
    assert "background:var(--fila-yo)" in regla["tbody tr.yo td"]
    nombre = regla["tbody tr.yo .c-nombre"]
    assert "color:var(--txt)" in nombre and "font-weight:700" in nombre
    # Lleno es a favor, hueco es en contra: se distingue sin color.
    assert "background:var(--verde)" in regla[".progreso-semana .ok"]
    assert "background:transparent" in regla[".progreso-semana .mal"]
    assert "box-shadow:inset 0 0 0 1.5px var(--rojo)" in regla[".progreso-semana .mal"]
    assert "var(--fila-estado)" in regla[".juego-fila .fila-mi-pick .sig"]   # el anillo
    assert "✓" in html and "✕" in html           # al terminar, la marca no depende del color
    assert "opacity:.55" in regla['.duelo-pick:has(.opcion[aria-pressed="true"]) .opcion[aria-pressed="false"]']


def test_los_titulares_son_blancos_y_de_un_solo_color(armado, tmp_path: Path):
    html = render(armado, tmp_path)
    assert not re.search(r"\bresalta\b", html)
    h1 = dict(_reglas(html))[".saludo h1"]
    assert "font-weight:700" in h1 and "letter-spacing:-.03em" in h1 and "color:" not in h1


def test_lo_que_se_veia_viejo_no_regresa(armado, tmp_path: Path):
    html = render(armado, tmp_path)
    estilo = _estilo(html)
    assert "box-shadow:0 0" not in estilo          # nada de neón
    assert "--mx" not in html and ".tarjeta::after" not in estilo      # la luz que seguía al cursor
    assert "barrer" not in estilo and "@keyframes listo" not in estilo
    assert "--resorte" not in html and "--suave" not in html


def test_solo_tres_radios_y_el_circulo(armado, tmp_path: Path):
    html = render(armado, tmp_path)
    radios = set(re.findall(r"border-radius:([^;}]+)", _estilo(html)))
    permitidos = {"var(--r1)", "var(--r2)", "var(--r3)", "50%", "99px",   # los tres y el círculo
                  "20px", "20px 20px 0 0", "26px",                        # la hoja, y la barra con su pastilla
                  "2px", "2px 2px 0 0"}                                   # segmentos de una tira o barra
    assert radios <= permitidos, radios - permitidos
    assert "--r1:16px; --r2:12px; --r3:8px" in html


def test_las_listas_y_tablas_no_llevan_caja(armado, tmp_path: Path):
    html = render(armado, tmp_path)
    listas = {".marco", ".boleta", ".fila-gan", ".split", ".candidato", ".lugar", ".tarjeta", ".ganadores", ".mi-semana"}
    for selector, declaraciones in _reglas(html):
        if selector in listas:
            for caja in ("background", "border:", "border-radius"):
                assert caja not in declaraciones, (selector, caja)
    # El encabezado de la tabla no lleva esquinas: la de la última columna se salía del marco.
    regla = dict(_reglas(html))
    assert not any(re.search(r"\bth\b", s) and "radius" in d for s, d in _reglas(html))
    # Y mismo relleno que sus números: el encabezado les cae exacto encima.
    assert "padding" in regla["th,td"] and "padding" not in regla["thead th"]
    # Con todas las semanas la tabla se desliza: el nombre no se parte letra por letra.
    assert "white-space:nowrap" in regla[".rueda.expandida .c-nombre"]


def test_un_solo_idioma_de_movimiento(armado, tmp_path: Path):
    html = render(armado, tmp_path)
    for variable in ("--sale:cubic-bezier(.16,1,.3,1)", "--entra:cubic-bezier(.4,0,1,1)",
                     "--traza:cubic-bezier(.65,0,.35,1)", "--hoja:cubic-bezier(.32,.72,0,1)", "--rebote:linear("):
        assert variable in html, variable
    # Nada grande rebota.
    grande = (".hoja", ".boton", ".juego-fila", ".mi-barra-yo", ".indicador", ".corredera", ".tarjeta",
              ".aviso-picks", ".opcion", ".celda-semana", ".ver-todas", ".mi-fila", ".flotante")
    for selector, declaraciones in _reglas(html):
        if "var(--rebote)" in declaraciones:
            assert not any(pieza in selector for pieza in grande), selector
    # Las entradas sueltan su capa al terminar; solo lo que sale se queda como terminó.
    for selector, declaraciones in _reglas(html):
        if re.search(r"animation:[^;}]*\bboth\b", declaraciones) and ".cancha" not in selector:
            assert re.search(r"\.mas|rodillo|saliendo|view-transition", selector), selector
    # Quedan tres puntos que laten sin parar, y ninguna celda.
    latidos = [s for s, d in _reglas(html) if "animation:latir" in d and "infinite" in d]
    assert len(latidos) <= 3, latidos


def test_presionar_responde_al_instante(armado, tmp_path: Path):
    html = render(armado, tmp_path)
    tacto = [(s, d) for s, d in _reglas(html) if "transform:scale(.985)" in d]
    assert tacto and all("transition:transform .07s linear" in d for _, d in tacto)
    selectores = ",".join(s for s, _ in tacto)
    for pieza in (".boton-principal:active", ".boton:active", ".juego-fila:active", ".mi-barra-yo:active"):
        assert pieza in selectores
    # Sin un touchstart, Safari de iOS no pinta :active.
    assert "addEventListener('touchstart',function(){},{passive:true})" in html


def test_lo_de_abajo_se_revela_una_vez_con_un_observador(armado, tmp_path: Path):
    html = render(armado, tmp_path)
    assert "new IntersectionObserver" in html
    assert "revelador.unobserve(entrada.target)" in html


def _arranque(html: str) -> str:
    """El script del <head>, el que corre antes de pintar."""
    cabeza = html[:html.index("</head>")]
    return cabeza[cabeza.index("<script>"):cabeza.index("</script>")]


def test_el_arranque_no_pinta_la_vista_equivocada(armado, tmp_path: Path):
    html = render(armado, tmp_path)
    arranque = _arranque(html)
    assert html.index("<script>") < html.index("<style>")      # antes de que haya algo que pintar
    assert "r.className='js'" in arranque
    assert "localStorage.getItem('angabave.tema')" in arranque     # tu equipo, desde el primer cuadro
    assert "sessionStorage.getItem('angabave.estreno')" in arranque
    # En JavaScript viejo: si el script principal no se entiende, esto sí tiene que correr.
    for moderno in ("=>", "let ", "const ", "`", "?.", "??", "async ", "class "):
        assert moderno not in arranque, moderno
    # Se destapa con DOMContentLoaded: aunque el script principal reviente, la General se ve.
    assert "addEventListener('DOMContentLoaded',function(){r.classList.add('listo')})" in arranque
    assert ".js:not(.listo) main>.vista" in html
    assert 'class="vista anima env" id="vista-general"' in html
    assert '.setProperty' not in arranque
    assert 'guardar("angabave.tema", null)' in _funcion(html, "aplicarTema")


def test_lo_publicado_no_lleva_notas_internas(armado, tmp_path: Path):
    html = render(armado, tmp_path)
    assert "/*" not in _estilo(html)
    principal = html[html.rindex("<script>"):html.rindex("</script>")]
    assert "/*" not in principal
    assert not re.search(r"^\s*//", principal, re.M)
    assert "<!--" not in html
    # Lo demás se queda: el código, su sangría, la red de seguridad y los datos.
    assert "\n  function pintarHoy(" in principal
    assert "window.angabaveListo = true" in principal
    assert 'var detalle = "";' in html
    assert datos_embebidos(html)["activa"] == 2


def test_quitar_notas_no_toca_textos_ni_expresiones():
    from quiniela.render_html import _sin_comentarios_js

    assert _sin_comentarios_js('a = "http://x/*y*/"; // nota') == 'a = "http://x/*y*/"; '
    assert _sin_comentarios_js("b = 'no // es nota'; /* esta\n   sí */ c = 1;") == "b = 'no // es nota';  c = 1;"
    assert _sin_comentarios_js('d = s.replace(/\\/\\/[/*"]/g, "");') == 'd = s.replace(/\\/\\/[/*"]/g, "");'
    assert _sin_comentarios_js("e = x / 2 / y; // mitad") == "e = x / 2 / y; "
    assert _sin_comentarios_js('function f() { return /"\\//.test(a); } // fin') == 'function f() { return /"\\//.test(a); } '
    assert _sin_comentarios_js('g = () => /^\\d+$/.test(a); // sí') == 'g = () => /^\\d+$/.test(a); '
    assert _sin_comentarios_js("h = 'it\\'s'; // otra") == "h = 'it\\'s'; "


def test_si_no_se_pueden_quitar_las_notas_la_pagina_igual_sale(armado, tmp_path: Path, monkeypatch):
    """Es un ahorro, no un requisito: el domingo la página se publica aunque esto truene."""
    import quiniela.render_html as generador

    def truena(_html):
        raise ValueError("comentario sin cerrar")

    monkeypatch.setattr(generador, "_sin_comentarios", truena)
    html = render(armado, tmp_path)
    assert "window.angabaveListo = true" in html


def test_el_pie_va_en_dos_renglones_y_sin_la_palabra_alfa(armado, tmp_path: Path):
    from quiniela.render_html import VERSION

    html = render(armado, tmp_path)
    pie = html[html.index("<footer>"):html.index("</footer>")]
    assert pie.count("<p") == 2
    assert "Actualizado 20 sep 2026, 14:32, hora de Ciudad de México" in pie
    assert "Desarrollado por Angel Barrera" in pie and VERSION in pie
    assert "Gana la semana" not in pie               # las reglas viven en Premios
    # La palabra no se ve en ningún lado: lo que se pinta es el cuerpo sin sus scripts.
    cuerpo = re.sub(r"<script.*?</script>", "", html[html.index("<body>"):], flags=re.S)
    assert not re.search(r"\balfa\b", cuerpo, re.I)
    assert '"alfa"' not in html[html.rindex("<script>"):]


def test_la_prueba_de_red_encuentra_la_version_en_las_dos_paginas(armado, tmp_path: Path):
    from quiniela.render_html import ETAPA, VERSION

    render(armado, tmp_path)
    red = (tmp_path / "red.html").read_text(encoding="utf-8")
    patron = r'<meta name="version" content="([^"]+)"'
    assert patron in red
    assert re.search(r"\balfa\b", re.sub(r"<script.*?</script>", "", red, flags=re.S), re.I) is None
    for nombre in ("index.html", "cargar.html"):
        pagina = (tmp_path / nombre).read_text(encoding="utf-8")
        assert re.search(patron, pagina).group(1) == f"{ETAPA} {VERSION}", nombre


def test_hay_animacion_para_los_cambios_de_marcador(armado, tmp_path: Path):
    html = render(armado, tmp_path)
    assert "@keyframes ola" in html and "@keyframes rueda" in html
    assert "anotaciones.set" in html          # se detecta el cambio


def test_las_tandas_cierran_el_dia_anterior_a_las_23_59(tmp_path: Path):
    """El jueves cierra el miércoles; el domingo y el lunes, el sábado."""
    from quiniela.render_html import _tandas

    jueves = datetime(2026, 9, 25, 0, 15, tzinfo=timezone.utc)      # jue 24, 18:15 CDMX
    domingo = datetime(2026, 9, 27, 17, 0, tzinfo=timezone.utc)     # dom 27, 11:00 CDMX
    lunes = datetime(2026, 9, 29, 0, 15, tzinfo=timezone.utc)       # lun 28, 18:15 CDMX

    tandas = _tandas([
        Partido("Falcons", "Packers", inicio=jueves),
        Partido("Chargers", "Bills", inicio=domingo),
        Partido("Giants", "Rams", inicio=lunes),
    ])
    assert len(tandas) == 2
    assert tandas[0]["claves"] == ["Falcons@Packers"]
    assert "miércoles 23" in tandas[0]["cierre_texto"] and "23:59" in tandas[0]["cierre_texto"]
    assert tandas[1]["claves"] == ["Chargers@Bills", "Giants@Rams"]
    assert "sábado 26" in tandas[1]["cierre_texto"]


def test_sin_horarios_no_hay_tandas(tmp_path: Path):
    from quiniela.render_html import _tandas

    assert _tandas([Partido("Lions", "Bills")]) == []


def test_el_generador_de_picks_esta_en_la_semana_pendiente(armado, tmp_path: Path):
    html = render(armado, tmp_path)
    assert "Arma tu quiniela" in html
    assert "quinielanfl@hotmail.com" in html
    assert "exportarPicks" in html
    # Las tandas de la semana pendiente viajan con su fecha de cierre.
    datos = datos_embebidos(html)
    pendiente = next(s for s in datos["semanas"] if s["estado"] == "pendiente")
    assert pendiente["tandas"]
    assert all("cierre_texto" in t and t["claves"] for t in pendiente["tandas"])


def test_el_generador_no_manda_nada_por_su_cuenta(armado, tmp_path: Path):
    """Solo arma la imagen: nada de subir picks ni registrar nada."""
    html = render(armado, tmp_path)
    assert "fetch(" in html          # solo la consulta de marcadores
    assert "method: \"POST\"" not in html and "method:'POST'" not in html
    assert "FormData" not in html


def test_se_publica_un_sello_de_version(armado, tmp_path: Path):
    """Pages cachea el HTML diez minutos; este archivo es el que avisa."""
    import json as _json

    semanas, general = armado
    generar_html(
        anio=2026, semanas=semanas, tabla_acumulada=general,
        ruta_salida=tmp_path / "index.html", momento=MOMENTO,
    )
    sello = _json.loads((tmp_path / "version.json").read_text(encoding="utf-8"))
    assert sello["generado"] == MOMENTO.isoformat()
    assert sello["version"].startswith("v")
    assert sello["firma"] == datos_embebidos((tmp_path / "index.html").read_text(encoding="utf-8"))["firma"]


def test_la_pagina_vigila_su_propia_version(armado, tmp_path: Path):
    html = render(armado, tmp_path)
    assert 'fetch("version.json?t="' in html
    assert 'cache: "no-store"' in html
    # Y al recargar se salta el caché con un parámetro nuevo.
    assert "recargarFresco" in html
    assert "location.reload()" not in html


def test_los_partidos_salen_en_el_orden_de_la_nfl(armado, tmp_path: Path):
    """Por hora de inicio: jueves, domingo, lunes. No el del Excel ni el de ESPN."""
    datos = datos_embebidos(render(armado, tmp_path))
    for semana in datos["semanas"]:
        horas = [p["t"] for p in semana["partidos"] if p["t"]]
        assert horas == sorted(horas), f"semana {semana['n']} desordenada"


def test_reordenar_no_desfasa_los_picks(tmp_path: Path):
    """Si los picks se despegan de su partido, todo el conteo queda mal y no se ve.

    Se compara pick por pick contra el archivo del organizador.
    """
    from quiniela.render_html import _orden_nfl

    dir_cache = tmp_path / "resultados"
    ruta = crear_excel(tmp_path / "Semana_02.xlsx")
    partidos, picks = leer_picks(ruta)

    # Horarios deliberadamente al revés del orden del Excel.
    base = datetime(2026, 9, 25, 0, 15, tzinfo=timezone.utc)
    resultados = [
        Partido(v, l, 24, 17, l, True, "Final", base + timedelta(hours=len(ENFRENTAMIENTOS_S2) - i))
        for i, (v, l) in enumerate(ENFRENTAMIENTOS_S2)
    ]
    guardar_cache(2, resultados, dir_cache)
    tabla = tabla_semana(partidos, picks, resultados)
    general = tabla_general([ruta], dir_cache=dir_cache, ruta_overrides=tmp_path / "no.json")

    html = generar_html(
        anio=2026, semanas=[SemanaRender(2, resultados, picks, tabla)],
        tabla_acumulada=general, ruta_salida=tmp_path / "index.html", momento=MOMENTO,
    ).read_text(encoding="utf-8")
    datos = datos_embebidos(html)
    semana = datos["semanas"][0]

    # El orden publicado no puede ser el del Excel: los horarios van al revés.
    assert _orden_nfl(resultados) != list(range(len(resultados)))

    verdad = {
        nombre: dict(zip((p.clave for p in partidos), elegidos))
        for nombre, elegidos in picks.items()
    }
    claves = [p["v"] + "@" + p["l"] for p in semana["partidos"]]
    for fila, idx in enumerate(semana["jugadores"]):
        quien = datos["participantes"][idx]
        for col, clave in enumerate(claves):
            visitante, local = clave.split("@")
            publicado = local if semana["picks"][fila][col] == 1 else visitante
            assert publicado == verdad[quien][clave], f"{quien} desfasado en {clave}"


def test_un_nombre_con_codigo_no_entra_crudo_a_la_pagina(armado, tmp_path: Path):
    """El lector ya rechaza estos nombres; esta es la segunda barrera.

    La plantilla se llama index.html.j2 y el autoescape de Jinja la dejaba
    fuera. Si un nombre así llegara a los datos, la página tiene que pintarlo
    como texto y no ejecutarlo.
    """
    semanas, general = armado
    malicioso = '<img src=x onerror="alert(1)">'
    general = general.copy()
    general.loc[general.index[0], "participante"] = malicioso
    html = render((semanas, general), tmp_path)
    assert malicioso not in html
    assert "&lt;img src=x onerror=&#34;alert(1)&#34;&gt;" in html


def test_la_pagina_de_carga_sale_con_el_portal(armado, tmp_path: Path):
    render(armado, tmp_path)
    pagina = (tmp_path / "cargar.html").read_text(encoding="utf-8")

    # No aparece en buscadores ni manda de dónde viene.
    assert '<meta name="robots" content="noindex, nofollow">' in pagina
    assert '<meta name="referrer" content="no-referrer">' in pagina
    # Solo se puede conectar con la función que recibe los archivos.
    politica = re.search(r'Content-Security-Policy" content="([^"]+)"', pagina).group(1)
    assert "default-src 'none'" in politica
    assert re.search(r"connect-src ([^;]+)", politica).group(1) == "https://hxaajhsizdnlismnelqu.supabase.co"
    assert "form-action 'none'" in politica and "base-uri 'none'" in politica
    # Nada de afuera, y los datos se pintan como texto.
    assert "<script src" not in pagina and 'rel="stylesheet"' not in pagina
    assert "innerHTML" not in pagina and "insertAdjacentHTML" not in pagina
    # La llave se lee del "#", que no viaja al servidor; nunca de "?".
    assert "location.hash" in pagina and "location.search" not in pagina
    config = json.loads(re.search(r'<script id="config" type="application/json">(.*?)</script>', pagina).group(1))
    assert config["funcion"].endswith("/functions/v1/angabave-carga")


def test_la_pagina_de_carga_no_deja_rastro(armado, tmp_path: Path):
    render(armado, tmp_path)
    pagina = (tmp_path / "cargar.html").read_text(encoding="utf-8").lower()
    for rastro in ("claude", "anthropic", "inteligencia artificial", "gpt", "automáticamente"):
        assert rastro not in pagina


def test_el_generador_de_picks_no_usa_los_partidos_ya_cargados():
    """Con la semana a medias, s.partidos solo trae la tanda cargada.

    El generador ofrece otros partidos (los que faltan por repartir), así que la
    imagen y el contador tienen que salir de su propia lista. Cuando la imagen
    leía s.partidos, salía con "0 PICKS" y cortada.
    """
    plantilla = (Path(__file__).resolve().parents[1] / "quiniela" / "plantillas" / "index.html.j2").read_text(
        encoding="utf-8"
    )
    tramo = plantilla[plantilla.index("async function exportarPicks("):plantilla.index("function aviso(titulo, texto)")]
    codigo = [l for l in tramo.splitlines() if not l.strip().startswith(("//", "/*", "*"))]
    assert not [l for l in codigo if "s.partidos" in l or "s.tandas" in l]


# --- que ninguna página se quede en blanco -----------------------------------------


def _rescate(pagina: str) -> str:
    """El script de la red de seguridad, que va justo después del aviso."""
    inicio = pagina.index('<div id="rescate"')
    return pagina[inicio:pagina.index("</script>", inicio)]


@pytest.mark.parametrize("nombre", ["index.html", "cargar.html"])
def test_las_dos_paginas_traen_la_red_de_seguridad(armado, tmp_path: Path, nombre: str):
    render(armado, tmp_path)
    pagina = (tmp_path / nombre).read_text(encoding="utf-8")
    rescate = _rescate(pagina)
    # Está antes del script principal, para escuchar sus errores desde el principio.
    assert pagina.index('<div id="rescate"') < pagina.index("window.angabaveListo = true")
    # En JavaScript viejo: nada que un Safari de hace años no entienda.
    script = rescate[rescate.index("<script>"):]
    for moderno in ("=>", "let ", "const ", "`", "?.", "??", "async ", "class "):
        assert moderno not in script, moderno
    assert "navigator.userAgent" in script   # el detalle dice qué navegador era
    assert "<noscript>" in pagina


def test_el_portal_no_se_recarga_en_bucle():
    """El CDN de GitHub ignora el ?v=: recargar sin candado era un bucle en blanco."""
    plantilla = (Path(__file__).resolve().parents[1] / "quiniela" / "plantillas" / "index.html.j2").read_text(
        encoding="utf-8"
    )
    assert "sello.generado !== D.generado" not in plantilla
    assert "if (!(publicada > esta)) return;" in plantilla
    assert "ahora - previa.cuando < TRES_MIN" in plantilla
    assert "previa.version === version && ahora - previa.cuando < ONCE_MIN" in plantilla


def test_el_portal_solo_se_recarga_si_cambio_la_firma(armado, tmp_path: Path):
    """Antes se recargaba cada diez minutos, todo el año, con o sin novedades."""
    html = render(armado, tmp_path)
    assert "recarga" not in datos_embebidos(html)
    assert "D.recarga" not in html
    revisar = _funcion(html, "revisarVersion")
    assert "sello.firma === D.firma" in revisar
    # La hora nueva sin firma nueva es un latido: se anota y nada más.
    assert revisar.index("latido = publicada") < revisar.index("sello.firma === D.firma")
    # Y no se le recarga a quien está en medio de algo.
    assert revisar.index('.hoja-fondo') < revisar.index("recargarFresco(")
    assert "escribiendo()" in revisar and "ultimoToque" in revisar


def test_redibujar_le_devuelve_a_la_persona_lo_que_tenia_a_medias(armado, tmp_path: Path):
    """El marcador redibujaba la vista cada minuto y borraba búsquedas y elecciones."""
    html = render(armado, tmp_path)
    consultar = _funcion(html, "consultarVivo")
    assert "repintar()" not in consultar and "repintarSinEstorbar()" in consultar
    assert "JSON.stringify(todosLosJuegos(s)) !== antes" in consultar
    sin_estorbar = _funcion(html, "repintarSinEstorbar")
    assert sin_estorbar.index("leerControles()") < sin_estorbar.index("repintar()") < sin_estorbar.index("reponerControles(")
    # Las listas se recuerdan por el nombre: su valor es la posición en la tabla.
    assert "selectedOptions" in _funcion(html, "leerControles")
    assert "o.text === valores[i]" in _funcion(html, "reponerControles")
    assert "controles: leerControles()" in _funcion(html, "recordarSitio")
    # Solo si la recarga la hizo la página: quien recarga a mano quiere empezar de cero.
    assert "if (automatica) reponerControles(guardado.controles);" in html
    assert "recargaAutomatica = true;" in _funcion(html, "recargarFresco")


def test_compatibilidad_con_safari_viejo():
    raiz = Path(__file__).resolve().parents[1] / "quiniela" / "plantillas"
    portal = (raiz / "index.html.j2").read_text(encoding="utf-8")
    carga = (raiz / "cargar.html.j2").read_text(encoding="utf-8")
    assert "if (ctx.roundRect)" in portal            # iOS 16
    assert ".replaceChildren(" not in carga           # iOS 14
    assert "signal: control.signal" in carga         # nada se queda esperando para siempre


# --- las páginas sueltas: la misma casa que el portal ------------------------------

EMOJIS = re.compile("[\U0001F000-\U0001FAFF\u2190-\u21FF\u2300-\u23FF\u2600-\u27BF\uFE0F]")


@pytest.mark.parametrize("nombre", ["cargar.html", "red.html"])
def test_las_paginas_sueltas_son_de_la_misma_casa(armado, tmp_path: Path, nombre: str):
    from quiniela.render_html import tema_campo

    render(armado, tmp_path)
    pagina = (tmp_path / nombre).read_text(encoding="utf-8")
    for variable, valor in tema_campo().items():
        assert f"{variable}:{valor};" in pagina, variable
    assert EMOJIS.search(pagina) is None, EMOJIS.findall(pagina)
    # Lo de la generación pasada.
    for viejo in ("@font-face", "box-shadow", "radial-gradient", "linear-gradient", "letter-spacing",
                  "#041009", "#102117", "#f7c948", "#101724"):
        assert viejo not in pagina, viejo
    # Letra de 12 px para arriba y solo los tamaños de la casa.
    assert set(re.findall(r"font(?:-size)?:(\d+)px", pagina)) <= {"12", "14", "16", "20"}
    assert "rem" not in "".join(re.findall(r"font-size:[^;}]*", pagina))


def test_la_red_de_seguridad_es_de_la_misma_casa(armado, tmp_path: Path):
    render(armado, tmp_path)
    for nombre in ("index.html", "cargar.html"):
        rescate = _rescate((tmp_path / nombre).read_text(encoding="utf-8"))
        assert "La página no abrió en este teléfono" in rescate
        assert "Ajustes" not in rescate   # no todos los teléfonos son iPhone
        assert "#101613" in rescate and "#FF6B61" in rescate and "#FFD60A" in rescate
        assert "box-shadow" not in rescate and "#101724" not in rescate
        assert EMOJIS.search(rescate) is None


def test_los_textos_de_la_carga_que_se_cambiaron_y_los_que_se_quedan(armado, tmp_path: Path):
    render(armado, tmp_path)
    pagina = (tmp_path / "cargar.html").read_text(encoding="utf-8")
    for dice in (
        "Sube la hoja de la semana tal como la repartes, en Excel o PDF",
        "Sin conexión", "Revisa tu internet y vuelve a abrir el enlace.", "No se pudo terminar",
        "Ya empezaron, no cambian", "Última carga: ", "Quedó publicada.", "No pasó la revisión.", "Se está revisando.",
        "Carga del organizador",
        # Estos se quedan porque están bien.
        "Ya quedó. En un par de minutos se ve en el portal.",
        "No se tocó nada: el portal sigue exactamente como estaba.",
        "Una quiniela no pasa de 1 MB. ¿Es el archivo correcto?",
        "Algo falló de nuestro lado, no en tu archivo.",
    ):
        assert dice in pagina, dice
    for ya_no in ("No me pude conectar", "No pude terminar", "te digo", "Sellados", "Tu última carga", "CARGAR SEMANA"):
        assert ya_no not in pagina, ya_no
    assert "Desarrollado por Angel Barrera · v" in pagina and "· alfa" not in pagina
    assert "@media (hover:hover){.zona .arrastra{display:block}}" in pagina


def test_la_carga_sigue_hablando_igual_con_la_funcion(armado, tmp_path: Path):
    """Lo de la casa nueva es CSS y textos: la llave, la subida y la espera no se tocan."""
    render(armado, tmp_path)
    pagina = (tmp_path / "cargar.html").read_text(encoding="utf-8")
    for pieza in (
        'new URLSearchParams(location.hash.slice(1)).get("k")',
        'Object.assign({ "x-llave": llave }, opciones.cabeceras || {})',
        'que === "subir" ? 90000 : 20000',
        'cuerpo: archivo',
        '"x-archivo": encodeURIComponent(archivo.name), "content-type": "application/octet-stream"',
        "archivo.size > CONFIG.maximo",
        'pedir("estado", { params: { id } })',
        "CADA = 4000, PACIENCIA = 6 * 60 * 1000",
        r"/^[A-Za-z0-9_-]{32,64}$/.test(llave)",
        'entrada.accept = ".xlsx,.xlsm,.pdf,',
    ):
        assert pieza in pagina, pieza


def test_la_prueba_de_red_encuentra_la_version(armado, tmp_path: Path):
    """La versión ya no dice "alfa" en pantalla: la prueba de conexión la lee de la meta."""
    from quiniela.render_html import ETAPA, VERSION

    render(armado, tmp_path)
    red = (tmp_path / "red.html").read_text(encoding="utf-8")
    assert '<meta name="version" content="([^"]+)"' in red
    carga = (tmp_path / "cargar.html").read_text(encoding="utf-8")
    assert re.search(r'<meta name="version" content="([^"]+)"', carga).group(1) == f"{ETAPA} {VERSION}"
    # Y el portal, mientras traiga la etapa en el pie o en la meta.
    assert re.search(r"alfa v\d+\.\d+\.\d+", (tmp_path / "index.html").read_text(encoding="utf-8"))


def test_la_prueba_de_red_sale_con_el_portal(armado, tmp_path: Path):
    render(armado, tmp_path)
    pagina = (tmp_path / "red.html").read_text(encoding="utf-8")
    politica = re.search(r'Content-Security-Policy" content="([^"]+)"', pagina).group(1)
    assert re.search(r"connect-src ([^;]+)", politica).group(1).split() == [
        "'self'", "https://hxaajhsizdnlismnelqu.supabase.co", "https://site.api.espn.com",
    ]
    script = pagina[pagina.index("<script>"):]
    for moderno in ("=>", "let ", "const ", "`", "?.", "??", "async ", "class "):
        assert moderno not in script, moderno   # tiene que correr donde las otras fallan
    assert "<script src" not in pagina and "innerHTML" not in pagina
    for rastro in ("claude", "anthropic", "inteligencia artificial", "gpt", "automáticamente"):
        assert rastro not in pagina.lower()



# --- la experiencia nueva ------------------------------------------------------------


def test_hoy_es_la_portada(armado, tmp_path: Path):
    html = render(armado, tmp_path)
    assert 'id="vista-hoy"' in html
    assert ': "hoy";' in html                 # sin dirección ni sesión previa, abre en Hoy
    assert "function pintarHoy" in html


def test_las_dos_navegaciones_son_iguales(armado, tmp_path: Path):
    """Arriba en computadora y abajo en el teléfono, con los mismos cinco botones."""
    html = render(armado, tmp_path)
    navs = re.findall(r'<nav class="[^"]*navegacion[^"]*" data-nav[^>]*>(.*?)</nav>', html, re.S)
    assert len(navs) == 2
    botones = [re.findall(r'data-vista="([a-z]+)"', n) for n in navs]
    assert botones[0] == botones[1] == ["hoy", "picks", "semana", "general", "premios"]
    # La de abajo va fuera del encabezado: su desenfoque la dejaría pegada a él.
    assert html.index('class="navegacion al-pie"') > html.index("</header>")
    # "arriba" ya es el botón de volver arriba (fijo y transparente hasta que
    # bajas): una navegación con esa clase quedaba invisible en computadora.
    for clases in re.findall(r'<nav class="([^"]*navegacion[^"]*)"', html):
        assert "arriba" not in clases.split()


def test_la_marca_es_la_misma_en_todas_partes(armado, tmp_path: Path):
    from quiniela import marca

    html = render(armado, tmp_path)
    assert marca.ruta_a() in html and marca.ruta_linea() in html  # el SVG del encabezado
    assert marca.PALABRA in html and 'class="marca"' not in html  # la palabra ya es dibujo
    assert '<link rel="icon" href="data:image/svg+xml,' in html  # el ícono de la pestaña
    assert datos_embebidos(html)["logo"]["rutas"] == marca.rutas()   # el canvas de la imagen
    assert "escudoEnLienzo" not in html                          # el escudo viejo ya no está
    for pagina in ("cargar.html", "red.html"):
        suelta = (tmp_path / pagina).read_text(encoding="utf-8")
        assert marca.ruta_a() in suelta and marca.PALABRA in suelta and 'rel="icon"' in suelta, pagina


def test_la_marca_vale_para_cualquier_equipo_y_cualquier_fondo(armado, tmp_path: Path):
    """La A es del color del texto y la línea del oro; sin fondo propio ni degradados."""
    from quiniela import marca
    from quiniela.render_html import BASE_CAMPO, SEMANTICOS, tema_campo

    html = render(armado, tmp_path)
    assert ".logo .marca-linea{fill:var(--oro)}" in html and ".logo{color:var(--txt)}" in html
    svg = marca.svg()
    assert 'fill="currentColor"' in svg and "marca-linea" in svg
    for ajeno in ("Gradient", "<rect", "stroke", "url(#"):
        assert ajeno not in svg, ajeno
    # Los mismos colores del portal.
    assert marca.ORO == SEMANTICOS["oro"]
    assert marca.NEGRO == BASE_CAMPO["bg"]
    assert marca.BLANCO == tema_campo()["--txt"]


def test_la_linea_del_logo_se_traza_con_el_titular(armado, tmp_path: Path):
    html = render(armado, tmp_path)
    regla = re.search(r"\.llegando \.logo \.marca-linea\{([^}]*)\}", html).group(1)
    assert "transform-box:fill-box" in regla and "animation:traza" in regla


def test_la_marca_no_se_sale_de_su_caja():
    from quiniela import marca

    for pieza in (*marca.A, marca.LINEA, *marca.A_ICONO, *marca.A_FAVICON):
        assert all(0 <= x <= 64 and 0 <= y <= 64 for x, y in pieza)
    # El ícono que Android recorta: la A entera dentro del círculo seguro.
    for pieza in marca.A_ICONO:
        assert all(((x - 32) ** 2 + (y - 32) ** 2) ** 0.5 <= 25.6 for x, y in pieza)
    # Hay aire de verdad arriba y abajo de la línea, para que no se junte con la A.
    arriba, pie_izquierdo, _ = marca.A
    assert max(y for _, y in arriba) < min(y for _, y in marca.LINEA)
    assert min(y for _, y in pie_izquierdo) > max(y for _, y in marca.LINEA)


def test_la_palabra_aplanada_es_la_misma_del_svg():
    from quiniela import marca

    poligonos = marca.poligonos_de_palabra()
    assert len(poligonos) == 10   # ocho letras y los dos huecos de la B
    assert all(0 <= x <= marca.ANCHO_PALABRA and -1 <= y <= marca.ALTO_PALABRA - 1 for p in poligonos for x, y in p)


def test_la_palabra_dibujada_respeta_los_huecos_de_la_b():
    from quiniela.render_png import dibujar_palabra

    palabra = dibujar_palabra(84)     # 2 px por unidad, y la caja empieza en y = -1
    assert palabra.getpixel((2 * 140, 2 * 21))[3] == 255   # el tronco de la B
    assert palabra.getpixel((2 * 149, 2 * 12))[3] == 0     # su hueco de arriba
    assert palabra.getpixel((2 * 149, 2 * 29))[3] == 0     # y el de abajo


def test_en_vivo_solo_cuando_se_esta_jugando(armado, tmp_path: Path):
    """Una semana a medias un viernes está en curso, no en vivo."""
    html = render(armado, tmp_path)
    estado = html[html.index("function pintarEstado"):html.index("const COLORES")]
    assert "juegosEnVivo(s)" in estado
    assert 's.estado === "en_vivo") {\n      chip.classList.add("vivo")' not in estado


def test_el_aviso_de_rezago_solo_si_algo_ya_arranco(armado, tmp_path: Path):
    """Un viernes sin partidos, "10 horas sin recalcularse" era una falsa alarma."""
    html = render(armado, tmp_path)
    rezago = html[html.index("function avisoDeRezago"):]
    rezago = rezago[:rezago.index("\n  }\n")]
    assert "if (!arrancados.length) return null;" in rezago
    # Sin novedades el sitio ya no se publica: se cuenta desde el último latido o
    # desde la patada, no desde la última publicación de hace tres días.
    assert "Math.max(latido, Math.min(" in rezago
    assert "!latidoVisto" in rezago   # sin saber el último latido no se alarma a nadie


def test_los_iconos_de_la_app_salen_de_la_marca(tmp_path: Path):
    from quiniela.render_png import generar_iconos

    rutas = generar_iconos(tmp_path)
    assert [r.name for r in rutas] == ["icono-180.png", "icono-192.png", "icono-512.png"]
    for ruta, lado in zip(rutas, (180, 192, 512)):
        with Image.open(ruta) as icono:
            assert icono.size == (lado, lado)
            assert icono.mode == "RGB"   # iOS no acepta transparencia
            lienzo = icono.convert("RGB")
            # La línea amarilla de orilla a orilla; arriba de ella el pasto y abajo el negro.
            y_linea = round((35.4 + 2.4) / 64 * lado)
            for x in (1, lado // 2, lado - 2):
                r, g, b = lienzo.getpixel((x, y_linea))
                assert r > 240 and g > 200 and b < 40, (lado, x)
            r, g, b = lienzo.getpixel((3, 3))
            assert g > r + 30 and g > b and g < 120
            assert sum(lienzo.getpixel((3, lado - 4))) < 40
            # Y sobre la línea, en medio, la punta blanca de la A.
            assert min(lienzo.getpixel((lado // 2, round(14 / 64 * lado)))) > 230


def _funcion(html: str, nombre: str) -> str:
    """El cuerpo de una función del script de la página, hasta su llave de cierre."""
    cuerpo = html[html.index("function " + nombre):]
    return cuerpo[:cuerpo.index("\n  }\n")]


def test_antes_de_la_patada_no_hay_cero_a_cero(armado, tmp_path: Path):
    """ESPN manda "0" de marcador antes del partido: no se pinta como un 0-0."""
    html = render(armado, tmp_path)
    vivo = _funcion(html, "parsearVivo")
    assert 'tipo.state === "pre"' in vivo and "v.m = null; l.m = null;" in vivo
    assert "enJuego: !tipo.completed && !antes" in vivo
    # En juego se ve el cuarto y el reloj, no un "En curso" genérico.
    assert '"Q" + reloj.period' in vivo


def test_los_picks_de_la_semana_que_sigue_no_tapan_la_que_se_juega(armado, tmp_path: Path):
    """El domingo en la noche importa cómo vas, no los picks que cierran el miércoles."""
    html = render(armado, tmp_path)
    hoy = _funcion(html, "pintarHoy")
    assert "picks.s === s" in hoy and "36 * 3600e3" in hoy
    assert ': apuran ? "picks"' in hoy


def test_el_martes_se_ve_quien_gano_la_semana(armado, tmp_path: Path):
    html = render(armado, tmp_path)
    hoy = _funcion(html, "pintarHoy")
    assert "semanaRecienCerrada()" in hoy
    assert 'picks: [["picks", "previo"]' in hoy
    # Y la barra muestra la última semana con tabla mientras la nueva no se reparte.
    assert "D.semanas.slice().reverse()" in _funcion(html, "numerosDe")


def test_elegir_nombre_es_de_un_toque(armado, tmp_path: Path):
    """La barra trae la lista encima: el teléfono abre su selector nativo al primer toque."""
    html = render(armado, tmp_path)
    barra = _funcion(html, "pintarMiBarra")
    assert 'listaDeNombres("¿Quién eres?")' in barra
    assert ".mi-barra-invita select{position:absolute; inset:0" in html
    assert "quien-eres" not in html                  # la tarjeta duplicada ya no está


def test_las_clases_nuevas_no_chocan_con_el_podio(armado, tmp_path: Path):
    """.lugar es del podio (borde, barra lateral): el lugar en la barra lo heredaba."""
    html = render(armado, tmp_path)
    script = html[html.index('id="datos"'):]
    assert not re.search(r'crear\("[a-z]+", "lugar"', script)
    assert not re.search(r'cifra\([^;]*, "lugar"\)', script)


def test_picks_tiene_su_seccion_y_es_la_unica_puerta(armado, tmp_path: Path):
    """Armar picks se hace en un solo lugar: la sección Picks de la barra."""
    html = render(armado, tmp_path)
    assert 'id="vista-picks"' in html and "function pintarPicks" in html
    assert 'data-vista="picks"' in html and 'class="globo"' not in html   # sin contador: no hacía falta
    script = html[html.index('id="datos"'):]
    llamadas = re.findall(r"moduloPicks\(", script)
    assert len(llamadas) == 2                                   # la definición y una sola llamada
    assert "moduloPicks(abiertos.s" in _funcion(html, "pintarPicks")


def test_hoy_no_pasa_de_cuatro_tarjetas(armado, tmp_path: Path):
    """Con demasiadas secciones la gente se pierde: cada momento lleva pocas."""
    html = render(armado, tmp_path)
    plan = _funcion(html, "pintarHoy")
    fases = re.findall(r'(\w+): \[\[([^\]]*)\], \[([^\]]*)\]\]', plan)
    assert {f[0] for f in fases} == {"vivo", "hoy", "picks", "cerrada", "semana"}
    for fase, principal, lateral in fases:
        assert len(re.findall(r'"\w+"', principal + lateral)) <= 4, fase


def test_la_semana_se_cambia_con_flechas_y_una_hoja(armado, tmp_path: Path):
    """La fila de S1 a S18 crecía sin fin: ahora flechas y todas en una hoja aparte."""
    html = render(armado, tmp_path)
    selector = _funcion(html, "selectorDeSemanas")
    assert "flecha-semana" in selector and "abrirSemanas(actual" in selector
    hoja = _funcion(html, "abrirHoja")
    assert 'setAttribute("aria-modal", "true")' in hoja and 'e.key === "Escape"' in hoja
    # Y "Semana" en la barra siempre lleva a la que se está jugando.
    assert "semanaElegida = D.activa" in html


def test_hoy_dice_cuando_no_hay_partidos(armado, tmp_path: Path):
    """Un día sin partidos se dice claro, y si ese día cierran picks, también."""
    html = render(armado, tmp_path)
    hoy = _funcion(html, "pintarHoy")
    assert "!vivos.length && !hoy.length && !terminados.length" in hoy
    assert "diaSinPartidos(picks)" in _funcion(html, "saludo")
    aviso = _funcion(html, "diaSinPartidos")
    assert '"Hoy no hay partidos ni eventos."' in aviso and "cierran los picks" in aviso


def test_el_podio_pinta_medalla_por_lugar_y_no_por_escalon():
    """Con 5 empatados en 2º, el escalón que sigue es el 7º: ni bronce ni premio."""
    from quiniela.render_html import _armar_podio

    nombres = [f"J{i}" for i in range(7)]
    general = ([{"p": 0, "pos": 1, "total": 52}]
               + [{"p": i, "pos": 2, "total": 51} for i in range(1, 6)]
               + [{"p": 6, "pos": 7, "total": 50}])
    reparto = ([{"nombre": "J0", "premio": "$17,640"}]
               + [{"nombre": f"J{i}", "premio": "$1,512"} for i in range(1, 6)])
    escalones = _armar_podio(general, nombres, reparto)
    assert [e["medalla"] for e in escalones] == ["oro", "plata", "sin-medalla"]
    assert [e["premio"] for e in escalones] == ["$17,640", "$1,512", None]
    # Con dos empatados en 1º, el que sigue es 3º: bronce, no plata.
    dos_arriba = [{"p": 0, "pos": 1, "total": 52}, {"p": 1, "pos": 1, "total": 52}, {"p": 2, "pos": 3, "total": 50}]
    assert [e["medalla"] for e in _armar_podio(dos_arriba, nombres, [])] == ["oro", "bronce"]


def test_la_dinamica_explica_los_empates_con_montos_de_verdad():
    from quiniela.render_html import dinamica

    texto = " ".join(sum(dinamica().values(), []))
    for monto in ("$5,200", "$17,640", "$5,040", "$2,520", "$1,512", "$8,400", "$11,340"):
        assert monto in texto
    assert "Del 4.º lugar en adelante no hay premio" in texto


def test_la_rebanada_de_hoy_viaja_agrupada_por_lugar(armado, tmp_path: Path):
    """Quién se llevaría algo si la temporada terminara hoy, sin esperar a la semana 18."""
    html = render(armado, tmp_path)
    premios = datos_embebidos(html)["premios"]
    assert premios["reparto"] == []                       # el oficial, hasta cerrar la temporada
    assert premios["hoy"] and {"pos", "p", "aciertos", "porcentaje", "premio"} <= set(premios["hoy"][0])
    assert all(g["pos"] <= 3 for g in premios["hoy"])
    assert "function tocariaHoy" in html


@pytest.mark.skipif(shutil.which("node") is None, reason="hace falta node para revisar la sintaxis")
def test_los_scripts_de_la_pagina_no_tienen_errores_de_sintaxis(armado, tmp_path: Path):
    """Un error de sintaxis tumba el script entero: la página queda a medias y sin aviso.

    Pasó en la v0.20.2 en preparación (una variable declarada dos veces) y solo se vio
    en el navegador.
    """
    html = render(armado, tmp_path)
    scripts = re.findall(r"<script(?![^>]*application/json)[^>]*>(.*?)</script>", html, re.S)
    assert scripts
    for i, codigo in enumerate(scripts):
        archivo = tmp_path / f"script{i}.js"
        archivo.write_text(codigo, encoding="utf-8")
        revision = subprocess.run(["node", "--check", str(archivo)], capture_output=True, text=True)
        assert revision.returncode == 0, revision.stderr


# --- publicar solo si hay algo que contar ---------------------------------------


def _generar(armado, ruta: Path, momento: datetime = MOMENTO) -> dict:
    semanas, general = armado
    generar_html(anio=2026, semanas=semanas, tabla_acumulada=general,
                 ruta_salida=ruta / "index.html", momento=momento)
    return json.loads((ruta / "version.json").read_text(encoding="utf-8"))


def _con_partidos(armado, cambio) -> tuple:
    """El mismo armado con los partidos de la primera semana retocados."""
    semanas, general = armado
    primera = semanas[0]
    return ([SemanaRender(primera.numero, cambio(list(primera.partidos)), primera.picks, primera.tabla,
                          primera.panorama, primera.faltantes), *semanas[1:]], general)


def test_la_firma_no_cambia_con_el_orden_de_los_empatados(armado, tmp_path: Path):
    """Dentro de un empate las filas siguen a quien va ganando: eso no es noticia."""
    from quiniela.render_html import _firma

    semana = {"partidos": [], "por_entregar": [], "tabla": [{"p": 0, "pos": 1, "f": 3, "e": 0}, {"p": 1, "pos": 1, "f": 3, "e": 0}]}
    volteada = {**semana, "tabla": semana["tabla"][::-1]}
    assert _firma({"semanas": [semana]}) == _firma({"semanas": [volteada]})
    otra = {**semana, "tabla": [{"p": 0, "pos": 1, "f": 4, "e": 0}, {"p": 1, "pos": 2, "f": 3, "e": 0}]}
    assert _firma({"semanas": [semana]}) != _firma({"semanas": [otra]})


def test_la_firma_no_cambia_con_la_hora_ni_con_los_marcadores_en_curso(armado, tmp_path: Path):
    (tmp_path / "a").mkdir(), (tmp_path / "b").mkdir()
    base = _generar(armado, tmp_path / "a")

    def se_mueve_el_marcador(partidos):
        p = partidos[1]
        partidos[1] = Partido(p.visitante, p.local, 21, 28, None, False, "Halftime", p.inicio)
        p = partidos[2]
        partidos[2] = Partido(p.visitante, p.local, 3, 0, None, False, "In Progress", p.inicio)  # arrancó
        return partidos

    otra = _generar(_con_partidos(armado, se_mueve_el_marcador), tmp_path / "b", MOMENTO + timedelta(hours=3))
    assert otra["firma"] == base["firma"]


@pytest.mark.parametrize("cambio", [
    lambda p: Partido(p.visitante, p.local, 21, 28, p.local, True, "Final", p.inicio),
    lambda p: Partido(p.visitante, p.local, 0, 0, None, False, "Postponed", p.inicio),
    lambda p: Partido(p.visitante, p.local, 0, 0, None, False, "Scheduled", datetime(2026, 9, 21, 17, tzinfo=timezone.utc)),
    lambda p: Partido(p.visitante, p.local, 0, 0, None, False, "Scheduled", datetime(2026, 9, 21, 5, tzinfo=timezone.utc), hora_definida=False),
], ids=["cerro", "pospuesto", "se-movio", "hora-por-definir"])
def test_la_firma_si_cambia_con_lo_que_dura(armado, tmp_path: Path, cambio):
    (tmp_path / "a").mkdir(), (tmp_path / "b").mkdir()
    base = _generar(armado, tmp_path / "a")

    def retoca(partidos):
        partidos[2] = cambio(partidos[2])
        return partidos

    assert _generar(_con_partidos(armado, retoca), tmp_path / "b")["firma"] != base["firma"]


def test_sin_novedad_la_pagina_se_queda_como_esta(armado, tmp_path: Path):
    primera = _generar(armado, tmp_path)
    html = (tmp_path / "index.html").read_bytes()
    segunda = _generar(armado, tmp_path, MOMENTO + timedelta(hours=2))
    assert segunda == primera                      # ni la hora: no hay partido en curso
    assert (tmp_path / "index.html").read_bytes() == html


def _en_curso(armado, arranque: datetime):
    def retoca(partidos):
        p = partidos[1]
        partidos[1] = Partido(p.visitante, p.local, 7, 3, None, False, "In Progress", arranque)
        return partidos
    return _con_partidos(armado, retoca)


def test_con_un_partido_en_curso_hay_latido_y_solo_toca_el_sello(armado, tmp_path: Path):
    armado_vivo = _en_curso(armado, MOMENTO - timedelta(minutes=10))
    primera = _generar(armado_vivo, tmp_path)
    html = (tmp_path / "index.html").read_bytes()

    # A los diez minutos todavía no toca.
    assert _generar(armado_vivo, tmp_path, MOMENTO + timedelta(minutes=10)) == primera
    # A los veinte sí, y el sello es lo único que cambia: la página no se recarga por eso.
    latido = MOMENTO + timedelta(minutes=20)
    segunda = _generar(armado_vivo, tmp_path, latido)
    assert segunda["generado"] == latido.isoformat() and segunda["firma"] == primera["firma"]
    assert (tmp_path / "index.html").read_bytes() == html


def test_un_partido_pospuesto_no_da_latidos_para_siempre(armado, tmp_path: Path):
    armado_viejo = _en_curso(armado, MOMENTO - timedelta(hours=30))
    primera = _generar(armado_viejo, tmp_path)
    assert _generar(armado_viejo, tmp_path, MOMENTO + timedelta(hours=1)) == primera


def test_un_sello_viejo_sin_firma_obliga_a_publicar(armado, tmp_path: Path):
    _generar(armado, tmp_path)
    (tmp_path / "version.json").write_text('{"generado": "2026-09-20T10:00:00-06:00", "version": "v0.21.0"}\n', encoding="utf-8")
    (tmp_path / "index.html").write_text("vieja", encoding="utf-8")
    sello = _generar(armado, tmp_path, MOMENTO + timedelta(minutes=1))
    assert sello["firma"] and (tmp_path / "index.html").read_text(encoding="utf-8") != "vieja"


# --- la hora por definir ----------------------------------------------------------

# Lo que trae ESPN de la semana 16 de 2026: las 05:00 UTC del domingo, sábado 23:00 en CDMX.
_RELLENO = datetime(2026, 12, 27, 5, tzinfo=timezone.utc)


def _por_definir(visitante: str = "Buccaneers", local: str = "Falcons") -> Partido:
    return Partido(visitante, local, 0, 0, None, False, "Scheduled", _RELLENO, hora_definida=False)


def test_un_partido_sin_hora_no_publica_el_relleno():
    from quiniela.render_html import _describir

    d = _describir(_por_definir())
    assert (d["e"], d["grupo"], d["t"]) == ("Hora por definir", "Hora por definir", 0)
    assert "23:00" not in json.dumps(d)


def test_las_tandas_de_navidad_con_partidos_sin_hora():
    """Los domingos por definir son del domingo, no del "sábado 23:00" que parecían."""
    from quiniela.render_html import _tandas

    def juego(visitante, local, *cuando):
        return Partido(visitante, local, 0, 0, None, False, "Scheduled", datetime(*cuando, tzinfo=timezone.utc))

    tandas = _tandas([
        juego("Texans", "Eagles", 2026, 12, 25, 1, 15),      # jueves 24, 19:15 CDMX
        juego("Packers", "Bears", 2026, 12, 25, 18, 0),      # viernes 25
        _por_definir(),
        _por_definir("Bengals", "Colts"),
        juego("Chargers", "Dolphins", 2026, 12, 27, 18, 0),  # domingo 27
        juego("Giants", "Lions", 2026, 12, 29, 1, 15),       # lunes 28
    ])
    assert [t["claves"] for t in tandas] == [
        ["Texans@Eagles", "Packers@Bears"],
        # Los que no tienen hora, al final de su tanda.
        ["Chargers@Dolphins", "Giants@Lions", "Buccaneers@Falcons", "Bengals@Colts"],
    ]
    assert tandas[0]["cierre_texto"] == "miércoles 23 de dic a las 23:59"
    # El domingo manda: no el relleno, que habría cerrado el viernes.
    assert tandas[1]["cierre_texto"] == "sábado 26 de dic a las 23:59"
    assert tandas[1]["cierre"] == "2026-12-26T23:59:00-06:00"


def test_si_ningun_partido_tiene_hora_el_cierre_es_por_confirmar():
    """La semana 18 sale completa por definir hasta casi el final."""
    from quiniela.render_html import _tandas

    relleno = datetime(2027, 1, 10, 5, tzinfo=timezone.utc)
    tandas = _tandas([
        Partido("Jets", "Bills", 0, 0, None, False, "Scheduled", relleno, hora_definida=False),
        Partido("Browns", "Bengals", 0, 0, None, False, "Scheduled", relleno, hora_definida=False),
    ])
    assert len(tandas) == 1
    assert tandas[0]["cierre_texto"] == "sábado 9 de ene a las 23:59 (por confirmar)"


def test_los_partidos_sin_hora_van_al_final_de_la_semana():
    from quiniela.render_html import _orden_nfl

    domingo = datetime(2026, 12, 27, 18, tzinfo=timezone.utc)
    partidos = [_por_definir(), Partido("Chargers", "Dolphins", estado="Scheduled", inicio=domingo)]
    assert _orden_nfl(partidos) == [1, 0]


def test_el_navegador_tampoco_ordena_ni_pisa_lo_que_no_tiene_hora(armado, tmp_path: Path):
    html = render(armado, tmp_path)
    assert "(a.p.t || Infinity) - (b.p.t || Infinity)" in _funcion(html, "panelPartidos")
    assert 'crudo === "Scheduled" ? null' in _funcion(html, "parsearVivo")


# --- la vista previa y las imágenes -----------------------------------------------


def test_la_vista_previa_dice_quien_va_primero_y_como_va_la_semana():
    import pandas as pd

    from quiniela.render_html import descripcion_de_portada

    def tabla(*filas):
        return pd.DataFrame(filas, columns=["posicion", "participante", "acumulado"])

    uno = tabla((1, "Carlos Rodriguez", 69), (2, "Ana", 68))
    assert descripcion_de_portada(uno, 8, 1, 14) == (
        "Va en primero Carlos Rodriguez con 69 aciertos. Semana 8: 1 de 14 partidos jugados."
    )
    assert descripcion_de_portada(uno, 7, 16, 16) == "Va en primero Carlos Rodriguez con 69 aciertos. Semana 7 cerrada."
    dos = tabla((1, "Ana", 69), (1, "Beto", 69), (3, "Caro", 60))
    assert descripcion_de_portada(dos, 8, 0, 14).startswith("Van en primero Ana y Beto con 69 aciertos.")
    tres = tabla((1, "Ana", 69), (1, "Beto", 69), (1, "Caro", 69))
    assert descripcion_de_portada(tres, 8, 0, 14).startswith("Van en primero 3 empatados con 69 aciertos.")
    assert descripcion_de_portada(tabla((1, "Ana", 1)), 1, 1, 16).startswith("Va en primero Ana con 1 acierto.")
    assert descripcion_de_portada(tabla(), 1, 0, 16) == "Semana 1: 0 de 16 partidos jugados."


def test_la_vista_previa_sale_de_la_tabla_publicada(armado, tmp_path: Path):
    """La misma semana de la portada: la última con picks, no la que falta por cargar."""
    from quiniela.render_html import descripcion_de_portada

    semanas, general = armado
    assert not semanas[-1].picks   # la que trae el armado al final todavía no tiene hoja
    jugada = [s for s in semanas if s.picks][-1]
    esperado = descripcion_de_portada(general, jugada.numero, jugada.cerrados, jugada.total)
    assert f'<meta property="og:description" content="{esperado}">' in render(armado, tmp_path)
    assert f"Semana {jugada.numero}" in esperado and f"Semana {semanas[-1].numero}" not in esperado


def test_un_nombre_con_codigo_no_se_cuela_en_la_vista_previa(armado, tmp_path: Path):
    semanas, general = armado
    general = general.copy()
    general["posicion"] = range(1, len(general) + 1)
    general.loc[general.index[0], "participante"] = '"><script>alert(1)</script>'
    html = render((semanas, general), tmp_path)
    descripcion = re.search(r'property="og:description" content="([^"]*)"', html).group(1)
    assert "<script" not in descripcion and "&lt;script&gt;" in descripcion


def test_la_vista_previa_lleva_direcciones_completas(armado, tmp_path: Path):
    """Sin dirección completa WhatsApp no encuentra la imagen."""
    from quiniela.render_html import TAMANO_PORTADA

    html = render(armado, tmp_path)
    sello = json.loads((tmp_path / "version.json").read_text(encoding="utf-8"))
    assert '<meta property="og:url" content="https://vegeeks.github.io/angabave/">' in html
    assert f'<meta property="og:image" content="https://vegeeks.github.io/angabave/portada.png?v={sello["firma"]}">' in html
    assert f'<meta property="og:image:width" content="{TAMANO_PORTADA[0]}">' in html
    assert f'<meta property="og:image:height" content="{TAMANO_PORTADA[1]}">' in html
    # Y antes de la tipografía y el CSS: algunos lectores solo ven el principio.
    assert html.index('property="og:image"') < html.index("<style>")


def test_la_portada_mide_lo_que_declara_la_pagina(armado, tmp_path: Path):
    from quiniela.render_html import TAMANO_PORTADA
    from quiniela.render_png import generar_portada

    _, general = armado
    ruta = generar_portada(tabla_acumulada=general, semana=2, anio=2026, cerrados=1, total_partidos=16,
                           ruta_salida=tmp_path / "portada.png")
    with Image.open(ruta) as imagen:
        assert imagen.size == TAMANO_PORTADA
    assert ruta.stat().st_size < 300 * 1024   # WhatsApp no muestra las muy pesadas


def test_lo_que_dicen_las_imagenes_de_la_semana():
    from quiniela.render_html import como_va_la_semana
    from quiniela.render_png import titulo_ganadores

    assert como_va_la_semana(8, 1, 14) == ("Semana 8", "1 de 14 partidos jugados")
    assert como_va_la_semana(8, 0, 14) == ("Semana 8", "0 de 14 partidos jugados")
    assert como_va_la_semana(7, 14, 14) == ("Semana 7 cerrada", "14 partidos jugados")
    assert titulo_ganadores(7, 1, True) == "Ganó la semana 7"
    assert titulo_ganadores(7, 2, True) == "Ganaron la semana 7"
    assert titulo_ganadores(8, 1, False) == "Va ganando la semana 8"
    assert titulo_ganadores(8, 3, False) == "Van ganando la semana 8"


def test_quien_va_arriba_en_la_portada():
    import pandas as pd

    from quiniela.render_html import quien_va_primero

    def tabla(*filas):
        return pd.DataFrame(filas, columns=["posicion", "participante", "acumulado"])

    assert quien_va_primero(tabla((1, "Ana", 69), (2, "Beto", 68))) == (["Ana"], "va", "con 69 aciertos")
    assert quien_va_primero(tabla((1, "Ana", 69), (1, "Beto", 69))) == (["Ana", "Beto"], "van", "con 69 aciertos")
    assert quien_va_primero(tabla((1, "Ana", 69), (1, "Beto", 69), (1, "Caro", 69))) == (["3 empatados"], "van", "con 69 aciertos")
    assert quien_va_primero(tabla((1, "Ana", 1))) == (["Ana"], "va", "con 1 acierto")
    assert quien_va_primero(tabla()) == ([], "", "")


def _tabla_de_prueba(*primeros, resto: int = 33):
    """Una general con esos en primero y otros de relleno atrás, nombres largos incluidos."""
    import pandas as pd

    filas = [{"posicion": 1, "participante": n, "acumulado": 69, "errores": 40} for n in primeros]
    for i in range(resto):
        filas.append({"posicion": len(primeros) + i + 1, "participante": f"Chucho el Destructor {i:02d}", "acumulado": 60 - i // 4, "errores": 49})
    return pd.DataFrame(filas)


def _letra_fuera(imagen, de_x: int, a_x: int, linea: tuple[int, int]) -> bool:
    """¿Hay algo claro a los lados de esas columnas, sin contar la línea amarilla?"""
    gris = imagen.convert("L")
    ImageDraw.Draw(gris).rectangle([0, linea[0], gris.width, linea[1]], fill=0)
    lados = (gris.crop((0, 0, de_x, gris.height)), gris.crop((a_x, 0, gris.width, gris.height)))
    return max(lado.getextrema()[1] for lado in lados) > 90


@pytest.mark.parametrize("primeros", [
    ["Chucho el Destructor"],
    ["Ana", "Beto"],
    ["Chucho el Destructor", "Chilangos Norteños"],
    ["Ana", "Beto", "Caro"],
    ["Un Nombre Larguísimo Que Nadie Tendría En Una Quiniela De Verdad"],
])
@pytest.mark.parametrize("cerrados", [1, 14])
def test_en_la_portada_nada_se_sale_del_cuadrado_central(tmp_path: Path, primeros, cerrados):
    """Hay chats que la recortan de x=285 a x=915: fuera solo va la línea amarilla."""
    from quiniela.render_png import generar_portada

    ruta = generar_portada(tabla_acumulada=_tabla_de_prueba(*primeros), semana=8, anio=2026, cerrados=cerrados,
                           total_partidos=14, ruta_salida=tmp_path / "portada.png")
    with Image.open(ruta) as imagen:
        assert not _letra_fuera(imagen, 285, 915, (312, 317))
        # La línea sí va de orilla a orilla.
        assert imagen.convert("RGB").getpixel((0, 314)) == imagen.convert("RGB").getpixel((1199, 314)) == (255, 214, 10)
    assert ruta.stat().st_size < 300 * 1024


@pytest.mark.parametrize("ganadores", [
    ["Chucho el Destructor"],
    ["Chucho el Destructor", "Chilangos Norteños"],
    ["Chucho el Destructor", "Chilangos Norteños", "Karla Villasister"],
    ["Chucho el Destructor", "Chilangos Norteños", "Karla Villasister", "Leo Villavicencio", "Patrizio Di Toma", "Valentin Esparza"],
])
def test_en_la_tabla_nada_se_sale_de_sus_margenes(tmp_path: Path, ganadores):
    from quiniela.render_png import ANCHO, MARGEN

    ruta = generar_png(tabla_acumulada=_tabla_de_prueba("Chucho el Destructor"), semana=8, anio=2026, cerrados=9,
                       total_partidos=14, ruta_salida=tmp_path / "tabla.png", momento=MOMENTO,
                       ganadores=ganadores, premio="$1,733.33", oficial=True, semana_ganadores=7)
    with Image.open(ruta) as imagen:
        assert not _letra_fuera(imagen, MARGEN, ANCHO - MARGEN, (112, 115))
    assert ruta.stat().st_size < 300 * 1024


def test_la_tabla_es_de_ahora_sin_verde_ni_rojo_ni_columna_de_fallos(tmp_path: Path):
    """Los aciertos ya no compiten en color: el único color es la línea, el dinero y la medalla."""
    from quiniela.render_html import SEMANTICOS

    ruta = generar_png(tabla_acumulada=_tabla_de_prueba("Ana"), semana=8, anio=2026, cerrados=1, total_partidos=14,
                       ruta_salida=tmp_path / "tabla.png", momento=MOMENTO,
                       ganadores=["Ana"], premio="$5,200", oficial=True, semana_ganadores=7)
    with Image.open(ruta) as imagen:
        colores = {color for _, color in imagen.convert("RGB").getcolors(maxcolors=1 << 20)}
    for cual in ("verde", "rojo"):
        hexa = SEMANTICOS[cual]
        assert tuple(int(hexa[i:i + 2], 16) for i in (1, 3, 5)) not in colores, cual


def test_las_imagenes_salen_con_cualquier_fuente(tmp_path: Path, monkeypatch):
    """Arial en la Mac, Liberation en el runner y, sin ninguna, la que trae Pillow."""
    from quiniela import render_png

    for estilo in ("normal", "negrita"):
        rutas = render_png._FUENTES[estilo]
        assert "Arial" in rutas[0]
        assert [i for i, r in enumerate(rutas) if "Liberation" in r] < [i for i, r in enumerate(rutas) if "DejaVu" in r]

    monkeypatch.setattr(render_png, "_FUENTES", {"normal": ["/no/existe.ttf"], "negrita": ["/no/existe.ttf"]})
    render_png._fuente.cache_clear()
    try:
        tabla = _tabla_de_prueba("Chucho el Destructor", "Chilangos Norteños")
        portada = render_png.generar_portada(tabla_acumulada=tabla, semana=8, anio=2026, cerrados=1, total_partidos=14,
                                             ruta_salida=tmp_path / "portada.png")
        png = generar_png(tabla_acumulada=tabla, semana=8, anio=2026, cerrados=1, total_partidos=14,
                          ruta_salida=tmp_path / "tabla.png", momento=MOMENTO, ganadores=["Ana"], premio="$5,200", oficial=True)
        with Image.open(portada) as imagen:
            assert not _letra_fuera(imagen, 285, 915, (312, 317))
        assert png.exists()
    finally:
        render_png._fuente.cache_clear()


def test_la_imagen_solo_lleva_medalla_en_los_tres_primeros_lugares(tmp_path: Path):
    """Del 4º en adelante nadie cobra, y un 6º no puede salir en bronce."""
    from quiniela.render_png import COLOR_MEDALLA, FONDO, _fila, _rgb

    def lienzo_con(posicion: int):
        lienzo = Image.new("RGBA", (500, 66), _rgb(FONDO) + (255,))
        _fila(lienzo, (0, 4, 500, 60), {"posicion": posicion, "participante": "Ana", "acumulado": 60})
        return lienzo

    # El disco de la medalla: se mira a la izquierda de la cifra, en su renglón de en medio.
    for posicion, cual in ((1, "oro"), (2, "plata"), (3, "bronce")):
        assert lienzo_con(posicion).getpixel((4, 32))[:3] == _rgb(COLOR_MEDALLA[cual])
    for posicion in (4, 6, 11):
        assert lienzo_con(posicion).getpixel((4, 32))[:3] == _rgb(FONDO), posicion   # sin disco: el piso


def test_la_franja_acomoda_a_los_empatados(tmp_path: Path):
    from quiniela.render_png import _fuente, _renglones

    fuente = _fuente("negrita", 25)
    nombres = ["Luis Toledano", "Tristan Mejia"]
    assert _renglones(nombres, fuente, 900) == ["Luis Toledano · Tristan Mejia"]
    assert _renglones(nombres, fuente, 240) == ["Luis Toledano", "Tristan Mejia"]
    # Si ni en dos renglones caben, se cuentan.
    assert _renglones(nombres * 10, fuente, 300) is None


def test_tocar_el_campo_alterna_equipo_y_nombre():
    from pathlib import Path
    plantilla = (Path(__file__).resolve().parent.parent / "quiniela/plantillas/index.html.j2").read_text()
    assert '(equipo && alterno ? equipo : mio || equipo)' in plantilla
    assert 'e.target.closest("a,button,select,input,textarea,summary,label,.hoja-fondo")' in plantilla


def test_el_campo_responde_al_partido_de_tu_equipo():
    from pathlib import Path
    plantilla = (Path(__file__).resolve().parent.parent / "quiniela/plantillas/index.html.j2").read_text()
    for estado in ("gano", "perdio", "juega"):
        assert f"html[data-campo={estado}] .cp-palabra" in plantilla
    assert "function ultimoJuegoDeMiEquipo()" in plantilla


# --- v0.29: tu dinero ---------------------------------------------------------------


def test_el_json_lleva_lo_cobrado_y_su_texto(armado, tmp_path: Path):
    premios = datos_embebidos(render(armado, tmp_path))["premios"]
    assert len(premios["cobrado"]) == len(premios["cobrado_texto"]) == 4
    for centavos, texto in zip(premios["cobrado"], premios["cobrado_texto"]):
        assert (texto == "") == (centavos == 0)
        assert "$0" not in texto.replace("$0.", "") or centavos > 0


def test_cada_fila_de_la_general_dice_de_quien_es(armado, tmp_path: Path):
    html = render(armado, tmp_path)
    datos = datos_embebidos(html)
    cuerpo = re.search(r"<tbody>(.*?)</tbody>", html, re.S).group(1)
    filas = re.findall(r'<tr data-p="(\d+)"', cuerpo)
    assert [int(p) for p in filas] == [f["p"] for f in datos["general"]]
    # El script empareja por data-p, no por posición.
    marcar = _funcion(html, "marcarFilasPropias")
    assert "tr[data-p]" in marcar and "D.general[i]" not in marcar and "children[1].textContent" not in marcar


def test_la_ficha_no_enseña_dinero_en_cero(armado, tmp_path: Path):
    html = render(armado, tmp_path)
    assert '"$0"' not in html and "$0 " not in _funcion(html, "perfil")
    ficha = _funcion(html, "perfil")
    assert "dineroCobrado(idx)" in ficha and "if (ganado)" in ficha
    assert "> 0 && texto" in _funcion(html, "dineroCobrado")


def test_la_raya_de_cobro_cae_tras_el_ultimo_lugar_que_cobra(armado, tmp_path: Path, monkeypatch):
    monkeypatch.setattr("quiniela.render_html.UMBRAL_PODIO", 1)
    html = render(armado, tmp_path)
    datos = datos_embebidos(html)
    cobran = {g["pos"] for g in datos["premios"]["hoy"]}
    esperado = max(i for i, f in enumerate(datos["general"]) if f["pos"] in cobran)
    cuerpo = re.search(r"<tbody>(.*?)</tbody>", html, re.S).group(1)
    filas = re.findall(r'<tr data-p="\d+" class="[^"]*"|<tr class="corte-fila">', cuerpo)
    assert filas.count('<tr class="corte-fila">') == 1
    assert filas.index('<tr class="corte-fila">') == esperado + 1
    assert "corte-tras" in filas[esperado]


def test_la_general_pinta_el_dato_de_cada_quien(armado, tmp_path: Path, monkeypatch):
    monkeypatch.setattr("quiniela.render_html.UMBRAL_PODIO", 1)
    html = render(armado, tmp_path)
    assert re.search(r"<h1>(<span class=\"palabra\"><i style=\"--k:\d+\">[^<]+</i></span> ?)+</h1>", html)
    for texto in ("Tabla general", "Vas en la punta", "Empatas en la punta", "Cada punto es uno de los",
                  "Si terminara hoy, cobran hasta aquí", "Si terminara hoy: ", "campo-gral-pasto"):
        assert texto in html, texto
    assert "tuRebanada" not in html and "temporada es joven" not in html
    assert "La rebanada del pastel" not in html and "Cómo se reparte" in html


# ─── v0.31: se siente como app ──────────────────────────────────────────────

def test_el_manifiesto_trae_id_y_accesos_directos(tmp_path: Path):
    from quiniela.render_html import generar_manifiesto
    ruta = generar_manifiesto(tmp_path / "manifest.webmanifest")
    manifiesto = json.loads(ruta.read_text(encoding="utf-8"))
    assert manifiesto["id"] == "/angabave/"
    assert manifiesto["categories"] == ["sports"]
    assert manifiesto["description"]
    accesos = {a["name"]: a["url"] for a in manifiesto["shortcuts"]}
    assert accesos == {"Armar mis picks": "./#picks", "Hoy": "./#hoy",
                       "Semana en curso": "./#semana", "Tabla general": "./#general"}
    assert all(a["icons"][0]["src"] == "icono-192.png" for a in manifiesto["shortcuts"])


def test_el_enlace_al_manifiesto_solo_se_escribe_fuera_de_ios(armado, tmp_path: Path):
    html = render(armado, tmp_path)
    assert '<html lang="es-MX">' in html
    assert '<link rel="manifest"' not in re.sub(r"<script>.*?</script>", "", html, flags=re.S)
    arranque = _arranque(html)
    assert 'href="manifest.webmanifest"' in arranque
    assert "iP(hone|od|ad)" in arranque and "document.write" in arranque


def test_el_nombre_del_enlace_solo_se_aplica_en_la_app_guardada(armado, tmp_path: Path):
    html = render(armado, tmp_path)
    cuerpo = _funcion(html, "aplicarInvitacion")
    assert cuerpo.index("enAppGuardada()") < cuerpo.index("URLSearchParams")
    assert "D.participantes.includes(quien)" in cuerpo
    assert "D.colores[eq]" in cuerpo
    assert 'leer("angabave.jugador") === null' in cuerpo
    assert "navigator.standalone === true" in _funcion(html, "enAppGuardada")
    # Y se aplica antes de leer la memoria.
    assert html.index("  aplicarInvitacion();\n  montarSoy();") > 0
    # Abrir desde el ícono arranca en Hoy.
    assert 'tipoDeCarga === "navigate"' in html


def test_las_direcciones_nuevas_se_leen(armado, tmp_path: Path):
    html = render(armado, tmp_path)
    cuerpo = _funcion(html, "leerDireccion")
    assert '"#semana"' in cuerpo
    assert "PESTANAS.some" in cuerpo and 'split("@")' in cuerpo
    assert "partido: { v, l }" in cuerpo
    assert 'const PESTANAS = [["partidos", "Partidos"], ["tabla", "Tabla"]' in html
    assert '"escenarios"' in html
    # Cambiar de pestaña reemplaza la entrada del historial, no agrega otra.
    assert 'history.replaceState(estadoActual(), "", direccionDe(vistaActual));\n        moverCorredera' in html


def test_cada_hoja_tiene_su_boton_de_cerrar(armado, tmp_path: Path):
    html = render(armado, tmp_path)
    cuerpo = _funcion(html, "abrirHoja")
    assert 'crear("button", "hoja-cerrar", "×")' in cuerpo
    assert 'setAttribute("aria-label", "Cerrar")' in cuerpo
    assert 'closest(".hoja-cerrar, .hoja-compartir")' in cuerpo
    assert "fondoInerte(true)" in cuerpo and "fondoInerte(false)" in cuerpo
    assert "hoja.tabIndex = -1" in cuerpo
    # Una hoja sobre otra toma la entrada del historial.
    assert "history.replaceState(entrada" in cuerpo
    assert "contenido.parentNode === hoja" in cuerpo
    # Los dos "cerrar y navegar" pasan por una sola salida.
    assert html.count("salirDeHojaA(") == 3      # la definición y los dos usos
    assert "if (estado.hoja) return;" not in html
    css = dict(_reglas(html))
    assert "width:44px" in css[".hoja-cerrar,.hoja-compartir"] and "height:44px" in css[".hoja-cerrar,.hoja-compartir"]


def test_compartir_y_el_aviso_de_enlace_copiado(armado, tmp_path: Path):
    html = render(armado, tmp_path)
    cuerpo = _funcion(html, "compartir")
    assert "navigator.share({ title: D.marca, text: texto, url })" in cuerpo
    assert 'e.name === "AbortError"' in cuerpo
    assert 'avisoFlotante("Enlace copiado")' in cuerpo
    assert html.count('setAttribute("aria-label", "Compartir")') == 2    # la hoja del partido y la ficha


def test_la_barra_de_abajo_usa_aria_current(armado, tmp_path: Path):
    html = render(armado, tmp_path)
    botones = re.findall(r'<button type="button" data-vista="\w+"[^>]*>', html)
    assert len(botones) >= 5 and not any("aria-selected" in b for b in botones)
    assert '.navegacion button[aria-current="page"]' in html
    assert 'b.setAttribute("aria-current", "page")' in html
    # Las pestañas internas sí son pestañas.
    assert 'setAttribute("role", "tabpanel")' in html and 'setAttribute("aria-controls", "panel-semana")' in html
    assert '"ArrowRight"' in html and '"ArrowLeft"' in html
    # .sin-anillo es solo para el foco que regresa por programa tras un toque; con teclado sí hay anillo.
    assert "outline:0" not in "".join(d for s, d in _reglas(html)
                                      if ":focus" in s and "tabindex" not in s and ".hoja" not in s and ".sin-anillo" not in s)
    assert "if (!conTeclado)" in html
