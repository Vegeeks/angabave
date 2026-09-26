"""La forma "Cargar semana" de GitHub: quién la manda y qué adjuntó.

El workflow nunca pega el texto del hilo en un comando de la terminal. Lo lee
de aquí, del archivo del evento, y lo trata como lo que es: texto que escribió
alguien más. Del hilo se toman solo dos cosas, y las dos se revisan:

* quién lo abrió, por su número de cuenta, que no cambia aunque la persona
  cambie su nombre de usuario ni lo puede reclamar otro;
* el enlace del archivo adjunto, que tiene que ser uno solo y de GitHub.

Todo lo demás que diga el hilo se ignora.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import requests

from .carga import TAMANO_MAXIMO

__all__ = [
    "ErrorBuzon",
    "NoAutorizado",
    "Solicitud",
    "RUTA_CARGADORES",
    "cargadores",
    "leer_solicitud",
    "descargar",
    "reporte_rechazo",
]

RAIZ = Path(__file__).resolve().parents[1]
#: Las cuentas de GitHub que pueden cargar semanas.
RUTA_CARGADORES = RAIZ / "data" / "cargadores.json"

#: Así enlaza GitHub un archivo adjunto a un hilo. El segundo es el formato viejo.
_RE_ADJUNTOS = (
    re.compile(r"https://github\.com/user-attachments/files/\d+/[^\s()\[\]<>\"'`]+"),
    re.compile(r"https://github\.com/[A-Za-z0-9-]+/[A-Za-z0-9._-]+/files/\d+/[^\s()\[\]<>\"'`]+"),
)
_EXTENSIONES = (".xlsx", ".xlsm", ".pdf", ".xls")
_RE_HOST_S3 = re.compile(r"^github-production-[a-z0-9-]+\.s3\.amazonaws\.com$")
_REDIRECCIONES_MAXIMAS = 4
_ESPERA = 30


class ErrorBuzon(ValueError):
    """La solicitud no se puede atender. El mensaje es para quien la mandó."""


class NoAutorizado(ErrorBuzon):
    """Quien abrió el hilo no está en la lista de cargadores."""


@dataclass(frozen=True, slots=True)
class Solicitud:
    numero: int
    usuario: str
    cuenta: int
    enlace: str
    #: El nombre del archivo, ya limpio para usarlo en disco.
    nombre: str


def cargadores(ruta: Path = RUTA_CARGADORES) -> dict[int, str]:
    """Número de cuenta -> usuario. Si la lista no se puede leer, nadie carga."""
    try:
        datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
        cuentas = datos["cuentas"]
        autorizados: dict[int, str] = {}
        for cuenta in cuentas:
            numero = cuenta["id"]
            if not isinstance(numero, int) or isinstance(numero, bool) or numero <= 0:
                raise ValueError(f"id inválido: {numero!r}")
            if numero in autorizados:
                raise ValueError(f"id repetido: {numero}")
            autorizados[numero] = str(cuenta["usuario"])
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise RuntimeError(f"La lista de cargadores {ruta} no se puede usar: {error}") from error
    return autorizados


def leer_solicitud(evento: dict, autorizados: dict[int, str]) -> Solicitud:
    """Saca del evento de GitHub quién pide cargar y qué archivo adjuntó."""
    hilo = evento["issue"]
    autor = hilo["user"]
    usuario, cuenta = str(autor["login"]), autor["id"]
    if cuenta not in autorizados:
        raise NoAutorizado(
            f"@{usuario} no está en la lista de cuentas que pueden cargar la quiniela. Si eres "
            "quien la organiza, pídele a Angel que te agregue."
        )

    cuerpo = hilo.get("body") or ""
    enlaces = []
    for patron in _RE_ADJUNTOS:
        for enlace in patron.findall(cuerpo):
            if enlace not in enlaces:
                enlaces.append(enlace)
    if not enlaces:
        raise ErrorBuzon(
            "El hilo no trae ningún archivo adjunto. Vuelve a abrir la forma y arrastra el "
            "Excel o el PDF al recuadro; espera a que termine de subir antes de enviar."
        )
    if len(enlaces) > 1:
        raise ErrorBuzon(
            f"El hilo trae {len(enlaces)} archivos adjuntos. Manda uno por vez, cada uno en su "
            "propia forma."
        )

    enlace = enlaces[0]
    nombre = _nombre_limpio(unquote(urlparse(enlace).path.rsplit("/", 1)[-1]))
    if not nombre.lower().endswith(_EXTENSIONES):
        raise ErrorBuzon(
            f"El archivo adjunto es {nombre!r} y tiene que ser un Excel (.xlsx) o un PDF."
        )
    return Solicitud(int(hilo["number"]), usuario, int(cuenta), enlace, nombre)


def _nombre_limpio(nombre: str) -> str:
    """Solo letras, números, punto, guion y guion bajo: el nombre toca el disco."""
    limpio = re.sub(r"[^A-Za-z0-9._-]", "_", nombre).lstrip(".")
    base, punto, extension = limpio.rpartition(".")
    if not punto:
        return limpio[:100] or "archivo"
    return f"{base[:90] or 'archivo'}.{extension[:10]}"


def _host_permitido(url: str) -> bool:
    partes = urlparse(url)
    host = (partes.hostname or "").lower()
    return partes.scheme == "https" and (
        host == "github.com"
        or host.endswith(".githubusercontent.com")
        or bool(_RE_HOST_S3.match(host))
    )


def descargar(solicitud: Solicitud, carpeta: Path, *, sesion=None) -> Path:
    """Baja el adjunto sin salirse de los servidores de GitHub y con tope de tamaño.

    Las redirecciones se siguen a mano para revisar cada destino antes de
    pedirlo, y el archivo se corta en cuanto pasa del tope, diga lo que diga la
    cabecera.
    """
    sesion = sesion or requests.Session()
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / solicitud.nombre

    url = solicitud.enlace
    for _ in range(_REDIRECCIONES_MAXIMAS + 1):
        if not _host_permitido(url):
            raise ErrorBuzon("El enlace del archivo no lleva a los servidores de GitHub.")
        try:
            respuesta = sesion.get(url, stream=True, timeout=_ESPERA, allow_redirects=False)
        except requests.RequestException as error:
            raise ErrorBuzon(
                "No pude descargar el archivo de GitHub. Vuelve a intentarlo en unos minutos."
            ) from error
        if respuesta.status_code in (301, 302, 303, 307, 308):
            siguiente = respuesta.headers.get("Location", "")
            respuesta.close()
            url = urljoin(url, siguiente)
            continue
        break
    else:
        raise ErrorBuzon("El enlace del archivo da demasiadas vueltas; vuelve a adjuntarlo.")

    with respuesta:
        if respuesta.status_code != 200:
            raise ErrorBuzon(
                f"No pude descargar el archivo (GitHub respondió {respuesta.status_code}). "
                "Vuelve a adjuntarlo."
            )
        declarado = int(respuesta.headers.get("Content-Length") or 0)
        if declarado > TAMANO_MAXIMO:
            raise ErrorBuzon("El archivo es demasiado grande para ser una quiniela.")
        total = 0
        with destino.open("wb") as salida:
            for trozo in respuesta.iter_content(64 * 1024):
                total += len(trozo)
                if total > TAMANO_MAXIMO:
                    salida.close()
                    destino.unlink(missing_ok=True)
                    raise ErrorBuzon("El archivo es demasiado grande para ser una quiniela.")
                salida.write(trozo)
    return destino


def reporte_rechazo(error: ErrorBuzon, *, forma: str = "") -> str:
    """Lo que se contesta cuando el hilo no llega ni a revisarse."""
    if isinstance(error, NoAutorizado):
        return f"### ⛔ Esta cuenta no puede cargar semanas\n\n{error}\n"
    lineas = ["### ❌ No se cargó nada", "", str(error), ""]
    if forma:
        lineas.append(f"Vuelve a intentarlo aquí: {forma}")
    return "\n".join(lineas) + "\n"
