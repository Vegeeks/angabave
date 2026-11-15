"use strict";
const CAJA = "angabave-pagina-v1";
const ESPERA = 3500;
const FRESCA = 60000;
const RAIZ = new URL("./", self.registration.scope).href;
const PAGINAS = [RAIZ, RAIZ + "index.html"];
const FIN = "window.angabaveListo = true";

const sinParametros = (url) => url.split("#")[0].split("?")[0];
const esPortal = (url) => PAGINAS.indexOf(sinParametros(url)) >= 0;
const esperar = (ms) => new Promise((listo) => setTimeout(() => listo(null), ms));

/* Completa de verdad: termina en </html> y trae la marca del final del guion. Una página que se
   cortó en el camino nunca se guarda ni se abre desde aquí. */
function completa(texto) {
  return typeof texto === "string" && texto.length > 20000 && texto.indexOf(FIN) > 0 && /<\/html>\s*$/.test(texto);
}

/* Un valor de los datos de la página (el JSON de id="datos"). */
function dato(texto, clave) {
  const desde = texto.indexOf('id="datos">');
  if (desde < 0) return "";
  const hasta = texto.indexOf("</script>", desde);
  const m = new RegExp('"' + clave + '":"([^"]+)"').exec(texto.slice(desde, hasta < 0 ? texto.length : hasta));
  return m ? m[1] : "";
}

/* Cuándo se generó. Safari no siempre entiende seis decimales en los segundos. */
function momento(texto) {
  const t = Date.parse(dato(texto, "generado").replace(/(\.\d{3})\d+/, "$1"));
  return isFinite(t) ? t : 0;
}

async function leerCompleta(respuesta) {
  if (!respuesta || !respuesta.ok || respuesta.type === "opaqueredirect") throw new Error("sin página");
  const texto = await respuesta.text();
  if (!completa(texto)) throw new Error("llegó incompleta");
  return texto;
}

async function copiaGuardada() {
  try {
    const guardada = await (await caches.open(CAJA)).match(RAIZ);
    if (!guardada) return null;
    const texto = await guardada.text();
    if (!completa(texto)) return null;
    return {
      texto,
      cuando: Number(guardada.headers.get("X-Angabave-Guardada")) || 0,
      como: guardada.headers.get("X-Angabave-Como") || "",
    };
  } catch (e) {
    return null;
  }
}

/* Se guarda solo si no es más vieja que la que ya hay. */
async function guardar(texto, como) {
  try {
    const previa = await copiaGuardada();
    if (previa && momento(previa.texto) > momento(texto)) return false;
    await (await caches.open(CAJA)).put(RAIZ, new Response(texto, {
      headers: {
        "Content-Type": "text/html; charset=utf-8",
        "X-Angabave-Guardada": String(Date.now()),
        "X-Angabave-Como": como,
      },
    }));
    return true;
  } catch (e) {
    return false;   // sin espacio o sin permiso: la página sigue, solo sin copia nueva
  }
}

/* copiaDe: la hora en que se guardó, cuando lo que se abre es la copia porque la red no llegó. */
function pagina(texto, copiaDe) {
  if (copiaDe) texto = texto.replace(/<html\b/i, '<html data-copia="' + copiaDe + '"');
  return new Response(texto, { headers: { "Content-Type": "text/html; charset=utf-8" } });
}

function sinSenal() {
  return new Response(
    '<!doctype html><html lang="es-MX"><head><meta charset="utf-8">' +
    '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">' +
    '<meta name="theme-color" content="#060A08"><title>ANGABAVE</title></head>' +
    '<body style="margin:0; background:#060A08; color:#F3F6F4; font:16px/1.45 -apple-system,BlinkMacSystemFont,Roboto,Arial,sans-serif">' +
    '<main style="max-width:520px; margin:0 auto; padding:48px 16px">' +
    '<h1 style="font-size:20px; line-height:1.25; margin:0 0 8px">Sin conexión</h1>' +
    '<p style="margin:0 0 8px; color:#A7B1AB">Este teléfono todavía no tiene guardada una copia del portal.' +
    " Ábrelo una vez con señal o con wifi y, desde ahí, abrirá aunque la red falle.</p>" +
    '<a href="./" style="display:inline-block; padding:12px 0; color:#FFD60A; font-weight:700">Volver a intentar</a>' +
    "</main></body></html>",
    { headers: { "Content-Type": "text/html; charset=utf-8" } }
  );
}

/* Sin copia no hay con qué cubrir: lo de la red tal cual, en cuanto empiece a llegar. */
async function sinCopia(evento) {
  try {
    const respuesta = await fetch(evento.request);
    if (respuesta.ok) {
      evento.waitUntil(leerCompleta(respuesta.clone()).then((texto) => guardar(texto, "red"), () => null));
    }
    return respuesta;
  } catch (e) {
    return sinSenal();
  }
}

async function abrir(evento) {
  const copia = await copiaGuardada();
  if (!copia) return sinCopia(evento);
  // La página la acaba de pedir completa para recargarse con lo nuevo: se abre sin bajarla otra vez.
  if (copia.como === "precarga" && Date.now() - copia.cuando < FRESCA) return pagina(copia.texto, 0);

  const red = fetch(evento.request).then(leerCompleta);
  // Aunque gane la copia, lo que llegue de la red se guarda para la próxima.
  evento.waitUntil(red.then((texto) => guardar(texto, "red"), () => null));
  const llego = await Promise.race([red.catch(() => null), esperar(ESPERA)]);
  if (llego && momento(llego) >= momento(copia.texto)) return pagina(llego, 0);
  if (llego) return pagina(copia.texto, 0);   // el nodo del CDN venía atrasado: la copia es más nueva
  return pagina(copia.texto, copia.cuando || 1);
}

self.addEventListener("fetch", (evento) => {
  const pedido = evento.request;
  if (pedido.method !== "GET" || pedido.mode !== "navigate" || !esPortal(pedido.url)) return;
  evento.respondWith(abrir(evento));
});

self.addEventListener("install", (evento) => {
  self.skipWaiting();
  // La página que se acaba de ver casi siempre sigue en el caché del navegador: guardarla no gasta datos.
  // Con la red colgada no se espera para siempre: la copia se hace en la siguiente visita.
  const primera = fetch(new Request(RAIZ, { cache: "default" })).then(leerCompleta).then((texto) => guardar(texto, "red"), () => null);
  evento.waitUntil(Promise.race([primera, esperar(30000)]));
});

self.addEventListener("activate", (evento) => {
  evento.waitUntil((async () => {
    for (const nombre of await caches.keys()) {
      if (nombre.indexOf("angabave-") === 0 && nombre !== CAJA) await caches.delete(nombre);
    }
    await self.clients.claim();
  })());
});

/* La página pide la versión nueva completa antes de recargarse: si la red no la entrega, no se va
   de donde está. El ?v= salta el caché del CDN, así que llega la más reciente. */
self.addEventListener("message", (evento) => {
  const puerto = evento.ports && evento.ports[0];
  if (!puerto || !evento.data || evento.data.tipo !== "precargar") return;
  evento.waitUntil(
    fetch(new Request(RAIZ + "?v=" + Date.now(), { cache: "no-store" }))
      .then(leerCompleta)
      .then(async (texto) => {
        const ok = await guardar(texto, "precarga");
        puerto.postMessage({ ok, firma: dato(texto, "firma") });
      })
      .catch(() => puerto.postMessage({ ok: false, firma: "" }))
  );
});
