/**
 * Arranque de `angabave-carga` en Supabase: aquí solo se conecta la lógica de
 * carga.ts con la cubeta privada y con GitHub.
 *
 * Vive en el mismo proyecto de Supabase que la app pero no toca nada de ella:
 * su propia cubeta (`angabave-cargas`), sus propios secretos (`ANGABAVE_*`) y
 * ninguna tabla. Se despliega sin verificar el JWT de Supabase porque quien
 * llama no tiene cuenta: la puerta es la llave del enlace.
 *
 * Secretos:
 *   ANGABAVE_LLAVES   {"huella sha256": "nombre"}; lo escribe herramientas/llaves.py
 *   ANGABAVE_SECRETO  lo comparte con el workflow de GitHub
 *   ANGABAVE_GITHUB   token de GitHub que solo puede correr workflows de angabave
 */

import { type Almacen, type Bytes, crearManejador, TAMANO_MAXIMO } from "./carga.ts";

const URL_BASE = Deno.env.get("SUPABASE_URL") ?? "";
const LLAVE_DE_SERVICIO = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
const CUBETA = "angabave-cargas";
const REPO = "Vegeeks/angabave";
const WORKFLOW = "cargar.yml";
const ORIGEN = "https://vegeeks.github.io";

function llaves(): Record<string, string> {
  try {
    const datos = JSON.parse(Deno.env.get("ANGABAVE_LLAVES") ?? "{}");
    return Object.fromEntries(
      Object.entries(datos).filter(([h, n]) => /^[0-9a-f]{64}$/.test(h) && typeof n === "string"),
    ) as Record<string, string>;
  } catch {
    console.error("ANGABAVE_LLAVES no es JSON válido: nadie puede cargar hasta arreglarlo.");
    return {};
  }
}

function almacenSupabase(): Almacen {
  const base = `${URL_BASE}/storage/v1`;
  const autorizacion = { Authorization: `Bearer ${LLAVE_DE_SERVICIO}`, apikey: LLAVE_DE_SERVICIO };

  async function crearCubeta() {
    const r = await fetch(`${base}/bucket`, {
      method: "POST",
      headers: { ...autorizacion, "Content-Type": "application/json" },
      body: JSON.stringify({ id: CUBETA, name: CUBETA, public: false, file_size_limit: TAMANO_MAXIMO }),
    });
    const texto = await r.text();
    if (!r.ok && !/already exists|Duplicate/i.test(texto)) {
      throw new Error(`No pude crear la cubeta: ${r.status} ${texto.slice(0, 200)}`);
    }
  }

  async function subirUnaVez(ruta: string, datos: Bytes, tipo: string) {
    return await fetch(`${base}/object/${CUBETA}/${ruta}`, {
      method: "POST",
      headers: { ...autorizacion, "Content-Type": tipo, "x-upsert": "true" },
      body: datos,
    });
  }

  return {
    async subir(ruta, datos, tipo) {
      let r = await subirUnaVez(ruta, datos, tipo);
      if (!r.ok && /bucket not found/i.test(await r.clone().text())) {
        await crearCubeta();
        r = await subirUnaVez(ruta, datos, tipo);
      }
      if (!r.ok) throw new Error(`No pude guardar ${ruta}: ${r.status} ${(await r.text()).slice(0, 200)}`);
      await r.body?.cancel();
    },
    async bajar(ruta) {
      const r = await fetch(`${base}/object/authenticated/${CUBETA}/${ruta}`, { headers: autorizacion });
      if (!r.ok) {
        await r.body?.cancel();
        return null;
      }
      return new Uint8Array(await r.arrayBuffer());
    },
    async listar(prefijo) {
      const r = await fetch(`${base}/object/list/${CUBETA}`, {
        method: "POST",
        headers: { ...autorizacion, "Content-Type": "application/json" },
        body: JSON.stringify({ prefix: prefijo, limit: 100, offset: 0, sortBy: { column: "name", order: "desc" } }),
      });
      if (!r.ok) {
        await r.body?.cancel();
        return [];
      }
      const elementos = (await r.json()) as { name: string }[];
      return elementos.map((e) => e.name);
    },
  };
}

async function despachar(carga: string) {
  const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${Deno.env.get("ANGABAVE_GITHUB") ?? ""}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "angabave-carga",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ ref: "main", inputs: { carga } }),
    signal: AbortSignal.timeout(15_000),
  });
  const texto = await r.text();
  if (r.status !== 204 && r.status !== 200) throw new Error(`GitHub respondió ${r.status}: ${texto.slice(0, 200)}`);
}

Deno.serve(crearManejador({
  llaves: llaves(),
  secreto: Deno.env.get("ANGABAVE_SECRETO") ?? "",
  almacen: almacenSupabase(),
  despachar,
  ahora: () => new Date(),
  azar: () => [...crypto.getRandomValues(new Uint8Array(4))].map((b) => b.toString(16).padStart(2, "0")).join(""),
  origen: ORIGEN,
}));
