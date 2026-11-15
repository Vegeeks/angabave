"""Que el portal abra con datos celulares: la copia guardada (sw.js), la recarga que no deja la
pantalla en negro, el rescate que reintenta solo y el arranque que se nota."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from .test_render import _funcion, _rescate, armado, render  # noqa: F401  (armado es un fixture)

hay_node = pytest.mark.skipif(shutil.which("node") is None, reason="hace falta node")


# --- lo que se publica ---------------------------------------------------------------


def test_se_publica_la_copia_guardada(armado, tmp_path: Path):
    from quiniela.render_html import CAJA_COPIA, ESPERA_COPIA_MS

    render(armado, tmp_path)
    sw = (tmp_path / "sw.js").read_text(encoding="utf-8")
    assert sw.startswith('"use strict";')
    assert f'const CAJA = "{CAJA_COPIA}";' in sw and f"const ESPERA = {ESPERA_COPIA_MS};" in sw
    assert "{{" not in sw and "{%" not in sw
    # Solo la página del portal y solo cuando se navega a ella.
    assert 'pedido.mode !== "navigate"' in sw and "!esPortal(pedido.url)" in sw
    assert 'const PAGINAS = [RAIZ, RAIZ + "index.html"];' in sw
    for ajeno in ("cargar.html", "red.html", "version.json", "espn"):
        assert ajeno not in sw.lower(), ajeno
    # Nada cortado ni más viejo que la copia.
    assert "texto.indexOf(FIN) > 0 && /<\\/html>\\s*$/.test(texto)" in sw
    assert "momento(previa.texto) > momento(texto)" in sw
    assert '<html data-copia="' in sw


def test_la_pagina_trae_lo_que_la_copia_necesita_para_guardarse(armado, tmp_path: Path):
    """Si algún día esto deja de cumplirse, sw.js no truena: deja de guardar copia sin avisar. Aquí sí avisa."""
    html = render(armado, tmp_path)
    assert len(html) > 20000 and re.search(r"</html>\s*$", html)
    assert "window.angabaveListo = true" in html
    assert re.match(r"<!doctype html>\s*<html\b", html, re.I)   # ahí entra data-copia
    datos = html[html.index('id="datos">'):]
    datos = datos[:datos.index("</script>")]
    assert re.search(r'"generado":"[^"]+"', datos) and re.search(r'"firma":"[0-9a-f]{16}"', datos)


def test_el_portal_registra_la_copia_sin_estorbar(armado, tmp_path: Path):
    html = render(armado, tmp_path)
    inicio = html.index('navigator.serviceWorker.register("sw.js", { scope: "./" })')
    tramo = html[html.rindex("try {", 0, inicio):html.index("} catch (e)", inicio)]
    assert '"serviceWorker" in navigator' in tramo
    assert 'window.addEventListener("load", () => setTimeout(registrar, 1500), { once: true })' in tramo
    assert ".catch(() => {})" in tramo
    # Se registra después de que la página arrancó, y no la puede tumbar.
    assert html.index("window.angabaveListo = true") > inicio


def test_apagar_la_copia_la_da_de_baja(armado, tmp_path: Path, monkeypatch):
    import quiniela.render_html as generador

    monkeypatch.setattr(generador, "TRABAJADOR", False)
    html = render(armado, tmp_path)
    sw = (tmp_path / "sw.js").read_text(encoding="utf-8")
    assert "self.registration.unregister()" in sw and "respondWith" not in sw
    assert 'register("sw.js"' not in html
    assert "navigator.serviceWorker.getRegistrations()" in html and 'c.indexOf("angabave-") === 0' in html


def test_la_recarga_baja_completa_antes_de_soltar_la_pagina(armado, tmp_path: Path):
    html = render(armado, tmp_path)
    recargar = _funcion(html, "recargarFresco")
    assert recargar.index("bajarCompleta(version)") < recargar.index("location.replace(destino)")
    # Mientras bajaba la persona pudo empezar algo: tampoco se le recarga.
    assert recargar.index(".hoja-fondo") < recargar.index("location.replace(destino)")
    assert "pendiente.falla < TRES_MIN" in recargar
    bajar = _funcion(html, "bajarCompleta")
    assert "/<\\/html>\\s*$/.test(texto)" in bajar and "'\"firma\":\"' + firma + '\"'" in bajar
    assert "trabajador.firma === firma" in bajar
    assert 'control.postMessage({ tipo: "precargar" }, [canal.port2])' in _funcion(html, "precargarConTrabajador")


def test_version_json_no_se_queda_colgado_y_confirma_la_red(armado, tmp_path: Path):
    html = render(armado, tmp_path)
    revisar = _funcion(html, "revisarVersion")
    assert "setTimeout(() => control.abort(), 20000)" in revisar and "signal: control.signal" in revisar
    assert revisar.index("hayRed(") < revisar.index("recargarFresco(")
    assert 'window.addEventListener("online", revisarVersion);' in html


def test_el_aviso_de_copia_es_honesto(armado, tmp_path: Path):
    html = render(armado, tmp_path)
    assert '<p class="sin-senal env oculto" id="sin-senal" role="status"></p>' in html
    pintar = _funcion(html, "pintarAvisoCopia")
    assert '"Sin señal."' in pintar and "Ves lo guardado en este teléfono" in pintar
    assert "Se pone al día solo en cuanto vuelva la red." in pintar
    assert "avisoCopia.textContent = \"\"" in pintar and "innerHTML" not in pintar
    # Solo si la red tampoco contesta en un momento; y se va cuando confirma que está al día.
    assert "if (enCopia) setTimeout(() => { if (!redConfirmada) pintarAvisoCopia(false); }, 2500);" in html
    assert 'if (alDia) avisoCopia.classList.add("oculto");' in _funcion(html, "hayRed")


def test_mientras_carga_se_nota(armado, tmp_path: Path):
    html = render(armado, tmp_path)
    assert ".arranque{display:none}" in html
    assert ".js:not(.listo) .arranque{display:block;" in html
    assert ".estreno .arranque{visibility:hidden}" in html
    regla = re.search(r"\.arranque-barra::after\{([^}]*)\}", html).group(1)
    assert "infinite" not in regla and "backwards" in regla
    assert "@media (prefers-reduced-motion:reduce){.arranque-barra::after{animation:none" in html
    arranque = html[html.index('<div class="arranque env"'):]
    script = arranque[arranque.index("<script>"):arranque.index("</script>")]
    for moderno in ("=>", "let ", "const ", "`", "?.", "??", "async ", "class "):
        assert moderno not in script, moderno
    assert "Tu señal va lenta. Ya casi…" in script
    # La llegada del estadio solo si la página está lista pronto.
    cabeza = html[:html.index("</head>")]
    assert "r.classList.remove('estreno')},2500)" in cabeza


def test_el_rescate_reintenta_una_vez_y_lleva_a_la_prueba(armado, tmp_path: Path):
    render(armado, tmp_path)
    for nombre in ("index.html", "cargar.html"):
        rescate = _rescate((tmp_path / nombre).read_text(encoding="utf-8"))
        assert '<a href="red.html"' in rescate and "Probar la conexión" in rescate
        assert 'sessionStorage.getItem("angabave.reintento")' in rescate and "ahora - antes < 120000" in rescate
        assert 'if (mostrado !== "fallo" && reintentar()) return;' in rescate
        assert "Tu señal va muy lenta" in rescate
        # La otra vuelta lleva ?r= nuevo y conserva lo que va después del #.
        assert '"r=" + new Date().getTime()' in rescate
    # Y al arrancar, el ?r= se quita de la dirección igual que el ?v= de la recarga automática.
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert 'const deRecarga = (q) => q.has("v") || q.has("r");' in html and 'q.delete("r");' in html


def test_la_prueba_de_conexion_ve_la_copia_y_las_paginas_cortadas(armado, tmp_path: Path):
    from quiniela.render_html import CAJA_COPIA

    render(armado, tmp_path)
    red = (tmp_path / "red.html").read_text(encoding="utf-8")
    assert f'caches.open("{CAJA_COPIA}")' in red and "Copia guardada en este teléfono" in red
    assert 'if (cortada) partes.push("llegó cortada");' in red


# --- el trabajador, corrido en node con una red de mentiras ------------------------------

ARNES = r"""
const fs = require("fs");
const vm = require("vm");
const fuente = fs.readFileSync(process.argv[2], "utf8").replace(/const ESPERA = \d+;/, "const ESPERA = 150;");
const RAIZ = "https://x.test/angabave/";
const CAJA = /const CAJA = "([^"]+)"/.exec(fuente)[1];

function pagina(generado, firma, cortar) {
  const texto = '<!doctype html>\n<html lang="es-MX">\n<head></head><body>' + "x".repeat(25000) +
    '<script type="application/json" id="datos">{"semanas":[],"generado":"' + generado + '","firma":"' + firma + '"}</script>' +
    "<script>(() => { window.angabaveListo = true; })();</script>\n</body>\n</html>\n";
  return cortar ? texto.slice(0, Math.floor(texto.length / 2)) : texto;
}
const VIEJA = pagina("2026-11-14T20:00:00.123456-06:00", "0000000000000000");
const COPIA = pagina("2026-11-14T23:48:02.859082-06:00", "aaaaaaaaaaaaaaaa");
const NUEVA = pagina("2026-11-15T09:10:00.000001-06:00", "bbbbbbbbbbbbbbbb");
const html = (texto, estado) => new Response(texto, { status: estado || 200, headers: { "Content-Type": "text/html" } });
const tarda = (ms, valor) => new Promise((listo) => setTimeout(() => listo(valor), ms));

function entorno(red, copia) {
  const almacen = new Map(), llamadas = [], oyentes = {};
  const caches = {
    async open(nombre) {
      if (!almacen.has(nombre)) almacen.set(nombre, new Map());
      const m = almacen.get(nombre);
      return {
        async match(url) { const r = m.get(String(url.url || url)); return r ? r.clone() : undefined; },
        async put(url, r) { m.set(String(url.url || url), r.clone()); },
      };
    },
    async keys() { return [...almacen.keys()]; },
    async delete(nombre) { return almacen.delete(nombre); },
  };
  const self = {
    registration: { scope: RAIZ, unregister: async () => true },
    addEventListener: (tipo, fn) => { oyentes[tipo] = fn; },
    skipWaiting: () => {},
    clients: { claim: async () => {} },
  };
  const fetchFalso = async (pedido) => { const url = String(pedido.url || pedido); llamadas.push(url); return red(url); };
  vm.runInContext(fuente, vm.createContext({ self, caches, fetch: fetchFalso, Request, Response, Headers, URL, setTimeout, clearTimeout, console }));
  const leer = async () => {
    const r = await (await caches.open(CAJA)).match(RAIZ);
    return r ? { texto: await r.text(), como: r.headers.get("X-Angabave-Como") } : null;
  };
  const sembrar = async (texto, como, hace) => (await caches.open(CAJA)).put(RAIZ, new Response(texto, { headers: {
    "X-Angabave-Guardada": String(Date.now() - (hace || 0)), "X-Angabave-Como": como || "red" } }));
  return { oyentes, llamadas, leer, sembrar, copia };
}

async function esperarTodo(esperas) {
  let vistos = -1;
  while (vistos !== esperas.length) { vistos = esperas.length; await Promise.allSettled(esperas.slice()); }
}

async function navegar(e, url, modo) {
  let respuesta = null;
  const esperas = [];
  e.oyentes.fetch({ request: { url, method: "GET", mode: modo || "navigate" }, respondWith: (p) => { respuesta = p; }, waitUntil: (p) => esperas.push(p) });
  if (!respuesta) return { atendida: false };
  const inicio = Date.now();
  const r = await respuesta;
  const ms = Date.now() - inicio;
  const texto = await r.text();
  await esperarTodo(esperas);
  const guardada = await e.leer();
  const firma = (/"firma":"([0-9a-f]+)"/.exec(texto) || [])[1] || null;
  return { atendida: true, ms, firma, marcada: texto.indexOf("data-copia=") >= 0, sinConexion: texto.indexOf("Sin conexión") >= 0,
           guardada: guardada && ((/"firma":"([0-9a-f]+)"/.exec(guardada.texto) || [])[1]), como: guardada && guardada.como };
}

const casos = {
  async sin_copia_con_red() { return navegar(entorno(async () => html(NUEVA)), RAIZ); },
  async sin_copia_sin_red() { return navegar(entorno(async () => { throw new TypeError("Load failed"); }), RAIZ + "?soy=Ana"); },
  async copia_y_red_buena() { const e = entorno(async () => html(NUEVA)); await e.sembrar(COPIA); return navegar(e, RAIZ); },
  async copia_y_red_lenta() { const e = entorno(() => tarda(600, html(NUEVA))); await e.sembrar(COPIA); return navegar(e, RAIZ + "index.html"); },
  async copia_y_sin_red() { const e = entorno(async () => { throw new TypeError("Load failed"); }); await e.sembrar(COPIA); return navegar(e, RAIZ + "?v=1#semana"); },
  async copia_y_red_cortada() { const e = entorno(async () => html(pagina("2026-11-15T09:10:00-06:00", "bbbbbbbbbbbbbbbb", true))); await e.sembrar(COPIA); return navegar(e, RAIZ); },
  async copia_y_error_del_servidor() { const e = entorno(async () => html("Service Unavailable", 503)); await e.sembrar(COPIA); return navegar(e, RAIZ); },
  async copia_y_nodo_atrasado() { const e = entorno(async () => html(VIEJA)); await e.sembrar(COPIA); return navegar(e, RAIZ); },
  async no_atiende_lo_demas() {
    const e = entorno(async () => html(NUEVA));
    const urls = [RAIZ + "cargar.html#k=x", RAIZ + "red.html", RAIZ + "version.json", RAIZ + "tabla.png", "https://otro.test/angabave/"];
    const salida = [];
    for (const u of urls) salida.push((await navegar(e, u)).atendida);
    salida.push((await navegar(e, RAIZ, "cors")).atendida);
    return { atendidas: salida, llamadas: e.llamadas.length };
  },
  async precarga_y_abre_sin_bajar_otra_vez() {
    const e = entorno(async () => html(NUEVA));
    await e.sembrar(COPIA);
    const esperas = [];
    let recibido = null;
    e.oyentes.message({ data: { tipo: "precargar" }, ports: [{ postMessage: (m) => { recibido = m; } }], waitUntil: (p) => esperas.push(p) });
    await esperarTodo(esperas);
    const pedidoPrecarga = e.llamadas.slice();
    const tras = await navegar(e, RAIZ + "?v=2");
    return { recibido, pedidoPrecarga, tras, llamadasTras: e.llamadas.length - pedidoPrecarga.length };
  },
  async precarga_vieja_ya_no_cuenta() {
    const e = entorno(async () => html(NUEVA));
    await e.sembrar(COPIA, "precarga", 120000);
    return navegar(e, RAIZ);
  },
  async instalacion_guarda_la_primera() {
    const e = entorno(async () => html(COPIA));
    const esperas = [];
    e.oyentes.install({ waitUntil: (p) => esperas.push(p) });
    await esperarTodo(esperas);
    const g = await e.leer();
    return { guardada: g && (/"firma":"([0-9a-f]+)"/.exec(g.texto) || [])[1], llamadas: e.llamadas };
  },
};

(async () => {
  const salida = {};
  for (const [nombre, caso] of Object.entries(casos)) salida[nombre] = await caso();
  console.log(JSON.stringify(salida));
  process.exit(0);   // sin esperar los relojes largos del trabajador (el de la instalación es de 30 s)
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def corrida(tmp_path_factory):
    """El trabajador no depende de los datos: se escribe y se corre una sola vez para todo el archivo."""
    if shutil.which("node") is None:
        pytest.skip("hace falta node")
    from quiniela.render_html import generar_trabajador

    carpeta = tmp_path_factory.mktemp("trabajador")
    generar_trabajador(carpeta / "sw.js")
    arnes = carpeta / "arnes.js"
    arnes.write_text(ARNES, encoding="utf-8")
    r = subprocess.run(["node", str(arnes), str(carpeta / "sw.js")], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@hay_node
def test_sin_copia_la_red_tal_cual_y_se_guarda(corrida):
    caso = corrida["sin_copia_con_red"]
    assert caso["firma"] == "b" * 16 and not caso["marcada"]
    assert caso["guardada"] == "b" * 16 and caso["como"] == "red"
    # Sin copia y sin red: una página clara, no la pantalla de error del navegador.
    assert corrida["sin_copia_sin_red"]["sinConexion"] is True


@hay_node
def test_con_red_buena_siempre_lo_recien_publicado(corrida):
    caso = corrida["copia_y_red_buena"]
    assert caso["firma"] == "b" * 16 and not caso["marcada"] and caso["guardada"] == "b" * 16


@hay_node
def test_con_red_lenta_abre_la_copia_a_tiempo_y_guarda_la_nueva_para_despues(corrida):
    caso = corrida["copia_y_red_lenta"]
    assert caso["firma"] == "a" * 16 and caso["marcada"]
    assert 100 <= caso["ms"] < 500       # la espera, no lo que tarda la red
    assert caso["guardada"] == "b" * 16


@hay_node
def test_sin_red_la_copia_al_instante(corrida):
    caso = corrida["copia_y_sin_red"]
    assert caso["firma"] == "a" * 16 and caso["marcada"] and caso["ms"] < 100
    caso = corrida["copia_y_error_del_servidor"]
    assert caso["firma"] == "a" * 16 and caso["marcada"] and caso["guardada"] == "a" * 16


@hay_node
def test_una_pagina_cortada_ni_se_abre_ni_se_guarda(corrida):
    caso = corrida["copia_y_red_cortada"]
    assert caso["firma"] == "a" * 16 and caso["marcada"] and caso["guardada"] == "a" * 16


@hay_node
def test_un_nodo_atrasado_no_regresa_la_version_anterior(corrida):
    caso = corrida["copia_y_nodo_atrasado"]
    assert caso["firma"] == "a" * 16 and not caso["marcada"]   # la red sí contestó: no es "sin señal"
    assert caso["guardada"] == "a" * 16


@hay_node
def test_solo_atiende_la_pagina_del_portal(corrida):
    caso = corrida["no_atiende_lo_demas"]
    assert caso["atendidas"] == [False] * 6 and caso["llamadas"] == 0


@hay_node
def test_la_precarga_deja_lista_la_nueva_y_se_abre_sin_bajarla_otra_vez(corrida):
    caso = corrida["precarga_y_abre_sin_bajar_otra_vez"]
    assert caso["recibido"] == {"ok": True, "firma": "b" * 16}
    assert len(caso["pedidoPrecarga"]) == 1 and "?v=" in caso["pedidoPrecarga"][0]
    assert caso["llamadasTras"] == 0
    assert caso["tras"]["firma"] == "b" * 16 and not caso["tras"]["marcada"]
    # Pasado un minuto la precarga ya no se salta la red.
    vieja = corrida["precarga_vieja_ya_no_cuenta"]
    assert vieja["firma"] == "b" * 16 and vieja["como"] == "red"


@hay_node
def test_al_instalarse_guarda_la_pagina_que_se_acaba_de_ver(corrida):
    caso = corrida["instalacion_guarda_la_primera"]
    assert caso["guardada"] == "a" * 16 and caso["llamadas"] == ["https://x.test/angabave/"]
