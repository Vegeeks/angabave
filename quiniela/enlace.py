"""El lado del workflow del buzón por enlace.

Quien carga la semana sin cuenta de GitHub usa un enlace personal. La función
`angabave-carga` de Supabase recibe su archivo, lo guarda en una cubeta privada
y le pide a GitHub que corra el workflow de carga. Desde ahí, este módulo baja
el archivo y le devuelve a la función el resultado, que es lo que ve la página.

Las dos cosas van con un secreto que solo conocen la función y el workflow
(`ANGABAVE_SECRETO`). La carga llega como "prefijo/id" y se revisa su forma
antes de usarla: la escribe la función, pero viaja por GitHub.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import unquote

import requests

from .buzon import _nombre_limpio
from .carga import TAMANO_MAXIMO

__all__ = ["URL_FUNCION", "ErrorEnlace", "bajar", "contestar", "ESTADOS"]

#: La función que recibe los archivos del enlace. No es secreta: la puerta es la llave.
URL_FUNCION = "https://hxaajhsizdnlismnelqu.supabase.co/functions/v1/angabave-carga"
ESTADOS = ("listo", "rechazado", "falla")
_RE_CARGA = re.compile(r"^[0-9a-f]{16}/\d{8}T\d{6}-[0-9a-f]{8}$")
_ESPERA = 30


class ErrorEnlace(RuntimeError):
    """No se pudo hablar con la función del enlace."""


def _revisar(carga: str, secreto: str) -> None:
    if not _RE_CARGA.match(carga or ""):
        raise ErrorEnlace(f"La carga {carga!r} no tiene la forma esperada.")
    if not secreto:
        raise ErrorEnlace("Falta ANGABAVE_SECRETO: sin él la función no deja bajar ni contestar.")


def bajar(
    carga: str, carpeta: Path, *, secreto: str, url: str = URL_FUNCION, sesion=None
) -> tuple[Path, str]:
    """Baja el archivo de una carga. Devuelve su ruta y quién lo subió."""
    _revisar(carga, secreto)
    sesion = sesion or requests.Session()
    try:
        respuesta = sesion.get(
            url, params={"que": "archivo", "carga": carga}, headers={"x-secreto": secreto},
            timeout=_ESPERA, stream=True,
        )
    except requests.RequestException as error:
        raise ErrorEnlace(f"No pude hablar con la función del enlace: {error}") from error

    with respuesta:
        if respuesta.status_code != 200:
            raise ErrorEnlace(f"La función del enlace respondió {respuesta.status_code} al bajar {carga}.")
        nombre = _nombre_limpio(respuesta.headers.get("X-Archivo") or "archivo")
        cargador = " ".join(unquote(respuesta.headers.get("X-Cargador") or "").split())[:60]
        carpeta = Path(carpeta)
        carpeta.mkdir(parents=True, exist_ok=True)
        destino = carpeta / nombre
        total = 0
        with destino.open("wb") as salida:
            for trozo in respuesta.iter_content(64 * 1024):
                total += len(trozo)
                if total > TAMANO_MAXIMO:
                    salida.close()
                    destino.unlink(missing_ok=True)
                    raise ErrorEnlace("El archivo de la carga pasa del tamaño máximo.")
                salida.write(trozo)
    return destino, cargador or "sin nombre"


def contestar(
    carga: str, estado: str, resultado: dict | None, *, secreto: str, url: str = URL_FUNCION,
    sesion=None,
) -> None:
    """Le deja a la función el resultado de una carga, que es lo que ve la página."""
    _revisar(carga, secreto)
    if estado not in ESTADOS:
        raise ErrorEnlace(f"Estado {estado!r} inválido; va uno de {', '.join(ESTADOS)}.")
    sesion = sesion or requests.Session()
    try:
        respuesta = sesion.post(
            url, params={"que": "resultado", "carga": carga},
            headers={"x-secreto": secreto, "Content-Type": "application/json"},
            data=json.dumps({"estado": estado, "resultado": resultado}, ensure_ascii=False).encode("utf-8"),
            timeout=_ESPERA,
        )
    except requests.RequestException as error:
        raise ErrorEnlace(f"No pude hablar con la función del enlace: {error}") from error
    if respuesta.status_code != 200:
        raise ErrorEnlace(f"La función del enlace respondió {respuesta.status_code} al contestar {carga}.")
