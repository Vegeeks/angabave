"""Pruebas de las dos salidas: la página y la imagen."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from PIL import Image

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


def test_la_unica_direccion_externa_es_la_de_los_marcadores(armado, tmp_path: Path):
    """El resto de los enlaces son archivos propios (iconos, manifiesto)."""
    html = render(armado, tmp_path)
    externas = set(re.findall(r"https?://[^\s\"'<>]+", html))
    # El espacio de nombres de SVG es un identificador, no una petición de red.
    externas.discard("http://www.w3.org/2000/svg")
    assert externas == {"https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"}
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


def test_la_semana_sin_picks_se_marca_como_pendiente(armado, tmp_path: Path):
    html = render(armado, tmp_path)
    datos = datos_embebidos(html)
    semana3 = datos["semanas"][1]
    assert semana3["estado"] == "pendiente"
    assert semana3["jugadores"] == []
    assert len(semana3["partidos"]) == 2
    assert "Actualizando la semana " in html


def test_las_semanas_jugadas_quedan_navegables(armado, tmp_path: Path):
    html = render(armado, tmp_path)
    assert 'data-vista="2"' in html
    assert 'data-vista="3"' in html
    assert 'data-vista="general"' in html


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
    assert "Tu pick" in html                 # marca en cada partido


def test_la_semana_en_curso_queda_destacada(armado, tmp_path: Path):
    html = render(armado, tmp_path)
    datos = datos_embebidos(html)
    assert datos["activa"] == 2
    # La pastilla de la semana activa lleva su marca.
    assert 'data-vista="2"' in html and 'class="actual"' in html


def test_la_tipografia_viaja_dentro_del_html(armado, tmp_path: Path):
    """La fuente va incrustada: el sitio no pide un solo archivo de afuera."""
    html = render(armado, tmp_path)
    assert "@font-face" in html
    assert "src:url(data:font/woff2;base64," in html
    # Y sigue sin haber más direcciones externas que la de los marcadores.
    externas = set(re.findall(r"https?://[^\s\"'<>]+", html))
    externas.discard("http://www.w3.org/2000/svg")
    assert externas == {"https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"}


def test_la_fuente_solo_se_usa_en_mayusculas_y_cifras(armado, tmp_path: Path):
    """Los nombres llevan minúsculas: si usaran la recortada, se partirían."""
    html = render(armado, tmp_path)
    reglas = re.findall(r"([^{}]+)\{[^{}]*var\(--rotulo\)[^{}]*\}", html)
    selectores = " ".join(reglas)
    for nombres in (".c-nombre", ".lugar .quien", ".campeon .nombres", ".ficha .quien"):
        assert nombres not in selectores


def test_la_invitacion_de_primera_visita_existe(armado, tmp_path: Path):
    html = render(armado, tmp_path)
    assert "Primera vez por aquí" in html
    assert "angabave.invitado" in html       # se recuerda que ya la vio


def test_hay_animacion_para_los_cambios_de_marcador(armado, tmp_path: Path):
    html = render(armado, tmp_path)
    assert "@keyframes anotacion" in html
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
    assert "Arma tu quiniela y mándala" in html
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
