/**
 * Pruebas del buzón por enlace. Todo en memoria: ni Supabase ni GitHub.
 *
 *   deno test supabase/functions/angabave-carga/
 */

import { assert, assertEquals, assertMatch } from "jsr:@std/assert@1";
import { type Almacen, type Bytes, CARGAS_POR_HORA, crearManejador, huella, nombreLimpio } from "./carga.ts";

const LLAVE = "llave-de-prueba-del-organizador-1234567890";
const OTRA = "otra-llave-de-prueba-de-otra-persona-00000";
const SECRETO = "secreto-compartido-con-el-workflow";
const BASE = "https://funcion.test/";
const XLSX: Bytes = new Uint8Array([0x50, 0x4b, 0x03, 0x04, 1, 2, 3]);

function almacenEnMemoria() {
  const objetos = new Map<string, Bytes>();
  const almacen: Almacen = {
    subir: (ruta, datos) => Promise.resolve(void objetos.set(ruta, datos)),
    bajar: (ruta) => Promise.resolve(objetos.get(ruta) ?? null),
    listar: (prefijo) =>
      Promise.resolve(
        [
          ...new Set(
            [...objetos.keys()]
              .filter((r) => r.startsWith(prefijo + "/"))
              .map((r) => r.slice(prefijo.length + 1).split("/")[0]),
          ),
        ].sort().reverse(),
      ),
  };
  return { almacen, objetos };
}

async function armar(opciones: { despacharFalla?: boolean } = {}) {
  const { almacen, objetos } = almacenEnMemoria();
  const despachadas: string[] = [];
  let reloj = Date.UTC(2026, 8, 26, 3, 15, 0);
  let contador = 0;
  const manejar = crearManejador({
    llaves: { [await huella(LLAVE)]: "Organizador", [await huella(OTRA)]: "Otra persona" },
    secreto: SECRETO,
    almacen,
    despachar: (carga) => {
      if (opciones.despacharFalla) return Promise.reject(new Error("401 Bad credentials"));
      despachadas.push(carga);
      return Promise.resolve();
    },
    ahora: () => new Date(reloj),
    azar: () => (contador++).toString(16).padStart(8, "0"),
    origen: "https://vegeeks.github.io",
  });
  return { manejar, objetos, despachadas, avanzar: (ms: number) => void (reloj += ms) };
}

const pedir = (que: string, init: RequestInit & { llave?: string; secreto?: string; extra?: string } = {}) => {
  const headers = new Headers(init.headers);
  if (init.llave) headers.set("x-llave", init.llave);
  if (init.secreto) headers.set("x-secreto", init.secreto);
  return new Request(`${BASE}?que=${que}${init.extra ?? ""}`, { ...init, headers });
};

const subir = (llave: string, nombre: string, datos: Bytes) =>
  pedir("subir", { method: "POST", llave, body: datos, headers: { "x-archivo": encodeURIComponent(nombre) } });

Deno.test("la página del portal puede preguntar, y nadie más", async () => {
  const { manejar } = await armar();
  const r = await manejar(new Request(BASE, { method: "OPTIONS" }));
  assertEquals(r.status, 204);
  assertEquals(r.headers.get("access-control-allow-origin"), "https://vegeeks.github.io");
});

Deno.test("sin llave, con llave mal formada o desconocida, no pasa", async () => {
  const { manejar } = await armar();
  for (const llave of [undefined, "corta", "x".repeat(40), "llave con espacios que no sirve 12345"]) {
    const r = await manejar(pedir("quien", { llave }));
    assertEquals(r.status, 401);
    assertMatch((await r.json()).error, /no sirve/);
  }
});

Deno.test("con la llave dice de quién es el enlace", async () => {
  const { manejar } = await armar();
  const r = await manejar(pedir("quien", { llave: LLAVE }));
  assertEquals(await r.json(), { nombre: "Organizador", ultima: null });
});

Deno.test("sube, guarda y le avisa a GitHub", async () => {
  const { manejar, objetos, despachadas } = await armar();
  const r = await manejar(subir(LLAVE, "Quiniela 3.xlsx", XLSX));
  assertEquals(r.status, 202);
  const { id } = await r.json();
  assertMatch(id, /^20260926T031500-[0-9a-f]{8}$/);

  const prefijo = (await huella(LLAVE)).slice(0, 16);
  assertEquals(despachadas, [`${prefijo}/${id}`]);
  assertEquals(objetos.get(`${prefijo}/${id}/archivo`), XLSX);
  const estado = JSON.parse(new TextDecoder().decode(objetos.get(`${prefijo}/${id}/estado.json`)));
  assertEquals([estado.estado, estado.cargador, estado.archivo], ["en_cola", "Organizador", "Quiniela_3.xlsx"]);
});

Deno.test("rechaza lo que no es Excel ni PDF, con un mensaje claro", async () => {
  const { manejar, despachadas } = await armar();
  const casos: [string, Bytes, RegExp][] = [
    ["Quiniela.xls", XLSX, /formato viejo/],
    ["foto.png", XLSX, /Excel \(\.xlsx\) o un PDF/],
    ["Quiniela.xlsx", new Uint8Array([1, 2, 3, 4]), /no lo es/],
    ["Quiniela.xlsx", new Uint8Array([0xd0, 0xcf, 0x11, 0xe0, 0]), /contraseña/],
    ["Quiniela.pdf", XLSX, /PDF pero/],
    ["Quiniela.xlsx", new Uint8Array(), /vacío/],
  ];
  for (const [nombre, datos, mensaje] of casos) {
    const r = await manejar(subir(LLAVE, nombre, datos));
    assertEquals(r.status, 400, nombre);
    assertMatch((await r.json()).error, mensaje);
  }
  assertEquals(despachadas, []);
});

Deno.test("corta un archivo enorme aunque no diga su tamaño", async () => {
  const { manejar } = await armar();
  const trozo = new Uint8Array(1024 * 1024);
  trozo.set([0x50, 0x4b, 0x03, 0x04]);
  let enviados = 0;
  const flujo = new ReadableStream<Uint8Array>({
    pull(control) {
      if (enviados++ < 12) control.enqueue(trozo);
      else control.close();
    },
  });
  const r = await manejar(
    new Request(`${BASE}?que=subir`, {
      method: "POST",
      body: flujo,
      headers: { "x-llave": LLAVE, "x-archivo": "Q.xlsx" },
    }),
  );
  assertEquals(r.status, 413);
});

Deno.test("no deja más de las cargas permitidas por hora", async () => {
  const { manejar, avanzar } = await armar();
  for (let i = 0; i < CARGAS_POR_HORA; i++) {
    assertEquals((await manejar(subir(LLAVE, "Q.xlsx", XLSX))).status, 202);
    avanzar(1000);
  }
  assertEquals((await manejar(subir(LLAVE, "Q.xlsx", XLSX))).status, 429);
  // Otro enlace no se ve afectado, y pasada la hora vuelve a poder.
  assertEquals((await manejar(subir(OTRA, "Q.xlsx", XLSX))).status, 202);
  avanzar(3600_000);
  assertEquals((await manejar(subir(LLAVE, "Q.xlsx", XLSX))).status, 202);
});

Deno.test("si GitHub no acepta, lo dice y queda registrado", async () => {
  const { manejar, objetos } = await armar({ despacharFalla: true });
  const r = await manejar(subir(LLAVE, "Q.xlsx", XLSX));
  assertEquals(r.status, 502);
  const estado = [...objetos.entries()].find(([ruta]) => ruta.endsWith("estado.json"))!;
  assertEquals(JSON.parse(new TextDecoder().decode(estado[1])).estado, "falla");
});

Deno.test("cada enlace ve solo sus propias cargas", async () => {
  const { manejar } = await armar();
  const { id } = await (await manejar(subir(LLAVE, "Q.xlsx", XLSX))).json();
  assertEquals((await manejar(pedir("estado", { llave: LLAVE, extra: `&id=${id}` }))).status, 200);
  assertEquals((await manejar(pedir("estado", { llave: OTRA, extra: `&id=${id}` }))).status, 404);
  assertEquals((await manejar(pedir("estado", { llave: LLAVE, extra: "&id=../../x" }))).status, 400);
});

Deno.test("el workflow baja el archivo solo con el secreto", async () => {
  const { manejar, despachadas } = await armar();
  await manejar(subir(LLAVE, "Quiniela 3.xlsx", XLSX));
  const carga = despachadas[0];
  for (const secreto of [undefined, "equivocado", SECRETO + "x"]) {
    assertEquals((await manejar(pedir("archivo", { secreto, extra: `&carga=${carga}` }))).status, 401);
  }
  assertEquals((await manejar(pedir("archivo", { secreto: SECRETO, extra: "&carga=../../etc" }))).status, 400);

  const r = await manejar(pedir("archivo", { secreto: SECRETO, extra: `&carga=${carga}` }));
  assertEquals(r.status, 200);
  assertEquals(new Uint8Array(await r.arrayBuffer()), XLSX);
  assertEquals(r.headers.get("x-archivo"), "Quiniela_3.xlsx");
  assertEquals(decodeURIComponent(r.headers.get("x-cargador")!), "Organizador");
});

Deno.test("el workflow devuelve el resultado y la página lo ve", async () => {
  const { manejar, despachadas } = await armar();
  const { id } = await (await manejar(subir(LLAVE, "Q.xlsx", XLSX))).json();
  const carga = despachadas[0];

  const invalido = await manejar(pedir("resultado", {
    method: "POST",
    secreto: SECRETO,
    extra: `&carga=${carga}`,
    body: JSON.stringify({ estado: "hackeado" }),
  }));
  assertEquals(invalido.status, 400);

  const resultado = { aceptado: true, accion: "nueva", semana: 3, titulo: "Semana 3 cargada" };
  const r = await manejar(pedir("resultado", {
    method: "POST",
    secreto: SECRETO,
    extra: `&carga=${carga}`,
    body: JSON.stringify({ estado: "listo", resultado }),
  }));
  assertEquals(r.status, 200);

  const visto = await (await manejar(pedir("estado", { llave: LLAVE, extra: `&id=${id}` }))).json();
  assertEquals([visto.estado, visto.resultado.titulo], ["listo", "Semana 3 cargada"]);
  const quien = await (await manejar(pedir("quien", { llave: LLAVE }))).json();
  assertEquals(quien.ultima.id, id);
});

Deno.test("el nombre del archivo nunca se sale de su lugar", () => {
  assertEquals(nombreLimpio("../../.ssh/id.xlsx"), "_.._.ssh_id.xlsx");
  assertEquals(nombreLimpio("Quiniela 3 Jueves.pdf"), "Quiniela_3_Jueves.pdf");
  assert(!nombreLimpio(".oculto.xlsx").startsWith("."));
});

Deno.test("la huella es la misma que calcula herramientas/llaves.py", async () => {
  // SHA-256 de "abc", el vector de la norma; tests/test_llaves.py prueba el mismo.
  assertEquals(await huella("abc"), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
});
