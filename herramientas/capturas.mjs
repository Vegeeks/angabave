#!/usr/bin/env node
/* Fotos reales del portal, pantalla por pantalla, en un Chrome sin ventana.

     node herramientas/capturas.mjs --sitio <carpeta> --salida <carpeta> [--solo texto] [--filmar]

   Toma cada vista a tamaño de teléfono (y algunas a 320 px y en computadora), con
   y sin nombre elegido, con los momentos de herramientas/momentos.py si están en
   <sitio>/momentos, y deja en <salida>/reporte.json lo que se puede medir: errores
   de consola, desbordes a lo ancho, letra de menos de 12 px y botones de menos de
   44 px. Con --filmar guarda además cuadros de las animaciones de entrada y de un
   cambio de sección, para revisar el movimiento.

   También toma cargar.html y red.html. Ahí la función de carga y ESPN van simulados:
   estas fotos nunca le pegan a los de verdad ni necesitan una llave real.

   No usa dependencias: solo Node y el Chrome ya instalado. Nada de esto se publica. */

import { spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync, readFileSync, existsSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { extname, join, normalize } from "node:path";

const CHROME = process.env.CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const TELEFONO = { width: 390, height: 844, deviceScaleFactor: 2, mobile: true };
const CHICO = { width: 320, height: 640, deviceScaleFactor: 2, mobile: true };
const COMPU = { width: 1280, height: 800, deviceScaleFactor: 1, mobile: false };
const YO = "Angel D Luffy";

const opcion = (nombre, porOmision) => {
  const i = process.argv.indexOf("--" + nombre);
  return i >= 0 ? process.argv[i + 1] : porOmision;
};
const sitio = opcion("sitio");
const salida = opcion("salida");
const solo = opcion("solo", "");
const filmar = process.argv.includes("--filmar");
if (!sitio || !salida) {
  console.error("Uso: node herramientas/capturas.mjs --sitio <carpeta> --salida <carpeta> [--solo texto] [--filmar]");
  process.exit(2);
}
mkdirSync(salida, { recursive: true });

/* ── un servidor mínimo para la carpeta del sitio ── */
const TIPOS = { ".html": "text/html; charset=utf-8", ".json": "application/json", ".png": "image/png", ".webmanifest": "application/json" };
const servidor = createServer((pedido, respuesta) => {
  const ruta = decodeURIComponent(pedido.url.split("?")[0]);
  const archivo = join(sitio, normalize(ruta === "/" ? "/index.html" : ruta));
  if (!existsSync(archivo) || !statSync(archivo).isFile()) { respuesta.writeHead(404); respuesta.end(); return; }
  respuesta.writeHead(200, { "Content-Type": TIPOS[extname(archivo)] || "application/octet-stream", "Cache-Control": "no-store" });
  respuesta.end(readFileSync(archivo));
});
await new Promise((listo) => servidor.listen(0, "127.0.0.1", listo));
const base = "http://127.0.0.1:" + servidor.address().port;

/* ── Chrome y su protocolo, a mano ── */
const perfil = mkdtempSync(join(tmpdir(), "capturas-"));
const navegador = spawn(CHROME, ["--headless=new", "--remote-debugging-port=0", "--user-data-dir=" + perfil,
  "--no-first-run", "--no-default-browser-check", "--hide-scrollbars", "--force-color-profile=srgb"], { stdio: ["ignore", "ignore", "pipe"] });
const direccion = await new Promise((listo, falla) => {
  let texto = "";
  navegador.stderr.on("data", (d) => {
    texto += d;
    const m = texto.match(/ws:\/\/[^\s]+/);
    if (m) listo(m[0]);
  });
  setTimeout(() => falla(new Error("Chrome no arrancó")), 20000);
});
const conexion = new WebSocket(direccion);
await new Promise((listo) => { conexion.onopen = listo; });
let siguiente = 1;
const pendientes = new Map(), oyentes = new Set();
conexion.onmessage = (m) => {
  const dato = JSON.parse(m.data);
  if (dato.id && pendientes.has(dato.id)) {
    const { listo, falla } = pendientes.get(dato.id);
    pendientes.delete(dato.id);
    if (dato.error) falla(new Error(dato.error.message)); else listo(dato.result);
  } else oyentes.forEach((o) => o(dato));
};
const pedir = (metodo, params = {}, sesion) => new Promise((listo, falla) => {
  const id = siguiente++;
  pendientes.set(id, { listo, falla });
  conexion.send(JSON.stringify({ id, method: metodo, params, sessionId: sesion }));
});
const espera = (ms) => new Promise((r) => setTimeout(r, ms));

/* Lo que se mide en cada pantalla, dentro de la página. */
const MEDIR = `(() => {
  const visible = (el) => { const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none" && s.opacity !== "0"; };
  const chicos = new Map();
  const paseo = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const tamanos = new Set();
  while (paseo.nextNode()) {
    const nodo = paseo.currentNode;
    if (!nodo.textContent.trim()) continue;
    const el = nodo.parentElement;
    if (!el || ["SCRIPT", "STYLE", "OPTION"].includes(el.tagName) || !visible(el)) continue;
    const f = parseFloat(getComputedStyle(el).fontSize);
    tamanos.add(Math.round(f * 10) / 10);
    if (f < 12) chicos.set(nodo.textContent.trim().slice(0, 30), f);
  }
  const botones = Array.from(document.querySelectorAll("button,a[href],select,input,summary,[role=button]"))
    .filter((el) => el.offsetParent !== null || getComputedStyle(el).position === "fixed").filter(visible).map((el) => {
      const r = el.getBoundingClientRect();
      return { t: (el.innerText || el.getAttribute("aria-label") || el.tagName).trim().slice(0, 26).replace(/\\n/g, " "), a: Math.round(r.width), h: Math.round(r.height) };
    }).filter((b) => b.h < 44 || b.a < 44);
  return { alto: document.documentElement.scrollHeight, ancho: document.documentElement.scrollWidth, ventana: innerWidth,
    desborda: document.documentElement.scrollWidth > innerWidth + 1,
    tamanos: Array.from(tamanos).sort((a, b) => a - b), letraChica: Array.from(chicos.entries()).slice(0, 12),
    botonesChicos: botones.slice(0, 14), nodos: document.getElementsByTagName("*").length };
})()`;

const VISTA = (v) => `document.querySelector('.al-pie button[data-vista="${v}"], .en-cabeza button[data-vista="${v}"]').click()`;
const PESTANA = (t) => `Array.from(document.querySelectorAll('#vista-semana .tabs button')).find(b => b.textContent.startsWith(${JSON.stringify(t)})).click()`;
const ABAJO = (y) => `window.scrollTo({top:${y},behavior:'instant'})`;

const MOMENTOS = existsSync(join(sitio, "momentos"));

/* Lo que contesta la función de carga en las fotos, con la misma forma que la de verdad. */
const ENLACE = "#k=" + "a".repeat(40);
const CARGA = { id: "20261101T180000-0a1b2c3d", cargador: "Organizador", archivo: "Quiniela_semana_9.xlsx" };
const ENLACE_MALO = { quien: [401, { error: "Este enlace no sirve o ya fue anulado. Pídele a Angel uno nuevo." }] };
const CON_ULTIMA = (estado, resultado, archivo = CARGA.archivo) => ({
  quien: [200, { nombre: "Organizador", ultima: { ...CARGA, archivo, estado, resultado, creado: new Date(Date.now() - 3 * 3600e3).toISOString() } }],
});
// Una carga recién hecha sigue en revisión al abrir: la página espera su resultado sola.
const AL_TERMINAR = (estado, resultado) => ({
  quien: [200, { nombre: "Organizador", ultima: { ...CARGA, estado: "en_cola", creado: new Date().toISOString() } }],
  estado: [200, { ...CARGA, estado, resultado, creado: new Date().toISOString() }],
});
const QUEDO = {
  aceptado: true, accion: "tanda", semana: 9, titulo: "Semana 9: se agregó la tanda", participantes: 34,
  partidos_cargados: 13, partidos_semana: 14, sellados: ["Ravens @ Bills"],
  cambios: ["Entraron 13 partidos de la tanda del domingo.", "Cambió el pick de 2 participantes en partidos que no han empezado."],
  faltan: "Faltan 1 partido(s) de la semana: entran cuando llegue la hoja de esa tanda.",
  avisos: ["Sotocles no eligió en Jets @ Dolphins."],
};
const RECHAZO = {
  aceptado: false, accion: "rechazada", semana: 9, titulo: "No se cargó la semana 9",
  error: "La hoja trae 15 partidos y la semana 9 de la NFL tiene 14.\nRevisa el renglón de Jets @ Dolphins.",
  avisos: ["Hay dos participantes con el mismo nombre: Luis Santoyo."],
};
const FALLA = { aceptado: false, titulo: "No se pudo terminar", error: "Algo falló de nuestro lado, no en tu archivo. No se tocó nada y Angel ya tiene el aviso." };

const pantallas = [
  // El portal tal como está hoy, con nombre elegido.
  { n: "hoy", p: "/index.html", h: "#hoy", yo: YO },
  { n: "hoy-sin-nombre", p: "/index.html", h: "#hoy" },
  { n: "picks", p: "/index.html", h: "#picks", yo: YO },
  { n: "picks-abajo", p: "/index.html", h: "#picks", yo: YO, pasos: [ABAJO(760)] },
  { n: "semana-partidos", p: "/index.html", h: "#s8", yo: YO, pasos: [PESTANA("Partidos")] },
  { n: "semana-tabla", p: "/index.html", h: "#s8", yo: YO, pasos: [PESTANA("Tabla")] },
  { n: "semana-cerrada", p: "/index.html", h: "#s7", yo: YO },
  { n: "semana-cerrada-quien", p: "/index.html", h: "#s7", yo: YO, pasos: [PESTANA("Quién")] },
  { n: "general", p: "/index.html", h: "#general", yo: YO },
  { n: "general-abajo", p: "/index.html", h: "#general", yo: YO, pasos: [ABAJO(620)] },
  { n: "premios", p: "/index.html", h: "#premios", yo: YO },
  { n: "premios-abajo", p: "/index.html", h: "#premios", yo: YO, pasos: [ABAJO(1000)] },
  { n: "ficha", p: "/index.html", h: "#jugador/" + encodeURIComponent("Carlos Rodriguez"), yo: YO },
  { n: "ficha-abajo", p: "/index.html", h: "#jugador/" + encodeURIComponent("Carlos Rodriguez"), yo: YO, pasos: [ABAJO(720)] },
  { n: "hoja-semanas", p: "/index.html", h: "#s8", yo: YO, pasos: ["document.querySelector('.semana-elegida').click()"] },
  { n: "hoja-tu", p: "/index.html", h: "#hoy", yo: YO, pasos: ["document.getElementById('identidad').click()"] },
  { n: "hoja-partido", p: "/index.html", h: "#s7", yo: YO, pasos: [PESTANA("Partidos"), "document.querySelector('#vista-semana .juego-fila').click()"] },
  { n: "tema-chiefs", p: "/index.html", h: "#hoy", yo: YO, equipo: "Chiefs" },
  { n: "tema-chiefs-general", p: "/index.html", h: "#general", yo: YO, equipo: "Chiefs" },
  // Pantalla chica y computadora.
  { n: "chico-hoy", p: "/index.html", h: "#hoy", yo: YO, m: CHICO },
  { n: "chico-general", p: "/index.html", h: "#general", yo: YO, m: CHICO },
  { n: "chico-picks", p: "/index.html", h: "#picks", yo: YO, m: CHICO },
  { n: "compu-hoy", p: "/index.html", h: "#hoy", yo: YO, m: COMPU },
  { n: "compu-general", p: "/index.html", h: "#general", yo: YO, m: COMPU },
  { n: "compu-semana", p: "/index.html", h: "#s7", yo: YO, m: COMPU },
  // Otros momentos de la semana (reloj y ESPN de mentira).
  ...(MOMENTOS ? [
    { n: "vivo-hoy", p: "/momentos/fase-vivo.html", h: "#hoy", yo: YO },
    { n: "vivo-hoy-abajo", p: "/momentos/fase-vivo.html", h: "#hoy", yo: YO, pasos: [ABAJO(800)] },
    { n: "vivo-semana", p: "/momentos/fase-vivo.html", h: "#s7", yo: YO, pasos: [PESTANA("Partidos")] },
    { n: "vivo-escenarios", p: "/momentos/fase-vivo.html", h: "#s7", yo: YO, pasos: [PESTANA("Escenarios")] },
    { n: "domingo-temprano", p: "/momentos/fase-hoy.html", h: "#hoy", yo: YO },
    { n: "domingo-noche", p: "/momentos/fase-domingo-noche.html", h: "#hoy", yo: YO },
    { n: "martes", p: "/momentos/fase-martes.html", h: "#hoy", yo: YO },
    { n: "final", p: "/momentos/fase-final.html", h: "#hoy", yo: YO },
    { n: "final-premios", p: "/momentos/fase-final.html", h: "#premios", yo: YO },
  ] : []),
  // Las páginas sueltas: el enlace de carga en cada uno de sus caminos, y la prueba de conexión.
  { n: "cargar-sin-llave", p: "/cargar.html", h: "" },
  { n: "cargar-llave-mala", p: "/cargar.html", h: ENLACE, funcion: ENLACE_MALO },
  { n: "cargar-sin-conexion", p: "/cargar.html", h: ENLACE, funcion: { quien: null } },
  { n: "cargar-formulario", p: "/cargar.html", h: ENLACE, funcion: CON_ULTIMA("listo", QUEDO) },
  { n: "cargar-revisando", p: "/cargar.html", h: ENLACE, funcion: AL_TERMINAR("en_cola") },
  { n: "cargar-listo", p: "/cargar.html", h: ENLACE, funcion: AL_TERMINAR("listo", QUEDO), espera: 4500 },
  { n: "cargar-sin-cambios", p: "/cargar.html", h: ENLACE, espera: 4500,
    funcion: AL_TERMINAR("listo", { aceptado: true, accion: "sin_cambios", semana: 9, titulo: "Semana 9: ya estaba igual" }) },
  { n: "cargar-rechazado", p: "/cargar.html", h: ENLACE, funcion: AL_TERMINAR("rechazado", RECHAZO), espera: 4500 },
  { n: "cargar-falla", p: "/cargar.html", h: ENLACE, funcion: AL_TERMINAR("falla", FALLA), espera: 4500 },
  { n: "chico-cargar-formulario", p: "/cargar.html", h: ENLACE, m: CHICO,
    funcion: CON_ULTIMA("rechazado", RECHAZO, "Quiniela_semana_9_jueves_tanda_final_version_definitiva_de_verdad.xlsx") },
  { n: "chico-cargar-listo", p: "/cargar.html", h: ENLACE, funcion: AL_TERMINAR("listo", QUEDO), espera: 4500, m: CHICO },
  { n: "compu-cargar-formulario", p: "/cargar.html", h: ENLACE, funcion: CON_ULTIMA("listo", QUEDO), m: COMPU },
  { n: "red", p: "/red.html", h: "", funcion: { quien: [401, ENLACE_MALO.quien[1]], espn: [200, {}] } },
  { n: "red-falla", p: "/red.html", h: "", funcion: { quien: null, espn: null } },
  { n: "chico-red", p: "/red.html", h: "", funcion: { quien: [401, ENLACE_MALO.quien[1]], espn: [200, {}] }, m: CHICO },
];

/* Contesta las pedidas a la función y a ESPN de una pantalla simulada; null es sin red. */
function contestar({ requestId, request }, s, funcion) {
  const respuesta = request.method === "OPTIONS" ? [204, null]
    : funcion[request.url.includes("espn.com") ? "espn" : new URL(request.url).searchParams.get("que")];
  if (!respuesta) return pedir("Fetch.failRequest", { requestId, errorReason: "InternetDisconnected" }, s);
  return pedir("Fetch.fulfillRequest", {
    requestId,
    responseCode: respuesta[0],
    responseHeaders: ["Origin", "Headers", "Methods"].map((n) => ({ name: "Access-Control-Allow-" + n, value: "*" }))
      .concat({ name: "Content-Type", value: "application/json" }),
    body: Buffer.from(respuesta[1] === null ? "" : JSON.stringify(respuesta[1])).toString("base64"),
  }, s);
}

async function abrir(pantalla) {
  const { targetId } = await pedir("Target.createTarget", { url: "about:blank" });
  const { sessionId: s } = await pedir("Target.attachToTarget", { targetId, flatten: true });
  await pedir("Page.enable", {}, s);
  await pedir("Runtime.enable", {}, s);
  await pedir("Log.enable", {}, s);
  await pedir("Emulation.setDeviceMetricsOverride", pantalla.m || TELEFONO, s);
  if ((pantalla.m || TELEFONO).mobile) await pedir("Emulation.setTouchEmulationEnabled", { enabled: true }, s);
  const semilla = [
    // El perfil de Chrome se comparte entre pantallas: cada una arranca limpia.
    "try{",
    "localStorage.clear();sessionStorage.clear();sessionStorage.setItem('angabave.estreno','1');",
    pantalla.yo ? `localStorage.setItem('angabave.jugador',${JSON.stringify(pantalla.yo)});` : "",
    pantalla.equipo ? `localStorage.setItem('angabave.equipo',${JSON.stringify(pantalla.equipo)});` : "",
    pantalla.borrador ? `localStorage.setItem(${JSON.stringify(pantalla.borrador[0])},${JSON.stringify(pantalla.borrador[1])});` : "",
    "for(let n=1;n<=18;n++)localStorage.setItem('angabave.confeti.'+n,'1');",
    pantalla.estreno ? "sessionStorage.removeItem('angabave.estreno');" : "",
    "}catch(e){}",
  ].join("");
  await pedir("Page.addScriptToEvaluateOnNewDocument", { source: semilla }, s);
  const errores = [];
  const oyente = (dato) => {
    if (dato.sessionId !== s) return;
    if (dato.method === "Runtime.exceptionThrown") errores.push((dato.params.exceptionDetails.exception || {}).description || dato.params.exceptionDetails.text);
    if (dato.method === "Log.entryAdded" && dato.params.entry.level === "error" && !/scoreboard|Failed to load resource/.test(dato.params.entry.text + (dato.params.entry.url || ""))) errores.push(dato.params.entry.text);
    if (dato.method === "Runtime.consoleAPICalled" && dato.params.type === "error") errores.push(dato.params.args.map((a) => a.value || a.description).join(" "));
    if (dato.method === "Fetch.requestPaused") contestar(dato.params, s, pantalla.funcion).catch(() => {});
  };
  oyentes.add(oyente);
  if (pantalla.funcion) await pedir("Fetch.enable", { patterns: [{ urlPattern: "*supabase.co*" }, { urlPattern: "*espn.com*" }] }, s);
  return { s, targetId, errores, cerrar: async () => { oyentes.delete(oyente); await pedir("Target.closeTarget", { targetId }); } };
}

const hacer = (s, codigo) => pedir("Runtime.evaluate", { expression: codigo, awaitPromise: true, returnByValue: true }, s);
const foto = async (s, nombre, entera) => {
  const opciones = entera ? { captureBeyondViewport: true } : {};
  const { data } = await pedir("Page.captureScreenshot", { format: "png", ...opciones }, s);
  writeFileSync(join(salida, nombre + ".png"), Buffer.from(data, "base64"));
};

const reporte = {};
for (const pantalla of pantallas) {
  if (solo && !pantalla.n.includes(solo)) continue;
  const { s, errores, cerrar } = await abrir(pantalla);
  try {
    await pedir("Page.navigate", { url: base + pantalla.p + pantalla.h }, s);
    await espera(1400 + (pantalla.espera || 0));
    for (const paso of pantalla.pasos || []) { await hacer(s, paso); await espera(450); }
    await espera(900);
    await foto(s, pantalla.n);
    const { result } = await hacer(s, MEDIR);
    reporte[pantalla.n] = { ...result.value, errores };
    console.log(pantalla.n.padEnd(24), errores.length ? "ERRORES: " + errores[0].slice(0, 120) : "ok",
      result.value.desborda ? " DESBORDA" : "", " alto " + result.value.alto);
  } catch (e) {
    reporte[pantalla.n] = { falla: String(e) };
    console.log(pantalla.n.padEnd(24), "FALLÓ", String(e).slice(0, 120));
  }
  await cerrar();
}

/* ── el movimiento: cuadros de la entrada y de un cambio de sección ── */
async function filmacion(nombre, pantalla, accion, ms) {
  const { s, errores, cerrar } = await abrir(pantalla);
  const cuadros = [];
  const oyente = (dato) => {
    if (dato.sessionId === s && dato.method === "Page.screencastFrame") {
      cuadros.push({ t: dato.params.metadata.timestamp, data: dato.params.data });
      pedir("Page.screencastFrameAck", { sessionId: dato.params.sessionId }, s).catch(() => {});
    }
  };
  oyentes.add(oyente);
  if (accion) { await pedir("Page.navigate", { url: base + pantalla.p + pantalla.h }, s); await espera(1800); }
  await pedir("Page.startScreencast", { format: "jpeg", quality: 70, maxWidth: 390, everyNthFrame: 1 }, s);
  if (accion) await hacer(s, accion); else await pedir("Page.navigate", { url: base + pantalla.p + pantalla.h }, s);
  await espera(ms);
  await pedir("Page.stopScreencast", {}, s);
  oyentes.delete(oyente);
  const carpeta = join(salida, "cine-" + nombre);
  mkdirSync(carpeta, { recursive: true });
  // Con ocho cuadros repartidos en el tiempo basta para ver la coreografía.
  const paso = Math.max(1, Math.floor(cuadros.length / 8));
  const inicio = cuadros.length ? cuadros[0].t : 0;
  const elegidos = cuadros.filter((_, i) => i % paso === 0).slice(0, 10);
  elegidos.forEach((c) => writeFileSync(join(carpeta, String(Math.round((c.t - inicio) * 1000)).padStart(5, "0") + "ms.jpg"), Buffer.from(c.data, "base64")));
  console.log("cine-" + nombre, cuadros.length + " cuadros,", elegidos.length, "guardados", errores.length ? "ERRORES" : "");
  await cerrar();
}
if (filmar) {
  const base_ = { p: "/index.html", h: "#hoy", yo: YO };
  await filmacion("entrada", { ...base_, estreno: true }, null, 2200);
  await filmacion("a-general", base_, VISTA("general"), 1300);
  await filmacion("a-premios", { ...base_, h: "#general" }, VISTA("premios"), 1300);
  await filmacion("pestana", { ...base_, h: "#s7" }, PESTANA("Tabla"), 900);
  await filmacion("ficha", { ...base_, h: "#general" }, "document.querySelector('#vista-general tbody tr').click()", 1300);
  await filmacion("hoja", { ...base_, h: "#s8" }, "document.querySelector('.semana-elegida').click()", 1000);
}

writeFileSync(join(salida, "reporte.json"), JSON.stringify(reporte, null, 1));
const conErrores = Object.entries(reporte).filter(([, r]) => (r.errores || []).length || r.falla);
console.log(conErrores.length ? "Pantallas con errores: " + conErrores.map(([n]) => n).join(", ") : "Sin errores de consola en ninguna pantalla.");
conexion.close();
navegador.kill();
servidor.close();
await espera(300);
try { rmSync(perfil, { recursive: true, force: true }); } catch { /* lo limpia el sistema */ }
process.exit(conErrores.length ? 1 : 0);
