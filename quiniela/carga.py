"""La puerta de entrada de los picks.

Recibe el archivo del organizador tal como llega —Excel o PDF, la semana
completa o una sola tanda— y lo deja guardado y sellado, o explica por qué no.
Lo usan igual el comando `importar` en la Mac y el workflow que atiende la
forma "Cargar semana" de GitHub: no hay dos caminos que se desalineen.

Qué se revisa, en este orden:

1. Que el archivo sea lo que dice ser: Excel o PDF de verdad, de tamaño
   razonable, sin contraseña y sin trampas al descomprimirlo.
2. Lo que ya revisa el lector: nombres y equipos válidos, nadie repetido, un
   pick por partido y siempre de uno de los dos equipos de ese partido.
3. De qué semana es. Manda la celda "Semana N"; el nombre del archivo es solo
   una pista para cotejar.
4. Que no se salte ninguna semana.
5. Que cada partido exista en el calendario de la NFL de esa semana, con el
   local y el visitante en su lugar.
6. Cómo encaja con lo que ya estaba: semana nueva, la tanda que faltaba, o la
   semana entera otra vez. Una hoja que repite parte de lo cargado y omite otra
   parte se rechaza: no hay forma segura de adivinar qué quiso decir.
7. Que no cambie ni un pick de un partido que ya empezó.

Nada se escribe hasta que todo cuadra. El archivo que se guarda lo escribe este
mismo módulo, en la rejilla de siempre, y lo vuelve a leer para comprobar que
dice exactamente lo mismo antes de ponerlo en su lugar.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .espn import ErrorESPN, Partido
from .picks import (
    RUTA_SELLOS,
    ErrorPicks,
    Hoja,
    PicksAlteradosError,
    archivos_por_semana,
    clave_participante,
    escribir_hoja,
    leer_hoja,
    semana_en_el_nombre,
    verificar_sello,
)
from .scoring import (
    SEMANAS_TEMPORADA,
    ErrorCalendario,
    alertar_nombres_parecidos,
    emparejar_resultados,
)

__all__ = [
    "ErrorCarga",
    "Resultado",
    "recibir",
    "revisar_archivo",
    "reporte_markdown",
    "reporte_texto",
    "TAMANO_MAXIMO",
]

_log = logging.getLogger(__name__)

#: Una quiniela con logos pesa unos 400 KB. Más de esto es otro archivo.
TAMANO_MAXIMO = 10 * 1024 * 1024
#: Un Excel es un zip. Esto frena uno fabricado para reventar la memoria al
#: descomprimirlo, antes de dárselo a openpyxl.
DESCOMPRIMIDO_MAXIMO = 100 * 1024 * 1024
ENTRADAS_MAXIMAS = 5000
EXTENSIONES_ACEPTADAS = (".xlsx", ".xlsm", ".pdf")
#: Cuántos cambios se detallan en el reporte antes de resumir el resto.
CAMBIOS_DETALLADOS = 25

SITIO = "https://vegeeks.github.io/angabave/"


class ErrorCarga(ErrorPicks):
    """El archivo no se puede cargar. El mensaje es para el organizador."""


@dataclass
class Resultado:
    """Qué pasó con un archivo, con lo necesario para contárselo a quien lo mandó."""

    aceptado: bool
    #: "nueva", "tanda", "reemplazo", "sin_cambios" o "rechazada".
    accion: str
    archivo: str
    semana: int | None = None
    partidos_hoja: int = 0
    participantes: int = 0
    #: Los que tiene la NFL esa semana.
    partidos_semana: int = 0
    #: Los que tiene la quiniela de esa semana después de la carga.
    partidos_cargados: int = 0
    cambios: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    error: str = ""
    destino: Path | None = None
    sellados: list[str] = field(default_factory=list)


# --- el archivo en sí ----------------------------------------------------------


def revisar_archivo(ruta: Path) -> None:
    """Comprueba que el archivo sea un Excel o un PDF de verdad y sano.

    Va antes que cualquier lector: un archivo con la extensión cambiada, con
    contraseña o hecho para reventar al descomprimirse no llega a openpyxl.
    """
    ruta = Path(ruta)
    extension = ruta.suffix.lower()
    if extension == ".xls":
        raise ErrorCarga(
            "Es un Excel del formato viejo (.xls). Ábrelo y guárdalo como libro de Excel (.xlsx)."
        )
    if extension not in EXTENSIONES_ACEPTADAS:
        raise ErrorCarga(f"{ruta.name} no es un Excel (.xlsx) ni un PDF.")

    tamano = ruta.stat().st_size
    if tamano == 0:
        raise ErrorCarga("El archivo llegó vacío.")
    if tamano > TAMANO_MAXIMO:
        raise ErrorCarga(
            f"El archivo pesa {tamano / 1024 / 1024:.1f} MB y una quiniela no pasa de 1 MB. "
            "¿Es el archivo correcto?"
        )

    with ruta.open("rb") as archivo:
        inicio = archivo.read(8)

    if extension == ".pdf":
        if not inicio.startswith(b"%PDF-"):
            raise ErrorCarga("El archivo dice ser PDF pero por dentro no lo es.")
        return

    if inicio.startswith(b"\xd0\xcf\x11\xe0"):
        # Contenedor OLE: así se ven los .xls viejos y los .xlsx con contraseña.
        raise ErrorCarga(
            "El Excel tiene contraseña o es del formato viejo. Guárdalo como .xlsx sin contraseña."
        )
    if not inicio.startswith(b"PK\x03\x04"):
        raise ErrorCarga("El archivo dice ser Excel pero por dentro no lo es.")
    try:
        with zipfile.ZipFile(ruta) as libro:
            entradas = libro.infolist()
            if len(entradas) > ENTRADAS_MAXIMAS:
                raise ErrorCarga("El Excel trae demasiadas piezas por dentro para ser una quiniela.")
            if sum(entrada.file_size for entrada in entradas) > DESCOMPRIMIDO_MAXIMO:
                raise ErrorCarga("El Excel descomprimido pesaría demasiado para ser una quiniela.")
            if "xl/workbook.xml" not in {entrada.filename for entrada in entradas}:
                raise ErrorCarga("El archivo es un .zip pero no un libro de Excel.")
            dañada = libro.testzip()
            if dañada is not None:
                raise ErrorCarga(f"El Excel está dañado ({dañada}). Vuelve a guardarlo.")
    except zipfile.BadZipFile as error:
        raise ErrorCarga("El Excel está dañado. Vuelve a guardarlo o expórtalo de nuevo.") from error


# --- recibir -------------------------------------------------------------------


def recibir(
    ruta: Path,
    *,
    calendario: Callable[[int], list[Partido]],
    dir_picks: Path,
    semana: int | None = None,
    ruta_sellos: Path = RUTA_SELLOS,
    ahora: datetime | None = None,
    escribir: bool = True,
) -> Resultado:
    """Revisa el archivo completo y, si todo cuadra, lo guarda y lo sella.

    `calendario(n)` devuelve los partidos de la NFL de la semana n, con horario
    y estado. `semana` es la que declara quien lo manda, si declara alguna.
    Con `escribir=False` solo revisa: no toca ni los picks ni los sellos.

    Nunca lanza por un problema del archivo: lo devuelve en el resultado, con
    un mensaje que se le puede enseñar tal cual al organizador.
    """
    ruta = Path(ruta)
    try:
        return _recibir(
            ruta,
            calendario=calendario,
            dir_picks=Path(dir_picks),
            semana_declarada=semana,
            ruta_sellos=Path(ruta_sellos),
            ahora=ahora or datetime.now(timezone.utc),
            escribir=escribir,
        )
    except (ErrorPicks, ErrorCalendario) as error:
        return Resultado(
            aceptado=False, accion="rechazada", archivo=ruta.name, error=str(error).strip()
        )


class _Avisos(logging.Handler):
    """Junta las advertencias del lector para ponerlas en el reporte."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.mensajes: list[str] = []

    def emit(self, registro: logging.LogRecord) -> None:
        self.mensajes.append(registro.getMessage())


def _leer_con_avisos(ruta: Path) -> tuple[Hoja, list[str]]:
    avisos = _Avisos()
    raiz = logging.getLogger("quiniela")
    raiz.addHandler(avisos)
    try:
        return leer_hoja(ruta), avisos.mensajes
    finally:
        raiz.removeHandler(avisos)


def _recibir(
    ruta: Path,
    *,
    calendario: Callable[[int], list[Partido]],
    dir_picks: Path,
    semana_declarada: int | None,
    ruta_sellos: Path,
    ahora: datetime,
    escribir: bool,
) -> Resultado:
    revisar_archivo(ruta)
    hoja, avisos = _leer_con_avisos(ruta)

    numero = _semana(hoja, ruta.name, semana_declarada, avisos)
    guardadas = archivos_por_semana(dir_picks)
    ultima = max(guardadas, default=0)
    if numero > ultima + 1:
        raise ErrorCarga(
            f"Es la semana {numero}, pero la última cargada es la {ultima}: falta la "
            f"{ultima + 1}. Si de verdad no hubo quiniela esa semana, avísale a Angel."
        )

    try:
        resultados = calendario(numero)
    except ErrorESPN as error:
        raise ErrorCarga(
            "No pude consultar el calendario de la NFL para comprobar los partidos "
            "(ESPN no respondió). Vuelve a intentarlo en unos minutos."
        ) from error
    emparejar_resultados(hoja.partidos, resultados)
    reales = {partido.clave: partido for partido in resultados}
    arrancados = {
        partido.clave
        for partido in resultados
        if partido.finalizado or (partido.inicio is not None and partido.inicio <= ahora)
    }

    rutas_de_la_semana = guardadas.get(numero, [])
    actual = _leer_guardada(rutas_de_la_semana[0], numero) if rutas_de_la_semana else None
    accion, partidos, picks = _combinar(actual, hoja, avisos)
    partidos, picks = _en_orden_nfl(partidos, picks, reales)

    resultado = Resultado(
        aceptado=True,
        accion=accion,
        archivo=ruta.name,
        semana=numero,
        partidos_hoja=len(hoja.partidos),
        participantes=len(picks),
        partidos_semana=len(resultados),
        partidos_cargados=len(partidos),
        avisos=avisos,
    )

    if actual is not None:
        _proteger_arrancados(actual, partidos, picks, arrancados)
        if _mapa(actual.partidos, actual.picks) == _mapa(partidos, picks):
            resultado.accion = "sin_cambios"
            resultado.destino = rutas_de_la_semana[0]
            return resultado
        resultado.cambios = _cambios(actual, partidos, picks)

    ya_empezados = sorted(
        clave for clave in {p.clave for p in hoja.partidos} & arrancados
        if actual is None or clave not in {p.clave for p in actual.partidos}
    )
    if ya_empezados:
        resultado.avisos.append(
            "Cuando llegó la hoja ya habían empezado " + ", ".join(ya_empezados)
            + ": sus picks quedan sellados tal como vienen."
        )
    resultado.avisos.extend(_avisos_de_nombres(guardadas, numero, picks))

    if not escribir:
        _probar_sello(partidos, picks, numero, arrancados, ruta_sellos)
        return resultado

    destino, sellados = _guardar(
        partidos, picks, numero, arrancados, dir_picks, rutas_de_la_semana, ruta_sellos
    )
    resultado.destino = destino
    resultado.sellados = sorted(sellados)
    return resultado


def _semana(hoja: Hoja, nombre: str, declarada: int | None, avisos: list[str]) -> int:
    """La semana del archivo: manda la hoja, y lo declarado tiene que coincidir."""
    pista = semana_en_el_nombre(nombre)
    if hoja.semana is not None and declarada is not None and hoja.semana != declarada:
        raise ErrorCarga(
            f"Dijiste que es la semana {declarada}, pero la hoja dice 'Semana {hoja.semana}'."
        )
    numero = hoja.semana if hoja.semana is not None else declarada
    if numero is None:
        numero = pista
    if numero is None:
        raise ErrorCarga(
            "No sé de qué semana es: la hoja no dice 'Semana N' en la columna A y el nombre "
            "del archivo tampoco trae el número. Ponlo en la celda A2, como siempre."
        )
    if pista is not None and pista != numero:
        avisos.append(
            f"El archivo se llama {nombre!r}, que suena a la semana {pista}, pero la hoja dice "
            f"'Semana {numero}'. Usé la hoja, y sus partidos sí son de la semana {numero}."
        )
    if not 1 <= numero <= SEMANAS_TEMPORADA:
        raise ErrorCarga(
            f"La hoja dice 'Semana {numero}', y la temporada va de la 1 a la {SEMANAS_TEMPORADA}."
        )
    return numero


def _leer_guardada(ruta: Path, numero: int) -> Hoja:
    try:
        return leer_hoja(ruta)
    except ErrorPicks as error:
        raise ErrorCarga(
            f"El archivo que ya estaba guardado para la semana {numero} ({ruta.name}) no se "
            f"puede leer, así que no puedo comprobar qué cambia. Avísale a Angel. Detalle: {error}"
        ) from error


def _combinar(
    actual: Hoja | None, hoja: Hoja, avisos: list[str]
) -> tuple[str, list[Partido], dict[str, list[str]]]:
    """Decide cómo entra la hoja: semana nueva, tanda nueva o semana otra vez."""
    if actual is None:
        return "nueva", list(hoja.partidos), dict(hoja.picks)

    antes = {partido.clave for partido in actual.partidos}
    ahora = {partido.clave for partido in hoja.partidos}
    if ahora >= antes:
        return "reemplazo", list(hoja.partidos), dict(hoja.picks)
    if not ahora & antes:
        return ("tanda", *_juntar(actual, hoja, avisos))

    faltan = sorted(antes - ahora)
    raise ErrorCarga(
        f"La hoja repite {len(ahora & antes)} partido(s) que ya estaban cargados, pero le "
        f"faltan otros {len(faltan)} que también estaban ({', '.join(faltan)}). Manda la semana "
        "completa, o solo la tanda que falta."
    )


def _juntar(
    actual: Hoja, hoja: Hoja, avisos: list[str]
) -> tuple[list[Partido], dict[str, list[str]]]:
    """Pega una tanda nueva a la que ya estaba. Los participantes deben ser los mismos."""
    antes = {clave_participante(nombre): nombre for nombre in actual.picks}
    ahora = {clave_participante(nombre): nombre for nombre in hoja.picks}
    if set(antes) != set(ahora):
        partes = ["Para juntar esta tanda con la que ya estaba, los participantes tienen que ser los mismos."]
        solo_antes = sorted(antes[c] for c in set(antes) - set(ahora))
        solo_ahora = sorted(ahora[c] for c in set(ahora) - set(antes))
        if solo_antes:
            partes.append(f"No vienen en esta hoja: {', '.join(solo_antes)}.")
        if solo_ahora:
            partes.append(f"Vienen en esta hoja pero no en la anterior: {', '.join(solo_ahora)}.")
        raise ErrorCarga(" ".join(partes))

    picks: dict[str, list[str]] = {}
    for clave, nombre in ahora.items():
        if antes[clave] != nombre:
            avisos.append(f"{antes[clave]!r} ahora viene escrito {nombre!r}; me quedo con lo nuevo.")
        picks[nombre] = actual.picks[antes[clave]] + hoja.picks[nombre]
    return list(actual.partidos) + list(hoja.partidos), picks


def _en_orden_nfl(
    partidos: list[Partido], picks: dict[str, list[str]], reales: dict[str, Partido]
) -> tuple[list[Partido], dict[str, list[str]]]:
    """Ordena por hora de inicio, moviendo cada columna de picks con su partido."""
    def inicio(indice: int) -> float:
        real = reales.get(partidos[indice].clave)
        return real.inicio.timestamp() if real and real.inicio else float("inf")

    orden = sorted(range(len(partidos)), key=lambda i: (inicio(i), i))
    return (
        [partidos[i] for i in orden],
        {nombre: [elegidos[i] for i in orden] for nombre, elegidos in picks.items()},
    )


def _mapa(partidos: list[Partido], picks: dict[str, list[str]]) -> dict[str, dict[str, str]]:
    """Participante -> partido -> pick, sin importar el orden de filas ni columnas."""
    return {
        nombre: {partido.clave: elegido for partido, elegido in zip(partidos, elegidos)}
        for nombre, elegidos in picks.items()
    }


def _por_partido(
    partidos: list[Partido], picks: dict[str, list[str]]
) -> dict[str, dict[str, str]]:
    """Partido -> participante (sin acentos) -> pick."""
    return {
        partido.clave: {
            clave_participante(nombre): elegidos[indice] for nombre, elegidos in picks.items()
        }
        for indice, partido in enumerate(partidos)
    }


def _proteger_arrancados(
    actual: Hoja, partidos: list[Partido], picks: dict[str, list[str]], arrancados: set[str]
) -> None:
    """Ningún pick de un partido que ya empezó puede cambiar, aparecer ni desaparecer.

    Se compara contra lo publicado, no solo contra el sello: así la protección
    vale también para un partido que arrancó entre dos corridas del sitio.
    """
    antes = _por_partido(actual.partidos, actual.picks)
    despues = _por_partido(partidos, picks)
    nombres = {clave_participante(n): n for n in list(actual.picks) + list(picks)}
    for partido in sorted(arrancados & set(antes)):
        if partido not in despues:
            raise PicksAlteradosError(
                f"El partido {partido} ya empezó y la hoja nueva no lo trae. Los picks de un "
                "partido que ya arrancó no se pueden quitar."
            )
        tocados = sorted(
            nombres[c] for c in set(antes[partido]) | set(despues[partido])
            if antes[partido].get(c) != despues[partido].get(c)
        )
        if tocados:
            raise PicksAlteradosError(
                f"El partido {partido} ya empezó y la hoja nueva le cambia el pick a: "
                f"{', '.join(tocados)}. Los picks de un partido que ya arrancó no se pueden "
                "cambiar. Si fue un error de captura de antes, avísale a Angel."
            )


def _cambios(actual: Hoja, partidos: list[Partido], picks: dict[str, list[str]]) -> list[str]:
    """Lo que cambia respecto a lo guardado, en frases cortas."""
    cambios: list[str] = []
    antes_p = {clave_participante(n): n for n in actual.picks}
    ahora_p = {clave_participante(n): n for n in picks}
    for clave in sorted(set(ahora_p) - set(antes_p)):
        cambios.append(f"Entra {ahora_p[clave]}.")
    for clave in sorted(set(antes_p) - set(ahora_p)):
        cambios.append(f"Sale {antes_p[clave]}.")
    for clave in sorted(set(antes_p) & set(ahora_p)):
        if antes_p[clave] != ahora_p[clave]:
            cambios.append(f"{antes_p[clave]} ahora se escribe {ahora_p[clave]}.")

    antes_j = {p.clave for p in actual.partidos}
    nuevos = [p.clave for p in partidos if p.clave not in antes_j]
    if nuevos:
        cambios.append(f"Se agregan {len(nuevos)} partido(s): {', '.join(nuevos)}.")

    antes = _por_partido(actual.partidos, actual.picks)
    despues = _por_partido(partidos, picks)
    detalle: list[str] = []
    for partido in partidos:
        if partido.clave not in antes:
            continue
        for clave in sorted(set(antes[partido.clave]) & set(despues[partido.clave])):
            viejo, nuevo = antes[partido.clave][clave], despues[partido.clave][clave]
            if viejo != nuevo:
                detalle.append(f"{partido.clave}: {ahora_p[clave]} cambia {viejo} → {nuevo}.")
    if len(detalle) > CAMBIOS_DETALLADOS:
        sobran = len(detalle) - CAMBIOS_DETALLADOS
        detalle = detalle[:CAMBIOS_DETALLADOS] + [f"… y {sobran} pick(s) más."]
    return cambios + detalle


def _avisos_de_nombres(
    guardadas: dict[int, list[Path]], numero: int, picks: dict[str, list[str]]
) -> list[str]:
    """Nombres nuevos, ausentes o sospechosamente parecidos a los de otras semanas."""
    avisos: list[str] = []
    claves: dict[str, str] = {}
    semanas_por_clave: dict[str, set[int]] = {}
    anteriores: dict[str, str] = {}
    for otra, rutas in guardadas.items():
        if otra == numero:
            continue
        try:
            hoja = leer_hoja(rutas[0])
        except ErrorPicks:
            continue  # la semana guardada tiene su propio problema; no es de esta carga
        for nombre in hoja.picks:
            clave = clave_participante(nombre)
            claves.setdefault(clave, nombre)
            semanas_por_clave.setdefault(clave, set()).add(otra)
            if otra == numero - 1:
                anteriores[clave] = nombre

    actuales = {clave_participante(nombre): nombre for nombre in picks}
    for clave, nombre in actuales.items():
        claves[clave] = nombre
        semanas_por_clave.setdefault(clave, set()).add(numero)

    if anteriores:
        nuevos = sorted(actuales[c] for c in set(actuales) - set(anteriores))
        ausentes = sorted(anteriores[c] for c in set(anteriores) - set(actuales))
        if nuevos:
            avisos.append(f"No estaban en la semana {numero - 1}: {', '.join(nuevos)}.")
        if ausentes:
            avisos.append(f"Estaban en la semana {numero - 1} y aquí no vienen: {', '.join(ausentes)}.")

    pares = alertar_nombres_parecidos(claves, semanas_por_clave, registrar=False)
    esta_semana = set(actuales.values())
    for una, otra in pares:
        if una in esta_semana or otra in esta_semana:
            avisos.append(
                f"{una!r} y {otra!r} se parecen mucho. Si son la misma persona mal escrita, "
                "su temporada se contaría por separado."
            )
    return avisos


def _probar_sello(
    partidos: list[Partido],
    picks: dict[str, list[str]],
    numero: int,
    arrancados: set[str],
    ruta_sellos: Path,
) -> None:
    """Pasa la hoja por los sellos guardados sin tocar los de verdad."""
    with tempfile.TemporaryDirectory() as carpeta:
        prueba = Path(carpeta) / f"Semana_{numero:02d}.xlsx"
        copia = Path(carpeta) / "sellos.json"
        if ruta_sellos.exists():
            shutil.copy2(ruta_sellos, copia)
        escribir_hoja(prueba, numero, partidos, picks)
        verificar_sello(prueba, numero, arrancados, copia)


def _guardar(
    partidos: list[Partido],
    picks: dict[str, list[str]],
    numero: int,
    arrancados: set[str],
    dir_picks: Path,
    anteriores: list[Path],
    ruta_sellos: Path,
) -> tuple[Path, set[str]]:
    """Escribe, comprueba, sella y deja un solo archivo para la semana."""
    dir_picks.mkdir(parents=True, exist_ok=True)
    destino = dir_picks / f"Semana_{numero:02d}.xlsx"
    # Empieza con punto para que nadie lo tome por una semana mientras existe, y
    # termina en .xlsx porque el lector decide el formato por la extensión.
    temporal = dir_picks / f".Semana_{numero:02d}.nuevo.xlsx"
    try:
        escribir_hoja(temporal, numero, partidos, picks)
        releida = leer_hoja(temporal)
        if releida.semana != numero or _mapa(releida.partidos, releida.picks) != _mapa(partidos, picks):
            raise RuntimeError(
                f"La hoja que escribí para la semana {numero} no dice lo mismo al releerla."
            )
        _probar_sello(partidos, picks, numero, arrancados, ruta_sellos)
        os.replace(temporal, destino)
    finally:
        temporal.unlink(missing_ok=True)

    for ruta in anteriores:
        if ruta.resolve() != destino.resolve():
            ruta.unlink(missing_ok=True)
            _log.info("Quité %s: la semana %d queda en %s.", ruta.name, numero, destino.name)
    sellados = verificar_sello(destino, numero, arrancados, ruta_sellos)
    return destino, sellados


# --- reportes ------------------------------------------------------------------


_TITULOS = {
    "nueva": "Semana {n} cargada",
    "tanda": "Semana {n}: se agregó la tanda",
    "reemplazo": "Semana {n} actualizada",
    "sin_cambios": "Semana {n}: ya estaba igual",
}


def _faltantes(resultado: Resultado) -> str:
    faltan = resultado.partidos_semana - resultado.partidos_cargados
    if faltan <= 0:
        return ""
    return (
        f"Faltan {faltan} partido(s) de la semana: entran cuando llegue la hoja de esa tanda. "
        "Mientras, el portal sigue ofreciendo el generador de picks para esos partidos."
    )


def reporte_markdown(resultado: Resultado, *, forma: str = "") -> str:
    """El reporte que se contesta en el hilo de GitHub."""
    if not resultado.aceptado:
        semana = f" la semana {resultado.semana}" if resultado.semana else ""
        lineas = [
            f"### ❌ No se cargó{semana}",
            "",
            *[f"> {linea}" if linea else ">" for linea in resultado.error.splitlines()],
            "",
            "No se tocó nada: el portal sigue exactamente como estaba.",
        ]
        if forma:
            lineas.append(f"Corrige el archivo y vuelve a subirlo aquí: {forma}")
        if resultado.avisos:
            lineas += ["", "**Además:**", *[f"- {aviso}" for aviso in resultado.avisos]]
        return "\n".join(lineas) + "\n"

    titulo = _TITULOS[resultado.accion].format(n=resultado.semana)
    lineas = [f"### ✅ {titulo}", ""]
    if resultado.accion == "sin_cambios":
        lineas.append(
            f"El archivo dice exactamente lo mismo que ya estaba publicado "
            f"({resultado.participantes} participantes, {resultado.partidos_cargados} partidos). "
            "No hubo nada que cambiar."
        )
    else:
        lineas += [
            "| | |",
            "|---|---|",
            f"| Archivo | {resultado.archivo} |",
            f"| Participantes | {resultado.participantes} |",
            f"| Partidos en la hoja | {resultado.partidos_hoja} |",
            f"| Partidos de la semana cargados | {resultado.partidos_cargados} de {resultado.partidos_semana} |",
        ]
        if resultado.sellados:
            lineas.append(f"| Sellados porque ya empezaron | {len(resultado.sellados)} |")
    if resultado.cambios:
        lineas += ["", "**Qué cambió:**", *[f"- {cambio}" for cambio in resultado.cambios]]
    faltan = _faltantes(resultado)
    if faltan:
        lineas += ["", faltan]
    if resultado.avisos:
        lineas += ["", "**Para revisar:**", *[f"- {aviso}" for aviso in resultado.avisos]]
    if resultado.accion != "sin_cambios":
        lineas += ["", f"En un par de minutos se ve en el portal: {SITIO}"]
    return "\n".join(lineas) + "\n"


def reporte_texto(resultado: Resultado) -> str:
    """El mismo reporte, para la terminal."""
    if not resultado.aceptado:
        texto = ["No se cargó el archivo " + resultado.archivo + ":", resultado.error]
    elif resultado.accion == "sin_cambios":
        texto = [f"Semana {resultado.semana}: el archivo coincide con lo guardado. Sin cambios."]
    else:
        texto = [
            _TITULOS[resultado.accion].format(n=resultado.semana)
            + f": {resultado.participantes} participantes, "
            f"{resultado.partidos_cargados} de {resultado.partidos_semana} partidos"
            + (f" → {resultado.destino}" if resultado.destino else " (solo revisión).")
        ]
        texto += [f"  · {cambio}" for cambio in resultado.cambios]
        faltan = _faltantes(resultado)
        if faltan:
            texto.append(faltan)
    texto += [f"Aviso: {aviso}" for aviso in resultado.avisos]
    return "\n".join(texto)
