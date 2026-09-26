/**
 * El buzón por enlace de ANGABAVE.
 *
 * Quien carga la semana no tiene cuenta de GitHub: tiene un enlace personal con
 * una llave larga al azar. Esta función comprueba la llave, guarda el archivo en
 * una cubeta privada y le pide a GitHub que corra el workflow de carga. El
 * workflow hace toda la revisión con el mismo código de siempre
 * (quiniela/carga.py) y le devuelve aquí el resultado, que la página consulta.
 *
 * Aquí no se revisa la quiniela: solo quién llama, el tamaño y que el archivo
 * sea Excel o PDF de verdad. Lo demás lo decide el workflow, para que no haya
 * dos revisiones que se desalineen.
 *
 * De la llave solo se guarda su huella SHA-256: ni la función ni el repo la
 * conocen. Los primeros 16 caracteres de la huella agrupan las cargas de cada
 * enlace en la cubeta, para que cada quien vea solo las suyas.
 */

/** Bytes que se pueden mandar tal cual en una respuesta o una petición. */
export type Bytes = Uint8Array<ArrayBuffer>;

export interface Almacen {
  subir(ruta: string, datos: Bytes, tipo: string): Promise<void>;
  bajar(ruta: string): Promise<Bytes | null>;
  /** Nombres dentro de `prefijo/`, del más nuevo al más viejo. */
  listar(prefijo: string): Promise<string[]>;
}

export interface Entorno {
  /** Huella SHA-256 (hex) de cada llave -> nombre de quien la tiene. */
  llaves: Record<string, string>;
  /** Lo comparten solo esta función y el workflow. */
  secreto: string;
  almacen: Almacen;
  /** Pide a GitHub que corra el workflow de carga. Lanza si no lo acepta. */
  despachar(carga: string): Promise<void>;
  ahora(): Date;
  /** Ocho caracteres hexadecimales al azar. */
  azar(): string;
  /** Único origen de navegador que puede llamar: el portal. */
  origen: string;
}

export const TAMANO_MAXIMO = 10 * 1024 * 1024;
export const CARGAS_POR_HORA = 12;
const RESULTADO_MAXIMO = 64 * 1024;
const RE_LLAVE = /^[A-Za-z0-9_-]{32,64}$/;
const RE_ID = /^\d{8}T\d{6}-[0-9a-f]{8}$/;
const RE_CARGA = /^[0-9a-f]{16}\/\d{8}T\d{6}-[0-9a-f]{8}$/;
const EXTENSIONES = [".xlsx", ".xlsm", ".pdf"];
const ESTADOS_FINALES = ["listo", "rechazado", "falla"];

/** Compara sin delatar por el tiempo cuántos caracteres coincidieron. */
export function iguales(a: string, b: string): boolean {
  if (!a || a.length !== b.length) return false;
  let diferencia = 0;
  for (let i = 0; i < a.length; i++) diferencia |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diferencia === 0;
}

export async function huella(llave: string): Promise<string> {
  const resumen = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(llave));
  return [...new Uint8Array(resumen)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** Solo letras, números, punto, guion y guion bajo; lo mismo que buzon.py. */
export function nombreLimpio(nombre: string): string {
  const limpio = nombre.replace(/[^A-Za-z0-9._-]/g, "_").replace(/^\.+/, "");
  const punto = limpio.lastIndexOf(".");
  if (punto <= 0) return limpio.slice(0, 100) || "archivo";
  return `${limpio.slice(0, punto).slice(0, 90) || "archivo"}.${limpio.slice(punto + 1).slice(0, 10)}`;
}

function idNuevo(ahora: Date, azar: string): string {
  const iso = ahora.toISOString(); // 2026-09-26T03:15:00.000Z
  return `${iso.slice(0, 10).replaceAll("-", "")}T${iso.slice(11, 19).replaceAll(":", "")}-${azar}`;
}

function momentoDelId(id: string): number {
  const [f, h] = id.split("T");
  return Date.UTC(+f.slice(0, 4), +f.slice(4, 6) - 1, +f.slice(6, 8), +h.slice(0, 2), +h.slice(2, 4), +h.slice(4, 6));
}

export function crearManejador(entorno: Entorno) {
  const cors = {
    "Access-Control-Allow-Origin": entorno.origen,
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "x-llave, x-archivo, content-type",
    "Access-Control-Max-Age": "600",
    "Vary": "Origin",
  };

  const json = (datos: unknown, estado = 200) =>
    new Response(JSON.stringify(datos), {
      status: estado,
      headers: { ...cors, "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" },
    });
  const error = (mensaje: string, estado: number) => json({ error: mensaje }, estado);

  /** Quién es, según la llave del enlace; null si la llave no sirve. */
  async function dueno(peticion: Request): Promise<{ nombre: string; prefijo: string } | null> {
    const llave = peticion.headers.get("x-llave") ?? "";
    if (!RE_LLAVE.test(llave)) return null;
    const suya = await huella(llave);
    for (const [conocida, nombre] of Object.entries(entorno.llaves)) {
      if (iguales(suya, conocida)) return { nombre, prefijo: suya.slice(0, 16) };
    }
    return null;
  }

  const esDelWorkflow = (peticion: Request) => iguales(peticion.headers.get("x-secreto") ?? "", entorno.secreto);

  async function leerEstado(ruta: string): Promise<Record<string, unknown> | null> {
    const datos = await entorno.almacen.bajar(`${ruta}/estado.json`);
    return datos ? JSON.parse(new TextDecoder().decode(datos)) : null;
  }

  const guardarEstado = (ruta: string, estado: Record<string, unknown>) =>
    entorno.almacen.subir(
      `${ruta}/estado.json`,
      new TextEncoder().encode(JSON.stringify(estado)),
      "application/json",
    );

  /** Lee el cuerpo cortando en cuanto pase del tope, diga lo que diga la cabecera. */
  async function cuerpoConTope(peticion: Request, tope: number): Promise<Bytes | null> {
    const declarado = Number(peticion.headers.get("content-length") ?? "0");
    if (declarado > tope) return null;
    const lector = peticion.body?.getReader();
    if (!lector) return new Uint8Array();
    const trozos: Uint8Array[] = [];
    let total = 0;
    while (true) {
      const { done, value } = await lector.read();
      if (done) break;
      total += value.length;
      if (total > tope) {
        await lector.cancel();
        return null;
      }
      trozos.push(value);
    }
    const datos = new Uint8Array(total);
    let posicion = 0;
    for (const trozo of trozos) {
      datos.set(trozo, posicion);
      posicion += trozo.length;
    }
    return datos;
  }

  function problemaDelArchivo(nombre: string, datos: Bytes): string | null {
    const minusculas = nombre.toLowerCase();
    if (minusculas.endsWith(".xls")) {
      return "Es un Excel del formato viejo (.xls). Ábrelo y guárdalo como libro de Excel (.xlsx).";
    }
    if (!EXTENSIONES.some((e) => minusculas.endsWith(e))) {
      return "El archivo tiene que ser un Excel (.xlsx) o un PDF.";
    }
    if (datos.length === 0) return "El archivo llegó vacío.";
    const inicio = [...datos.slice(0, 5)];
    const empieza = (bytes: number[]) => bytes.every((b, i) => inicio[i] === b);
    if (minusculas.endsWith(".pdf")) {
      return empieza([0x25, 0x50, 0x44, 0x46, 0x2d]) ? null : "El archivo dice ser PDF pero por dentro no lo es.";
    }
    if (empieza([0xd0, 0xcf, 0x11, 0xe0])) {
      return "El Excel tiene contraseña o es del formato viejo. Guárdalo como .xlsx sin contraseña.";
    }
    return empieza([0x50, 0x4b, 0x03, 0x04]) ? null : "El archivo dice ser Excel pero por dentro no lo es.";
  }

  async function subir(peticion: Request, quien: { nombre: string; prefijo: string }) {
    const recientes = (await entorno.almacen.listar(quien.prefijo))
      .filter((id) => RE_ID.test(id) && entorno.ahora().getTime() - momentoDelId(id) < 3600_000);
    if (recientes.length >= CARGAS_POR_HORA) {
      return error("Van demasiadas cargas en la última hora con este enlace. Espera un poco.", 429);
    }

    const nombre = nombreLimpio(decodeURIComponent(peticion.headers.get("x-archivo") ?? ""));
    const datos = await cuerpoConTope(peticion, TAMANO_MAXIMO);
    if (datos === null) return error("El archivo pesa más de 10 MB; una quiniela no pasa de 1 MB.", 413);
    const problema = problemaDelArchivo(nombre, datos);
    if (problema) return error(problema, 400);

    const id = idNuevo(entorno.ahora(), entorno.azar());
    const carga = `${quien.prefijo}/${id}`;
    await entorno.almacen.subir(`${carga}/archivo`, datos, "application/octet-stream");
    const estado: Record<string, unknown> = {
      estado: "en_cola",
      cargador: quien.nombre,
      archivo: nombre,
      creado: entorno.ahora().toISOString(),
    };
    await guardarEstado(carga, estado);

    try {
      await entorno.despachar(carga);
    } catch (falla) {
      console.error(`No pude despachar ${carga}: ${(falla as Error).message}`);
      await guardarEstado(carga, { ...estado, estado: "falla", terminado: entorno.ahora().toISOString() });
      return error("El archivo llegó, pero no pude avisarle al sistema que lo revise. Avísale a Angel.", 502);
    }
    return json({ id }, 202);
  }

  return async function manejar(peticion: Request): Promise<Response> {
    if (peticion.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
    const url = new URL(peticion.url);
    const que = url.searchParams.get("que") ?? "";

    try {
      // Lo que pide el workflow, con el secreto compartido.
      if (que === "archivo" || que === "resultado") {
        if (!esDelWorkflow(peticion)) return error("No autorizado.", 401);
        const carga = url.searchParams.get("carga") ?? "";
        if (!RE_CARGA.test(carga)) return error("Carga inválida.", 400);
        const estado = await leerEstado(carga);
        if (!estado) return error("No existe esa carga.", 404);

        if (que === "archivo" && peticion.method === "GET") {
          const datos = await entorno.almacen.bajar(`${carga}/archivo`);
          if (!datos) return error("No existe esa carga.", 404);
          return new Response(datos, {
            headers: {
              "Content-Type": "application/octet-stream",
              "Cache-Control": "no-store",
              "X-Archivo": String(estado.archivo),
              "X-Cargador": encodeURIComponent(String(estado.cargador)),
            },
          });
        }
        if (que === "resultado" && peticion.method === "POST") {
          const cuerpo = await cuerpoConTope(peticion, RESULTADO_MAXIMO);
          if (cuerpo === null) return error("Resultado demasiado grande.", 413);
          const { estado: final, resultado } = JSON.parse(new TextDecoder().decode(cuerpo));
          if (!ESTADOS_FINALES.includes(final)) return error("Estado inválido.", 400);
          await guardarEstado(carga, {
            ...estado,
            estado: final,
            resultado: resultado ?? null,
            terminado: entorno.ahora().toISOString(),
          });
          return json({ ok: true });
        }
        return error("Método no permitido.", 405);
      }

      // Lo que pide la página, con la llave del enlace.
      const quien = await dueno(peticion);
      if (!quien) return error("Este enlace no sirve o ya fue anulado. Pídele a Angel uno nuevo.", 401);

      if (que === "quien" && peticion.method === "GET") {
        const ultima = (await entorno.almacen.listar(quien.prefijo)).find((id) => RE_ID.test(id));
        const estado = ultima ? await leerEstado(`${quien.prefijo}/${ultima}`) : null;
        return json({ nombre: quien.nombre, ultima: estado ? { id: ultima, ...estado } : null });
      }
      if (que === "subir" && peticion.method === "POST") return await subir(peticion, quien);
      if (que === "estado" && peticion.method === "GET") {
        const id = url.searchParams.get("id") ?? "";
        if (!RE_ID.test(id)) return error("Carga inválida.", 400);
        const estado = await leerEstado(`${quien.prefijo}/${id}`);
        return estado ? json({ id, ...estado }) : error("No existe esa carga.", 404);
      }
      return error("No sé qué hacer con esto.", 400);
    } catch (falla) {
      console.error(`Falla atendiendo ${que}: ${(falla as Error).stack ?? falla}`);
      return error("Algo falló de este lado. Intenta de nuevo en unos minutos.", 500);
    }
  };
}
