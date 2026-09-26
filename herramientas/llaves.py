"""Enlaces personales para cargar la semana sin cuenta de GitHub.

Cada enlace trae una llave al azar después del "#"; quien lo tiene puede subir
el archivo de la semana desde cargar.html, y nadie más. La llave se muestra una
sola vez, al crearla, y no se guarda en ningún lado: aquí y en Supabase queda
solo su huella SHA-256.

    python3 herramientas/llaves.py nueva "Organizador"    # imprime el enlace
    python3 herramientas/llaves.py lista
    python3 herramientas/llaves.py quitar "Organizador"   # su enlace deja de servir
    python3 herramientas/llaves.py token                  # una vez: el token de GitHub

Solo usa la biblioteca estándar de Python y la CLI de Supabase: no hace falta
activar el entorno del proyecto.

Cada cambio actualiza el secreto ANGABAVE_LLAVES de la función y deja
constancia en data/llaves_de_carga.json de quién tiene enlace y desde cuándo.
Primero se actualiza Supabase y después el archivo, para que el archivo nunca
diga que sirve un enlace que no sirve.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import secrets
import ssl
import subprocess
import sys
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
RUTA = RAIZ / "data" / "llaves_de_carga.json"
PROYECTO = "hxaajhsizdnlismnelqu"
REPO = "Vegeeks/angabave"
PAGINA = "https://vegeeks.github.io/angabave/cargar.html"
#: El formulario de GitHub para el token, ya lleno salvo el repo, que no se puede prellenar.
FORMA_TOKEN = (
    "https://github.com/settings/personal-access-tokens/new?name=Carga+ANGABAVE"
    "&description=Solo+corre+el+workflow+de+carga+de+Vegeeks%2Fangabave"
    "&target_name=Vegeeks&expires_in=366&actions=write"
)
_SIGNOS = set(" .'’-_&()")


class ErrorLlaves(ValueError):
    """Algo no cuadra con la lista de enlaces."""


def huella(llave: str) -> str:
    return hashlib.sha256(llave.encode("utf-8")).hexdigest()


def enlace(llave: str) -> str:
    return f"{PAGINA}#k={llave}"


def leer(ruta: Path = RUTA) -> list[dict]:
    if not ruta.exists():
        return []
    return json.loads(ruta.read_text(encoding="utf-8"))["llaves"]


def escribir(llaves: list[dict], ruta: Path = RUTA) -> None:
    contenido = {
        "_nota": "Quién tiene enlace para cargar la semana. Solo la huella: la llave no se guarda. "
                 "Se administra con herramientas/llaves.py.",
        "llaves": llaves,
    }
    ruta.write_text(json.dumps(contenido, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _clave(nombre: str) -> str:
    sin_acentos = "".join(
        c for c in unicodedata.normalize("NFD", nombre) if not unicodedata.combining(c)
    )
    return " ".join(sin_acentos.lower().split())


def revisar_nombre(nombre: str, llaves: list[dict]) -> str:
    """El nombre sale en la página ("Hola, …") y en el historial: nada raro."""
    nombre = " ".join(nombre.split())
    if not 2 <= len(nombre) <= 40:
        raise ErrorLlaves("El nombre va de 2 a 40 caracteres.")
    if not all(c.isalpha() or c.isdigit() or c in _SIGNOS for c in nombre):
        raise ErrorLlaves("El nombre solo puede llevar letras, números, espacios y . ' - _ & ( ).")
    if any(_clave(l["nombre"]) == _clave(nombre) for l in llaves):
        raise ErrorLlaves(f"Ya hay un enlace a nombre de {nombre!r}. Quítalo primero si quieres uno nuevo.")
    return nombre


def secreto_de_la_funcion(llaves: list[dict]) -> str:
    return json.dumps({l["huella"]: l["nombre"] for l in llaves}, ensure_ascii=False, separators=(",", ":"))


def _supabase_secreto(nombre: str, valor: str) -> None:
    """Escribe un secreto de la función. El valor va por la entrada estándar, no en la línea de comandos."""
    subprocess.run(
        ["supabase", "secrets", "set", "--project-ref", PROYECTO, "--env-file", "/dev/stdin"],
        input=f"{nombre}={valor}\n", text=True, check=True, capture_output=True,
    )


def nueva(nombre: str, *, ruta: Path = RUTA, publicar=_supabase_secreto) -> str:
    llaves = leer(ruta)
    nombre = revisar_nombre(nombre, llaves)
    llave = secrets.token_urlsafe(32)
    llaves.append({
        "nombre": nombre,
        "huella": huella(llave),
        "creada": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    publicar("ANGABAVE_LLAVES", secreto_de_la_funcion(llaves))
    escribir(llaves, ruta)
    return llave


def quitar(nombre: str, *, ruta: Path = RUTA, publicar=_supabase_secreto) -> None:
    llaves = leer(ruta)
    quedan = [l for l in llaves if _clave(l["nombre"]) != _clave(nombre)]
    if len(quedan) == len(llaves):
        raise ErrorLlaves(f"No hay ningún enlace a nombre de {nombre!r}.")
    publicar("ANGABAVE_LLAVES", secreto_de_la_funcion(quedan))
    escribir(quedan, ruta)


def _contexto_ssl() -> ssl.SSLContext:
    """Certificados para hablar con GitHub, corra esto el Python que lo corra.

    El Python de python.org para Mac no trae certificados hasta que se corre su
    «Install Certificates.command»: sin ellos, toda conexión segura truena con
    CERTIFICATE_VERIFY_FAILED. Se usan los de certifi si está, y si no, los que
    trae macOS en /etc/ssl/cert.pem.
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    if Path("/etc/ssl/cert.pem").exists():
        return ssl.create_default_context(cafile="/etc/ssl/cert.pem")
    return ssl.create_default_context()


def _github(metodo: str, ruta: str, token: str) -> int:
    """Código de respuesta de GitHub. El token viaja en la cabecera, nunca en un comando."""
    peticion = urllib.request.Request(
        f"https://api.github.com{ruta}", method=metodo,
        headers={
            "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "angabave-llaves",
        },
    )
    try:
        with urllib.request.urlopen(peticion, timeout=20, context=_contexto_ssl()) as respuesta:
            return respuesta.status
    except urllib.error.HTTPError as error:
        return error.code
    except (urllib.error.URLError, OSError) as error:
        motivo = getattr(error, "reason", error)
        raise ErrorLlaves(f"No pude conectarme con GitHub ({motivo}). Revisa tu internet e intenta de nuevo.")


def revisar_token(valor: str, consultar=_github) -> None:
    """Comprueba que el token pueda correr workflows de angabave, y nada más hace falta.

    La prueba es una escritura inofensiva: "habilitar" el workflow de carga, que
    ya está habilitado. Si el token solo pudiera leer, aquí truena, y no el
    sábado en la noche con el organizador subiendo la quiniela.
    """
    if not valor.startswith("github_pat_"):
        raise ErrorLlaves("Ese no parece un token de GitHub de los nuevos (empiezan con github_pat_).")
    codigo = consultar("PUT", f"/repos/{REPO}/actions/workflows/cargar.yml/enable", valor)
    if codigo == 204:
        return
    if codigo == 401:
        raise ErrorLlaves("GitHub no reconoce ese token. ¿Se copió completo?")
    if codigo == 404:
        raise ErrorLlaves(
            f"El token no llega al repo {REPO}. En «Repository access» elige «Only select "
            "repositories» y marca angabave."
        )
    if codigo == 403:
        raise ErrorLlaves("El token llega al repo pero no puede correr workflows: dale Actions «Read and write».")
    raise ErrorLlaves(f"GitHub respondió {codigo}. Intenta de nuevo en unos minutos.")


def token() -> None:
    """Guarda en Supabase el token de GitHub con el que la función pide revisar cada carga."""
    print("Si todavía no tienes el token, créalo con este formulario (ya viene lleno):\n")
    print(f"  {FORMA_TOKEN}\n")
    print("Lo único que falta elegir: en «Repository access», «Only select repositories» → angabave.")
    print("Luego «Generate token» y cópialo.\n")
    print("Pega el token de GitHub (no se ve mientras lo pegas) y oprime Enter:")
    valor = getpass.getpass(prompt="").strip()
    revisar_token(valor)
    _supabase_secreto("ANGABAVE_GITHUB", valor)
    print("Listo: GitHub aceptó el token y quedó guardado en Supabase.")


def main(argumentos: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Enlaces personales para cargar la semana.")
    sub = parser.add_subparsers(dest="accion", required=True)
    sub.add_parser("nueva", help="crea un enlace e imprime la liga").add_argument("nombre")
    sub.add_parser("quitar", help="anula el enlace de alguien").add_argument("nombre")
    sub.add_parser("lista", help="quién tiene enlace")
    sub.add_parser("token", help="guarda el token de GitHub de la función (una vez)")
    opciones = parser.parse_args(argumentos)
    try:
        if opciones.accion == "nueva":
            llave = nueva(opciones.nombre)
            print(f"Enlace para {opciones.nombre}. Se muestra solo esta vez; mándaselo por privado:\n")
            print(f"  {enlace(llave)}\n")
            print("Quien tenga este enlace puede cargar la semana. Si se filtra: "
                  f'python3 herramientas/llaves.py quitar "{opciones.nombre}"')
        elif opciones.accion == "quitar":
            quitar(opciones.nombre)
            print(f"El enlace de {opciones.nombre} ya no sirve.")
        elif opciones.accion == "lista":
            llaves = leer()
            if not llaves:
                print("No hay enlaces.")
            for l in llaves:
                print(f"  {l['nombre']:<30} desde {l['creada'][:10]}")
        else:
            token()
    except ErrorLlaves as error:
        print(f"No se hizo nada: {error}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as error:
        print(f"No se hizo nada: Supabase no aceptó el cambio.\n{error.stderr}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
